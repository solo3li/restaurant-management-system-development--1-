import secrets
from datetime import timedelta
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth.hashers import make_password, check_password


SAAS_FEATURES_CATALOG = [
    {"key": "pos", "label": "شاشة الكاشير ونقاط البيع (POS)", "desc": "تسجيل طلبات الصالة والسفري والفواتير"},
    {"key": "kds", "label": "شاشة المطبخ وتحضير الوجبات (KDS)", "desc": "إدارة تجهيز وتحضير الوجبات فورياً"},
    {"key": "menu_management", "label": "إدارة قائمة الطعام والوجبات", "desc": "تعديل الأسعار وإتاحة الأطباق بالفروع"},
    {"key": "delivery_management", "label": "نظام التوصيل ومناطق الخريطة", "desc": "تحديد الزون والكمبوندات وإسناد السائقين"},
    {"key": "call_center", "label": "الكول سنتر وخدمة العملاء", "desc": "استقبال طلبات الهاتف والتوجيه الآلي للفروع"},
    {"key": "inventory", "label": "إدارة المخزون والمواد الخام", "desc": "المستودعات والجرد وتنبيهات النواقص"},
    {"key": "custom_roles", "label": "المسميات الوظيفية والصلاحيات المخصصة", "desc": "إنشاء مسميات مخصصة ومصفوفة الصلاحيات"},
    {"key": "financial_analytics", "label": "التقارير والتحليلات المالية", "desc": "مؤشرات الإيرادات والمبيعات وتفاصيل الدفع"},
]


class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=100, verbose_name="اسم الباقة")
    code = models.SlugField(max_length=50, unique=True, verbose_name="كود الباقة")
    description = models.CharField(max_length=255, blank=True, default="", verbose_name="وصف الباقة")
    price_monthly = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="السعر الشهري (ر.س)")
    price_yearly = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="السعر السنوي (ر.س)")
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
        verbose_name = "باقة اشتراك SaaS"
        verbose_name_plural = "باقات اشتراك المنصة"
        ordering = ["ordering", "price_monthly"]

    def __str__(self):
        return f"{self.name} ({self.price_monthly} ر.س/شهر)"


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
    phone = models.CharField(max_length=50, default="", blank=True, verbose_name="رقم الهاتف")
    email = models.EmailField(blank=True, default="", verbose_name="البريد الإلكتروني")
    address = models.CharField(max_length=255, default="", blank=True, verbose_name="المقر الرئيسي")
    plan = models.CharField(max_length=30, choices=PLAN_CHOICES, default="standard", verbose_name="خطة الاشتراك")

    subscription_plan = models.ForeignKey(
        SubscriptionPlan,
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
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التسجيل")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخر تحديث")

    class Meta:
        verbose_name = "مستأجر / منشأة"
        verbose_name_plural = "المستأجرون (المنشآت والمطاعم)"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.slug})"

    def can_add_branch(self):
        if not self.subscription_plan:
            return True
        limit = self.subscription_plan.max_branches
        if limit is None or limit <= 0:
            return True
        return self.branches.count() < limit

    def can_add_employee(self):
        if not self.subscription_plan:
            return True
        limit = self.subscription_plan.max_employees
        if limit is None or limit <= 0:
            return True
        return self.employees.count() < limit

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
    city = models.CharField(max_length=100, default="", blank=True, verbose_name="المدينة")
    address = models.CharField(max_length=255, default="", blank=True, verbose_name="العنوان")
    phone = models.CharField(max_length=50, default="", blank=True, verbose_name="الهاتف")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active", verbose_name="الحالة")
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط العرض")
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="خط الطول")
    delivery_polygon = models.JSONField(default=list, blank=True, verbose_name="مضلع التغطية على الخريطة")
    delivery_radius_km = models.DecimalField(max_digits=5, decimal_places=2, default=5.00, verbose_name="نصف قطر التغطية (كم)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "فرع"
        verbose_name_plural = "الفروع"
        ordering = ["id"]

    def __str__(self):
        tenant_name = f" [{self.tenant.name}]" if self.tenant else ""
        return f"{self.name}{tenant_name}"


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
        verbose_name = "منطقة تغطية وكومبوند"
        verbose_name_plural = "المناطق والكومبوندات المغطاة"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_area_type_display()}) - {self.branch.name}"


