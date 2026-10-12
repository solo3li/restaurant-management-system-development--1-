import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from core.models import Tenant, SubscriptionPlan, UpgradeRequest, UserProfile
from core import partner_service as ps

def test_voice_partner_quota_integration():
    print("=== STARTING VOICE QUOTA PARTNER API INTEGRATION TESTS ===")

    # 1. Test Plan Quota Tier Resolution
    print("\n--- 1. Testing Plan Quota Tier Calculations ---")
    assert ps.get_plan_voice_caps("trial") == {"minute_cap": 50, "spending_cap": 5.0}
    assert ps.get_plan_voice_caps("starter") == {"minute_cap": 150, "spending_cap": 15.0}
    assert ps.get_plan_voice_caps("basic") == {"minute_cap": 150, "spending_cap": 15.0}
    assert ps.get_plan_voice_caps("standard") == {"minute_cap": 150, "spending_cap": 15.0}
    assert ps.get_plan_voice_caps("growth") == {"minute_cap": 500, "spending_cap": 40.0}
    assert ps.get_plan_voice_caps("pro") == {"minute_cap": 500, "spending_cap": 40.0}
    assert ps.get_plan_voice_caps("premium") == {"minute_cap": 500, "spending_cap": 40.0}
    assert ps.get_plan_voice_caps("enterprise") == {"minute_cap": 1500, "spending_cap": 100.0}
    print("✓ All 8 plan tier quota mappings verified successfully.")

    # 2. Test Live Partner API Client Lookup & Usage
    print("\n--- 2. Testing Live Partner API Usage Lookup ---")
    usage_res = ps.get_client_usage(49)
    assert usage_res.get("status") == "success", f"Usage query failed: {usage_res}"
    client_data = usage_res.get("client", {})
    print(f"✓ Retrieved Client 49 usage: total_minutes={client_data.get('total_minutes')}, "
          f"minute_cap={client_data.get('minute_cap')}, spending_cap={client_data.get('spending_cap')}")
    assert "total_minutes" in client_data
    assert "spending_cap" in client_data

    # 3. Test Live Direct Cap Update
    print("\n--- 3. Testing Direct Cap Update via Partner API ---")
    update_res = ps.update_client_cap(client_id=49, minute_cap=1500, spending_cap=100.0)
    assert update_res.get("status") == "success", f"Cap update failed: {update_res}"
    print(f"✓ Direct cap update succeeded: {update_res.get('message')}")

    # 4. Test Tenant Voice Cap Sync
    print("\n--- 4. Testing Tenant Plan Voice Cap Sync ---")
    tenant = Tenant.objects.get(id=1)
    sync_res = ps.sync_tenant_voice_caps(tenant, reset_to_plan=True)
    assert sync_res.get("status") == "success", f"Sync failed: {sync_res}"
    assert sync_res.get("client", {}).get("minute_cap") == 1500
    assert float(sync_res.get("client", {}).get("spending_cap")) == 100.0
    print(f"✓ Tenant {tenant.name} caps synced with plan tier Enterprise (1500 mins / $100.00).")

    # 5. Test Call Center API Endpoints
    print("\n--- 5. Testing Call Center API Endpoints (/api/ai-callcenter/usage/ & sync-caps/) ---")
    c = Client()
    admin_user = User.objects.filter(is_superuser=True).first()
    c.force_login(admin_user)
    session = c.session
    session["active_tenant_id"] = tenant.id
    session.save()

    # Usage API
    res_usage = c.get("/api/ai-callcenter/usage/")
    assert res_usage.status_code == 200, f"Usage endpoint failed: {res_usage.status_code}"
    usage_json = res_usage.json()
    assert usage_json.get("status") == "success"
    assert usage_json.get("minute_cap") == 1500
    assert "remaining_minutes" in usage_json
    print(f"✓ GET /api/ai-callcenter/usage/ responded 200 OK with remaining_minutes={usage_json.get('remaining_minutes')}.")

    # Sync Caps API
    res_sync = c.post("/api/ai-callcenter/sync-caps/")
    assert res_sync.status_code == 200, f"Sync endpoint failed: {res_sync.status_code}"
    sync_json = res_sync.json()
    assert sync_json.get("status") == "success"
    print("✓ POST /api/ai-callcenter/sync-caps/ responded 200 OK.")

    # 6. Test UpgradeRequest.apply_upgrade hook
    print("\n--- 6. Testing Subscription Upgrade Lifecycle Hook ---")
    pro_plan = SubscriptionPlan.objects.filter(code="pro").first()
    if pro_plan:
        up_req = UpgradeRequest(
            tenant=tenant,
            requested_plan=pro_plan,
            billing_cycle="monthly",
            requested_by=admin_user,
            status="approved"
        )
        up_req.apply_upgrade()
        # Verify that client 49 was synced to Pro tier (500 mins / $40.00)
        pro_usage = ps.get_client_usage(49).get("client", {})
        assert pro_usage.get("minute_cap") == 500, f"Expected 500, got {pro_usage.get('minute_cap')}"
        assert float(pro_usage.get("spending_cap")) == 40.0, f"Expected 40.0, got {pro_usage.get('spending_cap')}"
        print("✓ Upgrade to Pro tier auto-synced quota to 500 mins / $40.00.")

        # Re-upgrade back to Enterprise
        ent_plan = SubscriptionPlan.objects.filter(code="enterprise").first()
        up_req.requested_plan = ent_plan
        up_req.apply_upgrade()
        ent_usage = ps.get_client_usage(49).get("client", {})
        assert ent_usage.get("minute_cap") == 1500
        assert float(ent_usage.get("spending_cap")) == 100.0
        print("✓ Re-upgrade back to Enterprise tier auto-synced quota to 1500 mins / $100.00.")

    print("\n======================================================================")
    print("🎉 ALL PARTNER API VOICE QUOTA TESTS PASSED WITH 100% SUCCESS!")
    print("======================================================================")

if __name__ == "__main__":
    test_voice_partner_quota_integration()
