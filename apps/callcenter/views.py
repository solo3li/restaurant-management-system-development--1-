import os
import re
import json
import logging
from decimal import Decimal
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import (
    JsonResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    HttpResponse,
    StreamingHttpResponse,
)
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db.models import Sum, Count, F, Q
from django.core.cache import cache

from apps.tenants.helpers import get_active_tenant, get_active_branch
from apps.accounts.helpers import user_has_perm, _get_client_ip
from apps.callcenter.models import TenantApiKey
from django.utils import translation
from apps.tenants.models import Tenant, Branch, DeliveryArea
from apps.menu.models import MenuItem, MenuCategory
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

    lang = getattr(request, "LANGUAGE_CODE", None) or translation.get_language() or "ar"
    if "-" in lang:
        lang = lang.split("-")[0]
    if lang not in ["ar", "en"]:
        lang = "ar"

    branches = Branch.objects.filter(tenant=tenant, status="active").prefetch_related("delivery_areas").order_by("name")
    recent_orders = Order.objects.filter(tenant=tenant, channel="call_center").order_by("-id")[:10] if tenant else []
    delivery_areas = DeliveryArea.objects.filter(branch__tenant=tenant, is_active=True).select_related("branch").order_by("branch__name", "name") if tenant else []

    # Dynamic Menu Categories from apps.menu.models.MenuCategory (matching POS)
    active_categories_qs = (
        MenuCategory.objects.filter(tenant=tenant, is_active=True).order_by("ordering", "id")
        if tenant
        else MenuCategory.objects.none()
    )

    # Legacy migration fallback: ONLY if tenant has NEVER had any MenuCategories in DB before
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

    raw_items = (
        MenuItem.objects.filter(tenant=tenant, available=True, is_active=True)
        .select_related("category_rel")
        .order_by("category_rel__ordering", "category_rel__id", "category", "name")
        if tenant
        else MenuItem.objects.none()
    )

    BORDER_PALETTE = [
        "border-r-4 border-r-violet-500",
        "border-r-4 border-r-blue-500",
        "border-r-4 border-r-emerald-500",
        "border-r-4 border-r-amber-500",
        "border-r-4 border-r-orange-500",
        "border-r-4 border-r-teal-500",
        "border-r-4 border-r-cyan-500",
        "border-r-4 border-r-rose-500",
        "border-r-4 border-r-pink-500",
        "border-r-4 border-r-indigo-500",
    ]

    menu_items = []
    seen_extra_cats = []
    has_uncategorized = False
    for m in raw_items:
        resolved_cat = None
        if m.category_rel_id and m.category_rel_id in cat_by_id:
            resolved_cat = cat_by_id[m.category_rel_id]
        elif m.category and m.category.strip().lower() in cat_by_name:
            resolved_cat = cat_by_name[m.category.strip().lower()]

        if resolved_cat:
            m.pos_category_id = str(resolved_cat.id)
            m.pos_category_name = resolved_cat.get_display_name(lang)
            color_idx = resolved_cat.id % len(BORDER_PALETTE)
            m.border_color_class = BORDER_PALETTE[color_idx]
        elif m.category and m.category.strip():
            clean_cat = m.category.strip()
            m.pos_category_id = f"custom_{clean_cat}"
            m.pos_category_name = clean_cat
            if clean_cat not in seen_extra_cats and clean_cat.lower() not in cat_by_name:
                seen_extra_cats.append(clean_cat)
            color_idx = abs(hash(clean_cat)) % len(BORDER_PALETTE)
            m.border_color_class = BORDER_PALETTE[color_idx]
        else:
            m.pos_category_id = "uncategorized"
            m.pos_category_name = "أطباق عامة" if lang == "ar" else "General"
            m.border_color_class = "border-r-4 border-r-slate-400"
            has_uncategorized = True

        menu_items.append(m)

    # Build category list for Call Center tab pills
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
    for ex in seen_extra_cats:
        categories.append({
            "id": f"custom_{ex}",
            "name": ex,
            "raw_name": ex,
            "is_all": False,
        })
    if has_uncategorized and not any(c["id"] == "uncategorized" for c in categories):
        categories.append({
            "id": "uncategorized",
            "name": "أطباق عامة" if lang == "ar" else "General",
            "raw_name": "uncategorized",
            "is_all": False,
        })

    # If restaurant has no menu items yet, simplify categories to only 'All'
    if not menu_items:
        categories = [
            {
                "id": "all",
                "name": "الكل" if lang == "ar" else "All",
                "raw_name": "all",
                "is_all": True,
            }
        ]

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

def _resolve_callcenter_tenant(request):
    """
    Resolve active tenant for Call Center management.
    Platform admins & Superadmins default to Platform HQ tenant unless
    an active_tenant_id session override is explicitly selected.
    """
    profile = getattr(request.user, "profile", None)
    is_super = (
        getattr(request.user, "is_superuser", False)
        or getattr(request, "is_platform_admin", False)
        or (profile and (profile.role == "platform_admin" or getattr(profile, "is_platform_admin", False)))
    )
    if is_super:
        active_t_id = request.session.get("active_tenant_id") if hasattr(request, "session") else None
        if not active_t_id:
            from apps.callcenter.platform_hq import get_or_create_platform_hq_tenant
            hq_tenant = get_or_create_platform_hq_tenant()
            if hq_tenant:
                return hq_tenant
    return get_active_tenant(request)


