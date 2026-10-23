from decimal import Decimal
from django.db import models
from django.utils import timezone


class Tenant(models.Model):
    PLAN_CHOICES = [
        ("trial", "تجريبي"),
        ("standard", "أساسي"),
        ("premium", "متقدم"),
        ("enterprise", "شركات"),
    ]
    SUBSCRIPTION_STATUS_CHOICES = [
        ("trial", "فترة تجريبية"),
        ("active", "نشط"),
        ("expired", "منتهي"),
        ("grace_period", "فترة سماح"),
    ]
    BILLING_CYCLE_CHOICES = [
        ("monthly", "شهري"),
        ("yearly", "سنوي"),
        ("trial", "تجريبي"),
    ]

    name = models.CharField(max_length=255, verbose_name="اسم المطعم / المنشأة")
    slug = models.SlugField(max_length=100, unique=True, verbose_name="المعرف اللاتيني (Slug)")
    logo_emoji = models.CharField(max_length=20, default="🍽️", blank=True, verbose_name="شعار / أيقونة")
    logo_image = models.FileField(upload_to="tenant_logos/", blank=True, null=True, verbose_name="شعار المطعم (Logo)")
    cover_image = models.FileField(upload_to="tenant_covers/", blank=True, null=True, verbose_name="صورة الغلاف (Cover)")
    custom_domain = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True, verbose_name="النطاق المخصص (Custom Domain)")
    brand_color = models.CharField(max_length=20, default="#0E382A", blank=True, verbose_name="اللون الأساسي للهوية")
    bio = models.CharField(max_length=255, default="", blank=True, verbose_name="نبذة عن المطعم")
    phone = models.CharField(max_length=50, default="", blank=True, verbose_name="رقم الهاتف")
    email = models.EmailField(blank=True, default="", verbose_name="البريد الإلكتروني")
    address = models.CharField(max_length=255, default="", blank=True, verbose_name="المقر الرئيسي")
    plan = models.CharField(max_length=30, choices=PLAN_CHOICES, default="standard", verbose_name="خطة الاشتراك")

    subscription_plan = models.ForeignKey(
        'core.SubscriptionPlan',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tenants",
        verbose_name="باقة الاشتراك",
    )
    subscription_status = models.CharField(
        max_length=20,
        choices=SUBSCRIPTION_STATUS_CHOICES,
        default="active",
        verbose_name="حالة الاشتراك",
    )
    billing_cycle = models.CharField(
        max_length=20,
        choices=BILLING_CYCLE_CHOICES,
        default="monthly",
        verbose_name="دورة الفوترة",
    )
    subscription_start = models.DateTimeField(default=timezone.now, null=True, blank=True, verbose_name="تاريخ بدء الاشتراك")
    subscription_end = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ انتهاء الاشتراك")

    is_active = models.BooleanField(default=True, verbose_name="نشط")

    # Voice AI & Cloud PBX Partner Integration
    voice_client_id = models.IntegerField(null=True, blank=True, verbose_name="معرف الكول سنتر (Client ID)")
    voice_username = models.CharField(max_length=150, blank=True, default="", verbose_name="اسم مستخدم السنترال (Voice PBX Username)")
    voice_password = models.CharField(max_length=128, blank=True, default="", verbose_name="كلمة مرور السنترال (Voice PBX Password)")
    voice_is_active = models.BooleanField(default=False, verbose_name="تفعيل الكول سنتر الصوتي")
    default_currency = models.CharField(
        max_length=10,
        default="SAR",
        verbose_name="العملة الافتراضية للمنشأة",
        help_text="العملة الرسمية المعتمدة للمطعم والسلسلة وفروعها الجديدة."
    )
    google_maps_api_key = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="مفتاح Google Maps الخاص بالمنشأة (اختياري)",
        help_text="إن تُرك فارغاً، يتم استخدام المفتاح المركزي العام للمنصة تلقائياً."
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التسجيل")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخر تحديث")

    class Meta:
        app_label = 'core'
        verbose_name = "مستأجر / منشأة"
        verbose_name_plural = "المستأجرون (المنشآت والمطاعم)"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.slug})"

    def get_currency_name_ar(self):
        from core.currencies import get_currency_info
        return get_currency_info(self.default_currency).get("name_ar", "ريال")

    def get_currency_symbol_ar(self):
        from core.currencies import get_currency_info
        return get_currency_info(self.default_currency).get("symbol_ar", "ر.س")

    def get_currency_symbol_en(self):
        from core.currencies import get_currency_info
        return get_currency_info(self.default_currency).get("symbol_en", "SAR")

    def can_add_branch(self):
        if not self.subscription_plan:
            return True
        limit = self.subscription_plan.max_branches
        if limit is None or limit <= 0:
            return True
        return self.branches.filter(status="active").count() < limit

    def can_add_employee(self):
        if not self.subscription_plan:
            return True
        limit = self.subscription_plan.max_employees
        if limit is None or limit <= 0:
            return True
        return self.employees.filter(status__in=["active", "vacation"]).count() < limit

    def has_feature(self, feature_key):
        if not self.subscription_plan:
            return True
        raw_features = self.subscription_plan.features or []
        f_set = set(raw_features)
        if f_set & {"inventory", "inventory_mgmt"}:
            f_set.update(["inventory", "inventory_mgmt"])
        if f_set & {"delivery", "delivery_management", "delivery_zones"}:
            f_set.update(["delivery", "delivery_management", "delivery_zones"])
        if f_set & {"pos", "pos_billing"}:
            f_set.update(["pos", "pos_billing"])
        if f_set & {"kds", "kds_kitchen"}:
            f_set.update(["kds", "kds_kitchen"])
        if f_set & {"menu", "menu_management"}:
            f_set.update(["menu", "menu_management"])
        if f_set & {"call_center", "ai_call_center"}:
            f_set.update(["call_center", "ai_call_center"])
        if f_set & {"custom_roles", "manage_roles"}:
            f_set.update(["custom_roles", "manage_roles"])
        return feature_key in f_set

    def is_subscription_active(self):
        if not self.is_active:
            return False
        if self.subscription_status in ["active", "trial"]:
            if self.subscription_end and self.subscription_end < timezone.now():
                return False
            return True
        return False

    def is_subscription_expired(self):
        return not self.is_subscription_active()

    def days_until_expiry(self):
        if not self.subscription_end:
            return 999
        diff = (self.subscription_end - timezone.now()).total_seconds()
        return max(0, int(diff // 86400))


class Branch(models.Model):
    STATUS_CHOICES = [
        ("active", "نشط"),
        ("closed", "مغلق"),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="branches",
        null=True,
        blank=True,
        verbose_name="المستأجر / المنشأة",
    )
    name = models.CharField(max_length=255, verbose_name="اسم الفرع")
    name_en = models.CharField(max_length=255, default="", blank=True, verbose_name="اسم الفرع (إنجليزي)")
    city = models.CharField(max_length=100, default="", blank=True, verbose_name="المدينة")
    address = models.CharField(max_length=255, default="", blank=True, verbose_name="العنوان")
    phone = models.CharField(max_length=50, default="", blank=True, verbose_name="الهاتف")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active", verbose_name="الحالة")
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط العرض")
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط الطول")
    delivery_polygon = models.JSONField(default=list, blank=True, verbose_name="مضلع التغطية على الخريطة")
    delivery_radius_km = models.DecimalField(max_digits=5, decimal_places=2, default=5.00, verbose_name="نصف قطر التغطية (كم)")
    delivery_base_fee = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=15.00,
        verbose_name="رسوم فتحة العداد / الحد الأدنى للتوصيل",
        help_text="الرسوم الأساسية لتوصيل أي عنوان داخل مضلع الزون غير مسجل في جدول الكومبوندات."
    )
    delivery_base_km = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=3.00,
        verbose_name="المسافة الأساسية المشمولة بفتحة العداد (كم)",
        help_text="المسافة المغطاة ضمن رسوم فتحة العداد قبل تطبيق رسوم الكيلومترات الإضافية."
    )
    delivery_per_km_fee = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=3.00,
        verbose_name="رسوم الكيلومتر الإضافي",
        help_text="سعر كل كيلومتر قيادة إضافي بعد المسافة الأساسية."
    )
    opening_time = models.TimeField(null=True, blank=True, verbose_name="وقت فتح الفرع")
    closing_time = models.TimeField(null=True, blank=True, verbose_name="وقت إغلاق الفرع")
    min_delivery_order = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="الحد الأدنى لطلب التوصيل")
    min_order_tier1_km = models.DecimalField(max_digits=5, decimal_places=2, default=3.00, verbose_name="مسافة الشريحة الأولى للحد الأدنى (كم)")
    min_order_tier1_amount = models.DecimalField(max_digits=8, decimal_places=2, default=50.00, verbose_name="الحد الأدنى للشريحة الأولى")
    min_order_tier2_km = models.DecimalField(max_digits=5, decimal_places=2, default=6.00, verbose_name="مسافة الشريحة الثانية للحد الأدنى (كم)")
    min_order_tier2_amount = models.DecimalField(max_digits=8, decimal_places=2, default=100.00, verbose_name="الحد الأدنى للشريحة الثانية")
    min_order_tier3_amount = models.DecimalField(max_digits=8, decimal_places=2, default=150.00, verbose_name="الحد الأدنى للشريحة البعيدة")
    currency = models.CharField(
        max_length=10,
        default="SAR",
        verbose_name="عملة الفرع",
        help_text="العملة الرسمية للفرع والأسعار وطلبات الذكاء الاصطناعي والكول سنتر."
    )
    tax_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=15.00,
        verbose_name="نسبة ضريبة القيمة المضافة (%)",
        help_text="نسبة الضريبة الخاصة بالفرع (مثلاً 15.00 بالسعودية، 14.00 بمصر، 0 للمطاعم المعفاة)."
    )
    is_tax_inclusive = models.BooleanField(
        default=True,
        verbose_name="الأسعار شاملة الضريبة",
        help_text="إذا كان مفعلاً، تكون أسعار قائمة الطعام شاملة للضريبة ويتم احتساب الضريبة داخلياً، وإلا تضاف فوق المجموع."
    )
    cancellation_window_minutes = models.PositiveIntegerField(
        default=10,
        verbose_name="مهلة إلغاء الطلب (بالدقائق)",
        help_text="المدة الزمنية المسموح بها للعميل لإلغاء طلبه طالما لم يبدأ المطبخ في تحضيره."
    )
    is_accepting_orders = models.BooleanField(default=True, verbose_name="استقبال الطلبات الذاتية حالياً")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        app_label = 'core'
        verbose_name = "فرع"
        verbose_name_plural = "الفروع"
        ordering = ["id"]

    def get_currency_name_ar(self):
        from core.currencies import get_currency_info
        return get_currency_info(self.currency).get("name_ar", "ريال")

    def get_currency_symbol_ar(self):
        from core.currencies import get_currency_info
        return get_currency_info(self.currency).get("symbol_ar", "ر.س")

    def get_currency_symbol_en(self):
        from core.currencies import get_currency_info
        return get_currency_info(self.currency).get("symbol_en", "SAR")

    def get_display_name(self, lang="ar"):
        if lang == "en" and self.name_en:
            return self.name_en
        return self.name

    def is_currently_open(self):
        if not self.is_accepting_orders or self.status != "active":
            return False
        if not self.opening_time or not self.closing_time:
            return True
        from django.utils import timezone
        now_time = timezone.localtime().time()
        if self.opening_time <= self.closing_time:
            return self.opening_time <= now_time <= self.closing_time
        else:
            return now_time >= self.opening_time or now_time <= self.closing_time

    def get_min_order_for_distance(self, distance_km: float = 0.0) -> Decimal:
        """حساب الحد الأدنى للطلب بناءً على شرائح المسافة المحددة للفرع."""
        try:
            dist = Decimal(str(max(0.0, float(distance_km or 0))))
        except (ValueError, TypeError):
            dist = Decimal("0.0")

        t1_km = self.min_order_tier1_km if self.min_order_tier1_km is not None else Decimal("3.00")
        t1_amt = self.min_order_tier1_amount if self.min_order_tier1_amount is not None else Decimal("50.00")
        t2_km = self.min_order_tier2_km if self.min_order_tier2_km is not None else Decimal("6.00")
        t2_amt = self.min_order_tier2_amount if self.min_order_tier2_amount is not None else Decimal("100.00")
        t3_amt = self.min_order_tier3_amount if self.min_order_tier3_amount is not None else Decimal("150.00")

        if dist <= t1_km:
            return t1_amt
        elif dist <= t2_km:
            return t2_amt
        else:
            return t3_amt

    def __str__(self):
        tenant_name = f" [{self.tenant.name}]" if self.tenant else ""
        return f"{self.name}{tenant_name}"

    @property
    def is_active(self):
        return self.status == "active"