RESTAURANT_PERMISSIONS = [
    # 1. POS & Cashier
    ("pos_access", "فتح واستخدام شاشة الكاشير ونقاط البيع (POS)"),
    ("pos_create_order", "تسجيل وإنشاء طلب جديد بالصالة أو السفري أو التوصيل"),
    ("pos_apply_discount", "تطبيق الخصومات والعروض والكوبونات على الطلب"),
    ("pos_override_price", "تعديل أسعار الأصناف يدوياً في الفاتورة"),
    ("pos_void_item", "إلغاء وحذف أصناف أثناء إدخال الطلب"),
    ("pos_cancel_order", "إلغاء طلب مسجل ومؤكد"),
    ("pos_refund_order", "استرجاع الفواتير ورد المبالغ للعميل"),
    ("pos_reprint_receipt", "إعادة طباعة الفواتير والإيصالات القديمة"),
    ("pos_manage_shift", "فتح وإغلاق وردية الكاشير واستخراج تقرير Z-Report"),
    ("pos_cash_drawer", "فتح درج النقدية يدوياً وسحب وإيداع نقدية"),
    ("view_orders", "استعراض سجل الطلبات والفواتير"),
    ("edit_orders", "تعديل تفاصيل الطلبات القائمة"),
    ("cancel_orders", "إلغاء الطلبات المسجلة"),
    ("delete_orders", "حذف الطلبات نهائياً من قاعدة البيانات (حساس)"),

    # 2. Kitchen KDS
    ("kds_access", "الوصول لشاشة المطبخ وإعداد الطلبات (KDS)"),
    ("kds_update_status", "تحديث حالة الوجبات (قيد الطهي / جاهز للتسليم)"),
    ("kds_recall_order", "استرجاع طلب تم إتمامه بالخطأ لشاشة الطهي"),
    ("kds_pause_item", "تعليق إعداد صنف معين مؤقتاً في المطبخ"),

    # 3. Menu & Pricing
    ("menu_view", "استعراض قائمة الطعام والأطباق والأسعار"),
    ("menu_create_item", "إضافة وجبة أو طبق جديد للقائمة"),
    ("menu_edit_item", "تعديل بيانات وتفاصيل ومكونات الوجبة"),
    ("menu_change_price", "تعديل أسعار الوجبات في المنيو"),
    ("menu_delete_item", "حذف وجبة من قائمة الطعام نهائياً"),
    ("menu_toggle_availability", "تفعيل أو إيقاف توفر الطبق بالفرع (نفدت الكمية)"),
    ("menu_manage_categories", "إدارة وتعديل أقسام وتصنيفات المنيو"),
    ("menu_manage_modifiers", "إدارة الإضافات والخيارات والمكونات الإضافية"),
    ("manage_menu", "إدارة المنيو وتوفر الأصناف بالكامل"),

    # 4. Delivery & Fleet
    ("delivery_access", "الوصول للوحة متابعة التوصيل وإدارة السائقين"),
    ("delivery_assign_driver", "إسناد وتعيين الطلبات للسائقين"),
    ("delivery_track_drivers", "تتبع حركة ومسارات السائقين الحية على الخريطة"),
    ("delivery_manage_zones", "إدارة نطاقات ومناطق ورسوم التوصيل بالفروع"),
    ("delivery_override_status", "تحديث حالة التوصيل يدوياً (تم التسليم / تعذر)"),

    # 5. AI Call Center
    ("call_center_access", "الوصول لشاشة الكول سنتر واستقبال المكالمات الحية"),
    ("call_center_create_order", "تسجيل طلبات هاتفية للعملاء وتوجيهها للفروع"),
    ("call_center_manage_ai", "تعديل إعدادات وبرومبت وصوت وكيل الذكاء الاصطناعي"),
    ("call_center_view_logs", "الاستماع للمكالمات المسجلة ومراجعة سجلات المحادثة"),
    ("call_center_view_customers", "استعراض وإدارة قاعدة بيانات العملاء وعناوينهم"),

    # 6. Inventory & Purchasing
    ("inventory_view", "استعراض كميات المخزون والمواد الأولية والتنبيهات"),
    ("inventory_add_stock", "تسجيل فواتير الشراء وتوريد مواد جديدة للمستودع"),
    ("inventory_adjust_stock", "تسوية وتعديل كميات المخزون يدوياً (الجرد الفعلي)"),
    ("inventory_record_waste", "تسجيل هدر وتالف المواد الغذائية والمكونات"),
    ("inventory_transfer_stock", "تحويل ونقل المواد بين الفروع والمستودعات"),
    ("inventory_manage_suppliers", "إدارة الموردين وبياناتهم والأسعار المتفق عليها"),
    ("manage_inventory", "إدارة المستودعات والمخزون بالكامل"),

    # 7. Financials & Accounting
    ("finance_view_sales", "رؤية أرقام المبيعات والإيرادات اليومية واللحظية"),
    ("finance_view_reports", "الاطلاع على التقارير المالية والتحليلات الدورية"),
    ("finance_view_profit_loss", "الاطلاع على هوامش الربح وتقارير الأرباح والخسائر"),
    ("finance_export_tax_reports", "تصدير الفواتير والتقارير الضريبية المعتمدة لـ ZATCA"),
    ("finance_view_staff_performance", "الاطلاع على تقارير إنتاجية ومبيعات الموظفين والسائقين"),
    ("view_financials", "الاطلاع على الأرقام المالية ومبيعات الفروع"),

    # 8. Staff & HR
    ("hr_view_employees", "استعراض قائمة الموظفين وطاقم العمل"),
    ("hr_create_employee", "إضافة وتعيين موظف جديد في النظام"),
    ("hr_edit_employee", "تعديل بيانات الموظف والفرع والبيانات الوظيفية"),
    ("hr_manage_salaries", "تحديد وتعديل الرواتب والبدلات والمكافآت والخصومات"),
    ("hr_manage_credentials", "تعيين وتوليد رمز PIN وكود تسجيل الدخول للموظف"),
    ("hr_deactivate_employee", "تجميد أو إنهاء حساب موظف وسحب حق الدخول"),
    ("hr_manage_shifts", "جدولة الورديات وتسجيل الحضور والانصراف وساعات العمل"),
    ("manage_employees", "إدارة الموظفين والرواتب بالكامل"),

    # 9. HQ & Multi-Branch
    ("hq_view_master_dashboard", "الوصول للوحة القيادة العامة المجمعة لكل الفروع HQ"),
    ("branch_view_dashboard", "الوصول للوحة مؤشرات وعمليات الفرع الخاص"),
    ("branch_switch_branches", "التبديل بين الفروع واستعراض فروع متعددة للمطعم"),
    ("branch_manage_branches", "إنشاء فروع جديدة وتعديل بياناتها وساعات العمل"),
    ("view_hq_dashboard", "لوحة الإدارة العامة (HQ)"),
    ("view_branch_dashboard", "لوحة تحكم الفرع"),
    ("manage_branches", "إدارة الفروع ونطاقات التوصيل"),

    # 10. System & RBAC Settings
    ("system_manage_roles", "إنشاء وتعديل مسميات الوظائف وتوزيع الصلاحيات"),
    ("system_assign_permissions", "منح أو سحب صلاحيات مباشرة استثنائية لموظف بعينه"),
    ("system_manage_settings", "تعديل بيانات المنشأة والهوية والرقم الضريبي واللوجو"),
    ("system_manage_billing", "إدارة باقة الاشتراك والفوترة وتجديد اشتراك المنصة"),
    ("manage_roles", "إدارة المسميات والصلاحيات"),
]


