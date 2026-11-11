import os
import sys
import json
import mimetypes
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, EndpointConnectionError
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = "Migrate all local media files from MEDIA_ROOT to MinIO S3 bucket idempotently with size verification."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate the migration without actually uploading files to MinIO.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-upload all files even if they already exist in MinIO with matching size.",
        )
        parser.add_argument(
            "--bucket",
            type=str,
            default=getattr(settings, "AWS_STORAGE_BUCKET_NAME", "motaem-media"),
            help="Target MinIO bucket name (defaults to AWS_STORAGE_BUCKET_NAME).",
        )
        parser.add_argument(
            "--endpoint-url",
            type=str,
            default=None,
            help="MinIO S3 endpoint URL (defaults to AWS_S3_ENDPOINT_URL with local host fallback).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]
        bucket_name = options["bucket"]
        endpoint_url = options["endpoint_url"] or getattr(settings, "AWS_S3_ENDPOINT_URL", "http://minio:9000")

        # In local runs outside Docker, resolve minio:9000 to localhost:9200 if needed
        if "minio:9000" in endpoint_url:
            import socket
            try:
                socket.gethostbyname("minio")
            except Exception:
                endpoint_url = endpoint_url.replace("minio:9000", "127.0.0.1:9200")

        access_key = getattr(settings, "AWS_ACCESS_KEY_ID", "minioadmin")
        secret_key = getattr(settings, "AWS_SECRET_ACCESS_KEY", "minioadmin123")
        region_name = getattr(settings, "AWS_S3_REGION_NAME", "us-east-1")
        media_root = str(settings.MEDIA_ROOT)

        self.stdout.write(self.style.NOTICE("=" * 70))
        self.stdout.write(self.style.NOTICE("MOTAEM MEDIA MIGRATION TO MINIO S3"))
        self.stdout.write(self.style.NOTICE("=" * 70))
        self.stdout.write(f"Source MEDIA_ROOT: {media_root}")
        self.stdout.write(f"Target Bucket:    {bucket_name}")
        self.stdout.write(f"MinIO Endpoint:   {endpoint_url}")
        self.stdout.write(f"Dry Run Mode:     {dry_run}")
        self.stdout.write(f"Force Mode:       {force}")
        self.stdout.write("-" * 70)

        if not os.path.isdir(media_root):
            raise CommandError(f"MEDIA_ROOT does not exist: {media_root}")

        # Initialize boto3 S3 client
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name,
            config=Config(signature_version="s3v4"),
        )

        # Check connectivity and bucket existence
        if not dry_run:
            try:
                s3.head_bucket(Bucket=bucket_name)
                self.stdout.write(self.style.SUCCESS(f"Bucket '{bucket_name}' verified."))
            except ClientError as e:
                err_code = e.response.get("Error", {}).get("Code", "")
                if err_code in ("404", "NoSuchBucket"):
                    self.stdout.write(self.style.WARNING(f"Bucket '{bucket_name}' not found. Creating bucket..."))
                    s3.create_bucket(Bucket=bucket_name)
                    self.stdout.write(self.style.SUCCESS(f"Bucket '{bucket_name}' created successfully."))
                else:
                    raise CommandError(f"Failed to access MinIO bucket '{bucket_name}': {e}")
            except EndpointConnectionError as e:
                raise CommandError(f"Cannot connect to MinIO endpoint '{endpoint_url}': {e}")

            # Ensure public download policy
            try:
                policy = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "PublicReadGetObject",
                            "Effect": "Allow",
                            "Principal": "*",
                            "Action": ["s3:GetObject"],
                            "Resource": [f"arn:aws:s3:::{bucket_name}/*"],
                        }
                    ],
                }
                s3.put_bucket_policy(Bucket=bucket_name, Policy=json.dumps(policy))
                self.stdout.write(self.style.SUCCESS(f"Public download policy confirmed for '{bucket_name}'."))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Warning setting bucket policy: {e}"))

        # Extra mime-type registrations
        mimetypes.add_type("video/webm", ".webm")
        mimetypes.add_type("audio/webm", ".webm")
        mimetypes.add_type("image/webp", ".webp")
        mimetypes.add_type("image/svg+xml", ".svg")

        # Discover all local media files
        all_files = []
        for root_dir, _, filenames in os.walk(media_root):
            for fname in sorted(filenames):
                full_path = os.path.join(root_dir, fname)
                rel_path = os.path.relpath(full_path, media_root).replace("\\", "/")
                all_files.append((full_path, rel_path))

        total_files = len(all_files)
        self.stdout.write(f"Discovered {total_files} media files to process.\n")

        uploaded_count = 0
        skipped_count = 0
        error_count = 0
        transferred_bytes = 0

        for idx, (full_path, rel_path) in enumerate(all_files, start=1):
            local_size = os.path.getsize(full_path)
            content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"

            # Check if object already exists with matching size
            exists_in_minio = False
            if not dry_run and not force:
                try:
                    head_resp = s3.head_object(Bucket=bucket_name, Key=rel_path)
                    remote_size = head_resp.get("ContentLength")
                    if remote_size == local_size:
                        exists_in_minio = True
                except ClientError as e:
                    err_code = e.response.get("Error", {}).get("Code", "")
                    if err_code not in ("404", "NoSuchKey"):
                        self.stdout.write(self.style.WARNING(f"[{idx}/{total_files}] Error checking {rel_path}: {e}"))

            if exists_in_minio:
                skipped_count += 1
                if skipped_count <= 5 or skipped_count % 100 == 0 or idx == total_files:
                    self.stdout.write(f"[{idx}/{total_files}] [SKIP] {rel_path} ({local_size} bytes - up to date)")
                continue

            if dry_run:
                self.stdout.write(f"[{idx}/{total_files}] [DRY-RUN] Would upload {rel_path} ({local_size} bytes, {content_type})")
                uploaded_count += 1
                transferred_bytes += local_size
                continue

            # Upload to MinIO
            try:
                with open(full_path, "rb") as f:
                    s3.put_object(
                        Bucket=bucket_name,
                        Key=rel_path,
                        Body=f,
                        ContentType=content_type,
                    )

                # Verify upload existence and byte length
                verify_head = s3.head_object(Bucket=bucket_name, Key=rel_path)
                verified_size = verify_head.get("ContentLength")
                if verified_size != local_size:
                    raise CommandError(f"Verification mismatch for {rel_path}: local={local_size}, remote={verified_size}")

                uploaded_count += 1
                transferred_bytes += local_size
                if uploaded_count <= 10 or uploaded_count % 50 == 0 or idx == total_files:
                    self.stdout.write(self.style.SUCCESS(f"[{idx}/{total_files}] [UPLOADED] {rel_path} ({local_size} bytes) -> Verified OK"))
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(f"[{idx}/{total_files}] [ERROR] Failed uploading {rel_path}: {e}"))

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.NOTICE("MIGRATION SUMMARY"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Total Files Found:   {total_files}")
        self.stdout.write(f"Files Uploaded:      {uploaded_count}")
        self.stdout.write(f"Files Skipped:       {skipped_count}")
        self.stdout.write(f"Upload Errors:       {error_count}")
        self.stdout.write(f"Bytes Transferred:   {transferred_bytes / (1024 * 1024):.2f} MB ({transferred_bytes} bytes)")

        if error_count > 0:
            raise CommandError(f"Migration completed with {error_count} upload errors.")

        self.stdout.write(self.style.SUCCESS("All files verified successfully in MinIO storage! 100% COMPLETE."))
