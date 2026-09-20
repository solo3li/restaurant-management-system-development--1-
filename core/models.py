from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
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
        return feature_key in (self.subscription_plan.features or [])

    def is_subscription_active(self):
        if not self.is_active:
            return False
        if self.subscription_status in ["active", "trial"]:
            if self.subscription_end and self.subscription_end < timezone.now():
                return False
            return True
        return False

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


PERMISSIONS_CATALOG = [
    {
        "category": "لوحات التحكم والتقارير المالية",
        "icon": "📊",
        "permissions": [
            {"key": "view_hq_dashboard", "label": "لوحة الإدارة العامة (HQ)", "desc": "الاطلاع على أداء السلسلة ومؤشراتها العامة"},
            {"key": "view_branch_dashboard", "label": "لوحة تحكم الفرع", "desc": "الاطلاع على مؤشرات وإحصائيات الفرع المحدد"},
            {"key": "view_financials", "label": "الاطلاع على الأرقام المالية", "desc": "كشف إجمالي المبيعات، الإيرادات، وتفاصيل الكاش والبطاقات"},
        ]
    },
    {
        "category": "نقاط البيع والطلبات والفواتير",
        "icon": "💳",
        "permissions": [
            {"key": "pos_access", "label": "شاشة الكاشير ونقاط البيع (POS)", "desc": "تسجيل طلبات الصالة والسفري وإصدار الفواتير"},
            {"key": "view_orders", "label": "استعراض سجل الطلبات والفواتير", "desc": "رؤية قائمة الطلبات وطباعة الإيصالات والبحث"},
            {"key": "edit_orders", "label": "تعديل تفاصيل الطلبات", "desc": "إمكانية تغيير أصناف وملاحظات وحالة الطلبات القائمة"},
            {"key": "cancel_orders", "label": "إلغاء الطلبات", "desc": "إلغاء طلب وتغيير حالته إلى ملغي"},
            {"key": "delete_orders", "label": "حذف الطلبات نهائياً (حساس)", "desc": "حذف سجل الطلب بالكامل من قاعدة البيانات"},
        ]
    },
    {
        "category": "المطبخ والتوصيل والكول سنتر",
        "icon": "🍳",
        "permissions": [
            {"key": "kds_access", "label": "شاشة المطبخ وتحضير الوجبات (KDS)", "desc": "متابعة الطلبات وتحديث حالتها إلى جاهزة للتسليم"},
            {"key": "call_center_access", "label": "شاشة الكول سنتر وخدمة العملاء", "desc": "استقبال المكالمات وتوجيه الطلبات وتسجيلها"},
            {"key": "delivery_access", "label": "إدارة التوصيل وتعيين السائقين", "desc": "متابعة كباتن التوصيل وتوزيع الأوردرات عليهم"},
        ]
    },
    {
        "category": "قائمة الطعام والمخزون",
        "icon": "📋",
        "permissions": [
            {"key": "manage_menu", "label": "إدارة قائمة الطعام والأسعار", "desc": "إضافة وتعديل وحذف الوجبات وتحديد توفرها بالفروع"},
            {"key": "manage_inventory", "label": "إدارة المخزون والمواد الخام", "desc": "جرد وتعديل كميات المستودع والمكونات"},
        ]
    },
    {
        "category": "الفروع والموظفين والمسميات",
        "icon": "👥",
        "permissions": [
            {"key": "manage_branches", "label": "إدارة الفروع ونطاقات التوصيل", "desc": "افتتاح فروع جديدة وتحديد زون الخريطة والكمبوندات"},
            {"key": "manage_employees", "label": "إدارة الموظفين والرواتب", "desc": "تعيين موظفين جدد، تعديل الرواتب وتعيين الفروع"},
            {"key": "manage_roles", "label": "إدارة المسميات والصلاحيات", "desc": "إنشاء وتعديل وحذف المسميات الوظيفية ومصفوفة الصلاحيات"},
        ]
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
    name = models.CharField(max_length=100, verbose_name="اسم المسمى الوظيفي")
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default="branch", verbose_name="نطاق العمل")
    description = models.CharField(max_length=255, blank=True, default="", verbose_name="وصف المهام")
    is_system = models.BooleanField(default=False, verbose_name="مسمى أساسي للنظام")
    permissions = models.JSONField(default=list, blank=True, verbose_name="مصفوفة الصلاحيات")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخر تحديث")

    class Meta:
        verbose_name = "مسمى وظيفي وصلاحيات"
        verbose_name_plural = "المسميات الوظيفية والصلاحيات"
        unique_together = ("tenant", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_scope_display()})"

    def has_perm(self, perm_key):
        return perm_key in (self.permissions or [])


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
        if self.job_role:
            return self.job_role.has_perm(perm_key)
        # Fallback for legacy role choices
        if self.role == "manager":
            return perm_key not in ["delete_orders", "view_hq_dashboard", "manage_branches"]
        if self.role == "cashier":
            return perm_key in ["pos_access", "view_orders"]
        if self.role == "chef":
            return perm_key in ["kds_access"]
        if self.role == "driver":
            return perm_key in ["delivery_access"]
        if self.role == "call_center":
            return perm_key in ["call_center_access", "view_orders"]
        return False

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
        if self.job_role:
            return self.job_role.has_perm(perm_key)
        # Check attached employee profile
        if hasattr(self.user, "employee_profile") and self.user.employee_profile:
            return self.user.employee_profile.has_perm(perm_key)
        # Fallback for legacy role choices
        if self.role == "branch_manager":
            return perm_key not in ["delete_orders", "view_hq_dashboard", "manage_branches"]
        if self.role == "cashier":
            return perm_key in ["pos_access", "view_orders"]
        if self.role == "chef":
            return perm_key in ["kds_access"]
        if self.role == "driver":
            return perm_key in ["delivery_access"]
        if self.role == "call_center":
            return perm_key in ["call_center_access", "view_orders"]
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
