import os
import sys
import django
from datetime import timedelta
from decimal import Decimal

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.utils import timezone
from core.models import Tenant, Branch, Customer, MenuItem, Order, TenantApiKey, DeliveryArea
from core.mcp_server import (
    _strip_al,
    _canonical_food_name,
    _parse_natural_order_text,
    _validate_delivery_address_completeness,
    create_callcenter_order,
    cancel_order,
    track_order,
)

def run_tests():
    print("=" * 70)
    print("🧪 TESTING MCP HARDENED FIXES & ARCHITECTURAL ENHANCEMENTS")
    print("=" * 70)

    # ----------------------------------------------------
    # 1. Linguistic & Natural Order Parsing Tests
    # ----------------------------------------------------
    print("\n--- 1. Testing Linguistic & Food Parsing Fixes ---")
    
    # 1.1 Prefix stripping protection
    assert _strip_al("البان") == "البان", f"Expected 'البان', got '{_strip_al('البان')}'"
    assert _strip_al("الوان") == "الوان", f"Expected 'الوان', got '{_strip_al('الوان')}'"
    assert _strip_al("البرجر") == "برجر", f"Expected 'برجر', got '{_strip_al('البرجر')}'"
    print("✓ _strip_al preserves root words ('البان', 'الوان') while stripping actual prefixes ('البرجر' -> 'برجر').")

    # 1.2 Brand identity preservation
    assert _canonical_food_name("بيبسي") == "بيبسي", f"Expected 'بيبسي', got '{_canonical_food_name('بيبسي')}'"
    assert _canonical_food_name("سفن") == "سفن", f"Expected 'سفن', got '{_canonical_food_name('سفن')}'"
    assert _canonical_food_name("كوكاكولا") == "كولا", f"Expected 'كولا', got '{_canonical_food_name('كوكاكولا')}'"
    print("✓ _canonical_food_name preserves distinct brand names ('بيبسي', 'سفن', 'كولا').")

    # 1.3 Natural text splitting with items starting with 'و'
    order_text = "2 بيتزا مارجريتا و 1 ورق عنب و وافل نوتيلا و وينجز دجاج"
    parsed_items = _parse_natural_order_text(order_text)
    item_names = [it["name"] for it in parsed_items]
    print(f"Parsed items from text: {item_names}")
    assert any("ورق عنب" in n for n in item_names), f"'ورق عنب' was mangled in {item_names}"
    assert any("وافل" in n for n in item_names), f"'وافل' was mangled in {item_names}"
    assert any("وينجز" in n for n in item_names), f"'وينجز' was mangled in {item_names}"
    print("✓ _parse_natural_order_text preserves words starting with 'و' ('ورق عنب', 'وافل', 'وينجز').")

    # ----------------------------------------------------
    # 2. Multi-Country Delivery Address Validation Tests
    # ----------------------------------------------------
    print("\n--- 2. Testing Multi-Country Address Validation ---")
    
    # 2.1 Saudi street address
    ksa_addr = "حي العليا طريق الملك فهد عمارة 12 الدور الرابع شقة 8"
    valid_ksa, err_ksa = _validate_delivery_address_completeness(ksa_addr, "العليا")
    assert valid_ksa, f"KSA standard address should be valid: {err_ksa}"
    print("✓ Saudi standard address ('حي العليا طريق الملك فهد عمارة 12 الدور الرابع شقة 8') accepted.")

    # 2.2 Saudi landmark with outdoor pickup
    ksa_outdoor = "مستني في السيارة قدام بوابة الرياض بارك"
    valid_out, err_out = _validate_delivery_address_completeness(ksa_outdoor, "الرياض بارك")
    assert valid_out, f"Outdoor pickup should be accepted: {err_out}"
    print("✓ Outdoor pickup at Saudi landmark accepted immediately.")

    # 2.3 Ambiguous landmark prompt
    valid_amb, err_amb = _validate_delivery_address_completeness("عند رد سي مول", "رد سي مول")
    assert not valid_amb and err_amb["status"] == "disambiguation_required"
    assert "فضلاً هل الاستلام بالخارج" in err_amb["ai_speech_response"]
    print("✓ Ambiguous landmark returns polite, dialect-neutral disambiguation speech.")

    # ----------------------------------------------------
    # 3. Customer Profile Preservation Tests
    # ----------------------------------------------------
    print("\n--- 3. Testing Customer Profile Strategy ---")
    tenant = Tenant.objects.first()
    branch = Branch.objects.filter(tenant=tenant, status="active").first()
    
    # Setup test customer
    test_phone = "0511223344"
    Customer.objects.filter(tenant=tenant, phone=test_phone).delete()
    original_customer = Customer.objects.create(
        tenant=tenant,
        phone=test_phone,
        name="محمد عبد الله (العميل الأصلي)",
        address="شارع الملك فهد عمارة 1 شقة 1"
    )

    # Create key
    key_obj = TenantApiKey.objects.create(
        tenant=tenant,
        name="Test Hardened Key",
        assigned_branch=branch
    )
    raw_key = key_obj.key

    # Order placed by colleague/family member with different recipient name and address
    recipient_name = "سارة أحمد"
    recipient_addr = "مدينة الشروق كمبوند النرجس عمارة 40 دور 2 شقة 5"
    
    item = MenuItem.objects.filter(tenant=tenant, available=True).first()
    res = create_callcenter_order(
        branch_id=branch.id,
        customer_phone=test_phone,
        customer_name=recipient_name,
        customer_address=recipient_addr,
        items=[{"item_id": item.id, "quantity": 2}],
        order_type="delivery",
        access_key=raw_key
    )
    assert res.get("ok"), f"Order creation failed: {res}"
    order_num = res["order_number"]
    print(f"✓ Placed order #{order_num}")

    # Verify original customer profile was NOT overwritten
    original_customer.refresh_from_db()
    assert original_customer.name == "محمد عبد الله (العميل الأصلي)", f"Customer name was overwritten to '{original_customer.name}'!"
    assert original_customer.address == "شارع الملك فهد عمارة 1 شقة 1", f"Customer address was overwritten!"
    print(f"✓ Customer profile preserved: Name='{original_customer.name}', Address='{original_customer.address}'")

    # Verify Order record captured recipient name and address
    db_order = Order.objects.get(order_number=order_num)
    assert db_order.customer_name == recipient_name, f"Order customer_name should be recipient '{recipient_name}', got '{db_order.customer_name}'"
    assert db_order.address == recipient_addr, f"Order address should be '{recipient_addr}', got '{db_order.address}'"
    assert f"[المستلم: {recipient_name}]" in db_order.notes
    print(f"✓ Order #{order_num} has recipient name='{db_order.customer_name}', address='{db_order.address}', and note='{db_order.notes}'")

    # ----------------------------------------------------
    # 4. Branch Cancellation Window Tests
    # ----------------------------------------------------
    print("\n--- 4. Testing Branch Configurable Cancellation Window ---")
    
    # 4.1 Cancellation within window succeeds
    branch.cancellation_window_minutes = 10
    branch.save(update_fields=["cancellation_window_minutes"])

    cancel_res = cancel_order(order_number=order_num, access_key=raw_key)
    assert cancel_res.get("ok"), f"Cancel within window failed: {cancel_res}"
    print(f"✓ Order #{order_num} cancelled successfully within 10-minute window.")

    # 4.2 Cancellation after window has expired is rejected
    expired_order = Order.objects.create(
        tenant=tenant,
        branch=branch,
        order_number=f"ORD-EXP-TEST-001",
        customer=original_customer,
        subtotal=Decimal("50.00"),
        total=Decimal("50.00"),
        status="new"
    )
    # Simulate order created 25 minutes ago
    Order.objects.filter(id=expired_order.id).update(created_at=timezone.now() - timedelta(minutes=25))
    expired_order.refresh_from_db()

    cancel_expired_res = cancel_order(order_number=expired_order.order_number, access_key=raw_key)
    assert not cancel_expired_res.get("ok"), "Order should NOT be cancellable after cancellation window expires!"
    assert cancel_expired_res.get("cancellation_window_minutes") == 10
    assert "مر عليه أكثر من 10 دقائق" in cancel_expired_res.get("ai_speech_response", "")
    print(f"✓ Order #{expired_order.order_number} correctly rejected for cancellation after exceeding branch window (25 mins > 10 mins).")

    # Clean up
    key_obj.delete()
    expired_order.delete()
    db_order.delete()
    original_customer.delete()

    print("\n" + "=" * 70)
    print("🎉 ALL HARDENED ARCHITECTURAL TESTS PASSED 100%!")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()