PERMISSIONS_CATALOG = [
    {
        "category": "نقاط البيع والكاشير (POS)",
        "icon": "💳",
        "permissions": [
            {"key": "pos_access", "label": "شاشة الكاشير (POS)", "desc": "فتح واستخدام شاشة نقاط البيع وإصدار الفواتير"},
            {"key": "pos_create_order", "label": "تسجيل وإنشاء طلب", "desc": "تسجيل طلبات الصالة والسفري والتوصيل"},
            {"key": "pos_apply_discount", "label": "تطبيق الخصومات والعروض", "desc": "تخفيض الفاتورة وتطبيق الكوبونات"},
            {"key": "pos_override_price", "label": "تعديل السعر يدوياً", "desc": "تغيير سعر الصنف داخل الفاتورة يدوياً"},
            {"key": "pos_void_item", "label": "حذف صنف أثناء الطلب", "desc": "إلغاء صنف قبل إتمام الدفع والطباعة"},
            {"key": "pos_cancel_order", "label": "إلغاء طلب مؤكد", "desc": "إلغاء الفواتير المسجلة بعد الطباعة"},
            {"key": "pos_refund_order", "label": "استرجاع الفاتورة ورد المبلغ", "desc": "استرداد الأموال للعميل نقدية أو شبكة"},
            {"key": "pos_reprint_receipt", "label": "إعادة طباعة الفاتورة", "desc": "طباعة نسخ مكررة من الفواتير القديمة"},
            {"key": "pos_manage_shift", "label": "تقفيل الوردية (Z-Report)", "desc": "إغلاق الدرج وإصدار التقرير النهائي للوردية"},
            {"key": "pos_cash_drawer", "label": "درج النقدية وسحب/إيداع", "desc": "فتح الدرج يدوياً وتسجيل السحب والإيداع النقدي"},
            {"key": "view_orders", "label": "استعراض سجل الفواتير", "desc": "رؤية قائمة الطلبات السابقة وحالاتها"},
            {"key": "edit_orders", "label": "تعديل الطلبات القائمة", "desc": "إمكانية تغيير أصناف وحالة الطلب الجاري"},
            {"key": "cancel_orders", "label": "إلغاء الطلبات المسجلة - توافقي", "desc": "إلغاء الطلبات المسجلة والفواتير المعتمدة"},
            {"key": "delete_orders", "label": "حذف الطلب نهائياً (حساس)", "desc": "مسح سجل الفاتورة بالكامل من قاعدة البيانات"},
        ]
    },
    {
        "category": "المطبخ وإعداد الوجبات (KDS)",
        "icon": "🍳",
        "permissions": [
            {"key": "kds_access", "label": "شاشة المطبخ (KDS)", "desc": "متابعة أوامر الطبخ والوجبات الجارية فورياً"},
            {"key": "kds_update_status", "label": "تحديث حالة التحضير", "desc": "تحويل الطلب إلى قيد الطهي أو جاهز للتسليم"},
            {"key": "kds_recall_order", "label": "استرجاع طلب تم إتمامه", "desc": "إعادة الطلب لشاشة الطهي في حال الخطأ"},
            {"key": "kds_pause_item", "label": "تعليق إعداد صنف مؤقتاً", "desc": "إشعار الصالة بتأخير أو تعليق صنف محدد بالمطبخ"},
        ]
    },
    {
        "category": "قائمة الطعام والأسعار (Menu)",
        "icon": "📋",
        "permissions": [
            {"key": "menu_view", "label": "استعراض قائمة الطعام", "desc": "الاطلاع على الأطباق والأسعار والتصنيفات"},
            {"key": "menu_create_item", "label": "إضافة وجبة جديدة", "desc": "إنشاء أصناف ووجبات جديدة بالمنيو"},
            {"key": "menu_edit_item", "label": "تعديل تفاصيل الوجبة", "desc": "تعديل صور ومكونات ووصف الأطباق"},
            {"key": "menu_change_price", "label": "تعديل أسعار الأصناف", "desc": "تغيير الأسعار الرسمية للأطباق بالمنيو"},
            {"key": "menu_delete_item", "label": "حذف وجبة من القائمة", "desc": "حذف الصنف نهائياً من قاعدة بيانات المنيو"},
            {"key": "menu_toggle_availability", "label": "توفر الأصناف بالفرع", "desc": "إيقاف أو تفعيل توفر الصنف في مطبخ الفرع (نفدت الكمية)"},
            {"key": "menu_manage_categories", "label": "إدارة تصنيفات المنيو", "desc": "إضافة وتعديل أقسام المنيو (مشويات، مقبلات...)"},
            {"key": "menu_manage_modifiers", "label": "إدارة الإضافات والخيارات", "desc": "التحكم في خيارات الأطباق (إضافات، أحجام، صوصات)"},
            {"key": "manage_menu", "label": "إدارة المنيو وتوفر الأصناف - شامل", "desc": "التحكم الكامل في المنيو وتوفر الأصناف سحابياً وبالفروع"},
        ]
    },
    {
        "category": "التوصيل والأسطول والسائقين",
        "icon": "🛵",
        "permissions": [
            {"key": "delivery_access", "label": "لوحة متابعة التوصيل", "desc": "متابعة كباتن التوصيل والطلبات الجاهزة للنقل"},
            {"key": "delivery_assign_driver", "label": "إسناد الطلبات للسائقين", "desc": "تعيين وتوزيع الطلبات على السائقين المتاحين"},
            {"key": "delivery_track_drivers", "label": "تتبع مسارات السائقين", "desc": "متابعة مسارات الكباتن الحية على الخريطة"},
            {"key": "delivery_manage_zones", "label": "إدارة نطاقات ورسوم التوصيل", "desc": "تحديد مناطق وأحياء ورسوم التوصيل بالفروع"},
            {"key": "delivery_override_status", "label": "تعديل حالة التوصيل يدوياً", "desc": "تأكيد التسليم اليدوي أو معالجة تعذر التوصيل"},
        ]
    },
    {
        "category": "الكول سنتر والذكاء الاصطناعي",
        "icon": "🎧",
        "permissions": [
            {"key": "call_center_access", "label": "شاشة الكول سنتر الحية", "desc": "استقبال وإجراء المكالمات الهاتفية للعملاء"},
            {"key": "call_center_create_order", "label": "تسجيل طلبات الهاتف", "desc": "إنشاء طلب هاتف وتوجيهه للفرع الأنسب آلياً"},
            {"key": "call_center_manage_ai", "label": "إعدادات صوت الذكاء الاصطناعي", "desc": "تعديل شخصية وبرومبت وصوت وكيل AI"},
            {"key": "call_center_view_logs", "label": "مراجعة المكالمات المسجلة", "desc": "الاستماع لتسجيلات العملاء ومراجعة المحادثات"},
            {"key": "call_center_view_customers", "label": "بيانات وسجل العملاء", "desc": "استعراض سجل طلبات العملاء وعناوينهم الهاتفية"},
        ]
    },
    {
        "category": "المستودعات والمخزون والتوريد",
        "icon": "📦",
        "permissions": [
            {"key": "inventory_view", "label": "استعراض أرصدة المخزون", "desc": "رؤية كميات المواد الخام ونواقص المستودع"},
            {"key": "inventory_add_stock", "label": "تسجيل فواتير الشراء والتوريد", "desc": "إدخال بضاعة وتوريدات جديدة للمستودع"},
            {"key": "inventory_adjust_stock", "label": "جرد وتسوية المخزون", "desc": "تعديل الكميات الفعلية ومطابقة الجرد"},
            {"key": "inventory_record_waste", "label": "تسجيل الهدر والتالف", "desc": "حصر المواد الغذائية التالفة أو منتهية الصلاحية"},
            {"key": "inventory_transfer_stock", "label": "تحويل المواد بين الفروع", "desc": "نقل وتوريد بضائع من فرع أو مستودع لآخر"},
            {"key": "inventory_manage_suppliers", "label": "إدارة شركات التوريد", "desc": "بيانات الموردين والأسعار وسجل المشتريات"},
            {"key": "manage_inventory", "label": "إدارة المستودعات والمخزون - شامل", "desc": "إدارة المستودعات والمخزون بالكامل وحذف المواد الأولية"},
        ]
    },
    {
        "category": "التقارير المالية والمحاسبة",
        "icon": "📊",
        "permissions": [
            {"key": "finance_view_sales", "label": "رؤية المبيعات اليومية الحية", "desc": "الاطلاع على أرقام المبيعات النقدية والشبكة لحظياً"},
            {"key": "finance_view_reports", "label": "التقارير التحليلية والدورية", "desc": "مؤشرات نمو المبيعات الشهرية والسنوية"},
            {"key": "finance_view_profit_loss", "label": "تقارير الأرباح والتكاليف", "desc": "الاطلاع على هوامش الربح وصافي الأرباح التشغيلية"},
            {"key": "finance_export_tax_reports", "label": "تصدير فواتير وتقارير ZATCA", "desc": "استخراج الإقرارات الضريبية وتقارير هيئة الزكاة"},
            {"key": "finance_view_staff_performance", "label": "تقارير أداء الكاشير والموظفين", "desc": "مقارنة مبيعات الموظفين وإنتاجية السائقين"},
            {"key": "view_financials", "label": "كشف الأرقام المالية العامة", "desc": "إظهار أو حجب بطاقات المبيعات النقدية في لوحة الفرع"},
        ]
    },
    {
        "category": "الموظفين والرواتب والورديات (HR)",
        "icon": "👥",
        "permissions": [
            {"key": "hr_view_employees", "label": "استعراض قائمة الموظفين", "desc": "رؤية طاقم العمل والورديات الحالية"},
            {"key": "hr_create_employee", "label": "إضافة وتعيين موظف جديد", "desc": "تسجيل موظف جديد بالمنشأة"},
            {"key": "hr_edit_employee", "label": "تعديل بيانات الموظف والفرع", "desc": "تحديث هاتف وبيانات ونقل الموظف بين الفروع"},
            {"key": "hr_manage_salaries", "label": "إدارة الرواتب والبدلات", "desc": "تعديل الراتب الأساسي، المكافآت والخصومات"},
            {"key": "hr_manage_credentials", "label": "إدارة رمز PIN وكود الموظف", "desc": "توليد أو تغيير رمز PIN للدخول السريع"},
            {"key": "hr_deactivate_employee", "label": "تجميد أو إنهاء حساب موظف", "desc": "إيقاف الموظف وسحب حق الدخول نهائياً"},
            {"key": "hr_manage_shifts", "label": "جدولة الورديات وساعات العمل", "desc": "توزيع الشيفتات وتسجيل الحضور والانصراف"},
            {"key": "manage_employees", "label": "إدارة الموظفين والرواتب - شامل", "desc": "إدارة طاقم العمل والرواتب والورديات بالكامل"},
        ]
    },
    {
        "category": "الفروع والإدارة العامة (HQ)",
        "icon": "🏢",
        "permissions": [
            {"key": "hq_view_master_dashboard", "label": "لوحة القيادة العامة المجمعة (HQ)", "desc": "الاطلاع على أداء السلسلة ومؤشراتها العامة المجمعة"},
            {"key": "branch_view_dashboard", "label": "لوحة مؤشرات الفرع المحلي", "desc": "الاطلاع على مؤشرات وإحصائيات الفرع المحدد"},
            {"key": "branch_switch_branches", "label": "التنقل واستعراض الفروع الأخرى", "desc": "حرية استعراض فروع متعددة للمطعم"},
            {"key": "branch_manage_branches", "label": "إدارة وافتتاح الفروع الجديدة", "desc": "إنشاء فروع جديدة وتعديل بياناتها وساعات العمل"},
            {"key": "view_hq_dashboard", "label": "لوحة الإدارة العامة (HQ) - توافقي", "desc": "رؤية لوحة HQ"},
            {"key": "view_branch_dashboard", "label": "لوحة تحكم الفرع - توافقي", "desc": "رؤية لوحة الفرع"},
            {"key": "manage_branches", "label": "إدارة الفروع - توافقي", "desc": "إدارة الفروع ونطاقات التوصيل"},
        ]
    },
    {
        "category": "إدارة المنشأة والأدوار (System & Settings)",
        "icon": "⚙️",
        "permissions": [
            {"key": "system_manage_roles", "label": "إدارة المسميات والصلاحيات (RBAC)", "desc": "إنشاء وتعديل وحذف المسميات ومصفوفة الصلاحيات"},
            {"key": "system_assign_permissions", "label": "تخصيص صلاحيات استثنائية لموظف", "desc": "منح أو سحب صلاحيات فردية لموظف دون تغيير مسمى عمله"},
            {"key": "system_manage_settings", "label": "إعدادات المنشأة والهوية والضريبة", "desc": "تعديل اسم المطعم والشعار والرقم الضريبي"},
            {"key": "system_manage_billing", "label": "إدارة الفوترة والاشتراك السحابي", "desc": "الاطلاع على باقة SaaS وتجديد الاشتراك"},
            {"key": "manage_roles", "label": "إدارة المسميات - توافقي", "desc": "إدارة الصلاحيات والمسميات"},
        ]
    },
]


