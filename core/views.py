import os
import json
import csv
import sys
import logging
from decimal import Decimal
from datetime import timedelta

logger = logging.getLogger(__name__)

from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from django.contrib.auth import authenticate, login, logout
import asyncio
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.views.decorators.cache import never_cache
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, StreamingHttpResponse, HttpResponse, HttpResponseNotFound
from django.utils import timezone, translation
from django.utils.text import slugify
from django.db import transaction, IntegrityError
from django.db.models import Sum, Count, F, Q
from django.core.cache import cache
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from asgiref.sync import sync_to_async
from .kitchen_events import kitchen_broadcaster, serialize_kitchen_order, notify_kitchen_order_event

from .models import (
    Tenant,
    Branch,
    Employee,
    MenuItem,
    MenuCategory,
    MenuItemVariant,
    InventoryItem,
    Customer,
    Order,
    OrderItem,
    UserProfile,
    BranchMenuAvailability,
    BranchVariantPrice,
    DeliveryArea,
    JobRole,
    RESTAURANT_PERMISSIONS,
    PERMISSIONS_CATALOG,
    SubscriptionPlan,
    SAAS_FEATURES_CATALOG,
    UpgradeRequest,
    TenantApiKey,
    AuditLog,
    log_audit_event,
    ensure_tenant_preset_roles,
)


def _get_client_ip(request):
    """Safely extracts client IP address from HTTP request headers."""
    if not request:
        return None
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _check_rate_limit(key, max_attempts=5):
    """Checks if key is currently rate-limited (blocked)."""
    try:
        attempts = cache.get(key, 0)
        return attempts >= max_attempts
    except Exception:
        return False


def _record_failed_attempt(key, timeout_seconds=900):
    """Increments failed attempt count with 15 minutes expiration."""
    try:
        attempts = cache.get(key, 0) + 1
        cache.set(key, attempts, timeout=timeout_seconds)
        return attempts
    except Exception:
        return 1


def _clear_rate_limit(key):
    """Clears failed attempt count on successful login."""
    try:
        cache.delete(key)
    except Exception:
        pass


def get_active_tenant(request):
    """Resolve the active tenant for the current request."""
    if hasattr(request, "tenant") and request.tenant:
        return request.tenant

    profile = getattr(request.user, "profile", None)
    if profile and profile.tenant:
        return profile.tenant

    emp = getattr(request.user, "employee_profile", None)
    if emp and emp.tenant:
        return emp.tenant

    # Platform admin / Superuser session override
    active_t_id = request.session.get("active_tenant_id")
    if active_t_id:
        t = Tenant.objects.filter(id=active_t_id, is_active=True).first()
        if t:
            return t

    if hasattr(request, "user") and (request.user.is_superuser or (profile and profile.is_platform_admin)):
        return Tenant.objects.filter(is_active=True).first()

    return None


def get_active_branch(request):
    """Resolve active branch within the current tenant."""
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    emp = getattr(request.user, "employee_profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    can_operate_cross = (
        is_owner
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "call_center_access")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )

    if not can_operate_cross:
        if profile and profile.branch:
            return profile.branch
        if emp and emp.branch:
            return emp.branch

    has_session = hasattr(request, "session")
    if has_session and "active_branch_id" in request.session:
        active_id = request.session.get("active_branch_id")
        if active_id in ["all", 0, "0", None]:
            return None
        qs = Branch.objects.filter(id=active_id)
        if tenant:
            qs = qs.filter(tenant=tenant)
        b = qs.first()
        if b:
            return b

    if profile and profile.branch:
        return profile.branch
    if emp and emp.branch:
        return emp.branch

    if tenant:
        return tenant.branches.filter(status="active").first() or tenant.branches.first()

    return None


