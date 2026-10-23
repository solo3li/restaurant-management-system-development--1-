import os
import sys
import django
import time

sys.path.insert(0, "/root/motaem")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from decimal import Decimal
from core.models import Tenant, Branch, MenuItem, MenuItemVariant, Order, TenantApiKey, DeliveryArea
from core.redis_mcp_cache import (
    get_redis_client,
    get_branch_menu_matrix,
    get_active_order_by_number,
    get_next_order_sequence,
    cart_get,
)
from core.mcp import (
    cart_add_item,
    cart_view,
    cart_remove_item,
    cart_clear,
    create_callcenter_order,
    track_order,
    _is_rate_limited,
)

def run_tests():
    print("=" * 70)
    print("🧪 TESTING DRAFT CART, CACHE INVALIDATION & ATOMIC ORDER SEQUENCE")
    print("=" * 70)

    tenant = Tenant.objects.first()
    branch = Branch.objects.filter(tenant=tenant, status="active").first()
    key_obj = TenantApiKey.objects.filter(tenant=tenant, is_active=True).first()
    access_key = key_obj.key

    client = get_redis_client()
    assert client is not None, "Redis must be connected"

    # -------------------------------------------------------------
    # 1. Test Conversational Draft Cart (السلة المؤقتة)
    # -------------------------------------------------------------
    print("\n--- 1. Testing Draft Cart Sessions in Redis ---")
    customer_phone = "01122334455"
    cart_clear(customer_phone=customer_phone, access_key=access_key)

    # Find two available menu items
    items = list(MenuItem.objects.filter(tenant=tenant, available=True)[:2])
    item1 = items[0]
    item2 = items[1] if len(items) > 1 else items[0]

    # Add item 1
    res1 = cart_add_item(
        customer_phone=customer_phone,
        item_name=item1.name,
        quantity=2,
        notes="بدون بصل",
        branch_id=branch.id,
        access_key=access_key
    )
    assert res1["ok"] is True, f"cart_add_item 1 failed: {res1}"
    assert res1["cart"]["items_count"] == 2
    print(f"✓ Added 2x '{item1.name}' to cart: {res1['ai_speech_response']}")

    # Add item 2
    res2 = cart_add_item(
        customer_phone=customer_phone,
        item_name=item2.name,
        quantity=1,
        branch_id=branch.id,
        access_key=access_key
    )
    assert res2["ok"] is True, f"cart_add_item 2 failed: {res2}"
    assert res2["cart"]["items_count"] == 3
    print(f"✓ Added 1x '{item2.name}' to cart. Total items: {res2['cart']['items_count']}")

    # View cart
    view_res = cart_view(customer_phone=customer_phone, access_key=access_key)
    assert view_res["ok"] is True
    assert view_res["items_count"] == 3
    assert view_res["cart_total"] > 0
    print(f"✓ Viewed cart successfully: {view_res['ai_speech_response']}")

    # Remove one item
    rem_res = cart_remove_item(customer_phone=customer_phone, item_name_or_index=item2.name, access_key=access_key)
    assert rem_res["ok"] is True
    assert rem_res["cart"]["items_count"] == 2
    print(f"✓ Removed '{item2.name}'. Remaining items: {rem_res['cart']['items_count']}")

    # -------------------------------------------------------------
    # 2. Test Checkout from Draft Cart
    # -------------------------------------------------------------
    print("\n--- 2. Testing Direct Checkout from Draft Cart in create_callcenter_order ---")
    checkout_res = create_callcenter_order(
        customer_phone=customer_phone,
        customer_name="عميل السلة المؤقتة",
        order_type="takeaway",
        branch_id=branch.id,
        # items is intentionally omitted!
        access_key=access_key
    )
    assert checkout_res["ok"] is True, f"Cart checkout failed: {checkout_res}"
    assert checkout_res["used_draft_cart"] is True
    order_num = checkout_res["order_number"]
    print(f"✓ Order created directly from draft cart: #{order_num}")
    print(f"  AI Speech Response: {checkout_res['ai_speech_response']}")

    # Verify cart is automatically cleared after checkout
    after_cart = cart_get(tenant.id, customer_phone)
    assert len(after_cart.get("items", [])) == 0
    print("✓ Draft cart was automatically emptied upon successful checkout.")

    # -------------------------------------------------------------
    # 3. Test Atomic Sequence Generation (Redis INCR)
    # -------------------------------------------------------------
    print("\n--- 3. Testing Sub-millisecond Atomic Order Sequence (Redis INCR) ---")
    today_str = "20261023"
    t0 = time.time()
    seq1 = get_next_order_sequence(tenant.id, branch.id, today_str)
    seq2 = get_next_order_sequence(tenant.id, branch.id, today_str)
    seq3 = get_next_order_sequence(tenant.id, branch.id, today_str)
    t_elapsed = (time.time() - t0) * 1000
    assert seq2 == seq1 + 1
    assert seq3 == seq2 + 1
    print(f"✓ 3 atomic sequence increments executed in {t_elapsed:.3f}ms total (avg {t_elapsed/3:.4f}ms each): {seq1} -> {seq2} -> {seq3}")

    # -------------------------------------------------------------
    # 4. Test Live Cache Invalidation via Django Signals
    # -------------------------------------------------------------
    print("\n--- 4. Testing Live Memory Cache Invalidation via Django Signals ---")
    # Prime menu matrix cache
    matrix_before = get_branch_menu_matrix(tenant, branch)
    cache_key = f"menu_matrix:{tenant.id}:{branch.id}"
    assert client.get(cache_key) is not None, "Menu matrix should be cached in Redis"
    print(f"✓ Menu matrix cached in Redis ({len(matrix_before)} items)")

    # Modify an item and save -> signal triggers invalidate_branch_menu_cache
    item1.price = item1.price + Decimal("5.00")
    item1.save()
    assert client.get(cache_key) is None, "Cache should be invalidated immediately on item save"
    print("✓ Redis menu cache was automatically invalidated on MenuItem save signal!")

    # Prime again and test order status signal sync
    active_in_redis = get_active_order_by_number(tenant.id, order_num)
    assert active_in_redis is not None, "Order should be active in Redis"
    print(f"✓ Active order #{order_num} verified in Redis: status={active_in_redis['status']}")

    db_order = Order.objects.get(order_number=order_num)
    db_order.status = "preparing"
    db_order.save()

    active_updated = get_active_order_by_number(tenant.id, order_num)
    assert active_updated is not None
    assert active_updated["status"] == "preparing"
    print(f"✓ Active order #{order_num} updated to 'preparing' in Redis via Order post_save signal!")

    # Mark as delivered -> signal purges from active orders in Redis
    db_order.status = "delivered"
    db_order.save()
    active_purged = get_active_order_by_number(tenant.id, order_num)
    assert active_purged is None, "Delivered order must be removed from Redis active cache"
    print(f"✓ Delivered order #{order_num} automatically purged from Redis active orders via post_save signal!")

    # -------------------------------------------------------------
    # 5. Test SSE Rate Limiter
    # -------------------------------------------------------------
    print("\n--- 5. Testing Sliding-Window Rate Limiter ---")
    test_ip = "192.168.100.50"
    for _ in range(10):
        assert not _is_rate_limited(test_ip, max_requests=15, window_seconds=10)
    # Now exhaust
    for _ in range(5):
        _is_rate_limited(test_ip, max_requests=15, window_seconds=10)
    assert _is_rate_limited(test_ip, max_requests=15, window_seconds=10) is True
    print("✓ Rate limiter successfully blocked requests after exceeding window limit.")

    print("\n" + "=" * 70)
    print("🎉 ALL TESTS FOR DRAFT CART, CACHE INVALIDATION & ATOMIC SEQUENCING PASSED 100%!")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()
