import json
import logging
from decimal import Decimal
from datetime import timedelta
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
import asyncio
from asgiref.sync import sync_to_async
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone, translation
from django.db import transaction
from django.db.models import Sum, Count, F, Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.cache import cache

from apps.tenants.helpers import get_active_tenant, get_active_branch
from apps.accounts.helpers import user_has_perm, _get_client_ip
from apps.orders.models import Order, OrderItem, Customer
from apps.tenants.models import Tenant, Branch, DeliveryArea
from apps.menu.models import MenuItem, MenuCategory, MenuItemVariant, BranchMenuAvailability, BranchVariantPrice
from apps.accounts.models import Employee
from apps.audit.models import log_audit_event
from apps.kitchen.events import notify_kitchen_order_event
from apps.orders.events import (
    delivery_broadcaster,
    notify_delivery_order_event,
    serialize_delivery_order,
)

logger = logging.getLogger(__name__)

def branch_orders_view(request):
    if not (user_has_perm(request.user, "branch_view_orders") or user_has_perm(request.user, "view_orders")):
        return HttpResponseForbidden("غير مصرح لك باستعراض سجل طلبات الفرع")

    tenant = get_active_tenant(request)
    branch = get_active_branch(request)
    status_filter = request.GET.get("status", "all")
    type_filter = request.GET.get("type", "all")
    pay_method_filter = request.GET.get("pay_method", "all")
    date_filter = request.GET.get("date", "all")
    search = request.GET.get("q", "").strip()

    orders_base = Order.objects.filter(tenant=tenant) if tenant else Order.objects.none()
    if branch:
        orders_base = orders_base.filter(branch=branch)

    orders = orders_base.select_related("branch", "customer", "driver").prefetch_related("items__menu_item").order_by("-created_at", "-id")

    if status_filter != "all" and status_filter:
        if status_filter == "pending":
            orders = orders.filter(status__in=["new", "preparing", "ready", "out_for_delivery"])
        else:
            orders = orders.filter(status=status_filter)

    if type_filter != "all" and type_filter:
        orders = orders.filter(order_type=type_filter)

    if pay_method_filter != "all" and pay_method_filter:
        orders = orders.filter(pay_method=pay_method_filter)

    now = timezone.now()
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if date_filter == "today":
        orders = orders.filter(created_at__gte=start_of_today)
    elif date_filter == "yesterday":
        yesterday_start = start_of_today - timedelta(days=1)
        orders = orders.filter(created_at__gte=yesterday_start, created_at__lt=start_of_today)
    elif date_filter == "week":
        seven_days_ago = start_of_today - timedelta(days=6)
        orders = orders.filter(created_at__gte=seven_days_ago)
    elif date_filter == "month":
        thirty_days_ago = start_of_today - timedelta(days=29)
        orders = orders.filter(created_at__gte=thirty_days_ago)

    if search:
        orders = orders.filter(
            Q(order_number__icontains=search) |
            Q(customer_name__icontains=search) |
            Q(customer_phone__icontains=search) |
            Q(cashier__icontains=search)
        )

    # Summary metrics in a single optimized aggregation query
    metrics = orders.aggregate(
        total_orders=Count("id"),
        total_revenue=Sum("total", filter=~Q(status="cancelled")),
        pending_orders=Count("id", filter=Q(status__in=["new", "preparing", "ready", "out_for_delivery"])),
        delivered_orders=Count("id", filter=Q(status="delivered")),
        cancelled_orders=Count("id", filter=Q(status="cancelled")),
    )
    total_orders = metrics["total_orders"] or 0
    total_revenue = metrics["total_revenue"] or Decimal("0")
    pending_orders = metrics["pending_orders"] or 0
    delivered_orders = metrics["delivered_orders"] or 0
    cancelled_orders = metrics["cancelled_orders"] or 0

    page_num = request.GET.get("page", 1)
    paginator = Paginator(orders, 50)
    try:
        page_obj = paginator.page(page_num)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    can_cancel = is_owner or user_has_perm(request.user, "branch_cancel_orders") or user_has_perm(request.user, "pos_cancel_order") or user_has_perm(request.user, "cancel_orders")
    can_delete = is_owner or user_has_perm(request.user, "branch_delete_orders") or user_has_perm(request.user, "delete_orders")
    can_edit = is_owner or user_has_perm(request.user, "branch_edit_orders") or user_has_perm(request.user, "edit_orders")

    context = {
        "tenant": tenant,
        "branch": branch,
        "orders": page_obj,
        "page_obj": page_obj,
        "paginator": paginator,
        "status_filter": status_filter,
        "type_filter": type_filter,
        "pay_method_filter": pay_method_filter,
        "date_filter": date_filter,
        "search_query": search,
        "statuses": Order.STATUS_CHOICES,
        "order_types": Order.TYPE_CHOICES,
        "pay_choices": Order.PAY_CHOICES,
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "pending_orders": pending_orders,
        "delivered_orders": delivered_orders,
        "cancelled_orders": cancelled_orders,
        "can_cancel": can_cancel,
        "can_delete": can_delete,
        "can_edit": can_edit,
    }
    return render(request, "branch_orders.html", context)


# ==========================================
# 4b. HQ / ALL BRANCHES ORDERS VIEW
# ==========================================

