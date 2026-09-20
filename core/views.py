import json
from decimal import Decimal
from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.utils import timezone
from django.db.models import Sum, Count, F, Q

from .models import (
    Tenant,
    Branch,
    Employee,
    MenuItem,
    InventoryItem,
    Customer,
    Order,
    OrderItem,
    UserProfile,
    BranchMenuAvailability,
    DeliveryArea,
)


def get_active_tenant(request):
    """Resolve the active tenant for the current request."""
    if hasattr(request, "tenant") and request.tenant:
        return request.tenant

    profile = getattr(request.user, "profile", None)
    if profile and profile.tenant:
        return profile.tenant

    # Platform admin / Superuser session override
    active_t_id = request.session.get("active_tenant_id")
    if active_t_id:
        t = Tenant.objects.filter(id=active_t_id, is_active=True).first()
        if t:
            return t

    return Tenant.objects.filter(is_active=True).first()


def get_active_branch(request):
    """Resolve active branch within the current tenant."""
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner and profile and profile.branch:
        return profile.branch

    active_id = request.session.get("active_branch_id")
    if active_id:
        qs = Branch.objects.filter(id=active_id)
        if tenant:
            qs = qs.filter(tenant=tenant)
        return qs.first()

    return None


# ==========================================
# AUTHENTICATION & LOGIN (DUAL MODE)
# ==========================================

def login_view(request):
    if request.user.is_authenticated:
        profile = getattr(request.user, "profile", None)
        if profile and profile.is_platform_admin and not request.session.get("active_tenant_id"):
            return redirect("platform_dashboard")
        return redirect("dashboard")

    error_message = None
    if request.method == "POST":
        auth_type = request.POST.get("auth_type", "credentials")

        if auth_type == "pin":
            # Mode B: Quick Shift PIN Login for shift workers
            code = request.POST.get("employee_code", "").strip()
            pin = request.POST.get("pin", "").strip()

            if not code or not pin:
                error_message = "يرجى إدخال كود الموظف ورمز PIN المكون من 4 أرقام"
            else:
                emp_candidates = Employee.objects.filter(employee_code=code, status="active").select_related("tenant", "branch", "user")
                matched_emp = None
                for emp in emp_candidates:
                    if emp.check_pin(pin):
                        matched_emp = emp
                        break

                if matched_emp:
                    # Auto-provision user account if missing
                    user_to_login = matched_emp.user
                    if not user_to_login:
                        tenant_slug = matched_emp.tenant.slug if matched_emp.tenant else "sys"
                        username = f"emp_{tenant_slug}_{matched_emp.employee_code}"
                        user_to_login, _ = User.objects.get_or_create(username=username, defaults={"first_name": matched_emp.name})
                        user_to_login.set_password("admin123")
                        user_to_login.save()
                        matched_emp.user = user_to_login
                        matched_emp.save()

                    # Ensure UserProfile matches employee
                    UserProfile.objects.update_or_create(
                        user=user_to_login,
                        defaults={
                            "tenant": matched_emp.tenant,
                            "branch": matched_emp.branch,
                            "role": matched_emp.role,
                        }
                    )

                    login(request, user_to_login)
                    if matched_emp.tenant:
                        request.session["active_tenant_id"] = matched_emp.tenant.id
                    if matched_emp.branch:
                        request.session["active_branch_id"] = matched_emp.branch.id
                    request.session["active_employee_id"] = matched_emp.id

                    # Route by shift role
                    if matched_emp.role == "cashier":
                        return redirect("pos")
                    elif matched_emp.role == "chef":
                        return redirect("kitchen")
                    elif matched_emp.role == "driver":
                        return redirect("delivery")
                    elif matched_emp.role == "manager":
                        return redirect("branch_dashboard")
                    else:
                        return redirect("branch_dashboard")
                else:
                    error_message = "كود الموظف أو رمز PIN غير صحيح"

        else:
            # Mode A: Standard Credentials
            username = request.POST.get("username", "").strip()
            password = request.POST.get("password", "")
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                profile = getattr(user, "profile", None)

                # Route platform admin
                if profile and profile.is_platform_admin:
                    return redirect("platform_dashboard")

                # Bind tenant
                if profile and profile.tenant:
                    request.session["active_tenant_id"] = profile.tenant.id

                # Route branch-locked staff
                if profile and profile.role != "owner" and profile.branch:
                    request.session["active_branch_id"] = profile.branch.id
                    if profile.role == "cashier":
                        return redirect("pos")
                    elif profile.role == "chef":
                        return redirect("kitchen")
                    elif profile.role == "driver":
                        return redirect("delivery")
                    return redirect("branch_dashboard")

                return redirect("dashboard")
            else:
                error_message = "اسم المستخدم أو كلمة المرور غير صحيحة"

    return render(request, "login.html", {"error": error_message})


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def switch_branch_view(request, branch_id):
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner:
        return redirect("branch_dashboard")

    if branch_id == 0 or str(branch_id) == "all":
        request.session["active_branch_id"] = None
        return redirect("dashboard")
    else:
        branch = get_object_or_404(Branch, id=branch_id, tenant=tenant)
        request.session["active_branch_id"] = branch.id
        return redirect("branch_dashboard")


# ==========================================
# SAAS PLATFORM ADMIN (SUPER ADMIN)
# ==========================================

