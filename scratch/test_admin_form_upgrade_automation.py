import os
import sys
import django

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.append(r"c:\Users\solo\Downloads\restaurant-management-system-development (1)")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from core.models import Tenant, SubscriptionPlan, UpgradeRequest

def test_admin_form_upgrade_automation():
    print("================================================================")
    print("TEST: DJANGO ADMIN DETAIL FORM UPGRADE AUTOMATION")
    print("================================================================")

    client = Client()
    owner_burger = User.objects.get(username="owner_burger")
    admin_user = User.objects.filter(is_superuser=True).first()
    tenant = Tenant.objects.get(id=2)  # برجر كلاسيك

    # 1. Verify owner_burger's current plan is 'الباقة الاحترافية (Pro)'
    client.force_login(owner_burger)
    resp = client.get("/subscription/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert "الباقة الاحترافية (Pro)" in content, "Current plan 'الباقة الاحترافية (Pro)' not displayed on owner subscription page"
    print(f"✓ Current owner view confirmed: Tenant '{tenant.name}' is on '{tenant.subscription_plan.name}'")
    client.logout()

    # 2. Owner submits an upgrade request to 'باقة الشركات والفرانشايز (Enterprise)'
    plan_enterprise = SubscriptionPlan.objects.get(code="enterprise")
    client.force_login(owner_burger)
    import json
    resp = client.post(
        "/api/subscription/request-upgrade/",
        data=json.dumps({
            "plan_id": plan_enterprise.id,
            "billing_cycle": "yearly",
            "notes": "نريد ترقية لباقة الشركات"
        }),
        content_type="application/json"
    )
    assert resp.status_code == 200
    new_req_id = resp.json()["request_id"]
    print(f"✓ Owner submitted upgrade request #{new_req_id} for '{plan_enterprise.name}'")
    client.logout()

    # 3. Super Admin opens Django Admin change form and changes status to 'approved'
    client.force_login(admin_user)
    get_resp = client.get(f"/admin/core/upgraderequest/{new_req_id}/change/")
    assert get_resp.status_code == 200
    print(f"✓ Super Admin loaded /admin/core/upgraderequest/{new_req_id}/change/ (200 OK)")

    # Simulate admin submitting the change form with status='approved'
    post_data = {
        "tenant": str(tenant.id),
        "requested_plan": str(plan_enterprise.id),
        "billing_cycle": "yearly",
        "requested_by": str(owner_burger.id),
        "notes": "نريد ترقية لباقة الشركات",
        "status": "approved",  # Admin changed dropdown to approved!
        "_save": "حفظ",
    }
    post_resp = client.post(f"/admin/core/upgraderequest/{new_req_id}/change/", data=post_data, follow=True)
    assert post_resp.status_code == 200
    print("✓ Super Admin submitted change form with status='approved'")
    client.logout()

    # 4. Verify in DB that tenant.subscription_plan was automatically updated
    tenant.refresh_from_db()
    req_obj = UpgradeRequest.objects.get(id=new_req_id)
    assert req_obj.status == "approved"
    assert req_obj.reviewed_at is not None
    assert tenant.subscription_plan == plan_enterprise, f"Tenant plan was not upgraded! Got: {tenant.subscription_plan}"
    assert tenant.subscription_status == "active"
    print(f"✓ Database verified: Tenant '{tenant.name}' automatically upgraded to '{tenant.subscription_plan.name}'!")

    # 5. Verify that owner_burger sees the new plan immediately on /subscription/
    client.force_login(owner_burger)
    resp = client.get("/subscription/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert plan_enterprise.name in content, f"Owner subscription page did not display '{plan_enterprise.name}'"
    print(f"✓ Owner view confirmed: /subscription/ now displays '{plan_enterprise.name}' with new quotas!")
    client.logout()

    print("\n================================================================")
    print("AUTOMATED VERIFICATION SUCCEEDED! 100% OPERATIONAL.")
    print("================================================================")

if __name__ == "__main__":
    test_admin_form_upgrade_automation()
