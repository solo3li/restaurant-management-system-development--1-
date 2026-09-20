from datetime import timedelta
from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from .models import (
    Tenant,
    Branch,
    Employee,
    MenuItem,
    InventoryItem,
    Customer,
    Order,
    OrderItem,
    UserProfile,
    BranchMenuAvailability,
    DeliveryArea,
    JobRole,
    SubscriptionPlan,
    UpgradeRequest,
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "price_monthly",
        "price_yearly",
        "max_branches_display",
        "max_employees_display",
        "is_active",
        "is_popular",
        "ordering",
        "tenants_count",
    )
    list_filter = ("is_active", "is_popular")
    search_fields = ("name", "code", "description")
    list_editable = ("price_monthly", "price_yearly", "is_active", "is_popular", "ordering")
    prepopulated_fields = {"code": ("name",)}
    fieldsets = (
        ("البيانات الأساسية", {
            "fields": ("name", "code", "description", "ordering", "is_active", "is_popular")
        }),
        ("التسعير وفترة التجربة", {
            "fields": ("price_monthly", "price_yearly", "trial_days")
        }),
        ("سعة المنشأة والحدود", {
            "fields": ("max_branches", "max_employees")
        }),
        ("الميزات والأنظمة المضمنة", {
            "fields": ("features",),
            "description": "قائمة المفاتيح للميزات المسموحة (pos, kds, menu_management, delivery_management, call_center, inventory, custom_roles, financial_analytics)"
        }),
    )

    @admin.display(description="الحد الأقصى للفروع")
    def max_branches_display(self, obj):
        if obj.max_branches >= 999 or obj.max_branches <= 0:
            return "غير محدود ∞"
        return f"{obj.max_branches} فروع"

    @admin.display(description="الحد الأقصى للموظفين")
    def max_employees_display(self, obj):
        if obj.max_employees >= 999 or obj.max_employees <= 0:
            return "غير محدود ∞"
        return f"{obj.max_employees} موظف"

    @admin.display(description="المنشآت المشتركة")
    def tenants_count(self, obj):
        count = obj.tenants.count()
        return format_html("<strong>{}</strong> منشأة", count)


@admin.register(UpgradeRequest)
class UpgradeRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "requested_plan",
        "billing_cycle_badge",
        "requested_by",
        "status_badge",
        "created_at",
        "reviewed_at",
    )
    list_filter = ("status", "billing_cycle", "requested_plan", "created_at")
    search_fields = ("tenant__name", "tenant__slug", "requested_by__username", "notes")
    readonly_fields = ("created_at", "reviewed_at")
    actions = ["approve_requests", "reject_requests"]

    @admin.display(description="دورة الفوترة")
    def billing_cycle_badge(self, obj):
        return obj.get_billing_cycle_display()

    @admin.display(description="حالة الطلب")
    def status_badge(self, obj):
        if obj.status == "approved":
            return format_html('<span style="color: #257a4e; font-weight: bold;">● تمت الموافقة ✓</span>')
        elif obj.status == "rejected":
            return format_html('<span style="color: #b53a2b; font-weight: bold;">✕ مرفوض</span>')
        return format_html('<span style="color: #a26a0d; font-weight: bold;">⏳ قيد المراجعة</span>')

    @admin.action(description="✓ الموافقة على طلبات الترقية المحددة وتفعيل الباقة فوراً")
    def approve_requests(self, request, queryset):
        approved_count = 0
        for req in queryset:
            if req.status != "approved":
                req.status = "approved"
                req.reviewed_at = timezone.now()
                req.save()

                tenant = req.tenant
                tenant.subscription_plan = req.requested_plan
                tenant.billing_cycle = req.billing_cycle
                tenant.subscription_status = "active"

                extension_days = 365 if req.billing_cycle == "yearly" else 30
                base_time = tenant.subscription_end if (tenant.subscription_end and tenant.subscription_end > timezone.now()) else timezone.now()
                tenant.subscription_end = base_time + timedelta(days=extension_days)
                tenant.save()
                approved_count += 1

        self.message_user(
            request,
            f"تمت الموافقة على {approved_count} طلب ترقية وتحديث وتفعيل اشتراكات المنشآت بنجاح."
        )

    @admin.action(description="✕ رفض طلبات الترقية المحددة")
    def reject_requests(self, request, queryset):
        rejected_count = 0
        for req in queryset:
            if req.status != "rejected":
                req.status = "rejected"
                req.reviewed_at = timezone.now()
                req.save()
                rejected_count += 1

        self.message_user(
            request,
            f"تم رفض {rejected_count} طلب ترقية."
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.status == "approved":
            self.message_user(
                request,
                f"تمت الموافقة وتحديث باقة منشأة «{obj.tenant.name}» إلى «{obj.requested_plan.name}» وتمديد الصلاحية بنجاح."
            )
        elif obj.status == "rejected":
            self.message_user(
                request,
                f"تم تسجيل رفض طلب ترقية منشأة «{obj.tenant.name}»."
            )


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "subscription_plan",
        "subscription_status_badge",
        "billing_cycle",
        "subscription_end",
        "is_active",
        "branches_count",
        "created_at",
    )
    list_filter = ("subscription_status", "billing_cycle", "subscription_plan", "is_active")
    search_fields = ("name", "slug", "phone", "email")
    prepopulated_fields = {"slug": ("name",)}

    fieldsets = (
        ("بيانات المنشأة الأساسية", {
            "fields": ("name", "slug", "logo_emoji", "phone", "email", "address", "is_active")
        }),
        ("الاشتراك والباقة", {
            "fields": ("subscription_plan", "subscription_status", "billing_cycle", "subscription_start", "subscription_end")
        }),
    )

    @admin.display(description="حالة الاشتراك")
    def subscription_status_badge(self, obj):
        if obj.subscription_status == "active":
            return format_html('<span style="color: #257a4e; font-weight: bold;">نشط ✓</span>')
        elif obj.subscription_status == "trial":
            return format_html('<span style="color: #1f6e7e; font-weight: bold;">تجريبي</span>')
        return format_html('<span style="color: #b53a2b; font-weight: bold;">{}</span>', obj.get_subscription_status_display())

    @admin.display(description="الفروع")
    def branches_count(self, obj):
        return obj.branches.count()


