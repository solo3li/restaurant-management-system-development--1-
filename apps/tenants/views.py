import os
import json
import logging
import re
from decimal import Decimal
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotFound, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.db.models import Sum, Count, F, Q
from django.core.cache import cache
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from apps.tenants.helpers import get_active_tenant, get_active_branch
from apps.accounts.helpers import user_has_perm, _get_client_ip
from apps.tenants.models import Tenant, Branch, DeliveryArea, PlatformConfiguration
from apps.orders.models import Order, Customer
from apps.menu.models import MenuItem
from apps.inventory.models import InventoryItem
from apps.accounts.models import Employee
from apps.audit.models import log_audit_event
from core.currencies import CURRENCIES, CURRENCIES_DATA, get_currency_info
from django.contrib import messages

logger = logging.getLogger(__name__)

@login_required
def switch_branch_view(request, branch_id):
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    emp = getattr(request.user, "employee_profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    can_switch = (
        is_owner
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "call_center_access")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )
    if not can_switch:
        return redirect("branch_dashboard")

    if branch_id == 0 or str(branch_id) == "all":
        can_view_hq = (
            is_owner
            or user_has_perm(request.user, "view_hq_dashboard")
            or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
            or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
        )
        if can_view_hq:
            request.session["active_branch_id"] = None
            return redirect("dashboard")
        return redirect("branch_dashboard")
    else:
        branch = get_object_or_404(Branch, id=branch_id, tenant=tenant)
        request.session["active_branch_id"] = branch.id
        return redirect("branch_dashboard")


# ==========================================
# SAAS PLATFORM ADMIN (SUPER ADMIN)
# ==========================================

@login_required
def platform_dashboard_view(request):
    """Graceful redirect for deprecated /platform/ URL to Django Admin or dashboard."""
    profile = getattr(request.user, "profile", None)
    if request.user.is_superuser or (profile and profile.is_platform_admin):
        return redirect("/admin/")
    return redirect("dashboard")


@login_required
def switch_tenant_view(request, tenant_id):
    profile = getattr(request.user, "profile", None)
    if not (request.user.is_superuser or (profile and profile.is_platform_admin)):
        return HttpResponseForbidden("غير مصرح بالتبديل بين المنشآت")

    tenant = get_object_or_404(Tenant, id=tenant_id)
    request.session["active_tenant_id"] = tenant.id
    request.session["active_branch_id"] = None  # Clear branch selection to land on HQ
    return redirect("dashboard")


# ==========================================
# 1. OWNER / HQ DASHBOARD (SCOPED TO TENANT)
# ==========================================



def branch_dashboard_view(request):
    if not user_has_perm(request.user, "view_branch_dashboard"):
        return HttpResponseForbidden("غير مصرح لك بالوصول إلى لوحة تحكم الفرع")

    tenant = get_active_tenant(request)
    branch = get_active_branch(request)
    if not branch:
        first_b = Branch.objects.filter(tenant=tenant).first()
        if first_b:
            request.session["active_branch_id"] = first_b.id
            branch = first_b
        else:
            return redirect("branches")

    now = timezone.now()
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Branch orders today
    branch_orders_today = Order.objects.filter(tenant=tenant, branch=branch, created_at__gte=start_of_today).exclude(status="cancelled")
    sales_today = branch_orders_today.aggregate(t=Sum("total"))["t"] or Decimal("0")
    orders_count_today = branch_orders_today.count()

    # Kitchen active orders
    kitchen_pending_count = Order.objects.filter(
        tenant=tenant,
        branch=branch,
        status__in=["new", "preparing"]
    ).count()

    # Active deliveries for this branch
    active_deliveries_count = Order.objects.filter(
        tenant=tenant,
        branch=branch,
        order_type="delivery",
        status__in=["new", "preparing", "ready", "out_for_delivery"]
    ).count()

    # Branch low stock count
    branch_low_stock = InventoryItem.objects.filter(tenant=tenant, branch=branch, quantity__lte=F("min_quantity"))
    low_stock_count = branch_low_stock.count()

    # Branch employees
    employees_count = Employee.objects.filter(tenant=tenant, branch=branch).count()

    # Recent orders for this branch
    recent_orders = Order.objects.filter(tenant=tenant, branch=branch).order_by("-id")[:8]

    # Live kitchen queue preview
    kitchen_preview = Order.objects.filter(
        tenant=tenant,
        branch=branch,
        status__in=["new", "preparing"]
    ).prefetch_related("items").order_by("created_at")[:4]

    kitchen_preview_data = []
    for ko in kitchen_preview:
        elapsed = int((now - ko.created_at).total_seconds() / 60)
        kitchen_preview_data.append({
            "order": ko,
            "elapsed_minutes": elapsed,
        })

    context = {
        "tenant": tenant,
        "branch": branch,
        "sales_today": sales_today,
        "orders_today": orders_count_today,
        "kitchen_pending_count": kitchen_pending_count,
        "active_deliveries_count": active_deliveries_count,
        "low_stock_count": low_stock_count,
        "employees_count": employees_count,
        "recent_orders": recent_orders,
        "kitchen_preview_data": kitchen_preview_data,
        "branch_low_stock": branch_low_stock[:5],
    }
    return render(request, "branch_dashboard.html", context)


