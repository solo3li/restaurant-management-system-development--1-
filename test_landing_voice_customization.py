"""
Automated Test Suite for Platform Voice Assistant Customization & Admin Field Locking
(Language, Dialect, Voice Profile & Partner Client ID Lock)

Covers:
1. PlatformVoiceAssistantConfigAdmin: partner_client_id is locked (readonly, lock icon, badge, immutable on POST).
2. Partner Client ID automatic synchronization with Landing-Sales-Client (ID 662).
3. Visitor Voice Customization (Language: ar, en, fr, tr, de; Dialects: saudi, egyptian, gulf, moroccan, levantine, modern_standard, us, uk, standard; Voices: Aoede, Puck, Fenrir, Kore, Charon).
4. Lead recording: LandingVoiceLead stores language, dialect, and voice_name accurately.
5. Telephony session initiation: initiate_webrtc_call receives visitor preferences in real-time.
6. Welcome message localization and personalization.
7. LandingVoiceLeadAdmin: displays language, dialect, and voice profile in changelist and details.
8. Landing Page modal markup: ensures #lead-visitor-language, #lead-visitor-dialect, #lead-visitor-voice are present.
"""

import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.cache import cache

from apps.callcenter.models import (
    PlatformVoiceAssistantConfig,
    LandingVoiceLead,
)
from apps.callcenter.admin import (
    PlatformVoiceAssistantConfigAdmin,
    LandingVoiceLeadAdmin,
)
from apps.callcenter.landing_assistant_service import (
    ensure_landing_sales_client,
)


