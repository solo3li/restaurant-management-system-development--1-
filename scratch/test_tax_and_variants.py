import os
import sys
from decimal import Decimal

# Ensure UTF-8 output
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
import django
django.setup()

from core.models import Tenant, Branch, MenuItem, MenuItemVariant, TenantApiKey, Order, OrderItem, Customer
from core.mcp_server import preview_order, create_callcenter_order

def run_tax_and_variant_tests():
    print("=" * 70)
    print("🧪 TESTING DYNAMIC BRANCH TAX & ITEM VARIANTS END-TO-END")
    print("=" * 70)

    tenant = Tenant.objects.filter(is_active=True).first()
    assert tenant, "No active tenant found!"

    # 1. Setup Branch A: 14% Tax Inclusive
    branch_inc, _ = Branch.objects.get_or_create(
        tenant=tenant,
        name="فرع القاهرة (شامل الضريبة 14%)",
        defaults={
            "city": "القاهرة",
            "status": "active",
            "currency": "EGP",
            "tax_percentage": Decimal("14.00"),
            "is_tax_inclusive": True,
        }
    )
    branch_inc.tax_percentage = Decimal("14.00")
    branch_inc.is_tax_inclusive = True
    branch_inc.save()

    # 2. Setup Branch B: 10% Tax Exclusive
    branch_exc, _ = Branch.objects.get_or_create(
        tenant=tenant,
        name="فرع الإسكندرية (غير شامل الضريبة 10%)",
        defaults={
            "city": "الإسكندرية",
            "status": "active",
            "currency": "EGP",
            "tax_percentage": Decimal("10.00"),
            "is_tax_inclusive": False,
        }
    )
    branch_exc.tax_percentage = Decimal("10.00")
    branch_exc.is_tax_inclusive = False
    branch_exc.save()

    # 3. Create or get API key
    key_obj, _ = TenantApiKey.objects.get_or_create(
        tenant=tenant,
        name="مفتاح فحص الضرائب والأحجام",
        defaults={"key": "ak_live_tax_test_key_12345678901234567890"}
    )
    access_key = key_obj.key

    # 4. Create a Menu Item with Variants (e.g. بيتزا مشكل: وسط 120، كبير 180)
    pizza_item, _ = MenuItem.objects.get_or_create(
        tenant=tenant,
        name="بيتزا جبن كلاسيك",
        defaults={
            "category": "بيتزا",
            "price": Decimal("100.00"),
            "available": True,
            "has_variants": True,
        }
    )
    pizza_item.has_variants = True
    pizza_item.available = True
    pizza_item.save()

    v_medium, _ = MenuItemVariant.objects.get_or_create(
        menu_item=pizza_item,
        name="وسط",
        defaults={"price": Decimal("120.00")}
    )
    v_large, _ = MenuItemVariant.objects.get_or_create(
        menu_item=pizza_item,
        name="كبير",
        defaults={"price": Decimal("180.00")}
    )

    print(f"Created/Verified Item: {pizza_item.name} with variants: {v_medium.name} ({v_medium.price}), {v_large.name} ({v_large.price})")

    # -------------------------------------------------------------
    # Test 1: Item with variants without specifying size
    # -------------------------------------------------------------
    print("\n--- Test 1: Ordering item with variants without size selection ---")
    res_var_req = preview_order(
        branch_id=branch_inc.id,
        order_type="takeaway",
        items=[{"name": "بيتزا جبن كلاسيك", "quantity": 1}],
        access_key=access_key
    )
    assert res_var_req.get("status") == "variant_selection_required", f"Expected variant_selection_required, got: {res_var_req}"
    assert "وسط" in res_var_req.get("ai_speech_response"), "Expected variants mentioned in ai_speech_response"
    print("✓ Correctly returned status='variant_selection_required' with available options and speech guidance.")

    # -------------------------------------------------------------
    # Test 2: Tax Inclusive Calculation (Branch A - 14% Inclusive)
    # -------------------------------------------------------------
    print("\n--- Test 2: Tax-Inclusive Preview (14% VAT) ---")
    res_inc = preview_order(
        branch_id=branch_inc.id,
        order_type="takeaway",
        items=[{"name": "بيتزا جبن كلاسيك", "variant": "كبير", "quantity": 1}],
        access_key=access_key
    )
    assert res_inc["ok"] is True, f"Failed: {res_inc}"
    assert res_inc["is_tax_inclusive"] is True
    assert res_inc["tax_percentage"] == 14.0
    assert res_inc["subtotal"] == 180.0
    assert res_inc["total"] == 180.0
    # 180 - (180 / 1.14) = 22.105... -> 22.11
    assert abs(res_inc["tax"] - 22.11) < 0.05
    print(f"✓ Tax Inclusive OK: Subtotal={res_inc['subtotal']}, Tax={res_inc['tax']} (14%), Total={res_inc['total']}")

    # -------------------------------------------------------------
    # Test 3: Tax Exclusive Calculation (Branch B - 10% Exclusive)
    # -------------------------------------------------------------
    print("\n--- Test 3: Tax-Exclusive Preview (10% VAT Added On Top) ---")
    res_exc = preview_order(
        branch_id=branch_exc.id,
        order_type="takeaway",
        items=[{"name": "بيتزا جبن كلاسيك", "variant": "كبير", "quantity": 1}],
        access_key=access_key
    )
    assert res_exc["ok"] is True, f"Failed: {res_exc}"
    assert res_exc["is_tax_inclusive"] is False
    assert res_exc["tax_percentage"] == 10.0
    assert res_exc["subtotal"] == 180.0
    # 180 * 0.10 = 18.0
    assert res_exc["tax"] == 18.0
    # Total = 180 + 18 = 198.0
    assert res_exc["total"] == 198.0
    print(f"✓ Tax Exclusive OK: Subtotal={res_exc['subtotal']}, Tax={res_exc['tax']} (10%), Total={res_exc['total']}")

    # -------------------------------------------------------------
    # Test 4: Call Center Order Creation with Variant & Dynamic Tax Saved
    # -------------------------------------------------------------
    print("\n--- Test 4: Creating Order with Variant & Verifying Database Record ---")
    test_phone = "01055443322"
    order_res = create_callcenter_order(
        branch_id=branch_exc.id,
        order_type="takeaway",
        customer_phone=test_phone,
        customer_name="عميل فحص الضرائب",
        items=[{"name": "بيتزا جبن كلاسيك", "variant": "وسط", "quantity": 2}],
        access_key=access_key
    )
    assert order_res["ok"] is True, f"Order placement failed: {order_res}"
    order_data = order_res["order"]
    assert order_data["tax_percentage"] == 10.0
    assert order_data["is_tax_inclusive"] is False
    # Subtotal: 120 * 2 = 240
    assert order_data["subtotal"] == 240.0
    # Tax: 240 * 0.10 = 24.0
    assert order_data["tax"] == 24.0
    # Total: 240 + 24 = 264.0
    assert order_data["total"] == 264.0

    # Verify Database record directly
    db_order = Order.objects.get(order_number=order_data["order_number"])
    assert db_order.tax_percentage == Decimal("10.00")
    assert db_order.tax == Decimal("24.00")
    assert db_order.total == Decimal("264.00")

    db_item = db_order.items.first()
    assert db_item is not None
    assert db_item.variant_id == v_medium.id
    assert db_item.variant_name == "وسط"
    assert db_item.price == Decimal("120.00")
    assert db_item.qty == 2
    print(f"✓ Order #{db_order.order_number} saved in DB with Tax={db_order.tax} ({db_order.tax_percentage}%), Total={db_order.total}")
    print(f"✓ OrderItem saved with variant='{db_item.variant_name}', price={db_item.price}, qty={db_item.qty}")

    print("\n" + "=" * 70)
    print("🎉 ALL TAX & VARIANT INTEGRATION TESTS PASSED 100%!")
    print("=" * 70)

if __name__ == "__main__":
    run_tax_and_variant_tests()
