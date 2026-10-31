import random
import string
from datetime import timedelta
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User


class BrevoConfiguration(models.Model):
    """
    إعدادات منصة Brevo للبريد الإلكتروني المباشر والمعاملاتي (Singleton):
    يُدار بالكامل من لوحة تحكم الإدارة (Django Admin) لتحديث مفتاح API، بريد المرسل، واسم المرسل.
    """
    api_key = models.CharField(
        max_length=255,
        default="mock_brevo_key_redacted",
        verbose_name="مفتاح Brevo API (API Key)",
        help_text="مفتاح API المعتمد من حساب Brevo لإرسال رسائل البريد الإلكتروني."
    )
    sender_email = models.EmailField(
        default="hamed3alii.11@gmail.com",
        verbose_name="البريد الإلكتروني المعتمد للمرسل (Sender Email)",
        help_text="عنوان البريد الإلكتروني المعتمد في Brevo Senders الذي ستصل الرسائل منه للعملاء."
    )
    sender_name = models.CharField(
        max_length=120,
        default="منظومة مطاعم Cloud Restaurant OS",
        verbose_name="اسم المرسل الظاهر (Sender Name)",
        help_text="اسم المنشأة أو النظام الظاهر في عنوان البريد الوارد لدى المستلم."
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="تفعيل الإرسال عبر Brevo",
        help_text="عند التعطيل، لن يتم إرسال رسائل بريد حقيقية للعملاء."
    )
    webhook_secret = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="رمز حماية الويب هوك (Webhook Secret / Token)",
        help_text="رمز سري اختياري للتحقق من هوية الويب هوك الوارد من Brevo."
    )
    inbound_domain = models.CharField(
        max_length=255,
        blank=True,
        default="inbound.uggu.space",
        verbose_name="نطاق استقبال البريد الوارد (Inbound Domain)",
        help_text="النطاق المخصص لاستقبال ردود العملاء البريدية."
    )
    total_sent_count = models.PositiveIntegerField(
        default=0,
        verbose_name="إجمالي الرسائل المرسلة بنجاح"
    )
    created_at = models.DateTimeField(default=timezone.now, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخر تحديث")

    class Meta:
        app_label = 'core'
        verbose_name = "إعدادات منصة البريد (Brevo Configuration)"
        verbose_name_plural = "إعدادات منصة البريد (Brevo Configuration)"

    def __str__(self):
        state = "مفعل" if self.is_active else "معطل"
        return f"Brevo Config: {self.sender_email} ({state})"

    @classmethod
    def get_config(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class VerificationCode(models.Model):
    """
    أكواد التحقق الأبجدية الرقمية المكونة من 6 خانات (Alphanumeric 6-char):
    تُستخدم في استعادة كلمة المرور، التحقق من البريد، وتأمين الحسابات.
    تتميز بمدة صلاحية دقيقة مدتها ساعة واحدة (1 Hour Expiration).
    """
    PURPOSE_CHOICES = [
        ("password_reset", "إعادة تعيين كلمة المرور"),
        ("email_verification", "تأكيد البريد الإلكتروني"),
        ("account_security", "تأكيد أمان الحساب"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="verification_codes",
        verbose_name="المستخدم"
    )
    email = models.EmailField(db_index=True, verbose_name="البريد الإلكتروني")
    code = models.CharField(max_length=10, db_index=True, verbose_name="رمز التحقق (6 خانات)")
    purpose = models.CharField(
        max_length=30,
        choices=PURPOSE_CHOICES,
        default="password_reset",
        verbose_name="الغرض من الرمز"
    )
    expires_at = models.DateTimeField(verbose_name="تاريخ انتهاء الصلاحية (1 ساعة)")
    is_used = models.BooleanField(default=False, verbose_name="تم الاستخدام؟")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        app_label = 'core'
        verbose_name = "رمز التحقق البريدي (Verification Code)"
        verbose_name_plural = "أكواد التحقق البريدية (Verification Codes)"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email} - {self.code} ({self.purpose})"

    @property
    def is_valid(self):
        """Returns True if code is not used and not expired."""
        return (not self.is_used) and (timezone.now() <= self.expires_at)

    @classmethod
    def generate_code(cls, email: str, user=None, purpose: str = "password_reset", expiry_hours: int = 1):
        """
        Generates a 6-character alphanumeric code combining uppercase letters and numbers (e.g. K7B9X2).
        Sets expiration strictly to 1 hour from generation.
        """
        # Uppercase letters and digits (A-Z, 0-9)
        characters = string.ascii_uppercase + string.digits
        # Generate 6 characters
        code = "".join(random.choices(characters, k=6))
        expires_at = timezone.now() + timedelta(hours=expiry_hours)

        return cls.objects.create(
            user=user,
            email=email.strip().lower(),
            code=code,
            purpose=purpose,
            expires_at=expires_at,
            is_used=False
        )


class EmailLog(models.Model):
    """سجل الرسائل الصادرة المرسلة عبر Brevo لمتابعة حالة التسليم والتدقيق."""
    STATUS_CHOICES = [
        ("queued", "قيد الإرسال"),
        ("sent", "تم الإرسال بنجاح"),
        ("failed", "فشل الإرسال"),
    ]

    recipient_email = models.EmailField(db_index=True, verbose_name="البريد المستلم")
    recipient_name = models.CharField(max_length=255, blank=True, default="", verbose_name="اسم المستلم")
    subject = models.CharField(max_length=255, verbose_name="عنوان الرسالة")
    body_preview = models.TextField(blank=True, default="", verbose_name="مقتطف من المحتوى")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued", verbose_name="حالة الإرسال")
    brevo_message_id = models.CharField(max_length=255, blank=True, default="", verbose_name="معرف Brevo (Message-ID)")
    error_message = models.TextField(blank=True, default="", verbose_name="رسالة الخطأ إن وجدت")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ ووقت الإرسال")

    class Meta:
        app_label = 'core'
        verbose_name = "سجل البريد الصادر (Email Log)"
        verbose_name_plural = "سجلات البريد الصادر (Email Logs)"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.recipient_email} - {self.subject} ({self.status})"


class InboundEmailLog(models.Model):
    """
    سجل فحص البريد الوارد ومعالجة الويب هوك (Brevo Inbound Webhook Inspection):
    يستقبل ويفكك الردود البريدية للعملاء، يستخرج النص والمرفقات، ويربطها بتذاكر الدعم الفني تلقائياً.
    """
    message_id = models.CharField(max_length=255, blank=True, default="", verbose_name="معرف الرسالة الأصلية")
    sender_email = models.CharField(max_length=255, db_index=True, verbose_name="بريد المرسل")
    sender_name = models.CharField(max_length=255, blank=True, default="", verbose_name="اسم المرسل")
    recipient_email = models.CharField(max_length=255, verbose_name="البريد المستلم الأصلي")
    subject = models.CharField(max_length=500, verbose_name="موضوع الرسالة")
    body_text = models.TextField(blank=True, default="", verbose_name="المحتوى النصي المفكك")
    body_html = models.TextField(blank=True, default="", verbose_name="المحتوى بتنسيق HTML")
    raw_payload = models.JSONField(default=dict, blank=True, verbose_name="بيانات الحمولة الأصلية (JSON Payload)")
    headers = models.JSONField(default=dict, blank=True, verbose_name="ترويسات البريد (Headers)")
    ticket = models.ForeignKey(
        'core.SupportTicket',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inbound_emails",
        verbose_name="تذكرة الدعم المرتبطة"
    )
    is_processed = models.BooleanField(default=False, verbose_name="تمت المعالجة والربط؟")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الاستلام")

    class Meta:
        app_label = 'core'
        verbose_name = "سجل البريد الوارد (Inbound Email Webhook)"
        verbose_name_plural = "سجلات البريد الوارد (Inbound Email Webhooks)"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.created_at:%Y-%m-%d %H:%M}] From: {self.sender_email} - {self.subject}"