# ==========================================
# 3. KITCHEN DISPLAY SCREEN (KDS - المطبخ) & REAL-TIME SSE
# ==========================================



def branches_view(request):
    if not user_has_perm(request.user, "manage_branches"):
        return HttpResponseForbidden("غير مصرح لك بالوصول لإدارة الفروع")

    tenant = get_active_tenant(request)
    start_of_today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    branches = Branch.objects.filter(tenant=tenant).prefetch_related("delivery_areas").order_by("id")

    emp_counts = dict(
        Employee.objects.filter(tenant=tenant, branch__isnull=False)
        .values("branch_id")
        .annotate(c=Count("id"))
        .values_list("branch_id", "c")
    )
    sales_qs = (
        Order.objects.filter(tenant=tenant, created_at__gte=start_of_today, branch__isnull=False)
        .values("branch_id")
        .annotate(
            total_sales=Sum("total", filter=~Q(status="cancelled")),
            orders_cnt=Count("id")
        )
    )
    sales_map = {row["branch_id"]: row for row in sales_qs}

    branch_list = []
    for b in branches:
        emp_count = emp_counts.get(b.id, 0)
        s_info = sales_map.get(b.id, {})
        sales = s_info.get("total_sales") or Decimal("0")
        orders_count = s_info.get("orders_cnt", 0)
        branch_list.append({
            "branch": b,
            "employees_count": emp_count,
            "sales_today": sales,
            "orders_today": orders_count,
            "areas_count": b.delivery_areas.count(),
            "areas": list(b.delivery_areas.all()),
        })

    from core.currencies import CURRENCIES_DATA
    currencies_list = [
        {
            "code": code,
            "name_ar": info["name_ar"],
            "name_en": info["name_en"],
            "symbol_ar": info["symbol_ar"],
            "symbol_en": info["symbol_en"],
            "label": f"{info['name_ar']} ({code} - {info['symbol_ar']})"
        }
        for code, info in CURRENCIES_DATA.items()
    ]

    context = {
        "tenant": tenant,
        "branches_data": branch_list,
        "currencies_list": currencies_list,
        "default_currency": tenant.default_currency if tenant else "SAR",
    }
    return render(request, "branches.html", context)




def api_create_branch(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (user_has_perm(request.user, "branch_manage_branches") or user_has_perm(request.user, "manage_branches")):
        return JsonResponse({"error": "غير مصرح لك بإنشاء فروع جديدة"}, status=403)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    name = str(data.get("name", "")).strip()
    if not name:
        return JsonResponse({"error": "اسم الفرع مطلوب"}, status=400)

    if tenant and not tenant.can_add_branch():
        max_b = tenant.subscription_plan.max_branches if tenant.subscription_plan else 0
        return JsonResponse({
            "error": f"لقد استنفدت الحد الأقصى للفروع المسموح بها في باقتك الحالية ({max_b} فروع). يرجى ترقية باقة الاشتراك لإضافة فروع جديدة."
        }, status=400)

    lat = data.get("latitude")
    lng = data.get("longitude")
    polygon = data.get("polygon", [])
    radius = data.get("delivery_radius_km", 5.0)

    cur_choice = str(data.get("currency") or (tenant.default_currency if tenant else "SAR")).strip().upper()
    from core.currencies import CURRENCIES_DATA
    if cur_choice not in CURRENCIES_DATA:
        cur_choice = tenant.default_currency if tenant else "SAR"

    branch = Branch.objects.create(
        tenant=tenant,
        name=name,
        city=data.get("city", "الرياض"),
        address=data.get("address", ""),
        phone=data.get("phone", ""),
        currency=cur_choice,
        latitude=Decimal(str(lat)) if lat is not None and str(lat).strip() != "" else None,
        longitude=Decimal(str(lng)) if lng is not None and str(lng).strip() != "" else None,
        delivery_polygon=polygon if isinstance(polygon, list) else [],
        delivery_radius_km=Decimal(str(radius or 5.0)),
        tax_percentage=max(Decimal("0.00"), Decimal(str(data.get("tax_percentage") or 15.0))),
        is_tax_inclusive=bool(data.get("is_tax_inclusive", True)),
        cancellation_window_minutes=max(1, int(data.get("cancellation_window_minutes") or 10)),
        status="active",
    )

    # Process initial delivery areas / compounds if provided
    areas_data = data.get("delivery_areas") or data.get("areas") or []
    if isinstance(areas_data, list):
        for a in areas_data:
            a_name = str(a.get("name", "")).strip()
            if not a_name:
                continue
            DeliveryArea.objects.create(
                branch=branch,
                name=a_name,
                area_type=a.get("area_type", "compound"),
                delivery_fee=Decimal(str(a.get("delivery_fee") or 8.0)),
                estimated_time_minutes=int(a.get("estimated_time_minutes") or 35),
                notes=str(a.get("notes", "")).strip(),
                is_active=True,
            )

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="branch_created",
        target_model="Branch",
        target_id=branch.id,
        description=f"إنشاء الفرع الجديد «{branch.name}» في مدينة «{branch.city}»",
        ip_address=_get_client_ip(request),
    )

    return JsonResponse({
        "ok": True,
        "id": branch.id,
        "name": branch.name,
        "areas_count": branch.delivery_areas.count()
    })


