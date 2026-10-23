from django.db import models
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone


RESTAURANT_PERMISSIONS = [
    # 1. POS & Cashier (Branch Scope)
    ("pos_access", "فتح واستخدام شاشة الكاشير ونقاط البيع (POS)"),
    ("pos_apply_discount", "تطبيق الخصومات والعروض والكوبونات على الطلب"),
    ("pos_cancel_order", "إلغاء فواتير وطلبات الكاشير"),
    ("pos_refund_order", "استرجاع الفواتير ورد المبالغ للعميل"),
    ("pos_manage_shift", "فتح وإغلاق وردية الكاشير وتقرير Z ودرج النقدية"),
    ("pos_reprint_receipt", "إعادة طباعة الفواتير والإيصالات القديمة"),

    # 2. Kitchen KDS (Branch Scope)
    ("kds_access", "الوصول لشاشة المطبخ وتحديث إعداد الطلبات (KDS)"),
    ("kds_recall_order", "استرجاع طلب تم إتمامه بالخطأ لشاشة الطهي"),
    ("kds_pause_item", "تعليق إعداد صنف معين مؤقتاً في المطبخ"),

    # 3. Delivery & Fleet (Branch Scope)
    ("delivery_access", "الوصول للوحة متابعة التوصيل وإدارة السائقين"),
    ("delivery_assign_driver", "إسناد وتعيين الطلبات للسائقين"),
    ("delivery_override_status", "تحديث حالة التوصيل يدوياً وتأكيد التسليم"),
    ("delivery_track_drivers", "تتبع حركة ومسارات السائقين الحية على الخريطة"),

    # 4. Branch Orders (Branch Scope)
    ("branch_view_orders", "استعراض وبحث سجل طلبات وفواتير الفرع الحالي"),
    ("branch_edit_orders", "تعديل تفاصيل وملاحظات طلبات الفرع القائمة"),
    ("branch_cancel_orders", "إلغاء فواتير وطلبات الفرع المعتمدة"),
    ("branch_delete_orders", "حذف فواتير الفرع نهائياً من قاعدة البيانات (حساس)"),

    # 5. Branch Menu & Pricing (Branch Scope)
    ("menu_view", "استعراض قائمة الطعام والأطباق والأسعار"),
    ("menu_toggle_availability", "تفعيل أو إيقاف توفر الطبق بالفرع (نفدت الكمية)"),
    ("menu_manage_items", "تعديل بيانات ومكونات وخيارات أطباق الفرع"),
    ("menu_change_price", "تعديل أسعار الوجبات والأطباق في الفرع"),

    # 6. Branch Inventory (Branch Scope)
    ("inventory_view", "استعراض كميات المخزون والمواد الأولية بالفرع"),
    ("inventory_adjust_stock", "جرد وتسوية كميات المخزون يدوياً بالفرع"),
    ("inventory_add_stock", "تسجيل فواتير الشراء وتوريد مواد جديدة لمستودع الفرع"),
    ("inventory_record_waste", "تسجيل هدر وتالف المواد الغذائية بمطبخ الفرع"),

    # 7. HQ Orders (HQ Scope)
    ("hq_view_orders", "استعراض سجل طلبات وفواتير كافة فروع السلسلة (HQ)"),
    ("hq_edit_orders", "تعديل الطلبات المركزية وتوجيهها"),
    ("hq_cancel_orders", "إلغاء الطلبات المركزية عبر كافة الفروع"),
    ("hq_delete_orders", "حذف الفواتير نهائياً من قاعدة البيانات للإدارة العامة"),

    # 8. Central Call Center (HQ Scope)
    ("call_center_access", "الوصول لشاشة الكول سنتر واستقبال المكالمات الحية"),
    ("call_center_create_order", "تسجيل طلبات هاتفية للعملاء وتوجيهها للفروع"),
    ("call_center_view_customers", "استعراض وإدارة قاعدة بيانات وسجل العملاء"),

    # Legacy Compatibility (Synonyms kept so existing data & tests remain valid)
    ("pos_create_order", "تسجيل وإنشاء طلب جديد (توافقي)"),
    ("view_orders", "استعراض سجل الطلبات والفواتير (شامل)"),
    ("edit_orders", "تعديل تفاصيل الطلبات القائمة (شامل)"),
    ("cancel_orders", "إلغاء الطلبات المسجلة (شامل)"),
    ("delete_orders", "حذف الطلبات نهائياً من قاعدة البيانات (شامل)"),
    ("manage_menu", "إدارة المنيو وتوفر الأصناف بالكامل"),
    ("manage_inventory", "إدارة المستودعات والمخزون بالكامل"),
    ("kds_update_status", "تحديث حالة الوجبات في المطبخ"),
]


