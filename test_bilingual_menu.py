import os
import sys
import json
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from core.models import Tenant, Branch, MenuItem, MenuItemVariant, MenuCategory, DeliveryArea, Order, OrderItem, UserProfile

def run_bilingual_tests():
    print("=" * 60)
    print("🌐 Starting Digital Menu Bilingual (AR/EN) Test Suite")
    print("=" * 60)

    client = Client()

    tenant = Tenant.objects.first()
    assert tenant is not None, "No tenant found!"
    branch = Branch.objects.filter(tenant=tenant, status="active").first()
    assert branch is not None, "No active branch found!"

    # 1. Update Branch with English Name
    branch.name = "الفرع الرئيسي"
    branch.name_en = "Main Branch"
    branch.save()
    print(f"✅ Branch updated with bilingual names: AR='{branch.name}' | EN='{branch.name_en}'")

    # 2. Create Bilingual Category
    cat = MenuCategory.objects.create(
        tenant=tenant,
        name="برجر كلاسيك",
        name_en="Classic Burgers",
        ordering=1,
        is_active=True
    )
    print(f"✅ MenuCategory created: AR='{cat.name}' | EN='{cat.name_en}'")

    # 3. Create Bilingual MenuItem with Variants
    item = MenuItem.objects.create(
        tenant=tenant,
        category_rel=cat,
        name="برجر لحم مدخن",
        name_en="Smoked Beef Burger",
        description="شريحة لحم أنجوس مشوية مع جبنة شيدر وصوص مدخن",
        description_en="Angus beef patty grilled with cheddar cheese and smoky sauce",
        price=35.00,
        available=True,
        has_variants=True
    )

    v_single = MenuItemVariant.objects.create(
        menu_item=item,
        name="سنجل (فردي)",
        name_en="Single Patty",
        price=35.00,
        is_default=True
    )
    v_double = MenuItemVariant.objects.create(
        menu_item=item,
        name="دبل (مزدوج)",
        name_en="Double Patty",
        price=48.00,
        is_default=False
    )
    print(f"✅ MenuItem created with variants: Item EN='{item.name_en}', Variants EN=['{v_single.name_en}', '{v_double.name_en}']")

    # 4. Test Language Switcher Endpoint (/set-language/en/)
    print("\n--- 1. Testing Language Switcher Endpoint ---")
    resp_switch = client.get(f"/set-language/en/?next=/m/{tenant.slug}/")
    assert resp_switch.status_code == 302, f"Expected 302, got {resp_switch.status_code}"
    assert resp_switch.url == f"/m/{tenant.slug}/"
    assert client.session.get("django_language") == "en"
    print("✅ /set-language/en/ successfully redirected and set session/cookie to 'en'")

    # 5. Test English Rendering of Digital Menu
    print("\n--- 2. Testing English Digital Menu View ---")
    resp_en = client.get(f"/m/{tenant.slug}/")
    assert resp_en.status_code == 200
    html_en = resp_en.content.decode("utf-8")

    assert 'lang="en"' in html_en, "HTML lang attribute is not 'en'"
    assert 'dir="ltr"' in html_en, "HTML dir attribute is not 'ltr'"
    assert "Takeaway Pickup" in html_en, "'Takeaway Pickup' missing in English menu"
    assert "Home Delivery" in html_en, "'Home Delivery' missing in English menu"
    assert "Search for a meal, dish, or drink..." in html_en, "English search placeholder missing"
    assert "Classic Burgers" in html_en, "Category name_en 'Classic Burgers' not rendered"
    assert "Smoked Beef Burger" in html_en, "Item name_en 'Smoked Beef Burger' not rendered"
    assert "Single Patty" in html_en, "Variant name_en 'Single Patty' not rendered"
    assert "Double Patty" in html_en, "Variant name_en 'Double Patty' not rendered"
    assert "Main Branch" in html_en, "Branch name_en 'Main Branch' not rendered"
    assert "SAR" in html_en, "Currency 'SAR' not rendered"
    assert "View Cart & Order" in html_en, "Cart bar text 'View Cart & Order' not rendered"
    assert "Send Order to Restaurant Now" in html_en, "Submit button text missing in English"
    print("✅ English Digital Menu successfully verified: LTR layout, English names, variants, and UI strings intact!")

    # 6. Test Language Switcher Endpoint back to Arabic (/set-language/ar/)
    print("\n--- 3. Testing Switching Back to Arabic ---")
    resp_switch_ar = client.get(f"/set-language/ar/?next=/m/{tenant.slug}/")
    assert resp_switch_ar.status_code == 302
    assert client.session.get("django_language") == "ar"

    resp_ar = client.get(f"/m/{tenant.slug}/")
    assert resp_ar.status_code == 200
    html_ar = resp_ar.content.decode("utf-8")

    assert 'lang="ar"' in html_ar, "HTML lang attribute is not 'ar'"
    assert 'dir="rtl"' in html_ar, "HTML dir attribute is not 'rtl'"
    assert "استلام سفري من الفرع" in html_ar, "'استلام سفري من الفرع' missing in Arabic menu"
    assert "توصيل إلى منزلك" in html_ar, "'توصيل إلى منزلك' missing in Arabic menu"
    assert "برجر كلاسيك" in html_ar, "Category Arabic name missing"
    assert "برجر لحم مدخن" in html_ar, "Item Arabic name missing"
    assert "سنجل (فردي)" in html_ar, "Variant Arabic name missing"
    assert "ر.س" in html_ar, "Arabic currency 'ر.س' missing"
    assert "معاينة الطلب والسلة" in html_ar, "Arabic cart text missing"
    print("✅ Arabic Digital Menu successfully verified: RTL layout, Arabic names, and UI strings intact!")

    # 7. Test English Order Placement Response
    print("\n--- 4. Testing Placing Order with English Session ---")
    client.get(f"/set-language/en/?next=/m/{tenant.slug}/")
    order_payload = {
        "branch_id": branch.id,
        "order_type": "takeaway",
        "customer_name": "Alexander Smith",
        "customer_phone": "0559988112",
        "notes": "Extra crispy",
        "items": [
            {
                "menuItemId": item.id,
                "variantId": v_double.id,
                "qty": 1,
                "notes": ""
            }
        ]
    }
    resp_order = client.post(
        f"/api/m/{tenant.slug}/order/",
        data=json.dumps(order_payload),
        content_type="application/json"
    )
    assert resp_order.status_code == 201, f"Expected 201, got {resp_order.status_code}: {resp_order.content.decode('utf-8')}"
    ord_data = resp_order.json()
    assert ord_data["branch_name"] == "Main Branch", f"Expected 'Main Branch', got '{ord_data['branch_name']}'"
    assert ord_data["order_type"] == "Takeaway Pickup", f"Expected 'Takeaway Pickup', got '{ord_data['order_type']}'"
    assert "received successfully" in ord_data["message"], f"Expected English success message, got '{ord_data['message']}'"
    print(f"✅ Order #{ord_data['order_number']} placed in English with localized response: {ord_data['message']}")

    # Clean up test records
    item.delete()
    cat.delete()
    print("✅ Cleanup complete.")

    print("\n" + "=" * 60)
    print("🎉 ALL BILINGUAL TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 60)

if __name__ == "__main__":
    run_bilingual_tests()
