from datetime import timedelta
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

AVAILABLE_FEATURES = [
    {
        "key": "pos",
        "label": "نقاط البيع والكاشير (POS)",
        "desc": "تسجيل طلبات الصالة والسفري والفواتير والمدفوعات",
        "icon": "fas fa-cash-register",
    },
    {
        "key": "kds",
        "label": "شاشة المطبخ (KDS)",
        "desc": "تجهيز وتحضير الوجبات فورياً في مطبخ الفرع",
        "icon": "fas fa-utensils",
    },
    {
        "key": "menu_management",
        "label": "إدارة المنيو وقائمة الطعام",
        "desc": "إضافة وتعديل الوجبات والأسعار والفئات وتوفر الأطباق",
        "icon": "fas fa-book-open",
    },
    {
        "key": "delivery_management",
        "label": "نظام التوصيل ومناطق الخدمة",
        "desc": "تحديد مناطق التوصيل، إسناد ومتابعة السائقين",
        "icon": "fas fa-motorcycle",
    },
    {
        "key": "call_center",
        "label": "الكول سنتر ومساعد الذكاء الاصطناعي (AI Voice)",
        "desc": "استقبال المكالمات ومساعد الطلبات الذكي",
        "icon": "fas fa-headset",
    },
    {
        "key": "inventory",
        "label": "إدارة المخزون والمستودعات",
        "desc": "جرد المواد الخام، فواتير الموردين، وتسجيل الهدر",
        "icon": "fas fa-boxes",
    },
    {
        "key": "custom_roles",
        "label": "الأدوار والصلاحيات المخصصة",
        "desc": "مسميات وظيفية مخصصة ومصفوفة الصلاحيات",
        "icon": "fas fa-user-shield",
    },
    {
        "key": "financial_analytics",
        "label": "التقارير والتحليلات المالية",
        "desc": "مؤشرات الإيرادات والمبيعات والأرباح",
        "icon": "fas fa-chart-line",
    },
]
SAAS_FEATURES_CATALOG = AVAILABLE_FEATURES


class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=100, verbose_name="اسم الباقة")
    code = models.SlugField(max_length=50, unique=True, verbose_name="كود الباقة")
    description = models.CharField(max_length=255, blank=True, default="", verbose_name="وصف الباقة")
    price_monthly = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="السعر الشهري ($)")
    price_yearly = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="السعر السنوي ($)")
    max_branches = models.IntegerField(default=1, verbose_name="الحد الأقصى للفروع (0 لغير محدود)")
    max_employees = models.IntegerField(default=5, verbose_name="الحد الأقصى للموظفين (0 لغير محدود)")
    features = models.JSONField(default=list, blank=True, verbose_name="الميزات المفعلة في الباقة")
    trial_days = models.PositiveIntegerField(default=14, verbose_name="أيام التجربة المجانية")
    is_active = models.BooleanField(default=True, verbose_name="متاحة للاشتراك")
    is_popular = models.BooleanField(default=False, verbose_name="الباقة الأكثر طلباً")
    ordering = models.IntegerField(default=0, verbose_name="ترتيب العرض")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخر تحديث")

    class Meta:
        app_label = 'core'
        verbose_name = "باقة اشتراك SaaS"
        verbose_name_plural = "باقات اشتراك المنصة"
        ordering = ["ordering", "price_monthly"]

    def __str__(self):
        return f"{self.name} ({self.price_monthly} ر.س/شهر)"


class UpgradeRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "قيد المراجعة"),
        ("approved", "تمت الموافقة"),
        ("rejected", "مرفوض"),
    ]

    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name="upgrade_requests",
        verbose_name="المطعم / المنشأة",
    )
    requested_plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.CASCADE,
        related_name="upgrade_requests",
        verbose_name="الباقة المطلوبة",
    )
    billing_cycle = models.CharField(
        max_length=20,
        default="monthly",
        choices=[("monthly", "شهري"), ("yearly", "سنوي")],
        verbose_name="دورة الفوترة",
    )
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="طالب الترقية",
    )
    notes = models.TextField(blank=True, default="", verbose_name="ملاحظات الطلب")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
        verbose_name="حالة الطلب",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الطلب")
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ المراجعة")

    class Meta:
        app_label = 'core'
        verbose_name = "طلب ترقية باقة"
        verbose_name_plural = "طلبات ترقية الباقات"
        ordering = ["-created_at"]

    def __str__(self):
        return f"طلب {self.tenant.name} -> {self.requested_plan.name} ({self.get_status_display()})"

    def apply_upgrade(self):
        """Apply requested plan and extension to the tenant."""
        tenant = self.tenant
        tenant.subscription_plan = self.requested_plan
        tenant.billing_cycle = self.billing_cycle
        tenant.subscription_status = "active"
        tenant.is_active = True

        extension_days = 365 if self.billing_cycle == "yearly" else 30
        base_time = tenant.subscription_end if (tenant.subscription_end and tenant.subscription_end > timezone.now()) else timezone.now()
        tenant.subscription_end = base_time + timedelta(days=extension_days)
        tenant.save()

        # Synchronize call minute & spending caps with Partner API
        try:
            from core import partner_service as ps
            ps.sync_tenant_voice_caps(tenant, reset_to_plan=True)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Voice quota sync failed on upgrade for {tenant.slug}: {e}")

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        old_status = None
        if not is_new:
            try:
                old_status = UpgradeRequest.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            except Exception:
                pass

        if self.status == "approved":
            if not self.reviewed_at:
                self.reviewed_at = timezone.now()
            if is_new or old_status != "approved" or (self.tenant.subscription_plan_id != self.requested_plan_id):
                self.apply_upgrade()
        elif self.status == "rejected":
            if not self.reviewed_at:
                self.reviewed_at = timezone.now()

        super().save(*args, **kwargs)


from apps.tenants.models import Tenant


class TenantSubscription(Tenant):
    class Meta:
        proxy = True
        app_label = 'core'
        verbose_name = "مشترك / اشتراك منشأة"
        verbose_name_plural = "قائمة المشتركين (Subscribers)"