@login_required
def api_branch_delivery_areas(request, branch_id):
    tenant = get_active_tenant(request)
    branch = get_object_or_404(Branch, tenant=tenant, id=branch_id)

    if request.method == "GET":
        areas = list(branch.delivery_areas.all().values(
            "id", "name", "area_type", "delivery_fee", "estimated_time_minutes", "is_active", "notes"
        ))
        return JsonResponse({
            "ok": True,
            "branch": {
                "id": branch.id,
                "name": branch.name,
                "city": branch.city,
                "latitude": float(branch.latitude) if branch.latitude else None,
                "longitude": float(branch.longitude) if branch.longitude else None,
                "delivery_polygon": branch.delivery_polygon,
                "delivery_radius_km": float(branch.delivery_radius_km),
                "delivery_base_fee": float(branch.delivery_base_fee),
                "delivery_base_km": float(branch.delivery_base_km),
                "delivery_per_km_fee": float(branch.delivery_per_km_fee),
                "min_order_tier1_km": float(branch.min_order_tier1_km),
                "min_order_tier1_amount": float(branch.min_order_tier1_amount),
                "min_order_tier2_km": float(branch.min_order_tier2_km),
                "min_order_tier2_amount": float(branch.min_order_tier2_amount),
                "min_order_tier3_amount": float(branch.min_order_tier3_amount),
                "currency": branch.currency,
                "currency_symbol": branch.get_currency_symbol_ar(),
                "tax_percentage": float(branch.tax_percentage),
                "is_tax_inclusive": bool(branch.is_tax_inclusive),
                "cancellation_window_minutes": int(branch.cancellation_window_minutes),
            },
            "areas": areas
        })

    elif request.method == "POST":
        if tenant and not (tenant.has_feature("delivery_management") or tenant.has_feature("delivery")):
            return JsonResponse({"error": "ميزة إدارة مناطق التوصيل غير مفعلة في باقة اشتراك هذا المطعم. يرجى ترقية الباقة لتفعيلها."}, status=403)

        profile = getattr(request.user, "profile", None)
        emp = getattr(request.user, "employee_profile", None)
        is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

        if not is_owner_or_super and not (user_has_perm(request.user, "delivery_manage_zones") or user_has_perm(request.user, "manage_branches")):
            return JsonResponse({"error": "غير مصرح لك بإدارة وتعديل مناطق التوصيل"}, status=403)

        can_cross = (
            is_owner_or_super
            or user_has_perm(request.user, "branch_switch_branches")
            or user_has_perm(request.user, "manage_branches")
            or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
            or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
        )
        if not can_cross and profile and profile.branch and branch != profile.branch:
            return JsonResponse({"error": "غير مصرح لك بتعديل مناطق التوصيل لفرع آخر"}, status=403)

        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

        action = data.get("action", "add")
        if action == "add":
            name = str(data.get("name", "")).strip()
            if not name:
                return JsonResponse({"error": "اسم المنطقة أو الكومبوند مطلوب"}, status=400)
            fee_val = max(Decimal("0"), Decimal(str(data.get("delivery_fee") or 8.0)))
            area = DeliveryArea.objects.create(
                branch=branch,
                name=name,
                area_type=data.get("area_type", "compound"),
                delivery_fee=fee_val,
                estimated_time_minutes=int(data.get("estimated_time_minutes") or 35),
                notes=str(data.get("notes", "")).strip(),
                is_active=True
            )
            log_audit_event(
                tenant=tenant,
                user=request.user,
                action="delivery_area_created",
                target_model="DeliveryArea",
                target_id=area.id,
                description=f"إضافة منطقة التوصيل «{area.name}» برسوم {area.delivery_fee} ر.س لفرع «{branch.name}»",
                ip_address=_get_client_ip(request),
            )
            return JsonResponse({
                "ok": True,
                "area": {
                    "id": area.id,
                    "name": area.name,
                    "area_type": area.area_type,
                    "delivery_fee": str(area.delivery_fee),
                    "estimated_time_minutes": area.estimated_time_minutes,
                    "notes": area.notes
                }
            })

        elif action == "delete":
            area_id = data.get("area_id")
            del_target = DeliveryArea.objects.filter(branch=branch, id=area_id).first()
            del_name = del_target.name if del_target else str(area_id)
            DeliveryArea.objects.filter(branch=branch, id=area_id).delete()
            log_audit_event(
                tenant=tenant,
                user=request.user,
                action="delivery_area_deleted",
                target_model="DeliveryArea",
                target_id=area_id,
                description=f"حذف منطقة التوصيل «{del_name}» من فرع «{branch.name}»",
                ip_address=_get_client_ip(request),
            )
            return JsonResponse({"ok": True})

        elif action == "save_zone":
            lat = data.get("latitude")
            lng = data.get("longitude")
            polygon = data.get("polygon")
            radius = data.get("delivery_radius_km")

            if lat is not None and str(lat).strip():
                branch.latitude = Decimal(str(lat))
            if lng is not None and str(lng).strip():
                branch.longitude = Decimal(str(lng))
            if polygon is not None and isinstance(polygon, list):
                branch.delivery_polygon = polygon
            if radius is not None:
                branch.delivery_radius_km = Decimal(str(radius))
            if "delivery_base_fee" in data:
                branch.delivery_base_fee = max(Decimal("0.00"), Decimal(str(data["delivery_base_fee"] or 0)))
            if "delivery_base_km" in data:
                branch.delivery_base_km = max(Decimal("0.10"), Decimal(str(data["delivery_base_km"] or 1)))
            if "delivery_per_km_fee" in data:
                branch.delivery_per_km_fee = max(Decimal("0.00"), Decimal(str(data["delivery_per_km_fee"] or 0)))
            if "min_order_tier1_km" in data:
                branch.min_order_tier1_km = max(Decimal("0.10"), Decimal(str(data["min_order_tier1_km"] or 3)))
            if "min_order_tier1_amount" in data:
                branch.min_order_tier1_amount = max(Decimal("0.00"), Decimal(str(data["min_order_tier1_amount"] or 0)))
            if "min_order_tier2_km" in data:
                branch.min_order_tier2_km = max(Decimal("0.10"), Decimal(str(data["min_order_tier2_km"] or 6)))
            if "min_order_tier2_amount" in data:
                branch.min_order_tier2_amount = max(Decimal("0.00"), Decimal(str(data["min_order_tier2_amount"] or 0)))
            if "min_order_tier3_amount" in data:
                branch.min_order_tier3_amount = max(Decimal("0.00"), Decimal(str(data["min_order_tier3_amount"] or 0)))
            if "tax_percentage" in data:
                branch.tax_percentage = max(Decimal("0.00"), Decimal(str(data["tax_percentage"] or 0)))
            if "is_tax_inclusive" in data:
                branch.is_tax_inclusive = bool(data["is_tax_inclusive"])
            if "cancellation_window_minutes" in data:
                branch.cancellation_window_minutes = max(1, int(data["cancellation_window_minutes"] or 10))
            branch.save()
            log_audit_event(
                tenant=tenant,
                user=request.user,
                action="branch_zone_updated",
                target_model="Branch",
                target_id=branch.id,
                description=f"تحديث نطاق ومضلع التوصيل وقواعد التسعير لفرع «{branch.name}» (نصف القطر: {branch.delivery_radius_km} كم)",
                ip_address=_get_client_ip(request),
            )
            return JsonResponse({"ok": True, "message": "تم حفظ مضلع الزون وإحداثيات وقواعد تسعير الفرع بنجاح"})

        elif action == "save_pricing":
            if "delivery_base_fee" in data:
                branch.delivery_base_fee = max(Decimal("0.00"), Decimal(str(data.get("delivery_base_fee") or 0)))
            if "delivery_base_km" in data:
                branch.delivery_base_km = max(Decimal("0.10"), Decimal(str(data.get("delivery_base_km") or 1)))
            if "delivery_per_km_fee" in data:
                branch.delivery_per_km_fee = max(Decimal("0.00"), Decimal(str(data.get("delivery_per_km_fee") or 0)))
            if "min_order_tier1_km" in data:
                branch.min_order_tier1_km = max(Decimal("0.10"), Decimal(str(data.get("min_order_tier1_km") or 3)))
            if "min_order_tier1_amount" in data:
                branch.min_order_tier1_amount = max(Decimal("0.00"), Decimal(str(data.get("min_order_tier1_amount") or 0)))
            if "min_order_tier2_km" in data:
                branch.min_order_tier2_km = max(Decimal("0.10"), Decimal(str(data.get("min_order_tier2_km") or 6)))
            if "min_order_tier2_amount" in data:
                branch.min_order_tier2_amount = max(Decimal("0.00"), Decimal(str(data.get("min_order_tier2_amount") or 0)))
            if "min_order_tier3_amount" in data:
                branch.min_order_tier3_amount = max(Decimal("0.00"), Decimal(str(data.get("min_order_tier3_amount") or 0)))
            if "tax_percentage" in data:
                branch.tax_percentage = max(Decimal("0.00"), Decimal(str(data.get("tax_percentage") or 0)))
            if "is_tax_inclusive" in data:
                branch.is_tax_inclusive = bool(data.get("is_tax_inclusive"))
            if "cancellation_window_minutes" in data:
                branch.cancellation_window_minutes = max(1, int(data.get("cancellation_window_minutes") or 10))
            branch.save()
            log_audit_event(
                tenant=tenant,
                user=request.user,
                action="branch_pricing_updated",
                target_model="Branch",
                target_id=branch.id,
                description=f"تحديث قواعد التسعير وحدود الطلب لفرع «{branch.name}»",
                ip_address=_get_client_ip(request),
            )
            return JsonResponse({
                "ok": True,
                "message": "تم حفظ قواعد تسعير وحدود الطلب للفرع بنجاح",
                "delivery_base_fee": float(branch.delivery_base_fee),
                "delivery_base_km": float(branch.delivery_base_km),
                "delivery_per_km_fee": float(branch.delivery_per_km_fee),
                "min_order_tier1_km": float(branch.min_order_tier1_km),
                "min_order_tier1_amount": float(branch.min_order_tier1_amount),
                "min_order_tier2_km": float(branch.min_order_tier2_km),
                "min_order_tier2_amount": float(branch.min_order_tier2_amount),
                "min_order_tier3_amount": float(branch.min_order_tier3_amount),
                "tax_percentage": float(branch.tax_percentage),
                "is_tax_inclusive": bool(branch.is_tax_inclusive),
                "cancellation_window_minutes": int(branch.cancellation_window_minutes),
            })

        return JsonResponse({"error": "إجراء غير معروف"}, status=400)


