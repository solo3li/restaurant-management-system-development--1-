from django.db import models


class InventoryItem(models.Model):
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name="inventory_items",
        null=True,
        blank=True,
        verbose_name="المستأجر / المنشأة",
    )
    branch = models.ForeignKey(
        'core.Branch',
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
        app_label = 'core'
        verbose_name = "عنصر مخزون"
        verbose_name_plural = "المخزون"
        ordering = ["id"]

    def __str__(self):
        return f"{self.name} - {self.branch.name}"

    def display_name(self, lang=None):
        from django.utils import translation
        from core.i18n_catalog import get_translation
        active_lang = lang or translation.get_language() or "ar"
        if "-" in active_lang:
            active_lang = active_lang.split("-")[0]
        if active_lang == "ar":
            return self.name
        tr = get_translation(self.name, active_lang, default=None)
        if tr and tr != self.name:
            return tr
        return self.name

    def display_unit(self, lang=None):
        from django.utils import translation
        from core.i18n_catalog import get_translation
        active_lang = lang or translation.get_language() or "ar"
        if "-" in active_lang:
            active_lang = active_lang.split("-")[0]
        if active_lang == "ar":
            return self.unit
        tr = get_translation(self.unit, active_lang, default=None)
        if tr and tr != self.unit:
            return tr
        return self.unit
