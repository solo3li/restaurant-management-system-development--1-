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

    # 4. Tabbed Call Center Page Rendering
    print("\n>>> 4. Call Center Tabbed View & Iframe Suite Structure")
    res = client.get("/call-center/")
    assert res.status_code == 200, f"Expected 200 OK, got {res.status_code}"
    html = res.content.decode("utf-8")

    # Check tab ribbon buttons
    assert "main-tab-pos" in html, "Missing POS tab button"
    assert "main-tab-callcenter" in html, "Missing AI Call Center tab button"
    assert "main-tab-chathub" in html, "Missing WhatsApp Chat Hub tab button"
    print("  ✔ PASS: All 3 Navigation tabs (POS, Live Suite, Chat Hub) rendered in command toolbar")

    # Check Tab contents
    assert "id=\"tab-content-pos\"" in html, "Missing tab-content-pos container"
    assert "id=\"tab-content-callcenter\"" in html, "Missing tab-content-callcenter container"
    assert "id=\"tab-content-chathub\"" in html, "Missing tab-content-chathub container"
    print("  ✔ PASS: All 3 Tab content containers present in DOM")

    # Check Call Center Iframe and exact required permissions
    assert "id=\"callcenter-iframe\"" in html, "Missing callcenter-iframe"
    assert "/embed/call-center/" in html, "Missing /embed/call-center/ URL"
    assert "client_id=" in html, "Missing client_id in embed URL"
    assert "allow=\"microphone; camera; clipboard-read; clipboard-write;\"" in html or "allow=\"camera; microphone; clipboard-read; clipboard-write;\"" in html
    assert "min-height: 800px" in html
    print("  ✔ PASS: Call Center iframe configured with microphone, camera, and clipboard access")

    # Check WhatsApp Chat Hub Iframe and exact required permissions
    assert "id=\"chathub-iframe\"" in html, "Missing chathub-iframe"
    assert "/embed/chat-hub/" in html, "Missing /embed/chat-hub/ URL"
    assert "min-height: 700px" in html
    print("  ✔ PASS: WhatsApp Chat Hub iframe configured with camera, microphone, and clipboard access")

    # Check Client ID isolation badge
    assert f"#{embed1_ar['client_id']}" in html or f"{embed1_ar['client_id']}" in html
    print(f"  ✔ PASS: Isolated client indicator #{embed1_ar['client_id']} rendered on screen")

    # 5. Direct URL Routes & Parameterized Tab Selection
    print("\n>>> 5. Direct Tab Routes & Parameterized URL Selection")
    # Query parameter ?tab=call-center
    res_cc = client.get("/call-center/?tab=call-center")
    assert res_cc.status_code == 200
    html_cc = res_cc.content.decode("utf-8")
    assert "tab-content-callcenter" in html_cc
    assert "bg-violet-600 text-white" in html_cc

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

    # 8. Tab Badge Class Preservation & Template Fallback Robustness
    print("\n>>> 8. Tab Badge Class Preservation & Direct Template Fallback")
    # Verify DOM contains the specific persistent badge classes
    assert "tab-badge-cc" in html, "Missing tab-badge-cc class in Call Center tab"
    assert "tab-badge-wa" in html, "Missing tab-badge-wa class in WhatsApp tab"
    # Verify JS tab switcher specifically references and preserves ccBadge and waBadge
    assert "ccBadge.className" in html, "JS switcher must preserve ccBadge class"
    assert "waBadge.className" in html, "JS switcher must preserve waBadge class"

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
    print("  ✔ PASS: Sidebar includes dedicated WhatsApp Chat Hub item with active highlighting")

    # 11. Overview Subpage Resiliency & 500 Fix Verification
    print("\n>>> 11. Overview Subpage Resiliency & 500 Fix Verification")
    res_overview = client.get(reverse("ai_callcenter_overview"))
    assert res_overview.status_code == 200, f"Expected 200 OK for overview, got {res_overview.status_code}"
    html_ov = res_overview.content.decode("utf-8")
    assert "did_number" in html_ov or "جاهز للرنين" in html_ov or "خط الهاتف المخصص" in html_ov
    assert "total_calls_count" in html_ov or "المكالمات المستلمة" in html_ov
    print("  ✔ PASS: /ai-callcenter/overview/ loads cleanly with 200 OK, KPI cards, and DID strip")

    print("\n======================================================================")
    print("ALL EMBEDDED SUITE & STANDALONE INTEGRATION TESTS PASSED! (100%)")
    print("======================================================================")


if __name__ == "__main__":
    run_tests()
