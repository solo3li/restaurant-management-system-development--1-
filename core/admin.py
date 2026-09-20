from datetime import timedelta
from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.urls import path, reverse
from django.shortcuts import redirect, get_object_or_404
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
    RestaurantOwner,
    TenantSubscription,
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
        "quick_actions",
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

    @admin.display(description="إجراءات سريعة")
    def quick_actions(self, obj):
        if obj.status == "pending":
            approve_url = reverse("admin:upgraderequest-approve", args=[obj.id])
            reject_url = reverse("admin:upgraderequest-reject", args=[obj.id])
            safe_tenant = obj.tenant.name.replace("'", "\\'")
            safe_plan = obj.requested_plan.name.replace("'", "\\'")
            return format_html(
                '<a href="{}" onclick="return confirm(\'هل أنت متأكد من الموافقة على ترقية منشأة «{}» إلى باقة «{}»؟\');" '
                'style="background-color: #257a4e; color: #ffffff; padding: 4px 9px; border-radius: 6px; font-weight: bold; '
                'text-decoration: none; font-size: 11px; margin-left: 5px; display: inline-block; box-shadow: 0 1px 2px rgba(0,0,0,0.15);">✓ موافقة وتفعيل</a>'
                '<a href="{}" onclick="return confirm(\'هل أنت متأكد من رفض طلب ترقية منشأة «{}»؟\');" '
                'style="background-color: #b53a2b; color: #ffffff; padding: 4px 9px; border-radius: 6px; font-weight: bold; '
                'text-decoration: none; font-size: 11px; display: inline-block; box-shadow: 0 1px 2px rgba(0,0,0,0.15);">✕ رفض</a>',
                approve_url, safe_tenant, safe_plan,
                reject_url, safe_tenant
            )
        elif obj.status == "approved":
            return format_html('<span style="color: #257a4e; font-weight: bold; font-size: 11px;">مفعل ومعتمد ✓</span>')
        return format_html('<span style="color: #b53a2b; font-weight: bold; font-size: 11px;">مرفوض ✕</span>')

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:req_id>/approve/",
                self.admin_site.admin_view(self.quick_approve_view),
                name="upgraderequest-approve",
            ),
            path(
                "<int:req_id>/reject/",
                self.admin_site.admin_view(self.quick_reject_view),
                name="upgraderequest-reject",
            ),
        ]
        return custom_urls + urls

    def quick_approve_view(self, request, req_id):
        req = get_object_or_404(UpgradeRequest, id=req_id)
        req.status = "approved"
        req.save()
        self.message_user(
            request,
            f"تمت الموافقة بنجاح على طلب ترقية منشأة «{req.tenant.name}» إلى «{req.requested_plan.name}» وتمديد الصلاحية."
        )
        return redirect("admin:core_upgraderequest_changelist")

    def quick_reject_view(self, request, req_id):
        req = get_object_or_404(UpgradeRequest, id=req_id)
        req.status = "rejected"
        req.save()
        self.message_user(
            request,
            f"تم تسجيل رفض طلب ترقية منشأة «{req.tenant.name}»."
        )
        return redirect("admin:core_upgraderequest_changelist")

    @admin.action(description="✓ الموافقة على طلبات الترقية المحددة وتفعيل الباقة فوراً")
    def approve_requests(self, request, queryset):
        approved_count = 0
        for req in queryset:
            if req.status != "approved":
                req.status = "approved"
                req.reviewed_at = timezone.now()
                req.save()
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


@admin.register(RestaurantOwner)
class RestaurantOwnerAdmin(admin.ModelAdmin):
    list_display = (
        "owner_name",
        "username",
        "tenant_display",
        "plan_display",
        "subscription_status",
        "branches_count",
        "contact_phone",
        "email",
        "date_joined",
        "is_active_badge",
    )
    list_filter = (
        "tenant__subscription_plan",
        "tenant__subscription_status",
        "user__is_active",
    )
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
        "tenant__name",
        "tenant__phone",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).filter(role="owner").select_related("user", "tenant", "tenant__subscription_plan")

    @admin.display(description="اسم المالك")
    def owner_name(self, obj):
        name = obj.user.get_full_name() or obj.user.username
        return format_html("👤 <strong>{}</strong>", name)

    @admin.display(description="اسم المستخدم")
    def username(self, obj):
        return obj.user.username

    @admin.display(description="المنشأة / المطعم")
    def tenant_display(self, obj):
        if not obj.tenant:
            return "—"
        return format_html("{} <strong>{}</strong>", obj.tenant.logo_emoji or "🍽️", obj.tenant.name)

    @admin.display(description="الباقة الحالية")
    def plan_display(self, obj):
        if not obj.tenant or not obj.tenant.subscription_plan:
            return format_html('<span style="color: #7d6c59;">بدون باقة</span>')
        return format_html('<span style="color: #ac4a1a; font-weight: bold;">💎 {}</span>', obj.tenant.subscription_plan.name)

    @admin.display(description="حالة الاشتراك")
    def subscription_status(self, obj):
        if not obj.tenant:
            return "—"
        st = obj.tenant.subscription_status
        if st == "active":
            return format_html('<span style="color: #257a4e; font-weight: bold;">نشط ✓</span>')
        elif st == "trial":
            return format_html('<span style="color: #1f6e7e; font-weight: bold;">تجريبي</span>')
        return format_html('<span style="color: #b53a2b; font-weight: bold;">{}</span>', obj.tenant.get_subscription_status_display())

    @admin.display(description="الفروع")
    def branches_count(self, obj):
        if not obj.tenant:
            return 0
        return obj.tenant.branches.count()

    @admin.display(description="الهاتف")
    def contact_phone(self, obj):
        if hasattr(obj.user, "employee_profile") and obj.user.employee_profile and obj.user.employee_profile.phone:
            return obj.user.employee_profile.phone
        if obj.tenant and obj.tenant.phone:
            return obj.tenant.phone
        return "—"

    @admin.display(description="البريد الإلكتروني")
    def email(self, obj):
        return obj.user.email or (obj.tenant.email if obj.tenant else "—")

    @admin.display(description="تاريخ التسجيل")
    def date_joined(self, obj):
        return obj.user.date_joined.strftime("%Y-%m-%d")

    @admin.display(description="الحساب")
    def is_active_badge(self, obj):
        if obj.user.is_active:
            return format_html('<span style="color: #257a4e;">فعال</span>')
        return format_html('<span style="color: #b53a2b;">معطل</span>')


