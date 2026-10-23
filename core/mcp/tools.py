import os
import sys
import re
import json
import logging
import threading
from decimal import Decimal
from typing import Optional, List, Dict, Any, Union

from fastmcp import FastMCP
from django.db import models, transaction, IntegrityError, close_old_connections
from django.utils import timezone

from core.mcp.schemas import OrderItemInput
from core.mcp.middleware import _authenticate
from core.mcp.resolvers import (
    _clean_phone,
    _find_menu_item,
    _resolve_item_variant,
    _normalize_arabic_text,
    _normalize_digits,
    _parse_natural_order_text,
    _validate_delivery_address_completeness,
    _format_branch_closed_err,
    _resolve_delivery_coverage_and_branch,
)
from core.mcp.cart import (
    handle_cart_add_item,
    handle_cart_view,
    handle_cart_remove_item,
    handle_cart_clear,
)
from core.redis_mcp_cache import (
    cache_active_order,
    get_active_order_by_number,
    get_active_order_by_phone,
    remove_active_order,
    get_next_order_sequence,
    cart_get,
    cart_is_abandoned,
    cart_clear as redis_cart_clear,
)

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "Restaurant Call Center AI",
    instructions=(
        "أنت الموظف الافتراضي الذكي للكول سنتر الخاص بالمطعم. مهامك تشمل:\n"
        "1. الرد على العملاء بأسلوب مهذب واحترافي باللهجة المفهومة للعميل.\n"
        "2. استخدام lookup_customer للتعرف على العميل عند بدء الاتصال ومعرفة عنوانه المحفوظ وأوردراته الجارية.\n"
        "3. إدارة سلة المشتريات المؤقتة بالذكاء الاصطناعي عبر cart_add_item و cart_view لحفظ طلبات العميل تدريجياً أثناء المكالمة.\n"
        "4. فحص التغطية لطلبات التوصيل عبر check_delivery_coverage.\n"
        "5. معاينة الحساب بدقة عبر preview_order والتأكيد مع العميل قبل إنشاء الأوردر.\n"
        "6. إنشاء الأوردر في النظام عبر create_callcenter_order وتزويد العميل برقم الطلب.\n"
        "7. تتبع الأوردرات الجارية عبر track_order وإلغاء الأوردرات الجديدة عند رغبة العميل عبر cancel_order."
    )
)


# =====================================================================
# 1. Branch Management Tool
# =====================================================================

@mcp.tool
def get_branches(branch_id: Optional[int] = None, access_key: Optional[str] = None) -> Dict[str, Any]:
    """
    جلب قائمة الفروع المتاحة للمنشأة المرتبطة بمفتاح الـ API مع معلومات العملة والضريبة والتغطية.
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch

    qs = Branch.objects.filter(tenant=tenant, status="active")
    if key_obj.assigned_branch:
        qs = qs.filter(id=key_obj.assigned_branch_id)

    branches_data = []
    for b in qs:
        areas_count = b.delivery_areas.filter(is_active=True).count()
        branches_data.append({
            "id": b.id,
            "name": b.name,
            "city": b.city,
            "address": b.address,
            "phone": b.phone,
            "currency": b.currency,
            "currency_name": b.get_currency_name_ar(),
            "currency_symbol": b.get_currency_symbol_ar(),
            "tax_percentage": float(b.tax_percentage),
            "is_tax_inclusive": bool(b.is_tax_inclusive),
            "cancellation_window_minutes": int(getattr(b, "cancellation_window_minutes", 10)),
            "delivery_radius_km": float(b.delivery_radius_km),
            "delivery_areas_count": areas_count,
        })

    key_obj.record_usage(placed_order=False)
    close_old_connections()
    return {
        "ok": True,
        "tenant_name": tenant.name,
        "branches_count": len(branches_data),
        "branches": branches_data,
    }


# =====================================================================
# 2. Digital Menu Link Tool (Includes WhatsApp Suggested Text)
# =====================================================================

@mcp.tool
def get_digital_menu_link(branch_id: Optional[int] = None, access_key: Optional[str] = None) -> Dict[str, Any]:
    """
    استرجاع رابط قائمة الطعام الإلكترونية المباشرة (المنيو الرقمي QR Menu) للمطعم لمشاركته مع العميل أو إرساله عبر الواتساب.
    يُستخدم فوراً عند طلب العميل رابط المنيو أو تصفح القائمة أونلاين عبر الهاتف أو الواتساب.
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch

    branch = None
    if branch_id is not None:
        branch = Branch.objects.filter(tenant=tenant, id=branch_id, status="active").first()
        if not branch:
            return {"ok": False, "status": "error", "error": f"الفرع برقم #{branch_id} غير موجود أو غير تابع للمنشأة."}
    elif key_obj.assigned_branch:
        branch = key_obj.assigned_branch

    # Resolve Domain and URL
    if getattr(tenant, "custom_domain", None):
        c_domain = tenant.custom_domain.strip().rstrip("/")
        if not c_domain.startswith("http"):
            c_domain = f"https://{c_domain}"
        if branch:
            menu_url = f"{c_domain}/branch/{branch.id}/"
        else:
            menu_url = f"{c_domain}/"
    else:
        domain = os.environ.get("DOMAIN_NAME", "uggu.space").strip().rstrip("/")
        if not domain.startswith("http"):
            domain = f"https://{domain}"
        if branch:
            menu_url = f"{domain}/m/{tenant.slug}/branch/{branch.id}/"
        else:
            menu_url = f"{domain}/m/{tenant.slug}/"

    b_name = branch.name if branch else "كافة الفروع"
    whatsapp_text = (
        f"أهلاً بك يا فندم! 🍽️\n"
        f"يسعدنا تواصلك مع مطعم {tenant.name}.\n"
        f"تفضل رابط قائمة الطعام الإلكترونية لتصفح الوجبات والأسعار:\n"
        f"{menu_url}\n"
        f"يسعدنا دائماً خدمتك! ✨"
    )

    close_old_connections()
    return {
        "ok": True,
        "status": "success",
        "menu_url": menu_url,
        "restaurant_name": tenant.name,
        "branch_id": branch.id if branch else None,
        "branch_name": b_name,
        "message": f"رابط قائمة الطعام الإلكترونية لمطعم {tenant.name} هو: {menu_url}",
        "suggested_whatsapp_text": whatsapp_text
    }


# =====================================================================
# 3. Menu Browsing Tool
# =====================================================================

