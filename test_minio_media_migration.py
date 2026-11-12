import os
import re
import tempfile
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command, CommandError
from django.core.files.storage import default_storage, FileSystemStorage
from storages.backends.s3boto3 import S3Boto3Storage
from django.conf import settings
from django.contrib.auth.models import User
from apps.billing.models import UpgradeRequest, SubscriptionPlan, upgrade_receipt_upload_path
from apps.support.models import SupportTicket, TicketAttachment, ticket_attachment_upload_path
from apps.tenants.models import Tenant
from restaurant_system.settings import _is_minio_reachable


class MinIOMediaStorageTests(TestCase):
    """
    Comprehensive test suite for MinIO S3 media storage migration, Traefik SSL routing,
    cryptographic UUID upload paths, graceful fallback, and the migration management command.
    """

    def test_settings_storage_configuration(self):
        """Verify S3Boto3 / MinIO settings adhere to production specifications."""
        self.assertEqual(getattr(settings, "AWS_STORAGE_BUCKET_NAME", ""), "motaem-media")
        self.assertEqual(getattr(settings, "AWS_S3_CUSTOM_DOMAIN", ""), "uggu.space/media")
        self.assertFalse(getattr(settings, "AWS_QUERYSTRING_AUTH", True))
        self.assertFalse(getattr(settings, "AWS_S3_FILE_OVERWRITE", True))

    def test_s3boto3_storage_url_generation(self):
        """Verify S3Boto3Storage generates clean HTTPS URL matching Traefik routing without query params."""
        storage = S3Boto3Storage(
            bucket_name="motaem-media",
            custom_domain="uggu.space/media",
            querystring_auth=False,
        )
        url = storage.url("menu_items/angus_burger.jpg")
        self.assertEqual(url, "https://uggu.space/media/menu_items/angus_burger.jpg")
        self.assertNotIn("?", url)
        self.assertNotIn("AWSAccessKeyId", url)
        self.assertNotIn("Signature", url)

    def test_cryptographic_uuid_upgrade_receipt_path(self):
        """Verify upgrade receipt upload path generates unguessable UUID4 filename in %Y/%m/."""
        dummy_instance = MagicMock()

        # 1. Standard filename
        path = upgrade_receipt_upload_path(dummy_instance, "my_bank_receipt.PNG")
        pattern = r"^payment_receipts/\d{4}/\d{2}/[0-9a-f]{32}\.png$"
        self.assertTrue(re.match(pattern, path), f"Path '{path}' did not match '{pattern}'")

        # 2. Dotfile (e.g., .png from photo picker)
        dot_path = upgrade_receipt_upload_path(dummy_instance, ".png")
        self.assertTrue(re.match(pattern, dot_path), f"Dotfile path '{dot_path}' lost extension")

        # 3. No extension
        no_ext_path = upgrade_receipt_upload_path(dummy_instance, "raw_receipt_file")
        pattern_no_ext = r"^payment_receipts/\d{4}/\d{2}/[0-9a-f]{32}$"
        self.assertTrue(re.match(pattern_no_ext, no_ext_path), f"Path '{no_ext_path}' invalid")

        # 4. Arabic / unicode filename
        ar_path = upgrade_receipt_upload_path(dummy_instance, "إيصال_التحويل_البنكي.PDF")
        pattern_pdf = r"^payment_receipts/\d{4}/\d{2}/[0-9a-f]{32}\.pdf$"
        self.assertTrue(re.match(pattern_pdf, ar_path), f"Path '{ar_path}' invalid")

    def test_cryptographic_uuid_ticket_attachment_path(self):
        """Verify ticket attachment upload path generates unguessable UUID4 filename in %Y/%m/."""
        dummy_instance = MagicMock()

        # 1. Standard webm voice note
        path = ticket_attachment_upload_path(dummy_instance, "voice_recording.WEBM")
        pattern = r"^support_tickets/\d{4}/\d{2}/[0-9a-f]{32}\.webm$"
        self.assertTrue(re.match(pattern, path), f"Path '{path}' did not match '{pattern}'")

        # 2. Dotfile (e.g., .webm)
        dot_path = ticket_attachment_upload_path(dummy_instance, ".webm")
        self.assertTrue(re.match(pattern, dot_path), f"Dotfile path '{dot_path}' lost extension")

        # 3. Arabic screenshot filename
        ar_path = ticket_attachment_upload_path(dummy_instance, "لقطة_شاشة_الخطأ.JPEG")
        pattern_jpg = r"^support_tickets/\d{4}/\d{2}/[0-9a-f]{32}\.jpeg$"
        self.assertTrue(re.match(pattern_jpg, ar_path), f"Path '{ar_path}' invalid")

    def test_real_model_upload_upgrade_request(self):
        """Verify real UpgradeRequest model persists receipt with UUID4 path and resolves clean URL."""
        user = User.objects.create_user(username="receipt_tester", password="pwd")
        tenant = Tenant.objects.create(name="Receipt Test Tenant", slug="receipt-test-tenant")
        plan = SubscriptionPlan.objects.create(code="test_growth", name="Growth", price_monthly=99)

        receipt_content = b"fake binary image bytes for receipt"
        upload_file = SimpleUploadedFile("my_receipt.jpg", receipt_content, content_type="image/jpeg")
        req = UpgradeRequest.objects.create(
            tenant=tenant,
            requested_plan=plan,
            payment_method="vodafone_cash",
            receipt=upload_file,
        )

        pattern = r"^payment_receipts/\d{4}/\d{2}/[0-9a-f]{32}\.jpg$"
        self.assertTrue(re.match(pattern, req.receipt.name), f"Saved path {req.receipt.name} invalid")
        self.assertTrue(req.receipt.url.startswith("https://uggu.space/media/payment_receipts/"))
        self.assertTrue(req.receipt.storage.exists(req.receipt.name))

        # Cleanup
        req.receipt.delete(save=False)
        req.delete()
        plan.delete()
        tenant.delete()
        user.delete()

    def test_real_model_upload_ticket_attachment(self):
        """Verify real TicketAttachment model persists file with UUID4 path and resolves clean URL."""
        user = User.objects.create_user(username="ticket_tester", password="pwd")
        tenant = Tenant.objects.create(name="Ticket Test Tenant", slug="ticket-test-tenant")
        ticket = SupportTicket.objects.create(
            tenant=tenant,
            creator=user,
            subject="Test Attachment Ticket",
            description="Testing ticket file upload",
        )

        att_content = b"fake binary webm audio data"
        upload_file = SimpleUploadedFile("voice_note.webm", att_content, content_type="audio/webm")
        att = TicketAttachment.objects.create(
            ticket=ticket,
            file=upload_file,
            file_type="audio/webm",
            file_size=len(att_content),
        )

        pattern = r"^support_tickets/\d{4}/\d{2}/[0-9a-f]{32}\.webm$"
        self.assertTrue(re.match(pattern, att.file.name), f"Saved path {att.file.name} invalid")
        self.assertTrue(att.file.url.startswith("https://uggu.space/media/support_tickets/"))
        self.assertTrue(att.file.storage.exists(att.file.name))

        # Cleanup
        att.file.delete(save=False)
        att.delete()
        ticket.delete()
        tenant.delete()
        user.delete()

    def test_reachability_helper_and_graceful_fallback(self):
        """Verify _is_minio_reachable handles unreachable endpoints without raising exceptions."""
        self.assertFalse(_is_minio_reachable("http://192.0.2.1:9999", timeout=0.05))
        self.assertFalse(_is_minio_reachable("http://invalid.domain.that.does.not.exist:9000", timeout=0.05))

    def test_migrate_media_management_command_dry_run(self):
        """Verify migrate_media_to_minio management command runs successfully in dry-run mode on source directory."""
        from io import StringIO
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "menu_items")
            os.makedirs(nested)
            with open(os.path.join(nested, "burger.jpg"), "wb") as f:
                f.write(b"sample burger image bytes")
            with open(os.path.join(tmpdir, ".data_imported"), "wb") as f:
                pass  # 0-byte file

            out = StringIO()
            call_command("migrate_media_to_minio", source_dir=tmpdir, dry_run=True, stdout=out)
            output = out.getvalue()
            self.assertIn("MOTAEM MEDIA MIGRATION TO MINIO S3", output)
            self.assertIn("Dry Run Mode:     True", output)
            self.assertIn("Total Files Found:   2", output)
            self.assertIn("MIGRATION SUMMARY", output)
            self.assertIn("All files verified successfully", output)

    def test_migrate_media_live_and_idempotent_execution(self):
        """Verify migrate_media_to_minio uploads files, verifies byte size, and is idempotent on repeat runs."""
        import uuid, boto3
        from io import StringIO
        unique_folder = f"test_cat_{uuid.uuid4().hex[:8]}"
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = os.path.join(tmpdir, unique_folder)
            os.makedirs(sub)
            test_file = os.path.join(sub, "item_sync_test.txt")
            with open(test_file, "w") as f:
                f.write("test synchronization payload")

            # First run: uploads file
            out1 = StringIO()
            call_command("migrate_media_to_minio", source_dir=tmpdir, stdout=out1)
            output1 = out1.getvalue()
            self.assertIn("Files Uploaded:      1", output1)
            self.assertIn("All files verified successfully", output1)

            # Second run: file already exists in MinIO with matching size -> skipped (idempotent)
            out2 = StringIO()
            call_command("migrate_media_to_minio", source_dir=tmpdir, stdout=out2)
            output2 = out2.getvalue()
            self.assertIn("Files Skipped:       1", output2)
            self.assertIn("Files Uploaded:      0", output2)
            self.assertIn("All files verified successfully", output2)

            # Force run: re-uploads even if up-to-date
            out3 = StringIO()
            call_command("migrate_media_to_minio", source_dir=tmpdir, force=True, stdout=out3)
            output3 = out3.getvalue()
            self.assertIn("Files Uploaded:      1", output3)

            # Cleanup remote test file
            try:
                s3 = boto3.client("s3", endpoint_url=settings.AWS_S3_ENDPOINT_URL, aws_access_key_id=settings.AWS_ACCESS_KEY_ID, aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)
                s3.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=f"{unique_folder}/item_sync_test.txt")
            except Exception:
                pass

    def test_migrate_media_unreachable_endpoint_raises_error(self):
        """Verify migrate_media_to_minio raises CommandError when target MinIO endpoint is unreachable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "file.txt"), "w") as f:
                f.write("data")
            with self.assertRaises(CommandError) as ctx:
                call_command(
                    "migrate_media_to_minio",
                    source_dir=tmpdir,
                    endpoint_url="http://127.0.0.1:54321",
                )
            self.assertIn("Cannot connect to MinIO endpoint", str(ctx.exception))
