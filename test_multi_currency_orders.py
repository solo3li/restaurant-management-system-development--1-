"""
Unit & Integration Test Suite for End-to-End Multi-Currency Architecture:
- Financial Immutability & Persistence (POS, Call Center, QR Menu, FastMCP)
- Revenue Disaggregation & Grouping in HQ Orders and Dashboard
- Real-time SSE Serializers (KDS, Delivery Fleet)
- Dynamic Branch Switching & Branch Menu Custom Prices Context
- Audit Log Currency Symbol Formatting
- Legacy Backfill and Fallback Defaults
"""
import os
import json
import secrets
from decimal import Decimal
from datetime import timedelta

import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test.utils import setup_test_environment
setup_test_environment()

from django.test import Client, TestCase
from django.utils import timezone
from django.contrib.auth.models import User

from core.models import (
    Tenant, Branch, Order, OrderItem, MenuItem, Customer,
    DeliveryArea, TenantApiKey
)
from apps.audit.models import AuditLog
from apps.accounts.models import UserProfile, JobRole
from apps.menu.models import BranchMenuAvailability
from apps.kitchen.events import serialize_kitchen_order
from apps.orders.events import serialize_delivery_order
from core.mcp.tools import create_callcenter_order as mcp_create_order, create_order as mcp_create_order_alias
from core.i18n_catalog import get_translation


from unittest.mock import patch


class MultiCurrencyOrderTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Prevent SQLite connection closing inside TestCase
        for mod in ["django.db", "core.mcp.tools", "core.mcp.middleware", "core.mcp.cart"]:
            p = patch(f"{mod}.close_old_connections")
            p.start()
            self.addCleanup(p.stop)

        # Mock external partner service calls
        self.partner_patcher = patch("core.partner_service._request", return_value={"status": "success", "client_id": 123})
        self.partner_patcher.start()
        self.addCleanup(self.partner_patcher.stop)

        # 1. Multi-Branch Multi-Currency Setup
        self.tenant = Tenant.objects.create(
            name="مجموعة مطاعم العالمية",
            slug=f"global-dining-{secrets.token_hex(4)}",
            subscription_status="active",
            plan="enterprise",
            default_currency="SAR",
            voice_client_id=123
        )

        # Branch 1: Saudi Arabia (SAR / ر.س)
        self.branch_sa = Branch.objects.create(
            tenant=self.tenant,
            name="فرع الرياض - التحلية",
            currency="SAR",
            status="active"
        )

        # Branch 2: Egypt (EGP / ج.م)
        self.branch_eg = Branch.objects.create(
            tenant=self.tenant,
            name="فرع القاهرة - المعادي",
            currency="EGP",
            status="active"
        )

        # Branch 3: Tunisia (TND / د.ت)
        self.branch_tn = Branch.objects.create(
            tenant=self.tenant,
            name="فرع تونس - المرسى",
            currency="TND",
            status="active"
        )

        # 2. Menu Item & Custom Branch Availability
        self.menu_item = MenuItem.objects.create(
            tenant=self.tenant,
            name="وجبة برجر الشيف",
            price=Decimal("40.00"),
            available=True,
            category="وجبات رئيسية"
        )

        # Branch custom price in Egypt: 250.00 EGP
        self.branch_avail_eg = BranchMenuAvailability.objects.create(
            branch=self.branch_eg,
            menu_item=self.menu_item,
            is_available=True,
            custom_price=Decimal("250.00")
        )

        # 3. User & Roles (Owner for HQ cross-branch access)
        self.user = User.objects.create_user(
            username=f"owner_{secrets.token_hex(3)}",
            password="password123",
            email="owner@globaldining.com"
        )
        self.job_role = JobRole.objects.create(
            tenant=self.tenant,
            name="المالك التنفيذي",
            scope="hq"
        )
        self.job_role.set_permissions([
            "pos_access", "pos_create_order", "call_center_access",
            "call_center_create_order", "kds_access", "hq_view_orders",
            "view_orders", "order_actions", "view_hq_dashboard"
        ])
        self.user.is_superuser = True
        self.user.save()
        self.profile = UserProfile.objects.create(
            user=self.user,
            tenant=self.tenant,
            branch=None,
            role="owner",
            is_platform_admin=True,
            job_role=self.job_role
        )

        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session["active_branch_id"] = "all"
        session.save()

        # MCP Key
        self.mcp_key = TenantApiKey.objects.create(
            tenant=self.tenant,
            name="Voice AI Key",
            key=f"mcp-test-key-{secrets.token_hex(8)}",
            is_active=True
        )

    def test_pos_order_creation_persists_branch_currency(self):
        """POS order creation inherits and saves currency & currency_symbol from the selected branch"""
        self.client.force_login(self.user)
        payload = {
            "type": "dine_in",
            "channel": "cashier",
            "branchId": self.branch_eg.id,
            "payMethod": "cash",
            "items": [{"menuItemId": self.menu_item.id, "qty": 2}],
            "customerName": "أحمد المصري",
            "customerPhone": "01012345678"
        }
        res = self.client.post("/api/orders/", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 201)
        data = res.json()

        self.assertEqual(data["order"]["currency"], "EGP")
        self.assertEqual(data["order"]["currencySymbol"], "ج.م")

        # Verify DB Order record
        order = Order.objects.get(id=data["order"]["id"])
        self.assertEqual(order.currency, "EGP")
        self.assertEqual(order.currency_symbol, "ج.م")
        self.assertEqual(order.branch, self.branch_eg)

    def test_call_center_order_creation_persists_branch_currency(self):
        """Call Center order creation explicitly sets and returns branch currency"""
        self.client.force_login(self.user)
        payload = {
            "type": "delivery",
            "channel": "call_center",
            "branchId": self.branch_tn.id,
            "payMethod": "cash",
            "items": [{"menuItemId": self.menu_item.id, "qty": 1}],
            "customerName": "سليم التونسي",
            "customerPhone": "21698765432",
            "address": "المرسى، تونس"
        }
        res = self.client.post("/api/orders/", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 201)
        data = res.json()

        self.assertEqual(data["order"]["currency"], "TND")
        self.assertEqual(data["order"]["currencySymbol"], "د.ت")

        order = Order.objects.get(id=data["order"]["id"])
        self.assertEqual(order.currency, "TND")
        self.assertEqual(order.currency_symbol, "د.ت")

    def test_qr_menu_order_creation_persists_branch_currency(self):
        """QR Digital menu order creation stores branch currency & currency_symbol"""
        payload = {
            "branch_id": self.branch_tn.id,
            "order_type": "takeaway",
            "customer_name": "عميل الكيوار",
            "customer_phone": "21611223344",
            "items": [{"id": self.menu_item.id, "qty": 1}]
        }
        url = f"/api/m/{self.tenant.slug}/order/"
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 201)
        data = res.json()

        self.assertEqual(data.get("currency"), "TND")
        self.assertEqual(data.get("currency_symbol"), "د.ت")

        order = Order.objects.get(id=data["order_id"])
        self.assertEqual(order.currency, "TND")
        self.assertEqual(order.currency_symbol, "د.ت")

    def test_mcp_voice_ai_order_creation_persists_branch_currency(self):
        """FastMCP voice assistant create_order tool persists branch currency and symbol"""
        result = mcp_create_order(
            access_key=self.mcp_key.key,
            customer_phone="01155443322",
            customer_name="عميل كول سنتر ذكي",
            customer_address="المعادي شارع النصر",
            items=[{"name": self.menu_item.name, "quantity": 1}],
            order_type="takeaway",
            branch_id=self.branch_eg.id
        )
        self.assertTrue(result.get("ok"), f"MCP create_order failed: {result}")
        order_number = result.get("order_number")
        self.assertTrue(order_number)

        order = Order.objects.get(order_number=order_number)
        self.assertEqual(order.currency, "EGP")
        self.assertEqual(order.currency_symbol, "ج.م")

    def test_financial_immutability_on_branch_currency_change(self):
        """Order currency is immutable: changing branch currency afterwards does not alter existing orders"""
        # Create order in Saudi Branch (SAR)
        order = Order.objects.create(
            tenant=self.tenant,
            branch=self.branch_sa,
            order_number="ORD-TEST-IMMUTABLE-01",
            total=Decimal("120.00"),
            currency="SAR",
            currency_symbol="ر.س",
            status="delivered"
        )
        self.assertEqual(order.currency, "SAR")
        self.assertEqual(order.currency_symbol, "ر.س")

        # Now suppose branch changes currency to USD
        self.branch_sa.currency = "USD"
        self.branch_sa.save()

        # Refresh order from DB
        order.refresh_from_db()
        self.assertEqual(order.currency, "SAR", "Historical order currency must NOT change!")
        self.assertEqual(order.currency_symbol, "ر.س", "Historical currency symbol must NOT change!")

        # Resaving order must not overwrite existing currency
        order.notes = "Updated historical note"
        order.save()
        order.refresh_from_db()
        self.assertEqual(order.currency, "SAR")
        self.assertEqual(order.currency_symbol, "ر.س")

    def test_audit_log_uses_order_currency_symbol(self):
        """Audit log messages format order amount using order.currency_symbol instead of hardcoded 'ر.س'"""
        self.client.force_login(self.user)
        order = Order.objects.create(
            tenant=self.tenant,
            branch=self.branch_eg,
            order_number="ORD-TEST-AUDIT-01",
            total=Decimal("350.00"),
            currency="EGP",
            currency_symbol="ج.م",
            status="new",
            paid=True
        )

        # Cancel the order via cancel API
        res = self.client.post(f"/api/orders/{order.id}/cancel/", data=json.dumps({"reason": "طلب العميل إلغاء"}), content_type="application/json")
        self.assertEqual(res.status_code, 200)

        logs = AuditLog.objects.filter(target_model="Order", target_id=order.id)
        self.assertTrue(logs.exists())
        cancel_log = logs.filter(action="order_cancelled").first()
        self.assertIsNotNone(cancel_log)
        self.assertIn("ج.م", cancel_log.description, f"Audit log should use order's currency symbol 'ج.م', got: {cancel_log.description}")
        self.assertNotIn("ر.س", cancel_log.description, f"Audit log should NOT have hardcoded 'ر.س' for Egyptian order!")

    def test_hq_orders_view_multi_currency_aggregation(self):
        """HQ orders view groups revenue by currency when all branches selected, and displays single total when filtered"""
        # Create orders in SAR, EGP, and TND
        Order.objects.create(
            tenant=self.tenant, branch=self.branch_sa,
            order_number="ORD-SA-1", total=Decimal("150.00"),
            currency="SAR", currency_symbol="ر.س", status="delivered"
        )
        Order.objects.create(
            tenant=self.tenant, branch=self.branch_eg,
            order_number="ORD-EG-1", total=Decimal("450.00"),
            currency="EGP", currency_symbol="ج.م", status="delivered"
        )
        Order.objects.create(
            tenant=self.tenant, branch=self.branch_tn,
            order_number="ORD-TN-1", total=Decimal("85.50"),
            currency="TND", currency_symbol="د.ت", status="preparing"
        )

        self.client.force_login(self.user)

        # 1. Request All Branches (HQ View)
        res = self.client.get("/hq/orders/")
        self.assertEqual(res.status_code, 200)

        self.assertFalse(res.context["is_single_currency"], "is_single_currency must be False when multiple currencies exist")
        rev_by_currency = res.context["rev_by_currency"]
        self.assertEqual(len(rev_by_currency), 3)

        symbols = [item["currency_symbol"] for item in rev_by_currency]
        self.assertIn("ر.س", symbols)
        self.assertIn("ج.م", symbols)
        self.assertIn("د.ت", symbols)

        content = res.content.decode("utf-8")
        self.assertIn("ج.م", content)
        self.assertIn("د.ت", content)
        self.assertIn("ر.س", content)

        # 2. Filter by Egyptian branch only
        res_filtered = self.client.get(f"/hq/orders/?branch={self.branch_eg.id}")
        self.assertEqual(res_filtered.status_code, 200)
        self.assertTrue(res_filtered.context["is_single_currency"], "is_single_currency must be True when filtered to single branch")
        self.assertEqual(res_filtered.context["active_currency_symbol"], "ج.م")
        self.assertEqual(res_filtered.context["total_revenue"], Decimal("450.00"))

    def test_dashboard_view_today_sales_by_currency(self):
        """Central dashboard calculates today_sales_by_currency correctly without mixing currencies"""
        Order.objects.create(
            tenant=self.tenant, branch=self.branch_sa,
            order_number="ORD-DASH-SA", total=Decimal("100.00"),
            currency="SAR", currency_symbol="ر.س", status="delivered"
        )
        Order.objects.create(
            tenant=self.tenant, branch=self.branch_eg,
            order_number="ORD-DASH-EG", total=Decimal("200.00"),
            currency="EGP", currency_symbol="ج.م", status="delivered"
        )

        self.client.force_login(self.user)
        res = self.client.get("/dashboard/")
        self.assertEqual(res.status_code, 200)

        self.assertFalse(res.context["is_single_currency"])
        sales_by_curr = res.context["today_sales_by_currency"]
        self.assertEqual(len(sales_by_curr), 2)
        symbols = [item["currency_symbol"] for item in sales_by_curr]
        self.assertIn("ر.س", symbols)
        self.assertIn("ج.م", symbols)

    def test_sse_serializers_include_currency_and_symbol(self):
        """serialize_kitchen_order and serialize_delivery_order include currency and currency_symbol"""
        order = Order.objects.create(
            tenant=self.tenant,
            branch=self.branch_eg,
            order_number="ORD-SSE-01",
            total=Decimal("180.00"),
            currency="EGP",
            currency_symbol="ج.م",
            status="preparing"
        )

        kds_data = serialize_kitchen_order(order)
        self.assertEqual(kds_data.get("currency"), "EGP")
        self.assertEqual(kds_data.get("currency_symbol"), "ج.م")
        self.assertEqual(kds_data.get("total"), 180.0)

        delivery_data = serialize_delivery_order(order)
        self.assertEqual(delivery_data.get("currency"), "EGP")
        self.assertEqual(delivery_data.get("currency_symbol"), "ج.م")

    def test_pos_and_callcenter_views_provide_custom_prices_context(self):
        """POS and Call Center views pass branch_custom_prices_json in template context"""
        self.client.force_login(self.user)

        res_pos = self.client.get("/pos/")
        self.assertEqual(res_pos.status_code, 200)
        self.assertIn("branch_custom_prices_json", res_pos.context)
        pos_prices = json.loads(res_pos.context["branch_custom_prices_json"])
        b_id = str(self.branch_eg.id)
        m_id = str(self.menu_item.id)
        self.assertIn(b_id, pos_prices)
        self.assertEqual(pos_prices[b_id][m_id], 250.0)

        res_cc = self.client.get("/call-center/")
        self.assertEqual(res_cc.status_code, 200)
        self.assertIn("branch_custom_prices_json", res_cc.context)
        cc_prices = json.loads(res_cc.context["branch_custom_prices_json"])
        self.assertIn(b_id, cc_prices)
        self.assertEqual(cc_prices[b_id][m_id], 250.0)

    def test_order_model_save_fallback_defaults(self):
        """Order.save() automatically populates currency and currency_symbol if empty"""
        order = Order(
            tenant=self.tenant,
            branch=self.branch_tn,
            order_number="ORD-FALLBACK-01",
            total=Decimal("60.00")
        )
        order.save()
        self.assertEqual(order.currency, "TND")
        self.assertEqual(order.currency_symbol, "د.ت")

    def test_hq_orders_aggregation_deduplicates_legacy_and_unpopulated_currency_symbols(self):
        """HQ orders and dashboard merge orders with empty, whitespace, or fallback symbols into one group without pill duplicates"""
        Order.objects.filter(tenant=self.tenant).delete()

        # 1. Order with explicit SAR
        Order.objects.create(
            tenant=self.tenant, branch=self.branch_sa,
            order_number="ORD-DEDUP-01", total=Decimal("100.00"),
            currency="SAR", currency_symbol="ر.س", status="delivered"
        )
        # 2. Legacy order with blank currency_symbol
        o2 = Order.objects.create(
            tenant=self.tenant, branch=self.branch_sa,
            order_number="ORD-DEDUP-02", total=Decimal("50.00"),
            status="delivered"
        )
        Order.objects.filter(id=o2.id).update(currency_symbol="")

        # 3. Legacy order with whitespace currency_symbol
        o3 = Order.objects.create(
            tenant=self.tenant, branch=self.branch_sa,
            order_number="ORD-DEDUP-03", total=Decimal("25.00"),
            status="delivered"
        )
        Order.objects.filter(id=o3.id).update(currency_symbol="   ")

        self.client.force_login(self.user)
        res = self.client.get("/hq/orders/")
        self.assertEqual(res.status_code, 200)

        # All 3 orders resolve to SAR / "ر.س", so is_single_currency MUST be True!
        self.assertTrue(res.context["is_single_currency"], "Expected is_single_currency=True for all SAR orders")
        rev_by_currency = res.context["rev_by_currency"]
        self.assertEqual(len(rev_by_currency), 1, "Expected exactly 1 consolidated currency group")
        self.assertEqual(rev_by_currency[0]["currency_symbol"], "ر.س")
        self.assertEqual(rev_by_currency[0]["total"], Decimal("175.00"))
        self.assertEqual(rev_by_currency[0]["count"], 3)

        # Same consolidation in Dashboard view
        res_dash = self.client.get("/dashboard/")
        self.assertEqual(res_dash.status_code, 200)
        self.assertTrue(res_dash.context["is_single_currency"])
        dash_sales = res_dash.context["today_sales_by_currency"]
        self.assertEqual(len(dash_sales), 1)
        self.assertEqual(dash_sales[0]["currency_symbol"], "ر.س")
        self.assertEqual(dash_sales[0]["total"], Decimal("175.00"))
        self.assertEqual(dash_sales[0]["count"], 3)

    def test_mcp_create_order_alias_and_payload(self):
        """create_order MCP tool alias creates order and returns order.currency and order.currency_symbol"""
        result = mcp_create_order_alias(
            access_key=self.mcp_key.key,
            customer_phone="01199887766",
            customer_name="عميل التوجيه السريع",
            customer_address="شارع التحلية الرياض",
            items=[{"name": self.menu_item.name, "quantity": 2}],
            order_type="takeaway",
            branch_id=self.branch_sa.id
        )
        self.assertTrue(result.get("ok"), f"create_order failed: {result}")
        self.assertEqual(result.get("currency"), "SAR")
        self.assertEqual(result.get("currency_symbol"), "ر.س")
        self.assertIn("order", result)
        self.assertEqual(result["order"]["currency"], "SAR")
        self.assertEqual(result["order"]["currency_symbol"], "ر.س")

    def test_order_detail_view_renders_immutable_order_currency(self):
        """order_detail view renders order.currency_symbol even if branch currency was modified"""
        order = Order.objects.create(
            tenant=self.tenant, branch=self.branch_eg,
            order_number="ORD-DETAIL-TEST-01", total=Decimal("250.00"),
            subtotal=Decimal("250.00"), currency="EGP", currency_symbol="ج.م",
            status="delivered", cashier="كاشير فرع المعادي"
        )
        OrderItem.objects.create(
            order=order, menu_item=self.menu_item,
            name=self.menu_item.name, price=Decimal("250.00"), qty=1
        )

        self.client.force_login(self.user)
        res = self.client.get(f"/orders/{order.id}/")
        self.assertEqual(res.status_code, 200)
        content = res.content.decode("utf-8")
        self.assertIn("ج.م", content)
        self.assertTrue("250,00" in content or "250.00" in content, "Expected formatted total in content")

    def test_i18n_catalog_multilingual_currencies(self):
        """core.i18n_catalog translates Arabic currency symbols to standard ISO English codes"""
        self.assertEqual(get_translation("ج.م", "en"), "EGP")
        self.assertEqual(get_translation("ج.م", "fr"), "EGP")
        self.assertEqual(get_translation("د.ت", "en"), "TND")
        self.assertEqual(get_translation("د.ج", "en"), "DZD")
        self.assertEqual(get_translation("د.إ", "en"), "AED")
        self.assertEqual(get_translation("د.ك", "en"), "KWD")
        self.assertEqual(get_translation("د.م", "en"), "MAD")
        self.assertEqual(get_translation("ر.س", "en"), "SAR")


if __name__ == "__main__":
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(MultiCurrencyOrderTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        exit(1)
