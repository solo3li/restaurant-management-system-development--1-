import os
import sys
import django

# Fix console encoding for Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Setup Django environment
sys.path.append(r"c:\Users\solo\Downloads\restaurant-management-system-development (1)")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from core.models import Tenant, SubscriptionPlan, UpgradeRequest, DeliveryArea, JobRole, Branch

def test_django_admin():
    print("==================================================")
    print("TESTING DJANGO ADMIN FOR SUBSCRIPTIONS & UPGRADES")
    print("==================================================")

    client = Client()
    admin_user = User.objects.filter(is_superuser=True).first()
    assert admin_user is not None, "Superuser not found"
    client.force_login(admin_user)

    # 1. Test SubscriptionPlan list & add views
    print("\n--- 1. Testing SubscriptionPlan Admin Views ---")
    resp = client.get("/admin/core/subscriptionplan/")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    content = resp.content.decode("utf-8")
    assert "باقات اشتراك المنصة" in content or "Subscription" in content
    print("✓ /admin/core/subscriptionplan/ loaded successfully (200 OK)")

    resp = client.get("/admin/core/subscriptionplan/add/")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    print("✓ /admin/core/subscriptionplan/add/ loaded successfully (200 OK)")

    # 2. Test UpgradeRequest list view
    print("\n--- 2. Testing UpgradeRequest Admin Views ---")
    resp = client.get("/admin/core/upgraderequest/")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    print("✓ /admin/core/upgraderequest/ loaded successfully (200 OK)")

    # 3. Test DeliveryArea & JobRole views
    print("\n--- 3. Testing DeliveryArea & JobRole Admin Views ---")
    resp = client.get("/admin/core/deliveryarea/")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    print("✓ /admin/core/deliveryarea/ loaded successfully (200 OK)")

    resp = client.get("/admin/core/jobrole/")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    print("✓ /admin/core/jobrole/ loaded successfully (200 OK)")

    # 4. Test Tenant list view with subscription columns
    print("\n--- 4. Testing Tenant Admin View ---")
    resp = client.get("/admin/core/tenant/")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    content = resp.content.decode("utf-8")
    assert "حالة الاشتراك" in content
    print("✓ /admin/core/tenant/ shows subscription status and plan columns (200 OK)")

    # 5. Test Django Admin Custom Action: approve_requests
    print("\n--- 5. Testing Django Admin Action: approve_requests ---")
    tenant = Tenant.objects.filter(is_active=True).first()
    plan_starter = SubscriptionPlan.objects.filter(code="starter").first()
    plan_growth = SubscriptionPlan.objects.filter(code="growth").first()
    tenant.subscription_plan = plan_starter
    tenant.save()

    test_req = UpgradeRequest.objects.create(
        tenant=tenant,
        requested_plan=plan_growth,
        billing_cycle="yearly",
        requested_by=admin_user,
        notes="طلب ترقية تجريبي لاختبار Django Admin Action",
        status="pending",
    )

    action_data = {
        "action": "approve_requests",
        "_selected_action": [str(test_req.id)],
    }
    resp = client.post("/admin/core/upgraderequest/", data=action_data, follow=True)
    assert resp.status_code == 200

    test_req.refresh_from_db()
    tenant.refresh_from_db()
    assert test_req.status == "approved", f"Expected approved, got {test_req.status}"
    assert tenant.subscription_plan == plan_growth, f"Tenant plan was not updated to {plan_growth.name}"
    assert tenant.subscription_status == "active"
    print(f"✓ Admin Action 'approve_requests' successfully approved request #{test_req.id} and upgraded tenant to '{tenant.subscription_plan.name}'")

    # 6. Test Django Admin Custom Action: reject_requests
    print("\n--- 6. Testing Django Admin Action: reject_requests ---")
    test_req2 = UpgradeRequest.objects.create(
        tenant=tenant,
        requested_plan=plan_starter,
        billing_cycle="monthly",
        requested_by=admin_user,
        notes="طلب تجريبي للرفض",
        status="pending",
    )

    action_data = {
        "action": "reject_requests",
        "_selected_action": [str(test_req2.id)],
    }
    resp = client.post("/admin/core/upgraderequest/", data=action_data, follow=True)
    assert resp.status_code == 200

    test_req2.refresh_from_db()
    tenant.refresh_from_db()
    assert test_req2.status == "rejected", f"Expected rejected, got {test_req2.status}"
    assert tenant.subscription_plan == plan_growth, "Tenant plan should not have changed on rejection"
    print(f"✓ Admin Action 'reject_requests' successfully rejected request #{test_req2.id}")

    print("\n==================================================")
    print("ALL DJANGO ADMIN TESTS PASSED! 100% VERIFIED.")
    print("==================================================")

if __name__ == "__main__":
    test_django_admin()
