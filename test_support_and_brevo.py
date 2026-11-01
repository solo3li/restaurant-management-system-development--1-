import io
import json
import base64
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client, RequestFactory
from django.contrib import admin
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.tenants.models import Tenant, Branch
from apps.accounts.models import UserProfile
from apps.orders.models import Customer
from apps.communication.models import BrevoConfiguration, VerificationCode, EmailLog, InboundEmailLog
from apps.communication import brevo_service
from apps.communication.admin import send_custom_brevo_email_to_users, send_custom_brevo_email_to_customers
from apps.support.models import SupportTicket, TicketMessage, TicketAttachment


class BrevoAndSupportTicketsTestSuite(TestCase):
    """
    Comprehensive verification suite for:
    1. Brevo Configuration Singleton & Brevo Service.
    2. 6-Character Alphanumeric Verification Code & 1-Hour Expiration.
    3. Forgot Password / Reset Password End-to-End Workflow.
    4. Inbound Email Webhook & Automatic Ticket Reply Parsing.
    5. Full-Page Support Ticket System with Rich Media (Audio, Video, Images, Docs <= 25MB).
    6. Multi-Tenant Isolation & RBAC.
    """

    def setUp(self):
        self.client = Client()

        # Tenant 1: Grill House
        self.tenant1 = Tenant.objects.create(
            name="مطعم المشويات الأصيل",
            slug="grill-house",
            email="owner@grillhouse.com",
            phone="+966500000001",
            is_active=True
        )
        self.branch1 = Branch.objects.create(
            tenant=self.tenant1,
            name="فرع الرياض الرئيسي",
            status="active"
        )
        self.owner1 = User.objects.create_user(
            username="owner_grill",
            email="owner@grillhouse.com",
            password="password123",
            first_name="أحمد",
            last_name="الغامدي"
        )
        self.profile1 = UserProfile.objects.create(
            user=self.owner1,
            tenant=self.tenant1,
            branch=self.branch1,
            role="owner"
        )

        # Tenant 2: Burger Joint (for multi-tenant isolation tests)
        self.tenant2 = Tenant.objects.create(
            name="برجر كرافت",
            slug="burger-craft",
            email="owner@burgercraft.com",
            phone="+966500000002",
            is_active=True
        )
        self.branch2 = Branch.objects.create(
            tenant=self.tenant2,
            name="فرع جدة",
            status="active"
        )
        self.owner2 = User.objects.create_user(
            username="owner_burger",
            email="owner@burgercraft.com",
            password="password123",
            first_name="سعيد",
            last_name="القرني"
        )
        self.profile2 = UserProfile.objects.create(
            user=self.owner2,
            tenant=self.tenant2,
            branch=self.branch2,
            role="owner"
        )

        # Superadmin
        self.superadmin = User.objects.create_superuser(
            username="super_admin",
            email="superadmin@motaem.com",
            password="superpassword123"
        )

        # Ensure Brevo Config
        self.brevo_config = BrevoConfiguration.get_config()

    # =========================================================================
    # SUITE 1: Brevo Configuration Singleton & Service
    # =========================================================================
    def test_brevo_configuration_singleton(self):
        """Verifies BrevoConfiguration acts as a strict singleton with pk=1."""
        config1 = BrevoConfiguration.get_config()
        self.assertEqual(config1.pk, 1)
        self.assertTrue(config1.is_active)
        self.assertEqual(config1.sender_email, "hamed3alii.11@gmail.com")

        # Attempt to create another instance
        config2 = BrevoConfiguration(api_key="custom-key-test", sender_email="custom@motaem.com")
        config2.save()
        self.assertEqual(config2.pk, 1)
        self.assertEqual(BrevoConfiguration.objects.count(), 1)

        # Verify get_config retrieves updated
        reloaded = BrevoConfiguration.get_config()
        self.assertEqual(reloaded.api_key, "custom-key-test")
        self.assertEqual(reloaded.sender_email, "custom@motaem.com")

        # Restore
        reloaded.api_key = "mock_test_brevo_key_12345"
        reloaded.sender_email = "hamed3alii.11@gmail.com"
        reloaded.save()

    @patch("apps.communication.brevo_service.requests.post")
    def test_send_brevo_email_success(self, mock_post):
        """Verifies transactional email dispatch via Brevo and EmailLog record creation."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"messageId": "<brevo-test-msg-12345@smtp-relay.mailin.fr>"}
        mock_post.return_value = mock_resp

        result = brevo_service.send_brevo_email(
            to_email="customer@example.com",
            subject="اختبار إرسال بريد",
            html_content="<p>محتوى البريد التجريبي</p>",
            to_name="العميل التجريبي"
        )

        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("message_id"), "<brevo-test-msg-12345@smtp-relay.mailin.fr>")

        # Verify EmailLog created
        log = EmailLog.objects.filter(recipient_email="customer@example.com").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, "sent")
        self.assertEqual(log.brevo_message_id, "<brevo-test-msg-12345@smtp-relay.mailin.fr>")

    def test_send_brevo_email_deactivated(self):
        """Verifies no network calls happen and log records failed status when Brevo is deactivated."""
        config = BrevoConfiguration.get_config()
        config.is_active = False
        config.save()

        result = brevo_service.send_brevo_email(
            to_email="test@example.com",
            subject="Test inactive",
            html_content="<p>Test</p>"
        )
        self.assertEqual(result.get("status"), "error")
        log = EmailLog.objects.filter(recipient_email="test@example.com").first()
        self.assertEqual(log.status, "failed")
        self.assertIn("deactivated", log.error_message)

        # Restore
        config.is_active = True
        config.save()

    # =========================================================================
    # SUITE 2: Alphanumeric 6-Character Verification Code & 1-Hour Expiration
    # =========================================================================
    def test_alphanumeric_code_generation_and_properties(self):
        """Verifies code is exactly 6 alphanumeric uppercase characters with 1 hour expiration."""
        now = timezone.now()
        code_obj = VerificationCode.generate_code(
            email="test@grillhouse.com",
            user=self.owner1,
            purpose="password_reset",
            expiry_hours=1
        )

        # 1. Exactly 6 characters
        self.assertEqual(len(code_obj.code), 6)
        # 2. Uppercase and digits only
        self.assertTrue(code_obj.code.isalnum())
        self.assertTrue(code_obj.code.isupper())
        # 3. 1 hour expiration
        expected_expiry = now + timedelta(hours=1)
        self.assertAlmostEqual(code_obj.expires_at.timestamp(), expected_expiry.timestamp(), delta=10)
        # 4. Fresh code is valid
        self.assertTrue(code_obj.is_valid)

    def test_code_expiration_and_single_use(self):
        """Verifies expired codes and used codes are strictly rejected."""
        # Expired code (created 2 hours ago)
        expired_code = VerificationCode.objects.create(
            email="expired@example.com",
            code="EXPIRE",
            purpose="password_reset",
            expires_at=timezone.now() - timedelta(minutes=10),
            is_used=False
        )
        self.assertFalse(expired_code.is_valid)

        # Used code
        used_code = VerificationCode.objects.create(
            email="used@example.com",
            code="USEDD1",
            purpose="password_reset",
            expires_at=timezone.now() + timedelta(hours=1),
            is_used=True
        )
        self.assertFalse(used_code.is_valid)

    # =========================================================================
    # SUITE 3: Forgot Password & Reset Password Workflow
    # =========================================================================
    @patch("apps.communication.brevo_service.requests.post")
    def test_forgot_password_and_reset_flow(self, mock_post):
        """End-to-End test of forgot password, verification, and resetting password."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"messageId": "<brevo-pwd-reset-999@smtp-relay.brevo.com>"}
        mock_post.return_value = mock_resp

        # Step 1: Request code
        resp = self.client.post(
            reverse("forgot_password"),
            data=json.dumps({"identifier": "owner@grillhouse.com"}),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")

        # Locate generated code
        code_record = VerificationCode.objects.filter(email="owner@grillhouse.com", is_used=False).first()
        self.assertIsNotNone(code_record)
        valid_code = code_record.code

        # Step 2: Verify code with invalid attempt
        bad_resp = self.client.post(
            reverse("verify_code"),
            data=json.dumps({"email": "owner@grillhouse.com", "code": "WRONG1"}),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(bad_resp.status_code, 400)

        # Step 2: Verify code with valid code
        good_resp = self.client.post(
            reverse("verify_code"),
            data=json.dumps({"email": "owner@grillhouse.com", "code": valid_code}),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(good_resp.status_code, 200)
        self.assertEqual(good_resp.json()["status"], "success")

        # Step 3: Reset Password with mismatched passwords
        mismatch_resp = self.client.post(
            reverse("reset_password"),
            data=json.dumps({
                "email": "owner@grillhouse.com",
                "code": valid_code,
                "new_password": "NewSecretPass123",
                "confirm_password": "DifferentPassword123"
            }),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(mismatch_resp.status_code, 400)

        # Step 3: Reset Password successfully
        reset_resp = self.client.post(
            reverse("reset_password"),
            data=json.dumps({
                "email": "owner@grillhouse.com",
                "code": valid_code,
                "new_password": "NewSecretPass123",
                "confirm_password": "NewSecretPass123"
            }),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(reset_resp.status_code, 200)
        self.assertEqual(reset_resp.json()["status"], "success")

        # Verify User can login with new password
        self.owner1.refresh_from_db()
        self.assertTrue(self.owner1.check_password("NewSecretPass123"))

        # Verify Code marked as used
        code_record.refresh_from_db()
        self.assertTrue(code_record.is_used)

        # Step 4: Replay attack with same code strictly rejected
        replay_resp = self.client.post(
            reverse("reset_password"),
            data=json.dumps({
                "email": "owner@grillhouse.com",
                "code": valid_code,
                "new_password": "AnotherPassword456",
                "confirm_password": "AnotherPassword456"
            }),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(replay_resp.status_code, 400)

    # =========================================================================
    # SUITE 4: Brevo Inbound Email Webhook & Auto-Linking to Tickets
    # =========================================================================
    def test_brevo_inbound_webhook_reply_parser(self):
        """Verifies Brevo inbound webhook receives reply, extracts ticket number, and adds TicketMessage."""
        ticket = SupportTicket.objects.create(
            tenant=self.tenant1,
            ticket_number="TCK-202610-8899",
            creator=self.owner1,
            subject="عطل في الربط مع الطابعة الحرارية",
            description="الطباعة تتوقف عند ضغط طلب جديد",
            status="resolved"
        )

        # Simulated Brevo inbound JSON payload
        inbound_payload = {
            "items": [
                {
                    "MessageId": "<inbound-reply-abc-123@customer.com>",
                    "From": {"Address": "owner@grillhouse.com", "Name": "أحمد الغامدي"},
                    "To": [{"Address": "support@motaem.com", "Name": "Motaem Support"}],
                    "Subject": "Re: [TCK-202610-8899] عطل في الربط مع الطابعة الحرارية",
                    "RawTextBody": "قمنا بإعادة تشغيل الطابعة ولا زالت المشكلة قائمة، يرجى الفحص مجدداً.",
                    "RawHtmlBody": "<p>قمنا بإعادة تشغيل الطابعة ولا زالت المشكلة قائمة، يرجى الفحص مجدداً.</p>"
                }
            ]
        }

        resp = self.client.post(
            reverse("brevo_inbound_webhook"),
            data=json.dumps(inbound_payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "success")

        # Verify InboundEmailLog created and processed
        log = InboundEmailLog.objects.filter(message_id="<inbound-reply-abc-123@customer.com>").first()
        self.assertIsNotNone(log)
        self.assertTrue(log.is_processed)
        self.assertEqual(log.ticket, ticket)

        # Verify TicketMessage was created in ticket thread
        msg = ticket.messages.first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.sender_type, "tenant")
        self.assertIn("قمنا بإعادة تشغيل الطابعة", msg.message)

        # Verify ticket was reopened from resolved to in_progress
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "in_progress")

    # =========================================================================
    # SUITE 5: Full-Page Support Ticket System in Admin Tabs
    # =========================================================================
    def test_support_tickets_page_access_and_nav_tabs(self):
        """Verifies full-page support tickets view is integrated into general admin tabs."""
        # Unauthenticated blocked (redirects to login)
        resp_unauth = self.client.get(reverse("support_tickets"))
        self.assertEqual(resp_unauth.status_code, 302)

        # Authenticate Owner 1
        self.client.force_login(self.owner1)
        session = self.client.session
        session["active_tenant_id"] = self.tenant1.id
        session.save()

        resp = self.client.get(reverse("support_tickets"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")

        # Verify General Admin tab 6 is present and active
        self.assertIn("الدعم الفني والتذاكر", content)
        self.assertIn(reverse("support_tickets"), content)


    @patch("apps.communication.brevo_service.requests.post")
    def test_ticket_creation_with_rich_media_and_size_validation(self, mock_post):
        """Tests ticket creation with voice note, images, documents and 25MB file size limit."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"messageId": "<brevo-ticket-notice-1@smtp.brevo.com>"}
        mock_post.return_value = mock_resp

        self.client.force_login(self.owner1)
        session = self.client.session
        session["active_tenant_id"] = self.tenant1.id
        session.save()

        # 1. Reject file over 25MB (25 * 1024 * 1024 + 1024)
        oversized_data = b"X" * (25 * 1024 * 1024 + 100)
        oversized_file = SimpleUploadedFile("huge_log.txt", oversized_data, content_type="text/plain")

        fail_resp = self.client.post(
            reverse("api_create_ticket"),
            data={
                "subject": "تذكرة بملف ضخم",
                "description": "تجربة رفع ملف أكبر من 25MB",
                "attachments": [oversized_file]
            }
        )
        self.assertEqual(fail_resp.status_code, 400)
        self.assertIn("25 ميجابايت", fail_resp.json()["message"])

        # 2. Accept valid rich media files: image, video, and audio note
        valid_img = SimpleUploadedFile("screenshot.png", b"\x89PNG\r\n\x1a\nfakeimagebytes", content_type="image/png")
        valid_voice = SimpleUploadedFile("voicenote.webm", b"\x1aE\xdf\xa3fakeaudiobytes", content_type="audio/webm")

        create_resp = self.client.post(
            reverse("api_create_ticket"),
            data={
                "subject": "شاشة الكاشير تعلق عند الدفع الإلكتروني",
                "description": "عند اختيار مدى تتوقف الشاشة لمدة 30 ثانية",
                "category": "pos_hardware",
                "priority": "high",
                "attachments": [valid_img],
                "audio_note": valid_voice,
                "audio_duration": "14"
            }
        )
        self.assertEqual(create_resp.status_code, 200)
        ticket_id = create_resp.json()["ticket_id"]

        ticket = SupportTicket.objects.get(pk=ticket_id)
        self.assertEqual(ticket.tenant, self.tenant1)
        self.assertEqual(ticket.priority, "high")
        self.assertEqual(ticket.category, "pos_hardware")

        # Verify attachments created with auto-detected types
        attachments = ticket.attachments.all()
        self.assertEqual(attachments.count(), 2)

        img_att = attachments.filter(file_type="image").first()
        self.assertIsNotNone(img_att)
        self.assertEqual(img_att.file_name, "screenshot.png")

        audio_att = attachments.filter(file_type="audio").first()
        self.assertIsNotNone(audio_att)
        self.assertEqual(audio_att.duration_seconds, 14)

    # =========================================================================
    # SUITE 6: Multi-Tenant Isolation on Support Tickets
    # =========================================================================
    def test_multi_tenant_isolation_on_tickets(self):
        """Strictly prevents cross-tenant ticket inspection or mutation."""
        ticket_tenant1 = SupportTicket.objects.create(
            tenant=self.tenant1,
            ticket_number="TCK-T1-SECRET",
            creator=self.owner1,
            subject="بيانات خاصة بمطعم المشويات",
            description="تفاصيل سرية للمنشأة الأولى"
        )

        # Login as Owner 2 (Burger Craft)
        self.client.force_login(self.owner2)
        session = self.client.session
        session["active_tenant_id"] = self.tenant2.id
        session.save()

        # Attempt to access Tenant 1 ticket detail: STRICT 403 Forbidden
        forbidden_resp = self.client.get(reverse("support_ticket_detail", args=[ticket_tenant1.id]))
        self.assertEqual(forbidden_resp.status_code, 403)

        # Attempt to reply to Tenant 1 ticket: STRICT 403 Forbidden
        reply_forbidden = self.client.post(
            reverse("api_ticket_reply", args=[ticket_tenant1.id]),
            data={"message": "محاولة اختراق تذكرة منشأة أخرى"}
        )
        self.assertEqual(reply_forbidden.status_code, 403)

        # Attempt to change status of Tenant 1 ticket: STRICT 403 Forbidden
        status_forbidden = self.client.post(
            reverse("api_ticket_update_status", args=[ticket_tenant1.id]),
            data=json.dumps({"status": "closed"}),
            content_type="application/json"
        )
        self.assertEqual(status_forbidden.status_code, 403)

    # =========================================================================
    # SUITE 7: Ticket Thread Reply with Audio & Status Transition API
    # =========================================================================
    @patch("apps.communication.brevo_service.requests.post")
    def test_ticket_reply_and_status_transition_api(self, mock_post):
        """Verifies posting a reply with an audio note and transitioning ticket status."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"messageId": "<brevo-reply-msg-1@smtp.brevo.com>"}
        mock_post.return_value = mock_resp

        ticket = SupportTicket.objects.create(
            tenant=self.tenant1,
            ticket_number="TCK-202610-REPLY1",
            creator=self.owner1,
            subject="استفسار عن ربط أجهزة الطلبات",
            description="نحتاج مساعدة في ربط التابلت مع المطبخ",
            status="open"
        )

        self.client.force_login(self.owner1)
        session = self.client.session
        session["active_tenant_id"] = self.tenant1.id
        session.save()

        # Reply with audio note
        voice_file = SimpleUploadedFile("reply_voice.webm", b"\x1aE\xdf\xa3fakeaudio", content_type="audio/webm")
        reply_resp = self.client.post(
            reverse("api_ticket_reply", args=[ticket.id]),
            data={
                "message": "هذا تسجيل توضيحي للخطأ الظاهر على التابلت",
                "audio_note": voice_file,
                "audio_duration": "22"
            }
        )
        self.assertEqual(reply_resp.status_code, 200)
        self.assertEqual(reply_resp.json()["status"], "success")

        # Verify TicketMessage & attachment
        msg = ticket.messages.first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.sender_type, "tenant")
        self.assertIn("تسجيل توضيحي", msg.message)
        self.assertEqual(msg.attachments.count(), 1)
        self.assertEqual(msg.attachments.first().file_type, "audio")
        self.assertEqual(msg.attachments.first().duration_seconds, 22)

        # Status transition to resolved
        status_resp = self.client.post(
            reverse("api_ticket_update_status", args=[ticket.id]),
            data=json.dumps({"status": "resolved"}),
            content_type="application/json"
        )
        self.assertEqual(status_resp.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "resolved")
        self.assertIsNotNone(ticket.resolved_at)

    # =========================================================================
    # SUITE 8: Admin Direct Custom Email Tool & Connection Test
    # =========================================================================
    @patch("apps.communication.brevo_service.requests.post")
    def test_admin_send_direct_custom_email_view(self, mock_post):
        """Verifies Django Admin custom email composition screen and dispatch via Brevo."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"messageId": "<brevo-direct-custom-001@smtp.brevo.com>"}
        mock_post.return_value = mock_resp

        self.client.force_login(self.superadmin)

        # GET form
        get_resp = self.client.get(reverse("admin_brevo_send_email"))
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn("إرسال بريد إلكتروني مخصص عبر Brevo", get_resp.content.decode("utf-8"))

        # POST custom email
        post_resp = self.client.post(
            reverse("admin_brevo_send_email"),
            data={
                "recipient_email": "vip-client@restaurant.com",
                "recipient_name": "المدير التنفيذي",
                "subject": "رسالة خاصة من الإدارة العامة",
                "body_content": "يسرنا إبلاغكم بإطلاق الميزات الجديدة."
            }
        )
        self.assertEqual(post_resp.status_code, 200)
        self.assertIn("تم إرسال البريد الإلكتروني بنجاح", post_resp.content.decode("utf-8"))

        # Verify EmailLog created
        log = EmailLog.objects.filter(recipient_email="vip-client@restaurant.com").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, "sent")
        self.assertEqual(log.brevo_message_id, "<brevo-direct-custom-001@smtp.brevo.com>")

    @patch("apps.communication.admin.requests.get")
    def test_admin_brevo_test_connection_action(self, mock_get):
        """Verifies BrevoConfigurationAdmin test connection action."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "email": "hamed3alii.11@gmail.com",
            "companyName": "motanem",
            "plan": [{"credits": 300}]
        }
        mock_get.return_value = mock_resp

        self.client.force_login(self.superadmin)
        resp = self.client.get(reverse("admin:brevo_test_connection"), follow=True)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        self.assertIn("تم الاتصال بحساب Brevo بنجاح", content)

    # =========================================================================
    # SUITE 9: Email Verification Code Purpose Handling
    # =========================================================================
    @patch("apps.communication.brevo_service.requests.post")
    def test_email_verification_code_purpose(self, mock_post):
        """Verifies email verification purpose code generation and delivery."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"messageId": "<brevo-email-verify-55@smtp.brevo.com>"}
        mock_post.return_value = mock_resp

        code_obj = VerificationCode.generate_code(
            email="newstaff@grillhouse.com",
            user=self.owner1,
            purpose="email_verification",
            expiry_hours=1
        )
        self.assertEqual(code_obj.purpose, "email_verification")
        self.assertTrue(code_obj.is_valid)

        res = brevo_service.send_email_verification_code(
            email="newstaff@grillhouse.com",
            code=code_obj.code,
            user=self.owner1
        )
        self.assertEqual(res["status"], "success")

    # =========================================================================
    # SUITE 10: Django Admin User & Customer Direct Email Actions
    # =========================================================================
    def test_user_and_customer_admin_direct_email_actions(self):
        """Verifies direct Brevo email actions are properly registered on User and Customer admin models."""
        rf = RequestFactory()
        req = rf.get("/admin/")
        req.user = self.superadmin

        # 1. User Admin Actions
        user_admin = admin.site._registry.get(User)
        self.assertIsNotNone(user_admin)
        user_actions = user_admin.get_actions(req)
        self.assertIn("send_custom_brevo_email_to_users", user_actions)

        # Trigger action on user
        user_qs = User.objects.filter(pk=self.owner1.pk)
        redir_user = send_custom_brevo_email_to_users(user_admin, req, user_qs)
        self.assertEqual(redir_user.status_code, 302)
        self.assertIn("email=owner%40grillhouse.com", redir_user.url)

        # 2. Customer Admin Actions
        customer = Customer.objects.create(
            tenant=self.tenant1,
            name="سعد الشهري",
            phone="+966555112233",
            email="saad.customer@example.com"
        )
        customer_admin = admin.site._registry.get(Customer)
        self.assertIsNotNone(customer_admin)
        customer_actions = customer_admin.get_actions(req)
        self.assertIn("send_custom_brevo_email_to_customers", customer_actions)

        # Trigger action on customer
        cust_qs = Customer.objects.filter(pk=customer.pk)
        redir_cust = send_custom_brevo_email_to_customers(customer_admin, req, cust_qs)
        self.assertEqual(redir_cust.status_code, 302)
        self.assertIn("email=saad.customer%40example.com", redir_cust.url)

    # =========================================================================
    # SUITE 11: Webhook Inbound Base64 Attachments & HTML Ticket Extraction
    # =========================================================================
    def test_brevo_inbound_webhook_with_attachments_and_html_matching(self):
        """Verifies inbound email webhook extracts ticket ID from HTML body and ingests attachments."""
        ticket = SupportTicket.objects.create(
            tenant=self.tenant1,
            ticket_number="TCK-202611-7788",
            creator=self.owner1,
            subject="عطل في الطابعة الشبكية",
            description="الشبكة غير متصلة",
            status="open"
        )

        fake_png_bytes = b"\x89PNG\r\n\x1a\nfakeimagebytes123"
        fake_b64 = base64.b64encode(fake_png_bytes).decode("ascii")

        inbound_payload = {
            "items": [
                {
                    "MessageId": "<inbound-attach-test-01@customer.com>",
                    "From": {"Address": "owner@grillhouse.com", "Name": "أحمد الغامدي"},
                    "To": [{"Address": "support@motaem.com"}],
                    "Subject": "Re: استفسار عن الشبكة",  # Ticket ID intentionally omitted from Subject!
                    "RawTextBody": "أرفق لكم صورة من رسالة الخطأ الظاهرة على الشاشة.",
                    "RawHtmlBody": "<div><p>أرفق لكم صورة من رسالة الخطأ الظاهرة على الشاشة.</p><footer>تذكرة الدعم: [TCK-202611-7788]</footer></div>",
                    "Attachments": [
                        {
                            "Name": "error_screen.png",
                            "ContentType": "image/png",
                            "ContentLength": len(fake_png_bytes),
                            "Content": fake_b64
                        }
                    ]
                }
            ]
        }

        resp = self.client.post(
            reverse("brevo_inbound_webhook"),
            data=json.dumps(inbound_payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "success")

        # Verify message created on the ticket
        msg = ticket.messages.first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.sender_type, "tenant")
        self.assertIn("أرفق لكم صورة", msg.message)

        # Verify attachment was decoded and saved
        attachment = msg.attachments.first()
        self.assertIsNotNone(attachment)
        self.assertEqual(attachment.file_name, "error_screen.png")
        self.assertEqual(attachment.file_type, "image")
        self.assertEqual(attachment.file_size, len(fake_png_bytes))

    # =========================================================================
    # SUITE 12: Brevo Inbound Webhook Secret Authentication
    # =========================================================================
    def test_brevo_inbound_webhook_secret_enforcement(self):
        """Verifies webhook_secret enforces 403 when configured and invalid."""
        config = BrevoConfiguration.get_config()
        config.webhook_secret = "Secr3tToken-123456"
        config.save()

        payload = {"items": [{"Subject": "Hello", "RawTextBody": "Test without ticket"}]}

        # 1. No secret provided -> 403 Forbidden
        fail_resp = self.client.post(
            reverse("brevo_inbound_webhook"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(fail_resp.status_code, 403)

        # 2. Invalid secret provided -> 403 Forbidden
        bad_token_resp = self.client.post(
            reverse("brevo_inbound_webhook") + "?token=wrong-token",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(bad_token_resp.status_code, 403)

        # 3. Valid secret via query parameter ?secret= -> 200 OK
        ok_param_resp = self.client.post(
            reverse("brevo_inbound_webhook") + "?secret=Secr3tToken-123456",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(ok_param_resp.status_code, 200)

        # 4. Valid secret via X-Webhook-Secret header -> 200 OK
        ok_hdr_resp = self.client.post(
            reverse("brevo_inbound_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_WEBHOOK_SECRET="Secr3tToken-123456"
        )
        self.assertEqual(ok_hdr_resp.status_code, 200)

        # Reset secret
        config.webhook_secret = ""
        config.save()

    # =========================================================================
    # SUITE 13: Dedicated Send Verification Code API & Verification Workflow
    # =========================================================================
    @patch("apps.communication.brevo_service.requests.post")
    def test_send_verification_code_api_and_email_verification_flow(self, mock_post):
        """Verifies end-to-end API dispatch of email verification code and marking code used."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"messageId": "<brevo-email-vcode-99@smtp.brevo.com>"}
        mock_post.return_value = mock_resp

        # Step 1: Send verification code via API
        send_resp = self.client.post(
            reverse("api_send_verification_code"),
            data=json.dumps({
                "email": "verify-user@example.com",
                "purpose": "email_verification"
            }),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(send_resp.status_code, 200)
        send_data = send_resp.json()
        self.assertEqual(send_data["status"], "success")

        # Check DB code object
        code_obj = VerificationCode.objects.filter(email="verify-user@example.com", purpose="email_verification").first()
        self.assertIsNotNone(code_obj)
        self.assertEqual(len(code_obj.code), 6)
        self.assertTrue(code_obj.is_valid)

        # Step 2: Verify code with purpose=email_verification
        verify_resp = self.client.post(
            reverse("api_verify_code"),
            data=json.dumps({
                "email": "verify-user@example.com",
                "code": code_obj.code,
                "purpose": "email_verification"
            }),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(verify_resp.status_code, 200)
        verify_data = verify_resp.json()
        self.assertEqual(verify_data["status"], "success")
        self.assertTrue(verify_data.get("verified"))

        # Step 3: Verify code was marked is_used in DB
        code_obj.refresh_from_db()
        self.assertTrue(code_obj.is_used)
        self.assertFalse(code_obj.is_valid)

    # =========================================================================
    # SUITE 14: Support Reply Status Transition
    # =========================================================================
    @patch("apps.communication.brevo_service.requests.post")
    def test_support_reply_transitions_open_ticket_to_in_progress(self, mock_post):
        """Verifies that when support staff replies to an open ticket, its status transitions to in_progress."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"messageId": "<brevo-supp-reply-1@smtp.brevo.com>"}
        mock_post.return_value = mock_resp

        ticket = SupportTicket.objects.create(
            tenant=self.tenant1,
            ticket_number="TCK-202611-STATUS1",
            creator=self.owner1,
            subject="استفسار مفتوح",
            description="ننتظر رد الدعم",
            status="open"
        )

        # Superadmin / Support agent login
        self.client.force_login(self.superadmin)
        reply_resp = self.client.post(
            reverse("api_ticket_reply", args=[ticket.id]),
            data={"message": "أهلاً بك، نحن نعمل على حل المشكلة وسنوافيك بالرد."}
        )
        self.assertEqual(reply_resp.status_code, 200)
        data = reply_resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["sender_type"], "support")

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "in_progress")

    # =========================================================================
    # SUITE 15: Admin Live Chat Reply API with Brevo Outbound Notification & Media
    # =========================================================================
    @patch("apps.communication.brevo_service.requests.post")
    def test_admin_ticket_reply_with_brevo_and_media(self, mock_post):
        """Verifies staff admin reply with Brevo notification and media attachment."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"messageId": "<brevo-admin-reply-1001@smtp.brevo.com>"}
        mock_post.return_value = mock_resp

        ticket = SupportTicket.objects.create(
            tenant=self.tenant1,
            ticket_number="TCK-202611-ADMIN01",
            creator=self.owner1,
            subject="مشكلة في استيراد قائمة الطعام",
            description="ملف الإكسيل لا يتم رفعه بشكل صحيح",
            status="open"
        )

        # 1. Non-staff user strictly blocked with 403 Forbidden
        self.client.force_login(self.owner1)
        forbidden_resp = self.client.post(
            reverse("api_admin_ticket_reply", args=[ticket.id]),
            data={"message": "محاولة رد غير مصرح بها"}
        )
        self.assertEqual(forbidden_resp.status_code, 403)

        # 2. Staff user successfully replies with attachment and dispatches Brevo alert
        self.client.force_login(self.superadmin)
        valid_img = SimpleUploadedFile("solution_guide.png", b"\x89PNG\r\n\x1a\nsolutionpngbytes", content_type="image/png")

        reply_resp = self.client.post(
            reverse("api_admin_ticket_reply", args=[ticket.id]),
            data={
                "message": "مرحباً، تم فحص الملف وإصلاح صيغة الأعمدة المرفقة.",
                "notify_customer": "true",
                "is_internal": "false",
                "attachments": [valid_img]
            }
        )
        self.assertEqual(reply_resp.status_code, 200)
        data = reply_resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["sender_type"], "support")
        self.assertFalse(data["is_internal"])
        self.assertTrue(data["email_sent"])
        self.assertEqual(len(data["attachments"]), 1)
        self.assertEqual(data["attachments"][0]["file_name"], "solution_guide.png")

        # Verify DB TicketMessage and attachment
        msg = ticket.messages.first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.sender, self.superadmin)
        self.assertFalse(msg.is_internal)
        self.assertEqual(msg.attachments.count(), 1)
        self.assertEqual(msg.attachments.first().file_type, "image")

        # Verify ticket status moved to in_progress
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "in_progress")

        # Verify Brevo API was called with ticket subject and reference
        self.assertTrue(mock_post.called)
        sent_payload = mock_post.call_args[1]["json"]
        self.assertIn("TCK-202611-ADMIN01", sent_payload["subject"])
        self.assertEqual(sent_payload["to"][0]["email"], "owner@grillhouse.com")

        # 3. Oversized file (> 25MB) strictly rejected with 400
        oversized = SimpleUploadedFile("big.bin", b"0" * (25 * 1024 * 1024 + 1024), content_type="application/octet-stream")
        oversized_resp = self.client.post(
            reverse("api_admin_ticket_reply", args=[ticket.id]),
            data={"message": "رد بملف ضخم", "attachments": [oversized]}
        )
        self.assertEqual(oversized_resp.status_code, 400)
        self.assertIn("25 ميجابايت", oversized_resp.json()["message"])

    # =========================================================================
    # SUITE 16: Admin Internal Notes Isolation & Brevo Suppression
    # =========================================================================
    @patch("apps.communication.brevo_service.requests.post")
    def test_admin_internal_note_suppresses_email_and_hides_from_customer(self, mock_post):
        """Verifies internal notes never trigger email to customer and are hidden from customer view."""
        ticket = SupportTicket.objects.create(
            tenant=self.tenant1,
            ticket_number="TCK-202611-INTERNAL1",
            creator=self.owner1,
            subject="فحص داخلي لنظام الفواتير",
            description="العميل يطلب تعديل رقم السجل الضريبي",
            status="in_progress"
        )

        self.client.force_login(self.superadmin)
        note_resp = self.client.post(
            reverse("api_admin_ticket_reply", args=[ticket.id]),
            data={
                "message": "ملاحظة لفريق الحسابات: يرجى التحقق من شهادة ضريبة القيمة المضافة أولاً قبل الاعتماد.",
                "is_internal": "true",
                "notify_customer": "true"  # Should be strictly ignored when is_internal=true
            }
        )
        self.assertEqual(note_resp.status_code, 200)
        data = note_resp.json()
        self.assertTrue(data["is_internal"])
        self.assertFalse(data["email_sent"])

        # Verify no Brevo HTTP call was dispatched
        mock_post.assert_not_called()

        # Verify message created with is_internal=True
        msg = ticket.messages.first()
        self.assertIsNotNone(msg)
        self.assertTrue(msg.is_internal)

        # Verify customer (owner1) accessing ticket detail view CANNOT see the internal note
        self.client.force_login(self.owner1)
        session = self.client.session
        session["active_tenant_id"] = self.tenant1.id
        session.save()

        detail_resp = self.client.get(reverse("support_ticket_detail", args=[ticket.id]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertNotIn("شهادة ضريبة القيمة المضافة", detail_resp.content.decode("utf-8"))

        # Verify staff user CAN see the internal note in ticket detail
        self.client.force_login(self.superadmin)
        staff_detail_resp = self.client.get(reverse("support_ticket_detail", args=[ticket.id]))
        self.assertEqual(staff_detail_resp.status_code, 200)
        self.assertIn("شهادة ضريبة القيمة المضافة", staff_detail_resp.content.decode("utf-8"))

    # =========================================================================
    # SUITE 17: Admin Send & Close Ticket Action
    # =========================================================================
    @patch("apps.communication.brevo_service.requests.post")
    def test_admin_reply_and_close_ticket(self, mock_post):
        """Verifies close_ticket=true immediately transitions status to closed."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"messageId": "<brevo-close-msg-99@smtp.brevo.com>"}
        mock_post.return_value = mock_resp

        ticket = SupportTicket.objects.create(
            tenant=self.tenant1,
            ticket_number="TCK-202611-CLOSE1",
            creator=self.owner1,
            subject="طلب إغلاق حساب تجريبي",
            description="نود إنهاء التجربة",
            status="open"
        )

        self.client.force_login(self.superadmin)
        close_resp = self.client.post(
            reverse("api_admin_ticket_reply", args=[ticket.id]),
            data={
                "message": "تم تنفيذ طلبكم بنجاح وتم إغلاق التذكرة نهائياً.",
                "close_ticket": "true"
            }
        )
        self.assertEqual(close_resp.status_code, 200)
        data = close_resp.json()
        self.assertEqual(data["ticket_status"], "closed")

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "closed")
        self.assertIsNotNone(ticket.closed_at)

    # =========================================================================
    # SUITE 18: Message Deletion & Media Purge Endpoint
    # =========================================================================
    def test_admin_delete_ticket_message_and_attachments(self):
        """Verifies staff can delete a message and purge its attachments from storage."""
        ticket = SupportTicket.objects.create(
            tenant=self.tenant1,
            ticket_number="TCK-202611-DEL01",
            creator=self.owner1,
            subject="تذكرة لاختبار الحذف",
            description="وصف التذكرة"
        )
        msg = TicketMessage.objects.create(
            ticket=ticket,
            sender=self.superadmin,
            sender_type="support",
            message="رسالة سيتم حذفها"
        )
        dummy_file = SimpleUploadedFile("to_delete.png", b"\x89PNG\r\nfake", content_type="image/png")
        att = TicketAttachment.objects.create(
            ticket=ticket,
            message=msg,
            file=dummy_file,
            file_name="to_delete.png",
            file_type="image",
            file_size=10
        )

        # 1. Non-staff receives 403
        self.client.force_login(self.owner1)
        fail_del = self.client.post(reverse("api_admin_delete_message", args=[msg.id]))
        self.assertEqual(fail_del.status_code, 403)
        self.assertTrue(TicketMessage.objects.filter(pk=msg.id).exists())

        # 2. Staff user successfully deletes message and attachments
        self.client.force_login(self.superadmin)
        ok_del = self.client.post(reverse("api_admin_delete_message", args=[msg.id]))
        self.assertEqual(ok_del.status_code, 200)
        self.assertEqual(ok_del.json()["status"], "success")

        # Verify records removed from DB
        self.assertFalse(TicketMessage.objects.filter(pk=msg.id).exists())
        self.assertFalse(TicketAttachment.objects.filter(pk=att.id).exists())

    # =========================================================================
    # SUITE 19: Django Admin SupportTicket Change View Rendering
    # =========================================================================
    def test_support_ticket_django_admin_change_view_workspace(self):
        """Verifies Django admin change_form renders live chat workspace with ticket metadata."""
        ticket = SupportTicket.objects.create(
            tenant=self.tenant1,
            ticket_number="TCK-202611-ADMINVIEW",
            creator=self.owner1,
            subject="عطل في الطابعة اللاسلكية",
            description="الشبكة تقطع باستمرار",
            priority="high",
            status="open"
        )
        TicketMessage.objects.create(
            ticket=ticket,
            sender=self.owner1,
            sender_type="tenant",
            message="الرجاء حل المشكلة على وجه السرعة."
        )

        self.client.force_login(self.superadmin)
        admin_url = reverse("admin:core_supportticket_change", args=[ticket.id])
        resp = self.client.get(admin_url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode("utf-8")
        # Top bar elements
        self.assertIn("TCK-202611-ADMINVIEW", content)
        self.assertIn("عطل في الطابعة اللاسلكية", content)
        self.assertIn("مطعم المشويات الأصيل", content)
        # Chat workspace elements
        self.assertIn("محادثة الدعم الفني الحية والتفاعلية", content)
        self.assertIn("الرجاء حل المشكلة على وجه السرعة.", content)
        self.assertIn("حذف الرسالة", content)
        self.assertIn("إرسال إشعار بريدي عبر", content)
        self.assertIn("ملاحظة داخلية", content)
        self.assertIn("إرسال وإغلاق التذكرة", content)
        self.assertIn("quick-status-dropdown", content)

    # =========================================================================
    # SUITE 20: Admin Live Chat Edge Cases & Method Guards
    # =========================================================================
    @patch("apps.communication.brevo_service.requests.post")
    def test_admin_ticket_reply_attachment_only_fallback_and_guards(self, mock_post):
        """Verifies attachment-only admin reply sets proper Arabic fallback message and HTTP 405 guards."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"messageId": "<brevo-fallback-test@smtp.brevo.com>"}
        mock_post.return_value = mock_resp

        ticket = SupportTicket.objects.create(
            tenant=self.tenant1,
            ticket_number="TCK-202611-FALLBACK1",
            creator=self.owner1,
            subject="استفسار عن مرفق الرد",
            description="طلب توضيح",
            status="open"
        )

        self.client.force_login(self.superadmin)

        # 1. Reply with file ONLY (empty message text)
        pdf_file = SimpleUploadedFile("guide.pdf", b"%PDF-1.4fakecontent", content_type="application/pdf")
        reply_resp = self.client.post(
            reverse("api_admin_ticket_reply", args=[ticket.id]),
            data={
                "message": "",
                "notify_customer": "true",
                "attachments": [pdf_file]
            }
        )
        self.assertEqual(reply_resp.status_code, 200)
        data = reply_resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["message"], "📎 مرفقات من فريق الدعم الفني")
        self.assertEqual(data["ticket_status"], "in_progress")
        self.assertEqual(len(data["attachments"]), 1)
        self.assertEqual(data["attachments"][0]["file_name"], "guide.pdf")

        # Verify Brevo notification body contains the fallback message
        self.assertTrue(mock_post.called)
        sent_html = mock_post.call_args[1]["json"]["htmlContent"]
        self.assertIn("📎 مرفقات من فريق الدعم الفني", sent_html)

        # 2. HTTP GET on api_admin_ticket_reply strictly returns 405 Method Not Allowed JSON
        get_reply_resp = self.client.get(reverse("api_admin_ticket_reply", args=[ticket.id]))
        self.assertEqual(get_reply_resp.status_code, 405)
        self.assertEqual(get_reply_resp.json()["status"], "error")

        # 3. HTTP GET on api_admin_delete_message strictly returns 405 Method Not Allowed JSON
        msg_id = data["message_id"]
        get_del_resp = self.client.get(reverse("api_admin_delete_message", args=[msg_id]))
        self.assertEqual(get_del_resp.status_code, 405)
        self.assertEqual(get_del_resp.json()["status"], "error")

        # 4. Deletion of non-existent message returns 404
        non_existent_del = self.client.post(reverse("api_admin_delete_message", args=[9999999]))
        self.assertEqual(non_existent_del.status_code, 404)

        # 5. Status update with invalid status returns 400
        invalid_status_resp = self.client.post(
            reverse("api_ticket_update_status", args=[ticket.id]),
            data=json.dumps({"status": "invalid_status_xyz"}),
            content_type="application/json"
        )
        self.assertEqual(invalid_status_resp.status_code, 400)




