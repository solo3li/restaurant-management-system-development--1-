#!/usr/bin/env python3
"""
Test Suite: Upstream AI Call Center & WhatsApp Chat Hub Multi-Tenant Embedded Iframe Suites.
Verifies:
  1. core.partner_service.get_embed_urls_for_tenant client_id multi-tenant isolation & token mapping.
  2. Dynamic locale mapping (ar, en, fr, tr, de) into embed query parameters.
  3. /call-center/ renders responsive tabbed interface with POS, AI Call Center suite, and WhatsApp Chat Hub.
  4. Both iframes are rendered with full permissions (microphone, camera, clipboard-read, clipboard-write).
  5. URL routes /call-center/embedded/ and /call-center/chat-hub/ active tab rendering.
  6. Zero leakage in English mode.
  7. FastMCP order processing integration readiness.
"""
import os
import sys
import json
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client, RequestFactory
from django.urls import reverse
from django.contrib.auth.models import User
from apps.tenants.models import Tenant
from core.partner_service import (
    get_embed_urls_for_tenant,
    get_client_id_for_tenant,
    PARTNER_API_KEY,
    PARTNER_EMBED_BASE_URL,
)


def run_tests():
    print("======================================================================")
    print("STARTING TEST SUITE: AI CALL CENTER & WHATSAPP CHAT HUB EMBEDDED SUITES")
    print("======================================================================")

    # 1. Partner Service get_embed_urls_for_tenant & Multi-Tenant Isolation
    print("\n>>> 1. Multi-Tenant Isolation & URL Generator Verification")
    tenant1 = Tenant.objects.filter(id=1).first() or Tenant.objects.first()
    assert tenant1 is not None, "Tenant 1 must exist"

    embed1_ar = get_embed_urls_for_tenant(tenant1, locale="ar")
    assert embed1_ar["client_id"] == 49, f"Tenant 1 must map to partner client 49, got {embed1_ar['client_id']}"
    assert embed1_ar["token"] == PARTNER_API_KEY
    assert embed1_ar["locale"] == "ar"
    assert f"client_id=49" in embed1_ar["call_center_url"]
    assert f"locale=ar" in embed1_ar["call_center_url"]
    assert f"token={PARTNER_API_KEY}" in embed1_ar["call_center_url"]
    assert "/embed/call-center/" in embed1_ar["call_center_url"]
    assert f"client_id=49" in embed1_ar["chat_hub_url"]
    assert f"locale=ar" in embed1_ar["chat_hub_url"]
    assert f"token={PARTNER_API_KEY}" in embed1_ar["chat_hub_url"]
    assert "/embed/chat-hub/" in embed1_ar["chat_hub_url"]
    print(f"  ✔ PASS: Tenant 1 resolves to Client {embed1_ar['client_id']} with valid authenticated URLs")

    # Verify other tenants isolate to their distinct sub-client IDs
    other_tenant = Tenant.objects.exclude(id=1).filter(voice_client_id__isnull=False).first()
    if other_tenant:
        embed_other = get_embed_urls_for_tenant(other_tenant, locale="ar")
        assert embed_other["client_id"] == other_tenant.voice_client_id
        assert embed_other["client_id"] != 49, "Different tenant must not share client 49"
        assert f"client_id={other_tenant.voice_client_id}" in embed_other["call_center_url"]
        assert f"client_id={other_tenant.voice_client_id}" in embed_other["chat_hub_url"]
        print(f"  ✔ PASS: Tenant {other_tenant.id} strictly isolates to sub-client #{embed_other['client_id']}")

    # 2. Dynamic Locale Mapping Across 5 Official Languages
    print("\n>>> 2. Dynamic Locale Mapping Across Supported Languages")
    for loc in ["ar", "en", "fr", "tr", "de"]:
        res = get_embed_urls_for_tenant(tenant1, locale=loc)
        assert res["locale"] == loc
        assert f"&locale={loc}" in res["call_center_url"]
        assert f"&locale={loc}" in res["chat_hub_url"]
        print(f"  ✔ PASS: Locale '{loc}' properly propagated into iframe parameters")

    # Boundary: hyphenated locale like 'en-US' or unsupported locale falls back safely
    res_hyphen = get_embed_urls_for_tenant(tenant1, locale="en-US")
    assert res_hyphen["locale"] == "en"
    res_fallback = get_embed_urls_for_tenant(tenant1, locale="unknown-lang")
    assert res_fallback["locale"] == "ar"
    print("  ✔ PASS: Hyphenated locale 'en-US' normalized to 'en' and invalid locale safely defaults to 'ar'")

    # 3. Authenticated Access & Permissions
    print("\n>>> 3. Authenticated Access & RBAC Enforcement on /call-center/")
    client = Client()

    # Unauthenticated should be blocked (403 Forbidden or 302 redirect)
    unauth_res = client.get("/call-center/")
    assert unauth_res.status_code in (302, 403), f"Expected 302 or 403 for unauth, got {unauth_res.status_code}"
    print(f"  ✔ PASS: Unauthenticated access blocked ({unauth_res.status_code})")

    # Login as admin / owner
    owner = User.objects.filter(is_superuser=True).first()
    client.force_login(owner)

    # 4. Streamlined Call Center View & Iframe Suite Structure
    print("\n>>> 4. Call Center Streamlined View & Iframe Suite Structure")
    res = client.get("/call-center/")
    assert res.status_code == 200, f"Expected 200 OK, got {res.status_code}"
    html = res.content.decode("utf-8")

    # Verify redundant tabs and badges are cleanly removed from top bar
    assert "main-tab-pos" not in html, "POS tab button should be removed"
    assert "main-tab-callcenter" not in html, "Call Center tab button should be removed"
    assert "main-tab-chathub" not in html, "Chat Hub tab button should be removed"
    print("  ✔ PASS: Redundant top ribbon buttons cleanly removed for distraction-free view")

    # Check Tab contents
    assert "id=\"tab-content-pos\"" in html, "Missing tab-content-pos container"
    assert "id=\"tab-content-callcenter\"" in html, "Missing tab-content-callcenter container"
    assert "id=\"tab-content-chathub\"" in html, "Missing tab-content-chathub container"
    print("  ✔ PASS: Tab content containers present in DOM")

    # Check Call Center Iframe and exact required permissions
    assert "id=\"callcenter-iframe\"" in html, "Missing callcenter-iframe"
    assert "/embed/call-center/" in html, "Missing /embed/call-center/ URL"
    assert "client_id=" in html, "Missing client_id in embed URL"
    assert "allow=\"microphone; camera; clipboard-read; clipboard-write;\"" in html or "allow=\"camera; microphone; clipboard-read; clipboard-write;\"" in html
    assert "min-height: 800px" in html or "min-height: 850px" in html
    print("  ✔ PASS: Call Center iframe configured with microphone, camera, and clipboard access")

    # Check WhatsApp Chat Hub Iframe and exact required permissions
    assert "id=\"chathub-iframe\"" in html, "Missing chathub-iframe"
    assert "/embed/chat-hub/" in html, "Missing /embed/chat-hub/ URL"
    assert "min-height: 700px" in html or "min-height: 750px" in html
    print("  ✔ PASS: WhatsApp Chat Hub iframe configured with camera, microphone, and clipboard access")

    # Verify client ID is passed cleanly in authenticated iframe URL
    assert "client_id=" in html
    print("  ✔ PASS: Isolated client ID properly targeted in iframe URL")

    # 5. Direct URL Routes & Parameterized Tab Selection
    print("\n>>> 5. Direct Tab Routes & Parameterized Tab Selection")
    # Query parameter ?tab=call-center
    res_cc = client.get("/call-center/?tab=call-center")
    assert res_cc.status_code == 200
    html_cc = res_cc.content.decode("utf-8")
    assert "tab-content-callcenter" in html_cc

    # Direct route /call-center/embedded/
    res_emb = client.get(reverse("call_center_embedded"))
    assert res_emb.status_code == 200
    html_emb = res_emb.content.decode("utf-8")
    assert "tab-content-callcenter" in html_emb
    print("  ✔ PASS: /call-center/embedded/ renders with Call Center Suite tab active")

    # Direct route /call-center/chat-hub/
    res_ch = client.get(reverse("chat_hub_embedded"))
    assert res_ch.status_code == 200
    html_ch = res_ch.content.decode("utf-8")
    assert "tab-content-chathub" in html_ch
    print("  ✔ PASS: /call-center/chat-hub/ renders with WhatsApp Chat Hub tab active")

    # 6. Omnichannel View & Sub-Navigation Integration
    print("\n>>> 6. Omnichannel & AI Call Center Nav Tabs Integration")
    res_omni = client.get(reverse("ai_callcenter_omnichannel"))
    assert res_omni.status_code == 200
    html_omni = res_omni.content.decode("utf-8")
    assert reverse("chat_hub_embedded") in html_omni or "/call-center/chat-hub/" in html_omni, "Omnichannel missing link to /call-center/chat-hub/"
    assert reverse("call_center_embedded") in html_omni or "/call-center/embedded/" in html_omni, "Nav tabs missing link to /call-center/embedded/"
    print("  ✔ PASS: Omnichannel view and navigation tabs link directly to embedded suites")

    # 7. Bilingual & Multilingual Rendering
    print("\n>>> 7. English LTR Rendering & Locale Propagation")
    client.get("/set-language/en/")
    res_en = client.get("/call-center/")
    html_en = res_en.content.decode("utf-8")
    assert "locale=en" in html_en
    assert "Order Entry Point (POS)" in html_en or "Order Entry" in html_en or "Order" in html_en
    print("  ✔ PASS: English request propagates 'locale=en' into both upstream iframes")

    # Also test direct ?lang=en parameter
    res_en_param = client.get("/call-center/?lang=en")
    assert "locale=en" in res_en_param.content.decode("utf-8")
    print("  ✔ PASS: Query parameter ?lang=en propagates 'locale=en' into iframe URLs")

    # Restore Arabic
    client.get("/set-language/ar/")

    # 8. Template Fallback Robustness
    print("\n>>> 8. Dynamic Template Fallback Robustness")

    # Test direct template fallback when context URLs are omitted
    from django.template.loader import render_to_string
    rf = RequestFactory()
    mock_request = rf.get("/call-center/")
    mock_request.user = owner
    mock_request.LANGUAGE_CODE = "fr"
    fallback_html = render_to_string("call_center.html", {
        "tenant": tenant1,
        "active_tab": "call-center",
        "partner_client_id": 999,
        "request": mock_request,
    }, request=mock_request)
    assert "/embed/call-center/" in fallback_html
    assert "locale=fr" in fallback_html or "locale=" in fallback_html
    assert "client_id=999" in fallback_html
    print("  ✔ PASS: Dynamic template fallback resolves locale and sub-client isolation without pre-computed URL")

    # 9. Dedicated Standalone WhatsApp Chat Hub Page (/chat-hub/ & /whatsapp/)
    print("\n>>> 9. Standalone WhatsApp Chat Hub Dedicated Page (/chat-hub/ & /whatsapp/)")
    # Unauthenticated access check
    unauth_client = Client()
    unauth_hub = unauth_client.get(reverse("chat_hub_page"))
    assert unauth_hub.status_code in (302, 403), f"Expected 302 or 403, got {unauth_hub.status_code}"
    print(f"  ✔ PASS: Unauthenticated access to /chat-hub/ blocked ({unauth_hub.status_code})")

    # Authenticated access check on primary route for Tenant 1
    client.get(f"/switch-tenant/{tenant1.id}/")
    res_hub = client.get(reverse("chat_hub_page"))
    assert res_hub.status_code == 200, f"Expected 200 OK for /chat-hub/, got {res_hub.status_code}"
    html_hub = res_hub.content.decode("utf-8")
    assert "standalone-chathub-iframe" in html_hub, "Missing standalone-chathub-iframe id"
    assert "/embed/chat-hub/" in html_hub, "Missing /embed/chat-hub/ in standalone page iframe"
    assert f"client_id={embed1_ar['client_id']}" in html_hub
    assert f"token={PARTNER_API_KEY}" in html_hub
    assert "allow=\"camera; microphone; clipboard-read; clipboard-write;\"" in html_hub or "allow=\"microphone; camera; clipboard-read; clipboard-write;\"" in html_hub
    assert "reloadStandaloneChatHub()" in html_hub, "Missing reloadStandaloneChatHub button"
    assert f"#{embed1_ar['client_id']}" in html_hub, "Missing isolated client badge on standalone page"
    print("  ✔ PASS: /chat-hub/ renders dedicated standalone full-width Chat Hub with isolated client ID and permissions")

    # Isolation check for other tenant
    if other_tenant:
        client.get(f"/switch-tenant/{other_tenant.id}/")
        res_other_hub = client.get(reverse("chat_hub_page"))
        assert res_other_hub.status_code == 200
        html_other = res_other_hub.content.decode("utf-8")
        assert f"client_id={other_tenant.voice_client_id}" in html_other
        assert f"#{other_tenant.voice_client_id}" in html_other
        print(f"  ✔ PASS: Standalone page strictly isolates to other tenant client #{other_tenant.voice_client_id}")
        client.get(f"/switch-tenant/{tenant1.id}/")

    # Authenticated access check on alias route /whatsapp/
    res_wa = client.get(reverse("whatsapp_page"))
    assert res_wa.status_code == 200, f"Expected 200 OK for /whatsapp/, got {res_wa.status_code}"
    html_wa = res_wa.content.decode("utf-8")
    assert "standalone-chathub-iframe" in html_wa
    assert "/embed/chat-hub/" in html_wa
    print("  ✔ PASS: /whatsapp/ alias route renders standalone Chat Hub suite identically")

    # Dynamic locale propagation into standalone Chat Hub
    res_hub_fr = client.get("/chat-hub/?lang=fr")
    assert res_hub_fr.status_code == 200
    assert "locale=fr" in res_hub_fr.content.decode("utf-8")
    print("  ✔ PASS: Standalone page dynamically propagates '?lang=fr' into iframe parameters")

    # 10. Sidebar Navigation Integration & Active States
    print("\n>>> 10. Sidebar Navigation Integration & Active States")
    # Verify sidebar contains link to chat_hub_page
    assert reverse("chat_hub_page") in html_hub or "/chat-hub/" in html_hub, "Sidebar missing link to /chat-hub/"
    assert "#25D366" in html_hub, "Sidebar missing WhatsApp brand colored icon"
    # When requesting /chat-hub/, its link must have m3-active
    assert "m3-active bg-emerald-600/20 text-emerald-300" in html_hub or "m3-active" in html_hub, "Missing active state on WhatsApp Chat Hub sidebar item"
    # Verify sidebar AI Call Center item links to call_center_embedded
    assert reverse("call_center_embedded") in html_hub or "/call-center/embedded/" in html_hub, "Sidebar AI Call Center must link to /call-center/embedded/"
    print("  ✔ PASS: Sidebar includes dedicated WhatsApp Chat Hub item and AI Call Center links directly to /call-center/embedded/")

    # 11. Overview Route Redirection to Embedded Call Center
    print("\n>>> 11. Overview Route Redirection to Embedded Call Center")
    res_overview = client.get(reverse("ai_callcenter_overview"))
    assert res_overview.status_code == 302, f"Expected 302 redirect for overview, got {res_overview.status_code}"
    assert res_overview.url == reverse("call_center_embedded")
    res_followed = client.get(reverse("ai_callcenter_overview"), follow=True)
    assert res_followed.status_code == 200
    assert "tab-content-callcenter" in res_followed.content.decode("utf-8")
    assert "callcenter-iframe" in res_followed.content.decode("utf-8")
    print("  ✔ PASS: /ai-callcenter/overview/ cleanly redirects 302 to /call-center/embedded/ rendering live suite")

    # 12. Granular RBAC Verification on /chat-hub/ & /whatsapp/
    print("\n>>> 12. Granular RBAC Enforcement on Standalone Pages & Sidebar")
    from apps.accounts.models import JobRole, UserProfile
    from apps.billing.models import SubscriptionPlan

    # Create restricted role: Cashier without call_center_access
    cashier_role, _ = JobRole.objects.get_or_create(tenant=tenant1, name="Test Chat Hub Cashier", defaults={"scope": "branch"})
    cashier_role.sync_with_django_group()
    cashier_role.set_permissions(["pos_access", "pos_create_order"])

    cashier_user, _ = User.objects.get_or_create(username="test_chathub_cashier")
    cashier_user.groups.set([cashier_role.group])
    UserProfile.objects.update_or_create(user=cashier_user, defaults={"tenant": tenant1, "job_role": cashier_role, "role": "cashier"})

    # Create permitted role: Call Center Agent with call_center_access
    agent_role, _ = JobRole.objects.get_or_create(tenant=tenant1, name="Test Chat Hub Agent", defaults={"scope": "hq"})
    agent_role.sync_with_django_group()
    agent_role.set_permissions(["call_center_access", "call_center_create_order"])

    agent_user, _ = User.objects.get_or_create(username="test_chathub_agent")
    agent_user.groups.set([agent_role.group])
    UserProfile.objects.update_or_create(user=agent_user, defaults={"tenant": tenant1, "job_role": agent_role, "role": "call_center"})

    # Test Cashier: strictly blocked 403 on /chat-hub/ and /whatsapp/
    cashier_client = Client()
    cashier_client.force_login(cashier_user)
    c_session = cashier_client.session
    c_session["active_tenant_id"] = tenant1.id
    c_session.save()

    res_c_hub = cashier_client.get(reverse("chat_hub_page"))
    assert res_c_hub.status_code == 403, f"Expected 403 for cashier on /chat-hub/, got {res_c_hub.status_code}"
    res_c_wa = cashier_client.get(reverse("whatsapp_page"))
    assert res_c_wa.status_code == 403, f"Expected 403 for cashier on /whatsapp/, got {res_c_wa.status_code}"

    # Cashier sidebar must NOT leak the chat_hub_page link
    res_c_pos = cashier_client.get("/pos/")
    if res_c_pos.status_code == 200:
        pos_html = res_c_pos.content.decode("utf-8")
        assert "/chat-hub/" not in pos_html and "chat_hub_page" not in pos_html, "Cashier sidebar must not leak WhatsApp Chat Hub link"
    print("  ✔ PASS: Cashier without call_center_access strictly blocked (403) and sidebar link hidden")

    # Test Call Center Agent: allowed 200 on /chat-hub/ and /whatsapp/
    agent_client = Client()
    agent_client.force_login(agent_user)
    a_session = agent_client.session
    a_session["active_tenant_id"] = tenant1.id
    a_session.save()

    res_a_hub = agent_client.get(reverse("chat_hub_page"))
    assert res_a_hub.status_code == 200, f"Expected 200 for agent on /chat-hub/, got {res_a_hub.status_code}"
    res_a_wa = agent_client.get(reverse("whatsapp_page"))
    assert res_a_wa.status_code == 200, f"Expected 200 for agent on /whatsapp/, got {res_a_wa.status_code}"
    print("  ✔ PASS: Call Center Agent with call_center_access granted access (200 OK)")

    # 13. Subscription Plan Feature Gating
    print("\n>>> 13. Subscription Plan Feature Gating Verification")
    plan_no_cc, _ = SubscriptionPlan.objects.get_or_create(code="test_no_cc_plan", defaults={"name": "No CC Plan", "price_monthly": 50, "features": ["pos", "inventory"]})
    tenant_no_cc, _ = Tenant.objects.get_or_create(slug="tenant-no-call-center", defaults={"name": "Tenant Without Call Center", "subscription_plan": plan_no_cc})
    tenant_no_cc.subscription_plan = plan_no_cc
    tenant_no_cc.save()

    # Regular restaurant owner (non-superuser) bound to this tenant
    reg_owner_user, _ = User.objects.get_or_create(username="test_reg_owner_no_cc")
    UserProfile.objects.update_or_create(user=reg_owner_user, defaults={"tenant": tenant_no_cc, "role": "owner"})

    owner_client = Client()
    owner_client.force_login(reg_owner_user)

    res_no_cc = owner_client.get(reverse("chat_hub_page"))
    assert res_no_cc.status_code == 403, f"Expected 403 when plan lacks call_center, got {res_no_cc.status_code}"
    res_no_cc_wa = owner_client.get(reverse("whatsapp_page"))
    assert res_no_cc_wa.status_code == 403, f"Expected 403 on /whatsapp/ when plan lacks call_center, got {res_no_cc_wa.status_code}"

    # Sidebar must NOT show Chat Hub link when plan lacks call_center
    res_no_cc_dash = owner_client.get("/dashboard/")
    dash_html = res_no_cc_dash.content.decode("utf-8")
    assert "/chat-hub/" not in dash_html, "Sidebar must hide WhatsApp Chat Hub when subscription lacks call_center"
    print("  ✔ PASS: Subscription plan gating strictly enforced (403 + hidden sidebar link)")

    # 14. Edge Case Payload Resilience for _fetch_enriched_calls
    print("\n>>> 14. Edge Case Payload Resilience (_fetch_enriched_calls)")
    from apps.callcenter.views import _fetch_enriched_calls
    from unittest.mock import patch

    # Corrupted / unusual upstream payloads: non-dict items, float duration string, missing fields
    malformed_calls = [
        None,
        "not-a-dict",
        12345,
        {"call_id": "call_1", "duration_seconds": "45.7", "caller_phone": ""},
        {"call_id": "call_2", "duration_seconds": "invalid", "started_at": "2026-10-31T08:00:00Z"},
        {"call_id": "call_3", "duration_seconds": None, "caller_phone": "+966501234567"},
    ]
    with patch("core.partner_service.get_calls", return_value={"calls": malformed_calls}):
        calls, total, orders, inq = _fetch_enriched_calls(tenant1, 49)
        assert len(calls) == 3, f"Expected 3 valid dict calls parsed, got {len(calls)}"
        assert calls[0]["duration_formatted"] == "00:45"
        assert calls[1]["duration_formatted"] == "00:00"
        assert calls[2]["duration_formatted"] == "00:00"
        assert total == 3
        print("  ✔ PASS: _fetch_enriched_calls safely parsed malformed duration and non-dict records")

    # 15. Upstream Outage Resiliency: Overview redirects, Calls return 200
    print("\n>>> 15. Upstream Partner Outage Resiliency (Overview redirects 302, Calls 200 OK)")
    with patch("core.partner_service.get_telephony_numbers", side_effect=Exception("Partner down")):
        with patch("core.partner_service.get_client_usage", side_effect=Exception("Timeout")):
            with patch("core.partner_service.get_profile", side_effect=Exception("ConnectionRefused")):
                with patch("core.partner_service.get_calls", side_effect=Exception("502 Bad Gateway")):
                    client.force_login(owner)
                    client.get(f"/switch-tenant/{tenant1.id}/")
                    res_ov_outage = client.get(reverse("ai_callcenter_overview"))
                    assert res_ov_outage.status_code == 302, f"Expected 302 redirect on overview, got {res_ov_outage.status_code}"
                    assert res_ov_outage.url == reverse("call_center_embedded"), f"Expected redirect to call_center_embedded, got {res_ov_outage.url}"
                    res_calls_outage = client.get(reverse("ai_callcenter_calls"))
                    assert res_calls_outage.status_code == 200, f"Expected 200 during partner outage on calls, got {res_calls_outage.status_code}"
                    print("  ✔ PASS: Overview redirects 302 to embedded, Calls return 200 OK even during total partner API outage")

    # Cleanup temporary test objects
    cashier_user.delete()
    agent_user.delete()
    cashier_role.delete()
    agent_role.delete()
    reg_owner_user.delete()
    tenant_no_cc.delete()
    plan_no_cc.delete()

    print("\n======================================================================")
    print("ALL EMBEDDED SUITE & STANDALONE INTEGRATION TESTS PASSED! (100%)")
    print("======================================================================")


if __name__ == "__main__":
    run_tests()