def user_has_perm(user, perm_key):
    """
    Unified pure Django auth permission check.
    Bypasses for superuser and tenant owner / platform admin.
    All staff authorization is strictly verified through Django's native
    Group and Permission engine: user.has_perm('core.<codename>') and user.groups.
    Includes symmetric synonym resolution and self-healing group synchronization.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    if profile and (profile.is_platform_admin or profile.role in ["owner", "platform_admin"]):
        return True

    clean_key = perm_key.split(".")[-1]

    # Symmetric permission synonyms (legacy compatibility with new granular taxonomy)
    SYNONYM_MAP = {
        "manage_branches": "branch_manage_branches",
        "branch_manage_branches": "manage_branches",
        "manage_roles": "system_manage_roles",
        "system_manage_roles": "manage_roles",
        "view_hq_dashboard": "hq_view_master_dashboard",
        "hq_view_master_dashboard": "view_hq_dashboard",
        "view_branch_dashboard": "branch_view_dashboard",
        "branch_view_dashboard": "view_branch_dashboard",
        "cancel_orders": "pos_cancel_order",
        "pos_cancel_order": "cancel_orders",
    }
    keys_to_check = [clean_key]
    if clean_key in SYNONYM_MAP:
        keys_to_check.append(SYNONYM_MAP[clean_key])

    # Implied permissions mapping
    IMPLIED_PERMS = {
        "view_financials": ["finance_view_sales", "finance_view_reports", "finance_view_profit_loss"],
        "menu_view": ["manage_menu"],
        "inventory_view": ["manage_inventory"],
        "hr_view_employees": ["manage_employees"],
    }
    if clean_key in IMPLIED_PERMS:
        for ik in IMPLIED_PERMS[clean_key]:
            if ik not in keys_to_check:
                keys_to_check.append(ik)

    for k in keys_to_check:
        if user.has_perm(f"core.{k}"):
            return True
        # Direct check on user's groups to guarantee 0ms latency even before permission cache refresh
        if user.groups.filter(permissions__codename=k).exists():
            return True

    # Self-healing fallback: verify through assigned JobRole if user's group association lagged
    job_role = None
    if profile and profile.job_role:
        job_role = profile.job_role
    elif hasattr(user, "employee_profile") and user.employee_profile and user.employee_profile.job_role:
        job_role = user.employee_profile.job_role

    if job_role:
        for k in keys_to_check:
            if job_role.has_perm(k):
                # Auto-sync group to user immediately
                grp = job_role.sync_with_django_group()
                if grp:
                    user.groups.add(grp)
                return True

    return False


def get_post_login_redirect(user):
    """Determine the optimal starting view dynamically based on user roles and permissions."""
    if not user or not user.is_authenticated:
        return "login"

    profile = getattr(user, "profile", None)
    if user.is_superuser or (profile and profile.is_platform_admin):
        return "/admin/"

    is_owner = (profile and profile.role == "owner")
    if profile and profile.tenant and not profile.tenant.is_active:
        return "owner_subscription" if is_owner else "login"

    if is_owner or user_has_perm(user, "view_hq_dashboard"):
        return "dashboard"

    if user_has_perm(user, "view_branch_dashboard"):
        return "branch_dashboard"

    # Route by operational permission priority
    if user_has_perm(user, "pos_access") or user_has_perm(user, "pos_create_order"):
        return "pos"
    if user_has_perm(user, "kds_access"):
        return "kitchen"
    if user_has_perm(user, "call_center_access") or user_has_perm(user, "call_center_create_order"):
        return "call_center"
    if user_has_perm(user, "delivery_access"):
        return "delivery"
    if user_has_perm(user, "view_orders"):
        return "branch_orders"
    if user_has_perm(user, "manage_menu") or user_has_perm(user, "menu_view") or user_has_perm(user, "menu_toggle_availability"):
        return "branch_menu"
    if user_has_perm(user, "manage_inventory") or user_has_perm(user, "inventory_view"):
        return "inventory"
    if user_has_perm(user, "manage_employees") or user_has_perm(user, "hr_view_employees"):
        return "employees"
    if user_has_perm(user, "manage_branches"):
        return "branches"

    return "branch_dashboard"


# ==========================================
# AUTHENTICATION & LOGIN (DUAL MODE)
# ==========================================

def login_view(request):
    if request.user.is_authenticated:
        return redirect(get_post_login_redirect(request.user))

    error_message = None
    if request.GET.get("suspended") == "1":
        error_message = "تم إيقاف حساب هذه المنشأة مؤقتاً. يرجى مراجعة إدارة المطعم أو صاحب العمل."

    if request.method == "POST":
        auth_type = request.POST.get("auth_type", "credentials")

        if auth_type == "pin":
            # Mode B: Quick Shift PIN Login for shift workers
            code = request.POST.get("employee_code", "").strip()
            pin = request.POST.get("pin", "").strip()

            # Normalize Arabic digits (٠١٢٣٤٥٦٧٨٩ -> 0123456789)
            trans_table = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
            code = code.translate(trans_table).strip()
            pin = pin.translate(trans_table).strip()

            client_ip = _get_client_ip(request) or "unknown"
            pin_rate_key = f"rate_limit_pin_{client_ip}_{code}"

            if _check_rate_limit(pin_rate_key):
                error_message = "تم تجاوز الحد الأقصى للمحاولات الخاطئة (5 محاولات). يرجى الانتظار لمدة 15 دقيقة قبل المحاولة مرة أخرى."
            elif not code or not pin:
                error_message = "يرجى إدخال كود الموظف ورمز PIN المكون من 4 أرقام"
            else:
                restaurant_id = request.POST.get("restaurant") or request.GET.get("restaurant") or request.session.get("active_tenant_id")
                emp_candidates = Employee.objects.filter(employee_code=code, status="active").select_related("tenant", "branch", "user")
                if restaurant_id:
                    if str(restaurant_id).isdigit():
                        emp_candidates = emp_candidates.filter(tenant_id=int(restaurant_id))
                    else:
                        emp_candidates = emp_candidates.filter(Q(tenant__slug=restaurant_id) | Q(tenant__name=restaurant_id))

                matched_emps = []
                for emp in emp_candidates:
                    if emp.check_pin(pin):
                        if emp.user and not emp.user.is_active:
                            continue
                        matched_emps.append(emp)

                matched_emp = None
                if len(matched_emps) > 1 and not restaurant_id:
                    error_message = "يرجى تحديد اسم أو معرف المنشأة (المطعم) للدخول بهذا الحساب."
                elif len(matched_emps) >= 1:
                    matched_emp = matched_emps[0]

                if matched_emp:
                    if matched_emp.tenant and not matched_emp.tenant.is_active:
                        error_message = "تم إيقاف حساب هذه المنشأة مؤقتاً. يرجى مراجعة إدارة المطعم."
                    else:
                        _clear_rate_limit(pin_rate_key)
                        # Auto-assign default branch if none is set and role is branch-scoped
                        effective_branch = matched_emp.branch
                        if not effective_branch and matched_emp.tenant:
                            effective_branch = matched_emp.tenant.branches.filter(status="active").first() or matched_emp.tenant.branches.first()
                            matched_emp.branch = effective_branch
                            matched_emp.save(update_fields=["branch"])

                        # Auto-provision user account if missing
                        user_to_login = matched_emp.user
                        if not user_to_login:
                            tenant_slug = matched_emp.tenant.slug if matched_emp.tenant else "sys"
                            username = f"emp_{tenant_slug}_{matched_emp.employee_code}"
                            user_to_login, _ = User.objects.get_or_create(username=username, defaults={"first_name": matched_emp.name})
                            user_to_login.set_unusable_password()
                            user_to_login.save()
                            matched_emp.user = user_to_login
                            matched_emp.save(update_fields=["user"])

                        # Ensure UserProfile matches employee
                        user_profile_role = "branch_manager" if matched_emp.role == "manager" else matched_emp.role
                        UserProfile.objects.update_or_create(
                            user=user_to_login,
                            defaults={
                                "tenant": matched_emp.tenant,
                                "branch": effective_branch,
                                "role": user_profile_role,
                                "job_role": matched_emp.job_role,
                            }
                        )

                        # Sync Django Groups & Permissions
                        if matched_emp.job_role:
                            grp = matched_emp.job_role.sync_with_django_group()
                            if grp:
                                user_to_login.groups.set([grp])
                        else:
                            user_to_login.groups.clear()

                        for cache_field in ["_perm_cache", "_group_perm_cache", "_user_perm_cache"]:
                            if hasattr(user_to_login, cache_field):
                                delattr(user_to_login, cache_field)

                        login(request, user_to_login)
                        if matched_emp.tenant:
                            request.session["active_tenant_id"] = matched_emp.tenant.id
                        if effective_branch:
                            request.session["active_branch_id"] = effective_branch.id
                        request.session["active_employee_id"] = matched_emp.id

                        return redirect(get_post_login_redirect(user_to_login))
                elif not error_message:
                    _record_failed_attempt(pin_rate_key)
                    error_message = "كود الموظف أو رمز PIN غير صحيح"

        else:
            # Mode A: Standard Credentials
            username = request.POST.get("username", "").strip()
            password = request.POST.get("password", "")

            client_ip = _get_client_ip(request) or "unknown"
            cred_rate_key = f"rate_limit_cred_{client_ip}_{username}"

            if _check_rate_limit(cred_rate_key):
                error_message = "تم تجاوز الحد الأقصى للمحاولات الخاطئة (5 محاولات). يرجى الانتظار لمدة 15 دقيقة قبل المحاولة مرة أخرى."
            else:
                user = authenticate(request, username=username, password=password)

                # Fallback: if username is employee_code (e.g. "104"), resolve via Employee
                if user is None and username:
                    trans_table = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
                    clean_code = username.translate(trans_table).strip()
                    emp_candidate = Employee.objects.filter(employee_code=clean_code, status="active").select_related("user").first()
                    if emp_candidate and emp_candidate.user:
                        user = authenticate(request, username=emp_candidate.user.username, password=password)

                if user is not None:
                    profile = getattr(user, "profile", None)
                    emp_candidate = getattr(user, "employee_profile", None)
                    target_tenant = profile.tenant if (profile and profile.tenant) else (emp_candidate.tenant if (emp_candidate and emp_candidate.tenant) else None)
                    is_platform_admin = user.is_superuser or (profile and profile.is_platform_admin)

                    # Tenant Suspension Handling
                    if target_tenant and not target_tenant.is_active and not is_platform_admin:
                        is_owner = (profile and profile.role == "owner")
                        if not is_owner:
                            _record_failed_attempt(cred_rate_key)
                            error_message = "تم إيقاف حساب هذه المنشأة مؤقتاً. يرجى مراجعة إدارة المطعم أو صاحب العمل."
                            return render(request, "login.html", {"error": error_message})
                        else:
                            # Owner is routed exclusively to owner_subscription
                            _clear_rate_limit(cred_rate_key)
                            login(request, user)
                            request.session["active_tenant_id"] = target_tenant.id
                            return redirect("owner_subscription")

                    _clear_rate_limit(cred_rate_key)
                    login(request, user)

                    # Sync Django Group for user from Employee or Profile
                    emp_obj = getattr(user, "employee_profile", None)
                    eff_job_role = emp_obj.job_role if (emp_obj and emp_obj.job_role) else (profile.job_role if (profile and profile.job_role) else None)
                    if eff_job_role:
                        grp = eff_job_role.sync_with_django_group()
                        if grp:
                            user.groups.set([grp])

                    for cache_field in ["_perm_cache", "_group_perm_cache", "_user_perm_cache"]:
                        if hasattr(user, cache_field):
                            delattr(user, cache_field)

                    # Route platform admin / superuser directly to Django Admin
                    if user.is_superuser or (profile and profile.is_platform_admin):
                        return redirect("/admin/")

                    # Bind tenant
                    if profile and profile.tenant:
                        request.session["active_tenant_id"] = profile.tenant.id

                    # Route branch-locked staff
                    if profile and profile.role != "owner":
                        if not profile.branch and profile.tenant:
                            profile.branch = profile.tenant.branches.filter(status="active").first() or profile.tenant.branches.first()
                            profile.save(update_fields=["branch"])
                        if profile.branch:
                            request.session["active_branch_id"] = profile.branch.id

                    return redirect(get_post_login_redirect(user))
                else:
                    _record_failed_attempt(cred_rate_key)
                    error_message = "اسم المستخدم أو كلمة المرور غير صحيحة"

    return render(request, "login.html", {"error": error_message})


def logout_view(request):
    logout(request)
    return redirect("login")


def register_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    error_message = None
    plans = SubscriptionPlan.objects.filter(is_active=True).order_by("ordering")

    if request.method == "POST":
        restaurant_name = request.POST.get("restaurant_name", "").strip()
        cuisine_type = request.POST.get("cuisine_type", "شعبي وتراثي").strip()
        owner_name = request.POST.get("owner_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        email = request.POST.get("email", "").strip()
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()
        plan_code = request.POST.get("plan_code", "").strip() or "trial"

        if not restaurant_name or not username or not password:
            error_message = "يرجى تعبئة الحقول الإلزامية: اسم المطعم، اسم المستخدم، وكلمة المرور."
        elif User.objects.filter(username=username).exists():
            error_message = f"اسم المستخدم '{username}' مسجل مسبقاً، يرجى اختيار اسم مستخدم آخر."
        elif len(password) < 6:
            error_message = "كلمة المرور يجب أن لا تقل عن 6 خانات."
        else:
            try:
                with transaction.atomic():
                    # 1. Create User Account
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        password=password,
                        first_name=owner_name or restaurant_name
                    )

                    # 2. Pick Selected Plan (defaults to trial 14-day free trial)
                    plan = SubscriptionPlan.objects.filter(code=plan_code).first() or SubscriptionPlan.objects.filter(code="trial").first() or plans.first()

                    # 3. Generate unique slug
                    base_slug = slugify(restaurant_name) or f"restaurant-{user.id}"
                    slug = base_slug
                    counter = 1
                    while Tenant.objects.filter(slug=slug).exists():
                        slug = f"{base_slug}-{counter}"
                        counter += 1

                    # 4. Create Tenant
                    tenant = Tenant.objects.create(
                        name=restaurant_name,
                        slug=slug,
                        phone=phone,
                        email=email,
                        plan="trial",
                        subscription_plan=plan,
                        subscription_status="trial",
                        subscription_start=timezone.now(),
                        subscription_end=timezone.now() + timedelta(days=plan.trial_days if plan else 14),
                        is_active=True,
                    )

                    # 5. Create Owner Profile
                    UserProfile.objects.create(
                        user=user,
                        tenant=tenant,
                        role="owner"
                    )

                    # 6. Create Initial Main Branch
                    Branch.objects.create(
                        tenant=tenant,
                        name=f"الفرع الرئيسي — {restaurant_name}",
                        phone=phone,
                        status="active"
                    )

                    # 7. Seed standard preset roles
                    ensure_tenant_preset_roles(tenant)

                # 8. Authenticate and redirect
                login(request, user)
                request.session["active_tenant_id"] = tenant.id
                return redirect("dashboard")

            except Exception as e:
                error_message = f"حدث خطأ أثناء إنشاء الحساب: {str(e)}"

    return render(request, "register.html", {
        "error": error_message,
        "plans": plans
    })


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

@login_required
@ensure_csrf_cookie
def dashboard_view(request):
    profile = getattr(request.user, "profile", None)
    is_platform_admin = request.user.is_superuser or (profile and profile.is_platform_admin)

    # If platform admin and no tenant selected, go to Django Admin
    if is_platform_admin and not request.session.get("active_tenant_id") and request.GET.get("view") != "tenant":
        return redirect("/admin/")

    tenant = get_active_tenant(request)
    active_branch = get_active_branch(request)
    is_owner = is_platform_admin or (profile and profile.role == "owner")

    if not is_owner and not user_has_perm(request.user, "view_hq_dashboard"):
        if user_has_perm(request.user, "view_branch_dashboard"):
            return redirect("branch_dashboard")
        target_view = get_post_login_redirect(request.user)
        if target_view and target_view != "dashboard":
            return redirect(target_view)
        return HttpResponseForbidden("غير مصرح لك بالوصول إلى لوحة الإدارة العامة")

    # If a specific active branch is selected or user lacks HQ dashboard access, redirect to branch dashboard
    if active_branch is not None or (not is_owner and not user_has_perm(request.user, "view_hq_dashboard")):
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

    # 6. Branch performance comparison matrix & ranking (Optimized: 3 grouped queries total)
    branches = list(Branch.objects.filter(tenant=tenant, status="active").order_by("id"))
    total_branches_count = Branch.objects.filter(tenant=tenant).count()
    active_branches_count = len(branches)
    callcenter_orders_count = today_orders.filter(channel="call_center").count()
    cashier_orders_count = today_orders.filter(channel="cashier").count()

    branch_sales_map = {
        row["branch_id"]: {"total": row["t"] or Decimal("0"), "count": row["c"]}
        for row in today_orders.values("branch_id").annotate(t=Sum("total"), c=Count("id"))
    }
    branch_emps_map = {
        row["branch_id"]: row["c"]
        for row in Employee.objects.filter(tenant=tenant, branch__isnull=False).values("branch_id").annotate(c=Count("id"))
    }
    branch_stock_map = {
        row["branch_id"]: row["c"]
        for row in InventoryItem.objects.filter(tenant=tenant, quantity__lte=F("min_quantity"), branch__isnull=False).values("branch_id").annotate(c=Count("id"))
    }

    branch_matrix = []
    max_branch_sale = Decimal("1")
    for b in branches:
        sales_info = branch_sales_map.get(b.id, {"total": Decimal("0"), "count": 0})
        b_total = sales_info["total"]
        b_count = sales_info["count"]
        b_emps = branch_emps_map.get(b.id, 0)
        b_low_stock = branch_stock_map.get(b.id, 0)
        if b_total > max_branch_sale:
            max_branch_sale = b_total
        branch_matrix.append({
            "branch": b,
            "sales_today": float(b_total),
            "orders_today": b_count,
            "employees_count": b_emps,
            "low_stock_count": b_low_stock,
        })
    # Sort descending by sales for live ranking
    branch_matrix.sort(key=lambda x: x["sales_today"], reverse=True)

    recent_orders = Order.objects.filter(tenant=tenant).select_related("branch").order_by("-id")[:8]
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
        "active_branches_count": active_branches_count,
        "total_branches_count": total_branches_count,
        "callcenter_orders_count": callcenter_orders_count,
        "cashier_orders_count": cashier_orders_count,
        "recent_orders": recent_orders,
        "top_items": top_items_qs,
        "low_stock_items": low_stock[:8],
        "default_currency": tenant.default_currency if tenant else "SAR",
    }
    return render(request, "hq_dashboard.html", context)


# ==========================================
# 2. BRANCH DASHBOARD (SINGLE BRANCH)
# ==========================================

@login_required
@ensure_csrf_cookie
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

@login_required
@ensure_csrf_cookie
def kitchen_view(request):
    """
    Renders the Kitchen Display Screen with category stations, live counters,
    item-level checklists, and real-time SSE streaming.
    """
    tenant = get_active_tenant(request)
    if tenant and not tenant.has_feature("kds"):
        return HttpResponseForbidden("ميزة شاشة المطبخ (KDS) غير مفعلة في باقة اشتراك هذا المطعم. يرجى ترقية الباقة لتفعيلها.")

    if not user_has_perm(request.user, "kds_access"):
        return HttpResponseForbidden("غير مصرح لك بالوصول إلى شاشة المطبخ (KDS)")

    branch = get_active_branch(request)
    profile = getattr(request.user, "profile", None)
    emp = getattr(request.user, "employee_profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    can_cross = (
        is_owner
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )

    q_branch = request.GET.get("branch_id")
    if can_cross and q_branch and q_branch.isdigit():
        target_branch_id = int(q_branch)
    else:
        target_branch_id = branch.id if branch else None

    orders_qs = Order.objects.filter(
        tenant=tenant,
        status__in=["new", "preparing"]
    ).prefetch_related("items__menu_item", "branch").order_by("created_at")

    if target_branch_id:
        orders_qs = orders_qs.filter(branch_id=target_branch_id)

    orders_data = [serialize_kitchen_order(o) for o in orders_qs]

    # Extract all distinct categories available in this tenant's menu
    menu_categories = list(
        MenuItem.objects.filter(tenant=tenant)
        .exclude(category="")
        .values_list("category", flat=True)
        .distinct()
    )
    if not menu_categories:
        menu_categories = ["مشويات", "أطباق رئيسية", "مقبلات", "مشروبات", "حلويات", "ساندويتشات"]
    else:
        menu_categories = sorted(list(set(menu_categories)))

    # Calculate station counts across pending orders
    station_counts = {}
    for o in orders_data:
        for cat in o.get("categories", []):
            station_counts[cat] = station_counts.get(cat, 0) + 1

    branches = list(Branch.objects.filter(tenant=tenant, status="active"))

    context = {
        "tenant": tenant,
        "branch": branch,
        "target_branch_id": target_branch_id,
        "branches": branches,
        "kitchen_orders": orders_data,
        "kitchen_orders_json": json.dumps(orders_data),
        "total_pending": len(orders_data),
        "menu_categories": menu_categories,
        "station_counts": station_counts,
        "station_counts_json": json.dumps(station_counts),
    }
    return render(request, "kitchen.html", context)


async def kitchen_stream_view(request):
    """
    True Real-Time Server-Sent Events (SSE) push stream for the Kitchen Display Screen (KDS).
    Pushes events: 'connected', 'new_order', 'order_status_changed', 'order_updated', 'order_cancelled'.
    Maintains persistent ASGI connection with automatic keepalive (zero polling, 0ms latency).
    """
    if not request.user.is_authenticated:
        return HttpResponseForbidden("يرجى تسجيل الدخول للوصول إلى بث المطبخ المباشر")

    tenant = await sync_to_async(get_active_tenant)(request)
    if not tenant:
        return HttpResponseForbidden("المنشأة غير موجودة")

    has_kds_feat = await sync_to_async(tenant.has_feature)("kds")
    if not has_kds_feat:
        return HttpResponseForbidden("ميزة شاشة المطبخ (KDS) غير مفعلة في باقة اشتراك هذا المطعم")

    has_perm = await sync_to_async(user_has_perm)(request.user, "kds_access")
    if not has_perm:
        return HttpResponseForbidden("غير مصرح لك بالوصول إلى شاشة المطبخ (KDS)")

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

    queue = await kitchen_broadcaster.register(tenant.id, branch_id)

    async def event_generator():
        try:
            # Initial connection confirmation event
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
                    # Heartbeat comment to keep connection alive through proxies
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await kitchen_broadcaster.unregister(queue)

    response = StreamingHttpResponse(event_generator(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    response["Connection"] = "keep-alive"
    return response


@login_required
def kitchen_live_view(request):
    """
    Returns JSON snapshot of all active kitchen orders (new & preparing)
    along with calculated category stations and counts.
    """
    tenant = get_active_tenant(request)
    if tenant and not tenant.has_feature("kds"):
        return JsonResponse({"error": "ميزة شاشة المطبخ (KDS) غير مفعلة في باقة اشتراك هذا المطعم"}, status=403)

    if not user_has_perm(request.user, "kds_access"):
        return JsonResponse({"error": "غير مصرح لك بالوصول"}, status=403)
    branch = get_active_branch(request)
    profile = getattr(request.user, "profile", None)
    emp = getattr(request.user, "employee_profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    can_cross = (
        is_owner
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )

    q_branch = request.GET.get("branch_id")
    if can_cross and q_branch and q_branch.isdigit():
        target_branch_id = int(q_branch)
    else:
        target_branch_id = branch.id if branch else None

    orders_qs = Order.objects.filter(
        tenant=tenant,
        status__in=["new", "preparing"]
    ).prefetch_related("items__menu_item", "branch").order_by("created_at")

    if target_branch_id:
        orders_qs = orders_qs.filter(branch_id=target_branch_id)

    orders_data = [serialize_kitchen_order(o) for o in orders_qs]

    station_counts = {}
    for o in orders_data:
        for cat in o.get("categories", []):
            station_counts[cat] = station_counts.get(cat, 0) + 1

    return JsonResponse({
        "ok": True,
        "target_branch_id": target_branch_id,
        "orders": orders_data,
        "total_pending": len(orders_data),
        "station_counts": station_counts,
        "timestamp": timezone.now().isoformat(),
    })


# ==========================================
# 4. BRANCH ORDERS VIEW
# ==========================================

@login_required
@ensure_csrf_cookie
def branch_orders_view(request):
    if not user_has_perm(request.user, "view_orders"):
        return HttpResponseForbidden("غير مصرح لك باستعراض سجل طلبات الفرع")

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
        "branch": branch,
        "orders": page_obj,
        "page_obj": page_obj,
        "paginator": paginator,
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

    if not is_owner and not user_has_perm(request.user, "view_orders"):
        return HttpResponseForbidden("غير مصرح لك باستعراض سجل الطلبات")

    # If user is strictly branch-locked, redirect to branch orders
    can_operate_cross = (
        is_owner
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
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

    if not is_owner and not (user_has_perm(request.user, "pos_cancel_order") or user_has_perm(request.user, "cancel_orders")):
        return JsonResponse({"error": "غير مصرح لك بإلغاء الفواتير. يرجى مراجعة مدير الفرع لتسجيل الدخول من حسابه."}, status=403)

    order = get_object_or_404(Order, tenant=tenant, id=order_id)
    emp = getattr(request.user, "employee_profile", None)
    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    can_cross = (
        is_owner
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
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
    return JsonResponse({"ok": True, "status": "cancelled", "message": f"تم إلغاء الطلب {order.order_number} بنجاح"})


@login_required
def api_delete_order(request, order_id):
    if request.method not in ["POST", "DELETE"]:
        return HttpResponseBadRequest("POST or DELETE required")

    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner and not user_has_perm(request.user, "delete_orders"):
        return JsonResponse({"error": "غير مصرح لك بحذف الفواتير نهائياً. هذه العملية مقتصرة على الإدارة العامة."}, status=403)

    order = get_object_or_404(Order, tenant=tenant, id=order_id)
    emp = getattr(request.user, "employee_profile", None)
    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    can_cross = (
        is_owner
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
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
    order.delete()
    return JsonResponse({"ok": True, "message": f"تم حذف الطلب {order_number} نهائياً من قاعدة البيانات"})


# ==========================================
# 5. BRANCH MENU AVAILABILITY VIEW
# ==========================================

@login_required
@ensure_csrf_cookie
def branch_menu_view(request):
    if not (
        user_has_perm(request.user, "manage_menu") or
        user_has_perm(request.user, "menu_view") or
        user_has_perm(request.user, "menu_toggle_availability") or
        user_has_perm(request.user, "menu_edit_item")
    ):
        return HttpResponseForbidden("غير مصرح لك باستعراض أو إدارة قائمة الطعام")

    tenant = get_active_tenant(request)
    branch = get_active_branch(request)

    profile = getattr(request.user, "profile", None)
    can_manage_menu = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin)) or user_has_perm(request.user, "manage_menu") or user_has_perm(request.user, "menu_create_item")

    # Dynamic Categories from MenuCategory
    cat_objs = list(MenuCategory.objects.filter(tenant=tenant, is_active=True).order_by("ordering", "id"))
    category_names = ["الكل"] + [c.name for c in cat_objs]
    cat_filter = request.GET.get("cat", "الكل")
    search = request.GET.get("q", "").strip()

    menu_qs = MenuItem.objects.filter(tenant=tenant, is_active=True).prefetch_related("variants").order_by("category", "name")
    if cat_filter != "الكل":
        menu_qs = menu_qs.filter(category=cat_filter)
    if search:
        menu_qs = menu_qs.filter(name__icontains=search)

    branch_avail_map = {}
    branch_price_map = {}
    branch_variant_price_map = {}
    if branch:
        for av in BranchMenuAvailability.objects.filter(branch=branch):
            branch_avail_map[av.menu_item_id] = av.is_available
            branch_price_map[av.menu_item_id] = av.custom_price
        for vp in BranchVariantPrice.objects.filter(branch=branch):
            branch_variant_price_map[vp.variant_id] = vp.custom_price

    items_data = []
    for item in menu_qs:
        if branch:
            is_avail = branch_avail_map.get(item.id, item.available)
            custom_price = branch_price_map.get(item.id)
            effective_price = custom_price if custom_price is not None else item.price
            variants_list = []
            for v in item.variants.all():
                v_custom = branch_variant_price_map.get(v.id)
                variants_list.append({
                    "id": v.id,
                    "name": v.name,
                    "name_en": v.name_en,
                    "default_price": v.price,
                    "custom_price": v_custom,
                    "effective_price": v_custom if v_custom is not None else v.price,
                })
        else:
            is_avail = item.available
            custom_price = None
            effective_price = item.price
            variants_list = [{
                "id": v.id,
                "name": v.name,
                "name_en": v.name_en,
                "default_price": v.price,
                "custom_price": None,
                "effective_price": v.price,
            } for v in item.variants.all()]

        items_data.append({
            "item": item,
            "is_available": is_avail,
            "custom_price": custom_price,
            "effective_price": effective_price,
            "effective_min_price": item.get_min_price_for_branch(branch) if branch else item.min_price,
            "variants_data": variants_list,
            "variants": list(item.variants.all()),
        })

    currency_sym = branch.get_currency_symbol_ar() if branch else (tenant.get_currency_symbol_ar() if tenant else "ر.س")

    context = {
        "tenant": tenant,
        "branch": branch,
        "branches": Branch.objects.filter(tenant=tenant, status="active"),
        "items_data": items_data,
        "categories": category_names,
        "category_objs": cat_objs,
        "selected_cat": cat_filter,
        "search_query": search,
        "can_manage_menu": can_manage_menu,
        "branch_currency_symbol": currency_sym,
    }
    return render(request, "branch_menu.html", context)


# ==========================================
# 6. OPERATIONAL SCREENS
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
    categories = ["الكل", "أطباق رئيسية", "مشويات", "ساندويتشات", "برجر", "دجاج", "مقبلات", "مشروبات", "حلويات"]

    base_menu = MenuItem.objects.filter(tenant=tenant, available=True).order_by("category", "name")
    if branch:
        disabled_ids = set(BranchMenuAvailability.objects.filter(branch=branch, is_available=False).values_list("menu_item_id", flat=True))
        raw_items = list(base_menu.exclude(id__in=disabled_ids))
    else:
        raw_items = list(base_menu)

    menu_items = []
    for m in raw_items:
        m.price = m.get_price_for_branch(branch)
        menu_items.append(m)

    recent_orders = Order.objects.filter(tenant=tenant).order_by("-id")
    if branch:
        recent_orders = recent_orders.filter(branch=branch)

    currency_sym = branch.get_currency_symbol_ar() if branch else (tenant.get_currency_symbol_ar() if tenant else "ر.س")
    branches = list(tenant.branches.filter(status="active").order_by("name")) if tenant else []

    context = {
        "tenant": tenant,
        "current_branch": branch,
        "branches": branches,
        "categories": categories,
        "menu_items": menu_items,
        "recent_orders": recent_orders[:10],
        "branch_currency_symbol": currency_sym,
    }
    return render(request, "pos.html", context)


@login_required
@ensure_csrf_cookie
def call_center_view(request):
    tenant = get_active_tenant(request)
    if tenant and not tenant.has_feature("call_center"):
        return HttpResponseForbidden("ميزة الكول سنتر غير مفعلة في باقة اشتراك هذا المطعم. يرجى ترقية الباقة لتفعيلها.")

    if not user_has_perm(request.user, "call_center_access"):
        return HttpResponseForbidden("غير مصرح لك بالوصول إلى الكول سنتر")
    branches = Branch.objects.filter(tenant=tenant, status="active").prefetch_related("delivery_areas").order_by("name")
    menu_items = MenuItem.objects.filter(tenant=tenant, available=True).order_by("category", "name")
    recent_orders = Order.objects.filter(tenant=tenant, channel="call_center").order_by("-id")[:10]
    delivery_areas = DeliveryArea.objects.filter(branch__tenant=tenant, is_active=True).select_related("branch").order_by("branch__name", "name")

    seen_cats = []
    for m in menu_items:
        if m.category and m.category not in seen_cats:
            seen_cats.append(m.category)
    categories = ["الكل"] + (seen_cats if seen_cats else ["أطباق رئيسية", "مشويات", "ساندويتشات", "مشروبات"])

    currency_sym = tenant.get_currency_symbol_ar() if tenant else "ر.س"

    context = {
        "tenant": tenant,
        "branches": branches,
        "delivery_areas": delivery_areas,
        "categories": categories,
        "menu_items": menu_items,
        "recent_orders": recent_orders,
        "tenant_currency_symbol": currency_sym,
        "branch_currency_symbol": currency_sym,
    }
    return render(request, "call_center.html", context)


@login_required
@ensure_csrf_cookie
def delivery_view(request):
    tenant = get_active_tenant(request)
    if tenant and not (tenant.has_feature("delivery_management") or tenant.has_feature("delivery")):
        return HttpResponseForbidden("ميزة إدارة التوصيل غير مفعلة في باقة اشتراك هذا المطعم. يرجى ترقية الباقة لتفعيلها.")

    if not user_has_perm(request.user, "delivery_access"):
        return HttpResponseForbidden("غير مصرح لك بالوصول إلى قسم التوصيل")

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
    if tenant and not tenant.has_feature("inventory"):
        return HttpResponseForbidden("ميزة إدارة المخزون غير مفعلة في باقة اشتراك هذا المطعم. يرجى ترقية الباقة لتفعيلها.")

    if not (
        user_has_perm(request.user, "manage_inventory") or
        user_has_perm(request.user, "inventory_view") or
        user_has_perm(request.user, "inventory_add_stock") or
        user_has_perm(request.user, "inventory_adjust_stock")
    ):
        return HttpResponseForbidden("غير مصرح لك بالوصول لإدارة أو استعراض المخزون")
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


@login_required
@ensure_csrf_cookie
def employees_view(request):
    if not (
        user_has_perm(request.user, "manage_employees") or
        user_has_perm(request.user, "hr_view_employees") or
        user_has_perm(request.user, "hr_create_employee")
    ):
        return HttpResponseForbidden("غير مصرح لك باستعراض أو إدارة الموظفين")

    tenant = get_active_tenant(request)
    active_branch = get_active_branch(request)
    role_filter = request.GET.get("role", "all")
    job_role_filter = request.GET.get("job_role", "all")
    branch_filter = request.GET.get("branch", "all")
    search = request.GET.get("q", "").strip()

    employees = Employee.objects.filter(tenant=tenant).select_related("branch", "job_role").order_by("name")

    if active_branch:
        employees = employees.filter(branch=active_branch)
        branch_filter = active_branch.id
    elif branch_filter != "all" and str(branch_filter).isdigit():
        employees = employees.filter(branch_id=int(branch_filter))

    if job_role_filter != "all" and str(job_role_filter).isdigit():
        employees = employees.filter(job_role_id=int(job_role_filter))
    elif role_filter != "all":
        employees = employees.filter(Q(role=role_filter) | Q(job_role__name=role_filter))

    if search:
        employees = employees.filter(Q(name__icontains=search) | Q(phone__icontains=search) | Q(employee_code__icontains=search))

    branches = Branch.objects.filter(tenant=tenant).order_by("name")
    if tenant and not JobRole.objects.filter(tenant=tenant).exists():
        ensure_tenant_preset_roles(tenant)
    job_roles = JobRole.objects.filter(tenant=tenant).annotate(emp_count=Count("employees")).order_by("ordering", "id")

    base_qs = Employee.objects.filter(tenant=tenant, branch=active_branch) if active_branch else Employee.objects.filter(tenant=tenant)
    role_counts = dict(base_qs.values("role").annotate(c=Count("id")).values_list("role", "c"))
    roles_summary = {
        "all": sum(role_counts.values()),
        "manager": role_counts.get("manager", 0),
        "cashier": role_counts.get("cashier", 0),
        "chef": role_counts.get("chef", 0),
        "driver": role_counts.get("driver", 0),
        "call_center": role_counts.get("call_center", 0),
        "waiter": role_counts.get("waiter", 0),
    }

    # Calculate next suggested employee code for tenant
    max_numeric = 100
    for ec in Employee.objects.filter(tenant=tenant).values_list("employee_code", flat=True):
        if ec and ec.isdigit():
            max_numeric = max(max_numeric, int(ec))
    suggested_next_code = str(max_numeric + 1)

    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    can_manage_salaries = is_owner_or_super or user_has_perm(request.user, "hr_manage_salaries") or user_has_perm(request.user, "manage_employees")

    context = {
        "tenant": tenant,
        "current_branch": active_branch,
        "employees": employees,
        "branches": branches,
        "job_roles": job_roles,
        "permissions_catalog": PERMISSIONS_CATALOG,
        "role_filter": role_filter,
        "job_role_filter": job_role_filter,
        "branch_filter": branch_filter,
        "search_query": search,
        "roles_summary": roles_summary,
        "can_edit_id": is_owner_or_super,
        "can_manage_salaries": can_manage_salaries,
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

    if "driverId" in data:
        if not is_owner_or_super and not (user_has_perm(request.user, "delivery_assign_driver") or user_has_perm(request.user, "delivery_access") or user_has_perm(request.user, "edit_orders")):
            return JsonResponse({"error": "غير مصرح لك بإسناد السائقين للطلبات"}, status=403)
        drv_id = data["driverId"]
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

    return JsonResponse({"ok": True, "status": order.status})


@login_required
def api_toggle_branch_menu(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (user_has_perm(request.user, "menu_toggle_availability") or user_has_perm(request.user, "manage_menu")):
        return JsonResponse({"error": "غير مصرح لك بتعديل توفر الأصناف في الفرع"}, status=403)

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
        if not is_owner_or_super and not user_has_perm(request.user, "manage_menu"):
            return JsonResponse({"error": "تعطيل الصنف عن كافة الفروع يتطلب صلاحية إدارة المنيو الشاملة أو صفة المالك"}, status=403)
        item.available = not item.available
        item.save()
        return JsonResponse({"ok": True, "isAvailable": item.available, "itemName": item.name, "branch": "كل الفروع"})


@login_required
def api_update_branch_item_price(request, branch_id, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (
        user_has_perm(request.user, "manage_menu") or
        user_has_perm(request.user, "menu_edit_item") or
        user_has_perm(request.user, "manage_branches")
    ):
        return JsonResponse({"error": "غير مصرح لك بتعديل أسعار الأصناف في هذا الفرع"}, status=403)

    branch = get_object_or_404(Branch, tenant=tenant, id=branch_id)
    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    raw_price = data.get("custom_price")
    custom_price = None
    if raw_price is not None and str(raw_price).strip() != "":
        try:
            custom_price = max(Decimal("0.00"), Decimal(str(raw_price)))
        except Exception:
            return JsonResponse({"error": "قيمة السعر غير صحيحة"}, status=400)

    avail, _ = BranchMenuAvailability.objects.get_or_create(
        branch=branch,
        menu_item=item,
        defaults={"is_available": item.available}
    )
    avail.custom_price = custom_price
    avail.save(update_fields=["custom_price"])

    variants_data = data.get("variants") or []
    if isinstance(variants_data, list):
        for v_item in variants_data:
            v_id = v_item.get("variant_id")
            v_raw = v_item.get("custom_price")
            variant = item.variants.filter(id=v_id).first()
            if variant:
                v_price = None
                if v_raw is not None and str(v_raw).strip() != "":
                    try:
                        v_price = max(Decimal("0.00"), Decimal(str(v_raw)))
                    except Exception:
                        pass
                vp, _ = BranchVariantPrice.objects.get_or_create(
                    branch=branch,
                    variant=variant,
                    defaults={"is_available": True}
                )
                vp.custom_price = v_price
                vp.save(update_fields=["custom_price"])

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="branch_item_price_updated",
        target_model="MenuItem",
        target_id=item.id,
        description=f"تعديل سعر الصنف «{item.name}» في فرع «{branch.name}» إلى {custom_price if custom_price is not None else 'السعر الافتراضي'} {branch.get_currency_symbol_ar()}",
        ip_address=_get_client_ip(request),
    )

    effective_price = item.get_price_for_branch(branch)
    effective_min_price = item.get_min_price_for_branch(branch)
    return JsonResponse({
        "ok": True,
        "item_id": item.id,
        "branch_id": branch.id,
        "custom_price": float(custom_price) if custom_price is not None else None,
        "effective_price": float(effective_price),
        "effective_min_price": float(effective_min_price),
        "currency_symbol": branch.get_currency_symbol_ar(),
        "message": f"تم تحديث سعر «{item.name}» لفرع «{branch.name}» بنجاح."
    })


@login_required
def api_get_item_branch_prices(request, item_id):
    tenant = get_active_tenant(request)
    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)
    branches = Branch.objects.filter(tenant=tenant, status="active").order_by("id")

    b_avails = {av.branch_id: av for av in BranchMenuAvailability.objects.filter(menu_item=item)}
    b_v_prices = {}
    for vp in BranchVariantPrice.objects.filter(variant__menu_item=item):
        b_v_prices.setdefault(vp.branch_id, {})[vp.variant_id] = vp.custom_price

    branches_data = []
    item_variants = list(item.variants.all())

    for b in branches:
        av = b_avails.get(b.id)
        c_price = av.custom_price if av else None
        eff_price = c_price if c_price is not None else item.price

        v_list = []
        for v in item_variants:
            v_custom = b_v_prices.get(b.id, {}).get(v.id)
            v_eff = v_custom if v_custom is not None else v.price
            v_list.append({
                "variant_id": v.id,
                "name": v.name,
                "default_price": float(v.price),
                "custom_price": float(v_custom) if v_custom is not None else None,
                "effective_price": float(v_eff),
            })

        branches_data.append({
            "branch_id": b.id,
            "branch_name": b.name,
            "currency": b.currency,
            "currency_symbol": b.get_currency_symbol_ar(),
            "currency_name": b.get_currency_name_ar(),
            "custom_price": float(c_price) if c_price is not None else None,
            "effective_price": float(eff_price),
            "is_available": av.is_available if av else item.available,
            "variants": v_list,
        })

    return JsonResponse({
        "ok": True,
        "item": {
            "id": item.id,
            "name": item.name,
            "category": item.category,
            "default_price": float(item.price),
            "has_variants": item.has_variants,
            "tenant_currency": tenant.default_currency if tenant else "SAR",
            "tenant_currency_symbol": tenant.get_currency_symbol_ar() if tenant else "ر.س",
        },
        "branches": branches_data,
    })


@login_required
def api_update_item_branch_prices(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not user_has_perm(request.user, "manage_menu"):
        return JsonResponse({"error": "غير مصرح لك بتعديل أسعار الفروع المجمعة"}, status=403)

    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    branches_data = data.get("branches") or []
    updated_count = 0

    for b_entry in branches_data:
        b_id = b_entry.get("branch_id")
        branch = Branch.objects.filter(tenant=tenant, id=b_id).first()
        if not branch:
            continue

        raw_price = b_entry.get("custom_price")
        custom_price = None
        if raw_price is not None and str(raw_price).strip() != "":
            try:
                custom_price = max(Decimal("0.00"), Decimal(str(raw_price)))
            except Exception:
                pass

        avail, _ = BranchMenuAvailability.objects.get_or_create(
            branch=branch,
            menu_item=item,
            defaults={"is_available": item.available}
        )
        avail.custom_price = custom_price
        avail.save(update_fields=["custom_price"])
        updated_count += 1

        v_entries = b_entry.get("variants") or []
        for ve in v_entries:
            v_id = ve.get("variant_id")
            v_raw = ve.get("custom_price")
            variant = item.variants.filter(id=v_id).first()
            if variant:
                v_price = None
                if v_raw is not None and str(v_raw).strip() != "":
                    try:
                        v_price = max(Decimal("0.00"), Decimal(str(v_raw)))
                    except Exception:
                        pass
                vp, _ = BranchVariantPrice.objects.get_or_create(
                    branch=branch,
                    variant=variant,
                    defaults={"is_available": True}
                )
                vp.custom_price = v_price
                vp.save(update_fields=["custom_price"])

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="item_branch_prices_bulk_updated",
        target_model="MenuItem",
        target_id=item.id,
        description=f"تحديث أسعار الصنف «{item.name}» المخصصة لـ {updated_count} فروع",
        ip_address=_get_client_ip(request),
    )

    return JsonResponse({
        "ok": True,
        "message": f"تم تحديث أسعار الصنف «{item.name}» لـ {updated_count} فروع بنجاح.",
        "updated_count": updated_count
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


@login_required
def api_toggle_menu_item(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not user_has_perm(request.user, "manage_menu"):
        return JsonResponse({"error": "تعطيل أو تفعيل الصنف عن كامل المطعم مقتصر على إدارة المنيو العامة أو المالك"}, status=403)

    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)
    item.available = not item.available
    item.save()
    return JsonResponse({"ok": True, "available": item.available})


@login_required
def api_create_menu_item(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (user_has_perm(request.user, "menu_create_item") or user_has_perm(request.user, "manage_menu")):
        return JsonResponse({"error": "غير مصرح لك بإضافة أصناف جديدة للمنيو"}, status=403)

    is_multipart = request.content_type and "multipart/form-data" in request.content_type
    if is_multipart:
        data = request.POST
    else:
        try:
            data = json.loads(request.body.decode("utf-8")) if request.body else request.POST
        except Exception:
            data = request.POST

    name = str(data.get("name", "")).strip()
    if not name:
        return JsonResponse({"error": "اسم الصنف مطلوب"}, status=400)

    category_id = data.get("category_id")
    category_name = str(data.get("category", "")).strip()
    cat_obj = None
    if category_id:
        cat_obj = MenuCategory.objects.filter(tenant=tenant, id=category_id).first()
        if cat_obj:
            category_name = cat_obj.name
    elif category_name:
        cat_obj = MenuCategory.objects.filter(tenant=tenant, name__iexact=category_name).first()
        if not cat_obj:
            cat_obj = MenuCategory.objects.create(tenant=tenant, name=category_name)

    if not category_name:
        category_name = "أطباق رئيسية"

    price = Decimal(str(data.get("price") or 0))
    cost = Decimal(str(data.get("cost") or 0))
    description = str(data.get("description", "")).strip()
    name_en = str(data.get("name_en", "")).strip()
    description_en = str(data.get("description_en", "")).strip()
    emoji = str(data.get("emoji", "🍽️")).strip()

    # Parse Variants (Sizes) if provided
    variants_raw = data.get("variants")
    variants_list = []
    if variants_raw:
        if isinstance(variants_raw, str):
            try:
                variants_list = json.loads(variants_raw)
            except Exception:
                variants_list = []
        elif isinstance(variants_raw, list):
            variants_list = variants_raw

    has_variants = bool(variants_list)
    if has_variants:
        valid_prices = [Decimal(str(v.get("price", 0))) for v in variants_list if float(v.get("price", 0)) > 0]
        if valid_prices:
            price = min(valid_prices)

    if not has_variants and price <= 0:
        return JsonResponse({"error": "يرجى تحديد سعر صالح للصنف"}, status=400)

    item = MenuItem.objects.create(
        tenant=tenant,
        name=name,
        name_en=name_en,
        description=description,
        description_en=description_en,
        category=category_name,
        category_rel=cat_obj,
        price=price,
        cost=cost,
        emoji=emoji,
        available=True,
        has_variants=has_variants,
        is_active=True,
    )

    if "image" in request.FILES:
        item.image = request.FILES["image"]
        item.save(update_fields=["image"])

    # Create variant sizes
    has_any_default = any(bool(v.get("is_default")) for v in variants_list)
    for idx, v in enumerate(variants_list):
        v_name = str(v.get("name", "")).strip()
        v_name_en = str(v.get("name_en", "")).strip()
        v_price = Decimal(str(v.get("price", 0)))
        v_cost = Decimal(str(v.get("cost", 0)))
        is_def = bool(v.get("is_default")) if has_any_default else (idx == 0)
        if v_name and v_price > 0:
            MenuItemVariant.objects.create(
                menu_item=item,
                name=v_name,
                name_en=v_name_en,
                price=v_price,
                cost=v_cost,
                is_default=is_def,
                ordering=(idx + 1) * 10,
            )

    price_scope = request.POST.get("price_scope", "all")
    branch_id = request.POST.get("branch_id")
    target_branch = Branch.objects.filter(tenant=tenant, id=branch_id).first() if branch_id else None

    for b in Branch.objects.filter(tenant=tenant):
        c_price = price if (price_scope == "branch" and target_branch and b == target_branch) else None
        BranchMenuAvailability.objects.get_or_create(branch=b, menu_item=item, defaults={"is_available": True, "custom_price": c_price})

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="menu_item_created",
        target_model="MenuItem",
        target_id=item.id,
        description=f"إضافة الصنف «{item.name}» إلى قائمة الطعام (السعر: {item.price} ر.س، القسم: {item.category})",
        ip_address=_get_client_ip(request),
    )

    return JsonResponse({
        "status": "success",
        "id": item.id,
        "name": item.name,
        "price": float(item.price),
        "category": item.category,
        "image_url": item.image.url if item.image else "",
    }, status=201)


@login_required
def api_update_menu_item(request, item_id):
    if request.method not in ["POST", "PUT", "PATCH"]:
        return HttpResponseBadRequest("POST/PUT required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)

    is_multipart = request.content_type and "multipart/form-data" in request.content_type
    if is_multipart:
        data = request.POST
    else:
        try:
            data = json.loads(request.body.decode("utf-8")) if request.body else request.POST
        except Exception:
            data = request.POST

    if not is_owner_or_super and not (user_has_perm(request.user, "menu_edit_item") or user_has_perm(request.user, "manage_menu")):
        return JsonResponse({"error": "غير مصرح لك بتعديل بيانات أصناف المنيو"}, status=403)

    if "name" in data and str(data["name"]).strip():
        item.name = str(data["name"]).strip()

    if "name_en" in data:
        item.name_en = str(data["name_en"]).strip()

    if "description" in data:
        item.description = str(data["description"]).strip()

    if "description_en" in data:
        item.description_en = str(data["description_en"]).strip()

    if "category_id" in data and data["category_id"]:
        cat = MenuCategory.objects.filter(tenant=tenant, id=data["category_id"]).first()
        if cat:
            item.category_rel = cat
            item.category = cat.name
    elif "category" in data and str(data["category"]).strip():
        item.category = str(data["category"]).strip()
        cat = MenuCategory.objects.filter(tenant=tenant, name__iexact=item.category).first()
        if cat:
            item.category_rel = cat

    if "cost" in data:
        item.cost = Decimal(str(data["cost"] or 0))

    if "emoji" in data:
        item.emoji = str(data["emoji"])

    if "image" in request.FILES:
        item.image = request.FILES["image"]

    # Handle pricing scope: branch-specific vs all branches (master)
    price_scope = data.get("price_scope", "all")
    branch_id = data.get("branch_id")
    target_branch = Branch.objects.filter(tenant=tenant, id=branch_id).first() if branch_id else None

    # Handle variants if provided
    variants_raw = data.get("variants")
    variants_list = []
    if variants_raw:
        if isinstance(variants_raw, str):
            try:
                variants_list = json.loads(variants_raw)
            except Exception:
                variants_list = []
        elif isinstance(variants_raw, list):
            variants_list = variants_raw

    if price_scope == "branch" and target_branch:
        # 1. Save core item details without touching master item.price
        item.save()

        # 2. Update BranchMenuAvailability.custom_price for single-price items
        if not item.has_variants and "price" in data:
            raw_p = data.get("price")
            b_custom_price = None
            if raw_p is not None and str(raw_p).strip() != "":
                try:
                    b_custom_price = max(Decimal("0.00"), Decimal(str(raw_p)))
                except Exception:
                    pass
            avail, _ = BranchMenuAvailability.objects.get_or_create(
                branch=target_branch,
                menu_item=item,
                defaults={"is_available": item.available}
            )
            avail.custom_price = b_custom_price
            avail.save(update_fields=["custom_price"])

        # 3. If item has variants, update BranchVariantPrice for target_branch
        if item.has_variants and variants_list:
            for v_entry in variants_list:
                v_id = v_entry.get("id")
                v_price = v_entry.get("price")
                if v_id and v_price is not None:
                    var_obj = item.variants.filter(id=v_id).first()
                    if var_obj:
                        try:
                            vp_price = max(Decimal("0.00"), Decimal(str(v_price)))
                            vp, _ = BranchVariantPrice.objects.get_or_create(
                                branch=target_branch,
                                variant=var_obj,
                                defaults={"is_available": True}
                            )
                            vp.custom_price = vp_price
                            vp.save(update_fields=["custom_price"])
                        except Exception:
                            pass

        log_audit_event(
            tenant=tenant,
            user=request.user,
            action="branch_item_price_updated",
            target_model="MenuItem",
            target_id=item.id,
            description=f"تخصيص سعر الصنف «{item.name}» في فرع «{target_branch.name}» فقط إلى {data.get('price')} {target_branch.get_currency_symbol_ar()}",
            ip_address=_get_client_ip(request),
        )

        effective_price = item.get_price_for_branch(target_branch)
        return JsonResponse({
            "ok": True,
            "status": "success",
            "id": item.id,
            "name": item.name,
            "price": float(effective_price),
            "master_price": float(item.price),
            "price_scope": "branch",
            "branch_id": target_branch.id,
            "category": item.category,
            "image_url": item.image.url if item.image else "",
        })
    else:
        # price_scope == "all": Master price update for all branches
        if "variants" in data:
            if variants_list:
                item.has_variants = True
                item.variants.all().delete()
                has_any_default = any(bool(v.get("is_default")) for v in variants_list)
                for idx, v in enumerate(variants_list):
                    v_name = str(v.get("name", "")).strip()
                    v_name_en = str(v.get("name_en", "")).strip()
                    v_price = Decimal(str(v.get("price", 0)))
                    v_cost = Decimal(str(v.get("cost", 0)))
                    is_def = bool(v.get("is_default")) if has_any_default else (idx == 0)
                    if v_name and v_price > 0:
                        MenuItemVariant.objects.create(
                            menu_item=item,
                            name=v_name,
                            name_en=v_name_en,
                            price=v_price,
                            cost=v_cost,
                            is_default=is_def,
                            ordering=(idx + 1) * 10,
                        )
                valid_prices = [Decimal(str(v.get("price", 0))) for v in variants_list if float(v.get("price", 0)) > 0]
                if valid_prices:
                    item.price = min(valid_prices)
            else:
                item.has_variants = False
                item.variants.all().delete()
                if "price" in data:
                    item.price = Decimal(str(data["price"] or 0))
        elif "price" in data:
            new_price = Decimal(str(data["price"] or 0))
            if new_price > 0:
                item.price = new_price

        item.save()

        # If user explicitly updated all branches from a branch view, clear that branch's custom override
        if target_branch:
            BranchMenuAvailability.objects.filter(branch=target_branch, menu_item=item).update(custom_price=None)
            for v_obj in item.variants.all():
                BranchVariantPrice.objects.filter(branch=target_branch, variant=v_obj).update(custom_price=None)

        log_audit_event(
            tenant=tenant,
            user=request.user,
            action="menu_item_updated",
            target_model="MenuItem",
            target_id=item.id,
            description=f"تحديث السعر العام للصنف «{item.name}» لجميع الفروع إلى {item.price} {tenant.get_currency_symbol_ar() if tenant else 'ر.س'}",
            ip_address=_get_client_ip(request),
        )

        return JsonResponse({
            "ok": True,
            "status": "success",
            "id": item.id,
            "name": item.name,
            "price": float(item.price),
            "price_scope": "all",
            "category": item.category,
            "image_url": item.image.url if item.image else "",
        })


@login_required
def api_delete_menu_item(request, item_id):
    if request.method not in ["POST", "DELETE"]:
        return HttpResponseBadRequest("POST/DELETE required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (user_has_perm(request.user, "menu_delete_item") or user_has_perm(request.user, "manage_menu")):
        return JsonResponse({"error": "غير مصرح لك بحذف أصناف من المنيو"}, status=403)

    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)
    item_name = item.name
    item_id_val = item.id
    item_price = item.price

    # Safe Soft Delete
    item.is_active = False
    item.available = False
    item.save(update_fields=["is_active", "available"])

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="menu_item_deleted",
        target_model="MenuItem",
        target_id=item_id_val,
        description=f"أرشفة/حذف الصنف «{item_name}» من قائمة الطعام (السعر: {item_price} ر.س)",
        ip_address=_get_client_ip(request),
    )
    return JsonResponse({"ok": True, "message": f"تم حذف الصنف «{item_name}» بنجاح"})


# ----------------------------------------------------
# Dynamic Category Management APIs
# ----------------------------------------------------

@login_required
def api_list_categories(request):
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"error": "منشأة غير موجودة"}, status=400)
    cats = MenuCategory.objects.filter(tenant=tenant, is_active=True).order_by("ordering", "id")
    data = []
    for c in cats:
        data.append({
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "ordering": c.ordering,
            "image_url": c.image.url if c.image else "",
            "items_count": c.items.filter(is_active=True).count(),
        })
    return JsonResponse({"ok": True, "categories": data})


@login_required
def api_create_category(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner_or_super and not user_has_perm(request.user, "manage_menu"):
        return JsonResponse({"error": "غير مصرح لك بإضافة تصنيفات"}, status=403)

    is_multipart = request.content_type and "multipart/form-data" in request.content_type
    data = request.POST if is_multipart else (json.loads(request.body.decode("utf-8")) if request.body else request.POST)

    name = str(data.get("name", "")).strip()
    if not name:
        return JsonResponse({"error": "اسم التصنيف مطلوب"}, status=400)

    ordering = int(data.get("ordering", 10) or 10)
    existing_cat = MenuCategory.objects.filter(tenant=tenant, name=name).first()
    if existing_cat:
        if existing_cat.is_active:
            return JsonResponse({"error": "يوجد قسم نشط بهذا الاسم مسبقاً"}, status=400)
        else:
            cat = existing_cat
            cat.is_active = True
            cat.ordering = ordering
    else:
        cat = MenuCategory.objects.create(
            tenant=tenant,
            name=name,
            ordering=ordering,
            is_active=True
        )

    if "description" in data:
        cat.description = str(data["description"]).strip()

    if "name_en" in data:
        cat.name_en = str(data["name_en"]).strip()

    if "description_en" in data:
        cat.description_en = str(data["description_en"]).strip()

    if "image" in request.FILES:
        cat.image = request.FILES["image"]

    cat.save()
    return JsonResponse({
        "status": "success",
        "id": cat.id,
        "name": cat.name,
        "name_en": cat.name_en,
        "ordering": cat.ordering,
        "image_url": cat.image.url if cat.image else "",
    }, status=201)


@login_required
def api_update_category(request, cat_id):
    if request.method not in ["POST", "PUT", "PATCH"]:
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner_or_super and not user_has_perm(request.user, "manage_menu"):
        return JsonResponse({"error": "غير مصرح لك بتعديل التصنيفات"}, status=403)

    cat = get_object_or_404(MenuCategory, tenant=tenant, id=cat_id)
    is_multipart = request.content_type and "multipart/form-data" in request.content_type
    data = request.POST if is_multipart else (json.loads(request.body.decode("utf-8")) if request.body else request.POST)

    if "name" in data and str(data["name"]).strip():
        new_name = str(data["name"]).strip()
        if MenuCategory.objects.filter(tenant=tenant, name=new_name).exclude(id=cat.id).exists():
            return JsonResponse({"error": "يوجد قسم آخر بنفس هذا الاسم مسبقاً"}, status=400)
        old_name = cat.name
        cat.name = new_name
        MenuItem.objects.filter(tenant=tenant, category=old_name).update(category=cat.name)

    if "name_en" in data:
        cat.name_en = str(data["name_en"]).strip()

    if "description" in data:
        cat.description = str(data["description"]).strip()

    if "description_en" in data:
        cat.description_en = str(data["description_en"]).strip()

    if "ordering" in data:
        cat.ordering = int(data["ordering"] or 10)

    if "image" in request.FILES:
        cat.image = request.FILES["image"]

    cat.save()
    return JsonResponse({
        "status": "success",
        "id": cat.id,
        "name": cat.name,
        "ordering": cat.ordering,
        "image_url": cat.image.url if cat.image else "",
    })


@login_required
def api_delete_category(request, cat_id):
    if request.method not in ["POST", "DELETE"]:
        return HttpResponseBadRequest("POST/DELETE required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner_or_super and not user_has_perm(request.user, "manage_menu"):
        return JsonResponse({"error": "غير مصرح لك بحذف التصنيفات"}, status=403)

    cat = get_object_or_404(MenuCategory, tenant=tenant, id=cat_id)
    cat_name = cat.name
    cat.is_active = False
    cat.save(update_fields=["is_active"])
    return JsonResponse({"status": "success", "message": f"تم حذف التصنيف «{cat_name}» بنجاح"})


@login_required
def api_adjust_inventory(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    emp = getattr(request.user, "employee_profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if tenant and not tenant.has_feature("inventory") and not (request.user.is_superuser or (profile and profile.is_platform_admin)):
        return JsonResponse({"error": "ميزة إدارة المخزون غير مفعلة في باقة اشتراك هذا المطعم"}, status=403)

    if not is_owner_or_super and not (user_has_perm(request.user, "inventory_adjust_stock") or user_has_perm(request.user, "manage_inventory")):
        return JsonResponse({"error": "غير مصرح لك بتسوية أو تعديل كميات المخزون"}, status=403)

    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    can_cross = (
        is_owner_or_super
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    with transaction.atomic():
        item = InventoryItem.objects.select_for_update().filter(tenant=tenant, id=item_id).first()
        if not item:
            return JsonResponse({"error": "عنصر المخزون غير موجود"}, status=404)

        if not can_cross and user_branch and item.branch and item.branch != user_branch:
            return JsonResponse({"error": "غير مصرح لك بتسوية مخزون الفروع الأخرى"}, status=403)

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
        log_audit_event(
            tenant=tenant,
            user=request.user,
            action="inventory_stock_adjusted",
            target_model="InventoryItem",
            target_id=item.id,
            description=f"تسوية مخزون المادة «{item.name}» إلى {item.quantity} {item.unit} في فرع «{item.branch.name if item.branch else ''}»",
            ip_address=_get_client_ip(request),
        )
        return JsonResponse({"ok": True, "quantity": float(item.quantity), "minQuantity": float(item.min_quantity)})


@login_required
def api_create_inventory(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    emp = getattr(request.user, "employee_profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if tenant and not tenant.has_feature("inventory") and not (request.user.is_superuser or (profile and profile.is_platform_admin)):
        return JsonResponse({"error": "ميزة إدارة المخزون غير مفعلة في باقة اشتراك هذا المطعم"}, status=403)

    if not is_owner_or_super and not (user_has_perm(request.user, "inventory_add_stock") or user_has_perm(request.user, "manage_inventory")):
        return JsonResponse({"error": "غير مصرح لك بإضافة مواد جديدة للمخزون"}, status=403)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    name = str(data.get("name", "")).strip()
    branch_id = data.get("branchId")
    if not name or not branch_id:
        return JsonResponse({"error": "اسم المادة والفرع مطلوبان"}, status=400)

    branch = get_object_or_404(Branch, tenant=tenant, id=branch_id)
    if branch.status != "active":
        return JsonResponse({"error": "لا يمكن إضافة مخزون لفرع مغلق أو غير نشط"}, status=400)
    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    can_cross = (
        is_owner_or_super
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )
    if not can_cross and user_branch and branch != user_branch:
        return JsonResponse({"error": "غير مصرح لك بإضافة مخزون في الفروع الأخرى"}, status=403)

    item = InventoryItem.objects.create(
        tenant=tenant,
        branch=branch,
        name=name,
        unit=data.get("unit", "كجم"),
        quantity=max(Decimal("0"), Decimal(str(data.get("quantity") or 0))),
        min_quantity=max(Decimal("0"), Decimal(str(data.get("minQuantity") or 5))),
        supplier=data.get("supplier", ""),
    )
    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="inventory_item_created",
        target_model="InventoryItem",
        target_id=item.id,
        description=f"إضافة المادة «{item.name}» برصيد أولي {item.quantity} {item.unit} لفرع «{branch.name}»",
        ip_address=_get_client_ip(request),
    )
    return JsonResponse({"ok": True, "id": item.id})


@login_required
def api_delete_inventory(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    emp = getattr(request.user, "employee_profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if tenant and not tenant.has_feature("inventory") and not (request.user.is_superuser or (profile and profile.is_platform_admin)):
        return JsonResponse({"error": "ميزة إدارة المخزون غير مفعلة في باقة اشتراك هذا المطعم"}, status=403)

    if not is_owner_or_super and not user_has_perm(request.user, "manage_inventory"):
        return JsonResponse({"error": "غير مصرح لك بحذف مواد من المخزون (يتطلب صلاحية إدارة المخزون)"}, status=403)

    item = get_object_or_404(InventoryItem, tenant=tenant, id=item_id)
    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    can_cross = (
        is_owner_or_super
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )
    if not can_cross and user_branch and item.branch and item.branch != user_branch:
        return JsonResponse({"error": "غير مصرح لك بحذف مخزون الفروع الأخرى"}, status=403)

    item_name = item.name
    item_id_val = item.id
    item_qty = item.quantity
    item_unit = item.unit
    b_name = item.branch.name if item.branch else "الفرع"
    item.delete()
    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="inventory_item_deleted",
        target_model="InventoryItem",
        target_id=item_id_val,
        description=f"حذف عنصر المخزون «{item_name}» (الكمية: {item_qty} {item_unit}) من فرع «{b_name}»",
        ip_address=_get_client_ip(request),
    )
    return JsonResponse({"ok": True, "message": f"تم حذف عنصر المخزون «{item_name}» بنجاح"})


@login_required
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


def get_or_create_employee_user(tenant, employee_code, name, exclude_emp_id=None, password=None):
    """
    Safely find or create a dedicated Django User account for an employee without
    ever colliding with another employee's OneToOne User relationship.
    """
    tenant_slug = tenant.slug if tenant else "sys"
    clean_code = str(employee_code or "emp").strip()
    base_username = f"emp_{tenant_slug}_{clean_code}"
    username = base_username
    suffix = 1

    while True:
        existing_user = User.objects.filter(username=username).first()
        if not existing_user:
            user_obj = User.objects.create(username=username, first_name=name)
            if password:
                user_obj.set_password(password)
            else:
                user_obj.set_unusable_password()
            user_obj.save()
            return user_obj

        # Check if user is already attached to another employee
        emp_qs = Employee.objects.filter(user=existing_user)
        if exclude_emp_id:
            emp_qs = emp_qs.exclude(id=exclude_emp_id)

        if emp_qs.exists():
            suffix += 1
            username = f"{base_username}_{suffix}"
        else:
            existing_user.first_name = name
            if password:
                existing_user.set_password(password)
            existing_user.save()
            return existing_user


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

    if tenant and not tenant.can_add_employee():
        max_e = tenant.subscription_plan.max_employees if tenant.subscription_plan else 0
        return JsonResponse({
            "error": f"لقد استنفدت الحد الأقصى للموظفين المسموح بهم في باقتك الحالية ({max_e} موظف). يرجى ترقية باقة الاشتراك لإضافة موظف جديد."
        }, status=400)

    if not is_owner_or_super and not (user_has_perm(request.user, "hr_create_employee") or user_has_perm(request.user, "manage_employees")):
        return JsonResponse({"error": "غير مصرح لك بإضافة موظفين"}, status=403)

    branch_id = data.get("branchId") if "branchId" in data else data.get("branch_id")
    branch = Branch.objects.filter(tenant=tenant, id=branch_id).first() if branch_id else (profile.branch if profile and profile.branch else None)

    # Branch managers can only create employees in their branch
    if not is_owner_or_super and profile and profile.branch and branch != profile.branch:
        return JsonResponse({"error": "غير مصرح لك بإضافة موظف في فرع آخر"}, status=403)

    trans_table = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    # Generate or validate employee code
    code = str(data.get("employeeCode") or data.get("employee_code") or "").translate(trans_table).strip()
    if not code:
        max_numeric = 100
        for ec in Employee.objects.filter(tenant=tenant).values_list("employee_code", flat=True):
            clean_ec = str(ec or "").translate(trans_table).strip()
            if clean_ec and clean_ec.isdigit():
                max_numeric = max(max_numeric, int(clean_ec))
        code = str(max_numeric + 1)
    elif Employee.objects.filter(tenant=tenant, employee_code=code).exists():
        return JsonResponse({"error": f"كود الموظف ({code}) مستخدم مسبقاً في هذا المطعم، يرجى اختيار كود آخر"}, status=400)

    pin = str(data.get("pin") or data.get("pin_code") or "").translate(trans_table).strip()
    if not pin:
        import secrets
        pin = str(secrets.randbelow(9000) + 1000)
    elif len(pin) < 4:
        return JsonResponse({"error": "رمز PIN يجب أن يتكون من 4 أرقام على الأقل"}, status=400)

    # Job Role resolution
    job_role = None
    job_role_id = data.get("jobRoleId") if "jobRoleId" in data else data.get("job_role_id")
    if job_role_id and str(job_role_id).isdigit():
        if not is_owner_or_super and not (
            user_has_perm(request.user, "manage_roles") or
            user_has_perm(request.user, "system_manage_roles") or
            user_has_perm(request.user, "manage_employees")
        ):
            return JsonResponse({"error": "غير مصرح لك بتعيين المسمى الوظيفي والصلاحيات للموظف"}, status=403)
        job_role = JobRole.objects.filter(tenant=tenant, id=int(job_role_id)).first()

    salary_val = Decimal("4000")
    if "salary" in data and str(data["salary"]).strip():
        try:
            custom_salary = Decimal(str(data["salary"]))
            if custom_salary < 0:
                return JsonResponse({"error": "الراتب لا يمكن أن يكون سالباً"}, status=400)
            if custom_salary != salary_val and not is_owner_or_super and not (
                user_has_perm(request.user, "hr_manage_salaries") or
                user_has_perm(request.user, "manage_employees")
            ):
                return JsonResponse({"error": "غير مصرح لك بتحديد راتب مخصص للموظف"}, status=403)
            salary_val = custom_salary
        except Exception:
            return JsonResponse({"error": "قيمة الراتب غير صالحة"}, status=400)

    password = str(data.get("password") or "").strip() or None
    if password:
        if not is_owner_or_super and not (user_has_perm(request.user, "hr_manage_credentials") or user_has_perm(request.user, "manage_employees")):
            return JsonResponse({"error": "غير مصرح لك بتعيين كلمة مرور لحساب الموظف"}, status=403)
        if len(password) < 6:
            return JsonResponse({"error": "كلمة المرور يجب أن تتكون من 6 أحرف على الأقل"}, status=400)

    raw_role = str(data.get("role") or "").strip()
    if not raw_role and job_role:
        perms = set(job_role.get_permissions_list())
        if "pos_access" in perms:
            raw_role = "cashier"
        elif "kds_access" in perms:
            raw_role = "chef"
        elif "delivery_access" in perms:
            raw_role = "driver"
        elif "call_center_access" in perms:
            raw_role = "call_center"
        elif "manage_employees" in perms or "manage_branches" in perms or "hr_manage_shifts" in perms:
            raw_role = "manager"
        else:
            raw_role = "cashier"
    elif not raw_role:
        raw_role = "cashier"

    legacy_role = raw_role if raw_role in dict(Employee.ROLE_CHOICES) else "cashier"

    with transaction.atomic():
        user_obj = get_or_create_employee_user(tenant, code, name, password=password)

        emp = Employee.objects.create(
            tenant=tenant,
            name=name,
            phone=str(data.get("phone", "")).strip(),
            role=legacy_role,
            job_role=job_role,
            branch=branch,
            salary=salary_val,
            employee_code=code,
            user=user_obj,
        )
        emp.set_pin(pin)
        emp.save()

        user_profile_role = "branch_manager" if legacy_role == "manager" else legacy_role
        UserProfile.objects.update_or_create(
            user=user_obj,
            defaults={
                "tenant": tenant,
                "role": user_profile_role,
                "job_role": emp.job_role,
                "branch": emp.branch,
            }
        )

        # Sync with Django auth Group
        if emp.job_role:
            grp = emp.job_role.sync_with_django_group()
            if grp:
                user_obj.groups.set([grp])
        else:
            user_obj.groups.clear()

        log_audit_event(
            tenant=tenant,
            user=request.user,
            action="employee_created",
            target_model="Employee",
            target_id=emp.id,
            description=f"إضافة موظف جديد «{emp.name}» كود ({code}) ومسمى «{emp.job_role.name if emp.job_role else emp.role}»",
            ip_address=_get_client_ip(request),
        )

    return JsonResponse({
        "ok": True,
        "id": emp.id,
        "name": emp.name,
        "employeeCode": code,
        "pin": pin,
        "jobRole": emp.job_role.name if emp.job_role else emp.get_role_display()
    })


@login_required
def api_update_employee(request, emp_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    emp = get_object_or_404(Employee, tenant=tenant, id=emp_id)

    # Protect Owner Account from subordinate tampering
    is_target_owner = emp.user and (emp.user.is_superuser or (hasattr(emp.user, "profile") and emp.user.profile.role in ["owner", "platform_admin"]))
    if is_target_owner and not is_owner_or_super:
        return JsonResponse({"error": "غير مصرح لك بتعديل بيانات أو صلاحيات حساب مالك المنشأة"}, status=403)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    # Permission check
    if not is_owner_or_super and not (user_has_perm(request.user, "hr_edit_employee") or user_has_perm(request.user, "manage_employees")):
        return JsonResponse({"error": "غير مصرح لك بتعديل بيانات الموظفين"}, status=403)

    # Branch managers can only edit employees in their branch
    if not is_owner_or_super and profile and profile.branch and emp.branch != profile.branch:
        return JsonResponse({"error": "غير مصرح لك بتعديل موظفي الفروع الأخرى"}, status=403)

    if "name" in data and str(data["name"]).strip():
        emp.name = str(data["name"]).strip()
        if emp.user:
            emp.user.first_name = emp.name
            emp.user.save()

    trans_table = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    if "phone" in data:
        emp.phone = str(data["phone"]).translate(trans_table).strip()

    if "jobRoleId" in data or "job_role_id" in data:
        if not is_owner_or_super and not (
            user_has_perm(request.user, "manage_roles") or
            user_has_perm(request.user, "system_manage_roles") or
            user_has_perm(request.user, "manage_employees")
        ):
            return JsonResponse({"error": "غير مصرح لك بتعديل المسمى الوظيفي والصلاحيات للموظف"}, status=403)
        jr_id = data.get("jobRoleId") or data.get("job_role_id")
        if jr_id and str(jr_id).isdigit():
            emp.job_role = JobRole.objects.filter(tenant=tenant, id=int(jr_id)).first()
        else:
            emp.job_role = None
        if emp.user and hasattr(emp.user, "profile"):
            emp.user.profile.job_role = emp.job_role
            emp.user.profile.save()
        if emp.job_role:
            grp = emp.job_role.sync_with_django_group()
            if emp.user and grp:
                emp.user.groups.set([grp])
        elif emp.user:
            emp.user.groups.clear()

    if "role" in data and data["role"] in dict(Employee.ROLE_CHOICES):
        emp.role = data["role"]
        if emp.user and hasattr(emp.user, "profile"):
            emp.user.profile.role = emp.role
            emp.user.profile.save()

    if "status" in data and data["status"] in dict(Employee.STATUS_CHOICES):
        new_status = data["status"]
        if new_status == "inactive":
            if emp.user and request.user == emp.user:
                return JsonResponse({"error": "لا يمكنك تعطيل أو إلغاء تفعيل حسابك الشخصي لمنع قفل النظام"}, status=400)
            if is_target_owner and not is_owner_or_super:
                return JsonResponse({"error": "غير مصرح لك بتعطيل حساب مالك المنشأة"}, status=403)
        emp.status = new_status
        if emp.user:
            emp.user.is_active = (new_status == "active")
            emp.user.save(update_fields=["is_active"])

    if "salary" in data:
        if not is_owner_or_super and not (
            user_has_perm(request.user, "hr_manage_salaries") or
            user_has_perm(request.user, "manage_employees")
        ):
            return JsonResponse({"error": "غير مصرح لك بتعديل الراتب الأساسي للموظف"}, status=403)
        salary_str = str(data["salary"]).strip()
        if not salary_str:
            return JsonResponse({"error": "يرجى إدخال الراتب الأساسي للموظف"}, status=400)
        try:
            val = Decimal(salary_str)
            if val < 0:
                return JsonResponse({"error": "الراتب لا يمكن أن يكون سالباً"}, status=400)
            emp.salary = val
        except Exception:
            return JsonResponse({"error": "قيمة الراتب المدخلة غير صالحة"}, status=400)

    if ("branchId" in data or "branch_id" in data) and is_owner_or_super:
        b_id = data.get("branchId") if "branchId" in data else data.get("branch_id")
        if b_id and str(b_id).isdigit():
            emp.branch = Branch.objects.filter(tenant=tenant, id=int(b_id)).first()
        else:
            emp.branch = None
        if emp.user and hasattr(emp.user, "profile"):
            emp.user.profile.branch = emp.branch
            emp.user.profile.save()

    # Employee Code (ID) update - restricted to Superadmin and Owner
    new_code = str(data.get("employeeCode") or data.get("employee_code") or "").translate(trans_table).strip()
    if new_code and new_code != emp.employee_code:
        if not is_owner_or_super:
            return JsonResponse({"error": "تعديل كود الموظف مقتصر على المالك ومدير النظام فقط"}, status=403)
        if Employee.objects.filter(tenant=tenant, employee_code=new_code).exclude(id=emp.id).exists():
            return JsonResponse({"error": f"كود الموظف ({new_code}) مستخدم مسبقاً لموظف آخر"}, status=400)
        emp.employee_code = new_code

    # PIN change / reset - requires hr_manage_credentials
    new_pin = str(data.get("pin") or data.get("pin_code") or "").translate(trans_table).strip()
    if new_pin:
        if not is_owner_or_super and not (
            user_has_perm(request.user, "hr_manage_credentials") or
            user_has_perm(request.user, "manage_employees")
        ):
            return JsonResponse({"error": "غير مصرح لك بتعيين أو تغيير رمز PIN للموظف"}, status=403)
        if len(new_pin) < 4:
            return JsonResponse({"error": "رمز PIN يجب أن يتكون من 4 أرقام على الأقل"}, status=400)
        emp.set_pin(new_pin)

    # Password update (for dashboard login) - restricted to Owner and HQ HR Managers with hr_manage_credentials
    new_password = str(data.get("password") or data.get("new_password") or "").strip()
    if new_password:
        if not is_owner_or_super and not user_has_perm(request.user, "hr_manage_credentials"):
            return JsonResponse({"error": "غير مصرح لك بتعيين أو تغيير كلمة مرور حساب الموظف (مقتصر على إدارة المنشأة)"}, status=403)
        if len(new_password) < 6:
            return JsonResponse({"error": "كلمة المرور يجب أن تتكون من 6 أحرف على الأقل"}, status=400)
        if emp.user:
            emp.user.set_password(new_password)
            emp.user.save()

    # Ensure linked User exists safely
    if not emp.user and emp.employee_code:
        emp.user = get_or_create_employee_user(emp.tenant, emp.employee_code, emp.name, exclude_emp_id=emp.id)

    if emp.user and hasattr(emp.user, "profile"):
        emp.user.profile.tenant = emp.tenant
        emp.user.profile.branch = emp.branch
        emp.user.profile.role = emp.role
        emp.user.profile.job_role = emp.job_role
        emp.user.profile.save()

    emp.save()

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="employee_updated",
        target_model="Employee",
        target_id=emp.id,
        description=f"تحديث بيانات الموظف «{emp.name}» (الحالة: {emp.status}, المسمى: {emp.job_role.name if emp.job_role else emp.role})",
        ip_address=_get_client_ip(request),
    )

    return JsonResponse({"ok": True, "employeeCode": emp.employee_code, "hasPin": bool(emp.pin_code)})


@login_required
def api_delete_employee(request, emp_id):
    if request.method not in ["POST", "DELETE"]:
        return HttpResponseBadRequest("POST or DELETE required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (user_has_perm(request.user, "hr_deactivate_employee") or user_has_perm(request.user, "manage_employees")):
        return JsonResponse({"error": "غير مصرح لك بحذف أو تجميد الموظفين"}, status=403)

    emp = get_object_or_404(Employee, tenant=tenant, id=emp_id)

    # 1. Prevent self-deletion
    if emp.user and emp.user == request.user:
        return JsonResponse({"error": "لا يمكنك حذف أو تجميد حسابك الشخصي"}, status=400)

    # 2. Prevent subordinate from deleting/archiving restaurant owner or platform admin
    is_target_owner = emp.user and (emp.user.is_superuser or (hasattr(emp.user, "profile") and emp.user.profile.role in ["owner", "platform_admin"]))
    if is_target_owner and not is_owner_or_super:
        return JsonResponse({"error": "غير مصرح لك بحذف أو تجميد حساب مالك المنشأة"}, status=403)

    # Branch managers can only delete/archive employees in their branch
    if not is_owner_or_super and profile and profile.branch and emp.branch != profile.branch:
        return JsonResponse({"error": "غير مصرح لك بإدارة موظفي الفروع الأخرى"}, status=403)

    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        body = {}

    force_delete = bool(body.get("force", False)) and is_owner_or_super

    # Check if this employee has any linked orders or historical financial records
    has_driver_orders = Order.objects.filter(driver=emp).exists()
    has_cashier_orders = Order.objects.filter(tenant=tenant).filter(
        Q(cashier=emp.name) | Q(cashier=emp.employee_code)
    ).exists() if emp.employee_code else Order.objects.filter(tenant=tenant, cashier=emp.name).exists()

    has_history = has_driver_orders or has_cashier_orders

    with transaction.atomic():
        if has_history and not force_delete:
            # Soft Delete / Archive: Freeze account, deactivate user, detach permissions
            emp.status = "inactive"
            emp.save(update_fields=["status"])
            if emp.user:
                emp.user.is_active = False
                emp.user.groups.clear()
                emp.user.save(update_fields=["is_active"])
            log_audit_event(
                tenant=tenant,
                user=request.user,
                action="employee_archived",
                target_model="Employee",
                target_id=emp.id,
                description=f"أرشفة وتجميد الموظف «{emp.name}» كود {emp.employee_code}",
                ip_address=_get_client_ip(request),
            )
            return JsonResponse({
                "ok": True,
                "action": "archived",
                "message": f"نظراً لوجود فواتير وعمليات سابقة مرتبطة بالموظف «{emp.name}»، تم تجميد حسابه وسحب صلاحياته بنجاح لحماية السجلات المالية والمحاسبية."
            })
        else:
            # Hard delete
            emp_name = emp.name
            emp_id_val = emp.id
            user_obj = emp.user
            log_audit_event(
                tenant=tenant,
                user=request.user,
                action="employee_deleted",
                target_model="Employee",
                target_id=emp_id_val,
                description=f"حذف الموظف «{emp_name}» نهائياً",
                ip_address=_get_client_ip(request),
            )
            emp.delete()
            if user_obj:
                user_obj.delete()
            return JsonResponse({
                "ok": True,
                "action": "deleted",
                "message": f"تم حذف الموظف «{emp_name}» وحسابه نهائياً بنجاح."
            })


@login_required
def api_toggle_employee_status(request, emp_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (user_has_perm(request.user, "hr_deactivate_employee") or user_has_perm(request.user, "manage_employees")):
        return JsonResponse({"error": "غير مصرح لك بتعديل حالة الموظف"}, status=403)

    emp = get_object_or_404(Employee, tenant=tenant, id=emp_id)

    # 1. Prevent self-toggle
    if emp.user and emp.user == request.user:
        return JsonResponse({"error": "لا يمكنك تعديل حالة حسابك الشخصي"}, status=400)

    # 2. Prevent subordinate from toggling owner account status
    is_target_owner = emp.user and (emp.user.is_superuser or (hasattr(emp.user, "profile") and emp.user.profile.role in ["owner", "platform_admin"]))
    if is_target_owner and not is_owner_or_super:
        return JsonResponse({"error": "غير مصرح لك بتعديل حالة حساب مالك المنشأة"}, status=403)

    if not is_owner_or_super and profile and profile.branch and emp.branch != profile.branch:
        return JsonResponse({"error": "غير مصرح لك بإدارة موظفي الفروع الأخرى"}, status=403)

    # Toggle between active and inactive
    if emp.status != "active":
        if tenant and not tenant.can_add_employee():
            max_e = tenant.subscription_plan.max_employees if tenant.subscription_plan else 0
            return JsonResponse({"error": f"لا يمكن إعادة تنشيط الموظف لأنك بلغت الحد الأقصى للموظفين النشطين في باقتك الحالية ({max_e} موظف). يرجى ترقية الباقة أولاً."}, status=400)
        emp.status = "active"
    else:
        emp.status = "inactive"
    emp.save(update_fields=["status"])

    if emp.user:
        emp.user.is_active = (emp.status == "active")
        emp.user.save(update_fields=["is_active"])

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="employee_status_toggled",
        target_model="Employee",
        target_id=emp.id,
        description=f"تغيير حالة الموظف «{emp.name}» إلى {emp.status}",
        ip_address=_get_client_ip(request),
    )

    return JsonResponse({
        "ok": True,
        "status": emp.status,
        "new_status": emp.status,
        "status_display": emp.get_status_display(),
        "is_active": (emp.status == "active"),
        "message": f"تم تغيير حالة الموظف «{emp.name}» إلى ({emp.get_status_display()}) بنجاح."
    })


@login_required
def api_employee_detail(request, emp_id):
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (user_has_perm(request.user, "hr_view_employees") or user_has_perm(request.user, "manage_employees")):
        return JsonResponse({"error": "غير مصرح لك باستعراض تفاصيل الموظفين"}, status=403)

    tenant = get_active_tenant(request)
    emp = get_object_or_404(Employee.objects.select_related("user", "job_role", "branch"), tenant=tenant, id=emp_id)

    # Branch managers can only view details of employees in their own branch
    if not is_owner_or_super and profile and profile.branch and emp.branch != profile.branch:
        return JsonResponse({"error": "غير مصرح لك باستعراض موظفي الفروع الأخرى"}, status=403)

    perm_labels_map = dict(RESTAURANT_PERMISSIONS)
    permissions_detail = []
    effective_perms = set()

    if emp.user:
        for p in emp.user.get_all_permissions():
            codename = p.split(".")[-1]
            effective_perms.add(codename)
    if emp.job_role:
        effective_perms.update(emp.job_role.get_permissions_list())

    for k in sorted(effective_perms):
        permissions_detail.append({
            "key": k,
            "label": perm_labels_map.get(k, k),
        })

    delivered_orders_count = Order.objects.filter(driver=emp).count()

    can_view_salary = is_owner_or_super or user_has_perm(request.user, "hr_manage_salaries") or user_has_perm(request.user, "manage_employees")
    salary_display = str(emp.salary) if can_view_salary else "••••"

    data = {
        "ok": True,
        "employee": {
            "id": emp.id,
            "name": emp.name,
            "phone": emp.phone,
            "employee_code": emp.employee_code,
            "salary": salary_display,
            "can_view_salary": can_view_salary,
            "status": emp.status,
            "status_display": emp.get_status_display(),
            "hire_date": emp.hire_date.strftime("%Y-%m-%d") if emp.hire_date else "",
            "role_legacy": emp.role,
            "branch": {
                "id": emp.branch.id if emp.branch else None,
                "name": emp.branch.name if emp.branch else "الإدارة العامة (HQ)",
            },
            "job_role": {
                "id": emp.job_role.id if emp.job_role else None,
                "name": emp.job_role.name if emp.job_role else emp.get_role_display(),
                "scope": emp.job_role.scope if emp.job_role else "branch",
                "scope_display": emp.job_role.get_scope_display() if emp.job_role else "تشغيل فرع",
            },
            "user": {
                "id": emp.user.id if emp.user else None,
                "username": emp.user.username if emp.user else "",
                "is_active": emp.user.is_active if emp.user else False,
                "last_login": emp.user.last_login.strftime("%Y-%m-%d %H:%M") if emp.user and emp.user.last_login else "لم يسجل بعد",
            },
            "has_pin": bool(emp.pin_code),
            "delivered_orders_count": delivered_orders_count,
            "permissions_count": len(permissions_detail),
            "permissions": permissions_detail,
        }
    }
    return JsonResponse(data)


@login_required
def api_export_employees_csv(request):
    if not user_has_perm(request.user, "manage_employees") and not user_has_perm(request.user, "hr_view_employees"):
        return HttpResponseForbidden("غير مصرح لك بتصدير بيانات الموظفين")

    tenant = get_active_tenant(request)
    active_branch = get_active_branch(request)

    employees = Employee.objects.filter(tenant=tenant).select_related("branch", "job_role", "user").order_by("id")
    if active_branch:
        employees = employees.filter(branch=active_branch)

    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    filename = f"employees_{tenant.slug if tenant else 'list'}_{timezone.now().strftime('%Y%m%d')}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    # Write UTF-8 BOM so Excel opens Arabic properly
    response.write("\ufeff".encode("utf-8"))

    writer = csv.writer(response)
    writer.writerow([
        "كود الموظف",
        "اسم الموظف",
        "رقم الجوال",
        "المسمى الوظيفي",
        "نطاق العمل",
        "الفرع المعين",
        "الراتب الأساسي (ر.س)",
        "الحالة",
        "اسم مستخدم الدخول",
        "تاريخ التعيين"
    ])

    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    can_view_salary = is_owner_or_super or user_has_perm(request.user, "hr_manage_salaries") or user_has_perm(request.user, "manage_employees")

    for emp in employees:
        role_label = emp.job_role.name if emp.job_role else emp.get_role_display()
        scope_label = emp.job_role.get_scope_display() if emp.job_role else "تشغيل فرع"
        branch_name = emp.branch.name if emp.branch else "الإدارة العامة"
        username = emp.user.username if emp.user else "غير مربوط"
        hire_date_str = emp.hire_date.strftime("%Y-%m-%d") if emp.hire_date else ""
        salary_str = str(emp.salary) if can_view_salary else "••••"

        writer.writerow([
            emp.employee_code or str(emp.id),
            emp.name,
            emp.phone,
            role_label,
            scope_label,
            branch_name,
            salary_str,
            emp.get_status_display(),
            username,
            hire_date_str
        ])

    return response


# ==========================================
# 8. JOB ROLES & PERMISSIONS APIS
# ==========================================

@login_required
def api_job_roles(request):
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if request.method == "GET":
        if not is_owner_or_super and not (
            user_has_perm(request.user, "hr_view_employees") or
            user_has_perm(request.user, "manage_employees") or
            user_has_perm(request.user, "manage_roles") or
            user_has_perm(request.user, "system_manage_roles")
        ):
            return JsonResponse({"error": "غير مصرح لك باستعراض المسميات الوظيفية وهيكل الصلاحيات"}, status=403)

        if tenant and not JobRole.objects.filter(tenant=tenant).exists():
            ensure_tenant_preset_roles(tenant)
        roles = JobRole.objects.filter(tenant=tenant).annotate(employees_count=Count("employees")).order_by("ordering", "id")
        data = []
        for r in roles:
            perms_list = r.get_permissions_list()
            data.append({
                "id": r.id,
                "name": r.name,
                "scope": r.scope,
                "scope_display": r.get_scope_display(),
                "description": r.description,
                "is_system": r.is_system,
                "permissions": perms_list,
                "permissions_count": len(perms_list),
                "employees_count": r.employees_count,
            })
        return JsonResponse({"ok": True, "roles": data, "catalog": PERMISSIONS_CATALOG})

    elif request.method == "POST":
        if tenant and not tenant.has_feature("custom_roles") and not (request.user.is_superuser or (profile and profile.is_platform_admin)):
            return JsonResponse({"error": "إنشاء مسميات وظيفية مخصصة يتطلب باقة اشتراك تدعم ميزة الأدوار المخصصة (custom_roles)"}, status=403)

        if not is_owner_or_super and not user_has_perm(request.user, "manage_roles"):
            return JsonResponse({"error": "غير مصرح لك بإضافة مسميات وظيفية"}, status=403)

        try:
            body = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

        name = str(body.get("name", "")).strip()
        if not name:
            return JsonResponse({"error": "اسم المسمى الوظيفي مطلوب"}, status=400)

        if JobRole.objects.filter(tenant=tenant, name=name).exists():
            return JsonResponse({"error": f"المسمى الوظيفي «{name}» مسجل مسبقاً"}, status=400)

        scope = body.get("scope", "branch")
        if scope not in ["hq", "branch", "both"]:
            scope = "branch"

        description = str(body.get("description", "")).strip()
        permissions = body.get("permissions", [])
        if not isinstance(permissions, list):
            permissions = []

        role = JobRole.objects.create(
            tenant=tenant,
            name=name,
            scope=scope,
            description=description,
            is_system=False,
        )
        role.sync_with_django_group()
        role.set_permissions(permissions)
        perms_list = role.get_permissions_list()

        log_audit_event(
            tenant=tenant,
            user=request.user,
            action="role_created",
            target_model="JobRole",
            target_id=role.id,
            description=f"إنشاء مسمى وظيفي جديد «{role.name}» (النطاق: {role.scope})",
            ip_address=_get_client_ip(request),
        )

        return JsonResponse({
            "ok": True,
            "role": {
                "id": role.id,
                "name": role.name,
                "scope": role.scope,
                "scope_display": role.get_scope_display(),
                "description": role.description,
                "is_system": role.is_system,
                "permissions": perms_list,
                "permissions_count": len(perms_list),
                "employees_count": 0,
            }
        })

    return HttpResponseBadRequest("GET or POST required")


@login_required
def api_job_role_detail(request, role_id):
    tenant = get_active_tenant(request)
    role = get_object_or_404(JobRole, tenant=tenant, id=role_id)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not user_has_perm(request.user, "manage_roles"):
        return JsonResponse({"error": "غير مصرح لك بتعديل أو حذف المسميات الوظيفية"}, status=403)

    if role.is_system and not is_owner_or_super:
        return JsonResponse({"error": "فقط مالك المنشأة أو مدير النظام يمكنه تعديل الأدوار الأساسية للنظام أو صلاحياتها"}, status=403)

    if request.method in ["POST", "PATCH", "PUT"]:
        try:
            body = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

        action = body.get("action")
        if action == "delete" or request.method == "DELETE":
            if role.is_system:
                return JsonResponse({"error": "لا يمكن حذف هذا المسمى الأساسي للنظام"}, status=400)
            if role.employees.exists():
                return JsonResponse({
                    "error": f"لا يمكن حذف المسمى «{role.name}» لوجود {role.employees.count()} موظف مرتبطين به. يرجى نقلهم لمسمى آخر أولاً."
                }, status=400)
            log_audit_event(
                tenant=tenant,
                user=request.user,
                action="role_deleted",
                target_model="JobRole",
                target_id=role.id,
                description=f"حذف المسمى الوظيفي «{role.name}»",
                ip_address=_get_client_ip(request),
            )
            role.delete()
            return JsonResponse({"ok": True, "message": "تم حذف المسمى الوظيفي بنجاح"})

        # Update action
        name = str(body.get("name", "")).strip()
        if name and name != role.name:
            if JobRole.objects.filter(tenant=tenant, name=name).exclude(id=role.id).exists():
                return JsonResponse({"error": f"اسم المسمى «{name}» مستخدم مسبقاً"}, status=400)
            role.name = name

        if "scope" in body and body["scope"] in ["hq", "branch", "both"]:
            role.scope = body["scope"]

        if "description" in body:
            role.description = str(body["description"]).strip()

        role.save()
        grp = role.sync_with_django_group()

        if "permissions" in body and isinstance(body["permissions"], list):
            role.set_permissions(body["permissions"])

        # Update linked user profiles and groups
        for emp in role.employees.select_related("user"):
            if emp.user and hasattr(emp.user, "profile"):
                emp.user.profile.job_role = role
                emp.user.profile.save()
            if emp.user and grp:
                emp.user.groups.set([grp])
                for cache_field in ["_perm_cache", "_group_perm_cache", "_user_perm_cache"]:
                    if hasattr(emp.user, cache_field):
                        delattr(emp.user, cache_field)

        perms_list = role.get_permissions_list()
        log_audit_event(
            tenant=tenant,
            user=request.user,
            action="role_updated",
            target_model="JobRole",
            target_id=role.id,
            description=f"تحديث المسمى الوظيفي «{role.name}» (النطاق: {role.scope}) والصلاحيات: {perms_list}",
            ip_address=_get_client_ip(request),
        )
        return JsonResponse({
            "ok": True,
            "role": {
                "id": role.id,
                "name": role.name,
                "scope": role.scope,
                "scope_display": role.get_scope_display(),
                "description": role.description,
                "is_system": role.is_system,
                "permissions": perms_list,
                "permissions_count": len(perms_list),
                "employees_count": role.employees.count(),
            }
        })

    elif request.method == "DELETE":
        if role.is_system:
            return JsonResponse({"error": "لا يمكن حذف هذا المسمى الأساسي للنظام"}, status=400)
        if role.employees.exists():
            return JsonResponse({
                "error": f"لا يمكن حذف المسمى «{role.name}» لوجود {role.employees.count()} موظف مرتبطين به. يرجى نقلهم لمسمى آخر أولاً."
            }, status=400)
        role.delete()
        return JsonResponse({"ok": True, "message": "تم حذف المسمى الوظيفي بنجاح"})

    return HttpResponseBadRequest("Invalid method")


# ==========================================
# 9. SAAS SUBSCRIPTION PLANS & TENANT LIMITS
# ==========================================




# ==========================================
# 10. SAAS LANDING & OWNER SUBSCRIPTION VIEWS
# ==========================================

def landing_view(request):
    """Public Landing Page. If authenticated, redirect to appropriate workspace."""
    if request.user.is_authenticated:
        return redirect(get_post_login_redirect(request.user))

    plans = SubscriptionPlan.objects.filter(is_active=True).order_by("ordering", "price_monthly")
    total_tenants = Tenant.objects.filter(is_active=True).count()
    total_branches = Branch.objects.filter(status="active").count()
    total_orders = Order.objects.count()

    catalog_data = []
    for f in SAAS_FEATURES_CATALOG:
        key = f.get("key") or f.get("code")
        label = f.get("label") or f.get("name")
        catalog_data.append({
            "key": key,
            "code": key,
            "label": label,
            "name": label,
            "desc": f.get("desc", ""),
        })

    context = {
        "plans": plans,
        "catalog": catalog_data,
        "stats": {
            "restaurants": max(total_tenants, 18),
            "branches": max(total_branches, 45),
            "orders": max(total_orders, 15000),
            "uptime": "99.9%",
        }
    }
    return render(request, "landing.html", context)


@login_required
def owner_subscription_view(request):
    """Owner dashboard for viewing current subscription, limits usage, and requesting upgrades."""
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin)) or user_has_perm(request.user, "system_manage_billing")
    if not is_owner:
        return HttpResponseForbidden("صفحة إدارة الاشتراك مخصصة لمالك المنشأة أو المسؤول المخول بالفوترة")

    tenant = get_active_tenant(request)
    if not tenant:
        return HttpResponseBadRequest("لم يتم العثور على منشأة نشطة مرتبطة بحسابك")

    branches_count = Branch.objects.filter(tenant=tenant, status="active").count()
    employees_count = Employee.objects.filter(tenant=tenant, status__in=["active", "vacation"]).count()
    orders_count = Order.objects.filter(tenant=tenant).count()
    
    plan = tenant.subscription_plan
    max_branches = plan.max_branches if plan else 1
    max_employees = plan.max_employees if plan else 5

    branches_pct = min(100, int((branches_count / max_branches) * 100)) if max_branches > 0 else 100
    employees_pct = min(100, int((employees_count / max_employees) * 100)) if max_employees > 0 else 100

    available_plans = SubscriptionPlan.objects.filter(is_active=True).order_by("ordering", "price_monthly")
    upgrade_requests = UpgradeRequest.objects.filter(tenant=tenant).select_related("requested_plan", "requested_by").order_by("-created_at")

    feature_icons = {
        "pos": "💳",
        "kds": "🍳",
        "menu_management": "📋",
        "delivery_management": "🗺️",
        "call_center": "🎧",
        "inventory": "📦",
        "custom_roles": "🛡️",
        "financial_analytics": "📊",
    }

    # Catalog mapped with enabled flags for current plan
    current_features = plan.features if plan and plan.features else []
    features_with_status = []
    for feat in SAAS_FEATURES_CATALOG:
        f_key = feat.get("key") or feat.get("code")
        f_label = feat.get("label") or feat.get("name")
        f_desc = feat.get("desc", "")
        f_icon = feature_icons.get(f_key, "✨")
        is_active_feat = (f_key in current_features) or (request.user.is_superuser)
        features_with_status.append({
            "key": f_key,
            "code": f_key,
            "name": f_label,
            "label": f_label,
            "desc": f_desc,
            "icon": f_icon,
            "is_enabled": is_active_feat,
        })

    has_pending_request = upgrade_requests.filter(status="pending").exists()

    api_keys = TenantApiKey.objects.filter(tenant=tenant).select_related("assigned_branch").order_by("-created_at")
    branches = Branch.objects.filter(tenant=tenant, status="active")

    context = {
        "tenant": tenant,
        "plan": plan,
        "branches_count": branches_count,
        "employees_count": employees_count,
        "orders_count": orders_count,
        "max_branches": max_branches,
        "max_employees": max_employees,
        "branches_pct": branches_pct,
        "employees_pct": employees_pct,
        "days_left": tenant.days_until_expiry(),
        "is_expired": tenant.is_subscription_expired(),
        "features_with_status": features_with_status,
        "available_plans": available_plans,
        "upgrade_requests": upgrade_requests,
        "has_pending_request": has_pending_request,
        "api_keys": api_keys,
        "branches": branches,
        "manage_py_path": str(settings.BASE_DIR / "manage.py"),
        "python_path": sys.executable,
    }
    return render(request, "owner_subscription.html", context)



@login_required
def api_request_upgrade(request):
    """API for tenant owner to submit an upgrade request."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin)) or user_has_perm(request.user, "system_manage_billing")
    if not is_owner:
        return JsonResponse({"error": "طلب الترقية مقتصر على مالك المنشأة أو المسؤول المخول بالفوترة فقط"}, status=403)

    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"error": "لا توجد منشأة نشطة مرتبطة بحسابك"}, status=400)

    try:
        body = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    plan_id = body.get("plan_id")
    billing_cycle = body.get("billing_cycle", "monthly")
    notes = str(body.get("notes", "")).strip()

    if not plan_id:
        return JsonResponse({"error": "يرجى تحديد الباقة المطلوبة"}, status=400)

    plan = get_object_or_404(SubscriptionPlan, id=plan_id, is_active=True)

    if billing_cycle not in ["monthly", "yearly"]:
        billing_cycle = "monthly"

    # Create upgrade request
    upgrade_req = UpgradeRequest.objects.create(
        tenant=tenant,
        requested_plan=plan,
        billing_cycle=billing_cycle,
        requested_by=request.user,
        notes=notes,
        status="pending",
    )

    return JsonResponse({
        "ok": True,
        "message": f"تم إرسال طلب الترقية إلى باقة «{plan.name}» بنجاح! سيتم مراجعته وتفعيله من قبل إدارة المنصة.",
        "request_id": upgrade_req.id,
        "status": upgrade_req.status,
    })





