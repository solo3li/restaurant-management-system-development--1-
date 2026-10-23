import sys
import json
from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.contrib.auth.decorators import login_required

from apps.tenants.helpers import get_active_tenant
from apps.accounts.helpers import user_has_perm
from apps.billing.models import SubscriptionPlan, UpgradeRequest, SAAS_FEATURES_CATALOG
from apps.tenants.models import Branch
from apps.accounts.models import Employee
from apps.orders.models import Order
from apps.callcenter.models import TenantApiKey


@login_required
def owner_subscription_view(request):
    """Owner dashboard for viewing current subscription, limits usage, and requesting upgrades."""
    is_en = (request.session.get("django_language") == "en" or request.GET.get("lang") == "en" or getattr(request, "LANGUAGE_CODE", "") == "en")
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin)) or user_has_perm(request.user, "system_manage_billing")
    if not is_owner:
        msg = "The subscription & profile management page is restricted to restaurant owners and authorized billing managers." if is_en else "صفحة إدارة الاشتراك مخصصة لمالك المنشأة أو المسؤول المخول بالفوترة"
        return HttpResponseForbidden(msg)

    tenant = get_active_tenant(request)
    if not tenant:
        msg = "No active restaurant associated with your account" if is_en else "لم يتم العثور على منشأة نشطة مرتبطة بحسابك"
        return HttpResponseBadRequest(msg)

    branches_count = Branch.objects.filter(tenant=tenant, status="active").count()
    employees_count = Employee.objects.filter(tenant=tenant, status__in=["active", "vacation"]).count()
    orders_count = Order.objects.filter(tenant=tenant).count()
    
    plan = tenant.subscription_plan
    if not plan:
        plan = SubscriptionPlan.objects.filter(code=getattr(tenant, "plan", "")).first() or SubscriptionPlan.objects.filter(code="trial").first()
    max_branches = plan.max_branches if plan else 1
    max_employees = plan.max_employees if plan else 5

    is_unlimited_branches = max_branches >= 999 or max_branches == 0
    is_unlimited_employees = max_employees >= 999 or max_employees == 0

    remaining_branches = 999 if is_unlimited_branches else max(0, max_branches - branches_count)
    remaining_employees = 999 if is_unlimited_employees else max(0, max_employees - employees_count)

    branches_pct = min(100, int((branches_count / max_branches) * 100)) if (max_branches > 0 and not is_unlimited_branches) else min(100, branches_count * 10)
    employees_pct = min(100, int((employees_count / max_employees) * 100)) if (max_employees > 0 and not is_unlimited_employees) else min(100, employees_count * 5)

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

    feature_i18n = {
        "pos": {
            "en_name": "Point of Sale (POS)",
            "en_desc": "Dine-in, takeaway, and compliant e-invoicing",
        },
        "kds": {
            "en_name": "Kitchen Display System (KDS)",
            "en_desc": "Real-time kitchen prep station management",
        },
        "menu_management": {
            "en_name": "Menu & Recipe Management",
            "en_desc": "Menu catalogs and branch-specific dish pricing",
        },
        "delivery_management": {
            "en_name": "Delivery Dispatch & Fleet",
            "en_desc": "Delivery zone geofencing and driver dispatching",
        },
        "call_center": {
            "en_name": "AI Call Center & Orders",
            "en_desc": "Inbound telephony order capture & auto-routing",
        },
        "inventory": {
            "en_name": "Inventory & Stock Audit",
            "en_desc": "Multi-warehouse stock auditing and low inventory alerts",
        },
        "custom_roles": {
            "en_name": "Custom Roles & Granular RBAC",
            "en_desc": "Permission matrix and custom staff job roles",
        },
        "financial_analytics": {
            "en_name": "Financial Analytics & Reports",
            "en_desc": "Revenue metrics, sales analytics, and payment breakdowns",
        },
    }

    # Catalog mapped with enabled flags for current plan
    current_features = plan.features if plan and plan.features else []
    features_with_status = []
    for feat in SAAS_FEATURES_CATALOG:
        f_key = feat.get("key") or feat.get("code")
        f_label = feat.get("label") or feat.get("name")
        f_desc = feat.get("desc", "")
        f_icon = feature_icons.get(f_key, "✨")
        f_i18n = feature_i18n.get(f_key, {})
        is_active_feat = (f_key in current_features) or (request.user.is_superuser)
        features_with_status.append({
            "key": f_key,
            "code": f_key,
            "name": f_label,
            "name_en": f_i18n.get("en_name", f_label),
            "label": f_label,
            "desc": f_desc,
            "desc_en": f_i18n.get("en_desc", f_desc),
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
        "is_unlimited_branches": is_unlimited_branches,
        "is_unlimited_employees": is_unlimited_employees,
        "remaining_branches": remaining_branches,
        "remaining_employees": remaining_employees,
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

    is_en = (request.session.get("django_language") == "en" or request.GET.get("lang") == "en" or getattr(request, "LANGUAGE_CODE", "") == "en")

    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin)) or user_has_perm(request.user, "system_manage_billing")
    if not is_owner:
        err_msg = "Plan upgrade request is restricted to restaurant owners and billing managers only." if is_en else "طلب الترقية مقتصر على مالك المنشأة أو المسؤول المخول بالفوترة فقط"
        return JsonResponse({"error": err_msg}, status=403)

    tenant = get_active_tenant(request)
    if not tenant:
        err_msg = "No active restaurant associated with your account" if is_en else "لا توجد منشأة نشطة مرتبطة بحسابك"
        return JsonResponse({"error": err_msg}, status=400)

    try:
        body = json.loads(request.body.decode("utf-8"))
    except Exception:
        err_msg = "Invalid JSON data" if is_en else "بيانات غير صالحة"
        return JsonResponse({"error": err_msg}, status=400)

    plan_id = body.get("plan_id")
    billing_cycle = body.get("billing_cycle", "monthly")
    notes = str(body.get("notes", "")).strip()

    if not plan_id:
        err_msg = "Please select the target plan" if is_en else "يرجى تحديد الباقة المطلوبة"
        return JsonResponse({"error": err_msg}, status=400)

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

    plan_display = plan.name
    if is_en:
        from core.i18n_catalog import I18N_CATALOG
        plan_display_map = {
            "starter": "Starter Plan",
            "growth": "Growth Plan",
            "enterprise": "Enterprise Plan",
            "trial": "Free Trial Plan",
            "basic": "Basic Plan",
            "pro": "Pro Plan",
        }
        plan_display = plan_display_map.get(plan.code, I18N_CATALOG.get(plan.name, plan.name))
        succ_msg = f"Plan upgrade request for '{plan_display}' submitted successfully! Platform admins will review and activate it."
    else:
        succ_msg = f"تم إرسال طلب الترقية إلى باقة «{plan.name}» بنجاح! سيتم مراجعته وتفعيله من قبل إدارة المنصة."

    return JsonResponse({
        "ok": True,
        "message": succ_msg,
        "request_id": upgrade_req.id,
        "status": upgrade_req.status,
    })
