"""
Comprehensive Test Suite: Landing Voice Assistant Live Persona Synchronization
Verifies:
1. Platform HQ Tenant ("منظومة مطاعم HQ") setup with knowledge docs and client_id=49.
2. Super Admin frontend auto-linking to Platform HQ in AI Call Center.
3. Strict 403 Forbidden enforcement on /api/ai-callcenter/profiles/<id>/set-landing-persona/ for non-superadmins.
4. Successful persona binding by Super Admin updating PlatformVoiceAssistantConfig.
5. Immediate live reflection on public /api/landing/voice-session/ endpoint.
6. UI rendering in templates/ai_callcenter/persona.html (Active Badge & Super Admin Action Button).
"""

import json
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.callcenter.models import PlatformVoiceAssistantConfig
from apps.callcenter.platform_hq import (
    get_or_create_platform_hq_tenant,
    PLATFORM_HQ_NAME,
    PLATFORM_HQ_SLUG,
    PLATFORM_HQ_CLIENT_ID,
)
from apps.tenants.models import Tenant, Branch
from apps.accounts.models import UserProfile
from apps.audit.models import KnowledgeDocument

User = get_user_model()


class LandingPersonaSyncTestSuite(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

        # 1. Super Admin (Platform Admin)
        self.super_admin = User.objects.create_superuser(
            username="super_platform_admin",
            email="super@motaem.local",
            password="adminpassword123"
        )
        self.super_profile = UserProfile.objects.create(
            user=self.super_admin,
            role="platform_admin",
            is_platform_admin=True,
            tenant=None,
        )

        # 2. Regular Restaurant Owner & Tenant
        self.owner_user = User.objects.create_user(
            username="regular_rest_owner",
            email="owner@shawarma.local",
            password="password123"
        )
        self.reg_tenant = Tenant.objects.create(
            name="شاورما الأصالة",
            slug="shawarma-asala",
            is_active=True,
            voice_client_id=102,
        )
        self.owner_profile = UserProfile.objects.create(
            user=self.owner_user,
            tenant=self.reg_tenant,
            role="owner",
            is_platform_admin=False,
        )

        # 3. Regular Cashier Employee
        self.cashier_user = User.objects.create_user(
            username="regular_cashier",
            email="cashier@shawarma.local",
            password="password123"
        )
        self.cashier_profile = UserProfile.objects.create(
            user=self.cashier_user,
            tenant=self.reg_tenant,
            role="cashier",
            is_platform_admin=False,
        )

        # 4. Clean Platform Voice Assistant Config
        PlatformVoiceAssistantConfig.objects.all().delete()
        self.config = PlatformVoiceAssistantConfig.get_config()
        self.config.is_active = True
        self.config.assistant_name = "مستشار مبيعات كُـورَا الافتراضي"
        self.config.voice_name = "Aoede"
        self.config.language = "ar"
        self.config.accent = "saudi"
        self.config.partner_client_id = "49"
        self.config.welcome_message = "أهلاً بك في منصة كُـورَا."
        self.config.landing_profile_id = None
        self.config.save()

    def test_01_platform_hq_tenant_setup_and_knowledge(self):
        """Verify Platform HQ tenant ('منظومة مطاعم HQ') exists with sales knowledge docs and PBX client 49."""
        hq_tenant = get_or_create_platform_hq_tenant()
        self.assertIsNotNone(hq_tenant)
        self.assertEqual(hq_tenant.name, PLATFORM_HQ_NAME)
        self.assertEqual(hq_tenant.slug, PLATFORM_HQ_SLUG)
        self.assertEqual(hq_tenant.voice_client_id, PLATFORM_HQ_CLIENT_ID)
        self.assertTrue(hq_tenant.voice_is_active)
        self.assertTrue(hq_tenant.is_active)

        # Check knowledge documents
        docs = KnowledgeDocument.objects.filter(tenant=hq_tenant)
        self.assertGreaterEqual(docs.count(), 3)
        doc_titles = [d.title for d in docs]
        self.assertTrue(any("Sales & Subscriptions" in t or "باقات الاشتراك" in t for t in doc_titles))

        # Check default branch
        branch = Branch.objects.filter(tenant=hq_tenant, name="المقر الرئيسي").first()
        self.assertIsNotNone(branch)
        self.assertEqual(branch.name, "المقر الرئيسي")

    @patch("core.partner_service.get_profile")
    @patch("core.partner_service.get_studio_metadata")
    def test_02_superadmin_linked_to_platform_hq_in_callcenter(self, mock_studio, mock_prof):
        """Verify superadmin automatically resolves to Platform HQ tenant when visiting persona studio."""
        mock_prof.return_value = {
            "status": "success",
            "profiles": [
                {
                    "id": 260,
                    "name": "مستشار مبيعات المنظومة",
                    "voice_name": "Puck",
                    "is_active": True,
                    "dialect": "saudi",
                    "language": "arabic",
                    "gender": "male",
                    "persona_role": "sales_advisor"
                }
            ]
        }
        mock_studio.return_value = {"status": "success"}

        self.client.force_login(self.super_admin)
        response = self.client.get("/ai-callcenter/persona/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tenant"].slug, PLATFORM_HQ_SLUG)
        self.assertEqual(response.context["tenant"].name, PLATFORM_HQ_NAME)
        self.assertTrue(response.context["is_platform_admin"])

    def test_03_unauthenticated_set_landing_persona_blocked(self):
        """Verify unauthenticated requests cannot access set-landing-persona API."""
        response = self.client.post("/api/ai-callcenter/profiles/260/set-landing-persona/")
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertEqual(data["code"], "unauthorized")

    def test_04_regular_users_strictly_forbidden_403(self):
        """Verify regular restaurant owners and employees receive 403 Forbidden."""
        # 1. Regular Owner
        self.client.force_login(self.owner_user)
        res_owner = self.client.post("/api/ai-callcenter/profiles/260/set-landing-persona/")
        self.assertEqual(res_owner.status_code, 403)
        data_owner = res_owner.json()
        self.assertEqual(data_owner["code"], "forbidden")
        self.assertIn("المشرف العام للمنصة", data_owner["message"])

        # 2. Cashier
        self.client.force_login(self.cashier_user)
        res_cashier = self.client.post("/api/ai-callcenter/profiles/260/set-landing-persona/")
        self.assertEqual(res_cashier.status_code, 403)
        data_cashier = res_cashier.json()
        self.assertEqual(data_cashier["code"], "forbidden")

    @patch("core.partner_service.get_profile")
    @patch("core.partner_service.activate_profile")
    def test_05_superadmin_sets_landing_persona_success(self, mock_activate, mock_prof):
        """Verify superadmin can set a profile as landing persona and updates PlatformVoiceAssistantConfig."""
        mock_prof.return_value = {
            "status": "success",
            "profiles": [
                {
                    "id": 260,
                    "name": "مستشار مبيعات كُـورَا الرسمي",
                    "voice_name": "Fenrir",
                    "welcome_message": "مرحباً بكم في استشارة منصة كُـورَا السحابية المتقدمة.",
                    "system_prompt": "أنت المستشار الرسمي المعتمد للمبيعات وتوضيح باقات الاشتراك.",
                    "language": "arabic",
                    "dialect": "saudi",
                    "is_active": True,
                }
            ]
        }
        mock_activate.return_value = {"status": "success"}

        self.client.force_login(self.super_admin)
        response = self.client.post("/api/ai-callcenter/profiles/260/set-landing-persona/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["profile_id"], 260)

        # Check database persistence
        cfg = PlatformVoiceAssistantConfig.get_config()
        self.assertEqual(cfg.landing_profile_id, 260)
        self.assertEqual(cfg.assistant_name, "مستشار مبيعات كُـورَا الرسمي")
        self.assertEqual(cfg.voice_name, "Fenrir")
        self.assertEqual(cfg.welcome_message, "مرحباً بكم في استشارة منصة كُـورَا السحابية المتقدمة.")
        self.assertEqual(cfg.system_prompt, "أنت المستشار الرسمي المعتمد للمبيعات وتوضيح باقات الاشتراك.")
        self.assertEqual(cfg.language, "ar")
        self.assertEqual(cfg.accent, "saudi")
        self.assertEqual(cfg.partner_client_id, "49")
        self.assertTrue(cfg.is_active)

    @patch("core.partner_service.initiate_webrtc_call")
    def test_06_live_reflection_on_landing_voice_session(self, mock_webrtc):
        """Verify /api/landing/voice-session/ immediately reflects the approved landing persona."""
        mock_webrtc.return_value = {
            "status": "success",
            "call_id": "call_sync_999",
            "room_name": "room_sync_999",
            "livekit_url": "wss://livekit.test.local",
            "livekit_token": "token_mock_sync",
            "max_duration_seconds": 180,
        }

        # Update config directly simulating previous sync
        cfg = PlatformVoiceAssistantConfig.get_config()
        cfg.assistant_name = "مستشار المبيعات الذكي المحدث"
        cfg.voice_name = "Fenrir"
        cfg.welcome_message = "أهلاً وسهلاً بك، كيف أساعدك في اختيار باقة مطعمك اليوم؟"
        cfg.language = "ar"
        cfg.accent = "saudi"
        cfg.partner_client_id = "49"
        cfg.landing_profile_id = 260
        cfg.save()

        # Public guest call to /api/landing/voice-session/
        res = self.client.post("/api/landing/voice-session/", REMOTE_ADDR="198.51.100.222")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["agent_profile"]["name"], "مستشار المبيعات الذكي المحدث")
        self.assertEqual(data["agent_profile"]["voice"], "Fenrir")
        self.assertEqual(data["agent_profile"]["language"], "ar")
        self.assertEqual(data["agent_profile"]["accent"], "saudi")

        # Verify partner service called with updated welcome message and client 49
        mock_webrtc.assert_called_once()
        kwargs = mock_webrtc.call_args.kwargs
        self.assertEqual(kwargs["client_id"], 49)
        self.assertEqual(kwargs["welcome_message"], "أهلاً وسهلاً بك، كيف أساعدك في اختيار باقة مطعمك اليوم؟")

    @patch("core.partner_service.get_profile")
    @patch("core.partner_service.get_studio_metadata")
    def test_07_persona_page_renders_badge_and_button_rbacs(self, mock_studio, mock_prof):
        """Verify UI displays active badge for approved profile and buttons only for superadmin."""
        cfg = PlatformVoiceAssistantConfig.get_config()
        cfg.landing_profile_id = 260
        cfg.save()

        mock_prof.return_value = {
            "status": "success",
            "profiles": [
                {
                    "id": 260,
                    "name": "بروفايل معتمد",
                    "voice_name": "Fenrir",
                    "is_active": True,
                    "dialect": "saudi",
                    "language": "arabic",
                    "gender": "male",
                    "persona_role": "sales_advisor"
                },
                {
                    "id": 132,
                    "name": "بروفايل بديل",
                    "voice_name": "Aoede",
                    "is_active": False,
                    "dialect": "egyptian",
                    "language": "arabic",
                    "gender": "female",
                    "persona_role": "restaurant_orders"
                },
            ]
        }
        mock_studio.return_value = {"status": "success"}

        # 1. Super Admin View: Should see Badge on profile 260 and Action Button on profile 132
        self.client.force_login(self.super_admin)
        res_super = self.client.get("/ai-callcenter/persona/")
        self.assertEqual(res_super.status_code, 200)
        self.assertContains(res_super, "صوت صفحة الهبوط النشط")
        self.assertContains(res_super, "معتمد لصفحة الهبوط")
        self.assertContains(res_super, "اعتماده لصفحة الهبوط")
        self.assertContains(res_super, "btn-set-landing-132")

        # 2. Regular Owner View: Must NOT see "اعتماده لصفحة الهبوط" button
        self.client.force_login(self.owner_user)
        session = self.client.session
        session["active_tenant_id"] = self.reg_tenant.id
        session.save()

        res_owner = self.client.get("/ai-callcenter/persona/")
        self.assertEqual(res_owner.status_code, 200)
        self.assertNotContains(res_owner, "btn-set-landing-132")
        self.assertNotContains(res_owner, "btn-set-landing-260")

    @patch("core.partner_service.get_profile")
    @patch("core.partner_service.activate_profile")
    def test_08_superadmin_with_restaurant_profile_still_binds_platform_hq(self, mock_activate, mock_prof):
        """
        Verify that a superadmin whose user profile is associated with a restaurant
        still resolves to Platform HQ (client 49) when managing landing persona.
        """
        # Superadmin user whose profile points to reg_tenant (e.g. seed 'admin' user)
        admin_with_tenant = User.objects.create_superuser(
            username="admin_with_tenant",
            email="admin_tenant@motaem.local",
            password="adminpassword123"
        )
        UserProfile.objects.create(
            user=admin_with_tenant,
            role="owner",
            tenant=self.reg_tenant,
            is_platform_admin=False,
        )

        mock_prof.side_effect = lambda cid: {
            "status": "success",
            "profiles": [
                {
                    "id": 260,
                    "name": "مستشار المبيعات الرسمي",
                    "voice_name": "Fenrir",
                    "welcome_message": "مرحباً بكم في منصة كورا HQ.",
                    "system_prompt": "أنت المستشار الرسمي للمبيعات.",
                    "language": "arabic",
                    "dialect": "saudi",
                    "is_active": True,
                }
            ]
        } if cid == 49 else {
            "status": "success",
            "profiles": [
                {
                    "id": 88,
                    "name": "كاشير مطعم الشاورما",
                    "voice_name": "Aoede",
                    "welcome_message": "أهلاً بك في مطعم الشاورما.",
                    "language": "arabic",
                    "dialect": "saudi",
                    "is_active": True,
                }
            ]
        }
        mock_activate.return_value = {"status": "success"}

        self.client.force_login(admin_with_tenant)
        response = self.client.post("/api/ai-callcenter/profiles/260/set-landing-persona/")
        self.assertEqual(response.status_code, 200)

        cfg = PlatformVoiceAssistantConfig.get_config()
        # Must be Platform HQ client 49, NOT self.reg_tenant (102)
        self.assertEqual(cfg.partner_client_id, "49")
        self.assertEqual(cfg.landing_profile_id, 260)
        self.assertEqual(cfg.assistant_name, "مستشار المبيعات الرسمي")

    @patch("core.partner_service.get_profile")
    @patch("core.partner_service.activate_profile")
    def test_09_superadmin_switched_tenant_in_session_binds_switched_client(self, mock_activate, mock_prof):
        """
        Verify that when a superadmin explicitly switches tenant via active_tenant_id session,
        they can approve a persona from that switched tenant.
        """
        mock_prof.return_value = {
            "status": "success",
            "profiles": [
                {
                    "id": 999,
                    "name": "مساعد صوتي مخصص لفرع الشاورما",
                    "voice_name": "Aoede",
                    "welcome_message": "مرحباً بكم في شاورما الأصالة.",
                    "system_prompt": "أنت كول سنتر الشاورما.",
                    "language": "arabic",
                    "dialect": "saudi",
                    "is_active": True,
                }
            ]
        }
        mock_activate.return_value = {"status": "success"}

        self.client.force_login(self.super_admin)
        session = self.client.session
        session["active_tenant_id"] = self.reg_tenant.id
        session.save()

        response = self.client.post("/api/ai-callcenter/profiles/999/set-landing-persona/")
        self.assertEqual(response.status_code, 200)

        cfg = PlatformVoiceAssistantConfig.get_config()
        self.assertEqual(cfg.partner_client_id, str(self.reg_tenant.voice_client_id))
        self.assertEqual(cfg.landing_profile_id, 999)

    @patch("core.partner_service.get_profile")
    @patch("core.partner_service.activate_profile")
    def test_10_empty_welcome_or_prompt_fallback(self, mock_activate, mock_prof):
        """Verify profile with empty welcome message preserves existing defaults."""
        mock_prof.return_value = {
            "status": "success",
            "profiles": [
                {
                    "id": 260,
                    "name": "مساعد صوتي باسم جديد",
                    "voice_name": "Puck",
                    "welcome_message": "",
                    "system_prompt": "",
                    "language": "arabic",
                    "dialect": "saudi",
                }
            ]
        }
        mock_activate.return_value = {"status": "success"}

        cfg_before = PlatformVoiceAssistantConfig.get_config()
        default_welcome = cfg_before.welcome_message
        default_prompt = cfg_before.system_prompt

        self.client.force_login(self.super_admin)
        res = self.client.post("/api/ai-callcenter/profiles/260/set-landing-persona/")
        self.assertEqual(res.status_code, 200)

        cfg_after = PlatformVoiceAssistantConfig.get_config()
        self.assertEqual(cfg_after.assistant_name, "مساعد صوتي باسم جديد")
        self.assertEqual(cfg_after.voice_name, "Puck")
        self.assertEqual(cfg_after.welcome_message, default_welcome)
        self.assertEqual(cfg_after.system_prompt, default_prompt)

    @patch("core.partner_service.get_profile")
    @patch("core.partner_service.get_studio_metadata")
    def test_11_string_profile_id_template_badge(self, mock_studio, mock_prof):
        """Verify template renders active badge properly even when profile id is returned as string."""
        cfg = PlatformVoiceAssistantConfig.get_config()
        cfg.landing_profile_id = 260
        cfg.save()

        # String ID returned by partner PBX
        mock_prof.return_value = {
            "status": "success",
            "profiles": [
                {
                    "id": "260",
                    "name": "بروفايل معتمد بمعرف نصي",
                    "voice_name": "Fenrir",
                    "is_active": True,
                    "dialect": "saudi",
                    "language": "arabic",
                }
            ]
        }
        mock_studio.return_value = {"status": "success"}

        self.client.force_login(self.super_admin)
        res = self.client.get("/ai-callcenter/persona/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "صوت صفحة الهبوط النشط")
        self.assertContains(res, "معتمد لصفحة الهبوط")
