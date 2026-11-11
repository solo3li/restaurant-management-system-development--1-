"""
Comprehensive Test Suite for Subscription Architecture Fixes, Dual Currency,
Manual Payments, 3-Tier Lockout, Inngest Jobs, and Downgrade Overflow.
"""

from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings

from apps.tenants.models import Tenant, Branch
from apps.accounts.models import UserProfile, Employee
from apps.billing.models import SubscriptionPlan, UpgradeRequest
from apps.communication.models import EmailLog
from apps.orders.models import Order
from core.inngest_client import (
    run_subscription_transitions,
    run_reset_monthly_quotas,
    run_upgrade_approved,
)

User = get_user_model()


class SubscriptionFixesTestSuite(TestCase):
    def setUp(self):
        self.client = Client()

        # Ensure standard plans exist
        self.plan_trial, _ = SubscriptionPlan.objects.get_or_create(
            code="trial",
            defaults={
                "name": "الباقة التجريبية المجانية",
                "price_monthly": Decimal("0.00"),
                "price_yearly": Decimal("0.00"),
                "price_monthly_egp": Decimal("0.00"),
                "price_yearly_egp": Decimal("0.00"),
                "max_branches": 2,
                "max_employees": 10,
                "features": ["pos", "kds", "menu_management", "delivery_management", "inventory", "call_center", "ai_call_center"],
                "trial_days": 14,
            }
        )

        self.plan_starter, _ = SubscriptionPlan.objects.get_or_create(
            code="starter",
            defaults={
                "name": "باقة البداية",
                "price_monthly": Decimal("29.00"),
                "price_yearly": Decimal("290.00"),
                "price_monthly_egp": Decimal("1450.00"),
                "price_yearly_egp": Decimal("14500.00"),
                "max_branches": 1,
                "max_employees": 2,
                "features": ["pos", "menu_management"],
                "trial_days": 0,
            }
        )

        self.plan_growth, _ = SubscriptionPlan.objects.get_or_create(
            code="growth",
            defaults={
                "name": "باقة النمو المتقدمة",
                "price_monthly": Decimal("99.00"),
                "price_yearly": Decimal("990.00"),
                "price_monthly_egp": Decimal("4950.00"),
                "price_yearly_egp": Decimal("49500.00"),
                "max_branches": 3,
                "max_employees": 15,
                "features": ["pos", "kds", "menu_management", "inventory", "delivery_management"],
                "trial_days": 0,
            }
        )

        self.plan_pro, _ = SubscriptionPlan.objects.get_or_create(
            code="pro",
            defaults={
                "name": "الباقة الاحترافية",
                "price_monthly": Decimal("199.00"),
                "price_yearly": Decimal("1990.00"),
                "price_monthly_egp": Decimal("9950.00"),
                "price_yearly_egp": Decimal("99500.00"),
                "max_branches": 10,
                "max_employees": 50,
                "features": ["pos", "kds", "menu_management", "inventory", "delivery_management", "call_center", "ai_call_center", "custom_roles"],
                "trial_days": 0,
            }
        )

        # 1. Admin / Platform Superuser
        self.admin_user = User.objects.create_superuser(
            username="admin_sub_test",
            email="admin@motaem.local",
            password="adminpassword123",
        )

        # 2. Restaurant Owner
        self.owner_user = User.objects.create_user(
            username="owner_sub_test",
            email="owner@shawarma.local",
            password="ownerpassword123",
        )
        self.tenant = Tenant.objects.create(
            name="شاورما الفيروز",
            slug="shawarma-fayrouz",
            subscription_plan=self.plan_starter,
            subscription_status="active",
            subscription_end=timezone.now() + timedelta(days=30),
            is_active=True,
        )
        self.owner_profile = UserProfile.objects.create(
            user=self.owner_user,
            tenant=self.tenant,
            role="owner",
            is_platform_admin=False,
        )

        # 3. Staff Member (Cashier)
        self.cashier_user = User.objects.create_user(
            username="cashier_sub_test",
            email="cashier@shawarma.local",
            password="cashierpassword123",
        )
        self.cashier_profile = UserProfile.objects.create(
            user=self.cashier_user,
            tenant=self.tenant,
            role="cashier",
            is_platform_admin=False,
        )
        # Give cashier POS permissions for baseline functionality
        perm = Permission.objects.filter(codename="pos_access").first()
        if perm:
            self.cashier_user.user_permissions.add(perm)

        # Create 1 main branch for tenant
        self.branch1 = Branch.objects.create(
            tenant=self.tenant,
            name="الفرع الرئيسي",
            status="active",
        )

    # =========================================================================
    # 1. DUAL CURRENCY PRICING
    # =========================================================================
    def test_dual_currency_pricing_fields(self):
        """Verify USD and EGP price fields on SubscriptionPlan model."""
        self.assertEqual(self.plan_growth.price_monthly, Decimal("99.00"))
        self.assertEqual(self.plan_growth.price_yearly, Decimal("990.00"))
        self.assertEqual(self.plan_growth.price_monthly_egp, Decimal("4950.00"))
        self.assertEqual(self.plan_growth.price_yearly_egp, Decimal("49500.00"))

        # Verify default prices across tiers
        self.assertEqual(self.plan_starter.price_monthly_egp, Decimal("1450.00"))
        self.assertEqual(self.plan_pro.price_monthly_egp, Decimal("9950.00"))

    # =========================================================================
    # 2. MANUAL PAYMENT WORKFLOW & RECEIPT UPLOAD
    # =========================================================================
    def test_manual_payment_submission_multipart(self):
        """Verify owner can submit an upgrade request with proof receipt image."""
        self.client.force_login(self.owner_user)

        fake_receipt = SimpleUploadedFile(
            "transfer_receipt.jpg",
            b"\xFF\xD8\xFF\xE0\x00\x10JFIFfakeimagecontent",
            content_type="image/jpeg",
        )

        payload = {
            "plan_id": self.plan_growth.id,
            "billing_cycle": "monthly",
            "payment_method": "wallet",
            "currency": "EGP",
            "amount": "4950.00",
            "sender_account": "01099887766",
            "transaction_reference": "TXN-VF-778899",
            "admin_notes": "Paid via Vodafone Cash agent",
            "receipt": fake_receipt,
        }

        response = self.client.post("/api/subscription/request-upgrade/", payload, format="multipart")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("status"), "pending")
        self.assertTrue(data.get("request_id"))

        # Verify DB record
        req_obj = UpgradeRequest.objects.get(id=data["request_id"])
        self.assertEqual(req_obj.tenant, self.tenant)
        self.assertEqual(req_obj.requested_plan, self.plan_growth)
        self.assertEqual(req_obj.billing_cycle, "monthly")
        self.assertEqual(req_obj.payment_method, "wallet")
        self.assertEqual(req_obj.currency, "EGP")
        self.assertEqual(req_obj.amount, Decimal("4950.00"))
        self.assertEqual(req_obj.sender_account, "01099887766")
        self.assertEqual(req_obj.transaction_reference, "TXN-VF-778899")
        self.assertEqual(req_obj.status, "pending")
        self.assertTrue(req_obj.receipt.name.endswith(".jpg"))

    def test_manual_payment_json_fallback(self):
        """Verify JSON payload submission still works without uploaded file."""
        self.client.force_login(self.owner_user)
        payload = {
            "plan_id": self.plan_pro.id,
            "billing_cycle": "yearly",
            "payment_method": "instapay",
            "currency": "EGP",
            "amount": "99500.00",
            "sender_account": "user@instapay",
            "transaction_reference": "IP-998811",
            "admin_notes": "InstaPay transfer confirmation",
        }
        response = self.client.post(
            "/api/subscription/request-upgrade/",
            data=payload,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        req_obj = UpgradeRequest.objects.filter(sender_account="user@instapay").first()
        self.assertIsNotNone(req_obj)
        self.assertEqual(req_obj.payment_method, "instapay")
        self.assertEqual(req_obj.billing_cycle, "yearly")

    # =========================================================================
    # 3. ADMIN REVIEW & UPGRADE APPROVAL
    # =========================================================================
    @patch("core.partner_service.sync_tenant_voice_caps")
    def test_admin_upgrade_approval(self, mock_quota_sync):
        """Verify admin approval extends subscription, updates plan, and logs Brevo email."""
        mock_quota_sync.return_value = {"status": "success"}

        req_obj = UpgradeRequest.objects.create(
            tenant=self.tenant,
            requested_by=self.owner_user,
            requested_plan=self.plan_growth,
            billing_cycle="monthly",
            payment_method="wallet",
            currency="EGP",
            amount=Decimal("4950.00"),
            sender_account="01012345678",
            transaction_reference="REF-554433",
            status="pending",
        )

        initial_end = timezone.now()
        self.tenant.subscription_end = initial_end
        self.tenant.save()

        # Approve upgrade
        result = req_obj.apply_upgrade(admin_user=self.admin_user)
        self.assertTrue(result)

        # Refresh from DB
        req_obj.refresh_from_db()
        self.tenant.refresh_from_db()

        self.assertEqual(req_obj.status, "approved")
        self.assertIsNotNone(req_obj.reviewed_at)
        self.assertEqual(self.tenant.subscription_status, "active")
        self.assertEqual(self.tenant.subscription_plan, self.plan_growth)
        self.assertEqual(self.tenant.plan, "growth")

        # Extended by ~30 days
        self.assertGreaterEqual(self.tenant.subscription_end, initial_end + timedelta(days=29))

        # Check Brevo email log
        email_log = EmailLog.objects.filter(recipient_email=self.owner_user.email).order_by("-created_at").first()
        self.assertIsNotNone(email_log)
        self.assertIn("تفعيل اشتراكك", email_log.subject)

    # =========================================================================
    # 4. DOWNGRADE OVERFLOW DEACTIVATION
    # =========================================================================
    def test_downgrade_overflow_auto_deactivation(self):
        """
        If tenant downgrades to a lower plan, excess active branches and employees
        must be auto-deactivated to respect the new plan limits.
        """
        # Ensure plan_starter limits are strictly 1 branch and 2 employees
        self.plan_starter.max_branches = 1
        self.plan_starter.max_employees = 2
        self.plan_starter.save()

        # Set tenant to Pro plan with 3 branches and 4 employees
        self.tenant.subscription_plan = self.plan_pro
        self.tenant.plan = "pro"
        self.tenant.save()

        # Create 2 more active branches (total 3 branches)
        branch2 = Branch.objects.create(tenant=self.tenant, name="فرع المعادي", status="active")
        branch3 = Branch.objects.create(tenant=self.tenant, name="فرع التجمع", status="active")

        # Create 4 employees (total 4 employees)
        for i in range(1, 5):
            u = User.objects.create_user(username=f"emp_test_{i}", email=f"emp{i}@fayrouz.local")
            Employee.objects.create(
                tenant=self.tenant,
                branch=self.branch1,
                user=u,
                name=f"موظف {i}",
                status="active",
            )

        self.assertEqual(self.tenant.branches.filter(status="active").count(), 3)
        self.assertEqual(self.tenant.employees.filter(status__in=["active", "vacation"]).count(), 4)

        # Now tenant downgrades to Starter plan: max_branches=1, max_employees=2
        req_downgrade = UpgradeRequest.objects.create(
            tenant=self.tenant,
            requested_by=self.owner_user,
            requested_plan=self.plan_starter,  # max_branches=1, max_employees=2
            billing_cycle="monthly",
            payment_method="instapay",
            currency="EGP",
            amount=Decimal("1450.00"),
            status="pending",
        )

        req_downgrade.apply_upgrade(admin_user=self.admin_user)
        self.tenant.refresh_from_db()

        self.assertEqual(self.tenant.subscription_plan, self.plan_starter)
        # Verify branches: exactly 1 active branch remains
        active_branches = self.tenant.branches.filter(status="active")
        self.assertEqual(active_branches.count(), 1)
        closed_branches = self.tenant.branches.filter(status="closed")
        self.assertEqual(closed_branches.count(), 2)

        # Verify employees: exactly 2 active employees remain
        active_employees = self.tenant.employees.filter(status__in=["active", "vacation"])
        self.assertEqual(active_employees.count(), 2)
        inactive_employees = self.tenant.employees.filter(status="inactive")
        self.assertEqual(inactive_employees.count(), 2)

    # =========================================================================
    # 5. NULL SUBSCRIPTION_PLAN LOOPHOLE & AUTO-TRIAL
    # =========================================================================
    def test_null_subscription_plan_loophole_closed(self):
        """can_add_branch, can_add_employee, has_feature must return False when plan is None."""
        orphan_tenant = Tenant(
            name="مطعم الأيتام",
            slug="orphan-rest",
            subscription_plan=None,
        )

        self.assertFalse(orphan_tenant.can_add_branch())
        self.assertFalse(orphan_tenant.can_add_employee())
        self.assertFalse(orphan_tenant.has_feature("pos"))
        self.assertFalse(orphan_tenant.has_feature("call_center"))

    def test_auto_assign_trial_plan_on_new_tenant(self):
        """Newly created tenant with no plan is auto-assigned the 14-day Trial plan."""
        new_tenant = Tenant.objects.create(
            name="برجر السعادة",
            slug="burger-saada",
            is_active=True,
        )

        self.assertIsNotNone(new_tenant.subscription_plan)
        self.assertEqual(new_tenant.subscription_plan.code, "trial")
        self.assertEqual(new_tenant.plan, "trial")
        self.assertEqual(new_tenant.subscription_status, "trial")
        self.assertGreater(new_tenant.subscription_end, timezone.now())

    # =========================================================================
    # 6. 3-TIER SUBSCRIPTION LIFECYCLE & MIDDLEWARE
    # =========================================================================
    def test_tier1_active_subscription_unrestricted(self):
        """Active tenant operates normally without restriction."""
        self.tenant.subscription_status = "active"
        self.tenant.subscription_end = timezone.now() + timedelta(days=20)
        self.tenant.save()

        self.assertFalse(self.tenant.is_in_grace_period())
        self.assertFalse(self.tenant.is_locked_out())
        self.assertTrue(self.tenant.is_subscription_active())

    def test_tier2_grace_period_enforcement(self):
        """
        Grace period (0-3 days post-expiration):
        - POS and order creation remain functional.
        - Management / settings / employee / menu mutation POSTs are blocked (403).
        """
        # Expired 1 day ago (within 3 days)
        self.tenant.subscription_status = "active"
        self.tenant.subscription_end = timezone.now() - timedelta(days=1)
        self.tenant.save()

        self.assertTrue(self.tenant.is_in_grace_period())
        self.assertFalse(self.tenant.is_locked_out())
        self.assertGreaterEqual(self.tenant.grace_days_remaining(), 1)

        # 1. Owner access to POS remains functional
        self.client.force_login(self.owner_user)
        pos_resp = self.client.get("/pos/")
        self.assertEqual(pos_resp.status_code, 200)

        # 2. Owner attempting mutation in management is blocked with 403
        post_resp = self.client.post(
            "/api/menu/items/",
            {"name": "طبق تجريبي", "price": "50"},
            headers={"x-requested-with": "XMLHttpRequest"},
        )
        self.assertEqual(post_resp.status_code, 403)
        self.assertIn("فترة السماح", post_resp.json().get("error", ""))

    def test_tier3_hard_lockout_read_only_and_block_screen(self):
        """
        Hard lockout (>3 days post-expiration):
        - Owner can access /subscription/ and GET past reports, but all mutations blocked.
        - Staff (cashier) GET requests blocked with HTTP 403 and multilingual block screen.
        """
        # Expired 5 days ago (past 3 days)
        self.tenant.subscription_status = "expired"
        self.tenant.subscription_end = timezone.now() - timedelta(days=5)
        self.tenant.save()

        self.assertFalse(self.tenant.is_in_grace_period())
        self.assertTrue(self.tenant.is_locked_out())

        # 1. Owner can access subscription page
        self.client.force_login(self.owner_user)
        sub_resp = self.client.get("/subscription/")
        self.assertEqual(sub_resp.status_code, 200)

        # 2. Owner mutations blocked
        order_post = self.client.post(
            "/api/orders/",
            {"branch_id": self.branch1.id, "items": []},
            headers={"x-requested-with": "XMLHttpRequest"},
        )
        self.assertEqual(order_post.status_code, 403)
        self.assertIn("انتهت فترة الاشتراك", order_post.json().get("error", ""))

        # 3. Staff member (Cashier) gets 403 block screen on POS
        self.client.force_login(self.cashier_user)
        cashier_resp = self.client.get("/pos/")
        self.assertEqual(cashier_resp.status_code, 403)
        content = cashier_resp.content.decode("utf-8")
        self.assertIn("انتهت صلاحية اشتراك المنشأة", content)
        self.assertIn("يرجى التواصل مع إدارة المطعم لتجديد الاشتراك", content)

    # =========================================================================
    # 7. INNGEST INTEGRATION & CRONS
    # =========================================================================
    def test_inngest_webhook_endpoint(self):
        """Inngest webhook endpoint responds with 200 OK."""
        resp = self.client.get("/api/inngest/")
        self.assertEqual(resp.status_code, 200)

    def test_inngest_check_subscription_transitions_cron(self):
        """Cron transitions active expired tenants to grace_period or expired."""
        # Tenant 1: expired 1 day ago -> grace_period
        t1 = Tenant.objects.create(
            name="مطعم سماح",
            slug="rest-samah",
            subscription_plan=self.plan_starter,
            subscription_status="active",
            subscription_end=timezone.now() - timedelta(days=1),
        )

        # Tenant 2: expired 4 days ago -> expired
        t2 = Tenant.objects.create(
            name="مطعم قفل",
            slug="rest-qufl",
            subscription_plan=self.plan_starter,
            subscription_status="grace_period",
            subscription_end=timezone.now() - timedelta(days=4),
        )

        # Tenant 3: active in future -> active
        t3 = Tenant.objects.create(
            name="مطعم شغال",
            slug="rest-shaghal",
            subscription_plan=self.plan_starter,
            subscription_status="active",
            subscription_end=timezone.now() + timedelta(days=10),
        )

        # Run core transition function
        result = run_subscription_transitions()
        self.assertEqual(result.get("status"), "completed")

        t1.refresh_from_db()
        t2.refresh_from_db()
        t3.refresh_from_db()

        self.assertEqual(t1.subscription_status, "grace_period")
        self.assertEqual(t2.subscription_status, "expired")
        self.assertEqual(t3.subscription_status, "active")

    def test_inngest_reset_monthly_quotas_cron(self):
        """Cron resets voice & message quotas on billing day."""
        result = run_reset_monthly_quotas()
        self.assertEqual(result.get("status"), "completed")

    # =========================================================================
    # 8. MINIO & STORAGES CONFIGURATION
    # =========================================================================
    def test_storages_configuration(self):
        """Verify django-storages is in INSTALLED_APPS and STORAGES configured."""
        self.assertIn("storages", settings.INSTALLED_APPS)
        self.assertIn("default", settings.STORAGES)
        self.assertIn("BACKEND", settings.STORAGES["default"])