@login_required
def api_toggle_branch(request, branch_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (user_has_perm(request.user, "branch_manage_branches") or user_has_perm(request.user, "manage_branches")):
        return JsonResponse({"error": "غير مصرح لك بتغيير حالة الفرع"}, status=403)

    branch = get_object_or_404(Branch, tenant=tenant, id=branch_id)
    emp = getattr(request.user, "employee_profile", None)
    can_cross = (
        is_owner_or_super
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )
    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    if not can_cross and user_branch and branch != user_branch:
        return JsonResponse({"error": "غير مصرح لك بتغيير حالة فرع آخر"}, status=403)

    if branch.status == "closed":
        if tenant and not tenant.can_add_branch():
            max_b = tenant.subscription_plan.max_branches if tenant.subscription_plan else 0
            return JsonResponse({"error": f"لا يمكن إعادة تفعيل الفرع لأنك بلغت الحد الأقصى للفروع النشطة في باقتك الحالية ({max_b} فروع). يرجى ترقية الباقة أولاً."}, status=400)
        branch.status = "active"
    else:
        branch.status = "closed"
    branch.save()

    status_label = "فتح وتنشيط" if branch.status == "active" else "إغلاق مؤقت"
    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="branch_status_toggled",
        target_model="Branch",
        target_id=branch.id,
        description=f"{status_label} الفرع «{branch.name}» (الحالة الجديدة: {branch.status})",
        ip_address=_get_client_ip(request),
    )
    return JsonResponse({"ok": True, "status": branch.status})


