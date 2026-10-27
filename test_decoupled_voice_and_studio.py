"""
Unit & Integration Test Suite:
1. PlatformVoiceAssistantConfig Singleton & Django Admin
2. Public Landing WebRTC API (/api/webrtc/session/ & /api/landing/voice-session/) with IP Rate Limiting
3. Internal Authenticated Persona WebRTC Studio (/api/ai-callcenter/calls/webrtc/)
4. Call Center Menu Items & Empty State Handling
"""

import os
import json
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from apps.callcenter.models import PlatformVoiceAssistantConfig
from apps.tenants.models import Tenant, Branch
from apps.accounts.models import UserProfile
from apps.menu.models import MenuCategory, MenuItem

User = get_user_model()


class DecoupledVoiceAssistantTestSuite(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

        # 1. Platform Super Admin
        self.admin_user = User.objects.create_superuser(
            username="test_superadmin",
            email="superadmin@test.local",
            password="adminpassword123"
        )

        # 2. Restaurant Owner & Tenant
        self.owner_user = User.objects.create_user(
            username="test_owner",
            email="owner@test.local",
            password="password123"
        )
        self.tenant = Tenant.objects.create(
            name="مطعم الاختبار الإيطالي",
            slug="test-italian-rest",
            is_active=True
        )
        self.branch = Branch.objects.create(
            tenant=self.tenant,
            name="الفرع الرئيسي",
            status="active"
        )
        self.owner_profile = UserProfile.objects.create(
            user=self.owner_user,
            tenant=self.tenant,
            role="owner"
        )

        # 3. Ensure clean config
        PlatformVoiceAssistantConfig.objects.all().delete()
        self.config = PlatformVoiceAssistantConfig.get_config()
        self.config.is_active = True
        self.config.max_daily_calls_per_ip = 3
        self.config.max_call_duration_seconds = 180
        self.config.save()

    def test_01_platform_voice_config_singleton(self):
        """Test singleton behavior and defaults of PlatformVoiceAssistantConfig."""
        config1 = PlatformVoiceAssistantConfig.get_config()
        self.assertEqual(config1.id, 1)
        self.assertTrue(config1.is_active)
        self.assertEqual(config1.max_daily_calls_per_ip, 3)
        self.assertEqual(config1.max_call_duration_seconds, 180)

        # Attempt to create another instance must enforce singleton
        new_obj = PlatformVoiceAssistantConfig(id=99, assistant_name="مساعد بديل")
        new_obj.save()
        self.assertEqual(new_obj.id, 1)
        self.assertEqual(PlatformVoiceAssistantConfig.objects.count(), 1)

    @patch("core.partner_service.initiate_webrtc_call")
    def test_02_guest_landing_webrtc_session_success(self, mock_webrtc):
        """Test public guest access to landing page voice assistant without login."""
        mock_webrtc.return_value = {
            "status": "success",
            "call_id": "call_12345",
            "room_name": "room_landing_test",
            "livekit_url": "wss://livekit.test.local",
            "livekit_token": "mock_jwt_token_landing",
            "max_duration_seconds": 180,
        }

        # Guest (unauthenticated) POST to /api/webrtc/session/
        response = self.client.post("/api/webrtc/session/", REMOTE_ADDR="198.51.100.1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["room_name"], "room_landing_test")
        self.assertEqual(data["remaining_calls_today"], 2)  # 3 - 1 = 2 remaining

        # Verify partner service called with platform settings
        mock_webrtc.assert_called_once()
        kwargs = mock_webrtc.call_args.kwargs
        self.assertEqual(kwargs["max_duration_seconds"], 180)

    @patch("core.partner_service.initiate_webrtc_call")
    def test_03_guest_ip_rate_limiting(self, mock_webrtc):
        """Test strict daily IP rate limit (3 calls per day)."""
        mock_webrtc.return_value = {
            "status": "success",
            "call_id": "call_test",
            "room_name": "room_test",
            "livekit_url": "wss://livekit.test.local",
            "livekit_token": "token",
        }

        test_ip = "203.0.113.42"

        # Call 1: Allowed
        r1 = self.client.post("/api/webrtc/session/", REMOTE_ADDR=test_ip)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["remaining_calls_today"], 2)

        # Call 2: Allowed
        r2 = self.client.post("/api/webrtc/session/", REMOTE_ADDR=test_ip)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["remaining_calls_today"], 1)

        # Call 3: Allowed
        r3 = self.client.post("/api/webrtc/session/", REMOTE_ADDR=test_ip)
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()["remaining_calls_today"], 0)

        # Call 4: Blocked with HTTP 429
        r4 = self.client.post("/api/webrtc/session/", REMOTE_ADDR=test_ip)
        self.assertEqual(r4.status_code, 429)
        self.assertEqual(r4.json()["code"], "daily_limit_reached")

    def test_04_landing_disabled_assistant(self):
        """Test 403 response when platform voice assistant is disabled."""
        self.config.is_active = False
        self.config.save()

        response = self.client.post("/api/webrtc/session/", REMOTE_ADDR="198.51.100.99")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "assistant_disabled")

    def test_05_internal_persona_webrtc_requires_auth(self):
        """Test that /api/ai-callcenter/calls/webrtc/ is strictly protected by @login_required."""
        response = self.client.post("/api/ai-callcenter/calls/webrtc/")
        # Expect redirect to login (HTTP 302)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    @patch("core.partner_service.initiate_webrtc_call")
    def test_06_internal_persona_webrtc_authenticated(self, mock_webrtc):
        """Test authenticated restaurant owner initiating live testing in Persona studio."""
        mock_webrtc.return_value = {
            "status": "success",
            "call_id": "call_internal_999",
            "room_name": "room_tenant_test",
            "livekit_url": "wss://livekit.test.local",
            "livekit_token": "mock_jwt_internal",
            "max_duration_seconds": 300,
        }

        self.client.force_login(self.owner_user)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session.save()

        response = self.client.post(
            "/api/ai-callcenter/calls/webrtc/",
            data=json.dumps({"profile_id": "1"}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["restaurant_name"], self.tenant.name)

    def test_07_call_center_view_empty_state_and_with_items(self):
        """Test call center view renders smoothly with and without menu items."""
        self.client.force_login(self.owner_user)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session.save()

        # 1. Empty state: 0 items
        res_empty = self.client.get("/call-center/")
        self.assertEqual(res_empty.status_code, 200)
        self.assertContains(res_empty, "قائمة الطعام فارغة حالياً")

        # 2. Add an item
        cat = MenuCategory.objects.create(tenant=self.tenant, name="بيتزا", ordering=1)
        MenuItem.objects.create(
            tenant=self.tenant,
            name="بيتزا مارجريتا تيست",
            category="بيتزا",
            category_rel=cat,
            price=45.00,
            available=True,
            is_active=True
        )

        res_items = self.client.get("/call-center/")
        self.assertEqual(res_items.status_code, 200)
        self.assertContains(res_items, "بيتزا مارجريتا تيست")
