from django.db import models


class MenuCategory(models.Model):
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name="menu_categories",
        verbose_name="المستأجر / المنشأة",
    )
    name = models.CharField(max_length=100, verbose_name="اسم التصنيف")
    name_en = models.CharField(max_length=100, default="", blank=True, verbose_name="اسم التصنيف (إنجليزي)")
    description = models.TextField(blank=True, default="", verbose_name="وصف التصنيف")
    description_en = models.TextField(blank=True, default="", verbose_name="وصف التصنيف (إنجليزي)")
    image = models.FileField(upload_to="category_images/", blank=True, null=True, verbose_name="صورة القسم")
    ordering = models.IntegerField(default=10, verbose_name="ترتيب العرض")
    is_active = models.BooleanField(default=True, verbose_name="نشط")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخر تحديث")

    class Meta:
        app_label = 'core'
        verbose_name = "تصنيف قائمة الطعام"
        verbose_name_plural = "تصنيفات قائمة الطعام"
        unique_together = ("tenant", "name")
        ordering = ["ordering", "id"]

    def __str__(self):
        return f"{self.name} ({self.tenant.name if self.tenant else 'عام'})"

    def get_display_name(self, lang="ar"):
        if lang == "en" and self.name_en:
            return self.name_en
        return self.name

    def get_display_description(self, lang="ar"):
        if lang == "en" and self.description_en:
            return self.description_en
        return self.description


class MenuItem(models.Model):
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name="menu_items",
        null=True,
        blank=True,
        verbose_name="المستأجر / المنشأة",
    )
    name = models.CharField(max_length=255, verbose_name="اسم الصنف")
    name_en = models.CharField(max_length=255, default="", blank=True, verbose_name="اسم الصنف (إنجليزي)")
    description = models.TextField(default="", blank=True, verbose_name="وصف الطبق والمكونات")
    description_en = models.TextField(default="", blank=True, verbose_name="وصف الطبق (إنجليزي)")
    category = models.CharField(max_length=100, verbose_name="الفئة")
    category_rel = models.ForeignKey(
        MenuCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items",
        verbose_name="التصنيف المترابط",
    )
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="سعر البيع")
    cost = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="التكلفة")
    emoji = models.CharField(max_length=20, default="", blank=True, verbose_name="أيقونة")
    image = models.FileField(upload_to="menu_items/", blank=True, null=True, verbose_name="صورة الصنف")
    available = models.BooleanField(default=True, verbose_name="متوفر")
    has_variants = models.BooleanField(default=False, verbose_name="يحتوي على أحجام متعددة")
    is_active = models.BooleanField(default=True, verbose_name="مفعل وغير مؤرشف")

    class Meta:
        app_label = 'core'
        verbose_name = "صنف منيو"
        verbose_name_plural = "قائمة الطعام"
        ordering = ["id"]

    def __str__(self):
        return self.name

    def get_display_name(self, lang="ar"):
        if lang == "en" and self.name_en:
            return self.name_en
        return self.name

    def get_display_description(self, lang="ar"):
        if lang == "en" and self.description_en:
            return self.description_en
        return self.description

    @property
    def min_price(self):
        if self.has_variants and self.variants.exists():
            return self.variants.order_by("price").first().price
        return self.price

    def get_price_for_branch(self, branch):
        if not branch:
            return self.price
        b_avail = self.branch_availabilities.filter(branch=branch).first()
        if b_avail and b_avail.custom_price is not None:
            return b_avail.custom_price
        return self.price

    def get_min_price_for_branch(self, branch):
        if not branch or not self.has_variants:
            return self.get_price_for_branch(branch)
        variants = list(self.variants.all())
        if not variants:
            return self.get_price_for_branch(branch)
        prices = [v.get_price_for_branch(branch) for v in variants]
        return min(prices) if prices else self.get_price_for_branch(branch)


class MenuItemVariant(models.Model):
    menu_item = models.ForeignKey(
        MenuItem,
        on_delete=models.CASCADE,
        related_name="variants",
        verbose_name="صنف المنيو",
    )
    name = models.CharField(max_length=100, verbose_name="اسم الحجم / الخيار")
    name_en = models.CharField(max_length=100, default="", blank=True, verbose_name="اسم الحجم (إنجليزي)")
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="سعر الحجم")
    cost = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="التكلفة")
    is_default = models.BooleanField(default=False, verbose_name="الحجم الافتراضي")
    ordering = models.IntegerField(default=10, verbose_name="ترتيب العرض")

    class Meta:
        app_label = 'core'
        verbose_name = "حجم / خيار الصنف"
        verbose_name_plural = "أحجام وخيارات الأصناف"
        ordering = ["ordering", "id"]

    def __str__(self):
        return f"{self.menu_item.name} - {self.name} ({self.price} {self.menu_item.tenant.get_currency_symbol_ar() if self.menu_item and self.menu_item.tenant else 'ر.س'})"

    def get_display_name(self, lang="ar"):
        if lang == "en" and self.name_en:
            return self.name_en
        return self.name

    def get_price_for_branch(self, branch):
        if not branch:
            return self.price
        b_vp = self.branch_prices.filter(branch=branch).first()
        if b_vp and b_vp.custom_price is not None:
            return b_vp.custom_price
        return self.price


class BranchMenuAvailability(models.Model):
    branch = models.ForeignKey('core.Branch', on_delete=models.CASCADE, related_name="branch_menus", verbose_name="الفرع")
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name="branch_availabilities", verbose_name="صنف المنيو")
    is_available = models.BooleanField(default=True, verbose_name="متوفر في هذا الفرع")
    custom_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="سعر مخصص للفرع")

    class Meta:
        app_label = 'core'
        verbose_name = "توفر وتسعير الصنف بالفرع"
        verbose_name_plural = "توفر وتسعير الأصناف بالفروع"
        unique_together = ("branch", "menu_item")

    def __str__(self):
        status = "متوفر" if self.is_available else "غير متوفر"
        price_str = f" ({self.custom_price})" if self.custom_price is not None else ""
        return f"{self.menu_item.name} ({self.branch.name}) - {status}{price_str}"


class BranchVariantPrice(models.Model):
    branch = models.ForeignKey('core.Branch', on_delete=models.CASCADE, related_name="branch_variant_prices", verbose_name="الفرع")
    variant = models.ForeignKey(MenuItemVariant, on_delete=models.CASCADE, related_name="branch_prices", verbose_name="حجم الصنف")
    custom_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="سعر الحجم المخصص للفرع")
    is_available = models.BooleanField(default=True, verbose_name="متوفر في هذا الفرع")

    class Meta:
        app_label = 'core'
        verbose_name = "سعر حجم الصنف بالفرع"
        verbose_name_plural = "أسعار أحجام الأصناف بالفروع"
        unique_together = ("branch", "variant")

    def __str__(self):
        price_str = f"{self.custom_price}" if self.custom_price is not None else "افتراضي"
        return f"{self.variant.menu_item.name} - {self.variant.name} ({self.branch.name}) - {price_str}"
