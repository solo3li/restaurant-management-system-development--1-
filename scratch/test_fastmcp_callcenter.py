import os
import sys

# Ensure UTF-8 output for Windows console
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# Setup Django environment
sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")

import django
django.setup()

import json
from decimal import Decimal
from django.test import Client
from django.contrib.auth.models import User
from core.models import (
    Tenant,
    Branch,
    Customer,
    MenuItem,
    Order,
    DeliveryArea,
    TenantApiKey,
    UserProfile,
)
from core.mcp_server import (
    get_branches,
    get_menu,
    lookup_customer,
    check_delivery_coverage,
    create_callcenter_order,
    track_order,
    list_recent_orders,
)

def run_tests():
    print("=" * 70)
    print("🚀 AUTOMATED TEST SUITE: FASTMCP CALL CENTER AI INTEGRATION")
    print("=" * 70)

    # 1. Setup / Identify Owner & Tenant
    admin_user = User.objects.filter(is_superuser=True).first()
    if not admin_user:
        admin_user = User.objects.create_superuser("admin", "admin@example.com", "admin1234")

    client = Client()
    client.force_login(admin_user)

    profile = getattr(admin_user, "profile", None)
    if profile and profile.tenant:
        tenant = profile.tenant
    else:
        tenant = Tenant.objects.filter(is_active=True).first()
    assert tenant, "No active tenant found in database!"
    print(f"Testing with Tenant: {tenant.name} (ID: {tenant.id})")

    branch = Branch.objects.filter(tenant=tenant, status="active").first()
    if not branch:
        branch = Branch.objects.create(tenant=tenant, name="الفرع التجريبي", city="القاهرة", status="active")
    print(f"Testing with Branch: {branch.name} (ID: {branch.id})")

    # Add a sample delivery area if none exists
    area = DeliveryArea.objects.filter(branch=branch, is_active=True).first()
    if not area:
        area = DeliveryArea.objects.create(
            branch=branch,
            name="مدينة الشروق - كمبوند النرجس",
            area_type="compound",
            delivery_fee=Decimal("15.00"),
            estimated_time_minutes=35,
            is_active=True,
        )
    print(f"Delivery Area: {area.name} (Fee: {area.delivery_fee} EGP)")

    # Ensure at least 2 active menu items exist
    menu_item = MenuItem.objects.filter(tenant=tenant, available=True).first()
    if not menu_item:
        menu_item = MenuItem.objects.create(
            tenant=tenant,
            name="برجر شيف سبيشال",
            category="وجبات برجر",
            price=Decimal("120.00"),
            available=True,
        )
    print(f"Sample Menu Item: {menu_item.name} ({menu_item.price} EGP)")

    # 2. Test API Key Creation via Web API (/api/api-keys/create/)
    print("\n--- 1. Testing Web API: Create API Key ---")
    resp = client.post(
        "/api/api-keys/create/",
        data=json.dumps({"name": "بوت كول سنتر الذكاء الاصطناعي - تجريبي", "branch_id": branch.id}),
        content_type="application/json"
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.content}"
    res_data = resp.json()
    assert res_data.get("ok") is True, "Expected ok=True in response"
    key_info = res_data["key"]
    access_key = key_info["access_key"]
    key_id = key_info["id"]
    print(f"✓ API Key created successfully: {key_info['name']} (Prefix: {access_key[:14]}...)")

    # 3. Test Owner Subscription Page Rendering (/subscription/)
    print("\n--- 2. Testing Owner Subscription Page Rendering ---")
    session = client.session
    session["active_tenant_id"] = tenant.id
    session.save()

    resp = client.get("/subscription/")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    page_content = resp.content.decode("utf-8")
    assert "مفاتيح الذكاء الاصطناعي وتكامل الكول سنتر" in page_content, "FastMCP section missing in /subscription/"
    assert "بوت كول سنتر الذكاء الاصطناعي - تجريبي" in page_content, "Created key missing from page"
    assert "claude_desktop_config.json" in page_content, "Claude Desktop config instructions missing"
    print("✓ Owner Subscription page rendered FastMCP section and API keys table.")

    # 4. Test FastMCP Tool: get_branches
    print("\n--- 3. Testing FastMCP Tool: get_branches ---")
    branches_res = get_branches(access_key=access_key)
    assert branches_res["ok"] is True
    assert branches_res["branches_count"] >= 1
    print(f"✓ get_branches returned {branches_res['branches_count']} branch(es) for {branches_res['tenant_name']}")

    # 5. Test FastMCP Tool: get_menu
    print("\n--- 4. Testing FastMCP Tool: get_menu ---")
    menu_res = get_menu(branch_id=branch.id, access_key=access_key)
    assert menu_res["ok"] is True
    assert menu_res["total_items"] >= 1
    print(f"✓ get_menu returned {menu_res['total_items']} items in categories: {menu_res['categories']}")

    # 6. Test FastMCP Tool: lookup_customer (New Customer)
    print("\n--- 5. Testing FastMCP Tool: lookup_customer ---")
    test_phone = "01099887766"
    Customer.objects.filter(tenant=tenant, phone=test_phone).delete()
    cust_res = lookup_customer(phone=test_phone, access_key=access_key)
    assert cust_res["ok"] is True
    assert cust_res["found"] is False, "Expected new customer to not be found yet"
    print(f"✓ lookup_customer correctly identified new customer: {cust_res['message']}")

    # 7. Test FastMCP Tool: check_delivery_coverage
    print("\n--- 6. Testing FastMCP Tool: check_delivery_coverage ---")
    coverage_res = check_delivery_coverage(branch_id=branch.id, area_name="الشروق", access_key=access_key)
    assert coverage_res["ok"] is True
    assert coverage_res["covered"] is True, "Expected area to be covered"
    assert coverage_res["matched_area"]["delivery_fee"] == float(area.delivery_fee)
    print(f"✓ check_delivery_coverage found matching area: {coverage_res['matched_area']['name']} (Fee: {coverage_res['matched_area']['delivery_fee']} EGP)")

    # 8. Test FastMCP Tool: create_callcenter_order (ضرب أوردر كول سنتر)
    print("\n--- 7. Testing FastMCP Tool: create_callcenter_order ---")
    order_items = [
        {"item_id": menu_item.id, "quantity": 2, "notes": "بدون مخلل"}
    ]
    order_res = create_callcenter_order(
        branch_id=branch.id,
        customer_phone=test_phone,
        customer_name="أحمد طارق",
        customer_address="مدينة الشروق - كمبوند النرجس - عمارة 12 شقة 4",
        items=order_items,
        order_type="delivery",
        delivery_area_id=area.id,
        notes="يرجى الاتصال عند الوصول للبوابة",
        access_key=access_key
    )
    assert order_res["ok"] is True, f"Order placement failed: {order_res}"
    created_order = order_res["order"]
    order_num = created_order["order_number"]
    print(f"✓ Call Center Order Placed: #{order_num} | Total: {created_order['total']} EGP | Status: {created_order['status']}")

    # Verify Customer was automatically created in DB
    created_cust = Customer.objects.filter(tenant=tenant, phone=test_phone).first()
    assert created_cust is not None, "Customer was not created in DB!"
    assert created_cust.name == "أحمد طارق"
    assert created_cust.orders.count() >= 1
    print(f"✓ Customer registered automatically in DB: {created_cust.name} (Total Orders: {created_cust.orders.count()})")

    # Verify API Key stats were updated
    key_db = TenantApiKey.objects.get(id=key_id)
    assert key_db.total_orders_placed >= 1, "API Key total_orders_placed did not increment!"
    assert key_db.last_used_at is not None, "API Key last_used_at was not updated!"
    print(f"✓ API Key stats updated: {key_db.total_orders_placed} order(s) placed | Last Used: {key_db.last_used_at}")

    # 9. Test FastMCP Tool: track_order
    print("\n--- 8. Testing FastMCP Tool: track_order ---")
    track_res = track_order(order_number=order_num, access_key=access_key)
    assert track_res["ok"] is True, f"Track order failed: {track_res}"
    track_info = track_res["order"]
    assert track_info["order_number"] == order_num
    assert track_info["customer_phone"] == test_phone
    print(f"✓ track_order retrieved status: {track_info['status_label']} for Order #{order_num}")

    # 10. Test FastMCP Tool: list_recent_orders
    print("\n--- 9. Testing FastMCP Tool: list_recent_orders ---")
    recent_res = list_recent_orders(branch_id=branch.id, limit=5, access_key=access_key)
    assert recent_res["ok"] is True
    assert recent_res["count"] >= 1
    assert any(o["order_number"] == order_num for o in recent_res["orders"])
    print(f"✓ list_recent_orders listed {recent_res['count']} recent orders including #{order_num}")

    # 11. Test Security: Multi-tenant Isolation & Disabled Key
    print("\n--- 10. Testing Security: Disabled Key & Multi-tenancy Isolation ---")
    # Disable the key
    resp_toggle = client.post(f"/api/api-keys/{key_id}/toggle/")
    assert resp_toggle.status_code == 200
    assert resp_toggle.json()["is_active"] is False

    try:
        get_branches(access_key=access_key)
        assert False, "Disabled key should have raised ValueError!"
    except ValueError as e:
        print(f"✓ Disabled key correctly rejected: {e}")

    # Re-enable the key
    client.post(f"/api/api-keys/{key_id}/toggle/")

    # 12. Test Clean Deletion
    print("\n--- 11. Testing Web API: Delete API Key ---")
    resp_del = client.post(f"/api/api-keys/{key_id}/delete/")
    assert resp_del.status_code == 200
    assert not TenantApiKey.objects.filter(id=key_id).exists()
    print("✓ API Key deleted successfully.")

    print("\n" + "=" * 70)
    print("🎉 ALL FASTMCP CALL CENTER INTEGRATION TESTS PASSED 100%!")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()
