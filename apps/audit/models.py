from django.db import models
from django.contrib.auth.models import User


class AuditLog(models.Model):
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name="audit_logs",
        verbose_name="المنشأة",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="المستخدم المنفذ",
    )
    action = models.CharField(max_length=64, verbose_name="نوع العملية")
    target_model = models.CharField(max_length=64, blank=True, verbose_name="النموذج المتأثر")
    target_id = models.CharField(max_length=64, blank=True, verbose_name="معرف السجل")
    description = models.TextField(blank=True, verbose_name="تفاصيل العملية")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="عنوان IP")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ العملية")

    class Meta:
        app_label = 'core'
        verbose_name = "سجل التدقيق الأمني"
        verbose_name_plural = "سجلات التدقيق الأمني"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.action} - {self.tenant.name}"


def log_audit_event(tenant, user=None, action="", target_model="", target_id="", description="", ip_address=None):
    """Utility function to log sensitive security or financial actions safely."""
    try:
        if not tenant:
            return None
        return AuditLog.objects.create(
            tenant=tenant,
            user=user if user and getattr(user, "is_authenticated", False) else None,
            action=action,
            target_model=target_model,
            target_id=str(target_id) if target_id is not None else "",
            description=description,
            ip_address=ip_address,
        )
    except Exception:
        return None


class KnowledgeDocument(models.Model):
    """Local storage and metadata for uploaded restaurant knowledge documents (PDFs, Menus, FAQs)."""
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name='knowledge_documents',
    )
    partner_doc_id = models.IntegerField(null=True, blank=True, db_index=True, verbose_name="معرف المستند في منصة المكالمات")
    title = models.CharField(max_length=255, verbose_name="عنوان المستند أو السؤال")
    file = models.FileField(upload_to='knowledge_docs/%Y/%m/', null=True, blank=True, verbose_name="الملف المرفوع")
    file_type = models.CharField(max_length=32, blank=True, verbose_name="نوع الملف")
    file_size = models.PositiveIntegerField(default=0, verbose_name="حجم الملف بالبايت")
    source_type = models.CharField(max_length=32, default='file', verbose_name="مصدر المستند")  # 'file', 'faq', 'url'
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإضافة")

    class Meta:
        app_label = 'core'
        verbose_name = "مستند قاعدة المعرفة"
        verbose_name_plural = "مستندات قاعدة المعرفة"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.tenant.name})"