@login_required
@ensure_csrf_cookie
def hq_orders_view(request):
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner and not (user_has_perm(request.user, "hq_view_orders") or user_has_perm(request.user, "view_orders")):
        return HttpResponseForbidden("غير مصرح لك باستعراض سجل كافة طلبات الإدارة العامة")

    # If user is strictly branch-locked, redirect to branch orders
    can_operate_cross = (
        is_owner
        or (profile and profile.job_role and profile.job_role.scope == "hq")
    )
    if not can_operate_cross and profile and profile.branch:
        return redirect("branch_orders")

    branches = Branch.objects.filter(tenant=tenant).order_by("name") if tenant else Branch.objects.none()

    branch_filter = request.GET.get("branch", "all")
    status_filter = request.GET.get("status", "all")
    type_filter = request.GET.get("type", "all")
    pay_method_filter = request.GET.get("pay_method", "all")
    date_filter = request.GET.get("date", "all")
    search = request.GET.get("q", "").strip()

    orders_base = Order.objects.filter(tenant=tenant) if tenant else Order.objects.none()
    orders = orders_base.select_related("branch", "customer", "driver").prefetch_related("items__menu_item").order_by("-created_at", "-id")

    if branch_filter != "all" and branch_filter:
        orders = orders.filter(branch_id=branch_filter)

    if status_filter != "all" and status_filter:
        if status_filter == "pending":
            orders = orders.filter(status__in=["new", "preparing", "ready", "out_for_delivery"])
        else:
            orders = orders.filter(status=status_filter)

    if type_filter != "all" and type_filter:
        orders = orders.filter(order_type=type_filter)

    if pay_method_filter != "all" and pay_method_filter:
        orders = orders.filter(pay_method=pay_method_filter)

    now = timezone.now()
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if date_filter == "today":
        orders = orders.filter(created_at__gte=start_of_today)
    elif date_filter == "yesterday":
        yesterday_start = start_of_today - timedelta(days=1)
        orders = orders.filter(created_at__gte=yesterday_start, created_at__lt=start_of_today)
    elif date_filter == "week":
        seven_days_ago = start_of_today - timedelta(days=6)
        orders = orders.filter(created_at__gte=seven_days_ago)
    elif date_filter == "month":
        thirty_days_ago = start_of_today - timedelta(days=29)
        orders = orders.filter(created_at__gte=thirty_days_ago)

    if search:
        orders = orders.filter(
            Q(order_number__icontains=search) |
            Q(customer_name__icontains=search) |
            Q(customer_phone__icontains=search) |
            Q(cashier__icontains=search) |
            Q(branch__name__icontains=search)
        )

    # Summary metrics in a single optimized aggregation query
    metrics = orders.aggregate(
        total_orders=Count("id"),
        total_revenue=Sum("total", filter=~Q(status="cancelled")),
        pending_orders=Count("id", filter=Q(status__in=["new", "preparing", "ready", "out_for_delivery"])),
        delivered_orders=Count("id", filter=Q(status="delivered")),
        cancelled_orders=Count("id", filter=Q(status="cancelled")),
    )
    total_orders = metrics["total_orders"] or 0
    total_revenue = metrics["total_revenue"] or Decimal("0")
    pending_orders = metrics["pending_orders"] or 0
    delivered_orders = metrics["delivered_orders"] or 0
    cancelled_orders = metrics["cancelled_orders"] or 0

    page_num = request.GET.get("page", 1)
    paginator = Paginator(orders, 50)
    try:
        page_obj = paginator.page(page_num)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    context = {
        "tenant": tenant,
        "branches": branches,
        "orders": page_obj,
        "page_obj": page_obj,
        "paginator": paginator,
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "pending_orders": pending_orders,
        "delivered_orders": delivered_orders,
        "cancelled_orders": cancelled_orders,
        "branch_filter": branch_filter,
        "status_filter": status_filter,
        "type_filter": type_filter,
        "pay_method_filter": pay_method_filter,
        "date_filter": date_filter,
        "search_query": search,
        "statuses": Order.STATUS_CHOICES,
        "order_types": Order.TYPE_CHOICES,
        "pay_choices": Order.PAY_CHOICES,
    }
    return render(request, "hq_orders.html", context)


# ==========================================
# 4c. ORDER DETAILS & EDIT VIEWS
# ==========================================

@login_required
@ensure_csrf_cookie
def order_detail_view(request, order_id):
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner and not user_has_perm(request.user, "view_orders"):
        return HttpResponseForbidden("غير مصرح لك باستعراض تفاصيل الطلب")

    order = get_object_or_404(
        Order.objects.select_related("branch", "customer", "driver", "tenant").prefetch_related("items__menu_item"),
        tenant=tenant,
        id=order_id
    )

    emp = getattr(request.user, "employee_profile", None)
    can_cross = (
        is_owner
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )

    # If branch-locked and cannot cross, verify branch
    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    if not can_cross and user_branch and order.branch and order.branch != user_branch:
        return HttpResponseForbidden("غير مصرح لك بمشاهدة طلبات هذا الفرع")

    can_reprint = is_owner or user_has_perm(request.user, "pos_reprint_receipt") or user_has_perm(request.user, "pos_access")
    can_edit = is_owner or user_has_perm(request.user, "edit_orders") or user_has_perm(request.user, "manage_branches")

    audit_logs = AuditLog.objects.filter(
        tenant=tenant,
        target_model="Order",
        target_id=str(order.id)
    ).select_related("user").order_by("-created_at")

    context = {
        "tenant": tenant,
        "order": order,
        "items": order.items.all(),
        "is_owner": is_owner,
        "can_edit": can_edit,
        "can_reprint": can_reprint,
        "audit_logs": audit_logs,
    }
    return render(request, "order_detail.html", context)


