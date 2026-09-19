from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User



class Branch(models.Model):
    STATUS_CHOICES = [
        ("active", "نشط"),
        ("closed", "مغلق"),
    ]

    name = models.CharField(max_length=255, verbose_name="اسم الفرع")
    city = models.CharField(max_length=100, default="", blank=True, verbose_name="المدينة")
    address = models.CharField(max_length=255, default="", blank=True, verbose_name="العنوان")
    phone = models.CharField(max_length=50, default="", blank=True, verbose_name="الهاتف")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active", verbose_name="الحالة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "فرع"
        verbose_name_plural = "الفروع"
        ordering = ["id"]

    def __str__(self):
        return self.name


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

    name = models.CharField(max_length=255, verbose_name="اسم الموظف")
    phone = models.CharField(max_length=50, default="", blank=True, verbose_name="الجوال")
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, verbose_name="المسمى الوظيفي")
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

    def __str__(self):
        return f"{self.name} ({self.get_role_display()})"


class MenuItem(models.Model):
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
        ("owner", "مالك / إدارة عامة"),
        ("branch_manager", "مدير فرع"),
        ("cashier", "كاشير"),
        ("chef", "طاهٍ / مطبخ"),
        ("driver", "سائق توصيل"),
        ("call_center", "خدمة عملاء"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile", verbose_name="المستخدم")
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default="branch_manager", verbose_name="الدور والصلاحية")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_profiles", verbose_name="الفرع المعين")

    class Meta:
        verbose_name = "ملف المستخدم"
        verbose_name_plural = "ملفات المستخدمين"

    def __str__(self):
        branch_str = f" - {self.branch.name}" if self.branch else ""
        return f"{self.user.username} ({self.get_role_display()}{branch_str})"


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


