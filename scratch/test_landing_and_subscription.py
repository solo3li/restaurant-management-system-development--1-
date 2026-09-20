import os
import sys
import django
import json

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
from core.models import Tenant, Branch, Employee, UserProfile, SubscriptionPlan, UpgradeRequest

def run_tests():
    print("==================================================")
    print("STARTING TEST: LANDING PAGE & OWNER SUBSCRIPTION")
    print("==================================================")

    client = Client()

    # 1. TEST PUBLIC LANDING PAGE (UNAUTHENTICATED)
    print("\n--- 1. Testing Public Landing Page ---")
    resp = client.get("/")
    assert resp.status_code == 200, f"Expected 200 for landing page, got {resp.status_code}"
    content = resp.content.decode("utf-8")
    assert "ضِيَافَة" in content, "Brand name not found in landing page"
    assert "الجيل الجديد" in content, "Hero badge text not found in landing page"
    assert "دفع شهري" in content, "Pricing toggle not found in landing page"
    print("✓ Unauthenticated visitor receives public landing page (200 OK)")

    # 2. TEST AUTHENTICATED REDIRECTION FROM LANDING PAGE
    admin_user = User.objects.filter(is_superuser=True).first()
    assert admin_user is not None, "Superuser not found in database"
    client.force_login(admin_user)
    resp = client.get("/")
    assert resp.status_code in [302, 301], f"Expected 302 redirect for logged in user, got {resp.status_code}"
    print(f"✓ Authenticated user redirected from '/' to {resp.url} (302 Redirect)")
    client.logout()

    # 3. SETUP OWNER AND TENANT FOR SUBSCRIPTION TESTS
    print("\n--- 2. Testing Owner Subscription Dashboard ---")
    tenant = Tenant.objects.filter(is_active=True).first()
    assert tenant is not None, "Active tenant not found"

    # Ensure subscription plan exists
    plan_basic = SubscriptionPlan.objects.filter(code="starter").first()
    if not plan_basic:
        plan_basic = SubscriptionPlan.objects.create(
            name="باقة البداية",
            code="starter",
            description="مناسبة لتشغيل فرع واحد وكادر محدود",
            price_monthly=199,
            price_yearly=1990,
            max_branches=1,
            max_employees=5,
            features=["pos_billing", "kds_kitchen", "basic_reports"],
            is_active=True,
            ordering=1,
        )

    plan_pro = SubscriptionPlan.objects.filter(code="growth").first()
    if not plan_pro:
        plan_pro = SubscriptionPlan.objects.create(
            name="باقة النمو المتقدمة",
            code="growth",
            description="لتوسيع الفروع وتشغيل الكول سنتر والمخزون",
            price_monthly=499,
            price_yearly=4990,
            max_branches=5,
            max_employees=25,
            features=["pos_billing", "kds_kitchen", "call_center", "inventory_mgmt", "delivery_zones", "custom_roles"],
            is_active=True,
            is_popular=True,
            ordering=2,
        )

    tenant.subscription_plan = plan_basic
    tenant.save()

    # Create / Get owner user
    owner_user, _ = User.objects.get_or_create(username="test_owner_user", defaults={"first_name": "المالك التجريبي"})
    owner_user.set_password("pass123")
    owner_user.save()
    UserProfile.objects.update_or_create(
        user=owner_user,
        defaults={
            "tenant": tenant,
            "role": "owner",
            "is_platform_admin": False,
        }
    )

    # Test unauthenticated access to /subscription/
    resp = client.get("/subscription/")
    assert resp.status_code == 302, f"Expected 302 login redirect, got {resp.status_code}"
    print("✓ Unauthenticated request to /subscription/ redirected to login")

    # Test employee (non-owner) access to /subscription/
    emp_user, _ = User.objects.get_or_create(username="test_cashier_user", defaults={"first_name": "كاشير"})
    emp_user.set_password("pass123")
    emp_user.save()
    UserProfile.objects.update_or_create(
        user=emp_user,
        defaults={
            "tenant": tenant,
            "role": "cashier",
            "is_platform_admin": False,
        }
    )
    client.force_login(emp_user)
    resp = client.get("/subscription/")
    assert resp.status_code == 403, f"Expected 403 Forbidden for non-owner, got {resp.status_code}"
    print("✓ Non-owner (cashier) correctly blocked with 403 Forbidden")
    client.logout()

    # Test Owner access to /subscription/
    client.force_login(owner_user)
    session = client.session
    session["active_tenant_id"] = tenant.id
    session.save()

    resp = client.get("/subscription/")
    assert resp.status_code == 200, f"Expected 200 OK for owner, got {resp.status_code}"
    content = resp.content.decode("utf-8")
    assert plan_basic.name in content, f"Current plan name '{plan_basic.name}' not rendered"
    assert "الفروع المشغلة" in content, "Branches usage metric not found"
    assert "الموظفون المسجلون" in content, "Employees usage metric not found"
    assert "الميزات والأنظمة المضمنة" in content, "Features status section not found"
    assert "باقات الترقية المتاحة" in content, "Available plans section not found"
    print(f"✓ Owner dashboard rendered with plan '{plan_basic.name}' and live quota indicators (200 OK)")

    # 4. TEST UPGRADE REQUEST SUBMISSION BY OWNER
    print("\n--- 3. Testing Upgrade Request Submission Flow ---")
    req_payload = {
        "plan_id": plan_pro.id,
        "billing_cycle": "yearly",
        "notes": "نود الترقية لفتح 3 فروع جديدة في مدينة نصر والتجمع."
    }
    resp = client.post(
        "/api/subscription/request-upgrade/",
        data=json.dumps(req_payload),
        content_type="application/json"
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.content}"
    data = resp.json()
    assert data.get("ok") is True, f"Response did not return ok:True: {data}"
    req_id = data.get("request_id")
    print(f"✓ Owner successfully submitted upgrade request #{req_id} for '{plan_pro.name}'")

    # Verify request created in DB
    upgrade_req = UpgradeRequest.objects.get(id=req_id)
    assert upgrade_req.tenant == tenant
    assert upgrade_req.requested_plan == plan_pro
    assert upgrade_req.status == "pending"
    assert upgrade_req.billing_cycle == "yearly"
    print("✓ Database verified: UpgradeRequest record created with status='pending'")

    # Check that owner sees pending banner on /subscription/
    resp = client.get("/subscription/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert "طلب ترقية باقة قيد المراجعة حالياً" in content, "Pending banner not found on owner subscription page"
    assert f"#{req_id}" in content, "Upgrade request ID not found in history table"
    print("✓ Owner dashboard displays pending upgrade banner and request history")
    client.logout()

    # 5. TEST PLATFORM SUPER ADMIN REVIEWING & APPROVING UPGRADE
    print("\n--- 4. Testing Super Admin Approval Flow ---")
    # Non-admin cannot review
    client.force_login(owner_user)
    resp = client.post(
        f"/api/platform/upgrade-requests/{req_id}/review/",
        data=json.dumps({"action": "approve"}),
        content_type="application/json"
    )
    assert resp.status_code == 403, f"Expected 403 for non-admin review, got {resp.status_code}"
    print("✓ Non-admin cannot approve upgrade requests (403 Forbidden)")
    client.logout()

    # Super Admin logs in
    client.force_login(admin_user)
    resp = client.get("/platform/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert "طلبات ترقية الباقات المقدمة من الملاك" in content, "Upgrade requests table not found on platform dashboard"
    assert tenant.name in content, "Tenant name not found in upgrade requests"
    print("✓ Platform admin dashboard displays pending upgrade request")

    # Approve request
    resp = client.post(
        f"/api/platform/upgrade-requests/{req_id}/review/",
        data=json.dumps({"action": "approve"}),
        content_type="application/json"
    )
    assert resp.status_code == 200, f"Expected 200 on approval, got {resp.status_code}: {resp.content}"
    approval_data = resp.json()
    assert approval_data.get("ok") is True, f"Approval did not return ok:True: {approval_data}"

    # Verify tenant was upgraded
    tenant.refresh_from_db()
    upgrade_req.refresh_from_db()
    assert upgrade_req.status == "approved", f"Expected approved status, got {upgrade_req.status}"
    assert tenant.subscription_plan == plan_pro, f"Expected tenant plan to be '{plan_pro.name}', got '{tenant.subscription_plan.name}'"
    assert tenant.billing_cycle == "yearly"
    assert tenant.subscription_status == "active"
    print(f"✓ UpgradeRequest #{req_id} approved! Tenant '{tenant.name}' successfully upgraded to '{tenant.subscription_plan.name}' (Max branches: {tenant.subscription_plan.max_branches})")

    # 6. TEST REJECTING AN UPGRADE REQUEST
    print("\n--- 5. Testing Upgrade Request Rejection Flow ---")
    client.force_login(owner_user)
    resp = client.post(
        "/api/subscription/request-upgrade/",
        data=json.dumps({"plan_id": plan_basic.id, "billing_cycle": "monthly", "notes": "طلب تخفيض"}),
        content_type="application/json"
    )
    req2_id = resp.json()["request_id"]
    client.logout()

    # Admin rejects
    client.force_login(admin_user)
    resp = client.post(
        f"/api/platform/upgrade-requests/{req2_id}/review/",
        data=json.dumps({"action": "reject"}),
        content_type="application/json"
    )
    assert resp.status_code == 200
    req2 = UpgradeRequest.objects.get(id=req2_id)
    assert req2.status == "rejected"
    tenant.refresh_from_db()
    # Tenant plan stays plan_pro
    assert tenant.subscription_plan == plan_pro
    print(f"✓ UpgradeRequest #{req2_id} rejected cleanly. Tenant remains on '{tenant.subscription_plan.name}'")

    print("\n==================================================")
    print("ALL TESTS PASSED SUCCESSFULLY! 100% VERIFIED.")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