@login_required
def api_update_branch_currency(request, branch_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner_or_super and not (user_has_perm(request.user, "manage_branches") or user_has_perm(request.user, "branch_manage_branches")):
        return JsonResponse({"error": "غير مصرح لك بتغيير عملة الفرع"}, status=403)

    branch = get_object_or_404(Branch, tenant=tenant, id=branch_id)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    cur_code = str(data.get("currency", "")).strip().upper()
    from core.currencies import CURRENCIES_DATA, get_currency_info
    if cur_code not in CURRENCIES_DATA:
        return JsonResponse({"error": f"العملة «{cur_code}» غير صالحة أو غير مدعومة في النظام."}, status=400)

    old_cur = branch.currency
    branch.currency = cur_code
    branch.save(update_fields=["currency"])

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="branch_currency_updated",
        target_model="Branch",
        target_id=branch.id,
        description=f"تغيير عملة الفرع «{branch.name}» من {old_cur} إلى {cur_code} ({branch.get_currency_name_ar()})",
        ip_address=_get_client_ip(request),
    )

    info = get_currency_info(cur_code)
    return JsonResponse({
        "ok": True,
        "branch_id": branch.id,
        "currency": branch.currency,
        "currency_name": branch.get_currency_name_ar(),
        "currency_symbol": branch.get_currency_symbol_ar(),
        "message": f"تم تغيير عملة فرع «{branch.name}» إلى {branch.get_currency_name_ar()} ({cur_code}) بنجاح."
    })


