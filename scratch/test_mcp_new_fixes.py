import os
import sys
import django

sys.path.insert(0, "/root/motaem")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from decimal import Decimal
from django.utils import timezone
from core.models import Tenant, Branch, Customer, MenuItem, Order, OrderItem, TenantApiKey, DeliveryArea
from core.mcp_server import (
    lookup_customer,
    check_delivery_coverage,
    create_callcenter_order,
    get_menu,
    preview_order
)

def run_tests():
    print("=" * 70)
    print("🧪 TESTING NEW MCP FIXES & OPERATIONAL HARDENING")
    print("=" * 70)

    tenant = Tenant.objects.first()
    assert tenant, "No tenant found"

    branch = Branch.objects.filter(tenant=tenant, status="active").first()
    assert branch, "No active branch found"

    key_obj, _ = TenantApiKey.objects.get_or_create(
        tenant=tenant,
        name="Test New Fixes Key",
        defaults={"is_active": True}
    )
    access_key = key_obj.key

    # -------------------------------------------------------------
    # 1. Test Placeholder Name Greeting vs Real Name Greeting
    # -------------------------------------------------------------
    print("\n--- 1. Testing Customer Greeting (Placeholder vs Real Name) ---")
    placeholder_cust, _ = Customer.objects.get_or_create(
        tenant=tenant,
        phone="0501112233",
        defaults={"name": "عميل (0501112233)", "address": "شارع التحرير عمارة 5"}
    )
    placeholder_cust.name = "عميل (0501112233)"
    placeholder_cust.save()

    res_placeholder = lookup_customer(phone="0501112233", access_key=access_key)
    assert res_placeholder["ok"] is True
    assert "يا عميل" not in res_placeholder["ai_speech_response"], f"Robotic greeting found: {res_placeholder['ai_speech_response']}"
    assert "أهلاً بحضرتك يا فندم" in res_placeholder["ai_speech_response"]
    print("✓ Placeholder customer greeted respectfully without robotic 'يا عميل':")
    print(f"  Speech: \"{res_placeholder['ai_speech_response']}\"")

    real_cust, _ = Customer.objects.get_or_create(
        tenant=tenant,
        phone="0509998877",
        defaults={"name": "كريم محمود أحمد", "address": "شارع النصر عمارة 10"}
    )
    real_cust.name = "كريم محمود أحمد"
    real_cust.save()

    res_real = lookup_customer(phone="0509998877", access_key=access_key)
    assert res_real["ok"] is True
    assert "أستاذ كريم" in res_real["ai_speech_response"]
    print("✓ Real customer greeted with title and first name:")
    print(f"  Speech: \"{res_real['ai_speech_response']}\"")

    # -------------------------------------------------------------
    # 2. Test Item Notes Preservation (DB & Display Name) & Cash
    # -------------------------------------------------------------
    print("\n--- 2. Testing Item-Level Notes Preservation & Cash Payment ---")
    menu_item = MenuItem.objects.filter(tenant=tenant, available=True).first()
    assert menu_item, "No available menu item"

    test_addr = "مدينة الشروق كمبوند النرجس عمارة 12 دور 3 شقة 6"
    custom_notes = "بدون بصل وزيادة صوص طحينة"

    order_payload = [
        {
            "name": menu_item.name,
            "quantity": 2,
            "notes": custom_notes
        }
    ]

    res_order = create_callcenter_order(
        customer_phone="0509998877",
        customer_name="كريم محمود",
        customer_address=test_addr,
        items=order_payload,
        access_key=access_key
    )

    assert res_order["ok"] is True, f"Order failed: {res_order}"
    order_num = res_order["order_number"]
    db_order = Order.objects.get(tenant=tenant, order_number=order_num)

    assert db_order.pay_method == "cash", f"Expected cash, got {db_order.pay_method}"
    assert db_order.paid is False, "Expected paid=False on call center creation"
    print(f"✓ Order #{order_num} created with pay_method='cash' and paid=False.")

    db_item = db_order.items.first()
    assert db_item, "OrderItem not found in DB"
    assert db_item.notes == custom_notes, f"Expected notes '{custom_notes}', got '{db_item.notes}'"
    assert f"({custom_notes})" in db_item.name, f"Expected notes in display name, got '{db_item.name}'"
    print(f"✓ OrderItem #{db_item.id} saved in DB with:")
    print(f"  notes: \"{db_item.notes}\"")
    print(f"  name:  \"{db_item.name}\"")
    print(f"  Response item notes: \"{res_order['order']['items'][0]['notes']}\"")
    print(f"  Speech confirms: \"{res_order['ai_speech_response']}\"")

    # -------------------------------------------------------------
    # 3. Test Branch Operating Hours & is_accepting_orders Rejection
    # -------------------------------------------------------------
    print("\n--- 3. Testing Branch Operating Hours & is_accepting_orders Rejection ---")
    orig_accepting = branch.is_accepting_orders
    orig_open_time = branch.opening_time
    orig_close_time = branch.closing_time

    try:
        # 3.1: Branch paused (is_accepting_orders = False)
        branch.is_accepting_orders = False
        branch.save()

        res_paused = create_callcenter_order(
            branch_id=branch.id,
            customer_phone="0509998877",
            customer_name="كريم محمود",
            customer_address=test_addr,
            items=[{"name": menu_item.name, "quantity": 1}],
            access_key=access_key
        )
        assert res_paused.get("status") == "branch_closed", f"Expected branch_closed, got {res_paused}"
        assert "موقف استقبال الطلبات" in res_paused["ai_speech_response"]
        print(f"✓ Paused branch correctly rejected order creation:")
        print(f"  Speech: \"{res_paused['ai_speech_response']}\"")

        # 3.2: Branch closed outside operating hours
        branch.is_accepting_orders = True
        # Set working hours to a past window (e.g. 01:00 AM to 02:00 AM)
        import datetime
        branch.opening_time = datetime.time(1, 0)
        branch.closing_time = datetime.time(2, 0)
        branch.save()

        # If current time is not between 01:00 and 02:00, is_currently_open is False
        if not branch.is_currently_open():
            res_hours = preview_order(
                branch_id=branch.id,
                items=[{"name": menu_item.name, "quantity": 1}],
                customer_address=test_addr,
                access_key=access_key
            )
            assert res_hours.get("status") == "branch_closed", f"Expected branch_closed, got {res_hours}"
            assert "مغلق حالياً" in res_hours["ai_speech_response"]
            print(f"✓ Closed branch outside working hours correctly rejected preview:")
            print(f"  Speech: \"{res_hours['ai_speech_response']}\"")
        else:
            print("  (Skipping specific hour test because current time falls in 1-2 AM)")

    finally:
        branch.is_accepting_orders = orig_accepting
        branch.opening_time = orig_open_time
        branch.closing_time = orig_close_time
        branch.save()

    # -------------------------------------------------------------
    # 4. Test get_menu Optimization & is_branch_open
    # -------------------------------------------------------------
    print("\n--- 4. Testing get_menu Optimized Slicing & Operating Status ---")
    menu_res = get_menu(branch_id=branch.id, limit=5, access_key=access_key)
    assert menu_res["ok"] is True
    assert "is_branch_open" in menu_res
    assert menu_res["returned_items"] <= 5
    assert len(menu_res["categories"]) > 0
    print(f"✓ get_menu returned successfully with is_branch_open={menu_res['is_branch_open']}, returned_items={menu_res['returned_items']}, total_items={menu_res['total_items']}.")

    print("\n" + "=" * 70)
    print("🎉 ALL NEW FIXES AND ENHANCEMENTS PASSED 100%!")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()
