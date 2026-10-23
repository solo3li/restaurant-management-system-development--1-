import logging
from typing import Optional, Dict, Any
from django.db import close_old_connections

from core.mcp.middleware import _authenticate
from core.mcp.resolvers import _find_menu_item, _resolve_item_variant, _clean_phone
from core.redis_mcp_cache import (
    cart_add_item as redis_cart_add,
    cart_get as redis_cart_get,
    cart_remove_item as redis_cart_remove,
    cart_clear as redis_cart_clear,
)

logger = logging.getLogger(__name__)


def handle_cart_add_item(
    customer_phone: str,
    item_name: str,
    quantity: int = 1,
    variant: Optional[str] = None,
    notes: Optional[str] = None,
    branch_id: Optional[int] = None,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    إضافة صنف أو وجبة إلى سلة المشتريات المؤقتة للعميل (Draft Cart Session) في الذاكرة اللحظية Redis.
    تتيح لموظف الذكاء الاصطناعي إضافة الطلبات خطوة بخطوة أثناء المحادثة بسلاسة تامة.
    """
    clean_p = _clean_phone(customer_phone)
    if not clean_p:
        return {
            "ok": False,
            "status": "error",
            "error": "رقم هاتف العميل مطلوب لتسجيل الأصناف في السلة المؤقتة.",
            "ai_speech_response": "من فضلك يا فندم رقم التليفون لتسجيل الأصناف في طلبك."
        }

    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch, BranchMenuAvailability

    # Resolve Branch
    branch = None
    if branch_id is not None:
        branch = Branch.objects.filter(tenant=tenant, id=branch_id, status="active").first()
    elif key_obj.assigned_branch:
        branch = key_obj.assigned_branch

    disabled_item_ids = set()
    if branch:
        disabled_item_ids = set(
            BranchMenuAvailability.objects.filter(branch=branch, is_available=False).values_list("menu_item_id", flat=True)
        )

    # 1. Match Item using our unified fuzzy canonical resolver
    matched_item, matched_variant_from_name, err = _find_menu_item(
        tenant, branch, item_name, disabled_item_ids
    )

    if err or not matched_item:
        close_old_connections()
        if isinstance(err, dict):
            return err
        return {
            "ok": False,
            "status": "error",
            "error": f"لم يتم العثور على الصنف «{item_name}» في قائمة الطعام.",
            "ai_speech_response": f"بعتذر لحضرتك، الصنف «{item_name}» مش موجود في المنيو حالياً. تحب أرشحلك أصناف تانية؟"
        }

    # 2. Resolve Variant if applicable
    selected_variant = None
    item_spec = {"name": item_name, "variant": variant or ""}
    variant_obj, var_err = _resolve_item_variant(matched_item, branch, item_spec, item_name)
    if var_err:
        close_old_connections()
        return var_err

    selected_variant = variant_obj or matched_variant_from_name

    # 3. Calculate unit price
    if selected_variant:
        unit_price = float(selected_variant.get_price_for_branch(branch))
        variant_name = selected_variant.name
    else:
        unit_price = float(matched_item.get_price_for_branch(branch))
        variant_name = None

    qty = max(1, int(quantity or 1))

    # 4. Save to Redis Cart
    item_data = {
        "item_id": matched_item.id,
        "name": matched_item.name,
        "quantity": qty,
        "variant": variant_name,
        "price": unit_price,
        "notes": notes.strip() if notes else None,
    }

    updated_cart = redis_cart_add(tenant.id, clean_p, item_data)
    key_obj.record_usage(placed_order=False)
    close_old_connections()

    # Calculate current total
    cart_total = sum(float(i.get("price", 0)) * int(i.get("quantity", 1)) for i in updated_cart.get("items", []))
    items_count = updated_cart.get("items_count", 0)

    variant_desc = f" ({variant_name})" if variant_name else ""
    speech = f"تمام يا فندم، ضفت {qty} {matched_item.name}{variant_desc} للسلة. إجمالي السلة حالياً {items_count} صنف بمبلغ {cart_total:.2f} جنيه. تحب تضيف حاجة تانية؟"

    return {
        "ok": True,
        "status": "success",
        "action": "cart_add_item",
        "added_item": item_data,
        "cart": updated_cart,
        "cart_total": round(cart_total, 2),
        "ai_speech_response": speech
    }


def handle_cart_view(
    customer_phone: str,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    استعراض محتويات السلة المؤقتة للعميل والمجموع التقديري للأصناف.
    """
    clean_p = _clean_phone(customer_phone)
    if not clean_p:
        return {
            "ok": False,
            "status": "error",
            "error": "رقم هاتف العميل مطلوب لعرض السلة المؤقتة.",
            "ai_speech_response": "من فضلك يا فندم محتاج رقم تليفون حضرتك لعرض السلة."
        }

    key_obj, tenant = _authenticate(access_key)
    cart = redis_cart_get(tenant.id, clean_p)
    items = cart.get("items", [])

    if not items:
        close_old_connections()
        return {
            "ok": True,
            "status": "success",
            "cart": cart,
            "items_count": 0,
            "cart_total": 0.0,
            "message": "السلة فارغة حالياً.",
            "ai_speech_response": "سلة حضرتك فاضية حالياً يا فندم. تحب تطلب إيه من المنيو؟"
        }

    total = sum(float(i.get("price", 0)) * int(i.get("quantity", 1)) for i in items)
    items_summary = []
    for it in items:
        v_str = f" ({it['variant']})" if it.get("variant") else ""
        items_summary.append(f"{it['quantity']} {it['name']}{v_str}")

    summary_text = "، ".join(items_summary)
    speech = f"سلتك فيها حالياً: {summary_text}. الإجمالي {round(total, 2)} جنيه. تحب نأكد الطلب ولا حابب تعدل حاجة؟"

    close_old_connections()
    return {
        "ok": True,
        "status": "success",
        "cart": cart,
        "items_count": cart.get("items_count", len(items)),
        "cart_total": round(total, 2),
        "summary": summary_text,
        "ai_speech_response": speech
    }


def handle_cart_remove_item(
    customer_phone: str,
    item_name_or_index: str,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    حذف صنف محدد من سلة العميل المؤقتة بالاسم أو برقم الترتيب.
    """
    clean_p = _clean_phone(customer_phone)
    if not clean_p:
        return {
            "ok": False,
            "status": "error",
            "error": "رقم هاتف العميل مطلوب لتعديل السلة.",
            "ai_speech_response": "من فضلك يا فندم رقم التليفون لتعديل السلة."
        }

    key_obj, tenant = _authenticate(access_key)
    updated_cart = redis_cart_remove(tenant.id, clean_p, item_name_or_index)
    items = updated_cart.get("items", [])
    total = sum(float(i.get("price", 0)) * int(i.get("quantity", 1)) for i in items)

    if not items:
        speech = "تمام يا فندم، حذفت الصنف وبكده سلتك بقت فاضية. تحب تطلب أي حاجة تانية؟"
    else:
        speech = f"تمام يا فندم، حذفت الصنف من السلة. باقي في السلة {updated_cart.get('items_count', len(items))} صنف بإجمالي {round(total, 2)} جنيه."

    close_old_connections()
    return {
        "ok": True,
        "status": "success",
        "action": "cart_remove_item",
        "cart": updated_cart,
        "cart_total": round(total, 2),
        "ai_speech_response": speech
    }


def handle_cart_clear(
    customer_phone: str,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    إفراغ سلة العميل المؤقتة بالكامل.
    """
    clean_p = _clean_phone(customer_phone)
    if not clean_p:
        return {
            "ok": False,
            "status": "error",
            "error": "رقم هاتف العميل مطلوب لتفريغ السلة."
        }

    key_obj, tenant = _authenticate(access_key)
    redis_cart_clear(tenant.id, clean_p)
    close_old_connections()

    return {
        "ok": True,
        "status": "success",
        "action": "cart_clear",
        "message": "تم إفراغ سلة المشتريات المؤقتة بنجاح.",
        "ai_speech_response": "مسحت السلة لحضرتك بالكامل يا فندم. تحب نبدأ طلب جديد؟"
    }