@login_required
def api_update_tenant_currency(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner_or_super:
        return JsonResponse({"error": "تغيير العملة العامة للمطعم متاح للمدير والمالك فقط"}, status=403)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    cur_code = str(data.get("currency", "")).strip().upper()
    apply_all = bool(data.get("apply_to_all_branches", True))

    from core.currencies import CURRENCIES_DATA, get_currency_info
    if cur_code not in CURRENCIES_DATA:
        return JsonResponse({"error": f"العملة «{cur_code}» غير صالحة أو غير مدعومة في النظام."}, status=400)

    old_cur = tenant.default_currency
    tenant.default_currency = cur_code
    tenant.save(update_fields=["default_currency"])

    updated_branches = 0
    if apply_all:
        updated_branches = Branch.objects.filter(tenant=tenant).update(currency=cur_code)

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="tenant_currency_updated",
        target_model="Tenant",
        target_id=tenant.id,
        description=f"تغيير العملة الافتراضية للمطعم من {old_cur} إلى {cur_code} وتطبيقها على {updated_branches} فروع",
        ip_address=_get_client_ip(request),
    )

    return JsonResponse({
        "ok": True,
        "currency": tenant.default_currency,
        "currency_name": tenant.get_currency_name_ar(),
        "currency_symbol": tenant.get_currency_symbol_ar(),
        "updated_branches_count": updated_branches,
        "message": f"تم اعتماد {tenant.get_currency_name_ar()} ({cur_code}) كعملة افتراضية للمطعم وتحديث {updated_branches} فرع بنجاح."
    })




