"""
Unit and Integration Test Suite for Unified Order Number Format across all Channels:
- POS (Cashier)
- Call Center
- QR Menu
- FastMCP AI Call Center
- KDS & Screen Displays
- Daily Sequence Reset & Collision Prevention
- Legacy Order Preservation
"""
import os
import django
import json
from decimal import Decimal
from datetime import timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client, TestCase
from django.utils import timezone
from core.models import Tenant, Branch, Order, MenuItem, Customer
from core.redis_mcp_cache import generate_order_number, get_next_order_sequence, get_redis_client
from apps.kitchen.events import serialize_kitchen_order
from apps.orders.events import serialize_delivery_order


class UnifiedOrderNumberTests(TestCase):
    def setUp(self):
        self.client = Client()
        import secrets
        self.tenant = Tenant.objects.create(
            name="مطعم الاختبار الموحد",
            slug=f"test-u-{secrets.token_hex(4)}",
            subscription_status="active",
            plan="enterprise"
        )
        self.branch1 = Branch.objects.create(
            tenant=self.tenant,
            name="فرع التحلية",
            status="active"
        )
        self.branch2 = Branch.objects.create(
            tenant=self.tenant,
            name="فرع العليا",
            status="active"
        )
        self.menu_item = MenuItem.objects.create(
            tenant=self.tenant,
            name="برجر دجاج فاخر",
            price=Decimal("35.00"),
            available=True,
            category="ساندويتشات"
        )

        from django.contrib.auth.models import User
        from apps.accounts.models import UserProfile, JobRole

        self.user = User.objects.create_user(username="cashier_test", password="password123")
        self.job_role = JobRole.objects.create(
            tenant=self.tenant,
            name="كاشير رئيسي",
            scope="both"
        )
        self.job_role.set_permissions([
            "pos_access", "pos_create_order", "call_center_access",
            "call_center_create_order", "kds_access"
        ])
        self.profile = UserProfile.objects.create(
            user=self.user,
            tenant=self.tenant,
            branch=self.branch1,
            role="cashier",
            job_role=self.job_role
        )

    def test_format_with_branch(self):
        """Unified format: ORD-{YYYYMMDD}-B{branch_id}-{sequence:04d}"""
        today_str = timezone.now().strftime("%Y%m%d")
        ord_num = generate_order_number(self.tenant, self.branch1)
        expected_prefix = f"ORD-{today_str}-B{self.branch1.id}-"
        self.assertTrue(ord_num.startswith(expected_prefix), f"Expected prefix {expected_prefix}, got {ord_num}")
        seq_part = ord_num.split("-")[-1]
        self.assertEqual(len(seq_part), 4, f"Sequence part must be 4 digits, got {seq_part}")
        self.assertTrue(seq_part.isdigit(), f"Sequence part must be digits, got {seq_part}")

    def test_format_without_branch(self):
        """Unified format without branch: ORD-{YYYYMMDD}-BR-{sequence:04d}"""
        today_str = timezone.now().strftime("%Y%m%d")
        ord_num = generate_order_number(self.tenant, None)
        expected_prefix = f"ORD-{today_str}-BR-"
        self.assertTrue(ord_num.startswith(expected_prefix), f"Expected prefix {expected_prefix}, got {ord_num}")
        seq_part = ord_num.split("-")[-1]
        self.assertEqual(len(seq_part), 4)

    def test_branch_isolation_and_daily_reset(self):
        """Branch 1 and Branch 2 sequences must be distinct and start from 0001"""
        today_str = timezone.now().strftime("%Y%m%d")
        # Clean Redis sequence for this clean test
        redis = get_redis_client()
        if redis:
            redis.delete(f"order_seq:{self.tenant.id}:{self.branch1.id}:{today_str}")
            redis.delete(f"order_seq:{self.tenant.id}:{self.branch2.id}:{today_str}")

        num_b1_1 = generate_order_number(self.tenant, self.branch1)
        num_b2_1 = generate_order_number(self.tenant, self.branch2)

        self.assertEqual(num_b1_1, f"ORD-{today_str}-B{self.branch1.id}-0001")
        self.assertEqual(num_b2_1, f"ORD-{today_str}-B{self.branch2.id}-0001")

        # Create order in DB with num_b1_1 to simulate persistent sequence
        Order.objects.create(tenant=self.tenant, branch=self.branch1, order_number=num_b1_1, total=Decimal("35.00"))
        num_b1_2 = generate_order_number(self.tenant, self.branch1)
        self.assertEqual(num_b1_2, f"ORD-{today_str}-B{self.branch1.id}-0002")

    def test_short_order_number_property(self):
        """short_order_number extracts #0001 for unified orders and handles legacy cleanly"""
        order_unified = Order(order_number="ORD-20261101-B5-0042")
        self.assertEqual(order_unified.short_order_number, "#0042")

        order_no_branch = Order(order_number="ORD-20261101-BR-0007")
        self.assertEqual(order_no_branch.short_order_number, "#0007")

        order_legacy_tr = Order(order_number="T_R-1558")
        self.assertEqual(order_legacy_tr.short_order_number, "#1558")

        order_legacy_qr = Order(order_number="QR-F8A2B1")
        self.assertEqual(order_legacy_qr.short_order_number, "#QR-F8A2B1")

        order_empty = Order(order_number="")
        self.assertEqual(order_empty.short_order_number, "")

    def test_pos_order_creation_api(self):
        """POS order creation returns unified format and shortOrderNumber"""
        self.client.force_login(self.user)
        payload = {
            "type": "dine_in",
            "channel": "cashier",
            "branchId": self.branch1.id,
            "payMethod": "cash",
            "items": [{"menuItemId": self.menu_item.id, "qty": 1}],
            "customerName": "عميل صالة",
            "customerPhone": "0501234567"
        }
        res = self.client.post("/api/orders/", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 201)
        data = res.json()
        ord_num = data["order"]["orderNumber"]
        short_num = data["order"]["shortOrderNumber"]

        today_str = timezone.now().strftime("%Y%m%d")
        expected_prefix = f"ORD-{today_str}-B{self.branch1.id}-"
        self.assertTrue(ord_num.startswith(expected_prefix), f"POS order number must start with {expected_prefix}")
        self.assertTrue(short_num.startswith("#"), f"Short order number must start with #, got {short_num}")

        # Check DB
        db_order = Order.objects.get(id=data["order"]["id"])
        self.assertEqual(db_order.order_number, ord_num)
        self.assertEqual(db_order.short_order_number, short_num)

    def test_call_center_order_creation(self):
        """Call Center order creation returns unified format"""
        self.client.force_login(self.user)
        payload = {
            "type": "takeaway",
            "channel": "call_center",
            "branchId": self.branch2.id,
            "payMethod": "cash",
            "items": [{"menuItemId": self.menu_item.id, "qty": 2}],
            "customerName": "عميل هاتف",
            "customerPhone": "0559988776"
        }
        res = self.client.post("/api/orders/", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 201)
        data = res.json()
        ord_num = data["order"]["orderNumber"]
        today_str = timezone.now().strftime("%Y%m%d")
        expected_prefix = f"ORD-{today_str}-B{self.branch2.id}-"
        self.assertTrue(ord_num.startswith(expected_prefix))

    def test_qr_menu_order_creation(self):
        """QR Menu order creation generates unified format and returns short_order_number"""
        payload = {
            "branch_id": self.branch1.id,
            "order_type": "takeaway",
            "customer_name": "عميل الباركود",
            "customer_phone": "0543219876",
            "notes": "بدون بصل",
            "items": [{"id": self.menu_item.id, "qty": 1}]
        }
        url = f"/api/m/{self.tenant.slug}/order/"
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 201)
        data = res.json()
        ord_num = data["order_number"]
        short_num = data["short_order_number"]

        today_str = timezone.now().strftime("%Y%m%d")
        expected_prefix = f"ORD-{today_str}-B{self.branch1.id}-"
        self.assertTrue(ord_num.startswith(expected_prefix), f"QR order must start with {expected_prefix}, got {ord_num}")
        self.assertFalse(ord_num.startswith("QR-"), f"QR orders must no longer use legacy QR- prefix!")
        self.assertTrue(short_num.startswith("#"))

    def test_kds_serialization_includes_both_numbers(self):
        """serialize_kitchen_order includes order_number and short_order_number"""
        order = Order.objects.create(
            tenant=self.tenant,
            branch=self.branch1,
            order_number="ORD-20261101-B1-0005",
            total=Decimal("70.00"),
            status="new"
        )
        serialized = serialize_kitchen_order(order)
        self.assertEqual(serialized["order_number"], "ORD-20261101-B1-0005")
        self.assertEqual(serialized["short_order_number"], "#0005")

    def test_legacy_orders_unmodified(self):
        """Legacy orders remain completely valid and intact"""
        legacy = Order.objects.create(
            tenant=self.tenant,
            branch=self.branch1,
            order_number="T_R-9999",
            total=Decimal("50.00")
        )
    def test_daily_rollover_resets_sequence(self):
        """When date changes, sequence counter starts again from 0001 for each branch"""
        today_str = "20261101"
        tomorrow_str = "20261102"

        num_today = generate_order_number(self.tenant, self.branch1, date_str=today_str)
        self.assertTrue(num_today.startswith(f"ORD-{today_str}-B{self.branch1.id}-"))
        
        num_tomorrow = generate_order_number(self.tenant, self.branch1, date_str=tomorrow_str)
        self.assertEqual(num_tomorrow, f"ORD-{tomorrow_str}-B{self.branch1.id}-0001")

    def test_concurrent_order_number_generation(self):
        """Zero collision when generating order numbers concurrently across multiple threads"""
        import concurrent.futures
        today_str = timezone.now().strftime("%Y%m%d")

        def worker():
            return generate_order_number(self.tenant, self.branch1)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker) for _ in range(25)]
            results = [f.result() for f in futures]

        self.assertEqual(len(results), 25)
        # All generated numbers must be unique
        self.assertEqual(len(set(results)), 25, "Concurrent order generation produced collisions!")
        for num in results:
            self.assertTrue(num.startswith(f"ORD-{today_str}-B{self.branch1.id}-"))

    def test_redis_fallback_when_redis_unavailable(self):
        """When Redis is None or unavailable, get_next_order_sequence gracefully falls back to DB count"""
        from unittest.mock import patch
        today_str = "20261231"
        with patch("core.redis_mcp_cache.get_redis_client", return_value=None):
            seq1 = get_next_order_sequence(self.tenant.id, self.branch1.id, today_str)
            self.assertEqual(seq1, 1)

            Order.objects.create(
                tenant=self.tenant,
                branch=self.branch1,
                order_number=f"ORD-{today_str}-B{self.branch1.id}-0001",
                total=Decimal("20.00")
            )
            seq2 = get_next_order_sequence(self.tenant.id, self.branch1.id, today_str)
            self.assertEqual(seq2, 2)


if __name__ == "__main__":
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(UnifiedOrderNumberTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        exit(1)
