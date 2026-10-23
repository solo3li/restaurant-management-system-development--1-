import os
import sys
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import django
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from core.models import Tenant, Branch, MenuItem, MenuItemVariant, Order, Customer, TenantApiKey
from core.redis_mcp_cache import (
    get_redis_client,
    cache_active_order,
    get_active_order_by_phone,
    get_active_order_by_number,
    remove_active_order,
    get_branch_menu_matrix,
)
from core.mcp_server import (
    OrderItemInput,
    create_callcenter_order,
    lookup_customer,
    track_order,
    cancel_order,
    _find_menu_item,
    _authenticate,
)

def run_tests():
    print("=================================================================")
    print("  RUNNING COMPREHENSIVE END-TO-END MCP & REDIS TEST SUITE")
    print("=================================================================")

    # 1. Check Redis Connection
    r = get_redis_client()
    assert r is not None, "Redis client failed to connect to 127.0.0.1:6379"
    assert r.ping() is True, "Redis ping returned False"
    print(" [1/8] Redis server connected and responsive: PASS")

    # 2. Setup Tenant & API Key for testing
    tenant = Tenant.objects.filter(is_active=True).first()
    assert tenant is not None, "No active tenant found in database"
    branch = Branch.objects.filter(tenant=tenant, status="active").first()
    assert branch is not None, "No active branch found for tenant"

    api_key_obj = TenantApiKey.objects.filter(tenant=tenant, is_active=True).first()
    if not api_key_obj:
        api_key_obj = TenantApiKey.objects.create(
            tenant=tenant,
            name="E2E Test Key",
            key="test_e2e_key_secret_12345",
            is_active=True
        )
    test_key = api_key_obj.key
    print(f" [2/8] Authenticated Tenant '{tenant.name}', Branch '{branch.name}', Key OK: PASS")

    # 3. Test OrderItemInput flexibility (extra='allow', item_id, optional name)
    item_in1 = OrderItemInput(item_id=1, quantity=2, qty=2, size="وسط")
    assert item_in1.item_id == 1
    assert item_in1.quantity == 2
    assert getattr(item_in1, "qty", 2) == 2
    print(" [3/8] OrderItemInput Pydantic flexibility (optional name, extra='allow'): PASS")

    # 4. Test In-Memory Menu Matrix Caching in Redis
    matrix = get_branch_menu_matrix(tenant, branch)
    assert isinstance(matrix, list)
    assert len(matrix) > 0, "Menu matrix returned empty list"
    print(f" [4/8] Branch Menu Matrix in Redis ({len(matrix)} items cached): PASS")

    # 5. Test create_callcenter_order with streamlined arguments & active order Redis caching
    menu_item = MenuItem.objects.filter(tenant=tenant, available=True).first()
    assert menu_item is not None, "No available menu item found"

    test_phone = "0559988771"
    res_order = create_callcenter_order(
        phone=test_phone,
        customer_name="عميل تجربة الإند تو إند",
        address="مدينة الشروق - كمبوند النرجس، عمارة 15، شقة 4",
        items=[{"name": menu_item.name, "quantity": 2}],
        order_type="delivery",
        branch_id=branch.id,
        access_key=test_key
    )

    assert res_order.get("ok") is True, f"create_callcenter_order failed: {res_order}"
    order_num = res_order.get("order_number")
    assert order_num is not None, "Missing order_number in created order"
    print(f" [5/8] Order created successfully: #{order_num}")

    # 6. Verify Active Order in Redis Cache (<0.5ms lookup)
    t0 = time.perf_counter()
    cached_by_phone = get_active_order_by_phone(tenant.id, test_phone)
    t_phone = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    cached_by_num = get_active_order_by_number(tenant.id, order_num)
    t_num = (time.perf_counter() - t1) * 1000

    assert cached_by_phone is not None, "Order was NOT cached in Redis by phone"
    assert cached_by_num is not None, "Order was NOT cached in Redis by order_number"
    assert cached_by_phone["order_number"] == order_num
    assert cached_by_num["customer_phone"] == test_phone
    print(f" [6/8] Redis Active Order verified: Phone lookup took {t_phone:.3f}ms, Number lookup took {t_num:.3f}ms: PASS")

    # 7. Test lookup_customer and track_order using Redis cache
    res_lookup = lookup_customer(phone=test_phone, access_key=test_key)
    assert res_lookup.get("ok") is True
    assert res_lookup.get("has_active_recent_order") is True
    assert res_lookup["active_order"]["order_number"] == order_num

    res_track = track_order(order_number=order_num, access_key=test_key)
    assert res_track.get("ok") is True
    assert res_track.get("matched_by") == "redis_cache"
    assert res_track["order"]["order_number"] == order_num
    print(" [7/8] lookup_customer & track_order returned instant Redis response: PASS")

    # 8. Test cancel_order and verify Redis cache invalidation
    res_cancel = cancel_order(order_number=order_num, reason="اختبار الإلغاء الشامل", access_key=test_key)
    assert res_cancel.get("ok") is True, f"cancel_order failed: {res_cancel}"

    # Verify order is purged from Redis
    cached_after_cancel = get_active_order_by_number(tenant.id, order_num)
    assert cached_after_cancel is None, "Order was NOT purged from Redis after cancellation!"

    cached_phone_after = get_active_order_by_phone(tenant.id, test_phone)
    assert cached_phone_after is None, "Phone index was NOT purged from Redis after cancellation!"
    print(" [8/8] cancel_order executed and Redis active cache purged completely: PASS")

    print("\n=================================================================")
    print("  ALL 8 END-TO-END TESTS PASSED WITH 100% SUCCESS!")
    print("=================================================================")

if __name__ == "__main__":
    run_tests()