def _can_manage_restaurant_profile(user):
    """
    Check if the user has permission to view/manage HQ restaurant profile.
    Owner (is_owner) and HQ Manager (view_hq_dashboard or system_manage_settings) are permitted.
    Branch staff (Cashier, Kitchen, Driver, Branch Manager without HQ perms) are strictly forbidden.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    if profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin):
        return True
    return (
        user_has_perm(user, "view_hq_dashboard")
        or user_has_perm(user, "system_manage_settings")
    )


def _update_tenant_profile_data(tenant, data, files=None, require_name=True):
    """
    Validate and persist restaurant profile fields for active tenant.
    Returns (tenant, None) on success, or (None, error_str) on validation error.
    """
    ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
    MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2MB
    MAX_COVER_SIZE = 5 * 1024 * 1024  # 5MB

    # 1. Name
    if "name" in data:
        name = str(data.get("name", "")).strip()
        if require_name and not name:
            return None, "اسم المطعم مطلوب ولا يمكن تركه فارغاً"
        if name:
            if len(name) > 255:
                return None, "اسم المطعم يجب ألا يتجاوز 255 حرفاً"
            tenant.name = name
    elif require_name and not tenant.name:
        return None, "اسم المطعم مطلوب ولا يمكن تركه فارغاً"

    # 2. Bio / Description
    if "bio" in data:
        bio = str(data.get("bio", "")).strip()
        if len(bio) > 255:
            return None, "النبذة التعريفية يجب ألا تتجاوز 255 حرفاً"
        tenant.bio = bio

    # 3. Phone
    if "phone" in data:
        phone = str(data.get("phone", "")).strip()
        if len(phone) > 50:
            return None, "رقم الهاتف يجب ألا يتجاوز 50 حرفاً"
        tenant.phone = phone

    # 4. Email
    if "email" in data:
        email = str(data.get("email", "")).strip()
        if email:
            if len(email) > 254:
                return None, "البريد الإلكتروني يجب ألا يتجاوز 254 حرفاً"
            try:
                validate_email(email)
            except ValidationError:
                return None, "صيغة البريد الإلكتروني غير صالحة"
        tenant.email = email

    # 5. HQ Address
    if "address" in data:
        address = str(data.get("address", "")).strip()
        if len(address) > 255:
            return None, "العنوان يجب ألا يتجاوز 255 حرفاً"
        tenant.address = address

    # 6. Primary Brand Color (hex #RRGGBB)
    if "brand_color" in data:
        brand_color = str(data.get("brand_color", "")).strip()
        if brand_color:
            if not re.match(r"^#[0-9a-fA-F]{6}$", brand_color):
                return None, "صيغة كود اللون غير صحيحة، يجب أن تكون بتنسيق #RRGGBB (مثل #6366F1)"
            tenant.brand_color = brand_color

    # 7. Logo emoji (if provided)
    if "logo_emoji" in data:
        logo_emoji = str(data.get("logo_emoji", "")).strip()
        if logo_emoji:
            tenant.logo_emoji = logo_emoji[:20]

    # 8. Logo image file upload
    if files and "logo_image" in files:
        logo_file = files["logo_image"]
        if logo_file:
            if logo_file.size > MAX_LOGO_SIZE:
                return None, "حجم ملف الشعار يجب ألا يتجاوز 2 ميجابايت"
            ext = os.path.splitext(logo_file.name)[1].lower()
            if ext not in ALLOWED_IMAGE_EXTS:
                return None, "صيغة الشعار غير مدعومة. الصيغ المسموحة هي: PNG, JPG, JPEG, WEBP, SVG"
            tenant.logo_image = logo_file

    # 9. Cover banner file upload
    if files and "cover_image" in files:
        cover_file = files["cover_image"]
        if cover_file:
            if cover_file.size > MAX_COVER_SIZE:
                return None, "حجم ملف صورة الغلاف يجب ألا يتجاوز 5 ميجابايت"
            ext = os.path.splitext(cover_file.name)[1].lower()
            if ext not in ALLOWED_IMAGE_EXTS:
                return None, "صيغة صورة الغلاف غير مدعومة. الصيغ المسموحة هي: PNG, JPG, JPEG, WEBP, SVG"
            tenant.cover_image = cover_file

    tenant.save()
    return tenant, None


@login_required
def restaurant_profile_view(request):
    """
    Dedicated Central HQ Restaurant Profile View.
    Renders current restaurant identity, visual branding, and contact details.
    Handles profile updates via standard form POST and JSON/AJAX.
    Strictly verifies HQ RBAC and active tenant isolation.
    """
    tenant = get_active_tenant(request)
    if not tenant:
        return HttpResponseBadRequest("المنشأة غير موجودة")

    if not _can_manage_restaurant_profile(request.user):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.content_type == "application/json":
            return JsonResponse({"error": "غير مصرح لك بإدارة الملف التعريفي للمطعم"}, status=403)
        return HttpResponseForbidden("غير مصرح لك بإدارة الملف التعريفي للمطعم")

    is_ajax = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
        or request.content_type == "application/json"
    )

    if request.method == "POST":
        if request.content_type == "application/json" and request.body:
            try:
                data = json.loads(request.body.decode("utf-8"))
            except Exception:
                return JsonResponse({"error": "تنسيق JSON غير صالح"}, status=400)
        else:
            data = request.POST

        updated_tenant, err = _update_tenant_profile_data(tenant, data, request.FILES, require_name=True)
        if err:
            if is_ajax:
                return JsonResponse({"error": err, "success": False, "status": "error"}, status=400)
            context = {
                "tenant": tenant,
                "error_message": err,
                "active_tab": "restaurant_profile",
            }
            return render(request, "restaurant_profile.html", context, status=400)

        # Audit Event
        try:
            log_audit_event(
                tenant=updated_tenant,
                user=request.user,
                action="update",
                target_model="Tenant",
                target_id=str(updated_tenant.id),
                description=f"تحديث بيانات وهوية المطعم: {updated_tenant.name}",
                ip_address=_get_client_ip(request)
            )
        except Exception as e:
            logger.warning("Audit event log failed: %s", e)

        tenant_payload = {
            "id": updated_tenant.id,
            "name": updated_tenant.name,
            "slug": updated_tenant.slug,
            "bio": updated_tenant.bio,
            "phone": updated_tenant.phone,
            "email": updated_tenant.email,
            "address": updated_tenant.address,
            "brand_color": updated_tenant.brand_color,
            "logo_emoji": updated_tenant.logo_emoji,
            "logo_url": updated_tenant.logo_image.url if updated_tenant.logo_image else "",
            "cover_url": updated_tenant.cover_image.url if updated_tenant.cover_image else "",
        }

        if is_ajax:
            return JsonResponse({
                "status": "success",
                "success": True,
                "message": "تم حفظ بيانات وهوية المطعم بنجاح",
                "tenant": tenant_payload,
            })

        from django.contrib import messages
        messages.success(request, "تم حفظ بيانات وهوية المطعم بنجاح")
        return redirect("restaurant_profile")

    context = {
        "tenant": tenant,
        "active_tab": "restaurant_profile",
    }
    return render(request, "restaurant_profile.html", context)


@login_required
def api_restaurant_profile_update(request):
    """
    Dedicated JSON API endpoint to update restaurant profile details.
    Supports name, bio, phone, email, address, brand_color, logo_image, cover_image.
    Strictly verifies HQ RBAC and active tenant isolation.
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"error": "المنشأة غير موجودة"}, status=400)

    if not _can_manage_restaurant_profile(request.user):
        return JsonResponse({"error": "غير مصرح لك بإدارة الملف التعريفي للمطعم"}, status=403)

    if request.content_type == "application/json" and request.body:
        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse({"error": "تنسيق JSON غير صالح"}, status=400)
    else:
        data = request.POST

    updated_tenant, err = _update_tenant_profile_data(tenant, data, request.FILES, require_name=True)
    if err:
        return JsonResponse({"error": err, "success": False, "status": "error"}, status=400)

    try:
        log_audit_event(
            tenant=updated_tenant,
            user=request.user,
            action="update",
            target_model="Tenant",
            target_id=str(updated_tenant.id),
            description=f"تحديث بيانات وهوية المطعم (API): {updated_tenant.name}",
            ip_address=_get_client_ip(request)
        )
    except Exception as e:
        logger.warning("Audit event log failed: %s", e)

    return JsonResponse({
        "status": "success",
        "success": True,
        "message": "تم تحديث هوية وبيانات المطعم بنجاح",
        "tenant": {
            "id": updated_tenant.id,
            "name": updated_tenant.name,
            "slug": updated_tenant.slug,
            "bio": updated_tenant.bio,
            "phone": updated_tenant.phone,
            "email": updated_tenant.email,
            "address": updated_tenant.address,
            "brand_color": updated_tenant.brand_color,
            "logo_emoji": updated_tenant.logo_emoji,
            "logo_url": updated_tenant.logo_image.url if updated_tenant.logo_image else "",
            "cover_url": updated_tenant.cover_image.url if updated_tenant.cover_image else "",
        }
    })