PRESET_ROLES_CONFIG = [
    {
        "name": "مدير عام / إدارة عليا",
        "scope": "hq",
        "description": "إشراف وتحكم كامل في جميع موديولات وفروع وسجلات المطعم",
        "is_system": True,
        "permissions": [p[0] for p in RESTAURANT_PERMISSIONS],
    },
    {
        "name": "مدير فرع",
        "scope": "branch",
        "description": "إدارة العمليات اليومية للفرع، الكاشير، المطبخ، الموظفين، والمخزون",
        "is_system": True,
        "permissions": [
            "branch_view_dashboard", "view_branch_dashboard",
            "pos_access", "pos_create_order", "pos_apply_discount", "pos_void_item", "pos_cancel_order",
            "pos_reprint_receipt", "pos_manage_shift", "pos_cash_drawer", "view_orders", "edit_orders", "cancel_orders",
            "kds_access", "kds_update_status", "kds_recall_order", "kds_pause_item",
            "menu_view", "menu_toggle_availability", "manage_menu",
            "delivery_access", "delivery_assign_driver", "delivery_track_drivers", "delivery_override_status",
            "inventory_view", "inventory_add_stock", "inventory_adjust_stock", "inventory_record_waste", "manage_inventory",
            "finance_view_sales", "finance_view_reports", "view_financials",
            "hr_view_employees", "hr_manage_shifts", "hr_manage_credentials", "manage_employees",
        ],
    },
    {
        "name": "محاسب / مالي",
        "scope": "both",
        "description": "الاطلاع على التقارير المالية، إقرارات الضريبة ZATCA، الأرباح، وفواتير المشتريات",
        "is_system": True,
        "permissions": [
            "branch_view_dashboard", "view_branch_dashboard", "hq_view_master_dashboard", "view_hq_dashboard",
            "finance_view_sales", "finance_view_reports", "finance_view_profit_loss", "finance_export_tax_reports",
            "finance_view_staff_performance", "view_financials",
            "view_orders", "pos_reprint_receipt",
            "inventory_view",
            "hr_manage_salaries",
        ],
    },
    {
        "name": "كاشير رئيسي",
        "scope": "branch",
        "description": "مسؤول الوردية، تسجيل ومتابعة الطلبات، تطبيق الخصومات المصرحة، وإغلاق الوردية",
        "is_system": True,
        "permissions": [
            "pos_access", "pos_create_order", "pos_apply_discount", "pos_void_item", "pos_cancel_order",
            "pos_reprint_receipt", "pos_manage_shift", "pos_cash_drawer",
            "view_orders", "edit_orders", "cancel_orders",
            "finance_view_sales", "menu_view",
        ],
    },
    {
        "name": "كاشير صالة",
        "scope": "branch",
        "description": "تسجيل طلبات الصالة والسفري وإصدار الإيصالات فقط بدون صلاحيات خصم أو إلغاء",
        "is_system": True,
        "permissions": [
            "pos_access", "pos_create_order", "pos_reprint_receipt", "view_orders", "menu_view",
        ],
    },
    {
        "name": "طاهٍ رئيسي / مطبخ",
        "scope": "branch",
        "description": "شاشة المطبخ KDS، إعداد الوجبات، وتحديد توفر الأصناف في الفرع",
        "is_system": True,
        "permissions": [
            "kds_access", "kds_update_status", "kds_recall_order", "kds_pause_item",
            "menu_view", "menu_toggle_availability",
            "inventory_view", "inventory_adjust_stock", "inventory_record_waste",
        ],
    },
    {
        "name": "سائق توصيل",
        "scope": "branch",
        "description": "استلام الطلبات ومتابعة مسارات التوصيل وتأكيد التسليم للعملاء",
        "is_system": True,
        "permissions": [
            "delivery_access", "delivery_track_drivers", "delivery_override_status",
        ],
    },
    {
        "name": "موظف كول سنتر",
        "scope": "hq",
        "description": "استقبال اتصالات العملاء وتسجيل طلبات الهاتف وتوجيهها للفروع المناسبة",
        "is_system": True,
        "permissions": [
            "call_center_access", "call_center_create_order", "call_center_view_customers",
            "menu_view", "view_orders", "branch_switch_branches",
        ],
    },
]


