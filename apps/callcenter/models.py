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


class PlatformVoiceAssistantConfig(models.Model):
    """
    إعدادات المساعد الصوتي العام لمبيعات المنصة وصفحة الهبوط (Singleton):
    يُدار بالكامل من لوحة تحكم الإدارة (/admin/) للمشرفين والمسؤولين.
    """
    is_active = models.BooleanField(
        default=True,
        verbose_name="تفعيل المساعد الصوتي في صفحة الهبوط",
        help_text="عند التفعيل، يظهر زر التحدث الصوتي المباشر للزوار في صفحة الهبوط."
    )
    assistant_name = models.CharField(
        max_length=120,
        default="مستشار مبيعات كُـورَا السحابي",
        verbose_name="اسم المساعد الصوتي",
        help_text="الاسم الظاهر في نافذة الاتصال الصوتي على صفحة الهبوط."
    )
    welcome_message = models.TextField(
        default="أهلاً بك في منصة كُـورَا لإدارة المطاعم ونقاط البيع السحابية. كيف يمكنني مساعدتك في تطوير وتشغيل مطعمك اليوم؟",
        verbose_name="الرسالة الترحيبية الصوتية الأولى",
        help_text="العبارة الترحيبية التي ينطق بها المساعد فور بدء الاتصال الصوتي."
    )
    system_prompt = models.TextField(
        default="""أنت مستشار مبيعات خبير ومنفتح ومرح لمنصة "كُـورَا" (KURA Cloud Restaurant OS).
مهمتك:
1. الترحيب بزوّار الموقع وشرح ميزات المنصة بإيجاز واحترافية:
   - نظام نقاط البيع السحابي (POS) السريع والسلس على أي شاشة وتوافق كامل مع الطابعات الحرارية والدرج.
   - شاشات المطبخ الذكية (KDS) لتنظيم سير الطبخ وتفادي التأخير ومتابعة جاهزية الطلبات.
   - كول سنتر الذكاء الاصطناعي الصوتي الذي يستقبل اتصالات الزبائن الهاتفية ويرسل الطلبات للمطبخ تلقائياً.
   - أسطول التوصيل وتتبع المناديب وإدارة المخزون والتكاليف والفروع المتعددة.
2. توضيح باقات الاشتراك (تجربة مجانية 14 يوماً بدون بطاقة بنكية، باقة الأساسية للمطعم الفردي، وباقة النمو والسلاسل للشركات الكبيرة).
3. تشجيع الزائر على النقر على زر "ابدأ تجربتك المجانية" أعلى الصفحة لتسجيل مطعمه خلال دقيقة واحدة.
4. اللهجة: سعودية ودية ومهنية ولبقة للغاية، أو التحدث بلغة المتصل إن تحدث بلغة أخرى.
5. لا تعد بأشياء غير موجودة، وركّز دائماً على مساعدة صاحب المطعم في زيادة أرباحه وتقليل هدر التوصيل والكول سنتر.""",
        verbose_name="توجيهات وشخصية المساعد (System Prompt)",
        help_text="التوجيهات التفصيلية التي تحكم ردود المساعد مع زوار صفحة الهبوط."
    )
    partner_client_id = models.CharField(
        max_length=100,
        default="49",
        verbose_name="معرف العميل لدى مزود الاتصالات (Partner Client ID)",
        help_text="Client ID المخصص في مزود تقنية WebRTC (افتراضياً 49)."
    )
    voice_name = models.CharField(
        max_length=50,
        default="Puck",
        verbose_name="خامة الصوت (Gemini Live Voice)",
        choices=[
            ("Puck", "Puck (طبيعي ومرن - موصى به)"),
            ("Charon", "Charon (وقور وعميق)"),
            ("Aoede", "Aoede (أنثوي هادئ وواضح)"),
            ("Fenrir", "Fenrir (حماسي وواثق)"),
            ("Kore", "Kore (أنثوي لطيف واحترافي)"),
        ],
        help_text="نبرة وخامة الصوت المعتمدة من Google Gemini Live."
    )
    language = models.CharField(
        max_length=20,
        default="ar",
        verbose_name="اللغة الأساسية",
        choices=[
            ("ar", "العربية (Arabic)"),
            ("en", "الإنجليزية (English)"),
            ("fr", "الفرنسية (French)"),
            ("tr", "التركية (Turkish)"),
            ("de", "الألمانية (German)"),
        ],
    )
    accent = models.CharField(
        max_length=50,
        default="saudi",
        verbose_name="اللهجة الافتراضية",
        choices=[
            ("saudi", "سعودية (نجدية / حجازية)"),
            ("egyptian", "مصرية"),
            ("levantine", "شامية"),
            ("gulf", "خليجية عامة"),
            ("modern_standard", "فصحى مبسطة"),
        ],
    )
    max_call_duration_seconds = models.PositiveIntegerField(
        default=180,
        verbose_name="الحد الأقصى لمدّة المكالمة (بالثواني)",
        help_text="المدة القصوى للمكالمة الواحدة بالثواني (180 = 3 دقائق)."
    )
    max_daily_calls_per_ip = models.PositiveIntegerField(
        default=3,
        verbose_name="الحد اليومي للمكالمات لكل عنوان IP",
        help_text="الحد الأقصى لعدد المكالمات المسموح بها لكل IP يومياً لمنع استنزاف الرصيد."
    )
    landing_profile_id = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="معرف بروفايل صفحة الهبوط المعتمد",
        help_text="معرف البروفايل المعتمد حالياً في استوديو الكول سنتر لصفحة الهبوط."
    )
    created_at = models.DateTimeField(default=timezone.now, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخر تحديث")

    class Meta:
        app_label = 'core'
        verbose_name = "إعدادات مساعد مبيعات المنصة (صفحة الهبوط)"
        verbose_name_plural = "إعدادات مساعد مبيعات المنصة (صفحة الهبوط)"

    def __str__(self):
        state = "مفعل" if self.is_active else "معطل"
        return f"{self.assistant_name} ({state})"

    @classmethod
    def get_config(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