@login_required
def api_create_api_key(request):
    """API for tenant owner to create a new FastMCP / AI access key."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner:
        return JsonResponse({"error": "إنشاء مفاتيح الذكاء الاصطناعي مقتصر على مالك المنشأة فقط"}, status=403)

    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"error": "لا توجد منشأة نشطة مرتبطة بحسابك"}, status=400)

    try:
        body = json.loads(request.body.decode("utf-8"))
    except Exception:
        body = {}

    name = str(body.get("name", "")).strip() or "بوت كول سنتر الذكاء الاصطناعي"
    branch_id = body.get("branch_id")
    assigned_branch = None
    if branch_id:
        try:
            assigned_branch = Branch.objects.filter(tenant=tenant, id=int(branch_id), status="active").first()
        except (ValueError, TypeError):
            pass

    api_key_obj = TenantApiKey.objects.create(
        tenant=tenant,
        name=name,
        assigned_branch=assigned_branch,
        is_active=True,
    )

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="api_key_created",
        target_model="TenantApiKey",
        target_id=api_key_obj.id,
        description=f"إنشاء مفتاح ذكاء اصطناعي جديد: «{api_key_obj.name}» (الفرع: {assigned_branch.name if assigned_branch else 'كافة الفروع'})",
        ip_address=_get_client_ip(request),
    )

    return JsonResponse({
        "ok": True,
        "message": f"تم إنشاء مفتاح الذكاء الاصطناعي «{api_key_obj.name}» بنجاح!",
        "key": {
            "id": api_key_obj.id,
            "name": api_key_obj.name,
            "access_key": api_key_obj.key,
            "assigned_branch_name": assigned_branch.name if assigned_branch else "كافة الفروع",
            "created_at": api_key_obj.created_at.strftime("%Y-%m-%d %H:%M"),
        }
    })


@login_required
def api_toggle_api_key(request, key_id):
    """API to enable/disable an API key."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner:
        return JsonResponse({"error": "غير مصرح"}, status=403)

    tenant = get_active_tenant(request)
    api_key_obj = get_object_or_404(TenantApiKey, id=key_id, tenant=tenant)
    api_key_obj.is_active = not api_key_obj.is_active
    api_key_obj.save(update_fields=["is_active"])

    status_str = "تفعيل" if api_key_obj.is_active else "تعطيل"
    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="api_key_toggled",
        target_model="TenantApiKey",
        target_id=api_key_obj.id,
        description=f"{status_str} مفتاح الذكاء الاصطناعي «{api_key_obj.name}»",
        ip_address=_get_client_ip(request),
    )

    return JsonResponse({
        "ok": True,
        "is_active": api_key_obj.is_active,
        "message": f"تم {status_str} المفتاح بنجاح."
    })