@mcp.tool
def get_menu(
    branch_id: Optional[int] = None,
    category: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    استعراض أصناف قائمة الطعام (Menu) المتوفرة في فرع محدد وأسعارها وتصنيفاتها وأحجامها المتاحة (Variants) ونسبة الضريبة.
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch, MenuItem, BranchMenuAvailability

    if branch_id is not None:
        branch = Branch.objects.filter(tenant=tenant, id=branch_id, status="active").first()
        if not branch:
            return {"ok": False, "error": f"الفرع برقم #{branch_id} غير موجود أو غير تابع للمنشأة."}
    elif key_obj.assigned_branch:
        branch = key_obj.assigned_branch
    else:
        branch = Branch.objects.filter(tenant=tenant, status="active").first()
        if not branch:
            return {"ok": False, "error": "لا توجد أي فروع نشطة متاحة للمنشأة حالياً."}

    if key_obj.assigned_branch and key_obj.assigned_branch_id != branch.id:
        return {"ok": False, "error": f"مفتاح الـ API هذا مخصص لفرع «{key_obj.assigned_branch.name}» فقط."}

    cur_name = branch.get_currency_name_ar()
    cur_sym = branch.get_currency_symbol_ar()

    items_qs = MenuItem.objects.filter(tenant=tenant, available=True).prefetch_related("variants")
    if category and category.strip():
        items_qs = items_qs.filter(category__icontains=category.strip())

    if query and query.strip():
        q_str = query.strip()
        items_qs = items_qs.filter(
            models.Q(name__icontains=q_str) |
            models.Q(name_en__icontains=q_str) |
            models.Q(description__icontains=q_str) |
            models.Q(category__icontains=q_str)
        )

    # Check branch availability overrides
    disabled_items = set(
        BranchMenuAvailability.objects.filter(branch=branch, is_available=False).values_list("menu_item_id", flat=True)
    )
    if disabled_items:
        items_qs = items_qs.exclude(id__in=disabled_items)

    total_count = items_qs.count()
    limit_val = max(1, min(limit, 100))
    paged_items = list(items_qs.order_by("category", "name")[offset : offset + limit_val])

    categories_map = {}
    items_list = []
    for m in paged_items:
        variants_data = []
        if getattr(m, "has_variants", False):
            for v in m.variants.all():
                variants_data.append({
                    "id": v.id,
                    "name": v.name,
                    "price": float(v.get_price_for_branch(branch)),
                    "is_default": v.is_default
                })

        item_dict = {
            "id": m.id,
            "name": m.name,
            "category": m.category,
            "price": float(m.get_price_for_branch(branch)),
            "has_variants": bool(m.has_variants and len(variants_data) > 0),
            "variants": variants_data,
            "currency": branch.currency,
            "currency_name": cur_name,
            "currency_symbol": cur_sym,
            "emoji": m.emoji or "🍽️",
        }
        items_list.append(item_dict)
        categories_map.setdefault(m.category, []).append(item_dict)

    all_categories = list(dict.fromkeys(MenuItem.objects.filter(tenant=tenant, available=True).values_list("category", flat=True)))

    key_obj.record_usage(placed_order=False)
    close_old_connections()
    return {
        "ok": True,
        "tenant_name": tenant.name,
        "branch_name": branch.name,
        "branch_id": branch.id,
        "is_branch_open": branch.is_currently_open(),
        "currency": branch.currency,
        "currency_name": cur_name,
        "currency_symbol": cur_sym,
        "tax_info": {
            "tax_percentage": float(branch.tax_percentage),
            "is_tax_inclusive": bool(branch.is_tax_inclusive),
            "tax_status_label": f"الضريبة {branch.tax_percentage:.1f}% ({'شاملة في الأسعار' if branch.is_tax_inclusive else 'تضاف فوق المجموع'})"
        },
        "cancellation_window_minutes": int(getattr(branch, "cancellation_window_minutes", 10)),
        "total_items": total_count,
        "returned_items": len(items_list),
        "limit": limit_val,
        "offset": offset,
        "categories": all_categories,
        "items": items_list,
    }


# =====================================================================
# 4. Customer Lookup & Recognition Tool
# =====================================================================

@mcp.tool
def lookup_customer(
    phone: Optional[str] = None,
    customer_phone: Optional[str] = None,
    phone_number: Optional[str] = None,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    البحث عن العميل برقم هاتفه لجلب اسمه وعناوينه والكومبوند وتاريخ طلباته السابقة.
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Customer, Order

    raw_val = str(phone or customer_phone or phone_number or "").strip()
    if not raw_val:
        close_old_connections()
        return {
            "ok": True,
            "status": "ready",
            "message": "أداة البحث عن العميل (lookup_customer) جاهزة ونشطة بنجاح.",
            "diagnostic": True
        }

    clean_phone = _clean_phone(raw_val)
    phone_suffix = clean_phone[-9:] if len(clean_phone) >= 9 else clean_phone

    # 0. Fast Redis Active Order Check (<0.2ms)
    redis_active = get_active_order_by_phone(tenant.id, clean_phone)
    if redis_active:
        status_code = redis_active.get("status", "new")
        if status_code in ["new", "preparing"]:
            status_desc = "في المطبخ بنجهزه طازج لحضرتك"
        elif status_code in ["ready", "out_for_delivery"]:
            status_desc = "خرج مع الطيار وفي الطريق إليك"
        else:
            status_desc = redis_active.get("status_display", status_code)

        rem_min = max(5, redis_active.get("estimated_delivery_minutes", 35))
        ord_num = redis_active.get("order_number", "")
        cust_name = str(redis_active.get("customer_name") or "").strip()
        first_name = cust_name.split()[0] if cust_name else ""
        title = f"يا أستاذ {first_name}" if (first_name and not cust_name.startswith("عميل")) else "يا فندم"
        active_speech = (
            f"أهلاً بحضرتك {title}! بخصوص طلبك الأخير رقم #{ord_num}، "
            f"هو حالياً {status_desc} ومتوقع يوصلك خلال {rem_min} دقيقة تقريباً.. "
            f"تحب أساعد حضرتك في أي استفسار بخصوصه؟"
        )
        key_obj.record_usage(placed_order=False)
        close_old_connections()
        return {
            "ok": True,
            "found": True,
            "has_active_recent_order": True,
            "customer": {
                "id": None,
                "name": redis_active.get("customer_name") or "عميل",
                "phone": clean_phone,
                "address": redis_active.get("address") or "",
            },
            "active_order": {
                "order_number": ord_num,
                "status": status_code,
                "status_display": status_desc,
                "estimated_remaining_minutes": rem_min,
                "total": float(redis_active.get("total", 0)),
                "branch_name": redis_active.get("branch_name", ""),
                "items_summary": redis_active.get("items_summary", ""),
            },
            "ai_speech_response": active_speech,
            "instruction_for_ai": (
                "العميل لديه أوردر جارٍ قيد التنفيذ؛ اقرأ عليه نص ai_speech_response فوراً لتطمينه على طلبه. "
                "إذا كان يتصل للاستفسار عنه، أجب على تساؤلاته. أما إذا ذكر أنه يرغب في عمل طلب جديد إضافي، فابدأ معه في تلقي الأصناف الجديدة."
            )
        }

    customer = Customer.objects.filter(tenant=tenant).filter(
        models.Q(phone=clean_phone) | models.Q(phone__endswith=phone_suffix)
    ).first()

    # 0.5 Check for Abandoned Draft Cart from Interrupted Call (within 30 mins)
    has_cart, abandoned_cart = cart_is_abandoned(tenant.id, clean_phone, max_age_seconds=1800)
    if has_cart and abandoned_cart and abandoned_cart.get("items"):
        cart_items = abandoned_cart["items"]
        items_summary = " و ".join([f"{it['quantity']} {it['name']}" for it in cart_items[:4]])
        total_est = sum(float(it.get("price", 0)) * int(it.get("quantity", 1)) for it in cart_items)
        speech = (
            f"أهلاً بحضرتك يا فندم! نورتنا تاني.. "
            f"كان مسجل عندنا في طلبك السابق ({items_summary}).. "
            f"تحب نكمل عليها ولا حابب تعدل عليها أو تبدأ طلب جديد؟"
        )
        instruction = (
            "العميل لديه سلة طلبات سابقة غير مكتملة (مكالمة منقطعة)؛ اعرض عليه استئنافها كما في ai_speech_response. "
            "إذا وافق العميل (قال كمل، تمام، أو نعم)، استكمل معه تأكيد العنوان عبر checkout_cart أو create_callcenter_order. "
            "أما إذا قال (لا، أو ابدأ طلب جديد)، فاستدعِ أداة cart_clear فوراً لتفريغ السلة وابدأ معه طلباً جديداً."
        )
        key_obj.record_usage(placed_order=False)
        close_old_connections()
        return {
            "ok": True,
            "found": True,
            "has_abandoned_cart": True,
            "customer": {
                "id": customer.id if customer else None,
                "name": customer.name if customer else "عميل",
                "phone": clean_phone,
                "address": customer.address if customer else "",
            },
            "abandoned_cart": {
                "items": cart_items,
                "items_count": abandoned_cart.get("items_count", len(cart_items)),
                "estimated_total": round(total_est, 2),
                "items_summary": items_summary,
            },
            "ai_speech_response": speech,
            "instruction_for_ai": instruction,
        }

    now = timezone.now()
    one_hour_ago = now - timezone.timedelta(minutes=60)

    if not customer:
        key_obj.record_usage(placed_order=False)
        close_old_connections()
        welcome_speech = f"أهلاً بحضرتك في مطعم «{tenant.name}»! تشرفنا بخدمتك يا فندم.. تحب تطلب إيه اليوم سفري ولا دليفري؟"
        return {
            "ok": True,
            "found": False,
            "is_new_customer": True,
            "phone": clean_phone,
            "message": "عميل جديد غير مسجل مسبقاً. سيتم حفظ بياناته تلقائياً عند تسجيل الأوردر.",
            "ai_speech_response": welcome_speech,
            "instruction_for_ai": "رحب بالعميل الجديد بنص ai_speech_response واستقبل طلبه باحترافية."
        }

    # Proactive Active Order Check in DB
    active_order = Order.objects.filter(
        tenant=tenant,
        customer=customer,
        created_at__gte=one_hour_ago,
        status__in=["new", "preparing", "ready", "out_for_delivery"]
    ).order_by("-created_at").first()

    if active_order:
        try:
            cache_active_order(active_order)
        except Exception:
            pass
        elapsed_min = max(1, int((now - active_order.created_at).total_seconds() / 60))
        if active_order.status in ["new", "preparing"]:
            status_desc = "في المطبخ بنجهزه طازج لحضرتك"
        elif active_order.status in ["ready", "out_for_delivery"]:
            status_desc = "خرج مع الطيار وفي الطريق إليك"
        else:
            status_desc = active_order.get_status_display()

        area_est = active_order.delivery_area.estimated_time_minutes if active_order.delivery_area else 35
        rem_min = max(5, area_est - elapsed_min)
        cust_name = str(customer.name if customer else "").strip()
        first_name = cust_name.split()[0] if cust_name else ""
        title = f"يا أستاذ {first_name}" if (first_name and not cust_name.startswith("عميل")) else "يا فندم"
        active_speech = (
            f"أهلاً بحضرتك {title}! بخصوص طلبك الأخير رقم #{active_order.order_number}، "
            f"هو حالياً {status_desc} ومتوقع يوصلك خلال {rem_min} دقيقة تقريباً.. "
            f"تحب أساعد حضرتك في أي استفسار بخصوصه؟"
        )

        key_obj.record_usage(placed_order=False)
        close_old_connections()
        return {
            "ok": True,
            "found": True,
            "has_active_recent_order": True,
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "phone": customer.phone,
                "address": customer.address,
            },
            "active_order": {
                "order_number": active_order.order_number,
                "status": active_order.status,
                "status_display": status_desc,
                "created_minutes_ago": elapsed_min,
                "estimated_remaining_minutes": rem_min,
                "total": float(active_order.total),
                "branch_name": active_order.branch.name if active_order.branch else "",
            },
            "ai_speech_response": active_speech,
            "instruction_for_ai": (
                "العميل لديه أوردر جارٍ قيد التنفيذ؛ اقرأ عليه نص ai_speech_response فوراً لتطمينه على طلبه. "
                "إذا كان يتصل للاستفسار عنه، أجب على تساؤلاته. أما إذا ذكر أنه يرغب في عمل طلب جديد إضافي، فابدأ معه في تلقي الأصناف الجديدة."
            )
        }

    # Saved Address Recognition
    last_delivery_order = Order.objects.filter(
        tenant=tenant,
        customer=customer,
        order_type="delivery"
    ).exclude(address="").order_by("-created_at").first()

    saved_addr = last_delivery_order.address if last_delivery_order else customer.address
    saved_branch = last_delivery_order.branch if last_delivery_order else None
    saved_area = last_delivery_order.delivery_area if last_delivery_order else None

    recent_orders = Order.objects.filter(tenant=tenant, customer=customer).order_by("-created_at")[:3]
    orders_data = [
        {
            "order_number": o.order_number,
            "total": float(o.total),
            "status": o.get_status_display(),
            "created_at": o.created_at.strftime("%Y-%m-%d %H:%M"),
            "items_count": o.items.count(),
        }
        for o in recent_orders
    ]
    order_count = customer.orders.count()
    total_spent = float(customer.orders.aggregate(models.Sum("total"))["total__sum"] or 0)

    cust_name_clean = str(customer.name or "").strip()
    is_placeholder_name = (
        not cust_name_clean
        or cust_name_clean.lower() in ["عميل", "عميل نقدي", "عميل هاتف", "عميل جديد", "عميل مجهول"]
        or cust_name_clean.startswith("عميل (")
        or bool(re.match(r"^عميل\s*(\(\d+\))?$", cust_name_clean))
    )
    first_name = cust_name_clean.split()[0] if not is_placeholder_name else ""

    if saved_addr:
        if is_placeholder_name:
            greeting_speech = (
                f"أهلاً بحضرتك يا فندم! نورتنا في مطعم «{tenant.name}».. "
                f"تحب نوصل لحضرتك على نفس عنوانك السابق ({saved_addr}) ولا حابب تطلب على عنوان جديد؟"
            )
            instruction = (
                f"العميل مسجل مسبقاً ولديه عنوان محفوظ؛ رحب به بلطف واقرأ عليه نص ai_speech_response واعرض عليه التوصيل لنفس العنوان ({saved_addr}). "
                f"إذا وافق العميل (قال نعم، أو تمام، أو نفس العنوان)، اعتمد هذا العنوان والفرع فوراً دون الحاجة لسؤاله عن الحي أو المنطقة مجدداً."
            )
        else:
            greeting_speech = (
                f"أهلاً بحضرتك يا أستاذ {first_name}! نورتنا يا فندم.. "
                f"تحب نوصل لحضرتك على نفس عنوانك السابق ({saved_addr}) ولا حابب تطلب على عنوان جديد؟"
            )
            instruction = (
                f"العميل مسجل مسبقاً ولديه عنوان محفوظ؛ رحب به باسمه واقرأ عليه نص ai_speech_response واعرض عليه التوصيل لنفس العنوان ({saved_addr}). "
                f"إذا وافق العميل (قال نعم، أو تمام، أو نفس العنوان)، اعتمد هذا العنوان والفرع فوراً دون الحاجة لسؤاله عن الحي أو المنطقة أو رسم الخريطة مجدداً."
            )
    else:
        if is_placeholder_name:
            greeting_speech = f"أهلاً بحضرتك يا فندم! نورتنا في مطعم «{tenant.name}»، تشرفنا بخدمتك.. تحب تطلب إيه اليوم سفري ولا دليفري؟"
            instruction = "رحب بالعميل بلطف بنص ai_speech_response وتلقى طلبه."
        else:
            greeting_speech = f"أهلاً بحضرتك يا أستاذ {first_name}! نورتنا في مطعم «{tenant.name}»، تشرفنا بخدمتك يا فندم.. تحب تطلب إيه اليوم؟"
            instruction = "رحب بالعميل باسمه بنص ai_speech_response وتلقى طلبه."

    key_obj.record_usage(placed_order=False)
    close_old_connections()
    return {
        "ok": True,
        "found": True,
        "has_active_recent_order": False,
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "address": saved_addr or customer.address,
            "total_orders": order_count,
            "total_spent": total_spent,
            "created_at": customer.created_at.strftime("%Y-%m-%d"),
        },
        "saved_delivery_profile": {
            "saved_address": saved_addr,
            "saved_branch_id": saved_branch.id if saved_branch else None,
            "saved_branch_name": saved_branch.name if saved_branch else None,
            "saved_delivery_area_id": saved_area.id if saved_area else None,
            "saved_delivery_area_name": saved_area.name if saved_area else None,
        } if saved_addr else None,
        "recent_orders": orders_data,
        "ai_speech_response": greeting_speech,
        "instruction_for_ai": instruction,
    }


