"""
Comprehensive Automated Test Suite for Platform Voice Assistant 6-Tab Admin Interface
(PlatformVoiceAssistantConfigAdmin & Landing Assistant Services)

Covers:
1. Super Admin Permissions & 6-Tab Horizontal Ribbon Rendering in Slate Theme
2. Identity, Telephony, and Quotas Form Updating & Partner Client Linking (Landing-Sales-Client)
3. Tab 4: Isolated Knowledge Base Full CRUD (Upload, Add FAQ, Edit, Delete with Partner Sync)
4. Tab 5: Landing Leads CRM, One-Click WhatsApp Links, and Instant Status Updates
5. Tab 6: Redis Live Context Monitoring, Live JSON Compilation, and Instant Sync
"""

import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.callcenter.models import (
    PlatformVoiceAssistantConfig,
    LandingKnowledgeDocument,
    LandingVoiceLead,
)
from apps.billing.models import SubscriptionPlan
from apps.callcenter.landing_assistant_service import (
    ensure_landing_sales_client,
    sync_landing_assistant_live_context,
    push_live_context,
    clear_landing_assistant_live_context,
    get_landing_assistant_redis_status,
    sync_knowledge_doc_to_partner,
    build_landing_assistant_live_context,
    REDIS_LIVE_CONTEXT_KEY,
)