@login_required
def api_delete_api_key(request, key_id):
    """API to delete an API key."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner:
        return JsonResponse({"error": "غير مصرح"}, status=403)

    tenant = get_active_tenant(request)
    api_key_obj = get_object_or_404(TenantApiKey, id=key_id, tenant=tenant)
    name = api_key_obj.name
    api_key_id_val = api_key_obj.id
    api_key_obj.delete()

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="api_key_deleted",
        target_model="TenantApiKey",
        target_id=api_key_id_val,
        description=f"حذف مفتاح الذكاء الاصطناعي «{name}» نهائياً",
        ip_address=_get_client_ip(request),
    )

    return JsonResponse({
        "ok": True,
        "message": f"تم حذف المفتاح «{name}» نهائياً."
    })


# ==============================================================================
# AI Call Center Management (Owner Dashboard & Partner SaaS Integration)
# ==============================================================================

def _validate_callcenter_page_access(request):
    """
    Validate permissions and active tenant for AI Call Center pages.
    Returns (tenant, None) on success or (None, HttpResponse) on error.
    """
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin)) or user_has_perm(request.user, "call_center_manage_ai")
    if not is_owner:
        return None, HttpResponseForbidden("صفحة إدارة المساعد الصوتي مخصصة لمالك المنشأة أو المسؤول المخول بالذكاء الاصطناعي")

    tenant = get_active_tenant(request)
    if not tenant:
        return None, HttpResponseBadRequest("لم يتم العثور على منشأة نشطة مرتبطة بحسابك")

    if not tenant.has_feature("call_center"):
        return None, HttpResponseForbidden("ميزة المساعد الصوتي والكول سنتر غير مفعلة في باقة اشتراك هذا المطعم. يرجى ترقية الباقة لتفعيلها.")

    return tenant, None


def _get_callcenter_client_info(tenant):
    from core import partner_service as ps
    reg_info = ps.ensure_tenant_registered(tenant, password=tenant.voice_password or "Diyafa@2026!")
    client_id = reg_info.get("client_id") or ps.get_client_id_for_tenant(tenant)
    return client_id, reg_info


def _norm_phone(p):
    if not p:
        return ""
    import re
    digits = re.sub(r"\D", "", str(p))
    return digits[-9:] if len(digits) >= 9 else digits


def _fetch_enriched_calls(tenant, client_id):
    from core import partner_service as ps
    calls_resp = ps.get_calls(client_id)
    calls_data = calls_resp.get("calls") or []

    # Fallback to demo calls (user 49) if current tenant has no call sessions yet
    if not calls_data:
        demo_resp = ps.get_calls(49)
        calls_data = demo_resp.get("calls") or []

    tenant_orders = list(Order.objects.filter(tenant=tenant).select_related("branch").order_by("-created_at")[:50])

    for c in calls_data:
        # Format duration properly
        sec = int(c.get("duration_seconds") or 0)
        mins = sec // 60
        rem_secs = sec % 60
        c["duration_formatted"] = f"{mins:02d}:{rem_secs:02d}"
        c["duration"] = c["duration_formatted"]
        c["created_at"] = c.get("started_at") or ""
        c["transcript"] = c.get("transcript_text") or ""

        summary = c.get("summary") or ""
        turns = str(c.get("dialogue_turns") or "")
        c_phone = _norm_phone(c.get("caller_phone"))
        matched_ord = None

        for o in tenant_orders:
            if o.order_number in summary or o.order_number in turns:
                matched_ord = o
                break

        if not matched_ord and c_phone:
            matching_orders = [o for o in tenant_orders if o.customer_phone and _norm_phone(o.customer_phone) == c_phone]
            if matching_orders:
                matched_ord = matching_orders[0]

        c["linked_order"] = matched_ord
        c["has_order"] = bool(matched_ord)

        if matched_ord and matched_ord.customer_name:
            c["customer_name"] = matched_ord.customer_name
        else:
            raw_phone = c.get("caller_phone") or ""
            cust = Customer.objects.filter(tenant=tenant).filter(Q(phone=raw_phone) | Q(phone__endswith=c_phone) if c_phone else Q(phone=raw_phone)).first()
            c["customer_name"] = cust.name if cust else "عميل اتصال هاتفي"

        cid = c.get("call_id")
        if c.get("recording_url") and cid:
            c["recording_url"] = f"/api/ai-callcenter/calls/{cid}/recording/"

    total_calls_count = len(calls_data)
    orders_converted_count = sum(1 for c in calls_data if c.get("linked_order"))
    inquiries_count = max(0, total_calls_count - orders_converted_count)
    return calls_data, total_calls_count, orders_converted_count, inquiries_count


@login_required
def ai_callcenter_management_view(request):
    """
    Dispatcher and backward compatibility entrypoint.
    Redirects old ?tab=... query parameters to their dedicated subpage routes,
    or redirects to /ai-callcenter/overview/ by default.
    """
    tab = request.GET.get("tab", "").lower()
    tab_to_url = {
        "overview": "ai_callcenter_overview",
        "persona": "ai_callcenter_persona",
        "hours": "ai_callcenter_hours",
        "knowledge": "ai_callcenter_knowledge",
        "employees": "ai_callcenter_queues",
        "queues": "ai_callcenter_queues",
        "calls": "ai_callcenter_calls",
        "mcp": "ai_callcenter_capabilities",
        "capabilities": "ai_callcenter_capabilities",
        "omnichannel": "ai_callcenter_omnichannel",
    }
    target_route = tab_to_url.get(tab, "ai_callcenter_overview")

    q_params = request.GET.copy()
    q_params.pop("tab", None)
    url = reverse(target_route)
    if q_params:
        url = f"{url}?{q_params.urlencode()}"
    return redirect(url)


@login_required
def ai_callcenter_overview_view(request):
    """
    Dedicated Subpage 1: High-Level Overview, KPIs, Usage Quotas & Activity.
    """
    tenant, err_resp = _validate_callcenter_page_access(request)
    if err_resp:
        return err_resp

    from core import partner_service as ps
    client_id, _ = _get_callcenter_client_info(tenant)

    calls_data, total_calls_count, orders_converted_count, inquiries_count = _fetch_enriched_calls(tenant, client_id)

    tenant_orders = list(Order.objects.filter(tenant=tenant).select_related("branch").order_by("-created_at")[:50])
    call_orders = [o for o in tenant_orders if o.channel == "call_center"][:15]
    total_ai_orders = Order.objects.filter(tenant=tenant, channel="call_center").count()
    total_ai_revenue = Order.objects.filter(tenant=tenant, channel="call_center").aggregate(Sum("total"))["total__sum"] or Decimal("0.00")

    telephony_resp = ps.get_telephony_numbers(client_id)
    raw_nums = telephony_resp if isinstance(telephony_resp, list) else (telephony_resp.get("numbers") or [])
    primary_did = ""
    if raw_nums and len(raw_nums) > 0:
        first_num = raw_nums[0]
        if isinstance(first_num, dict):
            primary_did = first_num.get("phone_number") or first_num.get("number") or first_num.get("did") or ""
        elif isinstance(first_num, str):
            primary_did = first_num
    if not primary_did:
        primary_did = "لا يوجد خط هاتف مخصص بعد"

    usage_info = ps.get_client_usage(client_id).get("client") or {}
    plan_caps = ps.get_plan_voice_caps(tenant)

    context = {
        "tenant": tenant,
        "calls": calls_data[:10],
        "total_calls_count": total_calls_count,
        "orders_converted_count": orders_converted_count,
        "inquiries_count": inquiries_count,
        "call_orders": call_orders,
        "total_ai_orders": total_ai_orders,
        "total_ai_revenue": total_ai_revenue,
        "did_number": primary_did,
        "client_usage": usage_info,
        "plan_caps": plan_caps,
    }
    return render(request, "ai_callcenter/overview.html", context)


@login_required
def ai_callcenter_persona_view(request):
    """
    Dedicated Subpage 2: AI Persona, Dialects, Voice Profiles & Personality Tuning.
    """
    tenant, err_resp = _validate_callcenter_page_access(request)
    if err_resp:
        return err_resp

    from core import partner_service as ps
    client_id, _ = _get_callcenter_client_info(tenant)

    prof_resp = ps.get_profile(client_id)
    profile_data = prof_resp.get("profile") or prof_resp.get("active_profile") or {}
    profiles_data = prof_resp.get("profiles") or ([profile_data] if profile_data else [])

    req_profile_id = request.GET.get("profile_id")
    if req_profile_id and profiles_data:
        try:
            req_id_int = int(req_profile_id)
            matched = next((p for p in profiles_data if p.get("id") == req_id_int), None)
            if matched:
                profile_data = matched
        except Exception:
            pass

    # Clean old placeholder restaurant names in welcome message
    rest_name = tenant.name if (tenant and tenant.name) else "المطعم"
    if profile_data and "مطاعم كورا" in str(profile_data.get("welcome_message", "")):
        profile_data["welcome_message"] = str(profile_data["welcome_message"]).replace("مطاعم كورا", rest_name)

    # Fetch full studio metadata from partner API
    studio_data = ps.get_studio_metadata(client_id)
    if not isinstance(studio_data, dict) or studio_data.get("status") != "success":
        studio_data = {}

    context = {
        "tenant": tenant,
        "profile": profile_data,
        "profiles": profiles_data,
        "studio": studio_data,
        "studio_json": json.dumps(studio_data),
    }
    return render(request, "ai_callcenter/persona.html", context)


@login_required
def ai_callcenter_hours_view(request):
    """
    Dedicated Subpage 3: Business Hours & Off-Hours Smart Audio Apologies.
    """
    tenant, err_resp = _validate_callcenter_page_access(request)
    if err_resp:
        return err_resp

    from core import partner_service as ps
    client_id, _ = _get_callcenter_client_info(tenant)

    hours_data = ps.get_business_hours(client_id).get("schedule") or {}
    prof_resp = ps.get_profile(client_id)
    profile_data = prof_resp.get("profile") or prof_resp.get("active_profile") or {}

    context = {
        "tenant": tenant,
        "hours": hours_data,
        "profile": profile_data,
    }
    return render(request, "ai_callcenter/hours.html", context)


@login_required
def ai_callcenter_knowledge_view(request):
    """
    Dedicated Subpage 4: Restaurant Knowledge Base, FAQs & RAG Documents.
    """
    tenant, err_resp = _validate_callcenter_page_access(request)
    if err_resp:
        return err_resp

    from core import partner_service as ps
    from core.models import KnowledgeDocument
    client_id, _ = _get_callcenter_client_info(tenant)

    docs_data = ps.get_documents(client_id).get("documents") or []

    # Enrich docs_data with local file attachments
    local_docs = {
        ld.partner_doc_id: ld
        for ld in KnowledgeDocument.objects.filter(tenant=tenant)
        if ld.partner_doc_id
    }
    for doc in docs_data:
        doc_id = doc.get("id")
        if doc_id in local_docs:
            ld = local_docs[doc_id]
            if ld.file:
                doc["file_download_url"] = ld.file.url
                doc["is_local_file"] = True
            doc["source_type"] = ld.source_type
        else:
            doc["source_type"] = "faq" if not doc.get("file_type") or doc.get("file_type") == "txt" else "file"

    context = {
        "tenant": tenant,
        "documents": docs_data,
    }
    return render(request, "ai_callcenter/knowledge.html", context)


@login_required
def ai_callcenter_queues_view(request):
    """
    Dedicated Subpage 5: Human Transfer Queues, Routing Strategies & Staff Directory.
    """
    tenant, err_resp = _validate_callcenter_page_access(request)
    if err_resp:
        return err_resp

    from core import partner_service as ps
    client_id, _ = _get_callcenter_client_info(tenant)

    employees_data = ps.get_employees(client_id).get("employees") or []
    queues_data = ps.get_queues(client_id).get("queues") or []

    # Auto-seed default queue if tenant has 0 queues
    if not queues_data:
        try:
            default_q_desc = "طابور خدمة العملاء والطلبات العام: يتم تحويل المتصل إليه عند طلب التحدث مع ممثل خدمة العملاء أو لتأكيد وإلغاء الطلبات."
            seed_resp = ps.add_or_update_queue(
                client_id=client_id,
                name="طابور خدمة العملاء والطلبات",
                code="200",
                description=default_q_desc,
                strategy="round_robin",
                ring_timeout_seconds=20,
                total_timeout_seconds=60,
                fallback_action="ai_assistant"
            )
            if seed_resp.get("status") == "success" and seed_resp.get("queue"):
                new_q = seed_resp.get("queue")
                if employees_data:
                    ps.add_queue_member(client_id, new_q["id"], employees_data[0]["id"], order=1)
                queues_data = ps.get_queues(client_id).get("queues") or [new_q]
        except Exception as q_seed_err:
            logger.warning(f"Failed to auto-seed default queue for client {client_id}: {q_seed_err}")

    context = {
        "tenant": tenant,
        "employees": employees_data,
        "queues": queues_data,
        "primary_queue": queues_data[0] if queues_data else None,
    }
    return render(request, "ai_callcenter/queues.html", context)


@login_required
def ai_callcenter_calls_view(request):
    """
    Dedicated Subpage 6: Call History, Voice Audio Recordings & AI Transcripts.
    """
    tenant, err_resp = _validate_callcenter_page_access(request)
    if err_resp:
        return err_resp

    client_id, _ = _get_callcenter_client_info(tenant)
    calls_data, total_calls_count, orders_converted_count, inquiries_count = _fetch_enriched_calls(tenant, client_id)

    context = {
        "tenant": tenant,
        "calls": calls_data,
        "total_calls_count": total_calls_count,
        "orders_converted_count": orders_converted_count,
        "inquiries_count": inquiries_count,
    }
    return render(request, "ai_callcenter/calls.html", context)


@login_required
def ai_callcenter_capabilities_view(request):
    """
    Dedicated Subpage 7: AI Capabilities, FastMCP Integrated Tools & Redis Live Context.
    """
    tenant, err_resp = _validate_callcenter_page_access(request)
    if err_resp:
        return err_resp

    from core import partner_service as ps
    client_id, _ = _get_callcenter_client_info(tenant)

    mcp_resp = ps.get_client_mcp_servers(client_id)
    mcp_servers = mcp_resp.get("servers") or []
    primary_mcp = mcp_servers[0] if mcp_servers else None

    from core.models import TenantApiKey
    api_key_obj = TenantApiKey.objects.filter(tenant=tenant, is_active=True).first()
    if not api_key_obj:
        api_key_obj = TenantApiKey.objects.create(tenant=tenant, name="مفتاح FastMCP الموحد للمساعد الصوتي")
    access_key = api_key_obj.key if api_key_obj else ""

    base_host = request.get_host().split(":")[0]
    effective_domain = "uggu.space" if base_host in ("169.58.32.179", "127.0.0.1", "localhost") else base_host
    mcp_sse_url = f"https://{effective_domain}/sse?access_key={access_key}"
    mcp_streamable_url = f"https://{effective_domain}/mcp?access_key={access_key}"

    live_context_resp = ps.get_client_live_context(client_id)
    live_context_info = live_context_resp.get("context", {}) if live_context_resp.get("status") == "success" else {}
    live_context_data = live_context_info.get("data", {})
    live_context_cached = live_context_resp.get("cached_in_redis", False)

    context = {
        "tenant": tenant,
        "mcp_servers": mcp_servers,
        "primary_mcp": primary_mcp,
        "mcp_tools": primary_mcp.get("cached_tools", []) if primary_mcp else [],
        "access_key": access_key,
        "mcp_sse_url": mcp_sse_url,
        "mcp_streamable_url": mcp_streamable_url,
        "live_context": live_context_info,
        "live_context_data": live_context_data,
        "live_context_cached": live_context_cached,
        "live_context_raw": live_context_resp,
    }
    return render(request, "ai_callcenter/capabilities.html", context)


@login_required
@never_cache
def ai_callcenter_omnichannel_view(request):
    """
    Dedicated Subpage 8: Omnichannel Channels, Outbound AI Dialer & WhatsApp Web.
    """
    tenant, err_resp = _validate_callcenter_page_access(request)
    if err_resp:
        return err_resp

    from core import partner_service as ps
    client_id, _ = _get_callcenter_client_info(tenant)

    telephony_resp = ps.get_telephony_numbers(client_id)
    raw_nums = telephony_resp.get("numbers", []) if isinstance(telephony_resp, dict) else (telephony_resp if isinstance(telephony_resp, list) else [])
    primary_did = ""
    if raw_nums and len(raw_nums) > 0:
        first_num = raw_nums[0]
        if isinstance(first_num, dict):
            primary_did = first_num.get("phone_number") or first_num.get("number") or first_num.get("did") or ""
        elif isinstance(first_num, str):
            primary_did = first_num

    has_did = bool(primary_did and primary_did != "لا يوجد خط هاتف مخصص بعد")

    context = {
        "tenant": tenant,
        "did_number": primary_did,
        "has_did": has_did,
        "did_numbers": raw_nums,
    }
    return render(request, "ai_callcenter/omnichannel.html", context)



def _check_callcenter_admin(request):
    tenant = get_active_tenant(request)
    if tenant and not tenant.has_feature("call_center"):
        return JsonResponse({"status": "error", "message": "ميزة المساعد الصوتي والكول سنتر غير مفعلة في باقة اشتراك هذا المطعم. يرجى ترقية الباقة لتفعيلها."}, status=403)
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner and not user_has_perm(request.user, "call_center_manage_ai"):
        return JsonResponse({"status": "error", "message": "غير مصرح لك بإدارة إعدادات وكيل الذكاء الاصطناعي"}, status=403)
    return None


def _authenticate_callcenter_request(request):
    """
    Validates that the request is made by an authorized call center admin
    (either an authenticated user with call_center_manage_ai or owner,
     or an external system bearing a valid TenantApiKey).
    """
    if request.user and request.user.is_authenticated:
        return _check_callcenter_admin(request)

    # Check for access_key in headers, query, or body safely
    api_key_str = request.headers.get("X-API-Key") or request.GET.get("access_key")
    if not api_key_str:
        if getattr(request, "content_type", "") == "application/json":
            try:
                body = json.loads(request.body.decode("utf-8"))
                api_key_str = body.get("access_key")
            except Exception:
                pass
        else:
            try:
                api_key_str = request.POST.get("access_key")
            except Exception:
                pass

    if api_key_str:
        from core.models import TenantApiKey
        key_obj = TenantApiKey.objects.filter(key=api_key_str, is_active=True).first()
        if key_obj:
            request.tenant = key_obj.tenant
            return None

    return JsonResponse({"status": "error", "message": "غير مصرح. يرجى تسجيل الدخول بحساب مخول أو إرسال مفتاح access_key صالح."}, status=401)


@login_required
def api_ai_callcenter_create_profile(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err

    tenant = get_active_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"status": "error", "message": "بيانات JSON غير صالحة"}, status=400)

    # Set smart default for off_topic_response based on dialect if omitted
    dialect = data.get("dialect", "egyptian")
    if dialect == "modern_standard":
        dialect = "fusha"
        data["dialect"] = "fusha"

    rest_name = tenant.name.strip() if (tenant and getattr(tenant, "name", None)) else "المطعم"
    if "welcome_message" in data and "مطاعم كورا" in str(data["welcome_message"]):
        data["welcome_message"] = str(data["welcome_message"]).replace("مطاعم كورا", rest_name)

    if not data.get("off_topic_response"):
        defaults_by_dialect = {
            "saudi": f"أعتذر منك يا غالي، أنا في خدمتك لطلبات ومنيو {rest_name} فقط، تحب تطلب شيء من عروضنا اليوم؟",
            "emirati": f"السموحة منك طال عمرك، أنا أساعدك في طلبات ومنيو {rest_name} فقط، حاب تطلب شي الحين؟",
            "kuwaiti": f"السموحة يا غالي، أنا مخصص لطلبات ومنيو {rest_name} فقط، تبي تطلب شي من المنيو؟",
            "fusha": f"أعتذر منك يا سيدي، أنا هنا لمساعدتك في قائمة طعام وطلبات {rest_name} فقط، هل ترغب بطلب أي وجبة؟",
            "modern_standard": f"أعتذر منك يا سيدي، أنا هنا لمساعدتك في قائمة طعام وطلبات {rest_name} فقط، هل ترغب بطلب أي وجبة؟",
            "levantine": f"بعتذر منك يا غالي، أنا هون لمساعدتك بطلبات وقائمة {rest_name} بس، بتحب تطلب شي هلأ؟",
            "jordanian_palestinian": f"بعتذر منك يا غالي، أنا هون لمساعدتك بطلبات ومنيو {rest_name} بس، بتحب تطلب إشي هسا؟",
            "moroccan": f"كنعتذر منك أخاي، أنا هنا باش نعاونك في طلبات ومينو {rest_name} فقط، بغيتي تطلب شي حاجة دابا؟",
            "algerian": f"نعتذر منك خويا، أنا هنا باش نعاونك في طلبات ومينو {rest_name} برك، تحب تطلب شي حاجة درك؟",
            "tunisian": f"سامحني يا غالي، أنا لهنا باش نعاونك في منيو وطلبات {rest_name} كهو، تحب تعدي كوموند توا؟",
            "iraqi": f"أعتذر منك عيوني، أني بخدمتك لطلبات ومنيو {rest_name} وبس، تحب تطلب شي هسة؟",
            "sudanese": f"العفو منك يا غالي، أنا هنا لمساعدتك في طلبات ومنيو {rest_name} بس، تحب تطلب حاجة هسي؟",
            "yemeni": f"العفو منك يا طيب، أنا في خدمتك لطلبات ومنيو {rest_name} فقط، تشتي تطلب شي ذلحين؟",
            "egyptian": f"بعتذر جداً يا فندم، أنا هنا لمساعدتك في منيو وطلبات {rest_name} فقط، تؤمر بأي صنف النهارده؟",
            "english_us": f"I apologize, but I can only assist with {rest_name}'s menu and orders. Would you like to place an order today?",
            "english_uk": f"I do apologize, but I am only able to help with {rest_name}'s menu and orders. May I take your order?",
            "english": f"I apologize, I can only assist with {rest_name}'s menu and orders. Would you like to place an order today?",
            "french_fr": f"Je vous prie de m'excuser, mais je peux uniquement vous aider avec le menu et les commandes de {rest_name}. Souhaitez-vous commander ?",
        }
        data["off_topic_response"] = defaults_by_dialect.get(dialect, defaults_by_dialect["egyptian"])

    resp = ps.create_profile(client_id, data)
    return JsonResponse(resp)


@login_required
def api_ai_callcenter_update_profile(request, profile_id=None):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"status": "error", "message": "بيانات JSON غير صالحة"}, status=400)

    target_profile_id = profile_id or data.get("profile_id")
    if not target_profile_id:
        prof_resp = ps.get_profile(client_id)
        prof = prof_resp.get("profile") or prof_resp.get("active_profile") or {}
        target_profile_id = prof.get("id") or 66

    dialect = data.get("dialect", "egyptian")
    if dialect == "modern_standard":
        dialect = "fusha"
        data["dialect"] = "fusha"

    rest_name = tenant.name.strip() if (tenant and getattr(tenant, "name", None)) else "المطعم"
    if "welcome_message" in data and "مطاعم كورا" in str(data["welcome_message"]):
        data["welcome_message"] = str(data["welcome_message"]).replace("مطاعم كورا", rest_name)

    if "off_topic_response" in data and not str(data["off_topic_response"]).strip():
        defaults_by_dialect = {
            "saudi": f"أعتذر منك يا غالي، أنا في خدمتك لطلبات ومنيو {rest_name} فقط، تحب تطلب شيء من عروضنا اليوم؟",
            "emirati": f"السموحة منك طال عمرك، أنا أساعدك في طلبات ومنيو {rest_name} فقط، حاب تطلب شي الحين؟",
            "kuwaiti": f"السموحة يا غالي، أنا مخصص لطلبات ومنيو {rest_name} فقط، تبي تطلب شي من المنيو؟",
            "fusha": f"أعتذر منك يا سيدي، أنا هنا لمساعدتك في قائمة طعام وطلبات {rest_name} فقط، هل ترغب بطلب أي وجبة؟",
            "modern_standard": f"أعتذر منك يا سيدي، أنا هنا لمساعدتك في قائمة طعام وطلبات {rest_name} فقط، هل ترغب بطلب أي وجبة؟",
            "levantine": f"بعتذر منك يا غالي، أنا هون لمساعدتك بطلبات وقائمة {rest_name} بس، بتحب تطلب شي هلأ؟",
            "jordanian_palestinian": f"بعتذر منك يا غالي، أنا هون لمساعدتك بطلبات ومنيو {rest_name} بس، بتحب تطلب إشي هسا؟",
            "moroccan": f"كنعتذر منك أخاي، أنا هنا باش نعاونك في طلبات ومينو {rest_name} فقط، بغيتي تطلب شي حاجة دابا؟",
            "algerian": f"نعتذر منك خويا، أنا هنا باش نعاونك في طلبات ومينو {rest_name} برك، تحب تطلب شي حاجة درك؟",
            "tunisian": f"سامحني يا غالي، أنا لهنا باش نعاونك في منيو وطلبات {rest_name} كهو، تحب تعدي كوموند توا؟",
            "iraqi": f"أعتذر منك عيوني، أني بخدمتك لطلبات ومنيو {rest_name} وبس، تحب تطلب شي هسة؟",
            "sudanese": f"العفو منك يا غالي، أنا هنا لمساعدتك في طلبات ومنيو {rest_name} بس، تحب تطلب حاجة هسي؟",
            "yemeni": f"العفو منك يا طيب، أنا في خدمتك لطلبات ومنيو {rest_name} فقط، تشتي تطلب شي ذلحين؟",
            "egyptian": f"بعتذر جداً يا فندم، أنا هنا لمساعدتك في منيو وطلبات {rest_name} فقط، تؤمر بأي صنف النهارده؟",
            "english_us": f"I apologize, but I can only assist with {rest_name}'s menu and orders. Would you like to place an order today?",
            "english_uk": f"I do apologize, but I am only able to help with {rest_name}'s menu and orders. May I take your order?",
            "english": f"I apologize, I can only assist with {rest_name}'s menu and orders. Would you like to place an order today?",
            "french_fr": f"Je vous prie de m'excuser, mais je peux uniquement vous aider avec le menu et les commandes de {rest_name}. Souhaitez-vous commander ?",
        }
        data["off_topic_response"] = defaults_by_dialect.get(dialect, defaults_by_dialect["egyptian"])

    resp = ps.update_profile(client_id, int(target_profile_id), data)
    return JsonResponse(resp)


@login_required
def api_ai_callcenter_activate_profile(request, profile_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    resp = ps.activate_profile(client_id, profile_id)
    return JsonResponse(resp)


@login_required
def api_ai_callcenter_delete_profile(request, profile_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    resp = ps.delete_profile(client_id, profile_id)
    return JsonResponse(resp)


@login_required
def api_ai_callcenter_update_hours(request):
    if request.method not in ("POST", "PUT"):
        return HttpResponseBadRequest("POST or PUT required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"status": "error", "message": "Invalid JSON body"}, status=400)

    resp = ps.update_business_hours(client_id, data)
    return JsonResponse(resp)


@login_required
def api_ai_callcenter_add_doc(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    from core import partner_service as ps
    from core.models import KnowledgeDocument
    client_id = ps.get_client_id_for_tenant(tenant)

    # Check if this is a multipart file upload
    file_obj = request.FILES.get("file")
    if file_obj:
        allowed_exts = [".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".json"]
        filename = file_obj.name
        ext = os.path.splitext(filename)[1].lower()
        if ext not in allowed_exts:
            return JsonResponse({
                "status": "error",
                "message": f"صيغة الملف غير مدعومة ({ext}). الصيغ المسموحة هي: PDF, DOCX, TXT, CSV, MD, JSON"
            }, status=400)

        max_bytes = 25 * 1024 * 1024  # 25 MB
        if file_obj.size > max_bytes:
            return JsonResponse({
                "status": "error",
                "message": "حجم الملف يتجاوز الحد الأقصى المسموح به (25 ميجابايت)"
            }, status=400)

        title = (request.POST.get("title") or os.path.splitext(filename)[0]).strip()

        # Save to local KnowledgeDocument model & storage
        doc_record = KnowledgeDocument.objects.create(
            tenant=tenant,
            title=title,
            file=file_obj,
            file_type=ext.lstrip("."),
            file_size=file_obj.size,
            source_type="file"
        )

        # Build public absolute URL for the voice partner platform to ingest
        base_host = request.get_host().split(":")[0]
        effective_domain = "uggu.space" if base_host in ("169.58.32.179", "127.0.0.1", "localhost", "testserver") else base_host
        public_file_url = f"https://{effective_domain}{doc_record.file.url}"

        # Dispatch to partner platform
        resp = ps.add_document(client_id, title=title, file_url=public_file_url)

        if resp.get("status") == "success":
            partner_doc_id = resp.get("document", {}).get("id")
            if partner_doc_id:
                doc_record.partner_doc_id = partner_doc_id
                doc_record.save(update_fields=["partner_doc_id"])
            return JsonResponse({
                "status": "success",
                "message": resp.get("message") or f"تم رفع المستند '{title}' وفهرسته بنجاح في قاعدة المعرفة.",
                "document": resp.get("document")
            })
        else:
            if doc_record.file:
                try:
                    doc_record.file.delete(save=False)
                except Exception:
                    pass
            doc_record.delete()
            return JsonResponse({
                "status": "error",
                "message": resp.get("message") or "تعذر فهرسة المستند في خدمة المكالمات"
            }, status=400)

    # Otherwise, handle JSON / text payload
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        data = {}

    title = (request.POST.get("title") or data.get("title") or "").strip()
    content = (request.POST.get("content") or data.get("content") or "").strip()
    file_url = (request.POST.get("file_url") or data.get("file_url") or "").strip()

    if not title:
        return JsonResponse({"status": "error", "message": "عنوان المستند أو السؤال مطلوب"}, status=400)

    if not content and not file_url:
        return JsonResponse({"status": "error", "message": "يرجى كتابة نص المعلومة (FAQ) أو رفع ملف"}, status=400)

    resp = ps.add_document(client_id, title=title, content=content, file_url=file_url)

    if resp.get("status") == "success":
        partner_doc_id = resp.get("document", {}).get("id")
        source_type = "url" if file_url else "faq"
        KnowledgeDocument.objects.create(
            tenant=tenant,
            partner_doc_id=partner_doc_id,
            title=title,
            file_type="url" if file_url else "txt",
            source_type=source_type
        )

    return JsonResponse(resp)


@login_required
def api_ai_callcenter_delete_doc(request, doc_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    from core import partner_service as ps
    from core.models import KnowledgeDocument
    client_id = ps.get_client_id_for_tenant(tenant)

    resp = ps.delete_document(client_id, doc_id)

    # Delete local record and file
    ld = KnowledgeDocument.objects.filter(tenant=tenant, partner_doc_id=doc_id).first()
    if ld:
        if ld.file:
            try:
                ld.file.delete(save=False)
            except Exception:
                pass
        ld.delete()

    return JsonResponse(resp)


@login_required
def api_ai_callcenter_add_employee(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"status": "error", "message": "Invalid JSON body"}, status=400)

    name = (data.get("display_name") or data.get("name") or "").strip()
    ext = (data.get("extension") or data.get("ext") or "").strip()
    dept = (data.get("department") or data.get("dept") or "خدمة العملاء").strip()
    status = (data.get("status") or "ready").strip()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not name or not ext:
        return JsonResponse({"status": "error", "message": "اسم الموظف والتحويلة مطلوبان"}, status=400)

    resp = ps.add_employee(client_id, display_name=name, extension=ext, department=dept, status=status, username=username, password=password)
    status_code = 200
    if resp.get("status") == "error":
        code_val = resp.get("code")
        status_code = code_val if isinstance(code_val, int) and 400 <= code_val <= 599 else 400
        if not resp.get("message"):
            resp["message"] = "تعذر إضافة الموظف. يرجى التأكد من عدم تكرار رقم التحويلة."
    return JsonResponse(resp, status=status_code)


@login_required
def api_ai_callcenter_delete_employee(request, emp_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    resp = ps.delete_employee(client_id, emp_id)
    return JsonResponse(resp)


@login_required
def api_ai_callcenter_get_employee_credentials(request, emp_id):
    if request.method != "GET":
        return HttpResponseBadRequest("GET required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    resp = ps.get_employee(client_id, emp_id)
    return JsonResponse(resp)


@login_required
def api_ai_callcenter_reset_employee_password(request, emp_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    custom_password = None
    if request.body:
        try:
            data = json.loads(request.body.decode("utf-8"))
            custom_password = data.get("password")
        except Exception:
            pass

    resp = ps.reset_employee_password(client_id, emp_id, password=custom_password)
    return JsonResponse(resp)


@login_required
def api_ai_callcenter_update_employee_status(request, emp_id):
    """API to quickly update employee presence status (ready, busy, offline)."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err

    tenant = get_active_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"status": "error", "message": "Invalid JSON body"}, status=400)

    new_status = (data.get("status") or "ready").strip()
    if new_status not in ("ready", "busy", "offline"):
        return JsonResponse({"status": "error", "message": "حالة غير صالحة"}, status=400)

    resp = ps.update_employee(client_id, emp_id, status=new_status)
    return JsonResponse(resp)


