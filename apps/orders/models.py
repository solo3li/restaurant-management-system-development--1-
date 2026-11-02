from django.db import models
from django.utils import timezone


class Customer(models.Model):
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name="customers",
        null=True,
        blank=True,
        verbose_name="المستأجر / المنشأة",
    )
    name = models.CharField(max_length=255, verbose_name="اسم العميل")
    phone = models.CharField(max_length=50, db_index=True, verbose_name="رقم الهاتف")
    email = models.EmailField(max_length=254, blank=True, default="", verbose_name="البريد الإلكتروني")
    address = models.CharField(max_length=255, default="", blank=True, verbose_name="العنوان")
    notes = models.TextField(default="", blank=True, verbose_name="ملاحظات")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التسجيل")

    class Meta:
        app_label = 'core'
        verbose_name = "عميل"
        verbose_name_plural = "العملاء"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "phone"],
                condition=~models.Q(phone=""),
                name="unique_tenant_customer_phone",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "phone"], name="idx_cust_t_phone"),
        ]

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
        ("qr_menu", "المنيو الرقمي (QR)"),
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
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name="orders",
        null=True,
        blank=True,
        verbose_name="المستأجر / المنشأة",
    )
    order_number = models.CharField(max_length=50, db_index=True, verbose_name="رقم الطلب")
    order_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="dine_in", verbose_name="نوع الطلب")
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default="cashier", verbose_name="القناة")
    branch = models.ForeignKey(
        'core.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        verbose_name="الفرع",
    )
    delivery_area = models.ForeignKey(
        'core.DeliveryArea',
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
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, verbose_name="نسبة الضريبة المطبقة (%)")
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="مبلغ الضريبة")
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="الإجمالي")
    currency = models.CharField(max_length=10, default="SAR", verbose_name="عملة الطلب")
    currency_symbol = models.CharField(max_length=10, default="ر.س", blank=True, verbose_name="رمز عملة الطلب")
    cashier = models.CharField(max_length=255, default="", blank=True, verbose_name="الكاشير")
    driver = models.ForeignKey(
        'core.Employee',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_orders",
        verbose_name="السائق",
    )
    notes = models.TextField(default="", blank=True, verbose_name="ملاحظات")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="تاريخ ووقت الطلب")

    def save(self, *args, **kwargs):
        if not self.pk:
            if self.branch and getattr(self.branch, "currency", None):
                if not self.currency or (self.currency == "SAR" and self.branch.currency != "SAR"):
                    self.currency = self.branch.currency
                if not self.currency_symbol or (self.currency_symbol == "ر.س" and self.branch.currency != "SAR"):
                    self.currency_symbol = self.branch.get_currency_symbol_ar()
            elif self.tenant and getattr(self.tenant, "default_currency", None):
                if not self.currency:
                    self.currency = self.tenant.default_currency
                if not self.currency_symbol:
                    self.currency_symbol = self.tenant.get_currency_symbol_ar()
        if not self.currency:
            self.currency = "SAR"
        if not self.currency_symbol:
            self.currency_symbol = "ر.س"
        super().save(*args, **kwargs)

    class Meta:
        app_label = 'core'
        verbose_name = "طلب"
        verbose_name_plural = "الطلبات"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "order_number"], name="unique_tenant_order_number"),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "-created_at"], name="idx_ord_t_stat_dt"),
            models.Index(fields=["tenant", "-created_at"], name="idx_ord_t_dt"),
            models.Index(fields=["tenant", "branch", "-created_at"], name="idx_ord_t_br_dt"),
        ]

    def get_currency_symbol(self, lang=None):
        from django.utils import translation
        from core.currencies import get_currency_info
        active_lang = lang or translation.get_language() or "ar"
        if "-" in active_lang:
            active_lang = active_lang.split("-")[0]
        curr_code = getattr(self, "currency", None)
        if not curr_code:
            branch = getattr(self, "branch", None)
            if branch and getattr(branch, "currency", None):
                curr_code = branch.currency
            elif getattr(self, "tenant", None) and getattr(self.tenant, "default_currency", None):
                curr_code = self.tenant.default_currency
            else:
                curr_code = "SAR"
        info = get_currency_info(curr_code)
        if active_lang == "ar":
            return info.get("symbol_ar", "ر.س")
        return info.get("symbol_en", curr_code)

    def display_currency_symbol_for_lang(self, lang=None):
        return self.get_currency_symbol(lang)

    @property
    def display_currency_symbol(self):
        """
        Returns safe, guaranteed localized currency symbol for order display without template lookup errors.
        """
        return self.get_currency_symbol()

    def display_order_type(self, lang=None):
        from django.utils import translation
        from core.i18n_catalog import get_translation
        active_lang = lang or translation.get_language() or "ar"
        if "-" in active_lang:
            active_lang = active_lang.split("-")[0]
        return get_translation(self.get_order_type_display(), active_lang)

    def display_status(self, lang=None):
        from django.utils import translation
        from core.i18n_catalog import get_translation
        active_lang = lang or translation.get_language() or "ar"
        if "-" in active_lang:
            active_lang = active_lang.split("-")[0]
        return get_translation(self.get_status_display(), active_lang)

    def display_payment_method(self, lang=None):
        from django.utils import translation
        from core.i18n_catalog import get_translation
        active_lang = lang or translation.get_language() or "ar"
        if "-" in active_lang:
            active_lang = active_lang.split("-")[0]
        return get_translation(self.get_pay_method_display(), active_lang)

    def display_channel(self, lang=None):
        from django.utils import translation
        from core.i18n_catalog import get_translation
        active_lang = lang or translation.get_language() or "ar"
        if "-" in active_lang:
            active_lang = active_lang.split("-")[0]
        return get_translation(self.get_channel_display(), active_lang)

    @property
    def short_order_number(self):
        """
        Returns short sequence display (e.g. #0001) for unified order numbers
        like ORD-20261101-B5-0001. Falls back cleanly for legacy orders.
        """
        num = str(self.order_number or "").strip()
        if not num:
            return ""
        if num.startswith("#"):
            num = num.lstrip("#")
            if not num:
                return ""
        if "-" in num:
            parts = num.split("-")
            last_part = parts[-1]
            if last_part.isdigit():
                return f"#{last_part}"
        return f"#{num}"

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
        'core.MenuItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="صنف المنيو",
    )
    variant = models.ForeignKey(
        'core.MenuItemVariant',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
        verbose_name="الحجم المختار",
    )
    variant_name = models.CharField(max_length=100, blank=True, default="", verbose_name="اسم الحجم")
    name = models.CharField(max_length=255, verbose_name="اسم الصنف")
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="سعر الوحدة")
    qty = models.PositiveIntegerField(default=1, verbose_name="الكمية")
    notes = models.CharField(max_length=255, blank=True, default="", verbose_name="ملاحظات الصنف")

    class Meta:
        app_label = 'core'
        verbose_name = "عنصر طلب"
        verbose_name_plural = "عناصر الطلبات"

    @property
    def line_total(self):
        return self.price * self.qty

    def __str__(self):
        return f"{self.name} x {self.qty}"