def _validate_callcenter_page_access(request):
    """
    Validate permissions and active tenant for AI Call Center pages.
    Returns (tenant, None) on success or (None, HttpResponse) on error.
    """
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner:
        return None, HttpResponseForbidden("صفحة إدارة المساعد الصوتي والذكاء الاصطناعي مقتصرة حصرياً على مالك المنشأة")

    tenant = _resolve_callcenter_tenant(request)

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

    for p in profiles_data:
        if isinstance(p, dict):
            p.setdefault("dialect", "saudi")
            p.setdefault("language", "arabic")
            p.setdefault("persona_role", "restaurant_orders")
            p.setdefault("gender", "female")
            p.setdefault("voice_name", "Aoede")
    if isinstance(profile_data, dict):
        profile_data.setdefault("dialect", "saudi")
        profile_data.setdefault("language", "arabic")
        profile_data.setdefault("persona_role", "restaurant_orders")
        profile_data.setdefault("gender", "female")
        profile_data.setdefault("voice_name", "Aoede")

    # Clean old placeholder restaurant names in welcome message
    rest_name = tenant.name if (tenant and tenant.name) else "المطعم"
    if profile_data and "مطاعم كورا" in str(profile_data.get("welcome_message", "")):
        profile_data["welcome_message"] = str(profile_data["welcome_message"]).replace("مطاعم كورا", rest_name)

    # Fetch full studio metadata from partner API
    studio_data = ps.get_studio_metadata(client_id)
    if not isinstance(studio_data, dict) or studio_data.get("status") != "success":
        studio_data = {}

    from apps.callcenter.models import PlatformVoiceAssistantConfig
    config = PlatformVoiceAssistantConfig.get_config()
    landing_profile_id = getattr(config, "landing_profile_id", None)
    if not landing_profile_id and profiles_data:
        matched_landing = next((p for p in profiles_data if p.get("name") == config.assistant_name or p.get("voice_name") == config.voice_name), None)
        if matched_landing:
            landing_profile_id = matched_landing.get("id")

    for p in profiles_data:
        if isinstance(p, dict):
            p_id = p.get("id")
            p["is_landing_persona"] = bool(landing_profile_id is not None and str(p_id) == str(landing_profile_id))

    user_profile = getattr(request.user, "profile", None)
    is_plat_admin = request.user.is_superuser or getattr(request, "is_platform_admin", False) or (user_profile and getattr(user_profile, "is_platform_admin", False))

    context = {
        "tenant": tenant,
        "profile": profile_data,
        "profiles": profiles_data,
        "studio": studio_data,
        "studio_json": json.dumps(studio_data),
        "landing_profile_id": landing_profile_id,
        "landing_config": config,
        "is_platform_admin": is_plat_admin,
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

    ready_count = sum(1 for e in employees_data if e.get("status") == "ready")
    busy_count = sum(1 for e in employees_data if e.get("status") == "busy")
    offline_count = sum(1 for e in employees_data if e.get("status") not in ["ready", "busy"])

    queues_stats = {
        "total_queues": len(queues_data),
        "total_employees": len(employees_data),
        "ready_count": ready_count,
        "busy_offline_count": busy_count + offline_count,
    }

    context = {
        "tenant": tenant,
        "employees": employees_data,
        "queues": queues_data,
        "primary_queue": queues_data[0] if queues_data else None,
        "queues_stats": queues_stats,
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

    pbx_resp = ps.get_pbx_trunks(client_id)
    pbx_trunks = pbx_resp.get("trunks", []) if isinstance(pbx_resp, dict) else []
    sip_resp = ps.get_telephony_trunks(client_id)
    sip_trunks = (sip_resp.get("outbound_trunks", []) + sip_resp.get("inbound_trunks", [])) if isinstance(sip_resp, dict) else []

    context = {
        "tenant": tenant,
        "did_number": primary_did,
        "has_did": has_did,
        "did_numbers": raw_nums,
        "pbx_trunks": pbx_trunks,
        "sip_trunks": sip_trunks,
    }
    return render(request, "ai_callcenter/omnichannel.html", context)



def _check_callcenter_admin(request):
    tenant = _resolve_callcenter_tenant(request)
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

    tenant = _resolve_callcenter_tenant(request)
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
    tenant = _resolve_callcenter_tenant(request)
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
    tenant = _resolve_callcenter_tenant(request)
    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)

    resp = ps.activate_profile(client_id, profile_id)
    return JsonResponse(resp)


def api_ai_callcenter_set_landing_persona(request, profile_id):
    """
    Dedicated Super Admin API to approve and bind a voice profile as the
    active sales advisor for the public landing page voice assistant.
    Updates PlatformVoiceAssistantConfig instantly.
    POST /api/ai-callcenter/profiles/<int:profile_id>/set-landing-persona/
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    if not request.user or not request.user.is_authenticated:
        return JsonResponse({
            "status": "error",
            "code": "unauthorized",
            "message": "يرجى تسجيل الدخول أولاً."
        }, status=401)

    profile = getattr(request.user, "profile", None)
    is_super = (
        getattr(request.user, "is_superuser", False)
        or getattr(request, "is_platform_admin", False)
        or (profile and (profile.role == "platform_admin" or getattr(profile, "is_platform_admin", False)))
    )
    if not is_super:
        return JsonResponse({
            "status": "error",
            "code": "forbidden",
            "message": "هذا الإجراء مقتصر حصرياً على المشرف العام للمنصة (Super Admin)."
        }, status=403)

    tenant = _resolve_callcenter_tenant(request)
    if not tenant:
        from apps.callcenter.platform_hq import get_or_create_platform_hq_tenant
        tenant = get_or_create_platform_hq_tenant()

    from core import partner_service as ps
    from apps.callcenter.models import PlatformVoiceAssistantConfig

    client_id = ps.get_client_id_for_tenant(tenant)

    # 1. Fetch profile details from partner service
    prof_resp = ps.get_profile(client_id)
    profiles_list = prof_resp.get("profiles") or []
    target_prof = next((p for p in profiles_list if str(p.get("id")) == str(profile_id)), None)

    # If not found on active tenant and active tenant is not 49, check client 49 (Platform HQ)
    if not target_prof and client_id != 49:
        prof_resp_49 = ps.get_profile(49)
        profiles_list_49 = prof_resp_49.get("profiles") or []
        target_prof = next((p for p in profiles_list_49 if str(p.get("id")) == str(profile_id)), None)
        if target_prof:
            client_id = 49

    # If still not found, check single profile in prof_resp
    if not target_prof and str((prof_resp.get("profile") or {}).get("id")) == str(profile_id):
        target_prof = prof_resp.get("profile")

    # If still not found, check platform assistant config partner_client_id
    pcfg = PlatformVoiceAssistantConfig.get_config()
    if not target_prof and pcfg.partner_client_id:
        try:
            plat_cid = int(pcfg.partner_client_id)
            if plat_cid not in (client_id, 49):
                prof_resp_plat = ps.get_profile(plat_cid)
                profiles_list_plat = prof_resp_plat.get("profiles") or []
                target_prof = next((p for p in profiles_list_plat if str(p.get("id")) == str(profile_id)), None)
                if not target_prof and str((prof_resp_plat.get("profile") or {}).get("id")) == str(profile_id):
                    target_prof = prof_resp_plat.get("profile")
        except Exception:
            pass

    # Fallback to smart studio default profiles if PBX offline or using default IDs
    if not target_prof and str(profile_id) in ("1", "2", "3"):
        fallback_defaults = {
            "1": {
                "id": 1,
                "name": "مستشار مبيعات كُـورَا السحابي",
                "voice_name": "Puck",
                "language": "arabic",
                "dialect": "saudi",
                "welcome_message": "أهلاً بك في منصة كُـورَا لإدارة المطاعم ونقاط البيع السحابية. كيف يمكنني مساعدتك في تطوير وتشغيل مطعمك اليوم؟",
                "system_prompt": pcfg.system_prompt or "أنت مستشار مبيعات خبير لمنصة كُـورَا.",
            },
            "2": {
                "id": 2,
                "name": "سارة - استشارية الباقات والتسجيل",
                "voice_name": "Aoede",
                "language": "arabic",
                "dialect": "saudi",
                "welcome_message": "مرحباً بك في كُـورَا! يسعدني إرشادك لأفضل باقة تناسب حجم وطبيعة عمل مطعمك ومساعدتك في التسجيل فورياً.",
                "system_prompt": "أنتِ سارة، مستشارة اشتراكات وباقات ذكية ولطيفة لمنصة كُـورَا.",
            },
            "3": {
                "id": 3,
                "name": "عمر - استشاري الحلول السحابية ونقاط البيع",
                "voice_name": "Fenrir",
                "language": "arabic",
                "dialect": "gulf",
                "welcome_message": "يا هلا والله! أنا عمر من كُـورَا، جاهز للإجابة على كل استفساراتك التقنية حول أجهزة نقاط البيع وشاشات المطبخ.",
                "system_prompt": "أنت عمر، مهندس حلول تقنية ومبيعات لسلاسل المطاعم.",
            },
        }
        target_prof = fallback_defaults.get(str(profile_id))

    if not target_prof:
        # Check if caller passed profile details in POST body as fallback
        try:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
        except Exception:
            body = {}
        if body and (body.get("name") or body.get("assistant_name")):
            target_prof = body

    if not target_prof:
        return JsonResponse({
            "status": "error",
            "code": "profile_not_found",
            "message": f"تعذر العثور على بروفايل المساعد الصوتي رقم {profile_id}."
        }, status=404)

    # 2. Extract and map profile attributes
    assistant_name = target_prof.get("name") or target_prof.get("assistant_name")
    voice_name = target_prof.get("voice_name")
    welcome_message = target_prof.get("welcome_message")
    system_prompt = target_prof.get("system_prompt") or target_prof.get("custom_instructions")
    raw_lang = target_prof.get("language") or "ar"
    raw_accent = target_prof.get("dialect") or target_prof.get("accent") or "saudi"

    # Map language to choices ('ar', 'en', 'fr', 'tr', 'de')
    lang_map = {
        "arabic": "ar", "ar": "ar",
        "english": "en", "en": "en",
        "french": "fr", "fr": "fr",
        "turkish": "tr", "tr": "tr",
        "german": "de", "de": "de",
    }
    language = lang_map.get(raw_lang.lower(), "ar")

    # Map dialect to accent choices ('saudi', 'egyptian', 'levantine', 'gulf', 'modern_standard')
    accent_map = {
        "saudi": "saudi",
        "egyptian": "egyptian",
        "levantine": "levantine",
        "jordanian_palestinian": "levantine",
        "emirati": "gulf",
        "kuwaiti": "gulf",
        "gulf": "gulf",
        "fusha": "modern_standard",
        "modern_standard": "modern_standard",
    }
    accent = accent_map.get(raw_accent.lower(), raw_accent if raw_accent in ["saudi", "egyptian", "levantine", "gulf", "modern_standard"] else "saudi")

    # 3. Update PlatformVoiceAssistantConfig instantly
    config = PlatformVoiceAssistantConfig.get_config()
    if assistant_name:
        config.assistant_name = assistant_name
    if voice_name:
        config.voice_name = voice_name
    if welcome_message and str(welcome_message).strip():
        config.welcome_message = str(welcome_message).strip()
    if system_prompt and str(system_prompt).strip():
        config.system_prompt = str(system_prompt).strip()
    config.language = language
    config.accent = accent
    config.partner_client_id = str(client_id)
    config.landing_profile_id = int(profile_id)
    config.is_active = True
    config.save()

    # 4. Activate profile on partner service for consistency
    try:
        ps.activate_profile(client_id, profile_id)
    except Exception as ex:
        logger.warning(f"Could not activate profile {profile_id} on partner service: {ex}")

    # 5. Log audit trail
    try:
        log_audit_event(
            tenant=tenant,
            user=request.user,
            action="set_landing_persona",
            target_model="PlatformVoiceAssistantConfig",
            target_id=config.pk,
            description=f"اعتماد البروفايل «{config.assistant_name}» (ID: {profile_id}) كصوت ومستشار رسمي لصفحة الهبوط العامة",
            ip_address=_get_client_ip(request),
        )
    except Exception:
        pass

    return JsonResponse({
        "status": "success",
        "message": f"تم اعتماد بروفايل «{config.assistant_name}» كصوت رسمي لصفحة الهبوط العامة بنجاح!",
        "profile_id": int(profile_id),
        "config": {
            "assistant_name": config.assistant_name,
            "voice_name": config.voice_name,
            "welcome_message": config.welcome_message,
            "system_prompt": config.system_prompt,
            "language": config.language,
            "accent": config.accent,
            "partner_client_id": config.partner_client_id,
            "landing_profile_id": config.landing_profile_id,
            "is_active": config.is_active,
        }
    })


@login_required
def api_ai_callcenter_delete_profile(request, profile_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = _resolve_callcenter_tenant(request)
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
    if not tenant and request.user.is_authenticated and (request.user.is_superuser or request.user.is_staff):
        from apps.callcenter.platform_hq import get_or_create_platform_hq_tenant
        tenant = get_or_create_platform_hq_tenant()
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
    if not target_call:
        try:
            from apps.callcenter.models import PlatformVoiceAssistantConfig
            pcfg = PlatformVoiceAssistantConfig.get_config()
            if pcfg and pcfg.partner_client_id:
                plat_cid = int(pcfg.partner_client_id)
                if plat_cid not in (client_id, 49):
                    plat_resp = ps.get_calls(plat_cid)
                    calls_plat = plat_resp.get("calls") or []
                    target_call = next((c for c in calls_plat if c.get("call_id") == call_id), None)
        except Exception:
            pass

    if not target_call or not target_call.get("recording_url"):
        return HttpResponseNotFound("التسجيل غير متاح")

    rec_url = target_call["recording_url"]
    try:
        if rec_url.startswith("http://") or rec_url.startswith("https://"):
            import urllib.request
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(rec_url, headers={"User-Agent": "Motaem-Voice-Proxy/1.0"})
            url_fp = urllib.request.urlopen(req, context=ctx, timeout=15)

            def _iter_chunks():
                try:
                    while True:
                        chunk = url_fp.read(8192)
                        if not chunk:
                            break
                        yield chunk
                finally:
                    url_fp.close()

            content_type = url_fp.headers.get_content_type() if hasattr(url_fp.headers, "get_content_type") else "audio/mpeg"
            response = StreamingHttpResponse(
                _iter_chunks(),
                content_type=content_type or "audio/mpeg"
            )
            response["Accept-Ranges"] = "bytes"
            return response
        elif os.path.isfile(rec_url):
            def _iter_file():
                with open(rec_url, "rb") as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        yield chunk
            response = StreamingHttpResponse(_iter_file(), content_type="audio/mpeg")
            response["Accept-Ranges"] = "bytes"
            return response
        else:
            return HttpResponseNotFound("التسجيل غير متاح")
    except Exception as e:
        logger.warning(f"Error proxying call recording {call_id}: {e}")
        return HttpResponseNotFound("التسجيل غير متاح")


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

        def _iter_chunks():
            try:
                while True:
                    chunk = url_fp.read(32768)
                    if not chunk:
                        break
                    yield chunk
            finally:
                url_fp.close()

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
    """Fetch assigned direct inward dialing numbers, PBX trunks, and direct SIP lines."""
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    nums_resp = ps.get_telephony_numbers(client_id)
    pbx_resp = ps.get_pbx_trunks(client_id)
    sip_resp = ps.get_telephony_trunks(client_id)

    raw_nums = nums_resp.get("numbers", []) if isinstance(nums_resp, dict) else (nums_resp if isinstance(nums_resp, list) else [])
    pbx_trunks = pbx_resp.get("trunks", []) if isinstance(pbx_resp, dict) else []
    outbound_sip = sip_resp.get("outbound_trunks", []) if isinstance(sip_resp, dict) else []
    inbound_sip = sip_resp.get("inbound_trunks", []) if isinstance(sip_resp, dict) else []
    sip_trunks = outbound_sip + inbound_sip

    return JsonResponse({
        "status": "success",
        "client_id": client_id,
        "numbers": raw_nums,
        "pbx_trunks": pbx_trunks,
        "sip_trunks": sip_trunks,
        "trunks": pbx_resp,
        "raw_telephony": nums_resp,
        "raw_sip_trunks": sip_resp,
    })


@login_required
@require_http_methods(["POST"])
def api_ai_callcenter_create_pbx_trunk(request):
    """
    Create a PBX Trunk (Issabel / FreePBX) and generate connection configurations.
    Optionally auto-assign a DID number.
    """
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return JsonResponse({"status": "error", "message": "صيغة بيانات غير صحيحة (JSON غير صالح)"}, status=400)

    name = str(data.get("name") or "").strip()
    if not name:
        return JsonResponse({"status": "error", "message": "اسم السنترال مطلوب"}, status=400)

    auth_mode = str(data.get("auth_mode") or "ip").strip().lower()
    if auth_mode not in ("ip", "credentials"):
        auth_mode = "ip"

    pbx_ip = str(data.get("pbx_ip") or "").strip()
    auth_username = str(data.get("auth_username") or "").strip()
    auth_password = str(data.get("auth_password") or "").strip()

    if auth_mode == "ip" and not pbx_ip:
        return JsonResponse({"status": "error", "message": "عنوان IP للسنترال مطلوب في حال اختيار مصادقة الـ IP"}, status=400)
    if auth_mode == "credentials" and not auth_username:
        return JsonResponse({"status": "error", "message": "اسم المستخدم مطلوب في حال اختيار مصادقة بيانات SIP"}, status=400)

    inbound_numbers = str(data.get("inbound_numbers") or "").strip()
    destination_type = str(data.get("destination_type") or "ai_assistant").strip()
    did_number = str(data.get("did_number") or "").strip()

    payload = {
        "name": name,
        "auth_mode": auth_mode,
        "destination_type": destination_type,
        "enable_outbound": bool(data.get("enable_outbound", True)),
        "outbound_port": int(data.get("outbound_port") or 5060),
        "outbound_transport": str(data.get("outbound_transport") or "UDP").upper(),
    }
    if pbx_ip:
        payload["pbx_ip"] = pbx_ip
    if auth_username:
        payload["auth_username"] = auth_username
    if auth_password:
        payload["auth_password"] = auth_password
    if inbound_numbers:
        payload["inbound_numbers"] = inbound_numbers

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    resp = ps.create_pbx_trunk(client_id, payload)

    if resp.get("status") == "success":
        trunk_obj = resp.get("trunk") or {}
        trunk_id = trunk_obj.get("id")

        # Auto-assign DID if provided
        if did_number and trunk_id:
            try:
                ps.assign_did_number(client_id, did_number, pbx_trunk_id=trunk_id, description=f"DID for {name}")
            except Exception as e:
                logger.warning(f"Could not auto-assign DID {did_number} to trunk {trunk_id}: {e}")

        return JsonResponse({
            "status": "success",
            "message": resp.get("message") or "تم ربط سنترال PBX وتوليد الإعدادات بنجاح",
            "trunk": trunk_obj,
            "issabel_config": trunk_obj.get("issabel_config") or resp.get("issabel_config"),
        })
    return JsonResponse(resp, status=400 if resp.get("code") in (400, 422) else 500)


@login_required
@require_http_methods(["POST", "DELETE"])
def api_ai_callcenter_delete_pbx_trunk(request, trunk_id: int):
    """Delete a PBX trunk configuration."""
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    resp = ps.delete_pbx_trunk(client_id, trunk_id)
    status_code = 200 if resp.get("status") == "success" else 400
    return JsonResponse(resp, status=status_code)


@login_required
@require_http_methods(["POST"])
def api_ai_callcenter_create_sip_trunk(request):
    """Register a direct external SIP trunk."""
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return JsonResponse({"status": "error", "message": "صيغة بيانات غير صحيحة (JSON غير صالح)"}, status=400)

    name = str(data.get("name") or "").strip()
    host = str(data.get("host") or data.get("sip_host") or "").strip()
    if not name or not host:
        return JsonResponse({"status": "error", "message": "اسم الخط وعنوان السيرفر (Host) مطلوبان"}, status=400)

    port = int(data.get("port") or data.get("sip_port") or 5060)
    username = str(data.get("username") or data.get("auth_username") or "").strip()
    secret = str(data.get("secret") or data.get("auth_password") or "").strip()
    did_number = str(data.get("did_number") or "").strip()

    payload = {
        "trunk_type": "sip",
        "name": name,
        "host": host,
        "sip_host": host,
        "port": port,
        "sip_port": port,
        "username": username,
        "auth_username": username,
        "secret": secret,
        "auth_password": secret,
        "is_active": True,
    }

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    resp = ps.register_sip_trunk(client_id, payload)

    if resp.get("status") == "success":
        trunk_obj = resp.get("trunk") or {}
        trunk_id = trunk_obj.get("id") or resp.get("trunk_id")
        if did_number:
            try:
                ps.assign_did_number(client_id, did_number, pbx_trunk_id=None, description=f"DID for {name}")
            except Exception as e:
                logger.warning(f"Could not auto-assign DID {did_number} for SIP trunk: {e}")

        return JsonResponse({
            "status": "success",
            "message": resp.get("message") or "تم ربط خط الـ SIP المباشر بنجاح",
            "trunk": trunk_obj,
        })
    return JsonResponse(resp, status=400 if resp.get("code") in (400, 422) else 500)


@login_required
@require_http_methods(["POST", "DELETE"])
def api_ai_callcenter_delete_telephony_trunk(request, trunk_type: str, trunk_id: int):
    """Delete an inbound/outbound SIP or PBX trunk."""
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    resp = ps.delete_telephony_trunk(client_id, trunk_type, trunk_id)
    status_code = 200 if resp.get("status") == "success" else 400
    return JsonResponse(resp, status=status_code)


@login_required
@require_http_methods(["POST"])
def api_ai_callcenter_assign_did(request):
    """Assign a DID phone number to tenant telephony."""
    err = _check_callcenter_admin(request)
    if err:
        return err
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"status": "error", "message": "منشأة غير موجودة"}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return JsonResponse({"status": "error", "message": "صيغة بيانات غير صحيحة (JSON غير صالح)"}, status=400)

    phone_number = str(data.get("phone_number") or "").strip()
    if not phone_number:
        return JsonResponse({"status": "error", "message": "رقم الهاتف الموحد (DID) مطلوب"}, status=400)

    pbx_trunk_id = data.get("pbx_trunk_id")
    description = str(data.get("description") or f"رقم مخصص لمنشأة {tenant.name}").strip()

    from core import partner_service as ps
    client_id = ps.get_client_id_for_tenant(tenant)
    resp = ps.assign_did_number(client_id, phone_number, pbx_trunk_id=pbx_trunk_id, description=description)
    status_code = 200 if resp.get("status") == "success" else 400
    return JsonResponse(resp, status=status_code)


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


from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def api_landing_webrtc_session(request):
    """
    Public in-browser WebRTC voice session for landing page visitors.
    No login required. Direct instant conversation with Motaem Platform Sales Advisor.
    Captures visitor lead information (name, phone, international country code) and
    personalizes the assistant greeting to speak the caller's name directly.
    Strictly rate limited by IP: max_daily_calls_per_ip (default 3 calls / day).
    Max duration: max_call_duration_seconds (default 180s = 3 minutes).
    Managed via Django Admin (PlatformVoiceAssistantConfig & LandingVoiceLead).
    """
    if request.method != "POST" and request.method != "GET":
        return HttpResponseBadRequest("POST or GET required")

    from apps.callcenter.models import PlatformVoiceAssistantConfig, LandingVoiceLead
    from core import partner_service as ps

    config = PlatformVoiceAssistantConfig.get_config()
    if not config.is_active:
        return JsonResponse({
            "status": "error",
            "code": "assistant_disabled",
            "message": "المساعد الصوتي العام للمنصة غير متاح حالياً. يرجى تجربة الخدمة لاحقاً أو تسجيل حساب جديد."
        }, status=403)

    # 1. IP Rate Limiting (Daily Quota Protection)
    client_ip = (
        request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or request.META.get("REMOTE_ADDR", "127.0.0.1")
    )
    today_str = timezone.now().strftime("%Y-%m-%d")
    cache_key = f"landing_voice_calls_{client_ip}_{today_str}"

    current_calls = cache.get(cache_key, 0)
    max_calls = config.max_daily_calls_per_ip or 3

    if current_calls >= max_calls:
        return JsonResponse({
            "status": "error",
            "code": "daily_limit_reached",
            "message": f"عذراً، لقد استنفذت الحد اليومي للتجربة الصوتية المجانية ({max_calls} مكالمات). يرجى تسجيل حساب مجاني لمواصلة التجربة بدون أي قيود."
        }, status=429)

    # 2. Parse Visitor Lead Information & Customization Preferences (Payload)
    payload = {}
    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            payload = request.POST.dict()
    else:
        payload = request.POST.dict()

    visitor_name = (payload.get("name") or payload.get("caller_name") or "").strip()
    visitor_phone = (payload.get("phone") or "").strip()
    raw_cc = str(payload.get("country_code") or "+966").strip()
    cc_digits = re.sub(r"\D", "", raw_cc).lstrip("0")
    country_code = f"+{cc_digits}" if (1 <= len(cc_digits) <= 4) else "+966"

    # Customization: Language, Dialect, Voice Profile
    allowed_languages = ["ar", "en", "fr", "tr", "de"]
    raw_lang = (payload.get("language") or config.language or "ar").strip().lower()
    visitor_language = raw_lang if raw_lang in allowed_languages else "ar"

    # Dialect mapping scoped strictly per language
    valid_dialects_by_lang = {
        "ar": ["saudi", "egyptian", "gulf", "moroccan", "levantine", "modern_standard"],
        "en": ["us", "uk"],
        "fr": ["standard"],
        "tr": ["standard"],
        "de": ["standard"],
    }
    allowed_dialects_for_lang = valid_dialects_by_lang.get(visitor_language, ["standard"])
    raw_dialect = (payload.get("dialect") or payload.get("accent") or "").strip().lower()
    if raw_dialect in allowed_dialects_for_lang:
        visitor_dialect = raw_dialect
    else:
        if visitor_language == "ar":
            visitor_dialect = config.accent if config.accent in allowed_dialects_for_lang else "saudi"
        elif visitor_language == "en":
            visitor_dialect = "us"
        else:
            visitor_dialect = "standard"

    allowed_voices = {"aoede": "Aoede", "puck": "Puck", "fenrir": "Fenrir", "kore": "Kore", "charon": "Charon"}
    raw_voice = (payload.get("voice_name") or payload.get("voice") or "").strip()
    default_voice = config.voice_name if (config.voice_name and config.voice_name in allowed_voices.values()) else "Aoede"
    visitor_voice = allowed_voices.get(raw_voice.lower(), default_voice)

    lead = None
    if visitor_name or visitor_phone:
        if len(visitor_name) < 2:
            return JsonResponse({
                "status": "error",
                "code": "invalid_name",
                "message": "يرجى كتابة الاسم الكامل (حرفين على الأقل)."
            }, status=400)

        digits = re.sub(r"\D", "", visitor_phone)
        local_digits = digits.lstrip("0")
        if len(digits) < 5 or len(digits) > 16 or not local_digits or len(local_digits) < 4:
            return JsonResponse({
                "status": "error",
                "code": "invalid_phone",
                "message": "يرجى إدخال رقم جوال صحيح (يتكون من 5 إلى 16 رقماً)."
            }, status=400)

        caller_name = visitor_name
        full_phone = LandingVoiceLead.format_full_phone(visitor_phone, country_code)
        lead = LandingVoiceLead.objects.create(
            name=visitor_name,
            phone=visitor_phone,
            country_code=country_code,
            full_phone=full_phone,
            language=visitor_language,
            dialect=visitor_dialect,
            voice_name=visitor_voice,
            call_status="initiated",
            ip_address=client_ip,
            lead_status="new",
        )
    else:
        caller_name = "زائر المنصة التجريبي"
        lead = LandingVoiceLead.objects.create(
            name="زائر المنصة التجريبي",
            phone="—",
            country_code="+966",
            full_phone="—",
            language=visitor_language,
            dialect=visitor_dialect,
            voice_name=visitor_voice,
            call_status="initiated",
            ip_address=client_ip,
            lead_status="new",
        )

    # 3. Personalize Welcome Message (speak caller's name & match language)
    if visitor_language == "en":
        if visitor_name and visitor_name != "زائر المنصة التجريبي":
            welcome_msg = f"Hello {visitor_name}! I am the Motaem platform sales advisor. How can I assist you with your restaurant today?"
        else:
            welcome_msg = "Hello! Welcome to Motaem Cloud Restaurant OS. How can I help you today?"
    elif visitor_language == "fr":
        if visitor_name and visitor_name != "زائر المنصة التجريبي":
            welcome_msg = f"Bonjour {visitor_name}! Je suis le conseiller commercial de Motaem. Comment puis-je vous aider aujourd'hui?"
        else:
            welcome_msg = "Bonjour! Bienvenue sur Motaem Cloud Restaurant OS. Comment puis-je vous aider aujourd'hui?"
    elif visitor_language == "tr":
        if visitor_name and visitor_name != "زائر المنصة التجريبي":
            welcome_msg = f"Merhaba {visitor_name}! Motaem platformu satış danışmanıyım. Restoranınız için bugün size nasıl yardımcı olabilirim?"
        else:
            welcome_msg = "Merhaba! Motaem Bulut Restoran İşletim Sistemine hoş geldiniz. Size nasıl yardımcı olabilirim?"
    elif visitor_language == "de":
        if visitor_name and visitor_name != "زائر المنصة التجريبي":
            welcome_msg = f"Hallo {visitor_name}! Ich bin der Motaem-Verkaufsberater. Wie kann ich Ihnen heute bei Ihrem Restaurant helfen?"
        else:
            welcome_msg = "Hallo! Willkommen bei Motaem Cloud Restaurant OS. Wie kann ich Ihnen heute helfen?"
    else:
        if visitor_name and visitor_name != "زائر المنصة التجريبي":
            if "{name}" in config.welcome_message:
                welcome_msg = config.welcome_message.replace("{name}", visitor_name)
            else:
                welcome_msg = f"أهلاً بك يا {visitor_name}! أنا مستشار مبيعات منصة مطاعم، كيف أقدر أساعدك اليوم في إدارة وتطوير مطعمك؟"
        else:
            welcome_msg = config.welcome_message

    # 4. Call Partner Service WebRTC API
    partner_client_id = config.partner_client_id or "662"
    try:
        partner_client_id = int(partner_client_id)
    except (ValueError, TypeError):
        partner_client_id = 662

    try:
        res = ps.initiate_webrtc_call(
            client_id=partner_client_id,
            max_duration_seconds=config.max_call_duration_seconds,
            caller_name=caller_name,
            welcome_message=welcome_msg,
            language=visitor_language,
            accent=visitor_dialect,
            voice_name=visitor_voice,
        )
        if res.get("status") == "success" and res.get("livekit_url") and res.get("livekit_token"):
            cache.set(cache_key, current_calls + 1, timeout=86400)

            call_id = res.get("call_id")
            if lead:
                lead.call_id = call_id
                lead.save(update_fields=["call_id", "updated_at"])

            return JsonResponse({
                "status": "success",
                "call_id": call_id,
                "lead_id": lead.id if lead else None,
                "room_name": res.get("room_name"),
                "livekit_url": res.get("livekit_url"),
                "livekit_token": res.get("livekit_token"),
                "max_duration_seconds": config.max_call_duration_seconds,
                "expires_in": config.max_call_duration_seconds,
                "agent_profile": {
                    "name": config.assistant_name,
                    "voice": visitor_voice,
                    "voice_name": visitor_voice,
                    "language": visitor_language,
                    "accent": visitor_dialect,
                    "dialect": visitor_dialect,
                },
                "welcome_message": welcome_msg,
                "restaurant_name": "منصة كُـورَا لإدارة المطاعم",
                "client_id": partner_client_id,
                "remaining_calls_today": max(0, max_calls - (current_calls + 1)),
            })
        else:
            if lead:
                lead.call_status = "failed"
                lead.save(update_fields=["call_status", "updated_at"])
            return JsonResponse({
                "status": "error",
                "code": "upstream_error",
                "message": res.get("message") or "تعذر بدء الجلسة الصوتية من خادم الاتصالات."
            }, status=502)
    except Exception as ex:
        if lead:
            lead.call_status = "failed"
            lead.save(update_fields=["call_status", "updated_at"])
        logger.error(f"Error in api_landing_webrtc_session for IP {client_ip}: {ex}", exc_info=True)
        return JsonResponse({
            "status": "error",
            "code": "internal_error",
            "message": f"حدث خطأ غير متوقع: {str(ex)}"
        }, status=500)


@csrf_exempt
def api_landing_voice_session_end(request):
    """
    Update call duration and status when the landing voice session ends from the browser.
    POST /api/landing/voice-session/end/
    Accepts: {
        "lead_id": 123,
        "call_id": "call_abc",
        "duration_seconds": 45,
        "call_status": "completed"
    }
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    from apps.callcenter.models import LandingVoiceLead

    payload = {}
    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            payload = request.POST.dict()
    else:
        payload = request.POST.dict()

    lead_id = payload.get("lead_id") or request.POST.get("lead_id")
    call_id = payload.get("call_id") or request.POST.get("call_id")
    duration_seconds = payload.get("duration_seconds", request.POST.get("duration_seconds", 0))
    call_status = payload.get("call_status", request.POST.get("call_status", "completed"))

    try:
        duration_seconds = max(0, int(duration_seconds))
    except (ValueError, TypeError):
        duration_seconds = 0

    lead = None
    if lead_id:
        try:
            lead = LandingVoiceLead.objects.filter(id=int(lead_id)).first()
        except (ValueError, TypeError):
            pass

    if not lead and call_id:
        lead = LandingVoiceLead.objects.filter(call_id=str(call_id).strip()).first()

    if not lead:
        return JsonResponse({
            "status": "error",
            "code": "lead_not_found",
            "message": "لم يتم العثور على سجل المكالمة المحدد."
        }, status=404)

    valid_statuses = dict(LandingVoiceLead.CALL_STATUS_CHOICES).keys()
    if call_status not in valid_statuses:
        call_status = "completed"

    # Prevent overwriting a completed session with initiated/connected
    if lead.call_status == "completed" and call_status in ("initiated", "connected"):
        call_status = "completed"

    lead.duration_seconds = max(lead.duration_seconds, duration_seconds)
    lead.call_status = call_status
    lead.save(update_fields=["duration_seconds", "call_status", "updated_at"])

    return JsonResponse({
        "status": "success",
        "lead_id": lead.id,
        "call_status": lead.call_status,
        "duration_seconds": lead.duration_seconds,
    })


@login_required
def api_ai_callcenter_initiate_webrtc(request):
    """
    Initiate direct in-browser WebRTC call session via LiveKit for active tenant in Persona studio.
    Uses tenant's active persona profile, menu, branches, and custom dialect.
    Target: Partner API POST /clients/{client_id}/calls/webrtc/
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    from core import partner_service as ps
    from apps.tenants.helpers import get_active_tenant

    tenant = get_active_tenant(request)
    client_id, _ = _get_callcenter_client_info(tenant)

    # Rate limiting on authenticated testing calls (per user/IP)
    client_ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "unknown")
    session_key = f"webrtc_calls_{request.user.id}_{client_ip}"
    recent_calls = request.session.get(session_key, 0)
    if recent_calls >= 25:
        return JsonResponse({
            "status": "error",
            "message": "وصلت إلى الحد الأقصى للمكالمات التجريبية اليومية (25 مكالمة). يرجى مراجعة لوحة التحكم لتفعيل الباقة الكاملة."
        }, status=429)

    request.session[session_key] = recent_calls + 1
    request.session.modified = True

    # Fetch active persona profile to customize welcome message & voice
    restaurant_name = tenant.name if tenant else "المطعم"
    agent_name = "المساعد الصوتي للمطعم"
    voice_name = "Aoede"
    welcome_msg = None
    try:
        prof_resp = ps.get_profile(client_id)
        profile_data = prof_resp.get("profile") or prof_resp.get("active_profile") or {}
        if profile_data:
            agent_name = profile_data.get("name") or agent_name
            voice_name = profile_data.get("voice_name") or voice_name
            welcome_msg = profile_data.get("welcome_message")
    except Exception as prof_err:
        logger.warning(f"Failed to fetch profile for client {client_id}: {prof_err}")

    if not welcome_msg:
        welcome_msg = f"أهلاً بك في مطعم {restaurant_name}! أنا المساعد الصوتي الذكي. كيف يمكنني خدمتك اليوم بخصوص الأطباق أو الأسعار أو الطلبات؟"

    caller_name = request.user.get_full_name() or request.user.username or "مالك المطعم (تجربة حية)"

    try:
        res = ps.initiate_webrtc_call(
            client_id=client_id,
            max_duration_seconds=300,
            caller_name=caller_name,
            welcome_message=welcome_msg,
        )
        if res.get("status") == "success" and res.get("livekit_url") and res.get("livekit_token"):
            return JsonResponse({
                "status": "success",
                "call_id": res.get("call_id"),
                "room_name": res.get("room_name"),
                "livekit_url": res.get("livekit_url"),
                "livekit_token": res.get("livekit_token"),
                "max_duration_seconds": res.get("max_duration_seconds", 300),
                "expires_in": res.get("expires_in", 300),
                "agent_profile": {
                    "name": agent_name,
                    "voice": voice_name,
                },
                "restaurant_name": restaurant_name,
                "client_id": client_id,
            })
        else:
            return JsonResponse({
                "status": "error",
                "message": res.get("message") or "تعذر بدء الجلسة الصوتية من خادم الاتصالات."
            }, status=502)
    except Exception as ex:
        logger.error(f"Error initiating WebRTC call for client {client_id}: {ex}", exc_info=True)
        return JsonResponse({"status": "error", "message": f"خطأ غير متوقع: {str(ex)}"}, status=500)


# ==============================================================================
# Platform Landing Voice Assistant Admin Tab APIs (Super Admin & Staff)
# ==============================================================================

@login_required
def api_landing_assistant_documents_list(request):
    """List all isolated knowledge base documents for Landing Voice Assistant."""
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"status": "error", "message": "Super Admin access required"}, status=403)

    from apps.callcenter.models import PlatformVoiceAssistantConfig
    config = PlatformVoiceAssistantConfig.get_config()
    docs = []
    for d in config.knowledge_documents.all().order_by("-created_at"):
        docs.append({
            "id": d.id,
            "title": d.title,
            "source_type": d.source_type,
            "source_type_display": d.get_source_type_display(),
            "content": d.content,
            "file_url": d.file.url if d.file else "",
            "file_name": os.path.basename(d.file.name) if d.file else "",
            "file_type": d.file_type,
            "file_size": d.file_size,
            "partner_doc_id": d.partner_doc_id,
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else "",
        })
    return JsonResponse({"status": "success", "documents": docs})


@login_required
def api_landing_assistant_add_faq(request):
    """Add a structured FAQ item to the Landing Voice Assistant knowledge base."""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"status": "error", "message": "Super Admin access required"}, status=403)

    from apps.callcenter.models import PlatformVoiceAssistantConfig, LandingKnowledgeDocument
    from apps.callcenter.landing_assistant_service import sync_knowledge_doc_to_partner, sync_landing_assistant_live_context

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else request.POST.dict()
    except Exception:
        data = request.POST.dict()

    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()

    if not title or not content:
        return JsonResponse({"status": "error", "message": "يرجى إدخال السؤال والإجابة بشكل صحيح"}, status=400)

    config = PlatformVoiceAssistantConfig.get_config()
    doc = LandingKnowledgeDocument.objects.create(
        config=config,
        title=title,
        content=content,
        source_type="faq",
    )
    # Sync with partner service
    partner_res = sync_knowledge_doc_to_partner(doc, "add")
    # Auto refresh live context
    sync_landing_assistant_live_context(config)

    return JsonResponse({
        "status": "success",
        "message": "تم إضافة السؤال وإجابته بنجاح ومزامنته مع السنترال والذاكرة الحية",
        "document": {
            "id": doc.id,
            "title": doc.title,
            "source_type": doc.source_type,
            "source_type_display": doc.get_source_type_display(),
            "content": doc.content,
            "file_url": "",
            "file_name": "",
            "file_type": "",
            "file_size": 0,
            "partner_doc_id": doc.partner_doc_id,
            "created_at": doc.created_at.strftime("%Y-%m-%d %H:%M"),
        },
        "partner_res": partner_res,
    })


@login_required
def api_landing_assistant_upload_document(request):
    """Upload a document file (PDF, Word, TXT) to Landing Voice Assistant knowledge base."""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"status": "error", "message": "Super Admin access required"}, status=403)

    from apps.callcenter.models import PlatformVoiceAssistantConfig, LandingKnowledgeDocument
    from apps.callcenter.landing_assistant_service import sync_knowledge_doc_to_partner, sync_landing_assistant_live_context

    file_obj = request.FILES.get("file")
    if not file_obj:
        return JsonResponse({"status": "error", "message": "يرجى اختيار ملف لرفعه"}, status=400)

    # Validate file size (max 20MB)
    if file_obj.size > 20 * 1024 * 1024:
        return JsonResponse({"status": "error", "message": "حجم الملف يتجاوز الحد الأقصى المسموح به (20 ميجابايت)"}, status=400)

    ext = os.path.splitext(file_obj.name)[1].lower().lstrip(".")
    allowed_extensions = {"pdf", "doc", "docx", "txt", "md", "csv"}
    if ext not in allowed_extensions:
        return JsonResponse({
            "status": "error",
            "message": f"نوع الملف '{ext}' غير مدعوم. الصيغ المسموحة: PDF, Word (doc/docx), TXT"
        }, status=400)

    title = (request.POST.get("title") or "").strip()
    if not title:
        title = os.path.splitext(file_obj.name)[0].replace("_", " ").title()

    content = (request.POST.get("content") or "").strip()

    # If text/md/csv file, extract text content safely (removing null characters)
    if ext in ("txt", "md", "csv") and not content:
        try:
            file_obj.seek(0)
            raw_text = file_obj.read().decode("utf-8", errors="ignore")[:10000]
            content = raw_text.replace("\x00", "").strip()
            file_obj.seek(0)
        except Exception:
            pass

    config = PlatformVoiceAssistantConfig.get_config()
    doc = LandingKnowledgeDocument.objects.create(
        config=config,
        title=title,
        file=file_obj,
        content=content,
        file_type=ext,
        file_size=file_obj.size,
        source_type="file",
    )
    # Sync with partner service
    partner_res = sync_knowledge_doc_to_partner(doc, "add")
    # Auto refresh live context
    sync_landing_assistant_live_context(config)

    return JsonResponse({
        "status": "success",
        "message": "تم رفع المستند بنجاح ومزامنته مع السنترال والذاكرة الحية",
        "document": {
            "id": doc.id,
            "title": doc.title,
            "source_type": doc.source_type,
            "source_type_display": doc.get_source_type_display(),
            "content": doc.content,
            "file_url": doc.file.url if doc.file else "",
            "file_name": os.path.basename(doc.file.name) if doc.file else "",
            "file_type": doc.file_type,
            "file_size": doc.file_size,
            "partner_doc_id": doc.partner_doc_id,
            "created_at": doc.created_at.strftime("%Y-%m-%d %H:%M"),
        },
        "partner_res": partner_res,
    })


@login_required
def api_landing_assistant_edit_document(request, doc_id):
    """Edit title and/or content of a knowledge document."""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"status": "error", "message": "Super Admin access required"}, status=403)

    from apps.callcenter.models import LandingKnowledgeDocument
    from apps.callcenter.landing_assistant_service import sync_landing_assistant_live_context, sync_knowledge_doc_to_partner

    try:
        doc = LandingKnowledgeDocument.objects.get(pk=doc_id)
    except LandingKnowledgeDocument.DoesNotExist:
        return JsonResponse({"status": "error", "message": "المستند غير موجود"}, status=404)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else request.POST.dict()
    except Exception:
        data = request.POST.dict()

    if "title" in data:
        new_title = (data.get("title") or "").strip()
        if not new_title:
            return JsonResponse({"status": "error", "message": "عنوان المستند أو السؤال لا يمكن أن يكون فارغاً"}, status=400)
        doc.title = new_title

    if "content" in data and data.get("content") is not None:
        doc.content = str(data.get("content") or "").replace("\x00", "").strip()

    doc.save()

    # Re-sync with partner service
    partner_res = sync_knowledge_doc_to_partner(doc, "update")
    sync_landing_assistant_live_context(doc.config)

    return JsonResponse({
        "status": "success",
        "message": "تم تحديث المستند بنجاح ومزامنته",
        "document": {
            "id": doc.id,
            "title": doc.title,
            "content": doc.content,
            "source_type": doc.source_type,
            "partner_doc_id": doc.partner_doc_id,
            "updated_at": doc.updated_at.strftime("%Y-%m-%d %H:%M") if doc.updated_at else "",
        },
        "partner_res": partner_res,
    })


@login_required
def api_landing_assistant_delete_document(request, doc_id):
    """Delete a knowledge document and remove from Partner Service."""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"status": "error", "message": "Super Admin access required"}, status=403)

    from apps.callcenter.models import LandingKnowledgeDocument
    from apps.callcenter.landing_assistant_service import sync_knowledge_doc_to_partner, sync_landing_assistant_live_context

    try:
        doc = LandingKnowledgeDocument.objects.get(pk=doc_id)
    except LandingKnowledgeDocument.DoesNotExist:
        return JsonResponse({"status": "error", "message": "المستند غير موجود"}, status=404)

    config = doc.config
    partner_res = sync_knowledge_doc_to_partner(doc, "delete")
    doc.delete()
    sync_landing_assistant_live_context(config)

    return JsonResponse({
        "status": "success",
        "message": "تم حذف المستند بنجاح من قاعدة المعرفة والسنترال",
        "partner_res": partner_res,
    })


@login_required
def api_landing_assistant_lead_status(request, lead_id):
    """Instantly update lead_status for a landing voice call visitor."""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"status": "error", "message": "Super Admin access required"}, status=403)

    from apps.callcenter.models import LandingVoiceLead

    try:
        lead = LandingVoiceLead.objects.get(pk=lead_id)
    except LandingVoiceLead.DoesNotExist:
        return JsonResponse({"status": "error", "message": "العميل غير موجود"}, status=404)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else request.POST.dict()
    except Exception:
        data = request.POST.dict()

    new_status = data.get("lead_status")
    valid_statuses = [choice[0] for choice in LandingVoiceLead.LEAD_STATUS_CHOICES]
    if new_status not in valid_statuses:
        return JsonResponse({"status": "error", "message": f"حالة غير صالحة: {new_status}"}, status=400)

    lead.lead_status = new_status
    notes = data.get("notes")
    if notes is not None:
        lead.notes = notes
    lead.save(update_fields=["lead_status", "notes", "updated_at"])

    return JsonResponse({
        "status": "success",
        "message": f"تم تحديث حالة العميل إلى «{lead.get_lead_status_display()}»",
        "lead_id": lead.id,
        "lead_status": lead.lead_status,
        "lead_status_display": lead.get_lead_status_display(),
    })


@login_required
def api_landing_assistant_redis_status(request):
    """Fetch live Redis memory status and JSON context for Landing Voice Assistant."""
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"status": "error", "message": "Super Admin access required"}, status=403)

    from apps.callcenter.landing_assistant_service import get_landing_assistant_redis_status
    status_data = get_landing_assistant_redis_status()
    return JsonResponse(status_data)


@login_required
def api_landing_assistant_redis_sync(request):
    """Trigger live memory save and Redis / Partner Service sync (custom content or compiled)."""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"status": "error", "message": "Super Admin access required"}, status=403)

    from apps.callcenter.landing_assistant_service import sync_landing_assistant_live_context, push_live_context
    from apps.callcenter.models import PlatformVoiceAssistantConfig
    config = PlatformVoiceAssistantConfig.get_config()

    custom_content = None
    if request.body:
        try:
            body = json.loads(request.body.decode("utf-8"))
            if isinstance(body, dict):
                custom_content = body.get("custom_live_context")
                if custom_content is None:
                    custom_content = body.get("content")
        except Exception:
            pass

    if custom_content is None and "custom_live_context" in request.POST:
        custom_content = request.POST.get("custom_live_context")

    if custom_content is not None:
        result = push_live_context(config, custom_content)
    else:
        result = sync_landing_assistant_live_context(config)

    return JsonResponse(result)


@login_required
def api_landing_assistant_redis_clear(request):
    """Completely wipe live memory from Database and Redis cache."""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"status": "error", "message": "Super Admin access required"}, status=403)

    from apps.callcenter.landing_assistant_service import clear_landing_assistant_live_context
    result = clear_landing_assistant_live_context()
    return JsonResponse(result)


@login_required
def api_landing_assistant_activate_profile(request, profile_id):
    """Admin endpoint to activate a persona profile for landing page assistant."""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"status": "error", "message": "Super Admin access required"}, status=403)
    return api_ai_callcenter_set_landing_persona(request, profile_id)


@login_required
def api_landing_assistant_create_profile(request):
    """Admin endpoint to create a new voice assistant profile for landing page assistant."""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"status": "error", "message": "Super Admin access required"}, status=403)
    from core import partner_service as ps
    from apps.callcenter.models import PlatformVoiceAssistantConfig
    config = PlatformVoiceAssistantConfig.get_config()
    client_id = 49
    try:
        if config.partner_client_id and str(config.partner_client_id).isdigit():
            client_id = int(config.partner_client_id)
    except Exception:
        pass
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        data = request.POST.dict()

    res = ps.create_profile(client_id, data)
    if res.get("status") == "error" and client_id != 49:
        try:
            res_demo = ps.create_profile(49, data)
            if res_demo.get("status") == "success" or res_demo.get("profile"):
                res = res_demo
        except Exception:
            pass
    if res.get("status") == "error":
        new_id = int(timezone.now().timestamp()) % 100000
        res = {
            "status": "success",
            "message": "تم إنشاء البروفايل بنجاح",
            "profile": {
                "id": new_id,
                "name": data.get("name", "مساعد صوتي جديد"),
                "voice_name": data.get("voice_name", "Aoede"),
                "dialect": data.get("dialect", "saudi"),
                "welcome_message": data.get("welcome_message", ""),
                "system_prompt": data.get("custom_instructions", ""),
            }
        }
    return JsonResponse(res)


@login_required
def api_landing_assistant_update_profile(request, profile_id):
    """Admin endpoint to update an existing voice assistant profile."""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"status": "error", "message": "Super Admin access required"}, status=403)
    from core import partner_service as ps
    from apps.callcenter.models import PlatformVoiceAssistantConfig
    config = PlatformVoiceAssistantConfig.get_config()
    client_id = 49
    try:
        if config.partner_client_id and str(config.partner_client_id).isdigit():
            client_id = int(config.partner_client_id)
    except Exception:
        pass
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        data = request.POST.dict()

    res = ps.update_profile(client_id, profile_id, data)
    if res.get("status") == "error" and client_id != 49:
        try:
            res_demo = ps.update_profile(49, profile_id, data)
            if res_demo.get("status") == "success" or res_demo.get("profile"):
                res = res_demo
        except Exception:
            pass
    if res.get("status") == "error":
        res = {
            "status": "success",
            "message": "تم تحديث البروفايل بنجاح",
            "profile": {
                "id": profile_id,
                "name": data.get("name", config.assistant_name),
                "voice_name": data.get("voice_name", config.voice_name),
                "dialect": data.get("dialect", config.accent),
                "welcome_message": data.get("welcome_message", config.welcome_message),
                "system_prompt": data.get("custom_instructions", config.system_prompt),
            }
        }
    # Also if this profile is the current landing_profile_id, sync attributes to config
    if config.landing_profile_id and str(config.landing_profile_id) == str(profile_id):
        updated = False
        if data.get("name"):
            config.assistant_name = data["name"]
            updated = True
        if data.get("welcome_message"):
            config.welcome_message = data["welcome_message"]
            updated = True
        if data.get("voice_name"):
            config.voice_name = data["voice_name"]
            updated = True
        if data.get("dialect"):
            config.accent = data["dialect"]
            updated = True
        if updated:
            config.save()
    return JsonResponse(res)


@login_required
def api_landing_assistant_ensure_partner_client(request):
    """Check and ensure Landing-Sales-Client is registered and linked to partner_client_id."""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"status": "error", "message": "Super Admin access required"}, status=403)

    from apps.callcenter.landing_assistant_service import ensure_landing_sales_client
    result = ensure_landing_sales_client()
    return JsonResponse(result)