@login_required
@ensure_csrf_cookie
def order_edit_view(request, order_id):
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    order = get_object_or_404(
        Order.objects.select_related("branch", "customer", "driver", "tenant").prefetch_related("items__menu_item"),
        tenant=tenant,
        id=order_id
    )

    if not is_owner and not user_has_perm(request.user, "edit_orders"):
        return HttpResponseForbidden("غير مصرح لك بتعديل الطلبات")

    emp = getattr(request.user, "employee_profile", None)
    can_cross = (
        is_owner
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )

    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    if not can_cross and user_branch and order.branch and order.branch != user_branch:
        return HttpResponseForbidden("غير مصرح لك بتعديل طلبات هذا الفرع")

    branches = (
        Branch.objects.filter(tenant=tenant).filter(Q(status="active") | Q(id=order.branch_id))
        if tenant
        else Branch.objects.none()
    )
    drivers = (
        Employee.objects.filter(tenant=tenant, role="driver").filter(Q(status="active") | Q(id=order.driver_id))
        if tenant
        else Employee.objects.none()
    )
    menu_items = MenuItem.objects.filter(tenant=tenant, available=True).order_by("category", "name") if tenant else MenuItem.objects.none()

    if request.method == "POST":
        old_status = order.status
        old_driver_id = order.driver_id
        with transaction.atomic():
            if not can_cross and user_branch:
                order.branch = user_branch
            else:
                branch_id = request.POST.get("branch_id")
                if branch_id and branch_id != "none":
                    selected_branch = Branch.objects.filter(tenant=tenant, id=branch_id).filter(Q(status="active") | Q(id=order.branch_id)).first()
                    if not selected_branch:
                        return HttpResponseBadRequest("الفرع المحدد غير موجود أو مغلق")
                    order.branch = selected_branch
                else:
                    order.branch = None

            order.order_type = request.POST.get("order_type", order.order_type)
            order.channel = request.POST.get("channel", order.channel)
            new_status = request.POST.get("status", order.status)
            if new_status == "cancelled" and order.status != "cancelled":
                if not is_owner and not (user_has_perm(request.user, "pos_cancel_order") or user_has_perm(request.user, "cancel_orders")):
                    return HttpResponseForbidden("غير مصرح لك بإلغاء الفواتير أو الطلبات")
            order.status = new_status
            order.customer_name = request.POST.get("customer_name", order.customer_name).strip()

            # Normalize Arabic digits (٠١٢٣٤٥٦٧٨٩ -> 0123456789)
            trans_table = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
            raw_phone = request.POST.get("customer_phone", order.customer_phone)
            order.customer_phone = str(raw_phone or "").translate(trans_table).strip()

            order.address = request.POST.get("address", order.address).strip()
            order.notes = request.POST.get("notes", order.notes).strip()
            order.cashier = request.POST.get("cashier", order.cashier).strip()
            order.pay_method = request.POST.get("pay_method", order.pay_method)
            order.paid = request.POST.get("paid") in ["true", "on", "1", True]

            driver_id = request.POST.get("driver_id")
            if driver_id and driver_id != "none":
                driver_obj = Employee.objects.filter(tenant=tenant, id=driver_id, role="driver").filter(Q(status="active") | Q(id=order.driver_id)).first()
                if not driver_obj:
                    return HttpResponseBadRequest("السائق المحدد غير موجود أو غير نشط")
                if not can_cross and order.branch and driver_obj.branch and driver_obj.branch != order.branch:
                    return HttpResponseForbidden("لا يمكن إسناد سائق يتبع فرعاً آخر لهذا الطلب")
                order.driver = driver_obj
            else:
                order.driver = None

            # Update customer record if phone exists
            if order.customer_phone:
                cust, _ = Customer.objects.get_or_create(
                    tenant=tenant,
                    phone=order.customer_phone,
                    defaults={"name": order.customer_name, "address": order.address}
                )
                if order.customer_name and cust.name != order.customer_name:
                    cust.name = order.customer_name
                if order.address and cust.address != order.address:
                    cust.address = order.address
                cust.save()
                order.customer = cust

            # Items parsing from JSON submitted by interactive editor
            items_json = request.POST.get("items_json")
            parsed_items = None
            if items_json:
                try:
                    parsed_items = json.loads(items_json)
                except Exception:
                    parsed_items = None

            if parsed_items is not None:
                order.items.all().delete()
                subtotal = Decimal("0")
                for pi in parsed_items:
                    m_id = pi.get("menu_item_id")
                    m_item = MenuItem.objects.filter(tenant=tenant, id=m_id).first() if m_id else None
                    name = pi.get("name") or (m_item.name if m_item else "صنف")
                    price = Decimal(str(pi.get("price") or (m_item.price if m_item else 0)))
                    qty = max(1, int(pi.get("qty") or 1))
                    subtotal += price * qty
                    OrderItem.objects.create(
                        order=order,
                        menu_item=m_item,
                        name=name,
                        price=price,
                        qty=qty
                    )
                order.subtotal = subtotal

            # Delivery Fee & Discount
            try:
                raw_fee = Decimal(str(request.POST.get("delivery_fee") or ("8" if order.order_type == "delivery" else "0")))
                order.delivery_fee = max(Decimal("0"), raw_fee)
            except Exception:
                order.delivery_fee = Decimal("0")

            try:
                raw_discount = Decimal(str(request.POST.get("discount") or "0"))
            except Exception:
                raw_discount = Decimal("0")

            if raw_discount < 0:
                return HttpResponseBadRequest("قيمة الخصم لا يمكن أن تكون سالبة")

            new_discount = min(raw_discount, order.subtotal)

            if new_discount != order.discount:
                if not is_owner and not user_has_perm(request.user, "pos_apply_discount"):
                    return HttpResponseForbidden("غير مصرح لك بتعديل أو تطبيق الخصم على الفاتورة")
                order.discount = new_discount

            order.total = max(Decimal("0"), order.subtotal + order.delivery_fee - order.discount)
            order.save()

            log_audit_event(
                tenant=tenant,
                user=request.user,
                action="order_edited",
                target_model="Order",
                target_id=order.id,
                description=f"تعديل أصناف وتفاصيل الطلب #{order.order_number} (الإجمالي الجديد: {order.total} ر.س)",
                ip_address=_get_client_ip(request),
            )

        # Real-time SSE push to kitchen display screen
        event_type = "order_cancelled" if order.status == "cancelled" else ("order_status_changed" if old_status != order.status else "order_updated")
        notify_kitchen_order_event(order, event_type)

        if order.order_type == "delivery":
            deliv_event = "delivery_order_cancelled" if order.status == "cancelled" else (
                "delivery_status_changed" if old_status != order.status else (
                    "delivery_driver_assigned" if old_driver_id != order.driver_id else "delivery_order_updated"
                )
            )
            notify_delivery_order_event(order, deliv_event)

        return redirect("order_detail", order_id=order.id)

    context = {
        "tenant": tenant,
        "order": order,
        "items": order.items.all(),
        "branches": branches,
        "drivers": drivers,
        "menu_items": menu_items,
        "statuses": Order.STATUS_CHOICES,
        "order_types": Order.TYPE_CHOICES,
        "pay_choices": Order.PAY_CHOICES,
        "is_owner": is_owner,
    }
    return render(request, "order_edit.html", context)


@login_required
def api_cancel_order(request, order_id):
    if request.method not in ["POST", "PATCH"]:
        return HttpResponseBadRequest("POST or PATCH required")

    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    can_cancel = is_owner or user_has_perm(request.user, "branch_cancel_orders") or user_has_perm(request.user, "pos_cancel_order") or user_has_perm(request.user, "hq_cancel_orders") or user_has_perm(request.user, "cancel_orders")
    if not can_cancel:
        return JsonResponse({"error": "غير مصرح لك بإلغاء الفواتير أو الطلبات."}, status=403)

    order = get_object_or_404(Order, tenant=tenant, id=order_id)
    emp = getattr(request.user, "employee_profile", None)
    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    can_cross = (
        is_owner
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope == "hq")
        or (emp and emp.job_role and emp.job_role.scope == "hq")
    )
    if not can_cross and user_branch and order.branch and order.branch != user_branch:
        return JsonResponse({"error": "غير مصرح لك بالتعامل مع طلبات الفروع الأخرى"}, status=403)

    order.status = "cancelled"
    order.save()
    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="order_cancelled",
        target_model="Order",
        target_id=order.id,
        description=f"إلغاء الطلب #{order.order_number} بقيمة {order.total} ر.س",
        ip_address=_get_client_ip(request),
    )
    notify_kitchen_order_event(order, "order_cancelled")
    if order.order_type == "delivery":
        notify_delivery_order_event(order, "delivery_order_cancelled")
    return JsonResponse({"ok": True, "status": "cancelled", "message": f"تم إلغاء الطلب {order.order_number} بنجاح"})


@login_required
def api_delete_order(request, order_id):
    if request.method not in ["POST", "DELETE"]:
        return HttpResponseBadRequest("POST or DELETE required")

    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    can_delete = is_owner or user_has_perm(request.user, "branch_delete_orders") or user_has_perm(request.user, "hq_delete_orders") or user_has_perm(request.user, "delete_orders")
    if not can_delete:
        return JsonResponse({"error": "غير مصرح لك بحذف الفواتير نهائياً من قاعدة البيانات (يتطلب صلاحية حذف الفواتير)."}, status=403)

    order = get_object_or_404(Order, tenant=tenant, id=order_id)
    emp = getattr(request.user, "employee_profile", None)
    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    can_cross = (
        is_owner
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope == "hq")
        or (emp and emp.job_role and emp.job_role.scope == "hq")
    )
    if not can_cross and user_branch and order.branch and order.branch != user_branch:
        return JsonResponse({"error": "غير مصرح لك بحذف فواتير الفروع الأخرى"}, status=403)

    order_id_val = order.id
    order_number = order.order_number
    order_total = order.total
    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="order_deleted",
        target_model="Order",
        target_id=order_id_val,
        description=f"حذف الفاتورة #{order_number} نهائياً بقيمة {order_total} ر.س من قاعدة البيانات",
        ip_address=_get_client_ip(request),
    )
    notify_kitchen_order_event(order, "order_cancelled")
    if order.order_type == "delivery":
        notify_delivery_order_event(order, "delivery_order_cancelled")
    order.delete()
    return JsonResponse({"ok": True, "message": f"تم حذف الطلب {order_number} نهائياً من قاعدة البيانات"})