# =====================================================================
# 5. Delivery Coverage Tool
# =====================================================================

@mcp.tool
def check_delivery_coverage(
    branch_id: Optional[int] = None,
    area_name: Optional[str] = "",
    delivery_area_name: Optional[str] = None,
    customer_address: Optional[str] = None,
    address: Optional[str] = None,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    فحص هل منطقة العميل أو الكومبوند يقع ضمن مناطق توصيل المطعم، وحساب رسوم ووقت التوصيل وتحديد الفرع الأنسب تلقائياً.
    إلزامي الاستدعاء عند رغبة العميل في خدمة التوصيل (Delivery) وقبل إنشاء الطلب.
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch, DeliveryArea

    query = str(area_name or delivery_area_name or customer_address or address or "").strip()

    # Diagnostic / Health check call
    if not query:
        branch = Branch.objects.filter(tenant=tenant, status="active").first()
        all_areas = list(DeliveryArea.objects.filter(branch__tenant=tenant, is_active=True).values_list("name", flat=True))
        close_old_connections()
        return {
            "ok": True,
            "status": "ready",
            "message": "أداة فحص التغطية (check_delivery_coverage) جاهزة ونشطة بنجاح.",
            "branch_name": branch.name if branch else "الفرع الرئيسي",
            "available_areas": list(set(all_areas)),
            "diagnostic": True,
        }

    effective_branch_id = branch_id if branch_id is not None else (key_obj.assigned_branch_id if key_obj.assigned_branch else None)
    matched_branch, matched_area, err = _resolve_delivery_coverage_and_branch(
        tenant,
        customer_address=query,
        branch_id=effective_branch_id,
        delivery_area_name=query,
    )

    key_obj.record_usage(placed_order=False)
    close_old_connections()
    if err:
        err["covered"] = False
        return err

    cur_name = matched_branch.get_currency_name_ar()
    cur_sym = matched_branch.get_currency_symbol_ar()
    dist_val = getattr(matched_area, "distance_km", 0.0)
    min_order_req = matched_branch.get_min_order_for_distance(dist_val)
    return {
        "ok": True,
        "covered": True,
        "branch_id": matched_branch.id,
        "branch_name": matched_branch.name,
        "currency": matched_branch.currency,
        "currency_name": cur_name,
        "currency_symbol": cur_sym,
        "minimum_order_amount": float(min_order_req),
        "matched_area": {
            "id": matched_area.id,
            "name": matched_area.name,
            "area_type": matched_area.get_area_type_display(),
            "delivery_fee": float(matched_area.delivery_fee),
            "estimated_time_minutes": matched_area.estimated_time_minutes,
            "distance_km": float(dist_val) if dist_val else None,
            "minimum_order_amount": float(min_order_req),
            "notes": matched_area.notes or "",
        },
        "ai_speech_response": f"تمام يا فندم، منطقة «{matched_area.name}» مغطاة من خلال {matched_branch.name}، ورسوم التوصيل {matched_area.delivery_fee:.0f} {cur_name}، ووقت التوصيل التقديري حوالي {matched_area.estimated_time_minutes} دقيقة (والحد الأدنى للطلب {min_order_req:.0f} {cur_name}).",
        "instruction_for_ai": f"أبلغ العميل بأن المنطقة «{matched_area.name}» مغطاة ورسوم التوصيل هي {matched_area.delivery_fee:.0f} {cur_name}، ووقت التوصيل التقديري {matched_area.estimated_time_minutes} دقيقة كما في ai_speech_response."
    }


# =====================================================================
# 6. Preview & Total Calculation Tool
# =====================================================================

@mcp.tool
def preview_order(
    items: Optional[List[OrderItemInput]] = None,
    customer_address: Optional[str] = "",
    delivery_area_name: Optional[str] = None,
    delivery_area_id: Optional[int] = None,
    order_type: str = "delivery",
    branch_id: Optional[int] = None,
    branch_name: Optional[str] = None,
    branch: Optional[Any] = None,
    customer_phone: Optional[str] = None,
    phone: Optional[str] = None,
    phone_number: Optional[str] = None,
    customer_name: Optional[str] = None,
    name: Optional[str] = None,
    address: Optional[str] = None,
    notes: Optional[str] = None,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    معاينة وحساب الفاتورة المبدئية للطلب بدقة (الأسعار، الضريبة المحددة للفرع، ورسوم التوصيل) دون إنشاء أوردر في النظام.
    تُستخدم لحساب التكلفة الإجمالية وإبلاغ العميل بها والحصول على موافقته الصريحة قبل ضرب الطلب نهائياً.
    """
    close_old_connections()
    try:
        key_obj, tenant = _authenticate(access_key)
        from core.models import Branch, MenuItem, BranchMenuAvailability

        if not customer_address and address:
            customer_address = address

        # Diagnostic call
        if not items and not customer_address and not delivery_area_name:
            return {
                "ok": True,
                "status": "ready",
                "message": "أداة معاينة الفاتورة وحساب الإجمالي (preview_order) جاهزة ونشطة بنجاح.",
                "diagnostic": True
            }

        # Check cart if items empty and phone provided
        clean_p = _clean_phone(customer_phone or phone or phone_number)
        if (items is None or len(items) == 0) and clean_p:
            cached_cart = cart_get(tenant.id, clean_p)
            if cached_cart.get("items"):
                items = cached_cart["items"]

        # Parse & normalize items
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                natural = _parse_natural_order_text(items, tenant)
                if natural:
                    items = natural
                else:
                    return {
                        "ok": False,
                        "is_system_error": False,
                        "error_code": "ERR_INVALID_ITEMS_FORMAT",
                        "error": "صيغة قائمة الأصناف غير صالحة، يرجى تزويدنا بقائمة أصناف صحيحة.",
                        "ai_speech_response": "يا فندم ما قدرتش أحدد الأصناف المطلوبة، ممكن توضح لي طلبت إيه بالظبط؟",
                        "instruction_for_ai": "اطلب من العميل توضيح الأصناف والكميات المطلوبة."
                    }
        elif isinstance(items, dict):
            items = [items]

        cleaned_items = []
        for it in (items or []):
            if hasattr(it, "model_dump"):
                cleaned_items.append(it.model_dump())
            elif hasattr(it, "dict"):
                cleaned_items.append(it.dict())
            elif isinstance(it, dict):
                cleaned_items.append(it)
            elif isinstance(it, str):
                try:
                    cleaned_items.append(json.loads(it))
                except Exception:
                    nat = _parse_natural_order_text(it, tenant)
                    if nat:
                        cleaned_items.extend(nat)
                    else:
                        cleaned_items.append({"name": it, "quantity": 1})
            else:
                cleaned_items.append({"name": str(it), "quantity": 1})
        items = cleaned_items

        if not items:
            return {
                "ok": False,
                "is_system_error": False,
                "error_code": "ERR_ITEMS_REQUIRED",
                "error": "يجب تزويدنا بقائمة أصناف صالحة في المعامل items لحساب الفاتورة.",
                "ai_speech_response": "يا فندم محتاجة أعرف الأصناف اللي تحب تطلبها عشان أحسب لحضرتك الفاتورة.",
                "instruction_for_ai": "اسأل العميل عن الأصناف التي يود طلبها."
            }

        # Order Type & Delivery Coverage Calculation
        order_type = str(order_type or "delivery").strip().lower()
        if order_type not in ["delivery", "takeaway", "dine_in"]:
            order_type = "delivery"

        delivery_fee = Decimal("0.00")
        matched_area = None
        branch_obj = None

        effective_branch_id = branch_id if branch_id is not None else (key_obj.assigned_branch_id if key_obj.assigned_branch else None)

        if order_type == "delivery":
            branch_obj, matched_area, err = _resolve_delivery_coverage_and_branch(
                tenant,
                customer_address=customer_address or "",
                branch_id=effective_branch_id,
                delivery_area_id=delivery_area_id,
                delivery_area_name=delivery_area_name,
            )
            if err:
                return err
            delivery_fee = matched_area.delivery_fee
            addr_valid, addr_err = _validate_delivery_address_completeness(
                customer_address or "",
                matched_area_name=matched_area.name if matched_area else (delivery_area_name or "")
            )
        else:
            active_branches = list(Branch.objects.filter(tenant=tenant, status="active"))
            if not active_branches:
                return {
                    "ok": False,
                    "is_system_error": False,
                    "error": "لا توجد فروع نشطة متاحة للمنشأة حالياً.",
                    "ai_speech_response": "بعتذر لحضرتك، فروعنا مغلقة حالياً لاستقبال الطلبات.",
                    "instruction_for_ai": "أبلغ العميل بأن فروعنا مغلقة حالياً."
                }

            candidate_bname = str(branch_name or branch or "").strip()

            if effective_branch_id is not None:
                branch_obj = next((b for b in active_branches if b.id == effective_branch_id), None)
                if not branch_obj and 1 <= effective_branch_id <= len(active_branches):
                    branch_obj = active_branches[effective_branch_id - 1]

            if not branch_obj and candidate_bname:
                norm_b = _normalize_arabic_text(candidate_bname)
                for b in active_branches:
                    norm_curr = _normalize_arabic_text(b.name)
                    norm_city = _normalize_arabic_text(b.city)
                    if norm_b in norm_curr or norm_curr in norm_b or (norm_city and (norm_b in norm_city or norm_city in norm_b)):
                        branch_obj = b
                        break

            if not branch_obj:
                if len(active_branches) > 1:
                    branch_names = [b.name for b in active_branches]
                    b_names_str = " أو ".join([f"«{b.name}»" for b in active_branches[:4]])
                    return {
                        "ok": False,
                        "is_system_error": False,
                        "status": "branch_selection_required",
                        "error": f"يرجى تحديد فرع الاستلام لحساب الأسعار بدقة: ({b_names_str}).",
                        "available_branches": branch_names,
                        "ai_speech_response": f"تحب حضرتك تستلم من أي فرع لحساب الإجمالي بدقة؟ متاح عندنا: {b_names_str}.",
                        "instruction_for_ai": "اسأل العميل بلطف عن الفرع الذي يود الاستلام منه كما في ai_speech_response."
                    }
                else:
                    branch_obj = active_branches[0]

        if not branch_obj.is_currently_open():
            return _format_branch_closed_err(branch_obj)

        cur_name = branch_obj.get_currency_name_ar()
        cur_sym = branch_obj.get_currency_symbol_ar()

        disabled_item_ids = set(
            BranchMenuAvailability.objects.filter(branch=branch_obj, is_available=False).values_list("menu_item_id", flat=True)
        )
        all_tenant_items = list(MenuItem.objects.filter(tenant=tenant, available=True).prefetch_related("variants"))

        subtotal = Decimal("0.00")
        prepared_items = []

        for idx, item_spec in enumerate(items, start=1):
            menu_item, variant_item, match_err = _find_menu_item(tenant, branch_obj, item_spec, disabled_item_ids, all_tenant_items)
            if match_err:
                if isinstance(match_err, dict):
                    return match_err
                return {
                    "ok": False,
                    "error": match_err,
                    "ai_speech_response": f"يا فندم بخصوص طلبك، {match_err}",
                    "instruction_for_ai": "لا تقل إن هناك عطلاً بالسيستم! أبلغ العميل بما ورد في ai_speech_response واقترح عليه بديلاً متوفراً."
                }

            if isinstance(item_spec, dict):
                try:
                    qty = int(item_spec.get("quantity") or item_spec.get("qty") or 1)
                except (ValueError, TypeError):
                    qty = 1
            else:
                qty = 1

            if qty <= 0:
                continue

            if variant_item:
                item_price = variant_item.get_price_for_branch(branch_obj)
                display_name = f"{menu_item.name} ({variant_item.name})"
                var_name = variant_item.name
                var_id = variant_item.id
            else:
                item_price = menu_item.get_price_for_branch(branch_obj)
                display_name = menu_item.name
                var_name = None
                var_id = None

            line_total = item_price * qty
            subtotal += line_total
            prepared_items.append({
                "name": display_name,
                "item_id": menu_item.id,
                "variant_id": var_id,
                "variant_name": var_name,
                "quantity": qty,
                "unit_price": float(item_price),
                "line_total": float(line_total),
            })

        if not prepared_items:
            return {
                "ok": False,
                "error": "لم يتم العثور على أي أصناف صالحة لحساب الفاتورة.",
                "ai_speech_response": "يا فندم محتاجة تحديد الأصناف والكميات بوضوح لحساب الإجمالي.",
                "instruction_for_ai": "اطلب من العميل توضيح طلبه."
            }

        tax_rate = Decimal(str(getattr(branch_obj, "tax_percentage", None) or "0.00"))
        is_tax_inclusive = bool(getattr(branch_obj, "is_tax_inclusive", True))

        if is_tax_inclusive:
            if tax_rate > 0:
                tax_amount = (subtotal - (subtotal / (Decimal("1.00") + (tax_rate / Decimal("100.00"))))).quantize(Decimal("0.01"))
            else:
                tax_amount = Decimal("0.00")
            grand_total = subtotal + delivery_fee
        else:
            tax_amount = (subtotal * (tax_rate / Decimal("100.00"))).quantize(Decimal("0.01"))
            grand_total = subtotal + tax_amount + delivery_fee

        items_speech = " و ".join([f"{it['quantity']} {it['name']}" for it in prepared_items])

        # Minimum order check for delivery
        if order_type == "delivery":
            dist_val = getattr(matched_area, "distance_km", 0.0)
            min_order_req = branch_obj.get_min_order_for_distance(dist_val)
            if subtotal < min_order_req:
                diff = min_order_req - subtotal
                min_speech = (
                    f"طلبك ({items_speech}) بمجموع أصناف {subtotal:.0f} {cur_name}، "
                    f"ولكن الحد الأدنى لطلب التوصيل لمنطقة «{matched_area.name if matched_area else 'حضرتك'}» هو {min_order_req:.0f} {cur_name} "
                    f"(باقي {diff:.0f} {cur_name} لتكملة الحد الأدنى).. تحب نضيف لحضرتك مشروب أو صنف إضافي لتكملة الطلب؟"
                )
                key_obj.record_usage(placed_order=False)
                return {
                    "ok": True,
                    "error_code": "ERR_MIN_ORDER_NOT_MET",
                    "below_minimum_order": True,
                    "branch_name": branch_obj.name,
                    "currency": branch_obj.currency,
                    "currency_name": cur_name,
                    "currency_symbol": cur_sym,
                    "order_type": "توصيل",
                    "items": prepared_items,
                    "subtotal": float(subtotal),
                    "tax_percentage": float(tax_rate),
                    "is_tax_inclusive": is_tax_inclusive,
                    "tax": float(tax_amount),
                    "minimum_order_required": float(min_order_req),
                    "amount_needed": float(diff),
                    "delivery_fee": float(delivery_fee),
                    "delivery_area": matched_area.name if matched_area else "غير محدد",
                    "estimated_delivery_time": f"{matched_area.estimated_time_minutes} دقيقة" if matched_area else "30-45 دقيقة",
                    "total": float(grand_total),
                    "ai_speech_response": min_speech,
                    "ai_speech_summary": min_speech,
                    "instruction_for_ai": (
                        f"أبلغ العميل بلطف أن حساب الأصناف ({subtotal:.0f} {cur_name}) أقل من الحد الأدنى المطلوب للتوصيل لهذه المنطقة "
                        f"({min_order_req:.0f} {cur_name})، واقترح عليه إضافة أصناف إضافية بقيمة {diff:.0f} {cur_name} كما في ai_speech_response."
                    )
                }

        tax_speech = f" (شامل الضريبة {tax_rate:.0f}%)" if (is_tax_inclusive and tax_rate > 0) else (f" والضريبة {tax_amount:.0f} {cur_name}" if tax_rate > 0 else "")
        if order_type == "delivery":
            speech = f"إجمالي طلبك ({items_speech}) بقيمة {subtotal:.0f} {cur_name}{tax_speech}، ورسوم التوصيل {delivery_fee:.0f} {cur_name}، الإجمالي النهائي {grand_total:.0f} {cur_name}. تحب أسجل لحضرتك الطلب دلوقتي؟"
        else:
            speech = f"إجمالي طلبك سفري ({items_speech}) بقيمة {subtotal:.0f} {cur_name}{tax_speech}، وتقدر تستلمه من فرع {branch_obj.name}. تحب أسجل لحضرتك الطلب دلوقتي؟"

        key_obj.record_usage(placed_order=False)
        return {
            "ok": True,
            "below_minimum_order": False,
            "branch_name": branch_obj.name,
            "currency": branch_obj.currency,
            "currency_name": cur_name,
            "currency_symbol": cur_sym,
            "order_type": "توصيل" if order_type == "delivery" else "استلام من الفرع",
            "items": prepared_items,
            "subtotal": float(subtotal),
            "tax_percentage": float(tax_rate),
            "is_tax_inclusive": is_tax_inclusive,
            "tax": float(tax_amount),
            "delivery_fee": float(delivery_fee),
            "delivery_area": matched_area.name if matched_area else ("سفري" if order_type == "takeaway" else "غير محدد"),
            "estimated_delivery_time": f"{matched_area.estimated_time_minutes} دقيقة" if matched_area else "30-45 دقيقة",
            "address_status": "complete" if (order_type != "delivery" or addr_valid) else (addr_err.get("status", "details_required") if addr_err else "details_required"),
            "address_notice": (addr_err.get("ai_speech_response") if (order_type == "delivery" and not addr_valid and addr_err) else None),
            "total": float(grand_total),
            "ai_speech_response": speech,
            "ai_speech_summary": speech,
            "instruction_for_ai": "أخبر العميل بالإجمالي كما هو موضح في ai_speech_response واطلب موافقته الصريحة قبل تسجيل الأوردر نهائياً."
        }
    finally:
        close_old_connections()


# Alias for backward compatibility
calculate_order_total = preview_order


# =====================================================================
# 7. Order Placement Tool (Call Center AI)
# =====================================================================

@mcp.tool
def create_callcenter_order(
    phone: Optional[str] = None,
    items: Optional[List[OrderItemInput]] = None,
    customer_name: Optional[str] = "",
    address: Optional[str] = "",
    order_type: str = "delivery",
    branch_id: Optional[int] = None,
    customer_phone: Optional[str] = None,
    phone_number: Optional[str] = None,
    customer_address: Optional[str] = None,
    name: Optional[str] = None,
    branch_name: Optional[str] = None,
    branch: Optional[Any] = None,
    delivery_area_id: Optional[int] = None,
    delivery_area_name: Optional[str] = None,
    notes: str = "",
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    إنشاء (ضرب) أوردر جديد من الكول سنتر مع التعرف التلقائي على العميل برقم هاتفه،
    ومطابقة الأصناف الذكية بالمرادفات واللهجات والأحجام، وحساب الضريبة الخاصة بالفرع، والتوجيه التلقائي للفرع الذي يغطي عنوان العميل.
    وإذا كانت الأصناف غير ممررة يتم سحبها تلقائياً من سلة العميل المؤقتة (Draft Cart).
    """
    close_old_connections()
    try:
        key_obj, tenant = _authenticate(access_key)
        from core.models import Branch, Customer, MenuItem, Order, OrderItem, DeliveryArea, BranchMenuAvailability

        raw_phone = str(phone or customer_phone or phone_number or "").strip()
        customer_address = str(address or customer_address or "").strip()
        customer_name = str(customer_name or name or "").strip()
        branch_name = branch_name or branch

        # Diagnostic call
        if not raw_phone and not items and not customer_address:
            return {
                "ok": True,
                "status": "ready",
                "message": "أداة إنشاء أوردرات الكول سنتر (create_callcenter_order) جاهزة ونشطة بنجاح.",
                "diagnostic": True
            }

        # 1. Clean Phone
        clean_phone = _clean_phone(raw_phone)
        if not clean_phone or len(clean_phone) < 7:
            if raw_phone and ("dashboard" in str(raw_phone).lower() or "test" in str(raw_phone).lower()):
                clean_phone = "0559998877"
            else:
                return {
                    "ok": False,
                    "is_system_error": False,
                    "error_code": "ERR_PHONE_REQUIRED",
                    "status": "phone_required",
                    "error": "رقم هاتف العميل مطلوب لتسجيل الطلب وتتبعه.",
                    "ai_speech_response": "يا فندم محتاجة رقم تليفون حضرتك عشان نقدر نسجل الأوردر ونبعتلك رابط التتبع.",
                    "instruction_for_ai": "اطلب من العميل تزويدك برقم هاتفه لتسجيل الطلب."
                }

        # 2. Check draft cart session if items omitted/empty
        used_cart_checkout = False
        if (items is None or len(items) == 0) and clean_phone:
            cached_cart = cart_get(tenant.id, clean_phone)
            if cached_cart.get("items"):
                items = cached_cart["items"]
                used_cart_checkout = True

        # Parse & normalize items if stringified JSON, natural string, or Pydantic models
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                natural = _parse_natural_order_text(items, tenant)
                if natural:
                    items = natural
                else:
                    return {
                        "ok": False,
                        "is_system_error": False,
                        "error_code": "ERR_INVALID_ITEMS_FORMAT",
                        "error": "صيغة قائمة الأصناف غير صالحة.",
                        "ai_speech_response": "يا فندم ما قدرتش أسجل الأصناف المطلوبة، ممكن تعيدها لي تاني؟",
                        "instruction_for_ai": "اطلب من العميل إعادة ذكر الأصناف والكميات المطلوبة."
                    }
        elif isinstance(items, dict):
            items = [items]

        cleaned_items = []
        for it in (items or []):
            if hasattr(it, "model_dump"):
                cleaned_items.append(it.model_dump())
            elif hasattr(it, "dict"):
                cleaned_items.append(it.dict())
            elif isinstance(it, dict):
                cleaned_items.append(it)
            elif isinstance(it, str):
                try:
                    cleaned_items.append(json.loads(it))
                except Exception:
                    nat = _parse_natural_order_text(it, tenant)
                    if nat:
                        cleaned_items.extend(nat)
                    else:
                        cleaned_items.append({"name": it, "quantity": 1})
            else:
                cleaned_items.append({"name": str(it), "quantity": 1})
        items = cleaned_items

        if not items:
            return {
                "ok": False,
                "is_system_error": False,
                "error_code": "ERR_CART_EMPTY" if used_cart_checkout else "ERR_ITEMS_REQUIRED",
                "error": "سلة الطلبات فارغة أو لم يتم تحديد الأصناف المطلوبة لتنفيذ الطلب.",
                "ai_speech_response": "يا فندم السلة حالياً فارغة، تحب تطلب إيه من المنيو؟" if used_cart_checkout else "يا فندم محتاجة أعرف الأصناف والكميات المطلوبة عشان أسجل الأوردر.",
                "instruction_for_ai": "اطلب من العميل تحديد الأصناف التي يود طلبها ولا تقل إن هناك عطلاً بالسيستم."
            }

        # 3. Customer Recognition
        phone_suffix = clean_phone[-9:] if len(clean_phone) >= 9 else clean_phone
        customer = Customer.objects.filter(tenant=tenant).filter(
            models.Q(phone=clean_phone) | models.Q(phone__endswith=phone_suffix)
        ).first()

        clean_name = str(customer_name or "").strip()
        clean_addr = str(customer_address or "").strip()
        customer_recognized = False

        if customer:
            customer_recognized = True
            is_generic = not customer.name or customer.name.startswith("عميل") or customer.name.isdigit()
            if is_generic and clean_name and not clean_name.startswith("عميل"):
                customer.name = clean_name
                customer.save(update_fields=["name"])
            if not customer.address and clean_addr:
                customer.address = clean_addr
                customer.save(update_fields=["address"])
        else:
            cust_name_to_save = clean_name or f"عميل ({clean_phone[-4:]})"
            try:
                customer = Customer.objects.create(
                    tenant=tenant,
                    phone=clean_phone,
                    name=cust_name_to_save,
                    address=clean_addr,
                )
            except IntegrityError:
                customer = Customer.objects.filter(tenant=tenant).filter(
                    models.Q(phone=clean_phone) | models.Q(phone__endswith=phone_suffix)
                ).first()

        # 4. Order Type & Delivery / Branch Resolution
        order_type = str(order_type or "delivery").strip().lower()
        if order_type not in ["delivery", "takeaway", "dine_in"]:
            order_type = "delivery"

        delivery_fee = Decimal("0.00")
        matched_area = None
        branch_obj = None

        effective_branch_id = branch_id if branch_id is not None else (key_obj.assigned_branch_id if key_obj.assigned_branch else None)

        if order_type == "delivery":
            branch_obj, matched_area, err = _resolve_delivery_coverage_and_branch(
                tenant,
                customer_address=clean_addr,
                branch_id=effective_branch_id,
                delivery_area_id=delivery_area_id,
                delivery_area_name=delivery_area_name,
            )
            if err:
                return err
            delivery_fee = matched_area.delivery_fee

            addr_valid, addr_err = _validate_delivery_address_completeness(
                clean_addr,
                matched_area_name=matched_area.name if matched_area else (delivery_area_name or "")
            )
            if not addr_valid:
                return addr_err
        else:
            active_branches = list(Branch.objects.filter(tenant=tenant, status="active"))
            if not active_branches:
                return {
                    "ok": False,
                    "is_system_error": False,
                    "error": "لا توجد فروع نشطة متاحة للمنشأة حالياً.",
                    "ai_speech_response": "بعتذر لحضرتك، فروعنا مغلقة حالياً لاستقبال الطلبات.",
                    "instruction_for_ai": "أبلغ العميل بأن الفروع مغلقة حالياً."
                }

            candidate_bname = str(branch_name or branch or "").strip()

            if effective_branch_id is not None:
                branch_obj = next((b for b in active_branches if b.id == effective_branch_id), None)
                if not branch_obj and 1 <= effective_branch_id <= len(active_branches):
                    branch_obj = active_branches[effective_branch_id - 1]

            if not branch_obj and candidate_bname:
                norm_b = _normalize_arabic_text(candidate_bname)
                for b in active_branches:
                    norm_curr = _normalize_arabic_text(b.name)
                    norm_city = _normalize_arabic_text(b.city)
                    if norm_b in norm_curr or norm_curr in norm_b or (norm_city and (norm_b in norm_city or norm_city in norm_b)):
                        branch_obj = b
                        break

            if not branch_obj:
                if len(active_branches) > 1:
                    branch_names = [b.name for b in active_branches]
                    b_names_str = " أو ".join([f"«{b.name}»" for b in active_branches[:4]])
                    return {
                        "ok": False,
                        "is_system_error": False,
                        "status": "branch_selection_required",
                        "error": f"يرجى تحديد فرع الاستلام من بين فروع المنشأة المتاحة: ({b_names_str}).",
                        "available_branches": branch_names,
                        "ai_speech_response": f"تحب حضرتك تستلم الطلب من أي فرع من فروعنا؟ متاح عندنا: {b_names_str}.",
                        "instruction_for_ai": "اسأل العميل بلطف عن الفرع الذي يود الاستلام منه من بين الفروع المتاحة كما في ai_speech_response ولا تسجل الطلب إلا بعد تحديد الفرع وتأكيده مع العميل."
                    }
                else:
                    branch_obj = active_branches[0]

        if not branch_obj.is_currently_open():
            return _format_branch_closed_err(branch_obj)

        # 5. Item Matching & Subtotal
        disabled_item_ids = set(
            BranchMenuAvailability.objects.filter(branch=branch_obj, is_available=False).values_list("menu_item_id", flat=True)
        )
        all_tenant_items = list(MenuItem.objects.filter(tenant=tenant, available=True).prefetch_related("variants"))

        subtotal = Decimal("0.00")
        order_items_prepared = []

        for idx, item_spec in enumerate(items, start=1):
            menu_item, variant_item, match_err = _find_menu_item(tenant, branch_obj, item_spec, disabled_item_ids, all_tenant_items)
            if match_err:
                if isinstance(match_err, dict):
                    return match_err
                return {
                    "ok": False,
                    "is_system_error": False,
                    "error": match_err,
                    "ai_speech_response": f"يا فندم بخصوص طلبك، {match_err}",
                    "instruction_for_ai": "لا تقل إن هناك عطلاً بالسيستم! أبلغ العميل بما جاء في ai_speech_response واقترح عليه بديلاً متوفراً."
                }

            if isinstance(item_spec, dict):
                try:
                    qty = int(item_spec.get("quantity") or item_spec.get("qty") or 1)
                except (ValueError, TypeError):
                    qty = 1
                item_notes = str(item_spec.get("notes") or item_spec.get("special_instructions") or "").strip()
            else:
                qty = 1
                item_notes = ""

            if qty <= 0:
                continue

            if variant_item:
                item_price = variant_item.get_price_for_branch(branch_obj)
                display_name = f"{menu_item.name} ({variant_item.name})"
                var_name = variant_item.name
            else:
                item_price = menu_item.get_price_for_branch(branch_obj)
                display_name = menu_item.name
                var_name = ""

            line_total = item_price * qty
            subtotal += line_total

            order_items_prepared.append({
                "menu_item": menu_item,
                "variant": variant_item,
                "variant_name": var_name,
                "display_name": display_name,
                "quantity": qty,
                "price": item_price,
                "total": line_total,
                "notes": item_notes,
            })

        if not order_items_prepared:
            return {
                "ok": False,
                "error": "لم يتم العثور على أي أصناف صالحة أو كميات مقبولة في الطلب.",
                "ai_speech_response": "يا فندم محتاجة تحديد الأصناف بوضوح لتسجيل الأوردر.",
                "instruction_for_ai": "اطلب من العميل توضيح طلبه."
            }

        tax_rate = Decimal(str(getattr(branch_obj, "tax_percentage", None) or "0.00"))
        is_tax_inclusive = bool(getattr(branch_obj, "is_tax_inclusive", True))

        if is_tax_inclusive:
            if tax_rate > 0:
                tax_amount = (subtotal - (subtotal / (Decimal("1.00") + (tax_rate / Decimal("100.00"))))).quantize(Decimal("0.01"))
            else:
                tax_amount = Decimal("0.00")
            total = subtotal + delivery_fee
        else:
            tax_amount = (subtotal * (tax_rate / Decimal("100.00"))).quantize(Decimal("0.01"))
            total = subtotal + tax_amount + delivery_fee

        cur_name = branch_obj.get_currency_name_ar()
        cur_sym = branch_obj.get_currency_symbol_ar()

        # Minimum order check for delivery
        if order_type == "delivery":
            dist_val = getattr(matched_area, "distance_km", 0.0)
            min_order_req = branch_obj.get_min_order_for_distance(dist_val)
            if subtotal < min_order_req:
                diff = min_order_req - subtotal
                items_speech = " و ".join([f"{oi['quantity']} {oi['display_name']}" for oi in order_items_prepared])
                return {
                    "ok": False,
                    "is_system_error": False,
                    "error_code": "ERR_MIN_ORDER_NOT_MET",
                    "below_minimum_order": True,
                    "subtotal": float(subtotal),
                    "tax_percentage": float(tax_rate),
                    "is_tax_inclusive": is_tax_inclusive,
                    "tax": float(tax_amount),
                    "minimum_order_required": float(min_order_req),
                    "amount_needed": float(diff),
                    "delivery_fee": float(delivery_fee),
                    "branch_name": branch_obj.name,
                    "currency": branch_obj.currency,
                    "currency_name": cur_name,
                    "currency_symbol": cur_sym,
                    "error": f"حساب أصناف الطلب {subtotal:.0f} {cur_name} وهو أقل من الحد الأدنى لطلب التوصيل ({min_order_req:.0f} {cur_name}).",
                    "ai_speech_response": f"يا فندم الحد الأدنى لطلب التوصيل لمنطقتك هو {min_order_req:.0f} {cur_name}، وحساب أصنافك حالياً {subtotal:.0f} {cur_name} (باقي {diff:.0f} {cur_name}). تحب نضيف لحضرتك مشروب أو صنف إضافي لنصل للحد الأدنى؟",
                    "instruction_for_ai": f"لا تسجل الأوردر الآن! أبلغ العميل بلطف أن طلبه أقل من الحد الأدنى للتوصيل ({min_order_req:.0f} {cur_name}) واطلب منه إضافة أصناف بقيمة {diff:.0f} {cur_name} لتكملة الطلب كما في ai_speech_response."
                }

        # Unique Order Number using Atomic Sequence (<0.05ms)
        date_str = timezone.now().strftime("%Y%m%d")
        b_code = f"B{branch_obj.id}" if branch_obj else "BR"
        base_prefix = f"ORD-{date_str}-{b_code}"
        full_notes = f"[AI Call Center: {key_obj.name}] {notes}".strip()

        order_recipient_name = clean_name or (customer.name if customer else "عميل هاتف")
        order_recipient_addr = clean_addr or (customer.address if customer else "")
        if customer and customer.name and clean_name and clean_name != customer.name and not clean_name.startswith("عميل"):
            recipient_note = f"[المستلم: {clean_name}]"
            if recipient_note not in full_notes:
                full_notes = f"{full_notes} | {recipient_note}".strip(" |")

        # 6. Atomic Order Creation
        with transaction.atomic():
            order = None
            for attempt in range(10):
                next_seq = get_next_order_sequence(tenant.id, branch_obj.id if branch_obj else 0, date_str)
                candidate_num = f"{base_prefix}-{next_seq:04d}"
                while Order.objects.filter(tenant=tenant, order_number=candidate_num).exists():
                    next_seq = get_next_order_sequence(tenant.id, branch_obj.id if branch_obj else 0, date_str)
                    candidate_num = f"{base_prefix}-{next_seq:04d}"
                order_number = candidate_num

                try:
                    sid = transaction.savepoint()
                    db_delivery_area = matched_area if (matched_area and hasattr(matched_area, "pk") and matched_area.pk) else None
                    order_notes = full_notes
                    if matched_area:
                        if not getattr(matched_area, "pk", None):
                            area_tag = f"[منطقة التوصيل المحددة بالخريطة: {getattr(matched_area, 'name', '')}]"
                            if area_tag not in order_notes:
                                order_notes = f"{order_notes} | {area_tag}".strip(" |")
                        if getattr(matched_area, "notes", None) and str(matched_area.notes) not in order_notes:
                            order_notes = f"{order_notes} | {matched_area.notes}".strip(" |")

                    order = Order.objects.create(
                        tenant=tenant,
                        branch=branch_obj,
                        order_number=order_number,
                        order_type=order_type,
                        channel="call_center",
                        customer=customer,
                        customer_name=order_recipient_name,
                        customer_phone=clean_phone if clean_phone else (customer.phone if customer else ""),
                        address=order_recipient_addr,
                        delivery_area=db_delivery_area,
                        subtotal=subtotal,
                        tax_percentage=tax_rate,
                        tax=tax_amount,
                        delivery_fee=delivery_fee,
                        discount=Decimal("0.00"),
                        total=total,
                        pay_method="cash",
                        paid=False,
                        cashier=f"AI: {key_obj.name}",
                        notes=order_notes,
                        status="new",
                    )
                    transaction.savepoint_commit(sid)
                    break
                except IntegrityError:
                    transaction.savepoint_rollback(sid)
                    continue

            if not order:
                return {"error": "فشل إنشاء الطلب بسبب تضارب أرقام الطلبات المتزامنة."}

            for oi in order_items_prepared:
                raw_item_notes = str(oi.get("notes") or "").strip()
                item_display_name = oi["display_name"]
                if raw_item_notes and f"({raw_item_notes})" not in item_display_name:
                    item_display_name = f"{item_display_name} ({raw_item_notes})"

                OrderItem.objects.create(
                    order=order,
                    menu_item=oi["menu_item"],
                    variant=oi["variant"],
                    variant_name=oi["variant_name"],
                    name=item_display_name,
                    price=oi["price"],
                    qty=oi["quantity"],
                    notes=raw_item_notes,
                )

            from core.models import log_audit_event
            cust_label = customer.name if customer else "عميل"
            log_audit_event(
                tenant=tenant,
                user=None,
                action="order_created",
                target_model="Order",
                target_id=order.id,
                description=f"إنشاء الطلب #{order.order_number} تلقائياً عبر كول سنتر الذكاء الاصطناعي ({key_obj.name}) للعميل {cust_label} بقيمة {order.total} {branch_obj.get_currency_symbol_ar()}",
                ip_address=None,
            )

        # Clear draft cart session upon successful order creation
        try:
            redis_cart_clear(tenant.id, clean_phone)
        except Exception as e:
            logger.warning(f"Failed to clear cart after order creation: {e}")

        # Real-time SSE push to kitchen display & Redis active order cache
        try:
            from core.kitchen_events import notify_kitchen_order_event
            notify_kitchen_order_event(order, "new_order")
        except Exception as e:
            logger.warning(f"Failed to notify kitchen of AI order: {e}")

        try:
            cache_active_order(order)
        except Exception as e:
            logger.warning(f"Failed to cache active order in Redis: {e}")

        key_obj.record_usage(placed_order=True)

        est_time = f"{matched_area.estimated_time_minutes} دقيقة" if (matched_area and matched_area.estimated_time_minutes) else "30 إلى 45 دقيقة"
        items_speech = " و ".join([f"{oi['quantity']} {oi['display_name']}" for oi in order_items_prepared])
        tax_speech = f" (شامل الضريبة {tax_rate:.0f}%)" if (is_tax_inclusive and tax_rate > 0) else (f" والضريبة {tax_amount:.0f} {cur_name}" if tax_rate > 0 else "")
        if order_type == "delivery":
            speech = f"تم تسجيل طلبك بنجاح برقم {order.order_number}! الطلب: ({items_speech}) بإجمالي {total:.0f} {cur_name}{tax_speech} والدفع نقداً عند الاستلام، ويوصل لحضرتك خلال {est_time} تقريباً، وبعت لحضرتك تفاصيل الفاتورة ورابط المتابعة على الواتساب دلوقتي."
        else:
            speech = f"تم تسجيل طلبك بنجاح برقم {order.order_number}! الطلب: ({items_speech}) بإجمالي {total:.0f} {cur_name}{tax_speech} والدفع نقداً، وتقدر تستلمه من فرع {branch_obj.name} خلال {est_time}، وبعت لحضرتك تفاصيل الفاتورة على الواتساب دلوقتي."

        # Automatic Instant WhatsApp Confirmation (Preserved 100% exactly as-is!)
        try:
            from core import partner_service as ps
            wa_cid = getattr(tenant, "voice_client_id", None) or ps.get_client_id_for_tenant(tenant)
            if wa_cid and clean_phone and clean_phone != "web_dashboard" and "dashboard" not in str(clean_phone).lower() and clean_phone != "0559998877":
                items_lines = "\n".join([f"• {oi['quantity']} × {oi['display_name']} ({oi['total']:.0f} {cur_sym})" for oi in order_items_prepared])

                domain = os.environ.get("DOMAIN_NAME", "uggu.space").strip().rstrip("/")
                if not domain.startswith("http"):
                    domain = f"https://{domain}"
                menu_track_url = f"{domain}/m/{tenant.slug}/?order={order.order_number}"

                tax_line = f"🏷️ *الضريبة:* مشمولة بالأسعار ({tax_rate:.0f}%)\n" if (is_tax_inclusive and tax_rate > 0) else (f"🏷️ *الضريبة ({tax_rate:.0f}%):* {tax_amount:.0f} {cur_sym}\n" if tax_rate > 0 else "")

                wa_text = (
                    f"🧾 *تأكيد طلبك من مطعم {tenant.name}*\n"
                    f"📍 *الفرع:* {branch_obj.name}\n"
                    f"🔢 *رقم الطلب:* #{order.order_number}\n\n"
                    f"🍔 *الأصناف المطلوبة:*\n{items_lines}\n\n"
                    f"💰 *المجموع:* {subtotal:.0f} {cur_sym}\n"
                    f"{tax_line}"
                    f"🛵 *رسوم التوصيل:* {delivery_fee:.0f} {cur_sym}\n"
                    f"💵 *الإجمالي المطلوب:* {total:.0f} {cur_sym}\n\n"
                    f"🏠 *عنوان التوصيل:* {order_recipient_addr or 'استلام من الفرع'}\n"
                    f"⏱️ *وقت التوصيل المتوقع:* {est_time}\n\n"
                    f"🔗 *متابعة وتتبع حالة الطلب:*\n{menu_track_url}\n\n"
                    f"⭐ *رأيك يهمنا جداً!*\n"
                    f"كيف كانت تجربتك في المكالمة مع مساعدنا الصوتي الذكي؟ شاركنا تقييمك من 1 إلى 5 نجوم (أو أي ملاحظة) بالرد على هذه الرسالة.\n\n"
                    f"شكراً لطلبك! نسعد دائماً بخدمتكم."
                )
                def _send_wa_async():
                    close_old_connections()
                    try:
                        ps.send_whatsapp_message(wa_cid, clean_phone, wa_text)
                    except Exception as ex:
                        logger.warning(f"Error sending WhatsApp message: {ex}")
                    finally:
                        close_old_connections()
                wa_thread = threading.Thread(target=_send_wa_async, daemon=True)
                wa_thread.start()
        except Exception as e:
            logger.warning(f"Error initiating auto WhatsApp confirmation: {e}")

        return {
            "ok": True,
            "message": f"تم إنشاء الأوردر بنجاح برقم {order.order_number}",
            "order_number": order.order_number,
            "currency": branch_obj.currency,
            "currency_name": cur_name,
            "currency_symbol": cur_sym,
            "customer_recognized": customer_recognized,
            "used_draft_cart": used_cart_checkout,
            "ai_speech_response": speech,
            "instruction_for_ai": "اقرأ للعميل نص ai_speech_response لتأكيد رقم الأوردر والإجمالي ووقت التوصيل.",
            "order": {
                "id": order.id,
                "order_number": order.order_number,
                "branch_name": branch_obj.name,
                "currency": branch_obj.currency,
                "currency_name": cur_name,
                "currency_symbol": cur_sym,
                "order_type": order.get_order_type_display(),
                "status": order.get_status_display(),
                "status_code": order.status,
                "customer_name": order.customer_name,
                "customer_phone": order.customer_phone,
                "delivery_address": order.address,
                "subtotal": float(order.subtotal or 0.0),
                "tax_percentage": float(order.tax_percentage or 0.0),
                "is_tax_inclusive": is_tax_inclusive,
                "tax": float(order.tax or 0.0),
                "delivery_fee": float(order.delivery_fee or 0.0),
                "total": float(order.total or 0.0),
                "created_at": order.created_at.strftime("%Y-%m-%d %H:%M"),
                "items": [
                    {
                        "name": oi["display_name"],
                        "quantity": oi["quantity"],
                        "price": float(oi["price"]),
                        "total": float(oi["total"]),
                        "notes": oi["notes"]
                    }
                    for oi in order_items_prepared
                ]
            }
        }
    finally:
        close_old_connections()


# =====================================================================
# 7.5. Dedicated Cart Checkout Tool
# =====================================================================

@mcp.tool
def checkout_cart(
    customer_phone: str,
    customer_name: Optional[str] = "",
    customer_address: Optional[str] = "",
    order_type: str = "delivery",
    branch_id: Optional[int] = None,
    delivery_area_name: Optional[str] = None,
    delivery_area_id: Optional[int] = None,
    notes: str = "",
    phone: Optional[str] = None,
    address: Optional[str] = None,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    تأكيد وتنفيذ الطلب مباشرة من سلة المشتريات المؤقتة للعميل (Draft Cart Checkout) دون الحاجة لإعادة تمرير قائمة الأصناف.
    يُستخدم عند رغبة العميل في إتمام الطلب أو بعد موافقته على استئناف سلة مكالمة سابقة منقطعة.
    """
    target_phone = str(customer_phone or phone or "").strip()
    clean_p = _clean_phone(target_phone)
    if not clean_p:
        return {
            "ok": False,
            "is_system_error": False,
            "error_code": "ERR_PHONE_REQUIRED",
            "status": "phone_required",
            "error": "رقم هاتف العميل مطلوب لتنفيذ الطلب من السلة.",
            "ai_speech_response": "يا فندم محتاجة رقم تليفون حضرتك عشان نقدر نأكد الطلب من السلة.",
            "instruction_for_ai": "اطلب من العميل تزويدك برقم هاتفه."
        }

    return create_callcenter_order(
        phone=clean_p,
        items=None,
        customer_name=customer_name,
        address=customer_address or address or "",
        order_type=order_type,
        branch_id=branch_id,
        delivery_area_name=delivery_area_name,
        delivery_area_id=delivery_area_id,
        notes=notes,
        access_key=access_key,
    )


# =====================================================================
# 8. Order Tracking Tool
# =====================================================================

@mcp.tool
def track_order(
    order_number: Optional[str] = None,
    customer_phone: Optional[str] = None,
    phone: Optional[str] = None,
    phone_number: Optional[str] = None,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    تتبع حالة الأوردر للرد على العميل المتصل ومعرفة موقفه (في المطبخ / مع الدليفري / تم التسليم).
    """
    close_old_connections()
    try:
        key_obj, tenant = _authenticate(access_key)
        from core.models import Order

        raw_query = str(order_number or "").strip()
        raw_phone = str(customer_phone or phone or phone_number or "").strip()

        # Diagnostic call
        if not raw_query and not raw_phone:
            return {
                "ok": True,
                "status": "ready",
                "message": "أداة تتبع حالة الأوردرات (track_order) جاهزة ونشطة بنجاح.",
                "diagnostic": True
            }

        norm_query = _normalize_digits(raw_query)
        norm_phone = _clean_phone(raw_phone)

        if not norm_phone and re.match(r'^\+?[0-9]{8,15}$', norm_query):
            norm_phone = _clean_phone(norm_query)

        order = None
        customer_orders = []

        # 0. Redis Ultra-Fast Active Order Track (<0.2ms)
        redis_order = None
        if norm_query:
            redis_order = get_active_order_by_number(tenant.id, norm_query)
        if not redis_order and norm_phone:
            redis_order = get_active_order_by_phone(tenant.id, norm_phone)

        if redis_order:
            status_code = redis_order.get("status", "new")
            status_speech_map = {
                "new": "طلبك مسجل وجاري إرساله للمطبخ.",
                "preparing": "طلبك حالياً بيتجهز في المطبخ بكل اهتمام.",
                "ready": "طلبك جاهز تماماً وبانتظار مندوب التوصيل للاستلام.",
                "out_for_delivery": "طلبك خرج مع المندوب وفي الطريق لحضرتك حالياً.",
                "on_way": "طلبك خرج مع المندوب وفي الطريق لحضرتك حالياً.",
                "delivered": "الطلب مسجل عندنا إنه تم تسليمه بنجاح.",
                "cancelled": "الطلب مسجل إنه ملغي.",
                "canceled": "الطلب مسجل إنه ملغي.",
            }
            speech_state = status_speech_map.get(status_code, f"حالة طلبك الحالية هي {redis_order.get('status_display', status_code)}.")
            ai_speech = f"يا فندم بخصوص طلبك رقم {redis_order.get('order_number')}، {speech_state}"
            key_obj.record_usage(placed_order=False)
            return {
                "ok": True,
                "matched_by": "redis_cache",
                "ai_speech_response": ai_speech,
                "instruction_for_ai": "أبلغ العميل بحالة طلبه كما هو موضح في ai_speech_response.",
                "order": {
                    "id": redis_order.get("order_id"),
                    "order_number": redis_order.get("order_number"),
                    "branch_name": redis_order.get("branch_name", "الفرع الرئيسي"),
                    "status_code": status_code,
                    "status_display": redis_order.get("status_display", status_code),
                    "status_label": redis_order.get("status_display", status_code),
                    "customer_name": redis_order.get("customer_name", ""),
                    "customer_phone": redis_order.get("customer_phone", ""),
                    "delivery_address": redis_order.get("address", ""),
                    "subtotal": float(redis_order.get("subtotal", 0)),
                    "total": float(redis_order.get("total", 0)),
                    "tax": float(redis_order.get("tax", 0)),
                    "delivery_fee": float(redis_order.get("delivery_fee", 0)),
                    "items_summary": redis_order.get("items_summary", ""),
                    "currency_symbol": redis_order.get("currency_symbol", "ر.س"),
                }
            }

        # 1. Search by exact order_number
        if norm_query:
            order = Order.objects.filter(tenant=tenant, order_number__iexact=norm_query).select_related("branch", "customer", "driver").first()

            if not order:
                prefix = (tenant.slug[:3] if tenant and tenant.slug else "ORD").upper()
                for pfx in [prefix, "DIY", "ORD", "CC"]:
                    if not norm_query.upper().startswith(f"{pfx}-"):
                        candidate = Order.objects.filter(tenant=tenant, order_number__iexact=f"{pfx}-{norm_query}").select_related("branch", "customer", "driver").first()
                        if candidate:
                            order = candidate
                            break

            if not order:
                num_matches = re.findall(r'\d{3,5}', norm_query)
                for num in num_matches:
                    found = Order.objects.filter(tenant=tenant, order_number__icontains=num).select_related("branch", "customer", "driver").order_by("-created_at").first()
                    if found:
                        order = found
                        break

            if not order and norm_query.isdigit():
                order = Order.objects.filter(tenant=tenant, id=int(norm_query)).select_related("branch", "customer", "driver").first()

        # 2. Search by customer phone
        if not order and norm_phone:
            suffix = norm_phone[-9:] if len(norm_phone) >= 9 else norm_phone
            phone_orders_qs = Order.objects.filter(tenant=tenant).filter(
                models.Q(customer_phone__icontains=suffix) | models.Q(customer__phone__icontains=suffix)
            ).select_related("branch", "customer", "driver").order_by("-created_at")

            customer_orders = list(phone_orders_qs[:5])
            if customer_orders:
                active_orders = [o for o in customer_orders if o.status in ["new", "preparing", "ready", "out_for_delivery", "on_way"]]
                order = active_orders[0] if active_orders else customer_orders[0]

        if order and order.status in ["new", "preparing", "ready", "out_for_delivery", "on_way"]:
            try:
                cache_active_order(order)
            except Exception:
                pass

        if not order:
            key_obj.record_usage(placed_order=False)
            identifier = raw_query or raw_phone or "المحدد"
            return {
                "ok": False,
                "error": f"لم يتم العثور على أي أوردر بالمعرف أو رقم الهاتف «{identifier}» في سجلات المطعم.",
                "searched_value": identifier,
                "ai_speech_response": "بعتذر لحضرتك، مش لاقية أي أوردر مسجل بالبيانات دي. ممكن تتأكد من رقم الأوردر أو تديني رقم التليفون اللي سجلت بيه الطلب؟",
                "instruction_for_ai": "لا تقل إن هناك عطلاً بالسيستم! أبلغ العميل بلطف بعدم العثور على الأوردر واطلب منه رقم الجوال للبحث به كما في ai_speech_response."
            }

        status_speech_map = {
            "new": "طلبك مسجل وجاري إرساله للمطبخ.",
            "preparing": "طلبك حالياً بيتجهز في المطبخ بكل اهتمام.",
            "ready": "طلبك جاهز تماماً وبانتظار مندوب التوصيل للاستلام.",
            "out_for_delivery": "طلبك خرج مع المندوب وفي الطريق لحضرتك حالياً.",
            "on_way": "طلبك خرج مع المندوب وفي الطريق لحضرتك حالياً.",
            "delivered": "الطلب مسجل عندنا إنه تم تسليمه بنجاح.",
            "cancelled": "الطلب مسجل إنه ملغي.",
            "canceled": "الطلب مسجل إنه ملغي.",
        }
        speech_state = status_speech_map.get(order.status, f"حالة طلبك الحالية هي {order.get_status_display()}.")
        driver_speech = f" مع الكابتن {order.driver.name} ورقم هاتفه {order.driver.phone}" if (order.driver and order.status in ["out_for_delivery", "on_way"]) else ""
        ai_speech = f"يا فندم بخصوص طلبك رقم {order.order_number}، {speech_state}{driver_speech}."

        driver_info = None
        if order.driver:
            driver_info = {
                "name": order.driver.name,
                "phone": order.driver.phone or "غير مسجل",
            }

        items_data = [
            {"name": it.name, "quantity": it.qty, "price": float(it.price), "total": float(it.line_total)}
            for it in order.items.all()
        ]

        other_orders_summary = []
        if customer_orders and len(customer_orders) > 1:
            other_orders_summary = [
                {
                    "order_number": o.order_number,
                    "status": o.get_status_display(),
                    "total": float(o.total),
                    "created_at": o.created_at.strftime("%Y-%m-%d %H:%M"),
                }
                for o in customer_orders if o.id != order.id
            ]

        key_obj.record_usage(placed_order=False)
        return {
            "ok": True,
            "matched_by": "customer_phone" if (norm_phone and (raw_phone or not raw_query.startswith("DIY-"))) else "order_number",
            "ai_speech_response": ai_speech,
            "instruction_for_ai": "أبلغ العميل بحالة طلبه كما هو موضح في ai_speech_response.",
            "order": {
                "id": order.id,
                "order_number": order.order_number,
                "branch_name": order.branch.name if order.branch else "غير محدد",
                "status_code": order.status,
                "status_label": order.get_status_display(),
                "order_type": order.get_order_type_display(),
                "customer_name": order.customer_name,
                "customer_phone": order.customer_phone,
                "delivery_address": order.address,
                "subtotal": float(order.subtotal or 0.0),
                "tax_percentage": float(order.tax_percentage or 0.0),
                "tax": float(order.tax or 0.0),
                "delivery_fee": float(order.delivery_fee or 0.0),
                "total": float(order.total or 0.0),
                "currency": order.branch.currency if order.branch else "SAR",
                "currency_name": order.branch.get_currency_name_ar() if order.branch else "ريال",
                "currency_symbol": order.branch.get_currency_symbol_ar() if order.branch else "ر.س",
                "driver": driver_info,
                "items": items_data,
                "created_at": order.created_at.strftime("%Y-%m-%d %H:%M"),
            },
            "other_recent_orders": other_orders_summary,
        }
    finally:
        close_old_connections()


# =====================================================================
# 9. Order Cancellation Tool
# =====================================================================

@mcp.tool
def cancel_order(
    order_number: Optional[str] = None,
    customer_phone: Optional[str] = None,
    phone: Optional[str] = None,
    phone_number: Optional[str] = None,
    reason: str = "طلب العميل عبر الهاتف",
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    إلغاء أوردر تم طلبه حديثاً بشرط أن يكون الأوردر لا يزال في حالة 'جديد' (new) ولم يبدأ المطبخ في تحضيره.
    """
    close_old_connections()
    try:
        key_obj, tenant = _authenticate(access_key)
        from core.models import Order

        raw_query = str(order_number or "").strip()
        raw_phone = str(customer_phone or phone or phone_number or "").strip()

        # Diagnostic call
        if not raw_query and not raw_phone:
            return {
                "ok": True,
                "status": "ready",
                "message": "أداة إلغاء الأوردرات الجديدة (cancel_order) جاهزة ونشطة بنجاح.",
                "diagnostic": True
            }

        norm_query = _normalize_digits(raw_query)
        norm_phone = _clean_phone(raw_phone)

        if not norm_phone and re.match(r'^\+?[0-9]{8,15}$', norm_query):
            norm_phone = _clean_phone(norm_query)

        order = None

        if norm_query:
            order = Order.objects.filter(tenant=tenant, order_number__iexact=norm_query).select_related("branch", "customer").first()
            if not order:
                prefix = (tenant.slug[:3] if tenant and tenant.slug else "ORD").upper()
                for pfx in [prefix, "DIY", "ORD", "CC"]:
                    if not norm_query.upper().startswith(f"{pfx}-"):
                        candidate = Order.objects.filter(tenant=tenant, order_number__iexact=f"{pfx}-{norm_query}").select_related("branch", "customer").first()
                        if candidate:
                            order = candidate
                            break

            if not order:
                num_matches = re.findall(r'\d{3,5}', norm_query)
                for num in num_matches:
                    found = Order.objects.filter(tenant=tenant, order_number__icontains=num).select_related("branch", "customer").order_by("-created_at").first()
                    if found:
                        order = found
                        break

            if not order and norm_query.isdigit():
                order = Order.objects.filter(tenant=tenant, id=int(norm_query)).select_related("branch", "customer").first()

        if not order and norm_phone:
            suffix = norm_phone[-9:] if len(norm_phone) >= 9 else norm_phone
            phone_orders_qs = Order.objects.filter(tenant=tenant).filter(
                models.Q(customer_phone__icontains=suffix) | models.Q(customer__phone__icontains=suffix)
            ).select_related("branch", "customer").order_by("-created_at")

            active_orders = [o for o in phone_orders_qs[:5] if o.status in ["new", "preparing", "ready", "out_for_delivery", "on_way"]]
            order = active_orders[0] if active_orders else phone_orders_qs.first()

        if not order:
            key_obj.record_usage(placed_order=False)
            identifier = raw_query or raw_phone or "غير محدد"
            return {
                "ok": False,
                "is_system_error": False,
                "error_code": "ERR_ORDER_NOT_FOUND",
                "error": f"لم يتم العثور على أي أوردر بالمعرف أو رقم الهاتف «{identifier}» لإلغائه.",
                "ai_speech_response": "مش لاقية أي أوردر مسجل بالبيانات دي عشان أقدر ألغيه لحضرتك. تحب تديني رقم تليفونك أبحث بيه؟",
                "instruction_for_ai": "لا تقل إن هناك عطلاً بالسيستم! أبلغ العميل بعدم العثور على الأوردر واطلب منه رقم الجوال للبحث به كما في ai_speech_response."
            }

        if order.status in ["cancelled", "canceled"]:
            key_obj.record_usage(placed_order=False)
            return {
                "ok": False,
                "is_system_error": False,
                "error_code": "ERR_ORDER_ALREADY_CANCELLED",
                "error": f"هذا الأوردر برقم «{order.order_number}» ملغي بالفعل مسبقاً.",
                "order_number": order.order_number,
                "current_status": "ملغي",
                "ai_speech_response": f"يا فندم الأوردر رقم {order.order_number} ملغي بالفعل من قبل كده.",
                "instruction_for_ai": "أخبر العميل أن هذا الطلب ملغي بالفعل مسبقاً كما في ai_speech_response."
            }
        elif order.status != "new":
            status_label = order.get_status_display()
            key_obj.record_usage(placed_order=False)
            return {
                "ok": False,
                "is_system_error": False,
                "error_code": "ERR_ORDER_IN_PREPARATION",
                "error": f"عذراً، الأوردر برقم «{order.order_number}» في مرحلة «{status_label}» ولا يمكن إلغاؤه آلياً لأن المطبخ بدأ في تحضيره بالفعل.",
                "order_number": order.order_number,
                "current_status": status_label,
                "ai_speech_response": f"بعتذر جداً لحضرتك، الأوردر رقم {order.order_number} دخل مرحلة التحضير في المطبخ ومبنقدرش نلغيه بعد ما بدأوا فيه. تحب أحول حضرتك لخدمة العملاء أو مدير الفرع؟",
                "instruction_for_ai": "أبلغ العميل بلطف أن الطلب دخل مرحلة التحضير في المطبخ ولا يمكن إلغاؤه كما في ai_speech_response."
            }

        branch_obj = order.branch
        window_minutes = int(getattr(branch_obj, "cancellation_window_minutes", 10)) if branch_obj else 10
        elapsed_seconds = (timezone.now() - order.created_at).total_seconds()
        if elapsed_seconds > (window_minutes * 60):
            elapsed_minutes = int(elapsed_seconds // 60)
            key_obj.record_usage(placed_order=False)
            return {
                "ok": False,
                "is_system_error": False,
                "error_code": "ERR_ORDER_CANCEL_WINDOW_EXPIRED",
                "error": f"عذراً، لقد مضت {elapsed_minutes} دقيقة على إنشاء الأوردر رقم «{order.order_number}»، وتجاوز مهلة الإلغاء المحددة للفرع ({window_minutes} دقيقة). الطلب قيد التجهيز ولا يمكن إلغاؤه آلياً.",
                "order_number": order.order_number,
                "created_at": order.created_at.strftime("%Y-%m-%d %H:%M"),
                "cancellation_window_minutes": window_minutes,
                "ai_speech_response": f"بعتذر لحضرتك، الأوردر رقم {order.order_number} مر عليه أكثر من {window_minutes} دقائق وهو قيد التجهيز حالياً بالمطبخ ولا يمكن إلغاؤه آلياً. تحب أحولك لخدمة العملاء أو مدير الفرع للمساعدة؟",
                "instruction_for_ai": "أبلغ العميل بلطف أن مهلة الإلغاء المسموح بها قد انتهت والطلب قيد التجهيز بالمطبخ كما في ai_speech_response."
            }

        order.status = "cancelled"
        cancel_note = f"[تم الإلغاء آلياً بواسطة بوت الكول سنتر: {key_obj.name} - السبب: {reason}]"
        if order.notes:
            order.notes = f"{order.notes}\n{cancel_note}"
        else:
            order.notes = cancel_note
        order.save()

        try:
            from core.kitchen_events import notify_kitchen_order_event
            notify_kitchen_order_event(order, "order_cancelled")
        except Exception as e:
            logger.warning(f"Failed to notify kitchen of AI cancelled order: {e}")

        try:
            remove_active_order(tenant.id, order.order_number)
        except Exception as e:
            logger.warning(f"Failed to remove active order from Redis: {e}")

        key_obj.record_usage(placed_order=False)
        return {
            "ok": True,
            "message": f"تم إلغاء الأوردر برقم {order.order_number} بنجاح.",
            "order_number": order.order_number,
            "status": "ملغي",
            "cancelled_at": timezone.now().strftime("%Y-%m-%d %H:%M"),
            "ai_speech_response": f"تمام يا فندم، تم إلغاء الأوردر رقم {order.order_number} بنجاح. أقدر أساعد حضرتك في أي طلب تاني؟",
            "instruction_for_ai": f"أبلغ العميل بأنه تم إلغاء الأوردر رقم {order.order_number} بنجاح كما في ai_speech_response، واسأله إذا كان يرغب في أي خدمة أخرى."
        }
    finally:
        close_old_connections()


# =====================================================================
# 10. Recent Orders List Tool
# =====================================================================

@mcp.tool
def list_recent_orders(
    branch_id: Optional[int] = None,
    limit: int = 10,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    استعراض أحدث الأوردرات لمراقبة حركة الطلبات في المنشأة أو الفرع.
    """
    close_old_connections()
    try:
        key_obj, tenant = _authenticate(access_key)
        from core.models import Order

        qs = Order.objects.filter(tenant=tenant).select_related("branch", "customer")
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        elif key_obj.assigned_branch:
            qs = qs.filter(branch=key_obj.assigned_branch)

        orders = qs.order_by("-created_at")[:min(limit, 50)]
        orders_data = [
            {
                "id": o.id,
                "order_number": o.order_number,
                "branch": o.branch.name if o.branch else "الفرع الرئيسي",
                "customer_name": o.customer_name,
                "order_type": o.get_order_type_display(),
                "status": o.get_status_display(),
                "total": float(o.total),
                "created_at": o.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for o in orders
        ]

        key_obj.record_usage(placed_order=False)
        return {
            "ok": True,
            "tenant_name": tenant.name,
            "count": len(orders_data),
            "orders": orders_data,
        }
    finally:
        close_old_connections()


# =====================================================================
# 11. Conversational Draft Cart Tools (سلة المشتريات المؤقتة في الذاكرة اللحظية)
# =====================================================================

@mcp.tool
def cart_add_item(
    customer_phone: str,
    item_name: str,
    quantity: int = 1,
    variant: Optional[str] = None,
    notes: Optional[str] = None,
    branch_id: Optional[int] = None,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    إضافة صنف أو وجبة لسلة المشتريات المؤقتة الخاصة بالعميل (Draft Cart) أثناء المكالمة.
    """
    return handle_cart_add_item(
        customer_phone=customer_phone,
        item_name=item_name,
        quantity=quantity,
        variant=variant,
        notes=notes,
        branch_id=branch_id,
        access_key=access_key,
    )


@mcp.tool
def cart_view(
    customer_phone: str,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    عرض تفاصيل ومجموع سلة المشتريات المؤقتة للعميل للرد الصوتي السريع أثناء المكالمة.
    """
    return handle_cart_view(
        customer_phone=customer_phone,
        access_key=access_key,
    )


@mcp.tool
def cart_remove_item(
    customer_phone: str,
    item_name_or_index: str,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    حذف صنف من سلة المشتريات المؤقتة للعميل بالاسم أو بالترتيب.
    """
    return handle_cart_remove_item(
        customer_phone=customer_phone,
        item_name_or_index=item_name_or_index,
        access_key=access_key,
    )


@mcp.tool
def cart_clear(
    customer_phone: str,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    تفريغ سلة المشتريات المؤقتة للعميل بالكامل.
    """
    return handle_cart_clear(
        customer_phone=customer_phone,
        access_key=access_key,
    )
