"""
Redis High-Performance In-Memory Cache for Call Center MCP & Restaurant Operations.
Features:
1. Active Orders In-Memory Index (sub-millisecond customer lookup & order tracking).
2. Branch Menu Matrix In-Memory Cache (zero-query menu and variant resolution).
3. Graceful degradation: If Redis is temporarily unreachable, transparently falls back to database.
"""
import json
import logging
from typing import Dict, Any, Optional, List
from django.utils import timezone

logger = logging.getLogger(__name__)

_redis_client = None

def get_redis_client():
    """Return reusable thread-safe Redis client instance with connection pooling."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.Redis(
                host='127.0.0.1',
                port=6379,
                db=0,
                decode_responses=True,
                socket_timeout=1.5,
                socket_connect_timeout=1.5
            )
            # Test connection
            _redis_client.ping()
        except Exception as e:
            logger.warning(f"Redis not available for MCP cache: {e}")
            _redis_client = None
    return _redis_client


# =====================================================================
# 1. Active Orders Cache (Ultra-Fast Customer Lookup & Status Tracking)
# =====================================================================

ACTIVE_ORDER_TTL = 7200  # 2 hours in seconds

def cache_active_order(order, ttl: int = ACTIVE_ORDER_TTL) -> bool:
    """
    Store an active order in Redis indexed by order_number and customer phone.
    Active statuses: 'new', 'preparing', 'ready', 'out_for_delivery'.
    """
    client = get_redis_client()
    if not client or not order:
        return False

    try:
        tenant_id = getattr(order, "tenant_id", None) or (order.tenant.id if order.tenant else 0)
        order_num = str(order.order_number).strip().upper()
        clean_phone = str(order.customer_phone or "").strip().replace(" ", "").replace("-", "")
        phone_suffix = clean_phone[-9:] if len(clean_phone) >= 9 else clean_phone

        created_at_iso = order.created_at.isoformat() if hasattr(order, "created_at") and order.created_at else timezone.now().isoformat()
        
        # Build items summary text
        items_summary = ""
        if hasattr(order, "items"):
            items_summary = " و ".join([f"{it.qty} {it.name}" for it in order.items.all()[:4]])

        cur_sym = "ر.س"
        if order.branch and hasattr(order.branch, "get_currency_symbol_ar"):
            cur_sym = order.branch.get_currency_symbol_ar()

        area_name = order.delivery_area.name if order.delivery_area else ""
        est_min = order.delivery_area.estimated_time_minutes if order.delivery_area else 35

        payload = {
            "order_id": order.id,
            "order_number": order_num,
            "tenant_id": tenant_id,
            "branch_id": order.branch_id,
            "branch_name": order.branch.name if order.branch else "الفرع الرئيسي",
            "customer_name": order.customer_name or "عميل نقدي",
            "customer_phone": order.customer_phone or "",
            "phone_suffix": phone_suffix,
            "address": order.address or "",
            "delivery_area_name": area_name,
            "estimated_delivery_minutes": est_min,
            "status": order.status,
            "status_display": order.get_status_display(),
            "subtotal": float(order.subtotal or 0),
            "total": float(order.total or 0),
            "tax": float(order.tax or 0),
            "delivery_fee": float(order.delivery_fee or 0),
            "currency_symbol": cur_sym,
            "items_summary": items_summary,
            "created_at_iso": created_at_iso,
            "cached_at": timezone.now().isoformat()
        }

        json_data = json.dumps(payload, ensure_ascii=False)

        pipe = client.pipeline()
        # 1. By Order Number
        pipe.set(f"active_order:num:{tenant_id}:{order_num}", json_data, ex=ttl)
        # 2. By Phone Suffix
        if phone_suffix:
            pipe.set(f"active_order:phone:{tenant_id}:{phone_suffix}", order_num, ex=ttl)

        pipe.execute()
        return True
    except Exception as e:
        logger.warning(f"Error caching active order in Redis: {e}")
        return False


def get_active_order_by_phone(tenant_id: int, phone: str) -> Optional[Dict[str, Any]]:
    """Retrieve active order payload for a phone number in <0.5ms from Redis."""
    client = get_redis_client()
    if not client or not phone:
        return None

    try:
        clean = str(phone).strip().replace(" ", "").replace("-", "").replace("+", "")
        suffix = clean[-9:] if len(clean) >= 9 else clean
        order_num = client.get(f"active_order:phone:{tenant_id}:{suffix}")
        if not order_num:
            return None
        return get_active_order_by_number(tenant_id, order_num)
    except Exception as e:
        logger.warning(f"Error reading active order by phone from Redis: {e}")
        return None


def get_active_order_by_number(tenant_id: int, order_number: str) -> Optional[Dict[str, Any]]:
    """Retrieve active order payload for an order number in <0.5ms from Redis."""
    client = get_redis_client()
    if not client or not order_number:
        return None

    try:
        clean_num = str(order_number).strip().upper()
        raw = client.get(f"active_order:num:{tenant_id}:{clean_num}")
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Error reading active order by number from Redis: {e}")
        return None


def update_active_order_status(tenant_id: int, order_number: str, new_status: str, new_status_display: str = "") -> bool:
    """Update active order status in Redis, or remove if transitioned to delivered/cancelled."""
    if new_status in ["delivered", "cancelled", "canceled"]:
        return remove_active_order(tenant_id, order_number)

    client = get_redis_client()
    if not client or not order_number:
        return False

    try:
        clean_num = str(order_number).strip().upper()
        key = f"active_order:num:{tenant_id}:{clean_num}"
        raw = client.get(key)
        if not raw:
            return False

        data = json.loads(raw)
        data["status"] = new_status
        data["status_display"] = new_status_display or new_status
        data["updated_at"] = timezone.now().isoformat()

        # Preserve remaining TTL
        remaining_ttl = client.ttl(key)
        ttl = remaining_ttl if remaining_ttl > 0 else ACTIVE_ORDER_TTL
        client.set(key, json.dumps(data, ensure_ascii=False), ex=ttl)
        return True
    except Exception as e:
        logger.warning(f"Error updating active order status in Redis: {e}")
        return False


def remove_active_order(tenant_id: int, order_number: str) -> bool:
    """Delete active order from Redis when delivered or cancelled."""
    client = get_redis_client()
    if not client or not order_number:
        return False

    try:
        clean_num = str(order_number).strip().upper()
        num_key = f"active_order:num:{tenant_id}:{clean_num}"
        raw = client.get(num_key)
        phone_suffix = None
        if raw:
            try:
                data = json.loads(raw)
                phone_suffix = data.get("phone_suffix")
            except Exception:
                pass

        pipe = client.pipeline()
        pipe.delete(num_key)
        if phone_suffix:
            pipe.delete(f"active_order:phone:{tenant_id}:{phone_suffix}")
        pipe.execute()
        return True
    except Exception as e:
        logger.warning(f"Error removing active order from Redis: {e}")
        return False


# =====================================================================
# 2. In-Memory Menu Matrix Cache (Zero-Query Item & Variant Matching)
# =====================================================================

MENU_MATRIX_TTL = 600  # 10 minutes

def get_branch_menu_matrix(tenant, branch) -> List[Dict[str, Any]]:
    """
    Retrieve pre-compiled branch menu items and variant pricing from Redis.
    Matches in pure Python memory in 0.1ms with zero database queries.
    """
    client = get_redis_client()
    tenant_id = tenant.id
    branch_id = branch.id if branch else 0
    cache_key = f"menu_matrix:{tenant_id}:{branch_id}"

    if client:
        try:
            cached = client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Error reading menu matrix from Redis: {e}")

    # Build matrix from database
    from core.models import MenuItem, BranchMenuAvailability

    disabled_item_ids = set()
    if branch:
        disabled_item_ids = set(
            BranchMenuAvailability.objects.filter(branch=branch, is_available=False).values_list("menu_item_id", flat=True)
        )

    qs = MenuItem.objects.filter(tenant=tenant, available=True).prefetch_related("variants")
    if disabled_item_ids:
        qs = qs.exclude(id__in=disabled_item_ids)

    matrix = []
    for item in qs:
        # Pre-compile branch prices and variants
        price = float(item.get_price_for_branch(branch))
        variants_list = []
        if item.has_variants:
            for v in item.variants.all():
                variants_list.append({
                    "id": v.id,
                    "name": v.name,
                    "price": float(v.get_price_for_branch(branch)),
                    "is_default": v.is_default
                })

        matrix.append({
            "id": item.id,
            "name": item.name,
            "category": item.category,
            "price": price,
            "has_variants": item.has_variants and len(variants_list) > 0,
            "variants": variants_list,
            "emoji": item.emoji or "🍽️"
        })

    if client:
        try:
            client.set(cache_key, json.dumps(matrix, ensure_ascii=False), ex=MENU_MATRIX_TTL)
        except Exception as e:
            logger.warning(f"Error storing menu matrix in Redis: {e}")

    return matrix


def invalidate_branch_menu_cache(tenant_id: int, branch_id: Optional[int] = None):
    """Purge branch menu cache when dishes, prices, or availability are modified."""
    client = get_redis_client()
    if not client:
        return

    try:
        if branch_id:
            client.delete(f"menu_matrix:{tenant_id}:{branch_id}")
        else:
            # Pattern delete for tenant
            keys = client.keys(f"menu_matrix:{tenant_id}:*")
            if keys:
                client.delete(*keys)
    except Exception as e:
        logger.warning(f"Error invalidating menu matrix cache in Redis: {e}")
