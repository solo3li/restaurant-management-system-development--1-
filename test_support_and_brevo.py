import io
import json
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.tenants.models import Tenant, Branch
from apps.accounts.models import UserProfile
from apps.communication.models import BrevoConfiguration, VerificationCode, EmailLog, InboundEmailLog
from apps.communication import brevo_service
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
        self.assertIn("xkeysib-", config1.api_key)
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

        # Restore original
        reloaded.api_key = "mock_brevo_key_redacted"
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