@login_required
def api_ai_callcenter_save_queue(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"status": "error", "message": "Invalid JSON body"}, status=400)

    queue_id = data.get("id") or data.get("queue_id")
    name = (data.get("name") or "طابور خدمة العملاء الرئيسي").strip()
    code = str(data.get("code") or "200").strip()
    description = (data.get("description") or "").strip()
    strategy = (data.get("strategy") or "round_robin").strip()
    if strategy not in ("round_robin", "ring_all"):
        strategy = "round_robin"
    ring_timeout = int(data.get("ring_timeout_seconds", 20))
    total_timeout = int(data.get("total_timeout_seconds", 60))
    fallback = (data.get("fallback_action") or "ai_assistant").strip()

    if queue_id:
        resp = ps.update_queue(
            client_id,
            queue_id=int(queue_id),
            name=name,
            code=code,
            description=description,
            strategy=strategy,
            ring_timeout_seconds=ring_timeout,
            total_timeout_seconds=total_timeout,
            fallback_action=fallback
        )
    else:
        resp = ps.add_or_update_queue(
            client_id,
            name=name,
            code=code,
            description=description,
            strategy=strategy,
            ring_timeout_seconds=ring_timeout,
            total_timeout_seconds=total_timeout,
            fallback_action=fallback
        )
    return JsonResponse(resp)


