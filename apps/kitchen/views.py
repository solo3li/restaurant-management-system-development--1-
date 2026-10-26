import json
import asyncio
from django.shortcuts import render
from django.http import HttpResponseForbidden, StreamingHttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from asgiref.sync import sync_to_async

from apps.tenants.helpers import get_active_tenant, get_active_branch
from apps.accounts.helpers import user_has_perm
from apps.kitchen.events import kitchen_broadcaster, serialize_kitchen_order
from apps.orders.models import Order
from apps.menu.models import MenuItem
from apps.tenants.models import Branch


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

    from django.utils.text import slugify
    from core.i18n_catalog import I18N_CATALOG

    category_translations = {cat: I18N_CATALOG.get(cat, cat) for cat in menu_categories}
    categories_data = [
        {
            "id": cat,
            "slug": slugify(cat, allow_unicode=True) or f"station-{i}",
            "name_ar": cat,
            "name_en": I18N_CATALOG.get(cat, cat),
        }
        for i, cat in enumerate(menu_categories)
    ]

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
        "categories_data": categories_data,
        "category_translations": category_translations,
        "category_translations_json": json.dumps(category_translations),
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