class PlatformVoiceAssistantAdminTabsTestSuite(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

        # 1. Clear & Initialize Platform Voice Assistant Config
        PlatformVoiceAssistantConfig.objects.all().delete()
        self.config = PlatformVoiceAssistantConfig.get_config()
        self.config.is_active = True
        self.config.assistant_name = "مستشار مبيعات كُـورَا الذكي"
        self.config.system_prompt = "أنت مستشار مبيعات خبير لمنظومة كُـورَا."
        self.config.welcome_message = "أهلاً بك في منصة كُـورَا! كيف أساعدك اليوم؟"
        self.config.voice_name = "Puck"
        self.config.language = "ar"
        self.config.accent = "saudi"
        self.config.max_call_duration_seconds = 180
        self.config.max_daily_calls_per_ip = 3
        self.config.partner_client_id = "662"
        self.config.save()
        clear_landing_assistant_live_context(self.config)

        # 2. Superadmin User
        self.admin_user = User.objects.create_superuser(
            username="test_superadmin",
            email="superadmin@kura.local",
            password="adminpassword123",
        )

        # 3. Regular Staff & Non-Staff Users for RBAC testing
        self.regular_user = User.objects.create_user(
            username="regular_visitor",
            email="visitor@kura.local",
            password="userpassword123",
        )

        # 4. Subscription Plan for Live Context Compilation
        SubscriptionPlan.objects.get_or_create(
            code="growth",
            defaults={
                "name": "باقة النمو المتقدمة",
                "description": "مثالية للمطاعم المتوسطة وسلاسل الفروع",
                "price_monthly": 199.00,
                "price_yearly": 1990.00,
                "max_branches": 5,
                "max_employees": 20,
                "features": ["pos", "kds", "call_center", "inventory"],
                "is_active": True,
            }
        )

    def tearDown(self):
        clear_landing_assistant_live_context(self.config)
        cache.clear()

    # =========================================================================
    # SUITE 1: Super Admin Permissions and 6-Tab Rendering in Slate Theme
    # =========================================================================

    def test_01_unauthenticated_and_non_superadmin_access(self):
        """Test non-authenticated and non-superadmin access controls."""
        # Unauthenticated access to admin change form redirected to login
        resp = self.client.get(f"/admin/core/platformvoiceassistantconfig/{self.config.pk}/change/")
        self.assertEqual(resp.status_code, 302)

        # Unauthenticated access to APIs returns 302 or 403
        resp = self.client.get("/api/landing-assistant/documents/")
        self.assertEqual(resp.status_code, 302)

        # Non-staff authenticated user blocked with 403 Forbidden from APIs
        self.client.force_login(self.regular_user)
        resp = self.client.get("/api/landing-assistant/documents/")
        self.assertEqual(resp.status_code, 403)

        resp = self.client.post("/api/landing-assistant/redis/sync/")
        self.assertEqual(resp.status_code, 403)

        resp = self.client.post("/api/landing-assistant/partner-client/ensure/")
        self.assertEqual(resp.status_code, 403)

    def test_02_superadmin_renders_all_6_tabs_in_slate_theme(self):
        """Verify that Super Admin can access change view and all 6 tabs are rendered."""
        self.client.force_login(self.admin_user)
        resp = self.client.get(f"/admin/core/platformvoiceassistantconfig/{self.config.pk}/change/")
        self.assertEqual(resp.status_code, 200)

        html = resp.content.decode("utf-8")

        # 6 Tab Labels
        expected_tabs = [
            "1. هوية المساعد والشخصية",
            "2. إعدادات الصوت والاتصال",
            "3. حدود الاستهلاك وحماية التكاليف",
            "4. قاعدة المعرفة المعزولة",
            "5. سجل المكالمات والعملاء المحتملين",
            "6. الذاكرة المنظمة الحية (Redis)",
        ]
        for tab_name in expected_tabs:
            self.assertIn(tab_name, html, f"Tab '{tab_name}' not found in rendered admin HTML")

        # Tab pane IDs
        self.assertIn('id="tab-identity"', html)
        self.assertIn('id="tab-telephony"', html)
        self.assertIn('id="tab-quotas"', html)
        self.assertIn('id="tab-knowledge"', html)
        self.assertIn('id="tab-leads"', html)
        self.assertIn('id="tab-redis"', html)

        # Unified Slate theme styling anchors
        self.assertIn(".landing-tabs-bar", html)
        self.assertIn(".landing-tab-btn", html)
        self.assertIn("#272b30", html)
        self.assertIn("#32383e", html)

    # =========================================================================
    # SUITE 2: Tab 1, 2, 3 Form Updating & Partner Client Linking
    # =========================================================================

    def test_03_admin_form_post_saves_identity_telephony_quotas(self):
        """Verify standard Django admin form submission saves Tabs 1, 2, 3 data."""
        self.client.force_login(self.admin_user)

        post_data = {
            "is_active": "on",
            "assistant_name": "مستشار مبيعات كُـورَا المحدّث",
            "system_prompt": "توجيهات جديدة محدثة بالكامل لمبيعات المنصة.",
            "welcome_message": "مرحباً بكم في منصة كُـورَا! كيف نقدر نساعدكم اليوم؟",
            "partner_client_id": "662",
            "voice_name": "Charon",
            "language": "ar",
            "accent": "gulf",
            "max_call_duration_seconds": 240,
            "max_daily_calls_per_ip": 5,
            "_save": "حفظ",
        }
        resp = self.client.post(
            f"/admin/core/platformvoiceassistantconfig/{self.config.pk}/change/",
            data=post_data,
        )
        self.assertEqual(resp.status_code, 302)

        self.config.refresh_from_db()
        self.assertEqual(self.config.assistant_name, "مستشار مبيعات كُـورَا المحدّث")
        self.assertEqual(self.config.voice_name, "Charon")
        self.assertEqual(self.config.accent, "gulf")
        self.assertEqual(self.config.max_call_duration_seconds, 240)
        self.assertEqual(self.config.max_daily_calls_per_ip, 5)

    @patch("core.partner_service._request")
    def test_04_ensure_landing_sales_client_linking(self, mock_partner_req):
        """Test ensuring isolated Landing-Sales-Client is linked or registered."""
        # Scenario A: Existing client found on partner platform
        mock_partner_req.return_value = {
            "status": "success",
            "clients": [
                {
                    "client_id": 789,
                    "name": "Landing-Sales-Client",
                    "external_reference": "landing-sales-client",
                }
            ],
        }
        res = ensure_landing_sales_client(self.config)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["client_id"], "789")
        self.config.refresh_from_db()
        self.assertEqual(self.config.partner_client_id, "789")

        # Scenario B: Calling API endpoint as superadmin (POST allowed, GET rejected with 405)
        self.client.force_login(self.admin_user)
        get_resp = self.client.get("/api/landing-assistant/partner-client/ensure/")
        self.assertEqual(get_resp.status_code, 405)

        api_resp = self.client.post("/api/landing-assistant/partner-client/ensure/")
        self.assertEqual(api_resp.status_code, 200)
        self.assertEqual(api_resp.json()["status"], "success")

    # =========================================================================
    # SUITE 3: Tab 4 Isolated Knowledge Base Full CRUD with Partner Sync
    # =========================================================================

    @patch("core.partner_service.add_document")
    @patch("core.partner_service.delete_document")
    def test_05_knowledge_documents_full_crud(self, mock_del_doc, mock_add_doc):
        """Test full CRUD operations on LandingKnowledgeDocument with Partner Service sync."""
        mock_add_doc.return_value = {"status": "success", "document_id": 991}
        mock_del_doc.return_value = {"status": "success"}

        self.client.force_login(self.admin_user)

        # 1. Add FAQ
        faq_payload = {
            "title": "ما هي مزايا شاشات المطبخ KDS في كُـورَا؟",
            "content": "تنظيم إعداد الوجبات فورياً ومتابعة زمن الطهي وربط مباشر مع الكاشير وتطبيقات التوصيل.",
        }
        resp = self.client.post(
            "/api/landing-assistant/documents/add-faq/",
            data=json.dumps(faq_payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        faq_data = resp.json()
        self.assertEqual(faq_data["status"], "success")
        doc_id = faq_data["document"]["id"]

        doc = LandingKnowledgeDocument.objects.get(pk=doc_id)
        self.assertEqual(doc.source_type, "faq")
        self.assertEqual(doc.partner_doc_id, 991)
        self.assertIn("شاشات المطبخ", str(doc))

        # 2. Upload Document File (.txt)
        txt_content = b"KURA Restaurant OS Enterprise Sales Manual 2026."
        uploaded_file = SimpleUploadedFile("sales_manual.txt", txt_content, content_type="text/plain")

        resp = self.client.post(
            "/api/landing-assistant/documents/upload/",
            {"file": uploaded_file, "title": "كتيب مبيعات المنصة السنوي"},
        )
        self.assertEqual(resp.status_code, 200)
        file_doc_id = resp.json()["document"]["id"]

        file_doc = LandingKnowledgeDocument.objects.get(pk=file_doc_id)
        self.assertEqual(file_doc.source_type, "file")
        self.assertEqual(file_doc.file_type, "txt")
        self.assertGreater(file_doc.file_size, 0)

        # 3. List Documents
        resp = self.client.get("/api/landing-assistant/documents/")
        self.assertEqual(resp.status_code, 200)
        docs = resp.json()["documents"]
        self.assertEqual(len(docs), 2)

        # 4. Edit FAQ
        edit_payload = {
            "title": "ما هي مزايا شاشات المطبخ KDS الذكية المعتمدة؟",
            "content": "محتوى معدل ومطور لشاشات المطبخ.",
        }
        resp = self.client.post(
            f"/api/landing-assistant/documents/{doc_id}/edit/",
            data=json.dumps(edit_payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.title, "ما هي مزايا شاشات المطبخ KDS الذكية المعتمدة؟")
        self.assertEqual(doc.content, "محتوى معدل ومطور لشاشات المطبخ.")

        # 5. Delete Document with Partner Sync
        resp = self.client.post(f"/api/landing-assistant/documents/{doc_id}/delete/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(LandingKnowledgeDocument.objects.filter(pk=doc_id).exists())
        mock_del_doc.assert_called_with(client_id=662, doc_id=991)

    @patch("core.partner_service.add_document")
    def test_06_knowledge_document_validation(self, mock_add_doc):
        """Test boundary cases and validations on knowledge documents."""
        mock_add_doc.return_value = {"status": "success", "document_id": 992}
        self.client.force_login(self.admin_user)

        # Missing title or content in FAQ
        resp = self.client.post(
            "/api/landing-assistant/documents/add-faq/",
            data=json.dumps({"title": "", "content": ""}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

        # Upload without file
        resp = self.client.post("/api/landing-assistant/documents/upload/", {})
        self.assertEqual(resp.status_code, 400)

        # Edit non-existent document
        resp = self.client.post(
            "/api/landing-assistant/documents/999999/edit/",
            data=json.dumps({"title": "Test"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

        # Edit with empty title rejected
        faq = LandingKnowledgeDocument.objects.create(
            config=self.config,
            title="سؤال تجريبي",
            content="إجابة تجريبية",
            source_type="faq"
        )
        resp = self.client.post(
            f"/api/landing-assistant/documents/{faq.id}/edit/",
            data=json.dumps({"title": ""}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

        # Unsupported file extension rejected (.exe)
        bad_file = SimpleUploadedFile("malicious.exe", b"binary content", content_type="application/octet-stream")
        resp = self.client.post(
            "/api/landing-assistant/documents/upload/",
            {"file": bad_file, "title": "ملف تنفيذي غير مدعوم"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("غير مدعوم", resp.json()["message"])

        # File with null bytes handled safely without DB crash
        txt_with_null = SimpleUploadedFile("null_test.txt", b"Safe text\x00with null\x00bytes", content_type="text/plain")
        resp = self.client.post(
            "/api/landing-assistant/documents/upload/",
            {"file": txt_with_null, "title": "مستند يحتوي على رموز صفرية"},
        )
        self.assertEqual(resp.status_code, 200)
        created_doc = LandingKnowledgeDocument.objects.get(pk=resp.json()["document"]["id"])
        self.assertNotIn("\x00", created_doc.content)

        # Delete non-existent document
        resp = self.client.post("/api/landing-assistant/documents/999999/delete/")
        self.assertEqual(resp.status_code, 404)

    # =========================================================================
    # SUITE 4: Tab 5 Landing Leads & Calls Management
    # =========================================================================

    def test_07_landing_leads_crm_and_status_update(self):
        """Test embedded LandingVoiceLead table data and instant status updates."""
        lead = LandingVoiceLead.objects.create(
            name="عبدالله الشهري",
            phone="0559876543",
            country_code="+966",
            call_status="connected",
            duration_seconds=125,
            lead_status="new",
        )
        self.assertEqual(lead.full_phone, "+966559876543")
        self.assertEqual(lead.whatsapp_url, "https://wa.me/966559876543")
        self.assertEqual(lead.formatted_duration(), "02:05")

        self.client.force_login(self.admin_user)

        # 1. Update status to 'interested'
        resp = self.client.post(
            f"/api/landing-assistant/leads/{lead.id}/status/",
            data=json.dumps({"lead_status": "interested"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["lead_status"], "interested")
        lead.refresh_from_db()
        self.assertEqual(lead.lead_status, "interested")

        # 2. Update status to 'converted'
        resp = self.client.post(
            f"/api/landing-assistant/leads/{lead.id}/status/",
            data=json.dumps({"lead_status": "converted", "notes": "تم توقيع العقد السنوي"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.lead_status, "converted")
        self.assertEqual(lead.notes, "تم توقيع العقد السنوي")

        # 3. Invalid status rejected
        resp = self.client.post(
            f"/api/landing-assistant/leads/{lead.id}/status/",
            data=json.dumps({"lead_status": "invalid_status_xyz"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

        # 4. Non-existent lead returns 404
        resp = self.client.post(
            "/api/landing-assistant/leads/999999/status/",
            data=json.dumps({"lead_status": "converted"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

        # 5. Verify completed calls are included in connected_voice_calls KPI
        lead_completed = LandingVoiceLead.objects.create(
            name="سعد الدوسري",
            phone="0501234567",
            country_code="+966",
            call_status="completed",
            duration_seconds=90,
            lead_status="new",
        )
        ctx = build_landing_assistant_live_context(self.config)
        self.assertEqual(ctx["system_kpis"]["connected_voice_calls"], 2)  # 1 connected + 1 completed

    # =========================================================================
    # SUITE 5: Tab 6 Redis Live Context Monitoring & Instant Sync
    # =========================================================================

    @patch("core.partner_service.update_client_live_context")
    def test_08_redis_live_context_status_and_sync(self, mock_update_partner_ctx):
        """Test inspecting and syncing Redis live context payload for Landing Assistant."""
        mock_update_partner_ctx.return_value = {"status": "success"}

        # 1. Build context dictionary directly
        ctx = build_landing_assistant_live_context(self.config)
        self.assertIn("assistant", ctx)
        self.assertEqual(ctx["assistant"]["name"], self.config.assistant_name)
        self.assertIn("subscription_plans", ctx)
        self.assertIn("system_kpis", ctx)

        self.client.force_login(self.admin_user)

        # 2. Fetch Redis status via API
        resp = self.client.get("/api/landing-assistant/redis/status/")
        self.assertEqual(resp.status_code, 200)
        status_data = resp.json()
        self.assertEqual(status_data["status"], "success")
        self.assertIn("size_formatted", status_data)
        self.assertIn("keys_count", status_data)
        self.assertIn("context", status_data)

        # 3. Trigger immediate sync via API
        resp = self.client.post("/api/landing-assistant/redis/sync/")
        self.assertEqual(resp.status_code, 200)
        sync_res = resp.json()
        self.assertEqual(sync_res["status"], "success")
        self.assertIn("synced_at", sync_res)
        self.assertGreater(sync_res["size_bytes"], 0)

        # Verify Partner service context update was called
        mock_update_partner_ctx.assert_called()

        # Verify Redis / Cache value contains live payload
        cached_val = cache.get(REDIS_LIVE_CONTEXT_KEY)
        self.assertIsNotNone(cached_val)
        parsed = json.loads(cached_val)
        self.assertEqual(parsed["assistant"]["name"], self.config.assistant_name)

    # =========================================================================
    # SUITE 6: Tab 6 Free Manual Live Memory (Edit, Sync, Clear & Clean Default)
    # =========================================================================

    def test_09_manual_redis_live_context_edit_sync_and_clear(self):
        """Test free manual editing, instant Redis sync, and full memory clearing."""
        self.client.force_login(self.admin_user)

        # 1. Initially memory should be clean & white without forced static injection
        clear_landing_assistant_live_context(self.config)
        self.config.refresh_from_db()

        status_data = get_landing_assistant_redis_status(self.config)
        self.assertEqual(status_data["size_bytes"], 0)
        self.assertEqual(status_data["raw_json"], "")
        self.assertNotIn("منظومة كُـورَا", status_data["raw_json"])

        # 2. Superadmin manually saves & syncs custom live context
        custom_payload = {
            "restaurant_os_guide": "تعليمات مخصصة لصفحة الهبوط تم تحريرها يدوياً بالكامل",
            "features": ["نظام الكاشير السريع", "الربط مع الطابعات"],
            "working_hours": "24/7"
        }
        custom_json_str = json.dumps(custom_payload, ensure_ascii=False)

        resp = self.client.post(
            "/api/landing-assistant/redis/sync/",
            data=json.dumps({"custom_live_context": custom_json_str}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        res_json = resp.json()
        self.assertEqual(res_json["status"], "success")
        self.assertGreater(res_json["size_bytes"], 0)

        # Verify saved in Model
        self.config.refresh_from_db()
        self.assertEqual(self.config.custom_live_context, custom_json_str)

        # Verify cached in Redis / Django cache
        cached = cache.get(REDIS_LIVE_CONTEXT_KEY)
        self.assertEqual(cached, custom_json_str)

        # Verify inspection card status reflects updated size and keys
        status_after_sync = get_landing_assistant_redis_status(self.config)
        self.assertEqual(status_after_sync["size_bytes"], len(custom_json_str.encode("utf-8")))
        self.assertGreaterEqual(status_after_sync["keys_count"], 1)

        # 3. Superadmin triggers complete memory clear
        resp = self.client.post("/api/landing-assistant/redis/clear/")
        self.assertEqual(resp.status_code, 200)
        clear_res = resp.json()
        self.assertEqual(clear_res["status"], "success")
        self.assertEqual(clear_res["size_bytes"], 0)
        self.assertEqual(clear_res["keys_count"], 0)
        self.assertEqual(clear_res["raw_json"], "")

        # Verify model field is emptied
        self.config.refresh_from_db()
        self.assertEqual(self.config.custom_live_context, "")

        # Verify Redis / Cache is emptied
        self.assertIsNone(cache.get(REDIS_LIVE_CONTEXT_KEY))

    # =========================================================================
    # SUITE 7: Tab 1 Persona Studio & Hidden Digital Profile ID
    # =========================================================================

    @patch("core.partner_service.get_profile")
    def test_10_tab1_persona_studio_and_hidden_digital_id(self, mock_get_profile):
        """Test hiding landing_profile_id and rendering interactive Persona Studio with activation."""
        mock_get_profile.return_value = {
            "status": "success",
            "profiles": [
                {
                    "id": 101,
                    "name": "مستشار مبيعات كُـورَا الذكي",
                    "voice_name": "Puck",
                    "language": "arabic",
                    "dialect": "saudi",
                    "gender": "male",
                    "welcome_message": "أهلاً بك في منصة كُـورَا!",
                    "system_prompt": "أنت مستشار مبيعات خبير.",
                },
                {
                    "id": 102,
                    "name": "سارة - استشارية الباقات",
                    "voice_name": "Aoede",
                    "language": "arabic",
                    "dialect": "saudi",
                    "gender": "female",
                    "welcome_message": "مرحباً بك في كُـورَا!",
                    "system_prompt": "أنتِ سارة مستشارة الباقات.",
                }
            ]
        }

        self.client.force_login(self.admin_user)
        resp = self.client.get(f"/admin/core/platformvoiceassistantconfig/{self.config.pk}/change/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")

        # 1. Verify numeric field 'landing_profile_id' is NOT displayed in visible admin form fields
        self.assertNotIn('name="landing_profile_id" type="number"', html)
        self.assertNotIn('name="landing_profile_id" type="text"', html)
        # But hidden input is preserved for safe form submission
        self.assertIn('input type="hidden" name="landing_profile_id"', html)

        # 2. Verify Persona Studio interactive cards rendered
        self.assertIn("استوديو بروفايلات المساعد الصوتي (Persona Studio)", html)
        self.assertIn("مستشار مبيعات كُـورَا الذكي", html)
        self.assertIn("سارة - استشارية الباقات", html)
        self.assertIn("persona-card", html)
        self.assertIn("persona-pulse-dot", html)

        # 3. Super Admin activates profile 102 for landing assistant
        act_resp = self.client.post(
            f"/api/landing-assistant/profiles/102/activate/",
            data=json.dumps({}),
            content_type="application/json"
        )
        self.assertEqual(act_resp.status_code, 200)
        self.config.refresh_from_db()
        self.assertEqual(self.config.landing_profile_id, 102)
        self.assertEqual(self.config.assistant_name, "سارة - استشارية الباقات")
        self.assertEqual(self.config.voice_name, "Aoede")

    # =========================================================================
    # SUITE 8: Tab 5 Audio Modal & Call Recording Proxy
    # =========================================================================

    def test_11_tab5_audio_modal_and_recording_proxy(self):
        """Test audio listening button in Tab 5 and Audio Modal structure."""
        lead = LandingVoiceLead.objects.create(
            name="سلطان القحطاني",
            phone="0512345678",
            country_code="+966",
            call_status="completed",
            duration_seconds=145,
            call_id="call_test_audio_123",
            lead_status="interested",
        )

        self.client.force_login(self.admin_user)
        resp = self.client.get(f"/admin/core/platformvoiceassistantconfig/{self.config.pk}/change/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")

        # 1. Verify listen to recording button in leads table
        self.assertIn("btn-listen-audio", html)
        self.assertIn("استماع للتسجيل", html)
        self.assertIn(f'data-lead-id="{lead.id}"', html)
        self.assertIn('data-call-id="call_test_audio_123"', html)

        # 2. Verify Audio Modal element rendered in DOM
        self.assertIn('id="modal-call-audio"', html)
        self.assertIn('id="modal-audio-player"', html)
        self.assertIn('id="audio-caller-name"', html)
        self.assertIn('id="audio-caller-phone"', html)
        self.assertIn('id="audio-caller-duration"', html)
        self.assertIn('id="audio-in-progress-alert"', html)
        self.assertIn('id="audio-not-recorded-alert"', html)

        # 3. Test recording proxy returns 404 gracefully when recording not found
        resp = self.client.get(f"/api/ai-callcenter/calls/{lead.call_id}/recording/")
        self.assertIn(resp.status_code, [404, 500])

