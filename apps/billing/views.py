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
