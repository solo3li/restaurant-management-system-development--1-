import secrets
from django.db import models
from django.utils import timezone


def generate_api_key():
    return f"ak_live_{secrets.token_urlsafe(32)}"


class TenantApiKey(models.Model):
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name="api_keys",
        verbose_name="المنشأة / المطعم",
    )
    name = models.CharField(
        max_length=120,
        default="مفتاح كول سنتر الذكاء الاصطناعي",
        verbose_name="اسم المفتاح / البوت",
    )
    key = models.CharField(
        max_length=80,
        unique=True,
        db_index=True,
        default=generate_api_key,
        verbose_name="مفتاح الدخول (Access Key)",
    )
    assigned_branch = models.ForeignKey(
        'core.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="api_keys",
        verbose_name="الفرع المخصص (اختياري)",
        help_text="اتركه فارغاً للسماح للبوت بخدمة كافة فروع المنشأة",
    )
    is_active = models.BooleanField(default=True, verbose_name="مفعل")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    last_used_at = models.DateTimeField(null=True, blank=True, verbose_name="آخر استخدام")
    total_orders_placed = models.PositiveIntegerField(default=0, verbose_name="الطلبات المنفذة عبره")

    class Meta:
        app_label = 'core'
        verbose_name = "مفتاح ذكاء اصطناعي (API Key)"
        verbose_name_plural = "مفاتيح الذكاء الاصطناعي (AI Access Keys)"
        ordering = ["-created_at"]

    def __str__(self):
        branch_info = f" ({self.assigned_branch.name})" if self.assigned_branch else " (كافة الفروع)"
        return f"{self.tenant.name} - {self.name}{branch_info}"

    def record_usage(self, placed_order=False):
        now = timezone.now()
        if placed_order:
            TenantApiKey.objects.filter(pk=self.pk).update(
                last_used_at=now,
                total_orders_placed=models.F("total_orders_placed") + 1
            )
            self.last_used_at = now
            self.total_orders_placed += 1
        else:
            try:
                from django.core.cache import cache
                cache_key = f"apikey_usage_debounce_{self.pk}"
                if not cache.get(cache_key):
                    TenantApiKey.objects.filter(pk=self.pk).update(last_used_at=now)
                    self.last_used_at = now
                    cache.set(cache_key, True, timeout=60)
            except Exception:
                TenantApiKey.objects.filter(pk=self.pk).update(last_used_at=now)
                self.last_used_at = now
