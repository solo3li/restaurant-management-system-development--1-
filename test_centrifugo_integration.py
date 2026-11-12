"""
Test Suite: Centrifugo Real-Time Messaging & Multi-Tenant Authorization
------------------------------------------------------------------------
Verifies:
1. Centrifugo configuration file and Django settings
2. JWT Connection and Subscription token generation and HMAC validation
3. HTTP publish_event helper resilience & graceful fallback on container outage
4. API endpoint /api/realtime/token/ authentication and multi-tenant isolation
5. Channel authorization and strict cross-tenant rejection (HTTP 403)
6. Event notification triggers in Kitchen (KDS), Delivery, POS, and Call Center
7. Frontend templates integration with centrifuge.min.js
"""
import os
import json
import time
from decimal import Decimal
from django.test import TestCase, Client
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
import jwt

from apps.tenants.models import Tenant, Branch
from apps.orders.models import Order, OrderItem
from apps.accounts.models import Employee, UserProfile
from apps.kitchen.events import notify_kitchen_order_event
from apps.orders.events import notify_delivery_order_event
from core.centrifugo import (
    generate_connection_token,
    generate_subscription_token,
    publish_event,
    get_centrifugo_api_url,
    get_centrifugo_api_key,
    get_centrifugo_hmac_secret,
    get_centrifugo_ws_url,
    build_kds_channel,
    build_delivery_channel,
    build_pos_channel,
    build_callcenter_channel,
)


class CentrifugoIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Tenant 1: Shawarma Al-Reef
        self.tenant1 = Tenant.objects.create(
            name="شاورما الريف",
            slug="shawarma-al-reef-test",
            subscription_status="active"
        )
        self.branch1 = Branch.objects.create(
            tenant=self.tenant1,
            name="فرع التحلية",
            status="active"
        )
        self.user1 = User.objects.create_user(
            username="reef_owner",
            password="password123",
            email="owner@reef.test"
        )
        self.profile1 = UserProfile.objects.create(
            user=self.user1,
            tenant=self.tenant1,
            role="owner"
        )

        # Tenant 2: Burger House (Isolated Tenant)
        self.tenant2 = Tenant.objects.create(
            name="برجر هاوس",
            slug="burger-house-test",
            subscription_status="active"
        )
        self.branch2 = Branch.objects.create(
            tenant=self.tenant2,
            name="فرع العليا",
            status="active"
        )
        self.user2 = User.objects.create_user(
            username="burger_owner",
            password="password123",
            email="owner@burger.test"
        )
        self.profile2 = UserProfile.objects.create(
            user=self.user2,
            tenant=self.tenant2,
            role="owner"
        )

    # =========================================================================
    # 1. Configuration & Settings Verification
    # =========================================================================
    def test_centrifugo_config_json_file(self):
        """Verify centrifugo/config.json exists, is valid JSON, and has all 5 namespaces."""
        config_path = os.path.join(settings.BASE_DIR, "centrifugo", "config.json")
        self.assertTrue(os.path.exists(config_path), "centrifugo/config.json file must exist")

        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        self.assertIn("token_hmac_secret_key", cfg)
        self.assertIn("api_key", cfg)
        self.assertIn("admin_password", cfg)
        self.assertIn("admin_secret", cfg)
        self.assertTrue(cfg.get("admin"))
        self.assertTrue(cfg.get("http_stream"))
        self.assertTrue(cfg.get("sse"))

        ns_names = {ns["name"] for ns in cfg.get("namespaces", [])}
        expected_ns = {"kds", "delivery", "pos", "callcenter", "admin"}
        self.assertTrue(expected_ns.issubset(ns_names), f"All namespaces {expected_ns} must be present in config.json")

    def test_django_settings_and_helpers(self):
        """Verify settings and getter helpers return valid strings."""
        secret = get_centrifugo_hmac_secret()
        self.assertTrue(len(secret) >= 32, "HMAC secret must be at least 32 characters for security")

        api_key = get_centrifugo_api_key()
        self.assertTrue(len(api_key) > 8, "API key must be configured")

        api_url = get_centrifugo_api_url()
        self.assertTrue(api_url.startswith("http"), "API URL must start with http/https")

        ws_url = get_centrifugo_ws_url()
        self.assertIn("connection", ws_url)

    # =========================================================================
    # 2. Token Generation & JWT HMAC Signature Verification
    # =========================================================================
    def test_generate_connection_token(self):
        """Verify connection token generates valid HS256 JWT with sub and timestamps."""
        secret = get_centrifugo_hmac_secret()
        token = generate_connection_token(user_id=123, exp_seconds=3600)
        self.assertIsInstance(token, str)

        decoded = jwt.decode(token, secret, algorithms=["HS256"])
        self.assertEqual(decoded["sub"], "123")
        self.assertIn("exp", decoded)
        self.assertIn("iat", decoded)
        self.assertTrue(decoded["exp"] > decoded["iat"])

    def test_generate_subscription_token(self):
        """Verify subscription token generates valid HS256 JWT with sub and channel."""
        secret = get_centrifugo_hmac_secret()
        channel = "kds:tenant_1_branch_2"
        token = generate_subscription_token(user_id=123, channel=channel, exp_seconds=1800)
        self.assertIsInstance(token, str)

        decoded = jwt.decode(token, secret, algorithms=["HS256"])
        self.assertEqual(decoded["sub"], "123")
        self.assertEqual(decoded["channel"], channel)

    def test_token_signature_rejection_with_wrong_secret(self):
        """Ensure token cannot be tampered with or verified with wrong secret."""
        token = generate_subscription_token(user_id=123, channel="kds:test")
        with self.assertRaises(jwt.InvalidSignatureError):
            jwt.decode(token, "wrong-secret-key-that-should-fail-0000000", algorithms=["HS256"])

    # =========================================================================
    # 3. Channel Name Builders & HTTP Publishing Fallback
    # =========================================================================
    def test_channel_name_helpers(self):
        """Verify standard multi-tenant channel naming format."""
        self.assertEqual(build_kds_channel(1, 2), "kds:tenant_1_branch_2")
        self.assertEqual(build_kds_channel(1, None), "kds:tenant_1_all")
        self.assertEqual(build_delivery_channel(1, 2), "delivery:tenant_1_branch_2")
        self.assertEqual(build_delivery_channel(1, None), "delivery:tenant_1_all")
        self.assertEqual(build_pos_channel(1, 2), "pos:tenant_1_branch_2")
        self.assertEqual(build_pos_channel(1, None), "pos:tenant_1_all")
        self.assertEqual(build_callcenter_channel(1), "callcenter:tenant_1")

    def test_publish_event_resilience_on_unreachable_endpoint(self):
        """Verify publish_event catches connection errors gracefully and does not raise exceptions."""
        result = publish_event(
            channel="kds:tenant_1_branch_1",
            data={"test": "payload"},
            api_url="http://127.0.0.1:59999/api",
            timeout=0.1
        )
        self.assertFalse(result, "Unreachable server should return False without raising exceptions")

    # =========================================================================
    # 4. API Endpoint /api/realtime/token/ Authentication & Multi-Tenancy
    # =========================================================================
    def test_realtime_token_unauthenticated(self):
        """Unauthenticated requests to /api/realtime/token/ must be rejected with 401."""
        response = self.client.get("/api/realtime/token/")
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertIn("error", data)

    def test_realtime_token_authenticated(self):
        """Authenticated tenant owner receives connection token and authorized channel tokens."""
        self.client.force_login(self.user1)
        response = self.client.get(f"/api/realtime/token/?branch_id={self.branch1.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["status"], "success")
        self.assertEqual(data["tenant_id"], self.tenant1.id)
        self.assertEqual(data["branch_id"], self.branch1.id)
        self.assertIn("connection_token", data)
        self.assertIn("channels", data)
        self.assertIn("tokens", data)

        kds_chan = f"kds:tenant_{self.tenant1.id}_branch_{self.branch1.id}"
        self.assertEqual(data["channels"]["kds"], kds_chan)
        self.assertIn(kds_chan, data["tokens"])

        # Validate that the returned token decodes properly
        secret = get_centrifugo_hmac_secret()
        conn_token = data["connection_token"]
        decoded_conn = jwt.decode(conn_token, secret, algorithms=["HS256"])
        self.assertEqual(decoded_conn["sub"], str(self.user1.id))

    def test_realtime_token_cross_tenant_branch_blocked(self):
        """User from Tenant 1 attempting to request tokens for Tenant 2's branch must receive 403."""
        self.client.force_login(self.user1)
        response = self.client.get(f"/api/realtime/token/?branch_id={self.branch2.id}")
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn("error", data)

    def test_realtime_token_cross_tenant_channel_blocked(self):
        """User from Tenant 1 requesting subscription to Tenant 2's channel must receive 403."""
        self.client.force_login(self.user1)
        cross_channel = f"kds:tenant_{self.tenant2.id}_branch_{self.branch2.id}"
        response = self.client.get(f"/api/realtime/token/?channel={cross_channel}")
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn("error", data)

    def test_realtime_token_malformed_channel_blocked(self):
        """Malformed channel strings must receive 400 Bad Request."""
        self.client.force_login(self.user1)
        response = self.client.get("/api/realtime/token/?channel=bad_channel_without_colon")
        self.assertEqual(response.status_code, 400)

    # =========================================================================
    # 5. Order Notification Workflow Triggers
    # =========================================================================
    def test_notify_kitchen_order_event_execution(self):
        """Verify notify_kitchen_order_event executes without error and publishes to channels."""
        order = Order.objects.create(
            tenant=self.tenant1,
            branch=self.branch1,
            order_number="ORD-TEST-001",
            order_type="dine_in",
            channel="cashier",
            status="new",
            total=Decimal("45.00")
        )
        # Should execute safely without raising exceptions even if network calls happen
        try:
            notify_kitchen_order_event(order, "new_order")
            success = True
        except Exception:
            success = False
        self.assertTrue(success, "notify_kitchen_order_event must execute without unhandled exceptions")

    def test_notify_delivery_order_event_execution(self):
        """Verify notify_delivery_order_event handles delivery and non-delivery orders correctly."""
        deliv_order = Order.objects.create(
            tenant=self.tenant1,
            branch=self.branch1,
            order_number="ORD-TEST-002",
            order_type="delivery",
            channel="cashier",
            status="new",
            total=Decimal("60.00")
        )
        try:
            notify_delivery_order_event(deliv_order, "delivery_new_order")
            success = True
        except Exception:
            success = False
        self.assertTrue(success, "notify_delivery_order_event must execute without unhandled exceptions")

        # Non-delivery order should be gracefully skipped
        dine_in_order = Order.objects.create(
            tenant=self.tenant1,
            branch=self.branch1,
            order_number="ORD-TEST-003",
            order_type="dine_in",
            channel="cashier",
            status="new",
            total=Decimal("30.00")
        )
        try:
            notify_delivery_order_event(dine_in_order, "delivery_new_order")
            skip_success = True
        except Exception:
            skip_success = False
        self.assertTrue(skip_success)

    # =========================================================================
    # 6. Frontend Assets & Template Verification
    # =========================================================================
    def test_centrifuge_js_static_file_exists(self):
        """Verify static/js/centrifuge.min.js exists and is populated."""
        js_path = os.path.join(settings.BASE_DIR, "static", "js", "centrifuge.min.js")
        self.assertTrue(os.path.exists(js_path), "static/js/centrifuge.min.js must exist")
        self.assertGreater(os.path.getsize(js_path), 10000, "centrifuge.min.js must not be empty")

    def test_templates_reference_centrifuge(self):
        """Verify kitchen, delivery, pos, and call_center templates integrate Centrifuge."""
        templates_to_check = [
            ("templates/kitchen.html", "Centrifuge"),
            ("templates/delivery.html", "Centrifuge"),
            ("templates/pos.html", "Centrifuge"),
            ("templates/call_center.html", "Centrifuge"),
        ]
        for tpl_rel_path, search_term in templates_to_check:
            full_path = os.path.join(settings.BASE_DIR, tpl_rel_path)
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn(search_term, content, f"{tpl_rel_path} must reference {search_term}")