@admin.register(TenantSubscription)
class TenantSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "tenant_name",
        "owner_name",
        "plan_badge",
        "status_badge",
        "billing_cycle_display",
        "expiry_date",
        "branches_usage",
        "employees_usage",
        "is_active_badge",
    )
    list_filter = (
        "subscription_status",
        "billing_cycle",
        "subscription_plan",
        "is_active",
    )
    search_fields = ("name", "slug", "phone", "email")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("subscription_plan")

    @admin.display(description="المنشأة المشتركة")
    def tenant_name(self, obj):
        return format_html("{} <strong>{}</strong>", obj.logo_emoji or "🍽️", obj.name)

    @admin.display(description="المالك")
    def owner_name(self, obj):
        owner_profile = obj.user_profiles.filter(role="owner").select_related("user").first()
        if owner_profile and owner_profile.user:
            return owner_profile.user.get_full_name() or owner_profile.user.username
        return "—"

    @admin.display(description="باقة الاشتراك")
    def plan_badge(self, obj):
        if not obj.subscription_plan:
            return format_html('<span style="color: #7d6c59;">بدون باقة</span>')
        return format_html('<span style="color: #ac4a1a; font-weight: bold;">💎 {}</span>', obj.subscription_plan.name)

    @admin.display(description="حالة الاشتراك")
    def status_badge(self, obj):
        if obj.subscription_status == "active":
            return format_html('<span style="color: #257a4e; font-weight: bold;">نشط ✓</span>')
        elif obj.subscription_status == "trial":
            return format_html('<span style="color: #1f6e7e; font-weight: bold;">فترة تجريبية</span>')
        elif obj.subscription_status == "past_due":
            return format_html('<span style="color: #a26a0d; font-weight: bold;">متأخر السداد ⏳</span>')
        return format_html('<span style="color: #b53a2b; font-weight: bold;">{}</span>', obj.get_subscription_status_display())

    @admin.display(description="دورة الفوترة")
    def billing_cycle_display(self, obj):
        return obj.get_billing_cycle_display()

    @admin.display(description="تاريخ الانتهاء")
    def expiry_date(self, obj):
        if not obj.subscription_end:
            return "مستمر"
        days = obj.days_until_expiry()
        color = "#b53a2b" if days < 7 else "#257a4e"
        return format_html('{} (<span style="color: {}; font-weight: bold;">{} يوم</span>)', obj.subscription_end.strftime("%Y-%m-%d"), color, days)

    @admin.display(description="استهلاك الفروع")
    def branches_usage(self, obj):
        count = obj.branches.count()
        limit = obj.subscription_plan.max_branches if obj.subscription_plan else 0
        limit_text = "∞" if (limit <= 0 or limit >= 999) else str(limit)
        color = "#b53a2b" if (limit > 0 and limit < 999 and count >= limit) else "#26190f"
        return format_html('<span style="color: {}; font-weight: bold;">{}</span> / {}', color, count, limit_text)

    @admin.display(description="استهلاك الموظفين")
    def employees_usage(self, obj):
        count = obj.employees.count()
        limit = obj.subscription_plan.max_employees if obj.subscription_plan else 0
        limit_text = "∞" if (limit <= 0 or limit >= 999) else str(limit)
        color = "#b53a2b" if (limit > 0 and limit < 999 and count >= limit) else "#26190f"
        return format_html('<span style="color: {}; font-weight: bold;">{}</span> / {}', color, count, limit_text)

    @admin.display(description="حالة المنشأة")
    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color: #257a4e;">نشطة</span>')
        return format_html('<span style="color: #b53a2b;">معطلة</span>')