PERMISSIONS_CATALOG = [
    # === BRANCH SCOPE CATEGORIES ===
    {
        "category": "نقاط البيع والكاشير (POS)",
        "scope": "branch",
        "icon": "💳",
        "permissions": [
            {"key": "pos_access", "label": "شاشة الكاشير (POS)", "desc": "فتح واستخدام شاشة نقاط البيع وإصدار الفواتير وتسجيل الطلبات"},
            {"key": "pos_apply_discount", "label": "تطبيق الخصومات والعروض", "desc": "تخفيض الفاتورة وتطبيق الكوبونات والعروض"},
            {"key": "pos_cancel_order", "label": "إلغاء الفواتير بالكاشير", "desc": "إلغاء الفواتير المسجلة مباشرة من شاشة نقاط البيع"},
            {"key": "pos_refund_order", "label": "استرجاع الفاتورة ورد المبلغ", "desc": "استرداد الأموال للعميل نقدية أو شبكة"},
            {"key": "pos_manage_shift", "label": "تقفيل الوردية ودرج النقدية", "desc": "إغلاق الوردية وإصدار تقرير Z-Report وفتح درج النقدية"},
            {"key": "pos_reprint_receipt", "label": "إعادة طباعة الفواتير", "desc": "طباعة نسخ مكررة من الإيصالات والفواتير السابقة"},
        ]
    },
    {
        "category": "المطبخ وإعداد الوجبات (KDS)",
        "scope": "branch",
        "icon": "🍳",
        "permissions": [
            {"key": "kds_access", "label": "شاشة المطبخ (KDS)", "desc": "متابعة أوامر الطبخ وتحديث حالة الوجبات (قيد الطهي / جاهز)"},
            {"key": "kds_recall_order", "label": "استرجاع طلب تم إتمامه", "desc": "إعادة الطلب لشاشة الطهي في حال إنجازه بالخطأ"},
            {"key": "kds_pause_item", "label": "تعليق إعداد صنف مؤقتاً", "desc": "إشعار الصالة بتأخير أو تعليق صنف محدد بالمطبخ"},
        ]
    },
    {
        "category": "التوصيل وأسطول المناديب",
        "scope": "branch",
        "icon": "🛵",
        "permissions": [
            {"key": "delivery_access", "label": "شاشة متابعة وتوزيع التوصيل", "desc": "متابعة كباتن التوصيل والطلبات الجاهزة للنقل لحظياً"},
            {"key": "delivery_assign_driver", "label": "إسناد الطلبات للسائقين", "desc": "تعيين وتوزيع الطلبات على السائقين المتاحين بالفرع"},
            {"key": "delivery_override_status", "label": "تأكيد التسليم اليدوي", "desc": "تحديث حالة التوصيل يدوياً ومعالجة تعذر التسليم"},
            {"key": "delivery_track_drivers", "label": "تتبع مسارات السائقين", "desc": "متابعة مسارات الكباتن الحية على الخريطة"},
        ]
    },
    {
        "category": "سجل طلبات الفرع (Branch Orders)",
        "scope": "branch",
        "icon": "📑",
        "permissions": [
            {"key": "branch_view_orders", "label": "استعراض سجل طلبات الفرع", "desc": "رؤية وبحث وتصفية كافة فواتير وطلبات الفرع الحالي"},
            {"key": "branch_edit_orders", "label": "تعديل تفاصيل الطلبات القائمة", "desc": "تعديل أصناف وملاحظات وحالة الطلبات بالفرع"},
            {"key": "branch_cancel_orders", "label": "إلغاء طلبات الفرع", "desc": "إلغاء فواتير وطلبات الفرع المعتمدة"},
            {"key": "branch_delete_orders", "label": "حذف فواتير الفرع نهائياً (حساس)", "desc": "حذف سجل الفاتورة بالكامل من قاعدة البيانات"},
        ]
    },
    {
        "category": "قائمة طعام الفرع والأسعار (Branch Menu)",
        "scope": "branch",
        "icon": "📋",
        "permissions": [
            {"key": "menu_view", "label": "استعراض قائمة الطعام", "desc": "الاطلاع على الأصناف والتصنيفات والأسعار المعتمدة"},
            {"key": "menu_toggle_availability", "label": "توفر الأصناف بالفرع", "desc": "إيقاف أو تفعيل توفر الصنف بمطبخ الفرع (نفدت الكمية)"},
            {"key": "menu_manage_items", "label": "تعديل بيانات ومكونات الأطباق", "desc": "تعديل صور ومكونات وإضافات وخيارات الأطباق بالفرع"},
            {"key": "menu_change_price", "label": "تعديل أسعار الأطباق بالفرع", "desc": "تغيير وتخصيص أسعار الوجبات الخاصة بالفرع"},
        ]
    },
    {
        "category": "جرد ومخزون الفرع (Branch Inventory)",
        "scope": "branch",
        "icon": "📦",
        "permissions": [
            {"key": "inventory_view", "label": "استعراض كميات المخزون", "desc": "رؤية أرصدة المواد الأولية ونواقص مستودع الفرع"},
            {"key": "inventory_adjust_stock", "label": "جرد وتسوية المخزون", "desc": "تسجيل الجرد الفعلي ومطابقة وتعديل الكميات"},
            {"key": "inventory_add_stock", "label": "تسجيل توريد وشراء بضاعة", "desc": "إدخال فواتير الشراء وتوريد مواد جديدة للمستودع"},
            {"key": "inventory_record_waste", "label": "تسجيل الهدر والتالف", "desc": "حصر وتسجيل المواد الغذائية التالفة بمطبخ الفرع"},
        ]
    },

    # === HQ SCOPE CATEGORIES ===
    {
        "category": "سجل كافة طلبات السلسلة (HQ Orders)",
        "scope": "hq",
        "icon": "🏢",
        "permissions": [
            {"key": "hq_view_orders", "label": "استعراض طلبات كافة الفروع (HQ)", "desc": "استعراض وبحث وتصفية طلبات كل فروع السلسلة مجمعة"},
            {"key": "hq_edit_orders", "label": "تعديل الطلبات المركزية", "desc": "تعديل وتوجيه الطلبات عبر فروع السلسلة"},
            {"key": "hq_cancel_orders", "label": "إلغاء الطلبات المركزية", "desc": "إلغاء أي فاتورة عبر أي فرع من الإدارة العامة"},
            {"key": "hq_delete_orders", "label": "حذف الفواتير نهائياً (حساس جداً)", "desc": "حذف الفواتير نهائياً من قاعدة البيانات للإدارة العامة"},
        ]
    },
    {
        "category": "مركز الاتصالات المباشرة (Central Call Center)",
        "scope": "hq",
        "icon": "🎧",
        "permissions": [
            {"key": "call_center_access", "label": "شاشة الكول سنتر المباشرة", "desc": "استقبال وإجراء المكالمات الهاتفية الحية للعملاء"},
            {"key": "call_center_create_order", "label": "تسجيل وتوجيه طلبات الهاتف", "desc": "إنشاء طلب هاتفي وتوجيهه آلياً للفرع الأنسب للعميل"},
            {"key": "call_center_view_customers", "label": "بيانات وسجل العملاء", "desc": "استعراض سجل طلبات العملاء وعناوينهم السابقة"},
        ]
    },
]

