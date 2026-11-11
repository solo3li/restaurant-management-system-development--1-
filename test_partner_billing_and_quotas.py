"""
Tests for Partner Billing, Message & Character Quotas, Wholesale/Retail Rate Management,
and Call Center Live Quota Trackers.
"""
import json
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth.models import User
from apps.tenants.models import Tenant
from apps.billing.models import SubscriptionPlan
import core.partner_service as ps


class PartnerBillingAndQuotasTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username="admin_test", email="admin@test.local", password="password123"
        )
        self.regular_user = User.objects.create_user(
            username="regular_test", email="regular@test.local", password="password123"
        )

        self.plan_starter = SubscriptionPlan.objects.create(
            name="باقة البداية",
            code="test_starter",
            price_monthly=29.00,
            monthly_voice_minutes=150,
            monthly_messages_quota=500,
            monthly_chars_quota=25000,
            spending_cap=15.00,
            features=["call_center", "pos"],
        )
        self.plan_pro = SubscriptionPlan.objects.create(
            name="باقة المحترفين",
            code="test_pro",
            price_monthly=99.00,
            monthly_voice_minutes=500,
            monthly_messages_quota=2500,
            monthly_chars_quota=125000,
            spending_cap=40.00,
            features=["call_center", "pos"],
        )

        self.tenant = Tenant.objects.create(
            name="مطعم البيت السعيد",
            slug="happy-home-rest",
            subscription_plan=self.plan_pro,
            voice_client_id=49,
            voice_username="prt_10_happy",
            voice_password="Pass_123!",
            is_active=True,
        )

    # 1. SubscriptionPlan Model & DB Fields
    def test_subscription_plan_model_fields(self):
        plan = self.plan_pro
        self.assertEqual(plan.monthly_voice_minutes, 500)
        self.assertEqual(plan.monthly_messages_quota, 2500)
        self.assertEqual(plan.monthly_chars_quota, 125000)
        self.assertEqual(float(plan.spending_cap), 40.00)

    # 2. get_plan_voice_caps with direct Model instance and fallback
    def test_get_plan_voice_caps_from_model(self):
        caps = ps.get_plan_voice_caps(self.plan_pro)
        self.assertEqual(caps["minute_cap"], 500)
        self.assertEqual(caps["message_cap"], 2500)
        self.assertEqual(caps["message_char_cap"], 125000)
        self.assertEqual(caps["spending_cap"], 40.0)

    def test_get_plan_voice_caps_from_tenant(self):
        caps = ps.get_plan_voice_caps(self.tenant)
        self.assertEqual(caps["minute_cap"], 500)
        self.assertEqual(caps["message_cap"], 2500)
        self.assertEqual(caps["message_char_cap"], 125000)

    def test_get_plan_voice_caps_fallback_string(self):
        trial_caps = ps.get_plan_voice_caps("trial")
        self.assertEqual(trial_caps["minute_cap"], 50)
        self.assertEqual(trial_caps["message_cap"], 200)
        self.assertEqual(trial_caps["message_char_cap"], 10000)
        self.assertEqual(trial_caps["spending_cap"], 5.0)

        ent_caps = ps.get_plan_voice_caps("enterprise")
        self.assertEqual(ent_caps["minute_cap"], 1500)
        self.assertEqual(ent_caps["message_cap"], 10000)
        self.assertEqual(ent_caps["message_char_cap"], 500000)
        self.assertEqual(ent_caps["spending_cap"], 100.0)

    # 3. update_client_cap payload structure
    @patch("core.partner_service._request")
    def test_update_client_cap_payload(self, mock_request):
        mock_request.return_value = {"status": "success"}
        resp = ps.update_client_cap(
            client_id=123,
            minute_cap=500,
            spending_cap=40.0,
            message_cap=2500,
            message_char_cap=125000,
            is_active=True,
        )
        self.assertEqual(resp["status"], "success")
        mock_request.assert_called_once_with(
            "/clients/123/cap/",
            method="POST",
            data={
                "client_id": 123,
                "minute_cap": 500,
                "spending_cap": 40.0,
                "message_cap": 2500,
                "message_char_cap": 125000,
                "is_active": True,
            },
        )

    # 4. register_sub_client payload structure
    @patch("core.partner_service._request")
    def test_register_sub_client_payload(self, mock_request):
        mock_request.return_value = {"status": "success", "client_id": 789}
        resp = ps.register_sub_client(
            name="برجر جديد",
            external_reference="new-burger",
            email="burger@test.local",
            spending_cap=40.0,
            minute_cap=500,
            message_cap=2500,
            message_char_cap=125000,
        )
        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["client_id"], 789)
        call_args = mock_request.call_args[1]
        self.assertEqual(call_args["data"]["message_cap"], 2500)
        self.assertEqual(call_args["data"]["message_char_cap"], 125000)

    # 5. sync_tenant_voice_caps integration
    @patch("core.partner_service._request")
    def test_sync_tenant_voice_caps(self, mock_request):
        mock_request.return_value = {"status": "success"}
        res = ps.sync_tenant_voice_caps(self.tenant, reset_to_plan=True)
        self.assertEqual(res["status"], "success")
        mock_request.assert_called_once_with(
            "/clients/49/cap/",
            method="POST",
            data={
                "client_id": 49,
                "minute_cap": 500,
                "spending_cap": 40.0,
                "message_cap": 2500,
                "message_char_cap": 125000,
                "is_active": True,
            },
        )

    # 6. get_partner_settings and update_partner_settings
    @patch("core.partner_service._request")
    def test_partner_settings_methods(self, mock_request):
        mock_request.return_value = {
            "status": "success",
            "settings": {"retail_rate_per_minute": 0.05, "retail_rate_per_1k_chars": 0.015},
        }
        res_get = ps.get_partner_settings()
        self.assertEqual(res_get["status"], "success")
        mock_request.assert_called_with("/settings/")

        ps.update_partner_settings(retail_rate_per_minute=0.06, retail_rate_per_1k_chars=0.018)
        mock_request.assert_called_with(
            "/settings/",
            method="POST",
            data={"retail_rate_per_minute": 0.06, "retail_rate_per_1k_chars": 0.018},
        )

    # 7. api_ai_callcenter_usage returns full message & character quotas
    @patch("core.partner_service.get_client_usage")
    def test_api_ai_callcenter_usage_payload(self, mock_usage):
        mock_usage.return_value = {
            "status": "success",
            "client": {
                "id": 49,
                "total_minutes": 120,
                "minute_cap": 500,
                "total_messages": 350,
                "message_cap": 2500,
                "total_message_chars": 17500,
                "message_char_cap": 125000,
                "spending_cap": 40.0,
                "total_spent": 4.10,
                "retail_revenue": 8.50,
                "estimated_profit": 4.40,
                "is_active": True,
            },
        }

        self.client.force_login(self.admin_user)
        # Bind session to tenant
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session.save()

        response = self.client.get("/api/ai-callcenter/usage/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["total_minutes"], 120)
        self.assertEqual(data["remaining_minutes"], 380)
        self.assertEqual(data["minute_percent"], 24.0)

        self.assertEqual(data["total_messages"], 350)
        self.assertEqual(data["message_cap"], 2500)
        self.assertEqual(data["remaining_messages"], 2150)
        self.assertEqual(data["message_percent"], 14.0)

        self.assertEqual(data["total_message_chars"], 17500)
        self.assertEqual(data["message_char_cap"], 125000)
        self.assertEqual(data["remaining_message_chars"], 107500)
        self.assertEqual(data["char_percent"], 14.0)

        self.assertEqual(data["retail_revenue"], 8.50)
        self.assertEqual(data["estimated_profit"], 4.40)

    # 8. Admin Partner Rates & Wallet endpoints RBAC & Handling
    def test_admin_rates_endpoints_rbac(self):
        # Unauthenticated -> redirect or 302
        res = self.client.get("/api/landing-assistant/rates/")
        self.assertIn(res.status_code, [302, 403])

        # Regular user -> 403
        self.client.force_login(self.regular_user)
        res = self.client.get("/api/landing-assistant/rates/")
        self.assertEqual(res.status_code, 403)

        res_post = self.client.post("/api/landing-assistant/rates/update/", {})
        self.assertEqual(res_post.status_code, 403)

        res_wal = self.client.get("/api/landing-assistant/wallet/")
        self.assertEqual(res_wal.status_code, 403)

    @patch("core.partner_service.get_partner_settings")
    @patch("core.partner_service.update_partner_settings")
    @patch("core.partner_service.get_partner_wallet")
    def test_admin_rates_endpoints_success(self, mock_wallet, mock_update, mock_settings):
        mock_settings.return_value = {"status": "success", "settings": {"retail_rate_per_minute": 0.05}}
        mock_update.return_value = {"status": "success", "message": "Updated"}
        mock_wallet.return_value = {"status": "success", "wallet": {"balance": 150.0}}

        self.client.force_login(self.admin_user)

        res_get = self.client.get("/api/landing-assistant/rates/")
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.json()["status"], "success")

        res_upd = self.client.post(
            "/api/landing-assistant/rates/update/",
            data=json.dumps({"retail_rate_per_minute": 0.06, "retail_rate_per_1k_chars": 0.018}),
            content_type="application/json",
        )
        self.assertEqual(res_upd.status_code, 200)
        mock_update.assert_called_once_with(
            retail_rate_per_minute=0.06,
            retail_rate_per_1k_chars=0.018,
            webhook_url=None,
        )

        res_wal = self.client.get("/api/landing-assistant/wallet/")
        self.assertEqual(res_wal.status_code, 200)
        self.assertEqual(res_wal.json()["wallet"]["balance"], 150.0)

    # 9. Template DOM Verification
    def test_call_center_template_dual_quota_dom(self):
        from django.template.loader import render_to_string
        rendered = render_to_string("call_center.html", {
            "tenant": self.tenant,
            "active_tab": "pos",
            "categories": [{"id": "all", "name": "الكل", "is_all": True}],
            "menu_items": [],
            "recent_orders": [],
            "branches": [],
            "delivery_areas": [],
            "tenant_currency_symbol": "ر.س",
            "branch_currency_symbol": "ر.س",
            "callcenter_embed_url": "https://example.com/embed/cc",
            "chathub_embed_url": "https://example.com/embed/hub",
            "partner_client_id": 49,
            "embed_locale": "ar",
            "partner_embed_token": "token123",
        })
        self.assertIn("main-tab-btn-pos", rendered)
        self.assertIn("main-tab-btn-callcenter", rendered)
        self.assertIn("main-tab-btn-chathub", rendered)
        self.assertIn("quota-mins-bar", rendered)
        self.assertIn("quota-msgs-bar", rendered)
        self.assertIn("quota-chars-used", rendered)
        self.assertIn("fetchCallCenterQuotas", rendered)

    def test_admin_change_form_partner_pricing_dom(self):
        from apps.callcenter.models import PlatformVoiceAssistantConfig
        config = PlatformVoiceAssistantConfig.get_config()
        self.client.force_login(self.admin_user)
        resp = self.client.get(f"/admin/core/platformvoiceassistantconfig/{config.pk}/change/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")

        self.assertIn("partner-wallet-balance", html)
        self.assertIn("wholesale-rate-min", html)
        self.assertIn("wholesale-rate-char", html)
        self.assertIn("input-retail-min", html)
        self.assertIn("input-retail-char", html)
        self.assertIn("btn-save-partner-rates", html)
        self.assertIn("fetchPartnerWalletAndRates", html)
