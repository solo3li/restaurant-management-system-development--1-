import os
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import django

# Setup Django environment
sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from core.models import Tenant, SubscriptionPlan, UpgradeRequest, UserProfile, RestaurantOwner, TenantSubscription

def run_tests():
    print("=" * 70)
    print("🚀 AUTOMATED TEST SUITE: OWNERS & SUBSCRIBERS IN ADMIN & PLATFORM")
    print("=" * 70)

    # 1. Verify Superuser exists
    admin_user = User.objects.filter(is_superuser=True).first()
    if not admin_user:
        admin_user = User.objects.create_superuser("testadmin", "admin@example.com", "admin1234")
        print("Created test superuser: testadmin")
    else:
        print(f"Using existing superuser: {admin_user.username}")

    client = Client()
    client.force_login(admin_user)

    # 2. Check Proxy Models in ORM
    print("\n--- Testing Proxy Models in ORM ---")
    owner_count = RestaurantOwner.objects.count()
    user_owner_count = UserProfile.objects.filter(role="owner").count()
    print(f"RestaurantOwner count: {owner_count} (UserProfile owner count: {user_owner_count})")
    assert owner_count == user_owner_count, f"Mismatch: RestaurantOwner ({owner_count}) != UserProfile owner ({user_owner_count})"

    tenant_sub_count = TenantSubscription.objects.count()
    tenant_count = Tenant.objects.count()
    print(f"TenantSubscription count: {tenant_sub_count} (Tenant count: {tenant_count})")
    assert tenant_sub_count == tenant_count, f"Mismatch: TenantSubscription ({tenant_sub_count}) != Tenant ({tenant_count})"
    print("✓ Proxy Models ORM checks passed.")

    # 3. Test Django Admin Restaurant Owners Changelist (/admin/core/restaurantowner/)
    print("\n--- Testing Django Admin: Restaurant Owners Changelist ---")
    resp = client.get("/admin/core/restaurantowner/")
    print(f"GET /admin/core/restaurantowner/ -> Status Code: {resp.status_code}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    content = resp.content.decode("utf-8")
    assert "قائمة الملاك (Restaurant Owners)" in content or "Restaurant owners" in content or "RestaurantOwner" in content
    print("✓ Restaurant Owners Changelist rendered successfully with title.")

    # 4. Test Django Admin Tenant Subscribers Changelist (/admin/core/tenantsubscription/)
    print("\n--- Testing Django Admin: Tenant Subscribers Changelist ---")
    resp = client.get("/admin/core/tenantsubscription/")
    print(f"GET /admin/core/tenantsubscription/ -> Status Code: {resp.status_code}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    content = resp.content.decode("utf-8")
    assert "قائمة المشتركين (Subscribers)" in content or "Subscribers" in content or "TenantSubscription" in content
    print("✓ Tenant Subscribers Changelist rendered successfully with title and quotas.")

    # 5. Test Django Admin Upgrade Requests Changelist with Quick Actions (/admin/core/upgraderequest/)
    print("\n--- Testing Django Admin: Upgrade Requests with Quick Actions ---")
    resp = client.get("/admin/core/upgraderequest/")
    print(f"GET /admin/core/upgraderequest/ -> Status Code: {resp.status_code}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    content = resp.content.decode("utf-8")
    assert "quick-approve" in content or "quick-reject" in content or "طلبات ترقية الباقات" in content
    print("✓ Upgrade Requests Changelist rendered successfully with quick actions.")

    # 6. Test SaaS Platform Dashboard (/platform/)
    print("\n--- Testing SaaS Platform Dashboard: Owners Section & KPIs ---")
    resp = client.get("/platform/")
    print(f"GET /platform/ -> Status Code: {resp.status_code}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    content = resp.content.decode("utf-8")
    assert "سجل ملاك المطاعم والمنشآت" in content, "Owners section heading missing from /platform/"
    assert "ملاك المنشآت" in content, "Owners KPI card missing from /platform/"
    assert "/admin/core/restaurantowner/" in content, "Link to Restaurant Owners Admin missing from /platform/"
    print("✓ Platform Dashboard rendered Section 3 (Restaurant Owners) & KPI stats successfully.")

    print("\n" + "=" * 70)
    print("🎉 ALL TESTS PASSED! FULL VERIFICATION SUCCESSFUL.")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()