class JobRole(models.Model):
    SCOPE_CHOICES = [
        ("hq", "إدارة عامة (HQ)"),
        ("branch", "تشغيل فرع"),
        ("both", "شامل (إدارة وفروع)"),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="job_roles",
        verbose_name="المطعم / المنشأة",
    )
    group = models.OneToOneField(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="job_role",
        verbose_name="مجموعة ديجانجو القياسية",
    )
    name = models.CharField(max_length=100, verbose_name="اسم المسمى الوظيفي")
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default="branch", verbose_name="نطاق العمل")
    description = models.CharField(max_length=255, blank=True, default="", verbose_name="وصف المهام")
    is_system = models.BooleanField(default=False, verbose_name="مسمى أساسي للنظام")
    ordering = models.IntegerField(default=10, verbose_name="ترتيب العرض")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخر تحديث")

    class Meta:
        verbose_name = "مسمى وظيفي وصلاحيات"
        verbose_name_plural = "المسميات الوظيفية والصلاحيات"
        unique_together = ("tenant", "name")
        ordering = ["ordering", "id"]
        permissions = RESTAURANT_PERMISSIONS

    def __str__(self):
        return f"{self.name} ({self.get_scope_display()})"

    def has_perm(self, perm_key):
        clean_key = perm_key.split(".")[-1]
        if self.group:
            return self.group.permissions.filter(codename=clean_key).exists()
        return False

    def get_permissions_list(self):
        if self.group:
            return list(self.group.permissions.values_list("codename", flat=True))
        return []

    def set_permissions(self, codenames):
        """Set permissions directly on the backing Django Group."""
        if not self.group:
            self.sync_with_django_group()
        from django.contrib.auth.models import Permission
        perm_objs = Permission.objects.filter(content_type__app_label="core", codename__in=codenames)
        self.group.permissions.set(perm_objs)
        # Invalidate permission caches for all linked employees
        for emp in self.employees.select_related("user"):
            if emp.user:
                emp.user.groups.set([self.group])
                for cache_field in ["_perm_cache", "_group_perm_cache", "_user_perm_cache"]:
                    if hasattr(emp.user, cache_field):
                        delattr(emp.user, cache_field)

    def sync_with_django_group(self):
        """Synchronize this JobRole with a Django auth Group."""
        if not self.tenant_id:
            return None
        from django.contrib.auth.models import Group
        group_name = f"t{self.tenant_id}_role_{self.id}"
        if not self.group:
            grp, _ = Group.objects.get_or_create(name=group_name)
            self.group = grp
            JobRole.objects.filter(id=self.id).update(group=grp)
        elif self.group.name != group_name:
            self.group.name = group_name
            self.group.save(update_fields=["name"])

        # Update and invalidate cache for all linked employees
        for emp in self.employees.select_related("user"):
            if emp.user:
                emp.user.groups.set([self.group])
                for cache_field in ["_perm_cache", "_group_perm_cache", "_user_perm_cache"]:
                    if hasattr(emp.user, cache_field):
                        delattr(emp.user, cache_field)

        return self.group

    def delete(self, *args, **kwargs):
        grp = self.group
        res = super().delete(*args, **kwargs)
        if grp:
            grp.delete()
        return res

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.tenant_id:
            self.sync_with_django_group()