class LandingVoiceCustomizationTestSuite(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

        # Clean DB state
        LandingVoiceLead.objects.all().delete()
        PlatformVoiceAssistantConfig.objects.all().delete()

        # Setup Config
        self.config = PlatformVoiceAssistantConfig.get_config()
        self.config.is_active = True
        self.config.assistant_name = "مستشار مبيعات كُـورَا الذكي"
        self.config.system_prompt = "أنت مستشار مبيعات خبير."
        self.config.welcome_message = "أهلاً بك في منصة كُـورَا! كيف أساعدك اليوم؟"
        self.config.partner_client_id = "662"
        self.config.voice_name = "Aoede"
        self.config.language = "ar"
        self.config.accent = "saudi"
        self.config.max_call_duration_seconds = 180
        self.config.max_daily_calls_per_ip = 5
        self.config.save()

        # Superadmin User
        self.admin_user = User.objects.create_superuser(
            username="admin_voice_test",
            email="admin_voice@kura.local",
            password="adminpassword123",
        )

    def tearDown(self):
        cache.clear()

    # =========================================================================
    # SUITE 1: Admin Partner Client ID Locking & Readonly Enforcement
    # =========================================================================

    def test_01_admin_partner_client_id_is_readonly(self):
        """Verify partner_client_id is strictly registered as readonly in admin."""
        self.assertIn("partner_client_id", PlatformVoiceAssistantConfigAdmin.readonly_fields)

    def test_02_admin_change_form_renders_locked_partner_client_id(self):
        """Verify change form renders lock icon and badge for partner_client_id."""
        self.client.force_login(self.admin_user)
        resp = self.client.get(f"/admin/core/platformvoiceassistantconfig/{self.config.pk}/change/")
        self.assertEqual(resp.status_code, 200)

        html = resp.content.decode("utf-8")
        # Check badge and locked icon in Tab 2
        self.assertIn("معرف نظامي معزول ومقفول", html)
        self.assertIn("partner-client-id-badge", html)
        self.assertIn("Landing-Sales-Client", html)
        self.assertIn("فحص وربط الحساب الآن", html)

    def test_03_admin_post_cannot_overwrite_locked_partner_client_id(self):
        """Verify POST submission with altered partner_client_id does NOT change DB value."""
        self.client.force_login(self.admin_user)

        post_data = {
            "is_active": "on",
            "assistant_name": "مستشار مبيعات كُـورَا المحدّث",
            "system_prompt": "توجيهات جديدة لمبيعات المنصة.",
            "welcome_message": "مرحباً بكم!",
            "partner_client_id": "999999",  # Malicious attempt to change locked field
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
        # partner_client_id must remain 662, NOT 999999
        self.assertEqual(self.config.partner_client_id, "662")

    @patch("core.partner_service._request")
    def test_04_ensure_partner_client_syncs_with_landing_sales_client_662(self, mock_req):
        """Verify ensure_landing_sales_client links automatically to Landing-Sales-Client."""
        mock_req.return_value = {
            "status": "success",
            "clients": [
                {
                    "client_id": 662,
                    "name": "Landing-Sales-Client",
                    "external_reference": "landing-sales-client",
                }
            ],
        }
        res = ensure_landing_sales_client(self.config)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["client_id"], "662")
        self.assertEqual(res["client_name"], "Landing-Sales-Client")

    # =========================================================================
    # SUITE 2: Visitor Voice Customization (Arabic & Saudi Dialect)
    # =========================================================================

    @patch("core.partner_service.initiate_webrtc_call")
    def test_05_visitor_arabic_saudi_customization(self, mock_initiate):
        """Verify visitor selecting Arabic + Saudi + Aoede is saved and passed to WebRTC."""
        mock_initiate.return_value = {
            "status": "success",
            "call_id": "call_saudi_01",
            "room_name": "room_saudi_01",
            "livekit_url": "wss://test.livekit.local",
            "livekit_token": "token_saudi_123",
        }

        payload = {
            "name": "فهد الدوسري",
            "phone": "551234567",
            "country_code": "+966",
            "language": "ar",
            "dialect": "saudi",
            "voice_name": "Aoede",
        }
        resp = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")

        # Verify agent_profile in response
        profile = data["agent_profile"]
        self.assertEqual(profile["language"], "ar")
        self.assertEqual(profile["dialect"], "saudi")
        self.assertEqual(profile["voice"], "Aoede")

        # Verify lead record in DB
        lead = LandingVoiceLead.objects.get(call_id="call_saudi_01")
        self.assertEqual(lead.name, "فهد الدوسري")
        self.assertEqual(lead.language, "ar")
        self.assertEqual(lead.dialect, "saudi")
        self.assertEqual(lead.voice_name, "Aoede")

        # Verify partner service call received customization
        mock_initiate.assert_called_once()
        _, kwargs = mock_initiate.call_args
        self.assertEqual(kwargs["caller_name"], "فهد الدوسري")
        self.assertEqual(kwargs["language"], "ar")
        self.assertEqual(kwargs["accent"], "saudi")
        self.assertEqual(kwargs["voice_name"], "Aoede")

    # =========================================================================
    # SUITE 3: Visitor Voice Customization (English & US/UK Dialects)
    # =========================================================================

    @patch("core.partner_service.initiate_webrtc_call")
    def test_06_visitor_english_us_customization(self, mock_initiate):
        """Verify visitor selecting English + US + Fenrir."""
        mock_initiate.return_value = {
            "status": "success",
            "call_id": "call_en_us_02",
            "room_name": "room_en_us_02",
            "livekit_url": "wss://test.livekit.local",
            "livekit_token": "token_en_123",
        }

        payload = {
            "name": "Alex Johnson",
            "phone": "4155551234",
            "country_code": "+1",
            "language": "en",
            "dialect": "us",
            "voice_name": "Fenrir",
        }
        resp = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        lead = LandingVoiceLead.objects.get(call_id="call_en_us_02")
        self.assertEqual(lead.language, "en")
        self.assertEqual(lead.dialect, "us")
        self.assertEqual(lead.voice_name, "Fenrir")
        self.assertIn("Hello Alex Johnson", data["welcome_message"])

    @patch("core.partner_service.initiate_webrtc_call")
    def test_07_visitor_english_uk_customization(self, mock_initiate):
        """Verify visitor selecting English + UK + Charon."""
        mock_initiate.return_value = {
            "status": "success",
            "call_id": "call_en_uk_03",
            "room_name": "room_en_uk_03",
            "livekit_url": "wss://test.livekit.local",
            "livekit_token": "token_uk_123",
        }

        payload = {
            "name": "Oliver Smith",
            "phone": "7911123456",
            "country_code": "+44",
            "language": "en",
            "dialect": "uk",
            "voice_name": "Charon",
        }
        resp = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        lead = LandingVoiceLead.objects.get(call_id="call_en_uk_03")
        self.assertEqual(lead.language, "en")
        self.assertEqual(lead.dialect, "uk")
        self.assertEqual(lead.voice_name, "Charon")

    # =========================================================================
    # SUITE 4: Visitor Voice Customization (French, Turkish, German)
    # =========================================================================

    @patch("core.partner_service.initiate_webrtc_call")
    def test_08_visitor_french_customization(self, mock_initiate):
        """Verify French visitor with standard dialect and Kore voice."""
        mock_initiate.return_value = {
            "status": "success",
            "call_id": "call_fr_04",
            "room_name": "room_fr_04",
            "livekit_url": "wss://test.livekit.local",
            "livekit_token": "token_fr_123",
        }

        payload = {
            "name": "Jean Dupont",
            "phone": "612345678",
            "country_code": "+33",
            "language": "fr",
            "dialect": "standard",
            "voice_name": "Kore",
        }
        resp = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        lead = LandingVoiceLead.objects.get(call_id="call_fr_04")
        self.assertEqual(lead.language, "fr")
        self.assertEqual(lead.dialect, "standard")
        self.assertEqual(lead.voice_name, "Kore")
        self.assertIn("Bonjour Jean Dupont", data["welcome_message"])

    @patch("core.partner_service.initiate_webrtc_call")
    def test_09_visitor_turkish_and_german_customization(self, mock_initiate):
        """Verify Turkish and German visitors with Puck and Fenrir."""
        mock_initiate.return_value = {
            "status": "success",
            "call_id": "call_tr_05",
            "room_name": "room_tr_05",
            "livekit_url": "wss://test.livekit.local",
            "livekit_token": "token_tr_123",
        }

        # Turkish
        payload_tr = {
            "name": "Mehmet Yilmaz",
            "phone": "5321234567",
            "country_code": "+90",
            "language": "tr",
            "dialect": "standard",
            "voice_name": "Puck",
        }
        resp = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps(payload_tr),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        lead_tr = LandingVoiceLead.objects.get(call_id="call_tr_05")
        self.assertEqual(lead_tr.language, "tr")
        self.assertEqual(lead_tr.voice_name, "Puck")

        # German
        mock_initiate.return_value["call_id"] = "call_de_06"
        payload_de = {
            "name": "Hans Mueller",
            "phone": "15112345678",
            "country_code": "+49",
            "language": "de",
            "dialect": "standard",
            "voice_name": "Fenrir",
        }
        resp = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps(payload_de),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        lead_de = LandingVoiceLead.objects.get(call_id="call_de_06")
        self.assertEqual(lead_de.language, "de")
        self.assertEqual(lead_de.voice_name, "Fenrir")

    # =========================================================================
    # SUITE 5: Arabic Regional Dialects (Egyptian, Gulf, Moroccan, Levantine, Fusha)
    # =========================================================================

    @patch("core.partner_service.initiate_webrtc_call")
    def test_10_arabic_regional_dialects(self, mock_initiate):
        """Verify all regional Arabic dialects (egyptian, gulf, moroccan, levantine, modern_standard)."""
        dialects = ["egyptian", "gulf", "moroccan", "levantine", "modern_standard"]
        for idx, dialect in enumerate(dialects):
            mock_initiate.return_value = {
                "status": "success",
                "call_id": f"call_ar_{dialect}_{idx}",
                "room_name": f"room_{dialect}",
                "livekit_url": "wss://test.livekit.local",
                "livekit_token": "token_123",
            }
            payload = {
                "name": f"عميل {dialect}",
                "phone": f"50111000{idx}",
                "country_code": "+966",
                "language": "ar",
                "dialect": dialect,
                "voice_name": "Puck",
            }
            resp = self.client.post(
                "/api/landing/voice-session/",
                data=json.dumps(payload),
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 200)
            lead = LandingVoiceLead.objects.get(call_id=f"call_ar_{dialect}_{idx}")
            self.assertEqual(lead.dialect, dialect)

    # =========================================================================
    # SUITE 6: Django Admin Display & CRM Integration for LandingVoiceLead
    # =========================================================================

    def test_11_landing_voice_lead_admin_displays_customization(self):
        """Verify LandingVoiceLeadAdmin list_display and fieldsets render language, dialect, and voice."""
        lead = LandingVoiceLead.objects.create(
            name="سارة المطيري",
            phone="509876543",
            country_code="+966",
            full_phone="+966509876543",
            language="ar",
            dialect="saudi",
            voice_name="Aoede",
            call_status="connected",
            duration_seconds=125,
            lead_status="interested",
        )

        self.client.force_login(self.admin_user)

        # 1. Changelist View
        resp = self.client.get("/admin/core/landingvoicelead/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")
        self.assertIn("سارة المطيري", html)
        self.assertIn("سعودية", html)
        self.assertIn("سارة (Aoede)", html)
        self.assertIn("العربية", html)

        # 2. Changeform View
        resp = self.client.get(f"/admin/core/landingvoicelead/{lead.pk}/change/")
        self.assertEqual(resp.status_code, 200)
        detail_html = resp.content.decode("utf-8")
        self.assertIn("التفضيلات الصوتية واللغوية", detail_html)
        self.assertIn("language", detail_html)
        self.assertIn("dialect", detail_html)
        self.assertIn("voice_name", detail_html)

    # =========================================================================
    # SUITE 7: Landing Page Template Renders Customization Fields
    # =========================================================================

    def test_12_landing_page_renders_voice_customization_modal_fields(self):
        """Verify templates/landing.html renders language, dialect, and voice profile select fields."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")

        self.assertIn('id="landing-lead-modal"', html)
        self.assertIn('id="lead-visitor-language"', html)
        self.assertIn('id="lead-visitor-dialect"', html)
        self.assertIn('id="lead-visitor-voice"', html)
        self.assertIn("handleLeadLanguageChange", html)
        self.assertIn("Aoede", html)
        self.assertIn("Puck", html)
        self.assertIn("Fenrir", html)
        self.assertIn("Kore", html)
        self.assertIn("Charon", html)

    # =========================================================================
    # SUITE 8: Edge Cases & Robustness Verification
    # =========================================================================

    def test_13_admin_methods_safe_when_obj_is_none(self):
        """Verify admin helper methods do not raise AttributeError when obj is None."""
        from django.contrib import admin
        config_admin = PlatformVoiceAssistantConfigAdmin(PlatformVoiceAssistantConfig, admin.site)
        lead_admin = LandingVoiceLeadAdmin(LandingVoiceLead, admin.site)

        # PlatformVoiceAssistantConfigAdmin
        res1 = config_admin.partner_client_id(None)
        self.assertIn("662", res1)
        self.assertIn("معرف نظامي معزول ومقفول", res1)

        res2 = config_admin.partner_client_id_display(None)
        self.assertIn("662", res2)

        # LandingVoiceLeadAdmin
        self.assertEqual(lead_admin.language_display(None), "—")
        self.assertEqual(lead_admin.dialect_display(None), "—")
        self.assertEqual(lead_admin.voice_display(None), "—")
        self.assertIn("—", lead_admin.whatsapp_button(None))
        self.assertIn("—", lead_admin.whatsapp_link_display(None))
        self.assertIn("—", lead_admin.call_status_badge(None))
        self.assertIn("00:00", lead_admin.formatted_duration_display(None))

    @patch("core.partner_service.initiate_webrtc_call")
    def test_14_language_scoped_dialect_mismatch_fallback(self, mock_initiate):
        """Verify cross-language dialect mismatches fall back strictly to appropriate defaults."""
        mock_initiate.return_value = {
            "status": "success",
            "call_id": "call_mismatch_01",
            "room_name": "room_mismatch_01",
            "livekit_url": "wss://test.livekit.local",
            "livekit_token": "token_mismatch_123",
        }

        # 1. English with Moroccan Arabic dialect -> Must fallback to 'us'
        resp1 = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps({"language": "en", "dialect": "moroccan", "name": "John Doe", "phone": "5551234"}),
            content_type="application/json",
        )
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()
        self.assertEqual(data1["agent_profile"]["dialect"], "us")
        lead1 = LandingVoiceLead.objects.get(call_id="call_mismatch_01")
        self.assertEqual(lead1.language, "en")
        self.assertEqual(lead1.dialect, "us")

        # 2. Arabic with UK British dialect -> Must fallback to 'saudi'
        mock_initiate.return_value["call_id"] = "call_mismatch_02"
        resp2 = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps({"language": "ar", "dialect": "uk", "name": "سعد علي", "phone": "5559876"}),
            content_type="application/json",
        )
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertEqual(data2["agent_profile"]["dialect"], "saudi")
        lead2 = LandingVoiceLead.objects.get(call_id="call_mismatch_02")
        self.assertEqual(lead2.language, "ar")
        self.assertEqual(lead2.dialect, "saudi")

        # 3. French with Saudi dialect -> Must fallback to 'standard'
        mock_initiate.return_value["call_id"] = "call_mismatch_03"
        resp3 = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps({"language": "fr", "dialect": "saudi", "name": "Pierre", "phone": "6123456"}),
            content_type="application/json",
        )
        self.assertEqual(resp3.status_code, 200)
        data3 = resp3.json()
        self.assertEqual(data3["agent_profile"]["dialect"], "standard")
        lead3 = LandingVoiceLead.objects.get(call_id="call_mismatch_03")
        self.assertEqual(lead3.language, "fr")
        self.assertEqual(lead3.dialect, "standard")

    @patch("core.partner_service.initiate_webrtc_call")
    def test_15_invalid_voice_name_fallback(self, mock_initiate):
        """Verify invalid voice profile falls back to config voice or Aoede."""
        mock_initiate.return_value = {
            "status": "success",
            "call_id": "call_voice_fb_01",
            "room_name": "room_voice_fb_01",
            "livekit_url": "wss://test.livekit.local",
            "livekit_token": "token_voice_fb_123",
        }
        resp = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps({"voice_name": "UnicornVoice", "name": "زائر", "phone": "5551111"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        lead = LandingVoiceLead.objects.get(call_id="call_voice_fb_01")
        self.assertEqual(lead.voice_name, "Aoede")

    def test_16_save_model_strictly_preserves_partner_client_id(self):
        """Verify save_model ensures partner_client_id cannot be changed from 662."""
        from django.contrib import admin
        config_admin = PlatformVoiceAssistantConfigAdmin(PlatformVoiceAssistantConfig, admin.site)
        cfg = PlatformVoiceAssistantConfig.get_config()
        cfg.partner_client_id = "662"
        cfg.save()

        # Simulate attempt to mutate partner_client_id via admin form save
        cfg.partner_client_id = "MALICIOUS_999"
        config_admin.save_model(request=None, obj=cfg, form=None, change=True)

        cfg.refresh_from_db()
        self.assertEqual(cfg.partner_client_id, "662")

    @patch("core.partner_service.initiate_webrtc_call")
    def test_17_all_11_languages_localized_greeting_and_strict_directive(self, mock_initiate):
        """Verify all 11 languages generate localized greeting with name and inject strict language directive."""
        lang_cases = [
            ("ar", "saudi", "Aoede", "فهد", "فهد", "Arabic (العربية)"),
            ("en", "english_us", "Puck", "Alex", "Alex", "English"),
            ("fr", "french_fr", "Kore", "Pierre", "Pierre", "French (Français)"),
            ("es", "spanish_es", "Galatea", "Carlos", "Carlos", "Spanish (Español)"),
            ("de", "german_de", "Fenrir", "Hans", "Hans", "German (Deutsch)"),
            ("it", "italian_it", "Despina", "Marco", "Marco", "Italian (Italiano)"),
            ("tr", "turkish_tr", "Zephyr", "Emre", "Emre", "Turkish (Türkçe)"),
            ("ru", "russian_ru", "Orus", "Ivan", "Ivan", "Russian (Русский)"),
            ("ur", "urdu_pk", "Sadachbia", "Tariq", "Tariq", "Urdu (اردو)"),
            ("hi", "hindi_in", "Kore", "Aarav", "Aarav", "Hindi (हिन्दी)"),
            ("zh", "chinese_zh", "Aoede", "Wei", "Wei", "Mandarin Chinese (中文)"),
        ]

        for idx, (lang, dialect, voice, name, expected_in_greeting, expected_lang_title) in enumerate(lang_cases):
            mock_initiate.reset_mock()
            mock_initiate.return_value = {
                "status": "success",
                "call_id": f"call_11lang_{idx}",
                "room_name": f"room_11lang_{idx}",
                "livekit_url": "wss://test.livekit.local",
                "livekit_token": f"token_11lang_{idx}",
            }

            payload = {
                "name": name,
                "phone": f"05000000{idx:02d}",
                "country_code": "+966",
                "language": lang,
                "dialect": dialect,
                "voice_name": voice,
            }
            resp = self.client.post(
                "/api/landing/voice-session/",
                data=json.dumps(payload),
                content_type="application/json",
                REMOTE_ADDR=f"198.51.100.{10+idx}",
            )
            self.assertEqual(resp.status_code, 200, f"Failed for language {lang}")
            data = resp.json()

            # 1. Check greeting contains name
            self.assertIn(expected_in_greeting, data["welcome_message"], f"Name missing in {lang} welcome message")

            # 2. Check strict directive passed to partner service
            mock_initiate.assert_called_once()
            _, kwargs = mock_initiate.call_args
            instructions = kwargs.get("custom_instructions") or kwargs.get("instructions") or ""
            self.assertIn("CRITICAL LANGUAGE DIRECTIVE", instructions)
            self.assertIn(expected_lang_title, instructions)

            # 3. Check DB record
            lead = LandingVoiceLead.objects.get(call_id=f"call_11lang_{idx}")
            self.assertEqual(lead.language, lang)
            self.assertEqual(lead.dialect, dialect)
            self.assertEqual(lead.voice_name, voice)

    @patch("core.partner_service.initiate_webrtc_call")
    def test_18_partner_pbx_room_name_stored_in_lead_call_id(self, mock_initiate):
        """Verify real Partner PBX integer call_id and room_name results in room_name stored in lead.call_id."""
        mock_initiate.return_value = {
            "status": "success",
            "call_id": 645,
            "room_name": "room_webrtc_prt_10_662_a7dad4d5",
            "livekit_url": "wss://test.livekit.local",
            "livekit_token": "token_rec_test",
        }

        payload = {
            "name": "حامد العلي",
            "phone": "0549998888",
            "country_code": "+966",
            "language": "ar",
            "dialect": "saudi",
            "voice_name": "Aoede",
        }
        resp = self.client.post(
            "/api/landing/voice-session/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        # Requirement 3: lead.call_id must store the room_name so recording proxy matches PBX room listing
        lead = LandingVoiceLead.objects.get(name="حامد العلي")
        self.assertEqual(lead.call_id, "room_webrtc_prt_10_662_a7dad4d5")

    def test_19_admin_tab1_live_webrtc_studio_tester_dom(self):
        """Verify interactive Live WebRTC Studio Tester card is properly embedded in Admin Tab 1."""
        self.client.force_login(self.admin_user)
        resp = self.client.get(f"/admin/core/platformvoiceassistantconfig/{self.config.pk}/change/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")

        # Studio Card in Tab 1
        self.assertIn('id="admin-webrtc-studio-card"', html)
        self.assertIn("استوديو الاختبار الصوتي الحي", html)

        # Control selectors
        self.assertIn('id="admin-tester-language"', html)
        self.assertIn('id="admin-tester-dialect"', html)
        self.assertIn('id="admin-tester-voice"', html)

        # Timer, status badge, wave bars, and buttons
        self.assertIn('id="admin-tester-timer"', html)
        self.assertIn('id="admin-tester-status-badge"', html)
        self.assertIn('id="admin-tester-wave-container"', html)
        self.assertIn('id="btn-admin-tester-start"', html)
        self.assertIn('id="btn-admin-tester-mute"', html)
        self.assertIn('id="btn-admin-tester-end"', html)

        # Verify all 11 languages rendered in select
        for lang_code in ("ar", "en", "fr", "es", "de", "it", "tr", "ru", "ur", "hi", "zh"):
            self.assertIn(f'value="{lang_code}"', html)

        # Verify 30 voices rendered in select
        self.assertIn('value="Aoede"', html)
        self.assertIn('value="Puck"', html)
        self.assertIn('value="Galatea"', html)
        self.assertIn('value="Despina"', html)
        self.assertIn('value="Sadachbia"', html)
        self.assertIn('value="Sao"', html)

    @patch("core.partner_service._request")
    def test_20_partner_service_initiate_webrtc_call_language_mapping(self, mock_request):
        """Verify initiate_webrtc_call canonicalizes ISO language codes to Partner PBX language IDs."""
        from core import partner_service as ps
        mock_request.return_value = {"status": "success", "room_name": "room_test_1", "livekit_url": "wss://test"}

        # Case A: 'ar' mapped to canonical 'arabic'
        ps.initiate_webrtc_call(client_id=662, language="ar")
        _, kwargs_a = mock_request.call_args
        self.assertEqual(kwargs_a["data"]["language"], "arabic")

        # Case B: 'es' mapped to canonical 'spanish'
        ps.initiate_webrtc_call(client_id=662, language="es")
        _, kwargs_b = mock_request.call_args
        self.assertEqual(kwargs_b["data"]["language"], "spanish")