@login_required
def api_ai_callcenter_delete_queue(request, queue_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    resp = ps.delete_queue(client_id, queue_id)
    return JsonResponse(resp)


@login_required
def api_ai_callcenter_add_queue_member(request, queue_id):
    """API to add an employee member to a call queue with order priority."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err

    tenant = get_active_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"status": "error", "message": "Invalid JSON body"}, status=400)

    employee_id = data.get("employee_id")
    order = int(data.get("order") or data.get("penalty") or 1)

    if not employee_id:
        return JsonResponse({"status": "error", "message": "يرجى تحديد الموظف المراد إضافته للطابور"}, status=400)

    resp = ps.add_queue_member(client_id, queue_id, employee_id=int(employee_id), order=order)
    return JsonResponse(resp)


@login_required
def api_ai_callcenter_remove_queue_member(request, queue_id):
    """API to remove an employee member from a call queue."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err

    tenant = get_active_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"status": "error", "message": "Invalid JSON body"}, status=400)

    employee_id = data.get("employee_id")
    if not employee_id:
        return JsonResponse({"status": "error", "message": "يرجى تحديد الموظف المراد إزالته من الطابور"}, status=400)

    resp = ps.remove_queue_member(client_id, queue_id, employee_id=int(employee_id))
    return JsonResponse(resp)


