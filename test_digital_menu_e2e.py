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

def run_tests():
    print("=" * 60)
    print("🚀 Starting Digital Menu & Self-Ordering E2E Test Suite")
    print("=" * 60)

    client = Client()

    # 1. Setup or Fetch Tenant and Test Data
    tenant = Tenant.objects.first()
    assert tenant is not None, "No tenant found in database!"
    print(f"✅ Found Active Tenant: {tenant.name} (Slug: {tenant.slug})")

    branch = Branch.objects.filter(tenant=tenant, status="active").first()
    assert branch is not None, "No active branch found for tenant!"
    print(f"✅ Found Active Branch: {branch.name} (ID: {branch.id})")

    item = MenuItem.objects.filter(tenant=tenant, available=True).first()
    assert item is not None, "No available MenuItem found for tenant!"
    print(f"✅ Found Available Item: {item.name} (Price: {item.price} SAR)")

    area = DeliveryArea.objects.filter(branch=branch).first()
    if not area:
        area = DeliveryArea.objects.create(
            branch=branch,
            name="حي النرجس التجريبي",
            delivery_fee=15.00
        )
    print(f"✅ Delivery Area Ready: {area.name} (Fee: {area.delivery_fee} SAR)")

    # 2. Test Public Digital Menu View
    print("\n--- 1. Testing Public Digital Menu View ---")
    resp = client.get(f"/m/{tenant.slug}/")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert tenant.name.encode("utf-8") in resp.content or "المنيو" in resp.content.decode("utf-8"), "Tenant name or menu not rendered"
    print(f"✅ GET /m/{tenant.slug}/ returned HTTP 200 OK")

    resp_branch = client.get(f"/m/{tenant.slug}/branch/{branch.id}/")
    assert resp_branch.status_code == 200, f"Expected 200, got {resp_branch.status_code}"
    print(f"✅ GET /m/{tenant.slug}/branch/{branch.id}/ returned HTTP 200 OK")

    resp_areas = client.get(f"/api/m/{tenant.slug}/areas/{branch.id}/")
    assert resp_areas.status_code == 200, f"Expected 200, got {resp_areas.status_code}"
    areas_data = resp_areas.json()
    assert "areas" in areas_data, "No 'areas' key in response"
    print(f"✅ GET /api/m/{tenant.slug}/areas/{branch.id}/ returned {len(areas_data['areas'])} areas")

    # 3. Test Placing Takeaway Order
    print("\n--- 2. Testing Placing Takeaway Order ---")
    takeaway_payload = {
        "branch_id": branch.id,
        "order_type": "takeaway",
        "customer_name": "سعد التميمي",
        "customer_phone": "0551122334",
        "notes": "الرجاء عدم وضع كاتشب",
        "items": [
            {
                "id": item.id,
                "qty": 2,
                "notes": "حار زيادة"
            }
        ]
    }
    resp_order1 = client.post(
        f"/api/m/{tenant.slug}/order/",
        data=json.dumps(takeaway_payload),
        content_type="application/json"
    )
    assert resp_order1.status_code == 201, f"Expected 201, got {resp_order1.status_code}: {resp_order1.content.decode('utf-8')}"
    order1_data = resp_order1.json()
    order1_id = order1_data["order_id"]
    order1_obj = Order.objects.get(id=order1_id)
    assert order1_obj.channel == "qr_menu", f"Expected channel 'qr_menu', got '{order1_obj.channel}'"
    assert order1_obj.order_type == "takeaway", f"Expected 'takeaway', got '{order1_obj.order_type}'"
    assert order1_obj.status == "new", f"Expected status 'new', got '{order1_obj.status}'"
    expected_subtotal = item.price * 2
    assert abs(float(order1_obj.subtotal) - float(expected_subtotal)) < 0.01, f"Expected subtotal {expected_subtotal}, got {order1_obj.subtotal}"
    assert abs(float(order1_obj.total) - float(expected_subtotal)) < 0.01, f"Expected total {expected_subtotal}, got {order1_obj.total}"
    assert order1_obj.delivery_fee == 0, f"Expected 0 delivery fee, got {order1_obj.delivery_fee}"
    print(f"✅ Takeaway Order #{order1_obj.order_number} created successfully: Total = {order1_obj.total} SAR, Channel = {order1_obj.channel}")

    # 4. Test Placing Delivery Order
    print("\n--- 3. Testing Placing Delivery Order ---")
    delivery_payload = {
        "branch_id": branch.id,
        "order_type": "delivery",
        "customer_name": "نورة المنصور",
        "customer_phone": "0509988776",
        "address": "طريق الملك فهد، عمارة 12، شقة 4",
        "delivery_area_id": area.id,
        "items": [
            {
                "id": item.id,
                "qty": 1,
                "notes": ""
            }
        ]
    }
    resp_order2 = client.post(
        f"/api/m/{tenant.slug}/order/",
        data=json.dumps(delivery_payload),
        content_type="application/json"
    )
    assert resp_order2.status_code == 201, f"Expected 201, got {resp_order2.status_code}: {resp_order2.content.decode('utf-8')}"
    order2_data = resp_order2.json()
    order2_id = order2_data["order_id"]
    order2_obj = Order.objects.get(id=order2_id)
    assert order2_obj.channel == "qr_menu", f"Expected channel 'qr_menu', got '{order2_obj.channel}'"
    assert order2_obj.order_type == "delivery", f"Expected 'delivery', got '{order2_obj.order_type}'"
    assert order2_obj.delivery_area == area
    expected_delivery_total = float(item.price) + float(area.delivery_fee)
    assert abs(float(order2_obj.total) - expected_delivery_total) < 0.01, f"Expected total {expected_delivery_total}, got {order2_obj.total}"
    print(f"✅ Delivery Order #{order2_obj.order_number} created successfully: Subtotal = {order2_obj.subtotal} + Delivery = {order2_obj.delivery_fee} -> Total = {order2_obj.total} SAR")

    # 5. Test Rejection of Dine-in Orders (Strict takeaway & delivery only)
    print("\n--- 4. Testing Strict Dine-in Rejection ---")
    dinein_payload = {
        "branch_id": branch.id,
        "order_type": "dine_in",
        "customer_name": "فهد",
        "customer_phone": "0555555555",
        "items": [{"id": item.id, "qty": 1}]
    }
    resp_dinein = client.post(
        f"/api/m/{tenant.slug}/order/",
        data=json.dumps(dinein_payload),
        content_type="application/json"
    )
    assert resp_dinein.status_code == 400, f"Expected 400 for dine_in, got {resp_dinein.status_code}"
    print(f"✅ Dine-in successfully rejected: {resp_dinein.json().get('error')}")

    # 6. Test Tenant Branding API
    print("\n--- 5. Testing Tenant Branding & Identity Updates ---")
    owner_profile = UserProfile.objects.filter(tenant=tenant, role="owner").first()
    owner_user = owner_profile.user if owner_profile else User.objects.filter(is_superuser=True).first()
    assert owner_user is not None, "Tenant owner or admin user is missing"
    client.force_login(owner_user)
    session = client.session
    session["active_tenant_id"] = tenant.id
    session.save()

    branding_resp = client.post("/api/settings/branding/", {
        "name": f"{tenant.name}",
        "bio": "أفخم المأكولات والمشويات المشوية على الفحم يومياً",
        "brand_color": "#124E3F",
        "logo_emoji": "🍔"
    })
    assert branding_resp.status_code == 200, f"Expected 200, got {branding_resp.status_code}: {branding_resp.content.decode('utf-8')}"
    tenant.refresh_from_db()
    assert tenant.bio == "أفخم المأكولات والمشويات المشوية على الفحم يومياً"
    assert tenant.brand_color == "#124E3F"
    print(f"✅ Tenant Branding updated successfully: Bio='{tenant.bio}', Brand Color='{tenant.brand_color}'")

    # 7. Test Custom Domain Binding & Middleware
    print("\n--- 6. Testing Custom Domain Binding & Auto-Routing Middleware ---")
    test_custom_domain = "order.testrestaurant.local"
    
    # Bind domain
    domain_resp = client.post(
        "/api/settings/custom-domain/",
        data=json.dumps({"custom_domain": test_custom_domain}),
        content_type="application/json"
    )
    assert domain_resp.status_code == 200, f"Expected 200, got {domain_resp.status_code}"
    tenant.refresh_from_db()
    assert tenant.custom_domain == test_custom_domain, f"Domain not saved: {tenant.custom_domain}"
    print(f"✅ Custom Domain bound successfully to tenant: {tenant.custom_domain}")

    # Test Host Header routing via Middleware (anonymous customer visitor)
    anon_client = Client()
    host_resp = anon_client.get("/", HTTP_HOST=test_custom_domain)
    assert host_resp.status_code == 200, f"Expected 200 when requesting custom domain root, got {host_resp.status_code}"
    assert tenant.name.encode("utf-8") in host_resp.content or "المنيو" in host_resp.content.decode("utf-8"), "Digital menu was not returned on custom domain root"
    print(f"✅ Middleware successfully routed Host '{test_custom_domain}/' directly to Digital Menu!")

    # Unbind domain clean up
    clear_resp = client.post(
        "/api/settings/custom-domain/",
        data=json.dumps({"custom_domain": ""}),
        content_type="application/json"
    )
    assert clear_resp.status_code == 200
    tenant.refresh_from_db()
    assert tenant.custom_domain is None
    print("✅ Custom Domain unbind clean up successful")

    import time
    test_suffix = int(time.time())
    test_cat_name = f"معجنات تجريبية {test_suffix}"
    test_cat_updated = f"معجنات إيطالية {test_suffix}"
    test_item_name = f"بيتزا بافلو {test_suffix}"

    # 8. Test Category CRUD via API
    print("\n--- 7. Testing Category Management CRUD APIs ---")
    cat_create_resp = client.post("/api/menu/categories/create/", {
        "name": test_cat_name,
        "description": "أشهى أنواع البيتزا والمعجنات الطازجة",
        "ordering": "5"
    })
    assert cat_create_resp.status_code in [200, 201], f"Expected 200/201, got {cat_create_resp.status_code}: {cat_create_resp.content.decode('utf-8')}"
    new_cat_id = cat_create_resp.json().get("id") or cat_create_resp.json().get("category", {}).get("id")
    test_cat = MenuCategory.objects.get(id=new_cat_id, tenant=tenant)
    assert test_cat.name == test_cat_name
    print(f"✅ Category created: {test_cat.name} (ID: {test_cat.id})")

    # Update category
    cat_update_resp = client.post(f"/api/menu/categories/{new_cat_id}/", {
        "name": test_cat_updated,
        "description": "وصف محدث للقسم",
        "ordering": "2"
    })
    assert cat_update_resp.status_code == 200
    test_cat.refresh_from_db()
    assert test_cat.name == test_cat_updated
    assert test_cat.description == "وصف محدث للقسم"
    print(f"✅ Category updated: {test_cat.name}")

    # List categories
    cat_list_resp = client.get("/api/menu/categories/")
    assert cat_list_resp.status_code == 200
    cats_data = cat_list_resp.json()["categories"]
    assert any(c["id"] == new_cat_id for c in cats_data)
    print(f"✅ List categories returned {len(cats_data)} categories including new one")

    # 9. Test MenuItem with Variants CRUD via API
    print("\n--- 8. Testing MenuItem Creation with Multiple Size Variants ---")
    variants_json = json.dumps([
        {"name": "صغير", "price": 18.00, "cost": 7.00, "is_default": False},
        {"name": "وسط", "price": 28.00, "cost": 11.00, "is_default": True},
        {"name": "كبير", "price": 42.00, "cost": 16.00, "is_default": False}
    ])
    item_create_resp = client.post("/api/menu/create/", {
        "name": test_item_name,
        "category_id": new_cat_id,
        "price": "28.00",
        "cost_price": "11.00",
        "description": "بيتزا إيطالية بجبنة الموزاريلا وصوص البافلو",
        "has_variants": "true",
        "variants": variants_json
    })
    assert item_create_resp.status_code in [200, 201], f"Expected 200/201, got {item_create_resp.status_code}: {item_create_resp.content.decode('utf-8')}"
    new_item_id = item_create_resp.json().get("id") or item_create_resp.json().get("item", {}).get("id")
    test_item = MenuItem.objects.get(id=new_item_id, tenant=tenant)

    assert test_item.has_variants is True
    assert test_item.variants.count() == 3
    assert test_item.min_price == 18.00
    v_small = test_item.variants.get(name="صغير")
    v_medium = test_item.variants.get(name="وسط")
    v_large = test_item.variants.get(name="كبير")
    assert v_medium.is_default is True
    print(f"✅ MenuItem with 3 variants created: {test_item.name} (Min price: {test_item.min_price} SAR)")

    # 10. Test Digital Menu Self-Ordering with Specific Variant Size
    print("\n--- 9. Testing Ordering with Variant Size via Digital Menu ---")
    variant_order_payload = {
        "branch_id": branch.id,
        "order_type": "takeaway",
        "customer_name": "عبدالله الراجحي",
        "customer_phone": "0543219876",
        "items": [
            {
                "menuItemId": test_item.id,
                "variantId": v_large.id,
                "qty": 2,
                "notes": "زيادة جبنة"
            }
        ]
    }
    resp_v_order = client.post(
        f"/api/m/{tenant.slug}/order/",
        data=json.dumps(variant_order_payload),
        content_type="application/json"
    )
    assert resp_v_order.status_code == 201, f"Expected 201, got {resp_v_order.status_code}: {resp_v_order.content.decode('utf-8')}"
    v_order_data = resp_v_order.json()
    v_order_obj = Order.objects.get(id=v_order_data["order_id"])
    expected_v_total = float(v_large.price) * 2 # 42 * 2 = 84
    assert abs(float(v_order_obj.total) - expected_v_total) < 0.01
    oi = v_order_obj.items.first()
    assert oi.variant == v_large
    assert oi.price == v_large.price
    print(f"✅ Order with Variant #{v_order_obj.order_number} confirmed: Size='{oi.variant_name}', Price={oi.price} SAR, Total={v_order_obj.total} SAR")

    # 11. Test Branch Operating Hours Enforcement (Store Closed)
    print("\n--- 10. Testing Branch Operating Hours & Order Acceptance ---")
    orig_accepting = branch.is_accepting_orders
    branch.is_accepting_orders = False
    branch.save(update_fields=["is_accepting_orders"])

    closed_order_payload = {
        "branch_id": branch.id,
        "order_type": "takeaway",
        "customer_name": "سلطان",
        "customer_phone": "0555551234",
        "items": [{"menuItemId": test_item.id, "qty": 1}]
    }
    resp_closed = client.post(
        f"/api/m/{tenant.slug}/order/",
        data=json.dumps(closed_order_payload),
        content_type="application/json"
    )
    assert resp_closed.status_code == 400, f"Expected 400 when branch closed, got {resp_closed.status_code}"
    assert "مغلق" in resp_closed.json().get("message", "")
    print(f"✅ Correctly rejected order when branch is closed: {resp_closed.json().get('message')}")

    # Re-enable branch
    branch.is_accepting_orders = orig_accepting
    branch.save(update_fields=["is_accepting_orders"])

    # 12. Test Minimum Delivery Order Threshold
    print("\n--- 11. Testing Minimum Delivery Order Enforcement ---")
    orig_min = branch.min_delivery_order
    branch.min_delivery_order = 100.00
    branch.save(update_fields=["min_delivery_order"])

    # Attempt delivery below 100 SAR (v_small = 18.00 SAR)
    under_min_payload = {
        "branch_id": branch.id,
        "order_type": "delivery",
        "customer_name": "ماجد العتيبي",
        "customer_phone": "0567890123",
        "address": "الرياض، حي الملقا",
        "delivery_area_id": area.id,
        "items": [{"menuItemId": test_item.id, "variantId": v_small.id, "qty": 1}]
    }
    resp_under = client.post(
        f"/api/m/{tenant.slug}/order/",
        data=json.dumps(under_min_payload),
        content_type="application/json"
    )
    assert resp_under.status_code == 400, f"Expected 400 when below min delivery order, got {resp_under.status_code}"
    assert "الحد الأدنى" in resp_under.json().get("message", "")
    print(f"✅ Order rejected below minimum delivery threshold: {resp_under.json().get('message')}")

    # Place delivery order exceeding threshold (3 x large = 3 x 42 = 126.00 SAR > 100)
    over_min_payload = {
        "branch_id": branch.id,
        "order_type": "delivery",
        "customer_name": "ماجد العتيبي",
        "customer_phone": "0567890123",
        "address": "الرياض، حي الملقا",
        "delivery_area_id": area.id,
        "items": [{"menuItemId": test_item.id, "variantId": v_large.id, "qty": 3}]
    }
    resp_over = client.post(
        f"/api/m/{tenant.slug}/order/",
        data=json.dumps(over_min_payload),
        content_type="application/json"
    )
    assert resp_over.status_code == 201, f"Expected 201 when exceeding min delivery, got {resp_over.status_code}: {resp_over.content.decode('utf-8')}"
    over_order = Order.objects.get(id=resp_over.json()["order_id"])
    print(f"✅ Delivery order exceeding threshold passed: Subtotal={over_order.subtotal} SAR, Total={over_order.total} SAR")

    # Restore min delivery
    branch.min_delivery_order = orig_min
    branch.save(update_fields=["min_delivery_order"])

    # 13. Test Soft Delete of Menu Items & Categories
    print("\n--- 12. Testing Safe Soft Delete / Archiving ---")
    del_item_resp = client.post(f"/api/menu/{test_item.id}/delete/")
    assert del_item_resp.status_code == 200
    test_item.refresh_from_db()
    assert test_item.is_active is False
    assert test_item.available is False
    print(f"✅ MenuItem safely soft-deleted: is_active={test_item.is_active}, available={test_item.available}")

    del_cat_resp = client.post(f"/api/menu/categories/{new_cat_id}/delete/")
    assert del_cat_resp.status_code == 200
    test_cat.refresh_from_db()
    assert test_cat.is_active is False
    print(f"✅ MenuCategory safely soft-deleted: is_active={test_cat.is_active}")

    # Verify historical orders referencing the item still exist and are valid
    assert OrderItem.objects.filter(menu_item=test_item).exists()
    print("✅ Historical OrderItems remained perfectly intact with no data loss!")

    print("\n" + "=" * 60)
    print("🎉 ALL DIGITAL MENU E2E TESTS PASSED PERFECTLY!")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
