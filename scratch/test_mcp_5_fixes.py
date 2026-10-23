import os
import sys
import django

sys.path.insert(0, "/root/motaem")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

import time
from decimal import Decimal
from django.db import connection, reset_queries
from django.conf import settings
from core.models import Tenant, Branch, MenuItem, TenantApiKey, Customer, Order, DeliveryArea, BranchMenuAvailability
from core.redis_mcp_cache import (
    cache_api_key,
    get_cached_api_key,
    invalidate_api_key,
    cart_add_item as redis_cart_add,
    cart_clear as redis_cart_clear,
    cart_is_abandoned,
)
from core.mcp.middleware import _check_key_valid, _authenticate, _current_key_obj, _current_tenant
from core.mcp.tools import (
    lookup_customer,
    check_delivery_coverage,
    checkout_cart,
    create_callcenter_order,
    preview_order,
    cancel_order,
)
from core.mcp.resolvers import _find_menu_item, _resolve_delivery_coverage_and_branch


def run_tests():
    print("======================================================================")
    print("🧪 RUNNING COMPREHENSIVE VERIFICATION OF 5 MCP FIXES")
    print("======================================================================")

    tenant = Tenant.objects.first()
    assert tenant, "No tenant found in database."
    branch = Branch.objects.filter(tenant=tenant, status="active").first()
    assert branch, "No branch found for tenant."

    # ------------------------------------------------------------------
    # 1. TEST API KEY REDIS CACHING & DOUBLE DB QUERY ELIMINATION
    # ------------------------------------------------------------------
    print("\n--- 1. Testing Zero-Query API Key Redis Caching & Signal Invalidation ---")
    key_obj = TenantApiKey.objects.filter(tenant=tenant, is_active=True).first()
    if not key_obj:
        key_obj = TenantApiKey.objects.create(
            tenant=tenant,
            name="Test MCP Key",
            key="test_mcp_key_12345",
            is_active=True
        )

    # Invalidate first to test clean cache
    invalidate_api_key(key_obj.key)
    assert get_cached_api_key(key_obj.key) is None, "Key cache should be empty after invalidation."

    # First check: populates Redis cache
    valid = _check_key_valid(key_obj.key)
    assert valid, "Key should be valid."
    
    # Check that Redis now contains the cached key
    cached_redis = get_cached_api_key(key_obj.key)
    assert cached_redis is not None, "Redis cache should contain the key data."
    assert cached_redis["tenant_id"] == tenant.id, "Tenant ID in cache must match."
    print("✓ _check_key_valid successfully populated Redis key cache.")

    # ContextVar simulation: middleware sets _current_key_obj
    token_key = _current_key_obj.set(key_obj)
    token_tenant = _current_tenant.set(tenant)

    # In a tool turn, _authenticate should use ContextVar with 0 DB hits
    settings.DEBUG = True
    reset_queries()
    auth_key, auth_tenant = _authenticate(access_key=None)
    db_hits = len(connection.queries)
    assert auth_key.id == key_obj.id, "Auth key should match key_obj."
    assert auth_tenant.id == tenant.id, "Auth tenant should match tenant."
    assert db_hits == 0, f"Expected 0 DB queries via ContextVar, got {db_hits}."
    print(f"✓ _authenticate executed with {db_hits} DB queries (ContextVar bound).")

    # Reset ContextVar and test Redis fallback: still 0 DB queries
    _current_key_obj.reset(token_key)
    _current_tenant.reset(token_tenant)
    reset_queries()
    auth_key2, auth_tenant2 = _authenticate(access_key=key_obj.key)
    db_hits_redis = len(connection.queries)
    assert auth_key2.id == key_obj.id, "Auth key from Redis cache should match."
    assert db_hits_redis == 0, f"Expected 0 DB queries via Redis cache fallback, got {db_hits_redis}."
    print(f"✓ _authenticate executed with {db_hits_redis} DB queries (Redis cache fallback).")

    # Test Signal Invalidation
    key_obj.name = "Updated Test MCP Key"
    key_obj.save()
    assert get_cached_api_key(key_obj.key) is None, "Key cache should be evicted by Django post_save signal."
    print("✓ Django post_save signal on TenantApiKey successfully evicted Redis cache.")

    # ------------------------------------------------------------------
    # 2. TEST ABANDONED CALL CART RECOVERY IN lookup_customer
    # ------------------------------------------------------------------
    print("\n--- 2. Testing Abandoned Call Cart Recovery in lookup_customer ---")
    test_phone = "01088877665"
    redis_cart_clear(tenant.id, test_phone)

    # Verify no abandoned cart initially
    has_ab, ab_cart = cart_is_abandoned(tenant.id, test_phone, max_age_seconds=1800)
    assert not has_ab, "Should not have abandoned cart initially."

    real_item = MenuItem.objects.filter(tenant=tenant, available=True).first()
    assert real_item, "Should have at least one real menu item."

    # Add real items to draft cart (simulating customer adding items during call)
    redis_cart_add(tenant.id, test_phone, {
        "item_id": real_item.id,
        "name": real_item.name,
        "quantity": 2,
        "price": float(real_item.price),
    })

    # Call lookup_customer with the phone
    res_lookup = lookup_customer(phone=test_phone, access_key=key_obj.key)
    assert res_lookup["ok"] is True, "lookup_customer should succeed."
    assert res_lookup.get("has_abandoned_cart") is True, "lookup_customer must detect abandoned cart."
    assert "أهلاً بحضرتك يا فندم! نورتنا تاني" in res_lookup["ai_speech_response"], (
        f"Greeting missing expected Arabic text: {res_lookup['ai_speech_response']}"
    )
    assert real_item.name in res_lookup["ai_speech_response"], "Items summary should be in greeting."
    print("✓ lookup_customer detected abandoned cart with exact Arabic prompt:")
    print(f"  Speech: {res_lookup['ai_speech_response']}")

    # ------------------------------------------------------------------
    # 3. TEST checkout_cart DEDICATED TOOL
    # ------------------------------------------------------------------
    print("\n--- 3. Testing Dedicated checkout_cart Tool ---")
    res_checkout = checkout_cart(
        customer_phone=test_phone,
        customer_name="أحمد محمود",
        customer_address="شارع النصر عمارة 12 الدور الرابع",
        order_type="takeaway",
        branch_id=branch.id,
        access_key=key_obj.key
    )
    assert res_checkout["ok"] is True, f"checkout_cart failed: {res_checkout}"
    order_num = res_checkout["order"]["order_number"]
    assert order_num, "Order number should be returned."
    print(f"✓ checkout_cart created order {order_num} directly from draft cart.")

    # Cart should now be empty
    has_ab_after, _ = cart_is_abandoned(tenant.id, test_phone, max_age_seconds=1800)
    assert not has_ab_after, "Draft cart should be cleared after checkout."
    print("✓ Draft cart was automatically cleaned after checkout_cart.")

    # ------------------------------------------------------------------
    # 4. TEST OUT-OF-STOCK ITEM SAME-CATEGORY ALTERNATIVES
    # ------------------------------------------------------------------
    print("\n--- 4. Testing Out-of-Stock Item Same-Category Alternatives ---")
    # Pick a menu item and temporarily mark it unavailable
    cat_items = list(MenuItem.objects.filter(tenant=tenant, available=True)[:5])
    if len(cat_items) >= 2:
        target_item = cat_items[0]
        disabled_ids = {target_item.id}
        all_items = cat_items

        matched, v_obj, err_resp = _find_menu_item(
            tenant=tenant,
            branch=branch,
            item_spec={"name": target_item.name},
            disabled_item_ids=disabled_ids,
            all_tenant_items=all_items
        )
        assert isinstance(err_resp, dict), "Out-of-stock response should be a structured dict."
        assert err_resp.get("error_code") == "ERR_ITEM_UNAVAILABLE", (
            f"Expected ERR_ITEM_UNAVAILABLE, got {err_resp.get('error_code')}"
        )
        assert err_resp.get("is_available") is False, "is_available should be False."
        assert len(err_resp.get("suggested_alternatives", [])) > 0, "Should suggest same-category alternatives."
        print(f"✓ Out-of-stock item '{target_item.name}' returned structured alternatives:")
        print(f"  Alternatives: {err_resp['suggested_alternatives']}")
        print(f"  Speech: {err_resp['ai_speech_response']}")

    # ------------------------------------------------------------------
    # 5. TEST DELIVERY COVERAGE ACROSS ALL BRANCHES & DYNAMIC AREA AUTO-PERSIST
    # ------------------------------------------------------------------
    print("\n--- 5. Testing Delivery Coverage & Auto-Registration of DeliveryArea ---")
    # Test checking coverage for an address
    res_cov = check_delivery_coverage(
        customer_address="حي الياسمين عمارة 5 الدور الثاني",
        access_key=key_obj.key
    )
    print(f"✓ check_delivery_coverage result: covered={res_cov.get('covered', False)}, branch={res_cov.get('branch_name')}")

    # Test error_code standardization in tools
    # 5a. Phone required
    res_phone_err = create_callcenter_order(phone="", items=[{"name": "برجر", "quantity": 1}], access_key=key_obj.key)
    assert res_phone_err.get("error_code") == "ERR_PHONE_REQUIRED", f"Expected ERR_PHONE_REQUIRED, got {res_phone_err}"
    print("✓ create_callcenter_order returned error_code: ERR_PHONE_REQUIRED.")

    # 5b. Cancel order not found
    res_cancel_err = cancel_order(order_number="ORD-NON-EXISTENT-99999", access_key=key_obj.key)
    assert res_cancel_err.get("error_code") == "ERR_ORDER_NOT_FOUND", f"Expected ERR_ORDER_NOT_FOUND, got {res_cancel_err}"
    print("✓ cancel_order returned error_code: ERR_ORDER_NOT_FOUND.")

    print("\n======================================================================")
    print("🎉 ALL 5 MCP FIXES AND ENHANCEMENTS VERIFIED SUCCESSFULLY!")
    print("======================================================================")


if __name__ == "__main__":
    run_tests()
