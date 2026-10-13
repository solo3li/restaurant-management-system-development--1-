import os
import sys
import json
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from core.models import Tenant, Branch, MenuItem, DeliveryArea, Order, OrderItem, UserProfile

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

    print("\n" + "=" * 60)
    print("🎉 ALL DIGITAL MENU E2E TESTS PASSED PERFECTLY!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