@login_required
def platform_dashboard_view(request):
    profile = getattr(request.user, "profile", None)
    if not (request.user.is_superuser or (profile and profile.is_platform_admin)):
        return HttpResponseForbidden("غير مصرح بالوصول إلى لوحة المنصة العامة")

    tenants = Tenant.objects.all().order_by("-id")
    tenants_data = []
    for t in tenants:
        b_count = Branch.objects.filter(tenant=t).count()
        e_count = Employee.objects.filter(tenant=t).count()
        o_count = Order.objects.filter(tenant=t).count()
        tenants_data.append({
            "tenant": t,
            "branches_count": b_count,
            "employees_count": e_count,
            "orders_count": o_count,
        })

    context = {
        "tenants_data": tenants_data,
        "total_tenants": tenants.count(),
        "total_branches": Branch.objects.count(),
        "total_employees": Employee.objects.count(),
        "total_orders": Order.objects.count(),
    }
    return render(request, "platform_dashboard.html", context)


@login_required
def switch_tenant_view(request, tenant_id):
    profile = getattr(request.user, "profile", None)
    if not (request.user.is_superuser or (profile and profile.is_platform_admin)):
        return HttpResponseForbidden("غير مصرح بالتبديل بين المنشآت")

    tenant = get_object_or_404(Tenant, id=tenant_id)
    request.session["active_tenant_id"] = tenant.id
    request.session["active_branch_id"] = None  # Clear branch selection to land on HQ
    return redirect("dashboard")