@login_required
def api_update_tenant_branding(request):
    """
    Update restaurant logo, cover, bio, brand color, phone, email, address, and name.
    Enforces HQ RBAC (Owner or HQ Manager).
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"error": "منشأة غير موجودة"}, status=400)

    if not _can_manage_restaurant_profile(request.user):
        return JsonResponse({"error": "غير مصرح لك بتعديل هوية المطعم"}, status=403)

    if request.content_type == "application/json" and request.body:
        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse({"error": "تنسيق JSON غير صالح"}, status=400)
    else:
        data = request.POST

    updated_tenant, err = _update_tenant_profile_data(tenant, data, request.FILES, require_name=False)
    if err:
        return JsonResponse({"error": err, "status": "error"}, status=400)

    try:
        log_audit_event(
            tenant=updated_tenant,
            user=request.user,
            action="update",
            target_model="Tenant",
            target_id=str(updated_tenant.id),
            description=f"تحديث هوية وشعار المطعم: {updated_tenant.name}",
            ip_address=_get_client_ip(request)
        )
    except Exception as e:
        logger.warning("Audit event log failed: %s", e)

    return JsonResponse({
        "status": "success",
        "message": "تم تحديث هوية وشعار المطعم بنجاح",
        "tenant": {
            "name": updated_tenant.name,
            "bio": updated_tenant.bio,
            "phone": updated_tenant.phone,
            "email": updated_tenant.email,
            "address": updated_tenant.address,
            "brand_color": updated_tenant.brand_color,
            "logo_emoji": updated_tenant.logo_emoji,
            "logo_url": updated_tenant.logo_image.url if updated_tenant.logo_image else "",
            "cover_url": updated_tenant.cover_image.url if updated_tenant.cover_image else "",
        }
    })


@login_required
def api_update_custom_domain(request):
    """Bind or clear custom domain for restaurant digital menu."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"error": "منشأة غير موجودة"}, status=400)

    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner:
        return JsonResponse({"error": "مقتصر على مالك المنشأة فقط"}, status=403)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else request.POST
    except Exception:
        data = request.POST

    domain = str(data.get("custom_domain", "")).strip().lower()
    # Strip http:// or https:// or trailing slashes
    import re
    domain = re.sub(r"^https?://", "", domain).strip("/")
    if domain:
        existing = Tenant.objects.filter(custom_domain__iexact=domain).exclude(id=tenant.id).first()
        if existing:
            return JsonResponse({"error": f"هذا النطاق «{domain}» مرتبط بالفعل بمنشأة أخرى."}, status=400)
        tenant.custom_domain = domain
    else:
        tenant.custom_domain = None

    tenant.save(update_fields=["custom_domain"])
    return JsonResponse({
        "status": "success",
        "message": "تم حفظ النطاق المخصص بنجاح" if domain else "تمت إزالة النطاق المخصص بنجاح",
        "custom_domain": tenant.custom_domain or "",
    })