def ensure_tenant_preset_roles(tenant):
    """Seed or update the 8 professional preset roles for a tenant and sync with Django groups."""
    created_or_updated = []
    for idx, cfg in enumerate(PRESET_ROLES_CONFIG):
        role, created = JobRole.objects.get_or_create(
            tenant=tenant,
            name=cfg["name"],
            defaults={
                "scope": cfg["scope"],
                "description": cfg["description"],
                "is_system": cfg["is_system"],
                "ordering": (idx + 1) * 10,
            }
        )
        if not created and role.is_system:
            # Refresh system preset permissions
            role.scope = cfg["scope"]
            role.description = cfg["description"]
            role.ordering = (idx + 1) * 10
            role.save()
        role.sync_with_django_group()
        role.set_permissions(cfg["permissions"])
        created_or_updated.append(role)
    return created_or_updated


class Employee(models.Model):
    ROLE_CHOICES = [
        ("manager", "مدير"),
        ("cashier", "كاشير"),
        ("chef", "طاهٍ"),
        ("driver", "سائق"),
        ("call_center", "خدمة عملاء"),
        ("waiter", "مباشر"),
    ]
    STATUS_CHOICES = [
        ("active", "على رأس العمل"),
        ("vacation", "في إجازة"),
        ("inactive", "غير نشط"),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="employees",
        null=True,
        blank=True,
        verbose_name="المستأجر / المنشأة",
    )
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_profile",
        verbose_name="حساب المستخدم المربوط",
    )
    name = models.CharField(max_length=255, verbose_name="اسم الموظف")
    employee_code = models.CharField(
        max_length=30,
        null=True,
        blank=True,
        verbose_name="كود الموظف للدخول السريع",
        help_text="مثال: 101 أو EMP-101",
    )
    pin_code = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        verbose_name="رمز PIN المشفر",
        help_text="رمز دخول سريع من 4 أرقام",
    )
    phone = models.CharField(max_length=50, default="", blank=True, verbose_name="الجوال")
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, verbose_name="المسمى الوظيفي")
    job_role = models.ForeignKey(
        JobRole,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name="المسمى الوظيفي المخصص",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name="الفرع",
    )
    salary = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="الراتب")
    hire_date = models.DateField(default=timezone.now, verbose_name="تاريخ التعيين")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active", verbose_name="الحالة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "موظف"
        verbose_name_plural = "الموظفون"
        ordering = ["id"]

    def set_pin(self, raw_pin):
        if raw_pin:
            self.pin_code = make_password(str(raw_pin).strip())
        else:
            self.pin_code = None

    def check_pin(self, raw_pin):
        if not self.pin_code or not raw_pin:
            return False
        return check_password(str(raw_pin).strip(), self.pin_code)

    def has_perm(self, perm_key):
        clean_key = perm_key.split(".")[-1]
        if self.user:
            if self.user.has_perm(f"core.{clean_key}"):
                return True
            if self.user.groups.filter(permissions__codename=clean_key).exists():
                return True
        if self.job_role:
            return self.job_role.has_perm(clean_key)
        return False

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.user:
            # Sync user is_active with employee status
            expected_active = (self.status == "active")
            if self.user.is_active != expected_active:
                self.user.is_active = expected_active
                self.user.save(update_fields=["is_active"])

            # Keep UserProfile in sync for tenant/branch scoping
            from django.apps import apps
            UserProfileModel = apps.get_model("core", "UserProfile")
            if UserProfileModel:
                UserProfileModel.objects.update_or_create(
                    user=self.user,
                    defaults={
                        "tenant": self.tenant,
                        "branch": self.branch,
                        "role": "staff"
                    }
                )

            if self.job_role:
                grp = self.job_role.sync_with_django_group()
                if grp:
                    self.user.groups.set([grp])
            else:
                self.user.groups.clear()

            for cache_field in ["_perm_cache", "_group_perm_cache", "_user_perm_cache"]:
                if hasattr(self.user, cache_field):
                    delattr(self.user, cache_field)

    def __str__(self):
        code_str = f" [{self.employee_code}]" if self.employee_code else ""
        role_label = self.job_role.name if self.job_role else self.get_role_display()
        return f"{self.name}{code_str} ({role_label})"