BRANCH_PERMISSIONS = {
    "pos_access", "pos_apply_discount", "pos_cancel_order", "pos_refund_order", "pos_manage_shift", "pos_reprint_receipt",
    "kds_access", "kds_recall_order", "kds_pause_item",
    "delivery_access", "delivery_assign_driver", "delivery_override_status", "delivery_track_drivers",
    "branch_view_orders", "branch_edit_orders", "branch_cancel_orders", "branch_delete_orders",
    "menu_view", "menu_toggle_availability", "menu_manage_items", "menu_change_price",
    "inventory_view", "inventory_adjust_stock", "inventory_add_stock", "inventory_record_waste",
    "pos_create_order", "view_orders", "edit_orders", "cancel_orders", "delete_orders", "manage_menu", "manage_inventory", "kds_update_status",
}

HQ_PERMISSIONS = {
    "hq_view_orders", "hq_edit_orders", "hq_cancel_orders", "hq_delete_orders",
    "call_center_access", "call_center_create_order", "call_center_view_customers",
    "view_orders", "edit_orders", "cancel_orders", "delete_orders",
}


PRESET_ROLES_CONFIG = [
    {
        "name": "مدير عام / إدارة عليا",
        "scope": "hq",
        "description": "متابعة وإشراف على فروع السلسلة وسجل الطلبات المركزية والكول سنتر",
        "is_system": True,
        "permissions": [
            "hq_view_orders", "hq_edit_orders", "hq_cancel_orders", "hq_delete_orders",
            "call_center_access", "call_center_create_order", "call_center_view_customers",
            "view_orders", "edit_orders", "cancel_orders", "delete_orders",
        ],
    },
    {
        "name": "مدير فرع",
        "scope": "branch",
        "description": "إدارة كامل العمليات التشغيلية للفرع (كاشير، مطبخ، توصيل، فواتير، منيو، ومخزون)",
        "is_system": True,
        "permissions": [
            "pos_access", "pos_apply_discount", "pos_cancel_order", "pos_refund_order", "pos_manage_shift", "pos_reprint_receipt",
            "kds_access", "kds_recall_order", "kds_pause_item",
            "delivery_access", "delivery_assign_driver", "delivery_override_status", "delivery_track_drivers",
            "branch_view_orders", "branch_edit_orders", "branch_cancel_orders", "branch_delete_orders",
            "menu_view", "menu_toggle_availability", "menu_manage_items", "menu_change_price",
            "inventory_view", "inventory_adjust_stock", "inventory_add_stock", "inventory_record_waste",
            "view_orders", "edit_orders", "cancel_orders", "pos_create_order",
        ],
    },
    {
        "name": "كاشير رئيسي",
        "scope": "branch",
        "description": "مسؤول الوردية، تسجيل ومتابعة الطلبات، تطبيق الخصومات المصرحة، وإلغاء الفواتير الخاطئة",
        "is_system": True,
        "permissions": [
            "pos_access", "pos_apply_discount", "pos_cancel_order", "pos_refund_order", "pos_manage_shift", "pos_reprint_receipt",
            "branch_view_orders", "branch_cancel_orders",
            "menu_view",
            "view_orders", "cancel_orders", "pos_create_order",
        ],
    },
    {
        "name": "كاشير صالة",
        "scope": "branch",
        "description": "تسجيل طلبات الصالة والسفري وإصدار الإيصالات فقط بدون صلاحيات خصم أو إلغاء",
        "is_system": True,
        "permissions": [
            "pos_access", "pos_reprint_receipt", "branch_view_orders", "menu_view",
            "view_orders", "pos_create_order",
        ],
    },
    {
        "name": "طاهٍ رئيسي / مطبخ",
        "scope": "branch",
        "description": "شاشة المطبخ KDS، إعداد الوجبات، وتحديد توفر الأصناف في مطبخ الفرع",
        "is_system": True,
        "permissions": [
            "kds_access", "kds_recall_order", "kds_pause_item", "kds_update_status",
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
        "description": "استقبال اتصالات العملاء المركزية وتسجيل طلبات الهاتف وتوجيهها للفروع المناسبة",
        "is_system": True,
        "permissions": [
            "call_center_access", "call_center_create_order", "call_center_view_customers",
            "hq_view_orders", "view_orders",
        ],
    },
    {
        "name": "مشرف عمليات عامة / HQ",
        "scope": "hq",
        "description": "متابعة ومراقبة سجل كافة طلبات السلسلة عبر كل الفروع وتنسيق عمليات الكول سنتر",
        "is_system": True,
        "permissions": [
            "hq_view_orders", "hq_edit_orders", "hq_cancel_orders",
            "call_center_access", "call_center_create_order", "call_center_view_customers",
            "view_orders", "edit_orders", "cancel_orders",
        ],
    },
]


class JobRole(models.Model):
    SCOPE_CHOICES = [
        ("branch", "تشغيل فرع"),
        ("hq", "إدارة عامة (HQ)"),
    ]

    tenant = models.ForeignKey(
        'core.Tenant',
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
        app_label = 'core'
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
        'core.Tenant',
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
        'core.Branch',
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
        app_label = 'core'
        verbose_name = "موظف"
        verbose_name_plural = "الموظفون"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "employee_code"],
                condition=models.Q(employee_code__isnull=False) & ~models.Q(employee_code=""),
                name="unique_tenant_emp_code"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="idx_emp_tenant_status"),
        ]

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
        'core.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="user_profiles",
        verbose_name="المستأجر / المنشأة",
    )
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default="branch_manager", verbose_name="الدور والصلاحية")
    branch = models.ForeignKey(
        'core.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_profiles",
        verbose_name="الفرع المعين",
    )
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
        app_label = 'core'
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


class RestaurantOwnerManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(role="owner")


class RestaurantOwner(UserProfile):
    objects = RestaurantOwnerManager()

    class Meta:
        proxy = True
        app_label = 'core'
        verbose_name = "مالك منشأة / مطعم"
        verbose_name_plural = "قائمة الملاك (Restaurant Owners)"
