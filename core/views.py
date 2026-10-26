"""
Core Views Facade & Central Handlers
-------------------------------------
Views have been modularized into domain-driven applications under `apps/`:
  - apps.accounts.views: Auth, employees, RBAC, job roles
  - apps.tenants.views: Branches, switching, delivery areas, branding, settings
  - apps.billing.views: Subscription plans, upgrade requests
  - apps.kitchen.views: Kitchen display system (KDS), SSE live stream
  - apps.orders.views: POS, delivery, order details & edits, cashier APIs
  - apps.menu.views: Menu categories, items, variants, branch pricing, QR digital menu
  - apps.inventory.views: Raw materials, stock adjustments, inventory alerts
  - apps.callcenter.views: Live phone orders, AI voice center management & tools
  - apps.audit.views: Security audit logs

This facade provides central landing and dashboard views, language switching,
and re-exports all domain views for 100% backward compatibility.
"""
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone, translation
from django.db.models import Sum, Count, F

# Helper imports from apps
from apps.tenants.helpers import get_active_tenant, get_active_branch
from apps.accounts.helpers import (
    user_has_perm,
    get_post_login_redirect,
    _get_client_ip,
    _check_rate_limit,
    _record_failed_attempt,
    _clear_rate_limit,
)

# Domain Model Imports
from apps.tenants.models import Tenant, Branch
from apps.orders.models import Order, OrderItem
from apps.inventory.models import InventoryItem
from apps.accounts.models import Employee
from apps.billing.models import SubscriptionPlan, SAAS_FEATURES_CATALOG

# Re-export all view functions from domain apps for 100% backward compatibility
from apps.accounts.views import (
    login_view,
    logout_view,
    register_view,
    employees_view,
    get_or_create_employee_user,
    api_create_employee,
    api_update_employee,
    api_delete_employee,
    api_toggle_employee_status,
    api_employee_detail,
    api_export_employees_csv,
    api_job_roles,
    api_job_role_detail,
)

from apps.tenants.views import (
    switch_branch_view,
    platform_dashboard_view,
    switch_tenant_view,
    branch_dashboard_view,
    branches_view,
    restaurant_profile_view,
    api_restaurant_profile_update,
    api_create_branch,
    api_branch_delivery_areas,
    api_toggle_branch,
    api_update_branch_currency,
    api_update_tenant_currency,
    api_update_tenant_branding,
    api_update_custom_domain,
)

from apps.billing.views import (
    owner_subscription_view,
    api_request_upgrade,
)

from apps.kitchen.views import (
    kitchen_view,
    kitchen_stream_view,
    kitchen_live_view,
)

from apps.orders.views import (
    branch_orders_view,
    hq_orders_view,
    order_detail_view,
    order_edit_view,
    api_cancel_order,
    api_delete_order,
    pos_view,
    delivery_view,
    delivery_stream_view,
    api_delivery_live,
    api_create_order,
    api_update_order,
    api_search_customers,
)

from apps.menu.views import (
    branch_menu_view,
    api_toggle_branch_menu,
    api_update_branch_item_price,
    api_get_item_branch_prices,
    api_update_item_branch_prices,
    api_toggle_menu_item,
    api_create_menu_item,
    api_update_menu_item,
    api_delete_menu_item,
    api_list_categories,
    api_create_category,
    api_update_category,
    api_delete_category,
    digital_menu_view,
    api_digital_menu_branch_areas,
    api_digital_menu_place_order,
)

from apps.inventory.views import (
    inventory_view,
    api_adjust_inventory,
    api_create_inventory,
    api_delete_inventory,
)

from apps.callcenter.views import (
    call_center_view,
    api_create_api_key,
    api_toggle_api_key,
    api_delete_api_key,
    _validate_callcenter_page_access,
    _get_callcenter_client_info,
    _norm_phone,
    _fetch_enriched_calls,
    ai_callcenter_management_view,
    ai_callcenter_overview_view,
    ai_callcenter_persona_view,
    ai_callcenter_hours_view,
    ai_callcenter_knowledge_view,
    ai_callcenter_queues_view,
    ai_callcenter_calls_view,
    ai_callcenter_capabilities_view,
    ai_callcenter_omnichannel_view,
    _check_callcenter_admin,
    _authenticate_callcenter_request,
    api_ai_callcenter_create_profile,
    api_ai_callcenter_update_profile,
    api_ai_callcenter_activate_profile,
    api_ai_callcenter_delete_profile,
    api_ai_callcenter_update_hours,
    api_ai_callcenter_add_doc,
    api_ai_callcenter_delete_doc,
    api_ai_callcenter_add_employee,
    api_ai_callcenter_delete_employee,
    api_ai_callcenter_get_employee_credentials,
    api_ai_callcenter_reset_employee_password,
    api_ai_callcenter_update_employee_status,
    api_ai_callcenter_save_queue,
    api_ai_callcenter_delete_queue,
    api_ai_callcenter_add_queue_member,
    api_ai_callcenter_remove_queue_member,
    api_ai_callcenter_sync_mcp,
    api_ai_callcenter_update_mcp_url,
    api_ai_callcenter_test_mcp_tool,
    api_ai_callcenter_sync_live_context,
    api_ai_callcenter_get_live_context,
    api_ai_callcenter_dial_customer,
    api_ai_callcenter_call_recording_proxy,
    api_ai_callcenter_whatsapp_status,
    api_ai_callcenter_whatsapp_connect,
    api_ai_callcenter_whatsapp_disconnect,
    api_ai_callcenter_whatsapp_send,
    api_ai_callcenter_whatsapp_conversations,
    api_ai_callcenter_whatsapp_conversation_messages,
    api_ai_callcenter_whatsapp_message_media,
    api_ai_callcenter_whatsapp_conversation_reply,
    api_ai_callcenter_whatsapp_conversation_toggle_ai,
    api_ai_callcenter_whatsapp_sync,
    api_ai_callcenter_telephony_info,
    api_ai_callcenter_usage,
    api_ai_callcenter_sync_caps,
    api_ai_callcenter_initiate_webrtc,
)

from apps.audit.views import (
    api_audit_logs,
)
from django.views.decorators.csrf import ensure_csrf_cookie


@ensure_csrf_cookie
def landing_view(request):

    """Public Landing Page with guest and authenticated navigation states."""
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
        "is_landing": True,
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


def set_language_view(request, lang_code):
    """
    Switch active interface language (ar/en), save to session and cookie,
    and redirect back to the previous page or next parameter.
    """
    if lang_code not in ["ar", "en"]:
        lang_code = "ar"

    translation.activate(lang_code)
    
    from django.utils.http import url_has_allowed_host_and_scheme
    next_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or "/"

    # Disallow open redirect vulnerabilities (external hosts, scheme-relative //, and backslash paths)
    if (
        not url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure()
        )
        or next_url.startswith("//")
        or next_url.startswith("/\\")
    ):
        next_url = "/"

    # Update or strip 'lang' query param in next_url to ensure the redirected page loads in lang_code
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    parsed = urlparse(next_url)
    query_params = parse_qs(parsed.query)
    if "lang" in query_params:
        query_params["lang"] = [lang_code]
        new_query = urlencode(query_params, doseq=True)
        next_url = urlunparse(parsed._replace(query=new_query))

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