@admin.register(DeliveryArea)
class DeliveryAreaAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "area_type", "delivery_fee", "estimated_time_minutes", "is_active", "created_at")
    list_filter = ("branch__tenant", "branch", "area_type", "is_active")
    search_fields = ("name", "notes", "branch__name")


@admin.register(JobRole)
class JobRoleAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "scope", "is_system", "permissions_count", "employees_count", "created_at")
    list_filter = ("scope", "is_system", "tenant")
    search_fields = ("name", "description")

    @admin.display(description="عدد الصلاحيات")
    def permissions_count(self, obj):
        return len(obj.permissions)

    @admin.display(description="الموظفون المرتبطون")
    def employees_count(self, obj):
        return obj.employees.count()


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "city", "phone", "status", "created_at")
    list_filter = ("tenant", "status", "city")
    search_fields = ("name", "city", "phone")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("name", "employee_code", "job_role", "tenant", "branch", "phone", "salary", "status")
    list_filter = ("tenant", "job_role", "role", "status", "branch")
    search_fields = ("name", "employee_code", "phone")


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "category", "price", "cost", "available")
    list_filter = ("tenant", "category", "available")
    search_fields = ("name", "category")


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "branch", "quantity", "min_quantity", "unit", "supplier")
    list_filter = ("tenant", "branch", "unit")
    search_fields = ("name", "supplier")


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "phone", "address", "created_at")
    list_filter = ("tenant",)
    search_fields = ("name", "phone", "address")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "tenant", "order_type", "channel", "branch", "customer_name", "total", "status", "created_at")
    list_filter = ("tenant", "order_type", "channel", "status", "branch")
    search_fields = ("order_number", "customer_name", "customer_phone")
    inlines = [OrderItemInline]


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant", "job_role", "role", "branch", "is_platform_admin")
    list_filter = ("tenant", "job_role", "role", "is_platform_admin", "branch")
    search_fields = ("user__username", "user__email")


@admin.register(BranchMenuAvailability)
class BranchMenuAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("branch", "menu_item", "is_available")
    list_filter = ("branch__tenant", "branch", "is_available", "menu_item__category")
    search_fields = ("menu_item__name", "branch__name")
