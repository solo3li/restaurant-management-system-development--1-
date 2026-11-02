import os
import random
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User


class SupportTicket(models.Model):
    """
    نظام تذاكر الدعم الفني المركزي المتكامل (Full-Page Support Ticket System):
    يتيح للعملاء وأصحاب المطاعم التفاعل مع إدارة النظام عبر محادثات نصية ورسائل وسائط غنية
    (تسجيلات صوتية، صور، وفيديوهات بحد أقصى 25 ميجابايت).
    """
    CATEGORY_CHOICES = [
        ("technical", "دعم فني ونظام"),
        ("billing", "فواتير واشتراكات"),
        ("pos_hardware", "أجهزة ونقاط بيع"),
        ("features", "اقتراحات وميزات جديدة"),
        ("general", "استفسار عام"),
    ]

    PRIORITY_CHOICES = [
        ("low", "منخفضة"),
        ("medium", "متوسطة"),
        ("high", "عالية"),
        ("urgent", "حرجة وعاجلة"),
    ]

    STATUS_CHOICES = [
        ("open", "مفتوحة"),
        ("in_progress", "قيد المعالجة"),
        ("resolved", "تم الحل"),
        ("closed", "مغلقة"),
    ]

    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name="support_tickets",
        verbose_name="المنشأة / المطعم"
    )
    ticket_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        verbose_name="رقم التذكرة المرجعي"
    )
    creator = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="created_tickets",
        verbose_name="منشئ التذكرة"
    )
    subject = models.CharField(max_length=255, verbose_name="عنوان التذكرة")
    category = models.CharField(
        max_length=30,
        choices=CATEGORY_CHOICES,
        default="technical",
        verbose_name="تصنيف المشكلة"
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default="medium",
        verbose_name="مستوى الأولوية"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="open",
        db_index=True,
        verbose_name="حالة التذكرة"
    )
    description = models.TextField(verbose_name="تفاصيل وبلاغ المشكلة")
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
        verbose_name="عضو فريق الدعم المعين"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ ووقت الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ آخر تحديث")
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ اعتماد الحل")
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ الإغلاق النهائي")

    class Meta:
        app_label = 'core'
        verbose_name = "تذكرة دعم فني (Support Ticket)"
        verbose_name_plural = "تذاكر الدعم الفني (Support Tickets)"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"[{self.ticket_number}] {self.subject} ({self.get_status_display()})"

    def display_category(self, lang=None):
        from django.utils import translation
        from core.i18n_catalog import get_translation
        active_lang = lang or translation.get_language() or "ar"
        if "-" in active_lang:
            active_lang = active_lang.split("-")[0]
        return get_translation(self.get_category_display(), active_lang)

    def display_priority(self, lang=None):
        from django.utils import translation
        from core.i18n_catalog import get_translation
        active_lang = lang or translation.get_language() or "ar"
        if "-" in active_lang:
            active_lang = active_lang.split("-")[0]
        return get_translation(self.get_priority_display(), active_lang)

    def display_status(self, lang=None):
        from django.utils import translation
        from core.i18n_catalog import get_translation
        active_lang = lang or translation.get_language() or "ar"
        if "-" in active_lang:
            active_lang = active_lang.split("-")[0]
        return get_translation(self.get_status_display(), active_lang)

    @classmethod
    def generate_ticket_number(cls):
        """Generates a unique reference ticket number like TCK-202610-4821."""
        prefix = timezone.now().strftime("TCK-%Y%m")
        while True:
            rand_code = random.randint(1000, 9999)
            num = f"{prefix}-{rand_code}"
            if not cls.objects.filter(ticket_number=num).exists():
                return num


class TicketMessage(models.Model):
    """
    سلسلة رسائل المحادثة التفاعلية في تذكرة الدعم (Ticket Message Thread):
    تربط ردود العميل وإجابات فريق الدعم مع تمييز دقيق لهوية المرسل.
    """
    SENDER_TYPE_CHOICES = [
        ("tenant", "العميل / المنشأة"),
        ("support", "فريق الدعم الفني"),
        ("system", "النظام التلقائي"),
    ]

    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="تذكرة الدعم"
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="ticket_messages",
        verbose_name="مرسل الرد"
    )
    sender_type = models.CharField(
        max_length=20,
        choices=SENDER_TYPE_CHOICES,
        default="tenant",
        verbose_name="نوع المرسل"
    )
    message = models.TextField(verbose_name="نص الرسالة أو الرد")
    is_internal = models.BooleanField(
        default=False,
        verbose_name="ملاحظة داخلية للمشرفين فقط"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ ووقت الإرسال")

    class Meta:
        app_label = 'core'
        verbose_name = "رد في تذكرة الدعم (Ticket Message)"
        verbose_name_plural = "ردود تذاكر الدعم (Ticket Messages)"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.ticket.ticket_number} - {self.sender.username} ({self.sender_type})"


class TicketAttachment(models.Model):
    """
    مرفقات وسائط الدعم الفني الغنية (Rich Media Attachments):
    تدعم التسجيلات الصوتية (مع مشغل صوت مدمج)، الصور (مع مستعرض Lightbox)،
    والفيديوهات (مع مشغل فيديو مضمن) بحجم أقصى 25 ميجابايت للملف الواحد.
    """
    FILE_TYPE_CHOICES = [
        ("audio", "تسجيل صوتي (Voice Note)"),
        ("image", "صورة (Image)"),
        ("video", "فيديو (Video Clip)"),
        ("document", "مستند / ملف (Document)"),
    ]

    MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 Megabytes

    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="تذكرة الدعم"
    )
    message = models.ForeignKey(
        TicketMessage,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
        verbose_name="الرسالة التابعة للمرفق"
    )
    file = models.FileField(
        upload_to="support_tickets/%Y/%m/",
        verbose_name="الملف المرفق"
    )
    file_type = models.CharField(
        max_length=20,
        choices=FILE_TYPE_CHOICES,
        default="document",
        verbose_name="نوع الوسائط"
    )
    file_name = models.CharField(max_length=255, verbose_name="اسم الملف الأصلي")
    file_size = models.PositiveIntegerField(
        verbose_name="حجم الملف بالبايت",
        help_text="حجم الملف بحد أقصى 25 ميجابايت."
    )
    duration_seconds = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="مدة التسجيل الصوتي أو الفيديو بالثواني"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الرفع")

    class Meta:
        app_label = 'core'
        verbose_name = "مرفق تذكرة دعم (Ticket Attachment)"
        verbose_name_plural = "مرفقات تذاكر الدعم (Ticket Attachments)"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.ticket.ticket_number} - {self.file_name} ({self.file_type})"

    @property
    def formatted_size(self):
        """Returns human readable file size like 1.4 MB or 540 KB."""
        size = self.file_size or 0
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        elif size >= 1024:
            return f"{size / 1024:.0f} KB"
        return f"{size} B"

    @classmethod
    def detect_file_type(cls, filename: str, content_type: str = "") -> str:
        """Helper to classify file into audio, image, video, or document."""
        ext = os.path.splitext(filename)[1].lower().strip(".")
        content_type = (content_type or "").lower()

        if ext in ["mp3", "wav", "ogg", "m4a", "webm", "aac", "flac"] or "audio" in content_type:
            # If webm has video, content_type might have video/webm, check content_type
            if "video" in content_type:
                return "video"
            return "audio"
        if ext in ["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp"] or "image" in content_type:
            return "image"
        if ext in ["mp4", "mov", "avi", "mkv", "webm"] or "video" in content_type:
            return "video"
        return "document"
