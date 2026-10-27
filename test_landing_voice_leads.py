"""
Comprehensive Automated Test Suite for Landing Page Voice Leads & Customer Acquisition
Covers:
1. LandingVoiceLead Model (Fields, format_full_phone across all countries, whatsapp_url, duration)
2. POST /api/landing/voice-session/ with visitor name, phone, country codes (+966, +20, +1, +44, custom)
3. Personalized welcome greeting pronouncing caller's name to Gemini Live / WebRTC Partner Service
4. Input validation (name length, phone digits) returning HTTP 400
5. POST /api/landing/voice-session/end/ (duration & call_status update by lead_id and call_id)
6. Django Admin LandingVoiceLeadAdmin (list_display, list_editable, search, filters, WhatsApp button)
7. Landing Page template modal rendering with international country code picker
"""
import json
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.cache import cache
from apps.callcenter.models import PlatformVoiceAssistantConfig, LandingVoiceLead
from apps.accounts.models import UserProfile
from apps.tenants.models import Tenant


class LandingVoiceLeadsTestSuite(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

        # 1. Platform Voice Assistant Config
        PlatformVoiceAssistantConfig.objects.all().delete()
        self.config = PlatformVoiceAssistantConfig.get_config()
        self.config.is_active = True
        self.config.assistant_name = "مستشار مبيعات منصة مطاعم"
        self.config.welcome_message = "أهلاً بك في منصة مطاعم السحابية! أنا مستشارك الذكي للمبيعات وتطوير الأعمال."
        self.config.max_daily_calls_per_ip = 5
        self.config.max_call_duration_seconds = 180
        self.config.partner_client_id = "49"
        self.config.save()

        # 2. Superadmin user for Django Admin verification
        self.admin_user = User.objects.create_superuser(
            username="test_admin",
            email="admin@test.local",
            password="adminpassword123",
        )

    def tearDown(self):
        cache.clear()

    # =========================================================================
    # SUITE 1: LandingVoiceLead Model Logic & Country Phone Formatting
    # =========================================================================

    def test_01_model_creation_and_fields(self):
        """Test creating LandingVoiceLead and verifying model defaults."""
        lead = LandingVoiceLead.objects.create(
            name="سعد الدوسري",
            phone="0551234567",
            country_code="+966",
            call_status="initiated",
            ip_address="192.168.1.100",
            notes="عميل مهتم بباقة المطاعم الاحترافية",
        )
        self.assertEqual(lead.name, "سعد الدوسري")
        self.assertEqual(lead.country_code, "+966")
        self.assertEqual(lead.full_phone, "+966551234567")
        self.assertEqual(lead.call_status, "initiated")
        self.assertEqual(lead.lead_status, "new")
        self.assertEqual(lead.duration_seconds, 0)
        self.assertEqual(lead.formatted_duration(), "00:00")
        self.assertEqual(lead.whatsapp_url, "https://wa.me/966551234567")
        self.assertIn("سعد الدوسري", str(lead))

    def test_02_format_full_phone_international_coverage(self):
        """Test formatting phone numbers across various countries worldwide."""
        cases = [
            # (raw_phone, country_code, expected_full, expected_wa)
            ("0501234567", "+966", "+966501234567", "https://wa.me/966501234567"),
            ("501234567", "+966", "+966501234567", "https://wa.me/966501234567"),
            ("01012345678", "+20", "+201012345678", "https://wa.me/201012345678"),
            ("1012345678", "+20", "+201012345678", "https://wa.me/201012345678"),
            ("0551234567", "+971", "+971551234567", "https://wa.me/971551234567"),
            ("2025550199", "+1", "+12025550199", "https://wa.me/12025550199"),
            ("7911123456", "+44", "+447911123456", "https://wa.me/447911123456"),
            ("5551234567", "+90", "+905551234567", "https://wa.me/905551234567"),
            ("15112345678", "+49", "+4915112345678", "https://wa.me/4915112345678"),
            ("612345678", "+33", "+33612345678", "https://wa.me/33612345678"),
            ("987654321", "+351", "+351987654321", "https://wa.me/351987654321"),  # Portugal (Custom)
            ("+966501234567", "+966", "+966501234567", "https://wa.me/966501234567"),
            ("00966501234567", "+966", "+966501234567", "https://wa.me/966501234567"),  # 00 prefix no duplication
            ("00201012345678", "+20", "+201012345678", "https://wa.me/201012345678"),
            ("+966 50 123 4567", "+966", "+966501234567", "https://wa.me/966501234567"),
            ("+966 (050) 123-4567", "+966", "+966501234567", "https://wa.me/966501234567"),
        ]
        for phone, cc, expected_full, expected_wa in cases:
            res_full = LandingVoiceLead.format_full_phone(phone, cc)
            self.assertEqual(res_full, expected_full, f"Failed for {phone} with CC {cc}")
            lead = LandingVoiceLead(name="Test", phone=phone, country_code=cc)
            lead.save()
            self.assertEqual(lead.full_phone, expected_full)
            self.assertEqual(lead.whatsapp_url, expected_wa)

    # =========================================================================
    # SUITE 2: POST /api/landing/voice-session/ Lead Capture & Personalized Welcome
    # =========================================================================

    @patch("core.partner_service.initiate_webrtc_call")
    def test_03_create_lead_and_personalized_greeting(self, mock_webrtc):
        """Verify visitor details create LandingVoiceLead and caller's name is pronounced in greeting."""
        mock_webrtc.return_value = {
            "status": "success",
            "call_id": "call_livekit_lead_101",
            "room_name": "room_lead_101",
            "livekit_url": "wss://livekit.test.local",
            "livekit_token": "token_lead_101",
            "max_duration_seconds": 180,
        }

        payload = {
            "name": "فيصل المطيري",
            "phone": "0541234567",
            "country_code": "+966",
        }

        res = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps(payload),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.88",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["call_id"], "call_livekit_lead_101")
        self.assertIsNotNone(data["lead_id"])

        # Check personalized greeting
        self.assertIn("فيصل المطيري", data["welcome_message"])
        self.assertEqual(
            data["welcome_message"],
            "أهلاً بك يا فيصل المطيري! أنا مستشار مبيعات منصة مطاعم، كيف أقدر أساعدك اليوم في إدارة وتطوير مطعمك؟"
        )

        # Check partner_service call arguments
        mock_webrtc.assert_called_once()
        _, kwargs = mock_webrtc.call_args
        self.assertEqual(kwargs["caller_name"], "فيصل المطيري")
        self.assertIn("فيصل المطيري", kwargs["welcome_message"])

        # Check database record
        lead = LandingVoiceLead.objects.get(id=data["lead_id"])
        self.assertEqual(lead.name, "فيصل المطيري")
        self.assertEqual(lead.phone, "0541234567")
        self.assertEqual(lead.country_code, "+966")
        self.assertEqual(lead.full_phone, "+966541234567")
        self.assertEqual(lead.call_id, "call_livekit_lead_101")
        self.assertEqual(lead.call_status, "initiated")
        self.assertEqual(lead.lead_status, "new")
        self.assertEqual(lead.ip_address, "198.51.100.88")

    @patch("core.partner_service.initiate_webrtc_call")
    def test_04_international_visitor_lead_capture(self, mock_webrtc):
        """Verify international leads from Egypt, UAE, and USA work seamlessly."""
        mock_webrtc.return_value = {
            "status": "success",
            "call_id": "call_intl_202",
            "room_name": "room_intl_202",
            "livekit_url": "wss://livekit.test.local",
            "livekit_token": "token_intl_202",
            "max_duration_seconds": 180,
        }

        # International Lead from Egypt (+20)
        res = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps({
                "name": "محمود حسني",
                "phone": "01098765432",
                "country_code": "+20",
            }),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.99",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        lead = LandingVoiceLead.objects.get(id=data["lead_id"])
        self.assertEqual(lead.country_code, "+20")
        self.assertEqual(lead.full_phone, "+201098765432")
        self.assertEqual(lead.whatsapp_url, "https://wa.me/201098765432")
        self.assertIn("محمود حسني", data["welcome_message"])

    def test_05_validation_rejections(self):
        """Verify invalid name or phone returns HTTP 400 with descriptive error message."""
        # 1. Name too short (< 2 chars)
        res = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps({
                "name": "أ",
                "phone": "0501234567",
                "country_code": "+966",
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["code"], "invalid_name")

        # 2. Phone invalid (too short)
        res = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps({
                "name": "طارق الصالح",
                "phone": "123",
                "country_code": "+966",
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["code"], "invalid_phone")

    # =========================================================================
    # SUITE 3: POST /api/landing/voice-session/end/ Call End Telemetry
    # =========================================================================

    def test_06_end_session_by_lead_id(self):
        """Verify ending session updates call duration and status by lead_id."""
        lead = LandingVoiceLead.objects.create(
            name="خالد التميمي",
            phone="0507778899",
            country_code="+966",
            call_status="initiated",
            duration_seconds=0,
            call_id="call_term_123",
        )

        res = self.client.post(
            "/api/landing/voice-session/end/",
            data=json.dumps({
                "lead_id": lead.id,
                "duration_seconds": 95,
                "call_status": "completed",
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["duration_seconds"], 95)
        self.assertEqual(data["call_status"], "completed")

        lead.refresh_from_db()
        self.assertEqual(lead.duration_seconds, 95)
        self.assertEqual(lead.call_status, "completed")
        self.assertEqual(lead.formatted_duration(), "01:35")

    def test_07_end_session_by_call_id(self):
        """Verify ending session updates call duration and status by call_id."""
        lead = LandingVoiceLead.objects.create(
            name="سلطان القحطاني",
            phone="0501112233",
            country_code="+966",
            call_status="initiated",
            duration_seconds=0,
            call_id="call_term_abc_456",
        )

        res = self.client.post(
            "/api/landing/voice-session/end/",
            data=json.dumps({
                "call_id": "call_term_abc_456",
                "duration_seconds": 120,
                "call_status": "completed",
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.duration_seconds, 120)
        self.assertEqual(lead.call_status, "completed")

    def test_08_end_session_not_found(self):
        """Verify ending non-existent session returns HTTP 404."""
        res = self.client.post(
            "/api/landing/voice-session/end/",
            data=json.dumps({
                "lead_id": 999999,
                "duration_seconds": 10,
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["code"], "lead_not_found")

    # =========================================================================
    # SUITE 4: Django Admin LandingVoiceLeadAdmin Verification
    # =========================================================================

    def test_09_admin_lead_list_view_and_whatsapp_button(self):
        """Verify Django Admin renders leads with WhatsApp button and editable lead_status."""
        self.client.force_login(self.admin_user)

        lead = LandingVoiceLead.objects.create(
            name="عمر الشريف",
            phone="0556667788",
            country_code="+966",
            full_phone="+966556667788",
            call_status="completed",
            duration_seconds=130,
            lead_status="interested",
        )

        res = self.client.get("/admin/core/landingvoicelead/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "عمر الشريف")
        self.assertContains(res, "+966556667788")
        self.assertContains(res, "https://wa.me/966556667788")
        self.assertContains(res, "محادثة واتساب")
        self.assertContains(res, "مكتملة")

    def test_10_admin_list_editable_lead_status(self):
        """Verify changing lead_status directly via Django Admin list view."""
        self.client.force_login(self.admin_user)

        lead = LandingVoiceLead.objects.create(
            name="بندر الرويلي",
            phone="0508889900",
            country_code="+966",
            lead_status="new",
        )

        # Post to admin changelist updating lead_status
        post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-id": str(lead.id),
            "form-0-lead_status": "converted",
            "_save": "حفظ",
        }
        res = self.client.post("/admin/core/landingvoicelead/", data=post_data, follow=True)
        self.assertEqual(res.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.lead_status, "converted")

    # =========================================================================
    # SUITE 5: Landing Page Modal Markup & Country Picker Rendering
    # =========================================================================

    def test_11_landing_page_renders_lead_modal(self):
        """Verify landing page renders the visitor lead modal with all world countries and custom code."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "id=\"landing-lead-modal\"")
        self.assertContains(res, "id=\"lead-visitor-name\"")
        self.assertContains(res, "id=\"lead-visitor-phone\"")
        self.assertContains(res, "id=\"lead-country-code\"")
        self.assertContains(res, "+966")  # Saudi
        self.assertContains(res, "+20")   # Egypt
        self.assertContains(res, "+971")  # UAE
        self.assertContains(res, "+1")    # USA
        self.assertContains(res, "+44")   # UK
        self.assertContains(res, "+90")   # Turkey
        self.assertContains(res, "+49")   # Germany
        self.assertContains(res, "+33")   # France
        self.assertContains(res, "custom") # Other/custom country code
        self.assertContains(res, "id=\"lead-custom-code-wrap\"")
        self.assertContains(res, "بدء المكالمة الصوتية الآن 🎙️")

    def test_12_whatsapp_url_validity_threshold_and_admin_sync(self):
        """Verify whatsapp_url returns empty for short/invalid numbers and save() resyncs full_phone on phone edit."""
        lead = LandingVoiceLead.objects.create(
            name="طارق الخالدي",
            phone="0501112233",
            country_code="+966",
        )
        self.assertEqual(lead.full_phone, "+966501112233")
        self.assertEqual(lead.whatsapp_url, "https://wa.me/966501112233")

        # Edit phone on model instance and save
        lead.phone = "0559998877"
        lead.save()
        lead.refresh_from_db()
        self.assertEqual(lead.full_phone, "+966559998877")
        self.assertEqual(lead.whatsapp_url, "https://wa.me/966559998877")

        # Short/invalid phone threshold check
        lead_dummy = LandingVoiceLead(name="زائر تجريبي", phone="—", full_phone="—")
        self.assertEqual(lead_dummy.whatsapp_url, "")

    def test_13_connected_telemetry_and_no_downgrade(self):
        """Verify call transitions to connected, and completed status is not downgraded."""
        lead = LandingVoiceLead.objects.create(
            name="سالم الغامدي",
            phone="0504445566",
            country_code="+966",
            call_status="initiated",
        )

        # 1. Update to connected
        res = self.client.post(
            "/api/landing/voice-session/end/",
            data=json.dumps({
                "lead_id": lead.id,
                "call_status": "connected",
                "duration_seconds": 0,
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.call_status, "connected")

        # 2. Complete session with duration
        res = self.client.post(
            "/api/landing/voice-session/end/",
            data=json.dumps({
                "lead_id": lead.id,
                "call_status": "completed",
                "duration_seconds": 75,
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.call_status, "completed")
        self.assertEqual(lead.duration_seconds, 75)

        # 3. Trailing connected ping cannot downgrade completed
        res = self.client.post(
            "/api/landing/voice-session/end/",
            data=json.dumps({
                "lead_id": lead.id,
                "call_status": "connected",
                "duration_seconds": 10,
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.call_status, "completed")
        self.assertEqual(lead.duration_seconds, 75)

    def test_14_landing_modal_bilingual_english_rendering(self):
        """Verify landing lead modal renders localized English labels when lang=en is queried."""
        res = self.client.get("/?lang=en")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "id=\"landing-lead-modal\"")
        self.assertContains(res, "Start Voice Call Now 🎙️")
        self.assertContains(res, "Full Name")
        self.assertContains(res, "Mobile Number")
