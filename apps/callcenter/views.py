import os
import json
import logging
from decimal import Decimal
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotFound, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.views.decorators.cache import never_cache
from django.utils import timezone
from django.db.models import Sum, Count, F, Q
from django.core.cache import cache

from apps.tenants.helpers import get_active_tenant, get_active_branch
from apps.accounts.helpers import user_has_perm, _get_client_ip
from apps.callcenter.models import TenantApiKey
from apps.tenants.models import Tenant, Branch, DeliveryArea
from apps.menu.models import MenuItem
from apps.orders.models import Order, Customer
from apps.audit.models import log_audit_event, KnowledgeDocument
from apps.accounts.models import Employee

logger = logging.getLogger(__name__)

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
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner:
        return None, HttpResponseForbidden("صفحة إدارة المساعد الصوتي والذكاء الاصطناعي مقتصرة حصرياً على مالك المنشأة")

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