@csrf_exempt
def api_ai_callcenter_sync_mcp(request):
    """Triggers live tool synchronization between FastMCP and Partner Voice Platform."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _authenticate_callcenter_request(request)
    if err:
        return err

    tenant = getattr(request, "tenant", None) or get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "لم يتم العثور على منشأة صالحة أو مصرح بها."}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    servers_resp = ps.get_client_mcp_servers(client_id)
    servers = servers_resp.get("servers") or []
    if not servers:
        from core.models import TenantApiKey
        api_key_obj = TenantApiKey.objects.filter(tenant=tenant, is_active=True).first()
        if not api_key_obj:
            api_key_obj = TenantApiKey.objects.create(tenant=tenant, name="مفتاح FastMCP الموحد للمساعد الصوتي")
        access_key = api_key_obj.key if api_key_obj else ""
        base_host = request.get_host().split(":")[0]
        effective_domain = "uggu.space" if base_host in ("169.58.32.179", "127.0.0.1", "localhost") else base_host
        mcp_sse_url = f"https://{effective_domain}/sse?access_key={access_key}"
        create_resp = ps.create_client_mcp_server(client_id, server_url=mcp_sse_url, sync_now=True)
        return JsonResponse(create_resp)

    mcp_id = servers[0]["id"]
    sync_resp = ps.sync_client_mcp_tools(client_id, mcp_id)
    return JsonResponse(sync_resp)


@csrf_exempt
def api_ai_callcenter_update_mcp_url(request):
    """Updates the live MCP server URL in Partner Voice Platform."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _authenticate_callcenter_request(request)
    if err:
        return err

    tenant = getattr(request, "tenant", None) or get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "لم يتم العثور على منشأة صالحة أو مصرح بها."}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"status": "error", "message": "Invalid JSON body"}, status=400)

    server_url = data.get("server_url", "").strip()
    if not server_url:
        return JsonResponse({"status": "error", "message": "رابط الخادم مطلوب"}, status=400)

    servers_resp = ps.get_client_mcp_servers(client_id)
    servers = servers_resp.get("servers") or []
    if not servers:
        create_resp = ps.create_client_mcp_server(client_id, server_url=server_url, sync_now=True)
        return JsonResponse(create_resp)

    mcp_id = servers[0]["id"]
    update_resp = ps.update_client_mcp_server(client_id, mcp_id, {"server_url": server_url})
    # Also trigger sync right after update
    ps.sync_client_mcp_tools(client_id, mcp_id)
    return JsonResponse(update_resp)


@csrf_exempt
def api_ai_callcenter_test_mcp_tool(request):
    """Executes a live tool call directly to test it from the dashboard or external systems."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _authenticate_callcenter_request(request)
    if err:
        return err

    tenant = getattr(request, "tenant", None) or get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "لم يتم العثور على منشأة صالحة أو مصرح بها."}, status=400)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"status": "error", "message": "Invalid JSON body"}, status=400)

    tool_name = data.get("tool_name", "").strip()
    params = data.get("params", {})

    from core.models import TenantApiKey
    api_key_obj = TenantApiKey.objects.filter(tenant=tenant, is_active=True).first()
    access_key = api_key_obj.key if api_key_obj else None

    from core import mcp_server as ms
    tool_map = {
        "get_branches": lambda: ms.get_branches(access_key=access_key),
        "get_menu": lambda: ms.get_menu(
            branch_id=int(params["branch_id"]) if params.get("branch_id") else None,
            category=params.get("category"),
            access_key=access_key
        ),
        "lookup_customer": lambda: ms.lookup_customer(phone=str(params.get("phone", "0501234567")), access_key=access_key),
        "check_delivery_coverage": lambda: ms.check_delivery_coverage(
            branch_id=int(params.get("branch_id", 1)),
            area_name=str(params.get("area_name", "الرياض")),
            access_key=access_key
        ),
        "preview_order": lambda: ms.preview_order(
            items=params.get("items", []),
            customer_address=str(params.get("customer_address", "")),
            delivery_area_name=params.get("delivery_area_name"),
            order_type=str(params.get("order_type", "delivery")),
            branch_id=int(params["branch_id"]) if params.get("branch_id") else None,
            access_key=access_key
        ),
        "create_callcenter_order": lambda: ms.create_callcenter_order(
            branch_id=int(params["branch_id"]) if params.get("branch_id") else None,
            customer_phone=str(params.get("customer_phone", "")),
            customer_name=str(params.get("customer_name", "")),
            customer_address=str(params.get("customer_address", "")),
            items=params.get("items", []),
            order_type=str(params.get("order_type", "delivery")),
            delivery_area_id=int(params["delivery_area_id"]) if params.get("delivery_area_id") else None,
            delivery_area_name=params.get("delivery_area_name"),
            notes=str(params.get("notes", "")),
            access_key=access_key
        ),
        "track_order": lambda: ms.track_order(
            order_number=str(params.get("order_number", "")).strip() or None,
            customer_phone=str(params.get("customer_phone", "")).strip() or None,
            access_key=access_key
        ),
        "cancel_order": lambda: ms.cancel_order(
            order_number=str(params.get("order_number", "")).strip() or None,
            customer_phone=str(params.get("customer_phone", "")).strip() or None,
            reason=str(params.get("reason", "طلب العميل عبر الهاتف")),
            access_key=access_key
        ),
        "list_recent_orders": lambda: ms.list_recent_orders(limit=int(params.get("limit", 5)), access_key=access_key),
    }

    if tool_name not in tool_map:
        return JsonResponse({"status": "error", "message": f"الأداة {tool_name} غير مدعومة للاختبار المباشر."}, status=400)

    try:
        res = tool_map[tool_name]()
        return JsonResponse({"status": "success", "tool": tool_name, "result": res})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def api_ai_callcenter_sync_live_context(request):
    """Trigger immediate live context compilation and Redis sync for client."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err

    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "لم يتم العثور على منشأة نشطة."}, status=400)
    from core import partner_service as ps
    try:
        res = ps.sync_tenant_live_context(tenant)
        return JsonResponse(res)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def api_ai_callcenter_get_live_context(request):
    """Retrieve current cached live context from Partner PBX."""
    err = _check_callcenter_admin(request)
    if err:
        return err

    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "لم يتم العثور على منشأة نشطة."}, status=400)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    try:
        res = ps.get_client_live_context(client_id)
        return JsonResponse(res)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def api_ai_callcenter_dial_customer(request):
    """Trigger an autonomous outbound AI call to a customer."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err

    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "لم يتم العثور على منشأة نشطة."}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return JsonResponse({"status": "error", "message": "بيانات JSON غير صالحة"}, status=400)

    phone = data.get("phone_number") or data.get("phone")
    order_id = data.get("order_id")
    customer_name = data.get("customer_name", "")
    call_goal = data.get("call_goal", "")

    if order_id and not phone:
        order = Order.objects.filter(tenant=tenant, id=order_id).first()
        if order:
            phone = order.customer_phone
            customer_name = customer_name or order.customer_name or ""
            call_goal = call_goal or f"تأكيد الطلب رقم {order.order_number} بقيمة {order.total} ريال مع العميل"

    if not phone:
        return JsonResponse({"status": "error", "message": "رقم هاتف العميل مطلوب لإجراء المكالمة"}, status=400)

    try:
        res = ps.dial_outbound_call(
            client_id=client_id,
            phone_number=phone,
            call_goal=call_goal or f"التواصل مع العميل بخصوص خدمات مطعم {tenant.name}",
            customer_name=customer_name
        )
        return JsonResponse(res)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def api_ai_callcenter_call_recording_proxy(request, call_id):
    """Secure white-labeled streaming proxy for call audio recordings."""
    tenant = get_active_tenant(request)
    if not tenant:
        return HttpResponseForbidden("لم يتم العثور على منشأة نشطة")
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    calls_resp = ps.get_calls(client_id)
    calls = calls_resp.get("calls") or []
    target_call = next((c for c in calls if c.get("call_id") == call_id), None)
    if not target_call:
        demo_resp = ps.get_calls(49)
        calls_demo = demo_resp.get("calls") or []
        target_call = next((c for c in calls_demo if c.get("call_id") == call_id), None)

    if not target_call or not target_call.get("recording_url"):
        return HttpResponseNotFound("التسجيل غير متاح")

    rec_url = target_call["recording_url"]
    try:
        import urllib.request
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(rec_url, headers={"User-Agent": "Motaem-Voice-Proxy/1.0"})
        url_fp = urllib.request.urlopen(req, context=ctx, timeout=15)

        async def _iter_chunks():
            try:
                while True:
                    chunk = await asyncio.to_thread(url_fp.read, 8192)
                    if not chunk:
                        break
                    yield chunk
            finally:
                await asyncio.to_thread(url_fp.close)

        content_type = url_fp.headers.get_content_type() if hasattr(url_fp.headers, "get_content_type") else "audio/mpeg"
        response = StreamingHttpResponse(
            _iter_chunks(),
            content_type=content_type or "audio/mpeg"
        )
        response["Accept-Ranges"] = "bytes"
        return response
    except Exception as e:
        return HttpResponse(f"Error loading recording: {e}", status=500)


@login_required
@never_cache
def api_ai_callcenter_whatsapp_status(request):
    """Get WhatsApp connection status for this tenant's AI assistant."""
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    res = ps.get_whatsapp_status(client_id)
    return JsonResponse(res)


@login_required
def api_ai_callcenter_whatsapp_connect(request):
    """Fetch QR code to link tenant's WhatsApp."""
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    res = ps.get_whatsapp_qr(client_id)
    if not isinstance(res, dict):
        return JsonResponse({"status": "error", "message": "استجابة غير صالحة من خادم الواتساب"}, status=502)

    base64_val = res.get("base64") or res.get("qr") or ""
    if not base64_val and isinstance(res.get("qrcode"), dict):
        base64_val = res["qrcode"].get("base64") or ""

    if base64_val:
        res["qr"] = base64_val
        res["base64"] = base64_val
        res["status"] = "success"
        res["ok"] = True

    return JsonResponse(res)


@login_required
def api_ai_callcenter_whatsapp_disconnect(request):
    """Disconnect tenant's WhatsApp session."""
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    res = ps.disconnect_whatsapp(client_id)
    return JsonResponse(res)


@login_required
def api_ai_callcenter_whatsapp_send(request):
    """Send WhatsApp message or order receipt to customer."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return JsonResponse({"status": "error", "message": "بيانات JSON غير صالحة"}, status=400)

    phone = data.get("phone_number") or data.get("phone")
    message = data.get("message") or ""
    order_id = data.get("order_id")

    if order_id and not message:
        order = Order.objects.filter(tenant=tenant, id=order_id).first()
        if order:
            phone = phone or order.customer_phone
            items_str = ", ".join(f"{it.name} x{it.qty}" for it in order.items.all())
            message = f"مرحباً بك من مطعم {tenant.name}!\nتم استلام طلبك رقم {order.order_number}:\n{items_str}\nالإجمالي: {order.total} ريال.\nشكراً لاختيارك لنا!"

    if not phone or not message:
        return JsonResponse({"status": "error", "message": "رقم الهاتف والرسالة مطلوبان"}, status=400)

    res = ps.send_whatsapp_message(client_id, phone, message)
    return JsonResponse(res)


@login_required
@never_cache
def api_ai_callcenter_whatsapp_conversations(request):
    """Fetch omnichannel WhatsApp conversations for tenant."""
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    q = request.GET.get("q", "").strip()
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = min(100, max(1, int(request.GET.get("page_size", 30))))
    except (ValueError, TypeError):
        page_size = 30

    res = ps.get_whatsapp_conversations(client_id, query=q, page=page, page_size=page_size)
    return JsonResponse(res)


@login_required
def api_ai_callcenter_whatsapp_conversation_messages(request, phone):
    """Fetch conversation messages history for specific customer phone."""
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    try:
        limit = min(200, max(1, int(request.GET.get("limit", 50))))
    except (ValueError, TypeError):
        limit = 50

    res = ps.get_whatsapp_conversation_messages(client_id, phone=phone, limit=limit)
    if res.get("status") == "success" and "messages" in res:
        for m in res["messages"]:
            if m.get("has_media") and not m.get("media_expired") and m.get("id"):
                m["media_url"] = f"/api/ai-callcenter/whatsapp/messages/{m['id']}/media/"
            elif m.get("media_expired"):
                m["media_url"] = ""
    return JsonResponse(res)


@login_required
def api_ai_callcenter_whatsapp_message_media(request, message_id):
    """
    Proxy media stream from partner telephony API with HTTP Range support for audio/video scrubbing.
    """
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return HttpResponseForbidden("منشأة غير موجودة")

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    range_header = request.headers.get("Range") or request.META.get("HTTP_RANGE")
    try:
        try:
            url_fp = ps.stream_whatsapp_message_media(client_id, message_id, range_header=range_header)
        except Exception as e_initial:
            if client_id != 69 and getattr(e_initial, 'code', None) == 404:
                url_fp = ps.stream_whatsapp_message_media(69, message_id, range_header=range_header)
            else:
                raise e_initial

        async def _iter_chunks():
            try:
                while True:
                    chunk = await asyncio.to_thread(url_fp.read, 32768)
                    if not chunk:
                        break
                    yield chunk
            finally:
                await asyncio.to_thread(url_fp.close)

        content_type = url_fp.headers.get_content_type() if hasattr(url_fp.headers, "get_content_type") else (url_fp.headers.get("Content-Type") or "application/octet-stream")
        status_code = getattr(url_fp, "status", 200)

        response = StreamingHttpResponse(
            _iter_chunks(),
            status=status_code,
            content_type=content_type
        )
        for h in ["Content-Length", "Content-Range", "Accept-Ranges", "Cache-Control"]:
            val = url_fp.headers.get(h)
            if val:
                response[h] = val
        if "Accept-Ranges" not in response:
            response["Accept-Ranges"] = "bytes"
        return response
    except Exception as e:
        status_code = getattr(e, "code", 404)
        logger.warning(f"Error streaming WhatsApp media {message_id}: {e}")
        return HttpResponse(f"Error loading media: {e}", status=status_code)


@login_required
def api_ai_callcenter_whatsapp_conversation_reply(request, phone):
    """Send human agent/cashier reply to customer on WhatsApp."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return JsonResponse({"status": "error", "message": "بيانات JSON غير صالحة"}, status=400)

    message = str(data.get("message") or "").strip()
    if not message:
        return JsonResponse({"status": "error", "message": "نص الرسالة مطلوب"}, status=400)

    res = ps.reply_whatsapp_conversation(client_id, phone=phone, message=message)
    return JsonResponse(res)


