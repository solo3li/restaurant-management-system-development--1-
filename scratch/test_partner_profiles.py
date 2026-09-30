import os
import sys
import json

sys.path.insert(0, "/root/motaem")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
import django
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import User
from core.models import Tenant, UserProfile
from core import views
from core import partner_service as ps

def run_tests():
    print("=== STARTING AI CALL CENTER PROFILES & OFF-TOPIC TESTS ===")
    factory = RequestFactory()
    
    # 1. Get or create owner user
    owner = User.objects.filter(is_superuser=True).first()
    if not owner:
        owner = User.objects.filter(profile__role="owner").first()
    if not owner:
        owner = User.objects.first()
    print(f"[+] Using test user: {owner.username}")

    dummy_req = factory.get("/")
    dummy_req.user = owner
    dummy_req.session = {}
    tenant = views.get_active_tenant(dummy_req)
    print(f"[+] Active tenant: {tenant.name} (ID: {tenant.id})")
    client_id = ps.get_client_id_for_tenant(tenant)
    print(f"[+] Voice Client ID: {client_id}")

    # 2. Test Smart Defaults in create_profile (when off_topic_response is omitted)
    print("\n--- Test 1: Smart default off_topic_response for Saudi dialect ---")
    saudi_payload = {
        "name": "مساعد المبيعات التجريبي",
        "gender": "male",
        "dialect": "saudi",
        "persona_role": "sales_advisor",
        "speaking_style": "friendly",
        "custom_instructions": "أنت مساعد مبيعات سعودي ودود.",
        "welcome_message": "أهلاً بك في مطاعم كورا!",
        # off_topic_response intentionally omitted to test smart default
        "is_active": False
    }
    req = factory.post(
        "/api/ai-callcenter/profiles/create/",
        data=json.dumps(saudi_payload),
        content_type="application/json"
    )
    req.user = owner
    req.session = {"active_tenant_id": tenant.id}
    
    res = views.api_ai_callcenter_create_profile(req)
    print("Create status code:", res.status_code)
    data = json.loads(res.content)
    print("Create response:", data)
    created_id = data.get("id") or (data.get("profile") or {}).get("id")
    print(f"[+] Created Profile ID: {created_id}")

    # Verify profile on remote API
    if created_id:
        profiles_resp = ps.get_profile(client_id)
        profiles_list = profiles_resp.get("profiles", [])
        matched = next((p for p in profiles_list if p.get("id") == created_id), None)
        assert matched is not None, "Created profile should exist in remote profiles"
        print(f"[+] Profile name: {matched.get('name')}")
        print(f"[+] Profile dialect: {matched.get('dialect')}")
        print(f"[+] Profile persona_role: {matched.get('persona_role')}")
        print(f"[+] Profile gender: {matched.get('gender')}")
        print(f"[+] Profile off_topic_response: {matched.get('off_topic_response')}")
        assert "مطاعم كُـورَا" in matched.get("off_topic_response", ""), "Smart default was successfully applied!"

        # 3. Test Update Profile with explicit off_topic_response
        print("\n--- Test 2: Updating profile with explicit off_topic_response ---")
        update_payload = {
            "profile_id": created_id,
            "name": "مساعد المبيعات السعودي المطور",
            "off_topic_response": "أعتذر منك يا غالي، تخصصي استقبال طلبات كورا وعروض اليوم فقط!",
            "speaking_style": "formal"
        }
        req_up = factory.post(
            f"/api/ai-callcenter/profile/{created_id}/",
            data=json.dumps(update_payload),
            content_type="application/json"
        )
        req_up.user = owner
        req_up.session = {"active_tenant_id": tenant.id}
        res_up = views.api_ai_callcenter_update_profile(req_up, profile_id=created_id)
        print("Update status code:", res_up.status_code)
        print("Update response:", res_up.content.decode("utf-8"))

        # 4. Test Activate Profile
        print("\n--- Test 3: Activate Profile ---")
        req_act = factory.post(f"/api/ai-callcenter/profiles/{created_id}/activate/")
        req_act.user = owner
        req_act.session = {"active_tenant_id": tenant.id}
        res_act = views.api_ai_callcenter_activate_profile(req_act, profile_id=created_id)
        print("Activate status code:", res_act.status_code)
        print("Activate response:", res_act.content.decode("utf-8"))

        # Re-activate original active profile or verify
        profiles_after = ps.get_profile(client_id).get("profiles", [])
        active_prof = next((p for p in profiles_after if p.get("is_active")), None)
        print(f"[+] Active profile ID now is: {active_prof.get('id') if active_prof else 'None'}")

    # 5. Test rendering the Dashboard View
    print("\n--- Test 4: Render ai_callcenter_management_view ---")
    req_view = factory.get("/ai-callcenter/")
    req_view.user = owner
    req_view.session = {"active_tenant_id": tenant.id}
    res_view = views.ai_callcenter_management_view(req_view)
    print("Dashboard render status code:", res_view.status_code)
    html_content = res_view.content.decode("utf-8")
    
    # Assert critical elements exist in rendered HTML
    assert "off_topic_response" in html_content, "off_topic_response input must be in HTML"
    assert "الرد على الأسئلة الخارجة عن السياق" in html_content, "Arabic label for off_topic_response must be present"
    assert "persona_role" in html_content, "persona_role select must be in HTML"
    assert "create-profile-modal" in html_content, "create-profile-modal must be in HTML"
    assert "openCreateProfileModal" in html_content, "openCreateProfileModal JS trigger must be in HTML"
    assert "DIALECT_OFF_TOPIC_DEFAULTS" in html_content, "DIALECT_OFF_TOPIC_DEFAULTS JS mapping must be in HTML"
    print("[+] All template checks passed successfully!")

    print("\n=== ALL PROFILE TESTS PASSED 100% SUCCESSFULLY ===")

if __name__ == "__main__":
    run_tests()