class MenuItem(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="menu_items",
        null=True,
        blank=True,
        verbose_name="المستأجر / المنشأة",
    )
    name = models.CharField(max_length=255, verbose_name="اسم الصنف")
    category = models.CharField(max_length=100, verbose_name="الفئة")
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="سعر البيع")
    cost = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="التكلفة")
    emoji = models.CharField(max_length=20, default="", blank=True, verbose_name="أيقونة")
    available = models.BooleanField(default=True, verbose_name="متوفر")

    class Meta:
        verbose_name = "صنف منيو"
        verbose_name_plural = "قائمة الطعام"
        ordering = ["id"]

    def __str__(self):
        return self.name


class InventoryItem(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="inventory_items",
        null=True,
        blank=True,
        verbose_name="المستأجر / المنشأة",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="inventory_items",
        verbose_name="الفرع",
    )
    name = models.CharField(max_length=255, verbose_name="اسم المادة")
    unit = models.CharField(max_length=50, default="كجم", verbose_name="الوحدة")
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="الكمية المتوفرة")
    min_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="حد الأمان الأدنى")
    supplier = models.CharField(max_length=255, default="", blank=True, verbose_name="المورد")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخر تحديث")

    class Meta:
        verbose_name = "عنصر مخزون"
        verbose_name_plural = "المخزون"
        ordering = ["id"]

    def __str__(self):
        return f"{self.name} - {self.branch.name}"


class Customer(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="customers",
        null=True,
        blank=True,
        verbose_name="المستأجر / المنشأة",
    )
    name = models.CharField(max_length=255, verbose_name="اسم العميل")
    phone = models.CharField(max_length=50, db_index=True, verbose_name="رقم الهاتف")
    address = models.CharField(max_length=255, default="", blank=True, verbose_name="العنوان")
    notes = models.TextField(default="", blank=True, verbose_name="ملاحظات")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التسجيل")

    class Meta:
        verbose_name = "عميل"
        verbose_name_plural = "العملاء"
        ordering = ["-id"]

    def __str__(self):
        return f"{self.name} ({self.phone})"