@login_required
def api_ai_callcenter_whatsapp_conversation_toggle_ai(request, phone):
    """Toggle AI auto-reply for customer conversation."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    data = {}
    if request.body:
        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            pass

    ai_active = data.get("ai_active") if "ai_active" in data else None
    res = ps.toggle_whatsapp_conversation_ai(client_id, phone=phone, enabled=ai_active)
    return JsonResponse(res)


@login_required
def api_ai_callcenter_whatsapp_sync(request):
    """Sync all genuine WhatsApp chats and messages directly from phone/evolution_db."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    data = {}
    if request.body:
        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            pass

    clean_old = bool(data.get("clean_old", False))
    try:
        max_messages = int(data.get("max_messages", 40))
    except (ValueError, TypeError):
        max_messages = 40

    res = ps.sync_whatsapp_chats(client_id, clean_old=clean_old, max_messages=max_messages)
    return JsonResponse(res)


@login_required
def api_ai_callcenter_telephony_info(request):
    """Fetch assigned direct inward dialing numbers and PBX trunks."""
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    nums_resp = ps.get_telephony_numbers(client_id)
    trunks = ps.get_pbx_trunks(client_id)
    raw_nums = nums_resp.get("numbers", []) if isinstance(nums_resp, dict) else (nums_resp if isinstance(nums_resp, list) else [])
    return JsonResponse({"status": "success", "numbers": raw_nums, "raw_telephony": nums_resp, "trunks": trunks})


@login_required
def api_ai_callcenter_usage(request):
    """Fetch live consumption and quotas for the tenant from Partner API."""
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    usage = ps.get_client_usage(client_id)
    plan_caps = ps.get_plan_voice_caps(tenant)
    client_data = usage.get("client") or {}

    total_mins = client_data.get("total_minutes") or 0
    cap_mins = client_data.get("minute_cap") or plan_caps.get("minute_cap") or 0
    remaining_mins = max(0, cap_mins - total_mins)

    return JsonResponse({
        "status": "success",
        "client_id": client_id,
        "usage": client_data,
        "plan_caps": plan_caps,
        "total_minutes": total_mins,
        "minute_cap": cap_mins,
        "remaining_minutes": remaining_mins,
        "spending_cap": client_data.get("spending_cap") or plan_caps.get("spending_cap"),
        "total_spent": client_data.get("total_spent") or 0.0,
        "is_active": client_data.get("is_active", True),
    })


@login_required
def api_ai_callcenter_sync_caps(request):
    """Synchronize / reset tenant call caps with the Voice AI partner platform."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    try:
        res = ps.sync_tenant_voice_caps(tenant, reset_to_plan=True)
        return JsonResponse(res)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


def set_language_view(request, lang_code):
    """
    Switch active interface language (ar/en), save to session and cookie,
    and redirect back to the previous page or next parameter.
    """
    from django.utils import translation
    from django.http import HttpResponseRedirect
    from django.conf import settings
    
    if lang_code not in ["ar", "en"]:
        lang_code = "ar"

    translation.activate(lang_code)
    
    next_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or "/"
    if not next_url.startswith("/"):
        next_url = "/"

    response = HttpResponseRedirect(next_url)
    request.session["django_language"] = lang_code
    request.session["_language"] = lang_code
    
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        lang_code,
        max_age=365 * 24 * 60 * 60,
        samesite="Lax"
    )
    return response


@login_required
def api_audit_logs(request):
    """API endpoint to query sensitive system audit logs for tenant owners/administrators."""
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (
        user_has_perm(request.user, "system_view_audit_logs") or
        user_has_perm(request.user, "system_manage_roles") or
        user_has_perm(request.user, "manage_roles")
    ):
        return JsonResponse({"error": "غير مصرح لك باستعراض سجل التدقيق الأمني"}, status=403)

    logs = AuditLog.objects.filter(tenant=tenant).select_related("user")[:100]
    data = []
    for l in logs:
        user_display = "النظام"
        if l.user:
            user_display = l.user.get_full_name() or l.user.username
        data.append({
            "id": l.id,
            "action": l.action,
            "user": user_display,
            "targetModel": l.target_model,
            "targetId": l.target_id,
            "description": l.description,
            "ipAddress": l.ip_address,
            "createdAt": l.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        })
    return JsonResponse({"ok": True, "logs": data})


# ==========================================
# 11. DIGITAL MENU & SELF-ORDERING (QR MENU)
# ==========================================

def digital_menu_view(request, slug=None, branch_id=None):
    """
    Public digital menu view for customers.
    Accessed via /m/<slug>/ or /m/<slug>/branch/<branch_id>/ or custom domain.
    """
    tenant = None
    if slug:
        tenant = get_object_or_404(Tenant, slug=slug, is_active=True)
    elif getattr(request, "custom_domain_tenant", None):
        tenant = request.custom_domain_tenant
    else:
        return HttpResponseNotFound("لم يتم العثور على قائمة طعام المطعم")

    # Determine active language for digital menu
    active_lang = None
    if hasattr(request, "LANGUAGE_CODE") and request.LANGUAGE_CODE:
        active_lang = request.LANGUAGE_CODE
    elif hasattr(request, "session") and request.session.get("django_language"):
        active_lang = request.session.get("django_language")
    elif request.COOKIES.get("django_language"):
        active_lang = request.COOKIES.get("django_language")
    else:
        active_lang = translation.get_language() or "ar"

    if "-" in active_lang:
        active_lang = active_lang.split("-")[0]
    if active_lang not in ["ar", "en"]:
        active_lang = "ar"

    branches = list(Branch.objects.filter(tenant=tenant, status="active").order_by("id"))
    for b in branches:
        b.display_name = b.get_display_name(active_lang)

    if not branches:
        return render(request, "qr_menu.html", {
            "tenant": tenant,
            "branches": [],
            "selected_branch": None,
            "no_branches": True,
            "categories": [],
            "categorized_items": {},
            "CURRENT_LANG": active_lang,
            "DIR": "rtl" if active_lang == "ar" else "ltr",
            "IS_RTL": active_lang == "ar",
        })

    # Determine selected branch
    selected_branch = None
    if branch_id:
        selected_branch = next((b for b in branches if b.id == branch_id), None)
    if not selected_branch:
        req_bid = request.GET.get("branch")
        if req_bid and str(req_bid).isdigit():
            selected_branch = next((b for b in branches if b.id == int(req_bid)), None)
    if not selected_branch:
        selected_branch = branches[0]

    selected_branch.display_name = selected_branch.get_display_name(active_lang)

    # Disabled items in this branch
    disabled_ids = set(
        BranchMenuAvailability.objects.filter(
            branch=selected_branch, is_available=False
        ).values_list("menu_item_id", flat=True)
    )

    # Dynamic Categories
    cat_objs = list(MenuCategory.objects.filter(tenant=tenant, is_active=True).order_by("ordering", "id"))
    categories_data = []
    cat_id_to_display = {}
    for c in cat_objs:
        disp_name = c.get_display_name(active_lang)
        cat_id_to_display[c.id] = disp_name
        categories_data.append({
            "id": c.id,
            "name": disp_name,
            "raw_name": c.name,
            "name_en": c.name_en,
            "image_url": c.image.url if c.image else "",
        })

    # Categories and items
    raw_items = MenuItem.objects.filter(tenant=tenant, is_active=True).prefetch_related("variants").order_by("category", "name")
    categories_set = [c["name"] for c in categories_data]
    categorized_items = {}

    for item in raw_items:
        if item.category_rel and item.category_rel.id in cat_id_to_display:
            cat = cat_id_to_display[item.category_rel.id]
        else:
            cat = item.category or ("General Dishes" if active_lang == "en" else "أطباق عامة")

        if cat not in categorized_items:
            categorized_items[cat] = []
            if cat not in categories_set:
                categories_set.append(cat)
                categories_data.append({
                    "id": None,
                    "name": cat,
                    "raw_name": item.category or cat,
                    "name_en": "",
                    "image_url": "",
                })

        is_avail = item.available and (item.id not in disabled_ids)
        item_variants = []
        for v in item.variants.all():
            v_eff_price = v.get_price_for_branch(selected_branch)
            item_variants.append({
                "id": v.id,
                "name": v.get_display_name(active_lang),
                "raw_name": v.name,
                "name_en": v.name_en,
                "price": float(v_eff_price),
                "is_default": v.is_default,
            })

        eff_price = item.get_price_for_branch(selected_branch)
        eff_min_price = item.get_min_price_for_branch(selected_branch)

        categorized_items[cat].append({
            "id": item.id,
            "name": item.get_display_name(active_lang),
            "raw_name": item.name,
            "name_en": item.name_en,
            "description": item.get_display_description(active_lang),
            "description_en": item.description_en,
            "price": float(eff_price),
            "min_price": float(eff_min_price),
            "has_variants": item.has_variants and len(item_variants) > 0,
            "variants": item_variants,
            "emoji": item.emoji or "🍽️",
            "image_url": item.image.url if item.image else "",
            "is_available": is_avail,
            "category": cat,
        })

    # Prepare sections list matching category_objs
    sections = []
    for c in categories_data:
        c_items = categorized_items.get(c["name"], [])
        if c_items:
            sections.append({
                "id": c["id"],
                "name": c["name"],
                "image_url": c["image_url"],
                "items": c_items,
            })

    # Delivery areas for selected branch
    areas = []
    for a in DeliveryArea.objects.filter(branch=selected_branch, is_active=True).order_by("delivery_fee", "name"):
        est_time = f"{a.estimated_time_minutes} min" if active_lang == "en" else f"{a.estimated_time_minutes} دقيقة"
        if not a.estimated_time_minutes:
            est_time = "30-45 min" if active_lang == "en" else "30-45 دقيقة"
        areas.append({
            "id": a.id,
            "name": a.name,
            "fee": float(a.delivery_fee or 0),
            "estimated_time": est_time,
        })

    is_open = selected_branch.is_currently_open()
    cur_sym = selected_branch.get_currency_symbol_ar() if active_lang == "ar" else selected_branch.get_currency_symbol_en()
    cur_name = selected_branch.get_currency_name_ar()
    context = {
        "tenant": tenant,
        "branches": branches,
        "selected_branch": selected_branch,
        "is_open": is_open,
        "min_delivery_order": float(selected_branch.min_delivery_order or 0),
        "branch_currency": selected_branch.currency,
        "branch_currency_symbol": cur_sym,
        "branch_currency_name": cur_name,
        "categories": categories_set,
        "category_objs": categories_data,
        "sections": sections,
        "categorized_items": categorized_items,
        "delivery_areas": areas,
        "brand_color": tenant.brand_color or "#0E382A",
        "CURRENT_LANG": active_lang,
        "DIR": "rtl" if active_lang == "ar" else "ltr",
        "IS_RTL": active_lang == "ar",
    }
    return render(request, "qr_menu.html", context)



def api_digital_menu_branch_areas(request, slug, branch_id):
    """Return JSON list of delivery areas for chosen branch."""
    tenant = get_object_or_404(Tenant, slug=slug, is_active=True)
    branch = get_object_or_404(Branch, tenant=tenant, id=branch_id, status="active")
    areas = []
    for a in DeliveryArea.objects.filter(branch=branch, is_active=True).order_by("delivery_fee", "name"):
        areas.append({
            "id": a.id,
            "name": a.name,
            "fee": float(a.delivery_fee or 0),
            "estimated_time": f"{a.estimated_time_minutes} دقيقة" if a.estimated_time_minutes else "30-45 دقيقة",
        })
    return JsonResponse({"status": "success", "areas": areas})


@csrf_exempt
def api_digital_menu_place_order(request, slug):
    """
    Public self-ordering endpoint for digital menu customers.
    Strictly accepts Takeaway (سفري) or Delivery (توصيل) orders only.
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    tenant = get_object_or_404(Tenant, slug=slug, is_active=True)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"status": "error", "message": "بيانات غير صالحة"}, status=400)

    branch_id = data.get("branch_id")
    order_type = str(data.get("order_type", "takeaway")).strip().lower()
    customer_name = str(data.get("customer_name", "")).strip()
    customer_phone = str(data.get("customer_phone", "")).strip()
    delivery_area_id = data.get("delivery_area_id")
    address = str(data.get("address", "")).strip()
    notes = str(data.get("notes", "")).strip()
    items_data = data.get("items", [])

    # Strict Validation: Takeaway and Delivery ONLY
    if order_type not in ["takeaway", "delivery"]:
        return JsonResponse({
            "status": "error",
            "message": "نوع الطلب غير صالح. الطلبات المتاحة هي: سفري أو توصيل فقط."
        }, status=400)

    if not customer_name or len(customer_name) < 2:
        return JsonResponse({"status": "error", "message": "يرجى كتابة اسم العميل بشكل صحيح."}, status=400)

    if not customer_phone or len(customer_phone) < 7:
        return JsonResponse({"status": "error", "message": "يرجى كتابة رقم هاتف صالح للتواصل."}, status=400)

    if order_type == "delivery":
        if not address:
            return JsonResponse({"status": "error", "message": "يرجى إدخال عنوان التوصيل المفصل."}, status=400)
        if not delivery_area_id:
            return JsonResponse({"status": "error", "message": "يرجى اختيار منطقة التوصيل من القائمة."}, status=400)

    branch = Branch.objects.filter(tenant=tenant, id=branch_id, status="active").first()
    if not branch:
        return JsonResponse({"status": "error", "message": "الفرع المحدد غير متاح لاستقبال الطلبات حالياً."}, status=400)

    # Check Branch Operating Hours
    if not branch.is_currently_open():
        time_info = ""
        if branch.opening_time and branch.closing_time:
            time_info = f" (ساعات العمل: {branch.opening_time.strftime('%I:%M %p')} إلى {branch.closing_time.strftime('%I:%M %p')})"
        return JsonResponse({
            "status": "error",
            "message": f"عذراً، فرع «{branch.name}» مغلق حالياً ولا يستقبل طلبات جديدة{time_info}."
        }, status=400)

    if not items_data or not isinstance(items_data, list):
        return JsonResponse({"status": "error", "message": "سلة الطلب فارغة. يرجى اختيار وجبات من المنيو أولاً."}, status=400)

    # Validate items and calculate totals strictly from DB
    menu_ids = [int(i.get("menuItemId") or i.get("id") or 0) for i in items_data if (i.get("menuItemId") or i.get("id"))]
    menu_map = {m.id: m for m in MenuItem.objects.filter(tenant=tenant, id__in=menu_ids)}
    disabled_ids = set(
        BranchMenuAvailability.objects.filter(branch=branch, is_available=False).values_list("menu_item_id", flat=True)
    )

    order_items_to_create = []
    subtotal = Decimal("0.00")
    for it in items_data:
        m_id = int(it.get("menuItemId") or it.get("id") or 0)
        m = menu_map.get(m_id)
        if not m or not m.available or m_id in disabled_ids:
            return JsonResponse({
                "status": "error",
                "message": f"الصنف «{m.name if m else m_id}» غير متاح للطلب في هذا الفرع حالياً."
            }, status=400)
        qty = max(1, int(it.get("qty", 1)))

        # Check variant (size) if selected
        v_id = it.get("variantId") or it.get("variant_id")
        variant_obj = None
        item_price = m.get_price_for_branch(branch)
        item_title = m.name
        if v_id and m.has_variants:
            variant_obj = MenuItemVariant.objects.filter(id=v_id, menu_item=m).first()
            if variant_obj:
                item_price = variant_obj.get_price_for_branch(branch)
                item_title = f"{m.name} ({variant_obj.name})"
        elif m.has_variants:
            variant_obj = m.variants.filter(is_default=True).first() or m.variants.first()
            if variant_obj:
                item_price = variant_obj.get_price_for_branch(branch)
                item_title = f"{m.name} ({variant_obj.name})"

        note_str = str(it.get("notes", "")).strip()[:200]
        if note_str:
            item_title = f"{item_title} [{note_str}]"

        subtotal += item_price * qty
        order_items_to_create.append({
            "item": m,
            "variant": variant_obj,
            "variant_name": variant_obj.name if variant_obj else "",
            "title": item_title,
            "qty": qty,
            "price": item_price,
        })

    # Validate Minimum Delivery Order
    if order_type == "delivery" and branch.min_delivery_order > 0 and subtotal < branch.min_delivery_order:
        cur_sym = branch.get_currency_symbol_ar()
        return JsonResponse({
            "status": "error",
            "message": f"الحد الأدنى لطلب التوصيل من هذا الفرع هو {branch.min_delivery_order} {cur_sym}. (المجموع الحالي: {subtotal} {cur_sym})."
        }, status=400)

    delivery_fee = Decimal("0.00")
    area = None
    if order_type == "delivery" and delivery_area_id:
        area = DeliveryArea.objects.filter(branch=branch, id=delivery_area_id, is_active=True).first()
        if area and area.delivery_fee:
            delivery_fee = Decimal(str(area.delivery_fee))

    total = subtotal + delivery_fee

    # Generate unique order number
    import secrets
    ord_number = f"QR-{secrets.token_hex(3).upper()}"
    while Order.objects.filter(tenant=tenant, order_number=ord_number).exists():
        ord_number = f"QR-{secrets.token_hex(3).upper()}"

    # Customer record
    cust, _ = Customer.objects.get_or_create(
        tenant=tenant,
        phone=customer_phone,
        defaults={"name": customer_name, "address": address}
    )

    order = Order.objects.create(
        tenant=tenant,
        branch=branch,
        order_number=ord_number,
        order_type=order_type,
        channel="qr_menu",
        status="new",
        pay_method="cash",
        paid=False,
        customer=cust,
        customer_name=customer_name,
        customer_phone=customer_phone,
        address=address,
        delivery_area=area,
        delivery_fee=delivery_fee,
        subtotal=subtotal,
        total=total,
        notes=notes,
    )

    for row in order_items_to_create:
        OrderItem.objects.create(
            order=order,
            menu_item=row["item"],
            variant=row["variant"],
            variant_name=row["variant_name"],
            name=row["title"],
            price=row["price"],
            qty=row["qty"],
        )

    # Broadcast real-time SSE event to kitchen display screens (0ms dispatch)
    try:
        notify_kitchen_order_event(order, "new_order")
    except Exception as e:
        logger.warning(f"Failed to dispatch kitchen SSE for QR order {order.order_number}: {e}")

    active_lang = request.session.get("django_language") or request.COOKIES.get("django_language") or "ar"
    if hasattr(request, "LANGUAGE_CODE") and request.LANGUAGE_CODE:
        active_lang = request.LANGUAGE_CODE
    if "-" in active_lang:
        active_lang = active_lang.split("-")[0]
    is_en = (active_lang == "en")

    return JsonResponse({
        "status": "success",
        "message": "Your order has been received successfully! Preparing in the kitchen." if is_en else "تم استلام طلبك بنجاح! جاري تحضيره في المطبخ.",
        "order_id": order.id,
        "order_number": order.order_number,
        "order_type": ("Takeaway Pickup" if order.order_type == "takeaway" else "Home Delivery") if is_en else order.get_order_type_display(),
        "branch_name": branch.get_display_name(active_lang),
        "total": float(order.total),
        "subtotal": float(order.subtotal),
        "delivery_fee": float(order.delivery_fee),
    }, status=201)


@login_required
def api_update_tenant_branding(request):
    """Update restaurant logo, cover, bio, brand color, and name."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"error": "منشأة غير موجودة"}, status=400)

    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner and not user_has_perm(request.user, "manage_menu"):
        return JsonResponse({"error": "غير مصرح لك بتعديل هوية المطعم"}, status=403)

    name = request.POST.get("name", "").strip()
    if name:
        tenant.name = name

    bio = request.POST.get("bio", "").strip()
    if bio is not None:
        tenant.bio = bio

    brand_color = request.POST.get("brand_color", "").strip()
    if brand_color:
        tenant.brand_color = brand_color

    logo_emoji = request.POST.get("logo_emoji", "").strip()
    if logo_emoji:
        tenant.logo_emoji = logo_emoji

    if "logo_image" in request.FILES:
        tenant.logo_image = request.FILES["logo_image"]

    if "cover_image" in request.FILES:
        tenant.cover_image = request.FILES["cover_image"]

    tenant.save()
    return JsonResponse({
        "status": "success",
        "message": "تم تحديث هوية وشعار المطعم بنجاح",
        "tenant": {
            "name": tenant.name,
            "bio": tenant.bio,
            "brand_color": tenant.brand_color,
            "logo_emoji": tenant.logo_emoji,
            "logo_url": tenant.logo_image.url if tenant.logo_image else "",
            "cover_url": tenant.cover_image.url if tenant.cover_image else "",
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