# ==========================================
# 5. BRANCH MENU AVAILABILITY VIEW
# ==========================================

@login_required
@ensure_csrf_cookie


def pos_view(request):
    tenant = get_active_tenant(request)
    if tenant and not tenant.has_feature("pos"):
        return HttpResponseForbidden("ميزة نقطة البيع (POS) غير مفعلة في باقة اشتراك هذا المطعم. يرجى ترقية الباقة لتفعيلها.")

    if not user_has_perm(request.user, "pos_access"):
        return HttpResponseForbidden("غير مصرح لك بالوصول إلى نقطة البيع (POS)")

    tenant = get_active_tenant(request)
    branch = get_active_branch(request)

    lang = getattr(request, "LANGUAGE_CODE", None) or translation.get_language() or "ar"
    if "-" in lang:
        lang = lang.split("-")[0]
    if lang not in ["ar", "en"]:
        lang = "ar"

    # Dynamic Menu Categories from apps.menu.models.MenuCategory
    active_categories_qs = (
        MenuCategory.objects.filter(tenant=tenant, is_active=True).order_by("ordering", "id")
        if tenant
        else MenuCategory.objects.none()
    )

    # Legacy migration fallback: ONLY if tenant has NEVER had any MenuCategories in DB before.
    # If the tenant already has MenuCategories (active or inactive/deleted), NEVER auto-provision or reactivate them.
    if tenant and not MenuCategory.objects.filter(tenant=tenant).exists():
        legacy_cats = list(
            MenuItem.objects.filter(tenant=tenant)
            .exclude(category="")
            .exclude(category__isnull=True)
            .values_list("category", flat=True)
            .distinct()
        )
        if legacy_cats:
            order_idx = 10
            for cat_name in legacy_cats:
                cat_name_clean = str(cat_name).strip()
                if cat_name_clean:
                    MenuCategory.objects.get_or_create(
                        tenant=tenant,
                        name=cat_name_clean,
                        defaults={"ordering": order_idx, "is_active": True},
                    )
                    order_idx += 10
            active_categories_qs = MenuCategory.objects.filter(
                tenant=tenant, is_active=True
            ).order_by("ordering", "id")

    active_cats_list = list(active_categories_qs)
    cat_by_id = {c.id: c for c in active_cats_list}
    cat_by_name = {}
    for c in active_cats_list:
        if c.name:
            cat_by_name[c.name.strip().lower()] = c
        if c.name_en and c.name_en.strip():
            cat_by_name[c.name_en.strip().lower()] = c

    base_menu = (
        MenuItem.objects.filter(tenant=tenant, available=True, is_active=True)
        .select_related("category_rel")
        .order_by("category_rel__ordering", "category_rel__id", "category", "name")
        if tenant
        else MenuItem.objects.none()
    )
    if branch:
        disabled_ids = set(
            BranchMenuAvailability.objects.filter(branch=branch, is_available=False).values_list(
                "menu_item_id", flat=True
            )
        )
        raw_items = list(base_menu.exclude(id__in=disabled_ids))
    else:
        raw_items = list(base_menu)

    BORDER_PALETTE = [
        "border-violet-500",
        "border-blue-500",
        "border-emerald-500",
        "border-amber-500",
        "border-orange-500",
        "border-teal-500",
        "border-cyan-500",
        "border-rose-500",
        "border-pink-500",
        "border-indigo-500",
    ]

    menu_items = []
    items_to_backfill = []
    has_uncategorized = False
    for m in raw_items:
        m.price = m.get_price_for_branch(branch)
        m.display_name = m.get_display_name(lang)

        resolved_cat = None
        if m.category_rel_id and m.category_rel_id in cat_by_id:
            resolved_cat = cat_by_id[m.category_rel_id]
        elif m.category and m.category.strip().lower() in cat_by_name:
            resolved_cat = cat_by_name[m.category.strip().lower()]
            if not m.category_rel_id:
                m.category_rel = resolved_cat
                items_to_backfill.append(m)

        if resolved_cat:
            m.pos_category_id = str(resolved_cat.id)
            m.pos_category_name = resolved_cat.get_display_name(lang)
            m.pos_category_raw_name = resolved_cat.name
            color_idx = resolved_cat.id % len(BORDER_PALETTE)
            m.border_color_class = BORDER_PALETTE[color_idx]
        else:
            m.pos_category_id = "uncategorized"
            m.pos_category_name = "أطباق عامة" if lang == "ar" else "General"
            m.pos_category_raw_name = "أطباق عامة"
            m.border_color_class = "border-slate-400"
            has_uncategorized = True

        menu_items.append(m)

    if items_to_backfill:
        try:
            MenuItem.objects.bulk_update(items_to_backfill, ["category_rel"])
        except Exception:
            pass

    # Build category list for POS tab pills
    categories = [
        {
            "id": "all",
            "name": "الكل" if lang == "ar" else "All",
            "raw_name": "all",
            "is_all": True,
        }
    ]
    for c in active_cats_list:
        categories.append({
            "id": str(c.id),
            "name": c.get_display_name(lang),
            "raw_name": c.name,
            "is_all": False,
        })
    if has_uncategorized:
        categories.append({
            "id": "uncategorized",
            "name": "أطباق عامة" if lang == "ar" else "General",
            "raw_name": "uncategorized",
            "is_all": False,
        })

    recent_orders = Order.objects.filter(tenant=tenant).order_by("-id") if tenant else Order.objects.none()
    if branch:
        recent_orders = recent_orders.filter(branch=branch)

    currency_sym = branch.get_currency_symbol_ar() if branch else (tenant.get_currency_symbol_ar() if tenant else "ر.س")
    branches = list(tenant.branches.filter(status="active").order_by("name")) if tenant else []

    context = {
        "tenant": tenant,
        "current_branch": branch,
        "branches": branches,
        "categories": categories,
        "active_categories": active_cats_list,
        "menu_items": menu_items,
        "recent_orders": recent_orders[:10],
        "branch_currency_symbol": currency_sym,
    }
    return render(request, "pos.html", context)


@login_required
@ensure_csrf_cookie


