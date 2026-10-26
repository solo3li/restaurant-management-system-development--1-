#!/usr/bin/env python3
"""
Test suite for AI Call Center Omnichannel & Central Telephony Partner integration.
"""
import os
import sys
import json
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
import django
django.setup()

from django.test import Client
from django.urls import reverse
from django.contrib.auth.models import User
from core.models import Tenant, UserProfile, Employee, JobRole

def run_tests():
    print(">>> Starting AI Call Center Omnichannel & Telephony Tests...")
    client = Client()

    # 1. Test unauthenticated access
    res = client.get(reverse("ai_callcenter_omnichannel"))
    assert res.status_code in (302, 403), f"Expected 302 or 403, got {res.status_code}"
    print("  ✔ PASS: Unauthenticated access blocked on /ai-callcenter/omnichannel/")

    unauth_post = client.post(reverse("api_ai_callcenter_create_pbx_trunk"), data="{}", content_type="application/json")
    assert unauth_post.status_code == 302, f"Expected 302 redirect for unauthenticated POST, got {unauth_post.status_code}"
    print("  ✔ PASS: Unauthenticated POST blocked on create-pbx-trunk")

    # 2. Get test tenant and superuser / owner
    tenant = Tenant.objects.filter(slug="diyafa").first() or Tenant.objects.first()
    assert tenant is not None, "Tenant must exist"
    
    owner = User.objects.filter(is_superuser=True).first()
    if not owner:
        owner = User.objects.filter(userprofile__tenant=tenant).first()
    assert owner is not None, "Owner user must exist"

    # Log in as owner
    client.force_login(owner)

    # 3. Test Omnichannel page renders with 200 OK and contains WhatsApp + SIP Trunk features
    res = client.get(reverse("ai_callcenter_omnichannel"))
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    content = res.content.decode("utf-8")
    assert "ربط خط هاتفي / SIP Trunk" in content, "Missing SIP Trunk button"
    assert "connect-trunk-modal" in content, "Missing connect-trunk-modal"
    assert "issabel-config-modal" in content, "Missing issabel-config-modal"
    assert "issabel-trunk-name-code" in content, "Missing Trunk Name box in Issabel modal"
    assert "issabel-register-container" in content, "Missing Register String container in Issabel modal"
    assert "assign-did-modal" in content, "Missing assign-did-modal"
    # Verify WhatsApp SVG is present (brand color #25D366 or official path)
    assert "#25D366" in content, "Missing WhatsApp brand color #25D366"
    assert "M17.472 14.382" in content, "Missing WhatsApp SVG path"

    # Verify zero unwanted raw emojis in omnichannel template
    import re
    emoji_pattern = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]|[✕✓✅❌🤖👤📢🔒⚠️🎤📘🔍👁️💳📄⬇️🔄▶⏸💬📱📞]")
    raw_emoji_matches = emoji_pattern.findall(content)
    assert len(raw_emoji_matches) == 0, f"Found unwanted raw emojis in rendered page: {raw_emoji_matches[:10]}"
    print("  ✔ PASS: Omnichannel page renders 200 with WhatsApp SVG & SIP Trunk modals (0 raw emojis)")

    # 4. Test Telephony Info API
    with patch("core.partner_service.get_telephony_trunks") as mock_get_trunks, \
         patch("core.partner_service.get_telephony_numbers") as mock_get_numbers, \
         patch("core.partner_service.get_pbx_trunks") as mock_get_pbx:
        
        mock_get_trunks.return_value = {
            "outbound_trunks": [{"trunk_id": "test-sip-1", "name": "Direct SIP Test"}],
            "inbound_trunks": [],
            "status": "ok"
        }
        mock_get_pbx.return_value = {
            "trunks": [{"id": 1, "name": "Issabel PBX Test"}],
            "status": "success"
        }
        mock_get_numbers.return_value = [{"phone_number": "+966110001111"}]

        url = reverse("api_ai_callcenter_telephony_info")
        res = client.get(url)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = res.json()
        assert data.get("status") == "success"
        assert len(data.get("numbers", [])) == 1
        assert len(data.get("pbx_trunks", [])) == 1
        print("  ✔ PASS: Telephony Info API returns phone numbers, PBX trunks, and SIP trunks")

    # 5. Test Create PBX Trunk API with validation & mocking
    with patch("core.partner_service.create_pbx_trunk") as mock_create_pbx:
        mock_create_pbx.return_value = {
            "status": "success",
            "trunk": {
                "id": 101,
                "name": "Issabel Branch 1",
                "issabel_config": {
                    "peer_details": "host=livekit.example.com\ntype=peer",
                    "user_details": "context=from-trunk\ntype=user"
                }
            }
        }
        payload = {
            "name": "Issabel Branch 1",
            "auth_mode": "ip",
            "pbx_ip": "192.168.1.100",
            "outbound_port": 5060,
            "outbound_transport": "UDP"
        }
        url = reverse("api_ai_callcenter_create_pbx_trunk")
        res = client.post(url, data=json.dumps(payload), content_type="application/json")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = res.json()
        assert data.get("status") == "success"
        assert "issabel_config" in data
        assert "peer_details" in data["issabel_config"]
        print("  ✔ PASS: Create PBX Trunk creates trunk & returns Issabel Asterisk config")

    # 6. Test Delete PBX Trunk API
    with patch("core.partner_service.delete_pbx_trunk") as mock_del_pbx:
        mock_del_pbx.return_value = {"status": "success", "message": "deleted"}
        url = reverse("api_ai_callcenter_delete_pbx_trunk", kwargs={"trunk_id": 101})
        res = client.post(url, data=json.dumps({}), content_type="application/json")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = res.json()
        assert data.get("status") == "success"
        print("  ✔ PASS: Delete PBX Trunk deletes trunk successfully")

    # 7. Test Create Direct SIP Trunk API
    with patch("core.partner_service.register_sip_trunk") as mock_create_sip:
        mock_create_sip.return_value = {
            "status": "success",
            "trunk": {
                "id": 202,
                "name": "Direct SIP Outbound"
            }
        }
        payload = {
            "name": "Direct SIP Outbound",
            "host": "sip.provider.com",
            "port": 5060,
            "username": "sipuser",
            "secret": "sippass"
        }
        url = reverse("api_ai_callcenter_create_sip_trunk")
        res = client.post(url, data=json.dumps(payload), content_type="application/json")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = res.json()
        assert data.get("status") == "success"
        print("  ✔ PASS: Create Direct SIP Trunk registers SIP trunk successfully")

    # 8. Test Delete Generic Telephony Trunk API
    with patch("core.partner_service.delete_telephony_trunk") as mock_del_sip:
        mock_del_sip.return_value = {"status": "success", "message": "SIP trunk deleted"}
        url = reverse("api_ai_callcenter_delete_telephony_trunk", kwargs={"trunk_type": "outbound", "trunk_id": 202})
        res = client.post(url, data=json.dumps({}), content_type="application/json")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = res.json()
        assert data.get("status") == "success"
        print("  ✔ PASS: Delete Telephony Trunk deletes SIP trunk successfully")

    # 9. Test Assign DID API
    with patch("core.partner_service.assign_did_number") as mock_assign_did:
        mock_assign_did.return_value = {"status": "success", "message": "DID assigned"}
        payload = {
            "phone_number": "+966110001111",
            "pbx_trunk_id": 101,
            "description": "DID mapping"
        }
        url = reverse("api_ai_callcenter_assign_did")
        res = client.post(url, data=json.dumps(payload), content_type="application/json")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = res.json()
        assert data.get("status") == "success"
        print("  ✔ PASS: Assign DID maps phone number to PBX trunk successfully")

    # 10. Test RBAC security: regular waiter employee without callcenter admin permission is denied
    waiter_user, _ = User.objects.get_or_create(username="test_waiter_telephony", defaults={"email": "waiter@test.com"})
    waiter_user.is_superuser = False
    waiter_user.save()
    UserProfile.objects.update_or_create(user=waiter_user, defaults={"tenant": tenant, "role": "employee"})
    client.force_login(waiter_user)

    rbac_res = client.post(
        reverse("api_ai_callcenter_create_pbx_trunk"),
        data=json.dumps({"name": "Unauthorized PBX"}),
        content_type="application/json"
    )
    assert rbac_res.status_code == 403, f"Expected 403 Forbidden for non-admin, got {rbac_res.status_code}"
    print("  ✔ PASS: RBAC enforces 403 Forbidden on telephony management for unauthorized employee")

    print("\n===========================================================================")
    print("ALL AI CALL CENTER OMNICHANNEL & TELEPHONY TESTS PASSED SUCCESSFULLY! 100%")
    print("===========================================================================")

if __name__ == "__main__":
    run_tests()