class Order(models.Model):
    TYPE_CHOICES = [
        ("dine_in", "محلي"),
        ("takeaway", "سفري"),
        ("delivery", "توصيل"),
    ]
    CHANNEL_CHOICES = [
        ("cashier", "الكاشير"),
        ("call_center", "الكول سنتر"),
    ]
    STATUS_CHOICES = [
        ("new", "جديد"),
        ("preparing", "قيد التحضير"),
        ("ready", "جاهز للتسليم"),
        ("out_for_delivery", "في الطريق"),
        ("delivered", "تم التسليم"),
        ("cancelled", "ملغي"),
    ]
    PAY_CHOICES = [
        ("cash", "نقداً"),
        ("card", "بطاقة"),
        ("wallet", "محفظة رقمية"),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="orders",
        null=True,
        blank=True,
        verbose_name="المستأجر / المنشأة",
    )
    order_number = models.CharField(max_length=50, unique=True, verbose_name="رقم الطلب")
    order_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="dine_in", verbose_name="نوع الطلب")
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default="cashier", verbose_name="القناة")
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        verbose_name="الفرع",
    )
    delivery_area = models.ForeignKey(
        "DeliveryArea",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        verbose_name="منطقة التوصيل / الكومبوند",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        verbose_name="العميل",
    )
    customer_name = models.CharField(max_length=255, default="عميل نقدي", verbose_name="اسم العميل")
    customer_phone = models.CharField(max_length=50, default="", blank=True, verbose_name="هاتف العميل")
    address = models.CharField(max_length=255, default="", blank=True, verbose_name="عنوان التوصيل")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="new", verbose_name="الحالة")
    pay_method = models.CharField(max_length=20, choices=PAY_CHOICES, default="cash", verbose_name="طريقة الدفع")
    paid = models.BooleanField(default=True, verbose_name="تم الدفع")
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="المجموع الفرعي")
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="رسوم التوصيل")
    discount = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="الخصم")
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="الإجمالي")
    cashier = models.CharField(max_length=255, default="", blank=True, verbose_name="الكاشير")
    driver = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_orders",
        verbose_name="السائق",
    )
    notes = models.TextField(default="", blank=True, verbose_name="ملاحظات")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="تاريخ ووقت الطلب")

    class Meta:
        verbose_name = "طلب"
        verbose_name_plural = "الطلبات"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.order_number} ({self.get_status_display()})"


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="الطلب",
    )
    menu_item = models.ForeignKey(
        MenuItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="صنف المنيو",
    )
    name = models.CharField(max_length=255, verbose_name="اسم الصنف")
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="سعر الوحدة")
    qty = models.PositiveIntegerField(default=1, verbose_name="الكمية")

    class Meta:
        verbose_name = "عنصر طلب"
        verbose_name_plural = "عناصر الطلبات"

    @property
    def line_total(self):
        return self.price * self.qty

    def __str__(self):
        return f"{self.name} x {self.qty}"


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ("platform_admin", "مسؤول المنصة العامة (SaaS Admin)"),
        ("owner", "مالك / إدارة عامة للمطعم"),
        ("branch_manager", "مدير فرع"),
        ("cashier", "كاشير"),
        ("chef", "طاهٍ / مطبخ"),
        ("driver", "سائق توصيل"),
        ("call_center", "خدمة عملاء"),
        ("waiter", "مباشر"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile", verbose_name="المستخدم")
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="user_profiles",
        verbose_name="المستأجر / المنشأة",
    )
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default="branch_manager", verbose_name="الدور والصلاحية")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_profiles", verbose_name="الفرع المعين")
    job_role = models.ForeignKey(
        JobRole,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_profiles",
        verbose_name="المسمى الوظيفي المخصص",
    )
    is_platform_admin = models.BooleanField(default=False, verbose_name="مسؤول النظام والمنصة بالكامل")

    class Meta:
        verbose_name = "ملف المستخدم"
        verbose_name_plural = "ملفات المستخدمين"

    def has_perm(self, perm_key):
        if self.is_platform_admin or self.role in ["owner", "platform_admin"]:
            return True
        clean_key = perm_key.split(".")[-1]
        if self.user:
            if self.user.has_perm(f"core.{clean_key}"):
                return True
            if self.user.groups.filter(permissions__codename=clean_key).exists():
                return True
        if self.job_role:
            return self.job_role.has_perm(clean_key)
        # Check attached employee profile
        if hasattr(self.user, "employee_profile") and self.user.employee_profile:
            return self.user.employee_profile.has_perm(clean_key)
        return False

    def __str__(self):
        tenant_str = f" [{self.tenant.name}]" if self.tenant else ""
        branch_str = f" - {self.branch.name}" if self.branch else ""
        role_label = self.job_role.name if self.job_role else self.get_role_display()
        return f"{self.user.username}{tenant_str} ({role_label}{branch_str})"


class BranchMenuAvailability(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="branch_menus", verbose_name="الفرع")
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name="branch_availabilities", verbose_name="صنف المنيو")
    is_available = models.BooleanField(default=True, verbose_name="متوفر في هذا الفرع")

    class Meta:
        verbose_name = "توفر الصنف بالفرع"
        verbose_name_plural = "توفر الأصناف بالفروع"
        unique_together = ("branch", "menu_item")

    def __str__(self):
        status = "متوفر" if self.is_available else "غير متوفر"
        return f"{self.menu_item.name} ({self.branch.name}) - {status}"


class UpgradeRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "قيد المراجعة"),
        ("approved", "تمت الموافقة"),
        ("rejected", "مرفوض"),
    ]

    tenant = models.ForeignKey(
        Tenant,
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

        extension_days = 365 if self.billing_cycle == "yearly" else 30
        base_time = tenant.subscription_end if (tenant.subscription_end and tenant.subscription_end > timezone.now()) else timezone.now()
        tenant.subscription_end = base_time + timedelta(days=extension_days)
        tenant.save()

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
            # If newly approved or tenant's current plan doesn't match requested plan:
            if is_new or old_status != "approved" or (self.tenant.subscription_plan_id != self.requested_plan_id):
                self.apply_upgrade()
        elif self.status == "rejected":
            if not self.reviewed_at:
                self.reviewed_at = timezone.now()

        super().save(*args, **kwargs)


class RestaurantOwnerManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(role="owner")


class RestaurantOwner(UserProfile):
    objects = RestaurantOwnerManager()

    class Meta:
        proxy = True
        verbose_name = "مالك منشأة / مطعم"
        verbose_name_plural = "قائمة الملاك (Restaurant Owners)"


class TenantSubscription(Tenant):
    class Meta:
        proxy = True
        verbose_name = "مشترك / اشتراك منشأة"
        verbose_name_plural = "قائمة المشتركين (Subscribers)"


def generate_api_key():
    return f"ak_live_{secrets.token_urlsafe(32)}"


class TenantApiKey(models.Model):
    tenant = models.ForeignKey(
        Tenant,
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
        Branch,
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
        verbose_name = "مفتاح ذكاء اصطناعي (API Key)"
        verbose_name_plural = "مفاتيح الذكاء الاصطناعي (AI Access Keys)"
        ordering = ["-created_at"]

    def __str__(self):
        branch_info = f" ({self.assigned_branch.name})" if self.assigned_branch else " (كافة الفروع)"
        return f"{self.tenant.name} - {self.name}{branch_info}"

    def record_usage(self, placed_order=False):
        self.last_used_at = timezone.now()
        if placed_order:
            self.total_orders_placed += 1
        self.save(update_fields=["last_used_at", "total_orders_placed"])