def delivery_view(request):
    tenant = get_active_tenant(request)
    if tenant and not (tenant.has_feature("delivery_management") or tenant.has_feature("delivery")):
        return HttpResponseForbidden("ميزة إدارة التوصيل غير مفعلة في باقة اشتراك هذا المطعم. يرجى ترقية الباقة لتفعيلها.")

    if not user_has_perm(request.user, "delivery_access"):
        return HttpResponseForbidden("غير مصرح لك بالوصول إلى قسم التوصيل")

    branch = get_active_branch(request)
    profile = getattr(request.user, "profile", None)
    emp = getattr(request.user, "employee_profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    can_cross = (
        is_owner
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )

    q_branch = request.GET.get("branch_id")
    target_branch = branch
    target_branch_id = branch.id if branch else None
    if can_cross and q_branch:
        if q_branch in ["all", "0", 0]:
            target_branch = None
            target_branch_id = None
        elif q_branch.isdigit():
            target_branch = Branch.objects.filter(tenant=tenant, id=int(q_branch)).first()
            target_branch_id = target_branch.id if target_branch else None

    start_of_today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    drivers_qs = Employee.objects.filter(tenant=tenant, role="driver", status="active").order_by("name")
    if target_branch:
        drivers_qs = drivers_qs.filter(Q(branch=target_branch) | Q(branch__isnull=True))

    drivers = list(drivers_qs)

    delivery_orders = Order.objects.filter(
        tenant=tenant,
        order_type="delivery",
        created_at__gte=start_of_today - timedelta(days=1),
    ).exclude(status="cancelled").select_related("branch", "driver", "delivery_area").order_by("-id")

    if target_branch:
        delivery_orders = delivery_orders.filter(branch=target_branch)

    orders_by_status = {
        "new": [],
        "preparing": [],
        "ready": [],
        "out_for_delivery": [],
        "delivered": [],
    }
    for order in delivery_orders:
        if order.status in orders_by_status:
            orders_by_status[order.status].append(order)

    driver_ids = [d.id for d in drivers]
    stats_map = {}
    if driver_ids:
        agg_qs = Order.objects.filter(tenant=tenant, driver_id__in=driver_ids).values("driver_id").annotate(
            active=Count("id", filter=Q(status="out_for_delivery")),
            done=Count("id", filter=Q(status="delivered", created_at__gte=start_of_today))
        )
        stats_map = {row["driver_id"]: row for row in agg_qs}

    driver_stats = []
    for d in drivers:
        st = stats_map.get(d.id, {})
        driver_stats.append({
            "id": d.id,
            "name": d.name,
            "phone": d.phone,
            "active": st.get("active", 0),
            "done": st.get("done", 0),
        })

    active_count = sum(len(orders_by_status[st]) for st in ["new", "preparing", "ready", "out_for_delivery"])
    branches = list(Branch.objects.filter(tenant=tenant, status="active")) if can_cross else []
    serialized_orders = [serialize_delivery_order(o) for o in delivery_orders]

    drivers_data = [{"id": d.id, "name": d.name, "phone": d.phone or ""} for d in drivers]

    context = {
        "tenant": tenant,
        "current_branch": branch,
        "target_branch_id": target_branch_id,
        "branches": branches,
        "orders_by_status": orders_by_status,
        "orders_json": json.dumps(serialized_orders),
        "drivers": drivers,
        "drivers_json": json.dumps(drivers_data),
        "driver_stats": driver_stats,
        "driver_stats_json": json.dumps(driver_stats),
        "active_count": active_count,
    }
    return render(request, "delivery.html", context)