class DeliveryArea(models.Model):
    AREA_TYPES = [
        ("compound", "كومبوند / مجمع سكني"),
        ("district", "حي سكني"),
        ("zone", "منطقة / قطاع"),
        ("commercial", "منطقة تجارية / مول"),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="delivery_areas",
        verbose_name="الفرع التابع له",
    )
    name = models.CharField(max_length=255, verbose_name="اسم المنطقة / الكومبوند")
    area_type = models.CharField(max_length=30, choices=AREA_TYPES, default="compound", verbose_name="نوع المنطقة")
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=8.00, verbose_name="رسوم التوصيل")
    estimated_time_minutes = models.PositiveIntegerField(default=35, verbose_name="وقت التوصيل التقديري (دقيقة)")
    is_active = models.BooleanField(default=True, verbose_name="نشطة للتوصيل")
    notes = models.CharField(max_length=255, blank=True, default="", verbose_name="ملاحظات / بوابات")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإضافة")

    class Meta:
        app_label = 'core'
        verbose_name = "منطقة تغطية وكومبوند"
        verbose_name_plural = "المناطق والكومبوندات المغطاة"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_area_type_display()}) - {self.branch.name}"


class PlatformConfiguration(models.Model):
    """
    إعدادات المنصة المركزية الموحدة (Singleton Configuration):
    تُدار حصرياً من لوحة تحكم الإدارة الرئيسية (Django Admin /admin/) للمديرين.
    """
    google_maps_api_key = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="مفتاح خرائط جوجل العام (Google Maps API Key)",
        help_text="يُستخدم في تحويل العناوين غير الدقيقة إلى إحداثيات (Geocoding)، والتعرف على معالم الخريطة وروابط الواتساب، وحساب مسافة ووقت التوصيل اللحظي (Distance Matrix)."
    )
    default_delivery_base_fee = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=15.00,
        verbose_name="رسوم فتحة عداد التوصيل الافتراضية (Base Fee)",
        help_text="تُطبق عند حساب رسوم التوصيل الحر بالمسافة في حال عدم وجود تسعيرة منطقة محددة."
    )
    default_delivery_per_km_fee = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=3.00,
        verbose_name="رسوم الكيلومتر الإضافي (Per KM Fee)",
        help_text="سعر كل كيلومتر بعد المسافة الأساسية."
    )
    default_base_distance_km = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=3.00,
        verbose_name="المسافة الأساسية المغطاة بفتحة العداد (كم)",
        help_text="المسافة المشمولة في السعر الأساسي قبل تطبيق رسوم الكيلومتر الإضافي."
    )
    max_delivery_radius_km = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=25.00,
        verbose_name="أقصى نطاق توصيل مسموح به (كم)",
        help_text="إذا زادت مسافة العميل عن هذا الحد يعتبر خارج نطاق التوصيل ويُقترح عليه الاستلام من الفرع."
    )
    average_kitchen_prep_minutes = models.PositiveIntegerField(
        default=20,
        verbose_name="متوسط وقت تجهيز الوجبة بالمطبخ (دقيقة)",
        help_text="يُضاف إلى زمن مسار التوصيل من جوجل لحساب وقت التسليم الكلي للعميل."
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخر تحديث")

    class Meta:
        app_label = 'core'
        verbose_name = "إعدادات المنصة المركزية"
        verbose_name_plural = "إعدادات المنصة المركزية (Google Maps & Delivery)"

    def __str__(self):
        return "إعدادات المنصة المركزية (Google Maps & Delivery)"

    @classmethod
    def get_solo(cls):
        obj, created = cls.objects.get_or_create(id=1)
        return obj
