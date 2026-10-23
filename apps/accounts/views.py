import os
import json
import csv
import logging
from decimal import Decimal
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.db.models import Sum, Count, F, Q

from apps.tenants.helpers import get_active_tenant, get_active_branch
from apps.accounts.helpers import (
    _get_client_ip,
    _check_rate_limit,
    _record_failed_attempt,
    _clear_rate_limit,
    user_has_perm,
    get_post_login_redirect,
)
from apps.accounts.models import (
    Employee,
    JobRole,
    UserProfile,
    RestaurantOwner,
    RESTAURANT_PERMISSIONS,
    PERMISSIONS_CATALOG,
    BRANCH_PERMISSIONS,
    HQ_PERMISSIONS,
    ensure_tenant_preset_roles,
)
from apps.tenants.models import Tenant, Branch
from apps.billing.models import SubscriptionPlan
from apps.audit.models import log_audit_event
from apps.orders.models import Order

logger = logging.getLogger(__name__)

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

                # 7. Authenticate and redirect
                login(request, user)
                request.session["active_tenant_id"] = tenant.id
                return redirect("dashboard")

            except Exception as e:
                error_message = f"حدث خطأ أثناء إنشاء الحساب: {str(e)}"

    return render(request, "register.html", {
        "error": error_message,
        "plans": plans
    })



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
    roles_stats = {
        "total": job_roles.count(),
        "branch": sum(1 for r in job_roles if r.scope == "branch"),
        "hq": sum(1 for r in job_roles if r.scope == "hq"),
        "assigned_employees": sum(r.emp_count for r in job_roles),
    }

    active_tab = request.GET.get("tab", "employees")

    context = {
        "tenant": tenant,
        "current_branch": active_branch,
        "employees": employees,
        "branches": branches,
        "job_roles": job_roles,
        "roles_stats": roles_stats,
        "active_tab": active_tab,
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
        stats = {
            "total": len(data),
            "branch": sum(1 for r in data if r["scope"] == "branch"),
            "hq": sum(1 for r in data if r["scope"] == "hq"),
            "assigned_employees": sum(r["employees_count"] for r in data),
        }
        return JsonResponse({"ok": True, "roles": data, "catalog": PERMISSIONS_CATALOG, "stats": stats})

    elif request.method == "POST":
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
        if scope not in ["hq", "branch"]:
            scope = "branch"

        description = str(body.get("description", "")).strip()
        permissions = body.get("permissions", [])
        if not isinstance(permissions, list):
            permissions = []

        # Strict Scope Validation: Cannot mix branch and hq permissions
        if scope == "branch":
            invalid_perms = [p for p in permissions if p in HQ_PERMISSIONS and p not in BRANCH_PERMISSIONS]
            if invalid_perms:
                return JsonResponse({"error": "لا يمكن إسناد صلاحيات الإدارة العامة (HQ) لمسمى وظيفي خاص بتشغيل الفرع (Branch)."}, status=400)
        elif scope == "hq":
            invalid_perms = [p for p in permissions if p in BRANCH_PERMISSIONS and p not in HQ_PERMISSIONS]
            if invalid_perms:
                return JsonResponse({"error": "لا يمكن إسناد صلاحيات تشغيل الفرع (Branch) لمسمى وظيفي خاص بالإدارة العامة (HQ)."}, status=400)

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

    if not is_owner_or_super and not user_has_perm(request.user, "manage_roles") and not user_has_perm(request.user, "hr_view_employees") and not user_has_perm(request.user, "manage_employees"):
        return JsonResponse({"error": "غير مصرح لك بالوصول لبيانات المسميات الوظيفية"}, status=403)

    if request.method == "GET":
        perms_list = role.get_permissions_list()
        employees_data = [
            {
                "id": emp.id,
                "name": emp.name,
                "employee_code": emp.employee_code or "—",
                "phone": emp.phone or "—",
                "branch_name": emp.branch.name if emp.branch else "الإدارة العامة",
            }
            for emp in role.employees.select_related("branch").order_by("name")
        ]
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
                "employees_count": len(employees_data),
                "employees": employees_data,
            }
        })

    if not is_owner_or_super and not user_has_perm(request.user, "manage_roles"):
        return JsonResponse({"error": "غير مصرح لك بتعديل أو حذف المسميات الوظيفية"}, status=403)

    if request.method in ["POST", "PATCH", "PUT", "DELETE"]:
        body = {}
        if request.body:
            try:
                body = json.loads(request.body.decode("utf-8"))
            except Exception:
                pass

        action = body.get("action")
        if action == "delete" or request.method == "DELETE":
            reassign_to_role_id = body.get("reassign_to_role_id")
            if role.employees.exists():
                if not reassign_to_role_id:
                    return JsonResponse({
                        "error": f"لا يمكن حذف المسمى «{role.name}» لوجود {role.employees.count()} موظف مرتبطين به. يرجى اختيار مسمى بديل لنقلهم إليه أولاً.",
                        "requires_reassign": True,
                        "employees_count": role.employees.count(),
                    }, status=400)

                target_role = get_object_or_404(JobRole, tenant=tenant, id=reassign_to_role_id)
                target_grp = target_role.sync_with_django_group()
                for emp in role.employees.select_related("user"):
                    emp.job_role = target_role
                    emp.save(update_fields=["job_role"])
                    if emp.user and hasattr(emp.user, "profile"):
                        emp.user.profile.job_role = target_role
                        emp.user.profile.save()
                    if emp.user and target_grp:
                        emp.user.groups.set([target_grp])
                        for cache_field in ["_perm_cache", "_group_perm_cache", "_user_perm_cache"]:
                            if hasattr(emp.user, cache_field):
                                delattr(emp.user, cache_field)

            log_audit_event(
                tenant=tenant,
                user=request.user,
                action="role_deleted",
                target_model="JobRole",
                target_id=role.id,
                description=f"حذف المسمى الوظيفي «{role.name}»" + (f" ونقل الموظفين إلى «{target_role.name}»" if reassign_to_role_id else ""),
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

        target_scope = body.get("scope", role.scope)
        if target_scope not in ["hq", "branch"]:
            target_scope = role.scope

        if "permissions" in body and isinstance(body["permissions"], list):
            target_perms = body["permissions"]
            if target_scope == "branch":
                invalid_perms = [p for p in target_perms if p in HQ_PERMISSIONS and p not in BRANCH_PERMISSIONS]
                if invalid_perms:
                    return JsonResponse({"error": "لا يمكن إسناد صلاحيات الإدارة العامة (HQ) لمسمى وظيفي خاص بتشغيل الفرع (Branch)."}, status=400)
            elif target_scope == "hq":
                invalid_perms = [p for p in target_perms if p in BRANCH_PERMISSIONS and p not in HQ_PERMISSIONS]
                if invalid_perms:
                    return JsonResponse({"error": "لا يمكن إسناد صلاحيات تشغيل الفرع (Branch) لمسمى وظيفي خاص بالإدارة العامة (HQ)."}, status=400)

        role.scope = target_scope
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

    return HttpResponseBadRequest("Invalid method")


# ==========================================
# 9. SAAS SUBSCRIPTION PLANS & TENANT LIMITS
# ==========================================