@login_required
def api_create_tenant(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    profile = getattr(request.user, "profile", None)
    if not (request.user.is_superuser or (profile and profile.is_platform_admin)):
        return JsonResponse({"error": "غير مصرح"}, status=403)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    name = str(data.get("name", "")).strip()
    slug = str(data.get("slug", "")).strip().lower()
    if not name or not slug:
        return JsonResponse({"error": "اسم المطعم والمعرف (Slug) مطلوبان"}, status=400)

    if Tenant.objects.filter(slug=slug).exists():
        return JsonResponse({"error": "المعرف اللاتيني (Slug) مستخدم بالفعل"}, status=400)

    tenant = Tenant.objects.create(
        name=name,
        slug=slug,
        logo_emoji=data.get("emoji", "🍽️"),
        phone=data.get("phone", ""),
        plan=data.get("plan", "standard"),
        address=data.get("address", ""),
        is_active=True,
    )

    # Provision Initial Owner
    owner_username = str(data.get("owner_username", "")).strip()
    owner_password = str(data.get("owner_password", "")).strip()
    if owner_username and owner_password:
        owner_user, _ = User.objects.get_or_create(username=owner_username, defaults={"first_name": name})
        owner_user.set_password(owner_password)
        owner_user.save()
        UserProfile.objects.update_or_create(
            user=owner_user,
            defaults={"tenant": tenant, "role": "owner", "branch": None}
        )

    return JsonResponse({"ok": True, "tenantId": tenant.id})


# ==========================================
# 1. OWNER / HQ DASHBOARD (SCOPED TO TENANT)
# ==========================================

@login_required
@ensure_csrf_cookie
def dashboard_view(request):
    profile = getattr(request.user, "profile", None)
    is_platform_admin = request.user.is_superuser or (profile and profile.is_platform_admin)

    # If platform admin and no tenant selected, go to platform dashboard
    if is_platform_admin and not request.session.get("active_tenant_id") and request.GET.get("view") != "tenant":
        return redirect("platform_dashboard")

    tenant = get_active_tenant(request)
    active_branch = get_active_branch(request)
    is_owner = is_platform_admin or (profile and profile.role == "owner")

    # If branch-locked or active branch selected, redirect to branch dashboard
    if not is_owner or active_branch is not None:
        return redirect("branch_dashboard")

    now = timezone.now()
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = start_of_today - timedelta(days=6)

    # 1. Orders today across this tenant's branches
    today_orders = Order.objects.filter(tenant=tenant, created_at__gte=start_of_today).exclude(status="cancelled")
    sales_today = today_orders.aggregate(total=Sum("total"))["total"] or Decimal("0")
    orders_count_today = today_orders.count()

    # 2. Active deliveries across tenant
    active_deliveries = Order.objects.filter(
        tenant=tenant,
        created_at__gte=start_of_today,
        order_type="delivery",
        status__in=["new", "preparing", "ready", "out_for_delivery"],
    ).count()

    # 3. Low stock count across tenant
    low_stock = InventoryItem.objects.filter(tenant=tenant, quantity__lte=F("min_quantity")).select_related("branch")
    low_stock_count = low_stock.count()

    # 4. Total employees and payroll for tenant
    total_employees = Employee.objects.filter(tenant=tenant).count()
    total_payroll = Employee.objects.filter(tenant=tenant, status="active").aggregate(s=Sum("salary"))["s"] or Decimal("0")

    # 5. Last 7 days sales series
    week_orders = Order.objects.filter(tenant=tenant, created_at__gte=seven_days_ago).exclude(status="cancelled")
    days_data = []
    arabic_days = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

    max_day_total = Decimal("1")
    for i in range(6, -1, -1):
        d_start = start_of_today - timedelta(days=i)
        d_end = d_start + timedelta(days=1)
        day_total = week_orders.filter(created_at__gte=d_start, created_at__lt=d_end).aggregate(
            t=Sum("total")
        )["t"] or Decimal("0")
        if day_total > max_day_total:
            max_day_total = day_total
        days_data.append({
            "label": "اليوم" if i == 0 else arabic_days[d_start.weekday()],
            "total": float(day_total),
            "is_today": i == 0,
        })

    # 6. Branch performance comparison matrix
    branches = Branch.objects.filter(tenant=tenant, status="active").order_by("id")
    branch_matrix = []
    max_branch_sale = Decimal("1")
    for b in branches:
        b_orders = today_orders.filter(branch=b)
        b_total = b_orders.aggregate(t=Sum("total"))["t"] or Decimal("0")
        b_count = b_orders.count()
        b_emps = Employee.objects.filter(branch=b).count()
        b_low_stock = InventoryItem.objects.filter(branch=b, quantity__lte=F("min_quantity")).count()
        if b_total > max_branch_sale:
            max_branch_sale = b_total
        branch_matrix.append({
            "branch": b,
            "sales_today": float(b_total),
            "orders_today": b_count,
            "employees_count": b_emps,
            "low_stock_count": b_low_stock,
        })

    recent_orders = Order.objects.filter(tenant=tenant).select_related("branch").order_by("-id")[:6]
    top_items_qs = (
        OrderItem.objects.filter(order__tenant=tenant, order__created_at__gte=start_of_today)
        .values("name")
        .annotate(total_qty=Sum("qty"), total_revenue=Sum(F("price") * F("qty")))
        .order_by("-total_qty")[:6]
    )

    week_total = sum(d["total"] for d in days_data)

    context = {
        "tenant": tenant,
        "sales_today": sales_today,
        "orders_today": orders_count_today,
        "active_deliveries": active_deliveries,
        "low_stock_count": low_stock_count,
        "total_employees": total_employees,
        "total_payroll": total_payroll,
        "days_data": days_data,
        "max_day_total": float(max_day_total),
        "week_total": week_total,
        "branch_matrix": branch_matrix,
        "max_branch_sale": float(max_branch_sale),
        "recent_orders": recent_orders,
        "top_items": top_items_qs,
        "low_stock_items": low_stock[:6],
    }
    return render(request, "hq_dashboard.html", context)


# ==========================================
# 2. BRANCH DASHBOARD (SINGLE BRANCH)
# ==========================================

@login_required
@ensure_csrf_cookie
def branch_dashboard_view(request):
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
# 3. KITCHEN DISPLAY SCREEN (KDS - المطبخ)
# ==========================================

@login_required
@ensure_csrf_cookie
def kitchen_view(request):
    tenant = get_active_tenant(request)
    branch = get_active_branch(request)
    now = timezone.now()

    orders_qs = Order.objects.filter(tenant=tenant, status__in=["new", "preparing"]).prefetch_related("items").order_by("created_at")
    if branch:
        orders_qs = orders_qs.filter(branch=branch)

    kitchen_orders = []
    for o in orders_qs:
        elapsed = int((now - o.created_at).total_seconds() / 60)
        kitchen_orders.append({
            "order": o,
            "elapsed_minutes": elapsed,
            "items": o.items.all(),
        })

    context = {
        "tenant": tenant,
        "branch": branch,
        "kitchen_orders": kitchen_orders,
        "total_pending": len(kitchen_orders),
    }
    return render(request, "kitchen.html", context)


# ==========================================
# 4. BRANCH ORDERS VIEW
# ==========================================

@login_required
@ensure_csrf_cookie
def branch_orders_view(request):
    tenant = get_active_tenant(request)
    branch = get_active_branch(request)
    status_filter = request.GET.get("status", "all")
    type_filter = request.GET.get("type", "all")
    search = request.GET.get("q", "").strip()

    orders = Order.objects.filter(tenant=tenant).select_related("branch", "driver").order_by("-id")
    if branch:
        orders = orders.filter(branch=branch)
    if status_filter != "all":
        orders = orders.filter(status=status_filter)
    if type_filter != "all":
        orders = orders.filter(order_type=type_filter)
    if search:
        orders = orders.filter(Q(order_number__icontains=search) | Q(customer_name__icontains=search) | Q(customer_phone__icontains=search))

    context = {
        "tenant": tenant,
        "branch": branch,
        "orders": orders[:50],
        "status_filter": status_filter,
        "type_filter": type_filter,
        "search_query": search,
        "statuses": Order.STATUS_CHOICES,
        "order_types": Order.TYPE_CHOICES,
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

    # If user is branch-locked and not an owner/admin, redirect to branch orders
    if not is_owner and profile and profile.branch:
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

    # Summary metrics for the filtered queryset
    total_orders = orders.count()
    total_revenue = orders.exclude(status="cancelled").aggregate(s=Sum("total"))["s"] or Decimal("0")
    pending_orders = orders.filter(status__in=["new", "preparing", "ready", "out_for_delivery"]).count()
    delivered_orders = orders.filter(status="delivered").count()
    cancelled_orders = orders.filter(status="cancelled").count()

    context = {
        "tenant": tenant,
        "branches": branches,
        "orders": orders[:100],
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

    order = get_object_or_404(
        Order.objects.select_related("branch", "customer", "driver", "tenant").prefetch_related("items__menu_item"),
        tenant=tenant,
        id=order_id
    )

    # If branch-locked and not owner, verify branch
    if not is_owner and profile and profile.branch and order.branch != profile.branch:
        return HttpResponseForbidden("غير مصرح لك بمشاهدة طلبات هذا الفرع")

    context = {
        "tenant": tenant,
        "order": order,
        "items": order.items.all(),
        "is_owner": is_owner,
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

    if not is_owner and profile and profile.branch and order.branch != profile.branch:
        return HttpResponseForbidden("غير مصرح لك بتعديل طلبات هذا الفرع")

    branches = Branch.objects.filter(tenant=tenant) if tenant else Branch.objects.none()
    drivers = Employee.objects.filter(tenant=tenant, role="driver") if tenant else Employee.objects.none()
    menu_items = MenuItem.objects.filter(tenant=tenant, available=True).order_by("category", "name") if tenant else MenuItem.objects.none()

    if request.method == "POST":
        branch_id = request.POST.get("branch_id")
        if branch_id and branch_id != "none":
            order.branch = Branch.objects.filter(tenant=tenant, id=branch_id).first()
        else:
            order.branch = None

        order.order_type = request.POST.get("order_type", order.order_type)
        order.channel = request.POST.get("channel", order.channel)
        order.status = request.POST.get("status", order.status)
        order.customer_name = request.POST.get("customer_name", order.customer_name).strip()
        order.customer_phone = request.POST.get("customer_phone", order.customer_phone).strip()
        order.address = request.POST.get("address", order.address).strip()
        order.notes = request.POST.get("notes", order.notes).strip()
        order.cashier = request.POST.get("cashier", order.cashier).strip()
        order.pay_method = request.POST.get("pay_method", order.pay_method)
        order.paid = request.POST.get("paid") in ["true", "on", "1", True]

        driver_id = request.POST.get("driver_id")
        if driver_id and driver_id != "none":
            order.driver = Employee.objects.filter(tenant=tenant, id=driver_id, role="driver").first()
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
            order.delivery_fee = Decimal(str(request.POST.get("delivery_fee") or ("8" if order.order_type == "delivery" else "0")))
        except Exception:
            order.delivery_fee = Decimal("0")

        try:
            order.discount = Decimal(str(request.POST.get("discount") or "0"))
        except Exception:
            order.discount = Decimal("0")

        order.total = max(Decimal("0"), order.subtotal + order.delivery_fee - order.discount)
        order.save()

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

    order = get_object_or_404(Order, tenant=tenant, id=order_id)
    if not is_owner and profile and profile.branch and order.branch != profile.branch:
        return JsonResponse({"error": "غير مصرح"}, status=403)

    order.status = "cancelled"
    order.save()
    return JsonResponse({"ok": True, "status": "cancelled", "message": f"تم إلغاء الطلب {order.order_number} بنجاح"})


@login_required
def api_delete_order(request, order_id):
    if request.method not in ["POST", "DELETE"]:
        return HttpResponseBadRequest("POST or DELETE required")

    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner:
        return JsonResponse({"error": "غير مصرح بالحذف النهائي إلا للإدارة العامة"}, status=403)

    order = get_object_or_404(Order, tenant=tenant, id=order_id)
    order_number = order.order_number
    order.delete()
    return JsonResponse({"ok": True, "message": f"تم حذف الطلب {order_number} نهائياً من قاعدة البيانات"})


# ==========================================
# 5. BRANCH MENU AVAILABILITY VIEW
# ==========================================

@login_required
@ensure_csrf_cookie
def branch_menu_view(request):
    tenant = get_active_tenant(request)
    branch = get_active_branch(request)
    categories = ["الكل", "أطباق رئيسية", "مشويات", "ساندويتشات", "برجر", "دجاج", "مقبلات", "مشروبات", "حلويات"]
    cat_filter = request.GET.get("cat", "الكل")
    search = request.GET.get("q", "").strip()

    menu_qs = MenuItem.objects.filter(tenant=tenant).order_by("category", "name")
    if cat_filter != "الكل":
        menu_qs = menu_qs.filter(category=cat_filter)
    if search:
        menu_qs = menu_qs.filter(name__icontains=search)

    branch_avail_map = {}
    if branch:
        for av in BranchMenuAvailability.objects.filter(branch=branch):
            branch_avail_map[av.menu_item_id] = av.is_available

    items_data = []
    for item in menu_qs:
        if branch:
            is_avail = branch_avail_map.get(item.id, item.available)
        else:
            is_avail = item.available

        items_data.append({
            "item": item,
            "is_available": is_avail,
        })

    context = {
        "tenant": tenant,
        "branch": branch,
        "items_data": items_data,
        "categories": categories,
        "selected_cat": cat_filter,
        "search_query": search,
    }
    return render(request, "branch_menu.html", context)


# ==========================================
# 6. OPERATIONAL SCREENS
# ==========================================

@login_required
@ensure_csrf_cookie
def pos_view(request):
    tenant = get_active_tenant(request)
    branch = get_active_branch(request)
    categories = ["الكل", "أطباق رئيسية", "مشويات", "ساندويتشات", "برجر", "دجاج", "مقبلات", "مشروبات", "حلويات"]

    all_menu = MenuItem.objects.filter(tenant=tenant).order_by("category", "name")
    if branch:
        disabled_ids = set(BranchMenuAvailability.objects.filter(branch=branch, is_available=False).values_list("menu_item_id", flat=True))
        menu_items = []
        for m in all_menu:
            m_avail = (m.id not in disabled_ids) and m.available
            if m_avail:
                menu_items.append(m)
    else:
        menu_items = list(all_menu.filter(available=True))

    recent_orders = Order.objects.filter(tenant=tenant).order_by("-id")
    if branch:
        recent_orders = recent_orders.filter(branch=branch)

    context = {
        "tenant": tenant,
        "current_branch": branch,
        "categories": categories,
        "menu_items": menu_items,
        "recent_orders": recent_orders[:10],
    }
    return render(request, "pos.html", context)


@login_required
@ensure_csrf_cookie
def call_center_view(request):
    tenant = get_active_tenant(request)
    branches = Branch.objects.filter(tenant=tenant, status="active").prefetch_related("delivery_areas").order_by("name")
    menu_items = MenuItem.objects.filter(tenant=tenant, available=True).order_by("category", "name")
    recent_orders = Order.objects.filter(tenant=tenant, channel="call_center").order_by("-id")[:10]
    delivery_areas = DeliveryArea.objects.filter(branch__tenant=tenant, is_active=True).select_related("branch").order_by("branch__name", "name")

    context = {
        "tenant": tenant,
        "branches": branches,
        "delivery_areas": delivery_areas,
        "menu_items": menu_items,
        "recent_orders": recent_orders,
    }
    return render(request, "call_center.html", context)


@login_required
@ensure_csrf_cookie
def delivery_view(request):
    tenant = get_active_tenant(request)
    branch = get_active_branch(request)
    start_of_today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    drivers_qs = Employee.objects.filter(tenant=tenant, role="driver", status="active").order_by("name")
    if branch:
        drivers_qs = drivers_qs.filter(Q(branch=branch) | Q(branch__isnull=True))

    drivers = list(drivers_qs)

    delivery_orders = Order.objects.filter(
        tenant=tenant,
        order_type="delivery",
        created_at__gte=start_of_today - timedelta(days=1),
    ).exclude(status="cancelled").select_related("branch", "driver").order_by("-id")

    if branch:
        delivery_orders = delivery_orders.filter(branch=branch)

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

    driver_stats = []
    for d in drivers:
        active = Order.objects.filter(tenant=tenant, driver=d, status="out_for_delivery").count()
        done = Order.objects.filter(tenant=tenant, driver=d, status="delivered", created_at__gte=start_of_today).count()
        driver_stats.append({
            "id": d.id,
            "name": d.name,
            "phone": d.phone,
            "active": active,
            "done": done,
        })

    active_count = sum(len(orders_by_status[st]) for st in ["new", "preparing", "ready", "out_for_delivery"])

    context = {
        "tenant": tenant,
        "current_branch": branch,
        "orders_by_status": orders_by_status,
        "drivers": drivers,
        "driver_stats": driver_stats,
        "active_count": active_count,
    }
    return render(request, "delivery.html", context)


@login_required
@ensure_csrf_cookie
def inventory_view(request):
    tenant = get_active_tenant(request)
    active_branch = get_active_branch(request)
    branch_id = request.GET.get("branch")
    search = request.GET.get("q", "").strip()

    items = InventoryItem.objects.filter(tenant=tenant).select_related("branch").order_by("branch__name", "name")

    if active_branch:
        items = items.filter(branch=active_branch)
        selected_branch = active_branch.id
    elif branch_id and branch_id.isdigit():
        items = items.filter(branch_id=int(branch_id))
        selected_branch = int(branch_id)
    else:
        selected_branch = "all"

    if search:
        items = items.filter(Q(name__icontains=search) | Q(supplier__icontains=search))

    branches = Branch.objects.filter(tenant=tenant).order_by("name")
    low_count = items.filter(quantity__lte=F("min_quantity")).count()

    context = {
        "tenant": tenant,
        "current_branch": active_branch,
        "items": items,
        "branches": branches,
        "low_count": low_count,
        "selected_branch": selected_branch,
        "search_query": search,
        "units": ["كجم", "لتر", "علبة", "قطعة", "كرتون", "حبة"],
    }
    return render(request, "inventory.html", context)


@login_required
@ensure_csrf_cookie
def branches_view(request):
    tenant = get_active_tenant(request)
    start_of_today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    branches = Branch.objects.filter(tenant=tenant).prefetch_related("delivery_areas").order_by("id")
    branch_list = []
    for b in branches:
        emp_count = Employee.objects.filter(branch=b).count()
        sales = Order.objects.filter(tenant=tenant, branch=b, created_at__gte=start_of_today).exclude(status="cancelled").aggregate(
            t=Sum("total")
        )["t"] or Decimal("0")
        orders_count = Order.objects.filter(tenant=tenant, branch=b, created_at__gte=start_of_today).count()
        branch_list.append({
            "branch": b,
            "employees_count": emp_count,
            "sales_today": sales,
            "orders_today": orders_count,
            "areas_count": b.delivery_areas.count(),
            "areas": list(b.delivery_areas.all()),
        })

    context = {
        "tenant": tenant,
        "branches_data": branch_list,
    }
    return render(request, "branches.html", context)


@login_required
@ensure_csrf_cookie
def employees_view(request):
    tenant = get_active_tenant(request)
    active_branch = get_active_branch(request)
    role_filter = request.GET.get("role", "all")
    branch_filter = request.GET.get("branch", "all")
    search = request.GET.get("q", "").strip()

    employees = Employee.objects.filter(tenant=tenant).select_related("branch").order_by("name")

    if active_branch:
        employees = employees.filter(branch=active_branch)
        branch_filter = active_branch.id
    elif branch_filter != "all" and str(branch_filter).isdigit():
        employees = employees.filter(branch_id=int(branch_filter))

    if role_filter != "all":
        employees = employees.filter(role=role_filter)
    if search:
        employees = employees.filter(Q(name__icontains=search) | Q(phone__icontains=search) | Q(employee_code__icontains=search))

    branches = Branch.objects.filter(tenant=tenant).order_by("name")

    base_qs = Employee.objects.filter(tenant=tenant, branch=active_branch) if active_branch else Employee.objects.filter(tenant=tenant)
    roles_summary = {
        "all": base_qs.count(),
        "manager": base_qs.filter(role="manager").count(),
        "cashier": base_qs.filter(role="cashier").count(),
        "chef": base_qs.filter(role="chef").count(),
        "driver": base_qs.filter(role="driver").count(),
        "call_center": base_qs.filter(role="call_center").count(),
        "waiter": base_qs.filter(role="waiter").count(),
    }

    # Calculate next suggested employee code for tenant
    last_emp = Employee.objects.filter(tenant=tenant, employee_code__regex=r'^\d+$').order_by("-id").first()
    if last_emp and last_emp.employee_code and last_emp.employee_code.isdigit():
        suggested_next_code = str(int(last_emp.employee_code) + 1)
    else:
        suggested_next_code = str(101 + Employee.objects.filter(tenant=tenant).count())

    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    context = {
        "tenant": tenant,
        "current_branch": active_branch,
        "employees": employees,
        "branches": branches,
        "role_filter": role_filter,
        "branch_filter": branch_filter,
        "search_query": search,
        "roles_summary": roles_summary,
        "can_edit_id": is_owner_or_super,
        "suggested_next_code": suggested_next_code,
    }
    return render(request, "employees.html", context)


# ==========================================
# 7. JSON API ENDPOINTS (TENANT AWARE)
# ==========================================

@login_required
def api_create_order(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    tenant = get_active_tenant(request)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    items_data = data.get("items", [])
    if not items_data:
        return JsonResponse({"error": "السلة فارغة — أضف أصنافاً أولاً"}, status=400)

    order_type = data.get("type", "dine_in")
    channel = data.get("channel", "cashier")

    active_branch = get_active_branch(request)
    branch_id = active_branch.id if active_branch else data.get("branchId")
    branch = Branch.objects.filter(tenant=tenant, id=branch_id).first() if branch_id else None

    # Resolve items scoped to tenant
    menu_ids = [int(i.get("menuItemId")) for i in items_data if i.get("menuItemId")]
    menu_map = {m.id: m for m in MenuItem.objects.filter(tenant=tenant, id__in=menu_ids)}

    rows = []
    subtotal = Decimal("0")
    for it in items_data:
        m_id = int(it.get("menuItemId", 0))
        m = menu_map.get(m_id)
        if not m:
            continue
        qty = max(1, int(it.get("qty", 1)))
        subtotal += m.price * qty
        rows.append({"menu_item": m, "name": m.name, "price": m.price, "qty": qty})

    if not rows:
        return JsonResponse({"error": "الأصناف المحددة غير متوفرة"}, status=400)

    delivery_area_id = data.get("deliveryAreaId")
    delivery_area = None
    if delivery_area_id:
        delivery_area = DeliveryArea.objects.filter(branch__tenant=tenant, id=delivery_area_id).first()
        if delivery_area:
            branch = delivery_area.branch

    if order_type == "delivery":
        if delivery_area:
            delivery_fee = delivery_area.delivery_fee
        else:
            delivery_fee = Decimal(str(data.get("deliveryFee") or "8"))
    else:
        delivery_fee = Decimal("0")

    discount = Decimal(str(data.get("discount") or 0))
    discount = max(Decimal("0"), min(discount, subtotal))
    total = max(Decimal("0"), subtotal + delivery_fee - discount)

    phone = str(data.get("customerPhone") or "").strip()
    cust_name = str(data.get("customerName") or "").strip() or ("عميل توصيل" if order_type == "delivery" else "عميل نقدي")
    address = str(data.get("address") or "").strip()
    customer = None

    if phone:
        customer, _ = Customer.objects.get_or_create(tenant=tenant, phone=phone, defaults={"name": cust_name, "address": address})
        if cust_name and customer.name != cust_name:
            customer.name = cust_name
        if address:
            customer.address = address
        customer.save()

    count = Order.objects.filter(tenant=tenant).count()
    prefix = tenant.slug[:3].upper() if tenant else "ORD"
    order_number = f"{prefix}-{1000 + count + 1}"

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
        cashier=str(data.get("cashier") or request.user.first_name or request.user.username),
        notes=str(data.get("notes") or ""),
    )

    for r in rows:
        OrderItem.objects.create(
            order=order,
            menu_item=r["menu_item"],
            name=r["name"],
            price=r["price"],
            qty=r["qty"],
        )

    return JsonResponse({"order": {"id": order.id, "orderNumber": order.order_number}}, status=201)


@login_required
def api_update_order(request, order_id):
    if request.method not in ["PATCH", "POST"]:
        return HttpResponseBadRequest("PATCH or POST required")

    tenant = get_active_tenant(request)
    order = get_object_or_404(Order, tenant=tenant, id=order_id)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    if "status" in data and data["status"] in dict(Order.STATUS_CHOICES):
        order.status = data["status"]

    if "driverId" in data:
        drv_id = data["driverId"]
        if drv_id:
            order.driver = Employee.objects.filter(tenant=tenant, id=drv_id, role="driver").first()
        else:
            order.driver = None

    if "paid" in data and isinstance(data["paid"], bool):
        order.paid = data["paid"]

    order.save()
    return JsonResponse({"ok": True, "status": order.status})


@login_required
def api_toggle_branch_menu(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    tenant = get_active_tenant(request)
    branch = get_active_branch(request)
    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)

    if branch:
        avail, _ = BranchMenuAvailability.objects.get_or_create(
            branch=branch,
            menu_item=item,
            defaults={"is_available": item.available}
        )
        avail.is_available = not avail.is_available
        avail.save()
        return JsonResponse({"ok": True, "isAvailable": avail.is_available, "itemName": item.name, "branch": branch.name})
    else:
        item.available = not item.available
        item.save()
        return JsonResponse({"ok": True, "isAvailable": item.available, "itemName": item.name, "branch": "كل الفروع"})


@login_required
def api_search_customers(request):
    q = request.GET.get("q", "").strip()
    if len(q) < 3:
        return JsonResponse({"customers": []})

    tenant = get_active_tenant(request)
    customers = Customer.objects.filter(
        tenant=tenant
    ).filter(Q(phone__icontains=q) | Q(name__icontains=q))[:8]

    data = []
    for c in customers:
        data.append({
            "id": c.id,
            "name": c.name,
            "phone": c.phone,
            "address": c.address,
            "ordersCount": Order.objects.filter(customer=c).count(),
        })
    return JsonResponse({"customers": data})


@login_required
def api_toggle_menu_item(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)
    item.available = not item.available
    item.save()
    return JsonResponse({"ok": True, "available": item.available})


@login_required
def api_create_menu_item(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    name = str(data.get("name", "")).strip()
    price = Decimal(str(data.get("price") or 0))
    if not name or price <= 0:
        return JsonResponse({"error": "اسم الصنف والسعر مطلوبان"}, status=400)

    item = MenuItem.objects.create(
        tenant=tenant,
        name=name,
        category=data.get("category", "أطباق رئيسية"),
        price=price,
        cost=Decimal(str(data.get("cost") or 0)),
        emoji=data.get("emoji", "🍽️"),
        available=True,
    )

    for b in Branch.objects.filter(tenant=tenant):
        BranchMenuAvailability.objects.get_or_create(branch=b, menu_item=item, defaults={"is_available": True})

    return JsonResponse({"id": item.id, "name": item.name}, status=201)


@login_required
def api_adjust_inventory(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    item = get_object_or_404(InventoryItem, tenant=tenant, id=item_id)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    if "delta" in data:
        delta = Decimal(str(data["delta"]))
        item.quantity = max(Decimal("0"), item.quantity + delta)
    elif "quantity" in data:
        item.quantity = max(Decimal("0"), Decimal(str(data["quantity"])))

    if "minQuantity" in data:
        item.min_quantity = max(Decimal("0"), Decimal(str(data["minQuantity"])))
    if "supplier" in data:
        item.supplier = str(data["supplier"])

    item.save()
    return JsonResponse({"ok": True, "quantity": float(item.quantity), "minQuantity": float(item.min_quantity)})


@login_required
def api_create_inventory(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    name = str(data.get("name", "")).strip()
    branch_id = data.get("branchId")
    if not name or not branch_id:
        return JsonResponse({"error": "اسم المادة والفرع مطلوبان"}, status=400)

    branch = get_object_or_404(Branch, tenant=tenant, id=branch_id)
    item = InventoryItem.objects.create(
        tenant=tenant,
        branch=branch,
        name=name,
        unit=data.get("unit", "كجم"),
        quantity=Decimal(str(data.get("quantity") or 0)),
        min_quantity=Decimal(str(data.get("minQuantity") or 5)),
        supplier=data.get("supplier", ""),
    )
    return JsonResponse({"ok": True, "id": item.id})


@login_required
def api_delete_inventory(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    item = get_object_or_404(InventoryItem, tenant=tenant, id=item_id)
    item.delete()
    return JsonResponse({"ok": True})


@login_required
def api_create_branch(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    name = str(data.get("name", "")).strip()
    if not name:
        return JsonResponse({"error": "اسم الفرع مطلوب"}, status=400)

    lat = data.get("latitude")
    lng = data.get("longitude")
    polygon = data.get("polygon", [])
    radius = data.get("delivery_radius_km", 5.0)

    branch = Branch.objects.create(
        tenant=tenant,
        name=name,
        city=data.get("city", "الرياض"),
        address=data.get("address", ""),
        phone=data.get("phone", ""),
        latitude=Decimal(str(lat)) if lat is not None and str(lat).strip() != "" else None,
        longitude=Decimal(str(lng)) if lng is not None and str(lng).strip() != "" else None,
        delivery_polygon=polygon if isinstance(polygon, list) else [],
        delivery_radius_km=Decimal(str(radius or 5.0)),
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
            },
            "areas": areas
        })

    elif request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

        action = data.get("action", "add")
        if action == "add":
            name = str(data.get("name", "")).strip()
            if not name:
                return JsonResponse({"error": "اسم المنطقة أو الكومبوند مطلوب"}, status=400)
            area = DeliveryArea.objects.create(
                branch=branch,
                name=name,
                area_type=data.get("area_type", "compound"),
                delivery_fee=Decimal(str(data.get("delivery_fee") or 8.0)),
                estimated_time_minutes=int(data.get("estimated_time_minutes") or 35),
                notes=str(data.get("notes", "")).strip(),
                is_active=True
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
            DeliveryArea.objects.filter(branch=branch, id=area_id).delete()
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
            branch.save()
            return JsonResponse({"ok": True, "message": "تم حفظ مضلع الزون وإحداثيات الفرع بنجاح"})

        return JsonResponse({"error": "إجراء غير معروف"}, status=400)


@login_required
def api_toggle_branch(request, branch_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    branch = get_object_or_404(Branch, tenant=tenant, id=branch_id)
    branch.status = "closed" if branch.status == "active" else "active"
    branch.save()
    return JsonResponse({"ok": True, "status": branch.status})


@login_required
def api_create_employee(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    name = str(data.get("name", "")).strip()
    if not name:
        return JsonResponse({"error": "اسم الموظف مطلوب"}, status=400)

    branch_id = data.get("branchId")
    branch = Branch.objects.filter(tenant=tenant, id=branch_id).first() if branch_id else None

    # Branch managers can only create employees in their branch
    if not is_owner_or_super and profile and profile.branch and branch != profile.branch:
        return JsonResponse({"error": "غير مصرح لك بإضافة موظف في فرع آخر"}, status=403)

    # Generate or validate employee code
    code = str(data.get("employeeCode") or "").strip()
    if not code:
        last_emp = Employee.objects.filter(tenant=tenant, employee_code__regex=r'^\d+$').order_by("-id").first()
        if last_emp and last_emp.employee_code and last_emp.employee_code.isdigit():
            code = str(int(last_emp.employee_code) + 1)
        else:
            code = str(101 + Employee.objects.filter(tenant=tenant).count())

    if Employee.objects.filter(tenant=tenant, employee_code=code).exists():
        return JsonResponse({"error": f"كود الموظف ({code}) مستخدم مسبقاً في هذا المطعم، يرجى اختيار كود آخر"}, status=400)

    pin = str(data.get("pin") or "").strip()
    if not pin:
        pin = "1234"
    elif len(pin) < 4:
        return JsonResponse({"error": "رمز PIN يجب أن يتكون من 4 أرقام على الأقل"}, status=400)

    emp = Employee.objects.create(
        tenant=tenant,
        name=name,
        phone=data.get("phone", ""),
        role=data.get("role", "cashier"),
        branch=branch,
        salary=Decimal(str(data.get("salary") or 4000)),
        employee_code=code,
    )
    emp.set_pin(pin)

    # Auto-link user account
    tenant_slug = tenant.slug if tenant else "sys"
    username = f"emp_{tenant_slug}_{code}"
    user_obj, _ = User.objects.get_or_create(username=username, defaults={"first_name": name})
    user_obj.set_password("admin123")
    user_obj.save()
    emp.user = user_obj
    emp.save()

    UserProfile.objects.update_or_create(
        user=user_obj,
        defaults={"tenant": tenant, "role": emp.role, "branch": emp.branch}
    )

    return JsonResponse({"ok": True, "id": emp.id, "name": emp.name, "employeeCode": code})


@login_required
def api_update_employee(request, emp_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    emp = get_object_or_404(Employee, tenant=tenant, id=emp_id)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    # Branch managers can only edit employees in their branch
    if not is_owner_or_super and profile and profile.branch and emp.branch != profile.branch:
        return JsonResponse({"error": "غير مصرح لك بتعديل موظفي الفروع الأخرى"}, status=403)

    if "name" in data and str(data["name"]).strip():
        emp.name = str(data["name"]).strip()
        if emp.user:
            emp.user.first_name = emp.name
            emp.user.save()

    if "phone" in data:
        emp.phone = str(data["phone"]).strip()

    if "role" in data and data["role"] in dict(Employee.ROLE_CHOICES):
        emp.role = data["role"]
        if emp.user and hasattr(emp.user, "profile"):
            emp.user.profile.role = emp.role
            emp.user.profile.save()

    if "status" in data and data["status"] in dict(Employee.STATUS_CHOICES):
        emp.status = data["status"]

    if "salary" in data:
        try:
            emp.salary = Decimal(str(data["salary"]))
        except Exception:
            pass

    if "branchId" in data and is_owner_or_super:
        emp.branch = Branch.objects.filter(tenant=tenant, id=data["branchId"]).first() if data["branchId"] else None
        if emp.user and hasattr(emp.user, "profile"):
            emp.user.profile.branch = emp.branch
            emp.user.profile.save()

    # Employee Code (ID) update - restricted to Superadmin and Owner
    new_code = str(data.get("employeeCode") or "").strip()
    if new_code and new_code != emp.employee_code:
        if not is_owner_or_super:
            return JsonResponse({"error": "تعديل كود الموظف مقتصر على المالك ومدير النظام فقط"}, status=403)
        if Employee.objects.filter(tenant=tenant, employee_code=new_code).exclude(id=emp.id).exists():
            return JsonResponse({"error": f"كود الموظف ({new_code}) مستخدم مسبقاً لموظف آخر"}, status=400)
        emp.employee_code = new_code

    # PIN change / reset - allowed for Owner, Superadmin, and Branch Manager
    new_pin = str(data.get("pin") or "").strip()
    if new_pin:
        if len(new_pin) < 4:
            return JsonResponse({"error": "رمز PIN يجب أن يتكون من 4 أرقام على الأقل"}, status=400)
        emp.set_pin(new_pin)

    emp.save()
    return JsonResponse({"ok": True, "employeeCode": emp.employee_code, "hasPin": bool(emp.pin_code)})