async def delivery_stream_view(request):
    """
    Real-Time Server-Sent Events (SSE) push stream for Delivery Management Screen.
    Pushes events: 'connected', 'delivery_new_order', 'delivery_status_changed', 'delivery_driver_assigned', 'delivery_order_cancelled'.
    Maintains persistent ASGI connection with automatic keepalive (zero polling, 0ms latency).
    """
    if not request.user.is_authenticated:
        return HttpResponseForbidden("يرجى تسجيل الدخول للوصول إلى بث التوصيل المباشر")

    tenant = await sync_to_async(get_active_tenant)(request)
    if not tenant:
        return HttpResponseForbidden("المنشأة غير موجودة")

    has_deliv_feat = (await sync_to_async(tenant.has_feature)("delivery_management") or
                      await sync_to_async(tenant.has_feature)("delivery"))
    if not has_deliv_feat:
        return HttpResponseForbidden("ميزة إدارة التوصيل غير مفعلة في باقة اشتراك هذا المطعم")

    has_perm = await sync_to_async(user_has_perm)(request.user, "delivery_access")
    if not has_perm:
        return HttpResponseForbidden("غير مصرح لك بالوصول إلى قسم التوصيل")

    branch = await sync_to_async(get_active_branch)(request)
    profile = getattr(request.user, "profile", None)
    emp = getattr(request.user, "employee_profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    has_switch = await sync_to_async(user_has_perm)(request.user, "branch_switch_branches")
    has_manage_b = await sync_to_async(user_has_perm)(request.user, "manage_branches")
    has_hq_scope = (profile and profile.job_role and profile.job_role.scope in ["hq", "both"]) or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    can_cross = is_owner or has_switch or has_manage_b or has_hq_scope

    branch_id = branch.id if branch else None
    q_branch = request.GET.get("branch_id")
    if can_cross and q_branch and q_branch.isdigit():
        branch_id = int(q_branch)

    queue = await delivery_broadcaster.register(tenant.id, branch_id)

    async def event_generator():
        try:
            init_payload = {
                "status": "connected",
                "tenant_id": tenant.id,
                "branch_id": branch_id,
                "server_time": timezone.now().isoformat(),
            }
            yield f"event: connected\ndata: {json.dumps(init_payload)}\n\n"

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await delivery_broadcaster.unregister(queue)

    response = StreamingHttpResponse(event_generator(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    response["Connection"] = "keep-alive"
    return response


@login_required
def api_delivery_live(request):
    """
    Returns JSON snapshot of all active delivery orders grouped by status,
    along with driver statistics and active count.
    """
    tenant = get_active_tenant(request)
    if tenant and not (tenant.has_feature("delivery_management") or tenant.has_feature("delivery")):
        return JsonResponse({"error": "ميزة إدارة التوصيل غير مفعلة في باقة اشتراك هذا المطعم"}, status=403)

    if not user_has_perm(request.user, "delivery_access"):
        return JsonResponse({"error": "غير مصرح لك بالوصول إلى قسم التوصيل"}, status=403)

    branch = get_active_branch(request)
    profile = getattr(request.user, "profile", None)
    emp = getattr(request.user, "employee_profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    can_cross = (
        is_owner
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )

    q_branch = request.GET.get("branch_id")
    target_branch = branch
    if can_cross and q_branch:
        if q_branch in ["all", "0", 0]:
            target_branch = None
        elif q_branch.isdigit():
            target_branch = Branch.objects.filter(tenant=tenant, id=int(q_branch)).first()

    start_of_today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    drivers_qs = Employee.objects.filter(tenant=tenant, role="driver", status="active").order_by("name")
    if target_branch:
        drivers_qs = drivers_qs.filter(Q(branch=target_branch) | Q(branch__isnull=True))
    drivers = list(drivers_qs)

    delivery_orders = Order.objects.filter(
        tenant=tenant,
        order_type="delivery",
        created_at__gte=start_of_today - timedelta(days=1),
    ).exclude(status="cancelled").select_related("branch", "driver", "delivery_area").order_by("-id")

    if target_branch:
        delivery_orders = delivery_orders.filter(branch=target_branch)

    orders_by_status = {
        "new": [],
        "preparing": [],
        "ready": [],
        "out_for_delivery": [],
        "delivered": [],
    }
    serialized_orders = []
    for order in delivery_orders:
        s_order = serialize_delivery_order(order)
        serialized_orders.append(s_order)
        if order.status in orders_by_status:
            orders_by_status[order.status].append(s_order)

    driver_ids = [d.id for d in drivers]
    stats_map = {}
    if driver_ids:
        agg_qs = Order.objects.filter(tenant=tenant, driver_id__in=driver_ids).values("driver_id").annotate(
            active=Count("id", filter=Q(status="out_for_delivery")),
            done=Count("id", filter=Q(status="delivered", created_at__gte=start_of_today))
        )
        stats_map = {row["driver_id"]: row for row in agg_qs}

    driver_stats = []
    for d in drivers:
        st = stats_map.get(d.id, {})
        driver_stats.append({
            "id": d.id,
            "name": d.name,
            "phone": d.phone or "",
            "active": st.get("active", 0),
            "done": st.get("done", 0),
        })

    active_count = sum(len(orders_by_status[st]) for st in ["new", "preparing", "ready", "out_for_delivery"])

    return JsonResponse({
        "ok": True,
        "orders_by_status": orders_by_status,
        "orders": serialized_orders,
        "driver_stats": driver_stats,
        "active_count": active_count,
    })


@login_required
@ensure_csrf_cookie


def api_create_order(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (
        user_has_perm(request.user, "pos_create_order") or
        user_has_perm(request.user, "pos_access") or
        user_has_perm(request.user, "call_center_create_order") or
        user_has_perm(request.user, "call_center_access")
    ):
        return JsonResponse({"error": "غير مصرح لك بإنشاء أو تسجيل طلبات جديدة"}, status=403)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    try:
        raw_discount = Decimal(str(data.get("discount") or 0))
    except Exception:
        raw_discount = Decimal("0")

    if raw_discount < 0:
        return JsonResponse({"error": "قيمة الخصم لا يمكن أن تكون سالبة"}, status=400)

    if raw_discount > 0 and not is_owner_or_super and not user_has_perm(request.user, "pos_apply_discount"):
        return JsonResponse({"error": "غير مصرح لك بتطبيق خصم على الفاتورة"}, status=403)

    items_data = data.get("items", [])
    if not items_data:
        return JsonResponse({"error": "السلة فارغة — أضف أصنافاً أولاً"}, status=400)

    order_type = data.get("type", "dine_in")
    channel = data.get("channel", "cashier")

    emp = getattr(request.user, "employee_profile", None)
    can_cross = (
        is_owner_or_super
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )
    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)

    active_branch = get_active_branch(request)
    if can_cross and data.get("branchId"):
        branch_id = data.get("branchId")
    else:
        branch_id = (active_branch.id if active_branch else None) or data.get("branchId")

    branch = Branch.objects.filter(tenant=tenant, id=branch_id).first() if branch_id else None

    if not can_cross and user_branch:
        branch = user_branch

    if branch and branch.status == "closed":
        return JsonResponse({"error": "الفرع المحدد مغلق حالياً ولا يستقبل طلبات جديدة"}, status=400)

    # Resolve items scoped to tenant and verify availability
    menu_ids = [int(i.get("menuItemId")) for i in items_data if i.get("menuItemId")]
    disabled_in_branch = set()
    if branch:
        disabled_in_branch = set(
            BranchMenuAvailability.objects.filter(
                branch=branch, menu_item_id__in=menu_ids, is_available=False
            ).values_list("menu_item_id", flat=True)
        )
    menu_map = {m.id: m for m in MenuItem.objects.filter(tenant=tenant, id__in=menu_ids)}

    rows = []
    subtotal = Decimal("0")
    for it in items_data:
        m_id = int(it.get("menuItemId", 0))
        m = menu_map.get(m_id)
        if not m:
            continue
        if not m.available or m_id in disabled_in_branch:
            return JsonResponse({"error": f"الصنف «{m.name}» غير متوفر حالياً بالفرع"}, status=400)
        qty = max(1, int(it.get("qty", 1)))
        unit_price = m.get_price_for_branch(branch)
        custom_price = it.get("customPrice") or it.get("custom_price")
        if custom_price is not None:
            try:
                cp = Decimal(str(custom_price))
                if cp > 0 and cp != unit_price:
                    if not is_owner_or_super and not user_has_perm(request.user, "pos_override_price"):
                        return JsonResponse({"error": f"غير مصرح لك بتعديل سعر الصنف «{m.name}» يدوياً"}, status=403)
                    unit_price = cp
            except Exception:
                pass
        subtotal += unit_price * qty
        rows.append({"menu_item": m, "name": m.name, "price": unit_price, "qty": qty})

    if not rows:
        return JsonResponse({"error": "الأصناف المحددة غير متوفرة"}, status=400)

    delivery_area_id = data.get("deliveryAreaId")
    delivery_area = None
    if delivery_area_id:
        delivery_area = DeliveryArea.objects.filter(branch__tenant=tenant, id=delivery_area_id, is_active=True).first()
        if not delivery_area:
            return JsonResponse({"error": "منطقة التوصيل المحددة غير مفعلة أو غير موجودة بالفرع"}, status=400)
        if not can_cross and user_branch and delivery_area.branch and delivery_area.branch != user_branch:
            return JsonResponse({"error": "غير مصرح لك باختيار منطقة توصيل تتبع فرعاً آخر"}, status=403)
        if can_cross:
            branch = delivery_area.branch

    if order_type == "delivery":
        if delivery_area:
            delivery_fee = max(Decimal("0"), delivery_area.delivery_fee)
        else:
            try:
                delivery_fee = max(Decimal("0"), Decimal(str(data.get("deliveryFee") or "8")))
            except Exception:
                delivery_fee = Decimal("0")
    else:
        delivery_fee = Decimal("0")

    if raw_discount > 0 and subtotal > 0:
        if (raw_discount / subtotal) > Decimal("0.50"):
            has_supervisor = is_owner_or_super or user_has_perm(request.user, "edit_orders") or user_has_perm(request.user, "manage_branches")
            if not has_supervisor:
                return JsonResponse({"error": "تطبيق خصم يتجاوز 50% من قيمة الطلب مقتصر على المشرف أو مدير الفرع"}, status=403)

    discount = max(Decimal("0"), min(raw_discount, subtotal))
    total = max(Decimal("0"), subtotal + delivery_fee - discount)

    trans_table = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    phone = str(data.get("customerPhone") or "").translate(trans_table).strip()
    cust_name = str(data.get("customerName") or "").strip() or ("عميل توصيل" if order_type == "delivery" else "عميل نقدي")
    address = str(data.get("address") or "").strip()
    customer = None

    cashier_name = (
        getattr(request.user, "employee_profile", None).name
        if getattr(request.user, "employee_profile", None)
        else (request.user.get_full_name() or request.user.first_name or request.user.username)
    )

    with transaction.atomic():
        if phone:
            customer = Customer.objects.filter(tenant=tenant, phone=phone).first()
            if not customer:
                try:
                    customer = Customer.objects.create(
                        tenant=tenant, phone=phone, name=cust_name, address=address
                    )
                except IntegrityError:
                    customer = Customer.objects.filter(tenant=tenant, phone=phone).first()
            if customer:
                if cust_name and customer.name != cust_name:
                    customer.name = cust_name
                if address and customer.address != address:
                    customer.address = address
                customer.save()

        prefix = (tenant.slug[:3] if tenant and tenant.slug else "ORD").upper()
        order = None
        for attempt in range(5):
            last_order = Order.objects.filter(tenant=tenant).order_by("-id").first()
            next_seq = (last_order.id + 1 + attempt) if last_order else (1 + attempt)
            candidate_num = f"{prefix}-{1000 + next_seq}"
            while Order.objects.filter(tenant=tenant, order_number=candidate_num).exists():
                next_seq += 1
                candidate_num = f"{prefix}-{1000 + next_seq}"
            order_number = candidate_num

            try:
                sid = transaction.savepoint()
                order = Order.objects.create(
                    tenant=tenant,
                    order_number=order_number,
                    order_type=order_type,
                    channel=channel,
                    branch=branch,
                    delivery_area=delivery_area,
                    customer=customer,
                    customer_name=cust_name,
                    customer_phone=phone,
                    address=address,
                    status="new",
                    pay_method=data.get("payMethod", "cash"),
                    paid=True,
                    subtotal=subtotal,
                    delivery_fee=delivery_fee,
                    discount=discount,
                    total=total,
                    cashier=cashier_name,
                    notes=str(data.get("notes") or ""),
                )
                transaction.savepoint_commit(sid)
                break
            except IntegrityError:
                transaction.savepoint_rollback(sid)
                continue

        if not order:
            return JsonResponse({"error": "حدث تضارب أثناء توليد رقم الطلب، يرجى إعادة المحاولة."}, status=409)

        for r in rows:
            OrderItem.objects.create(
                order=order,
                menu_item=r["menu_item"],
                name=r["name"],
                price=r["price"],
                qty=r["qty"],
            )

        log_audit_event(
            tenant=tenant,
            user=request.user,
            action="order_created",
            target_model="Order",
            target_id=order.id,
            description=f"إنشاء الطلب #{order.order_number} ({order.get_order_type_display()}) بقيمة {order.total} ر.س بواسطة الكاشير: {cashier_name}",
            ip_address=_get_client_ip(request),
        )

    # Broadcast real-time SSE event to all active kitchen screens (0ms)
    notify_kitchen_order_event(order, "new_order")
    if order.order_type == "delivery":
        notify_delivery_order_event(order, "delivery_new_order")

    return JsonResponse({"order": {"id": order.id, "orderNumber": order.order_number}}, status=201)


@login_required
def api_update_order(request, order_id):
    if request.method not in ["PATCH", "POST"]:
        return HttpResponseBadRequest("PATCH or POST required")

    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (
        user_has_perm(request.user, "edit_orders") or
        user_has_perm(request.user, "kds_update_status") or
        user_has_perm(request.user, "kds_access") or
        user_has_perm(request.user, "delivery_access") or
        user_has_perm(request.user, "pos_access")
    ):
        return JsonResponse({"error": "غير مصرح لك بتعديل الطلبات"}, status=403)

    order = get_object_or_404(Order, tenant=tenant, id=order_id)
    emp = getattr(request.user, "employee_profile", None)
    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    can_cross = (
        is_owner_or_super
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )
    if not can_cross and user_branch and order.branch and order.branch != user_branch:
        return JsonResponse({"error": "غير مصرح لك بتعديل طلبات فرع آخر"}, status=403)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    action = data.get("action")
    old_status = order.status
    old_driver_id = order.driver_id
    if action == "refund" or data.get("status") == "refunded" or data.get("refund"):
        if not is_owner_or_super and not user_has_perm(request.user, "pos_refund_order"):
            return JsonResponse({"error": "غير مصرح لك باسترجاع الفواتير ورد المبالغ للعميل"}, status=403)
        order.status = "cancelled"
        order.paid = False
        log_audit_event(
            tenant=tenant,
            user=request.user,
            action="order_refunded",
            target_model="Order",
            target_id=order.id,
            description=f"استرجاع الفاتورة #{order.order_number} وإعادة المبلغ بقيمة {order.total} ر.س",
            ip_address=_get_client_ip(request),
        )

    if "status" in data and data["status"] in dict(Order.STATUS_CHOICES):
        new_status = data["status"]
        if new_status == "cancelled":
            if not is_owner_or_super and not (user_has_perm(request.user, "pos_cancel_order") or user_has_perm(request.user, "cancel_orders")):
                return JsonResponse({"error": "غير مصرح لك بإلغاء الفواتير أو الطلبات"}, status=403)
            if old_status != "cancelled":
                log_audit_event(
                    tenant=tenant,
                    user=request.user,
                    action="order_cancelled",
                    target_model="Order",
                    target_id=order.id,
                    description=f"إلغاء الفاتورة #{order.order_number}",
                    ip_address=_get_client_ip(request),
                )
        else:
            if old_status == "cancelled":
                if not is_owner_or_super and not (user_has_perm(request.user, "pos_cancel_order") or user_has_perm(request.user, "cancel_orders")):
                    return JsonResponse({"error": "لا يمكن إعادة تنشيط طلب تم إلغاؤه إلا بإذن المالك أو مسؤول الإلغاءات"}, status=403)
                log_audit_event(
                    tenant=tenant,
                    user=request.user,
                    action="order_reactivated",
                    target_model="Order",
                    target_id=order.id,
                    description=f"إعادة تنشيط الطلب الملغي #{order.order_number} إلى حالة «{dict(Order.STATUS_CHOICES).get(new_status, new_status)}»",
                    ip_address=_get_client_ip(request),
                )
            elif old_status != new_status:
                status_dict = dict(Order.STATUS_CHOICES)
                old_lbl = status_dict.get(old_status, old_status)
                new_lbl = status_dict.get(new_status, new_status)
                log_audit_event(
                    tenant=tenant,
                    user=request.user,
                    action="order_status_changed",
                    target_model="Order",
                    target_id=order.id,
                    description=f"تحديث حالة الطلب #{order.order_number} من «{old_lbl}» إلى «{new_lbl}»",
                    ip_address=_get_client_ip(request),
                )

            if new_status in ["preparing", "ready"]:
                # Recalling an already ready or delivered order back to preparing/new
                if old_status in ["ready", "delivered"] and new_status in ["new", "preparing"]:
                    if not is_owner_or_super and not (user_has_perm(request.user, "kds_recall_order") or user_has_perm(request.user, "edit_orders")):
                        return JsonResponse({"error": "غير مصرح لك باسترجاع طلب تم إنجازه إلى شاشة الطهي (يتطلب صلاحية استرجاع الطلبات)"}, status=403)
                elif not is_owner_or_super and not (user_has_perm(request.user, "kds_update_status") or user_has_perm(request.user, "kds_access") or user_has_perm(request.user, "edit_orders")):
                    return JsonResponse({"error": "غير مصرح لك بتحديث حالة تحضير الطلب في المطبخ"}, status=403)
            elif new_status in ["out_for_delivery", "delivered"]:
                if not is_owner_or_super and not (
                    user_has_perm(request.user, "delivery_access") or
                    user_has_perm(request.user, "delivery_override_status") or
                    user_has_perm(request.user, "edit_orders")
                ):
                    return JsonResponse({"error": "غير مصرح لك بتحديث مسار وحالة توصيل الطلب"}, status=403)
        order.status = new_status

    if "driverId" in data or "driver_id" in data:
        if not is_owner_or_super and not (user_has_perm(request.user, "delivery_assign_driver") or user_has_perm(request.user, "delivery_access") or user_has_perm(request.user, "edit_orders")):
            return JsonResponse({"error": "غير مصرح لك بإسناد السائقين للطلبات"}, status=403)
        drv_id = data.get("driverId") if "driverId" in data else data.get("driver_id")
        if drv_id:
            driver_obj = Employee.objects.filter(tenant=tenant, id=drv_id, role="driver").filter(Q(status="active") | Q(id=order.driver_id)).first()
            if not driver_obj:
                return JsonResponse({"error": "السائق المحدد غير موجود أو غير نشط حالياً"}, status=400)
            if not is_owner_or_super:
                can_cross = (
                    user_has_perm(request.user, "branch_switch_branches")
                    or user_has_perm(request.user, "manage_branches")
                    or user_has_perm(request.user, "view_hq_dashboard")
                    or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
                    or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
                )
                if not can_cross and order.branch and driver_obj.branch and driver_obj.branch != order.branch:
                    return JsonResponse({"error": "لا يمكن إسناد سائق يتبع فرعاً آخر لهذا الطلب"}, status=403)
            if order.driver != driver_obj:
                order.driver = driver_obj
                log_audit_event(
                    tenant=tenant,
                    user=request.user,
                    action="order_driver_assigned",
                    target_model="Order",
                    target_id=order.id,
                    description=f"إسناد السائق «{driver_obj.name}» للطلب #{order.order_number}",
                    ip_address=_get_client_ip(request),
                )
        else:
            if order.driver is not None:
                order.driver = None
                log_audit_event(
                    tenant=tenant,
                    user=request.user,
                    action="order_driver_unassigned",
                    target_model="Order",
                    target_id=order.id,
                    description=f"إلغاء إسناد السائق عن الطلب #{order.order_number}",
                    ip_address=_get_client_ip(request),
                )

    if "paid" in data and isinstance(data["paid"], bool):
        if not is_owner_or_super and not (user_has_perm(request.user, "pos_access") or user_has_perm(request.user, "edit_orders")):
            return JsonResponse({"error": "غير مصرح لك بتحديث حالة دفع الفاتورة"}, status=403)
        if order.status == "cancelled" and data["paid"] is True:
            return JsonResponse({"error": "لا يمكن تأكيد دفع فاتورة تم إلغاؤها"}, status=400)
        if order.paid != data["paid"]:
            order.paid = data["paid"]
            paid_str = "تم الدفع بالكامل" if order.paid else "معلق / غير مدفوع"
            log_audit_event(
                tenant=tenant,
                user=request.user,
                action="order_payment_updated",
                target_model="Order",
                target_id=order.id,
                description=f"تحديث حالة سداد الطلب #{order.order_number} إلى «{paid_str}»",
                ip_address=_get_client_ip(request),
            )

    order.save()

    # Broadcast real-time SSE status change to kitchen displays (0ms)
    event_type = "order_status_changed" if old_status != order.status else "order_updated"
    notify_kitchen_order_event(order, event_type)

    if order.order_type == "delivery":
        deliv_event = "delivery_order_cancelled" if order.status == "cancelled" else (
            "delivery_status_changed" if old_status != order.status else (
                "delivery_driver_assigned" if old_driver_id != order.driver_id else "delivery_order_updated"
            )
        )
        notify_delivery_order_event(order, deliv_event)

    return JsonResponse({
        "ok": True,
        "status": order.status,
        "driver_id": order.driver_id,
        "driver_name": order.driver.name if order.driver else None,
    })


@login_required


def api_search_customers(request):
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (
        user_has_perm(request.user, "pos_access") or
        user_has_perm(request.user, "pos_create_order") or
        user_has_perm(request.user, "call_center_access") or
        user_has_perm(request.user, "call_center_create_order") or
        user_has_perm(request.user, "call_center_view_customers")
    ):
        return JsonResponse({"error": "غير مصرح لك بالبحث في دليل بيانات العملاء"}, status=403)

    trans_table = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    q = request.GET.get("q", "").translate(trans_table).strip()
    if len(q) < 3:
        return JsonResponse({"customers": []})

    tenant = get_active_tenant(request)
    emp = getattr(request.user, "employee_profile", None)
    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    can_cross = (
        is_owner_or_super
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
        or not user_branch
    )

    customers_qs = Customer.objects.filter(tenant=tenant)
    if not can_cross and user_branch:
        branch_cust_ids = Order.objects.filter(
            tenant=tenant, branch=user_branch, customer__isnull=False
        ).values_list("customer_id", flat=True)
        customers_qs = customers_qs.filter(id__in=branch_cust_ids)

    filter_cond = Q(phone__icontains=q) | Q(name__icontains=q)
    if not can_cross and user_branch:
        customers = customers_qs.filter(filter_cond).annotate(
            orders_count=Count("orders", filter=Q(orders__branch=user_branch, orders__tenant=tenant))
        )[:8]
    else:
        customers = customers_qs.filter(filter_cond).annotate(
            orders_count=Count("orders", filter=Q(orders__tenant=tenant))
        )[:8]

    data = [
        {
            "id": c.id,
            "name": c.name,
            "phone": c.phone,
            "address": c.address,
            "ordersCount": c.orders_count,
        }
        for c in customers
    ]
    return JsonResponse({"customers": data})

