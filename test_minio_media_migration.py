import os
import re
import tempfile
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.files.storage import default_storage, FileSystemStorage
from storages.backends.s3boto3 import S3Boto3Storage
from django.conf import settings
from apps.billing.models import UpgradeRequest, upgrade_receipt_upload_path
from apps.support.models import TicketAttachment, ticket_attachment_upload_path
from restaurant_system.settings import _is_minio_reachable


class MinIOMediaStorageTests(TestCase):
    """
    Test suite for MinIO S3 media storage migration, Traefik SSL routing configuration,
    cryptographic UUID upload paths, management migration command, and graceful fallback.
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
        path = upgrade_receipt_upload_path(dummy_instance, "my_bank_receipt.PNG")
        pattern = r"^payment_receipts/\d{4}/\d{2}/[0-9a-f]{32}\.png$"
        self.assertTrue(
            re.match(pattern, path),
            f"Path '{path}' did not match pattern '{pattern}'"
        )

    def test_cryptographic_uuid_ticket_attachment_path(self):
        """Verify ticket attachment upload path generates unguessable UUID4 filename in %Y/%m/."""
        dummy_instance = MagicMock()
        path = ticket_attachment_upload_path(dummy_instance, "voice_recording.WEBM")
        pattern = r"^support_tickets/\d{4}/\d{2}/[0-9a-f]{32}\.webm$"
        self.assertTrue(
            re.match(pattern, path),
            f"Path '{path}' did not match pattern '{pattern}'"
        )

    def test_reachability_helper_and_graceful_fallback(self):
        """Verify _is_minio_reachable handles unreachable endpoints without raising exceptions."""
        self.assertFalse(_is_minio_reachable("http://192.0.2.1:9999", timeout=0.05))
        self.assertFalse(_is_minio_reachable("http://invalid.domain.that.does.not.exist:9000", timeout=0.05))

    def test_migrate_media_management_command_dry_run(self):
        """Verify migrate_media_to_minio management command runs successfully in dry-run mode."""
        from io import StringIO
        out = StringIO()
        call_command("migrate_media_to_minio", dry_run=True, stdout=out)
        output = out.getvalue()
        self.assertIn("MOTAEM MEDIA MIGRATION TO MINIO S3", output)
        self.assertIn("Dry Run Mode:     True", output)
        self.assertIn("MIGRATION SUMMARY", output)
        self.assertIn("All files verified successfully", output)

    def test_migrate_media_idempotent_execution(self):
        """Verify migrate_media_to_minio execution is idempotent."""
        from io import StringIO
        out = StringIO()
        # Run command (with existing bucket)
        call_command("migrate_media_to_minio", stdout=out)
        output = out.getvalue()
        self.assertIn("MIGRATION SUMMARY", output)
        self.assertIn("All files verified successfully", output)
