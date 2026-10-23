from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import JobRole, Employee, UserProfile, RestaurantOwner


@admin.register(JobRole)
class JobRoleAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "scope", "is_system", "permissions_count", "employees_count", "created_at")
    list_filter = ("scope", "is_system", "tenant")
    search_fields = ("name", "description")

    @admin.display(description="عدد الصلاحيات")
    def permissions_count(self, obj):
        return len(obj.get_permissions_list())

    @admin.display(description="الموظفون المرتبطون")
    def employees_count(self, obj):
        return obj.employees.count()


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("name", "employee_code", "job_role", "tenant", "branch", "phone", "salary", "status")
    list_filter = ("tenant", "job_role", "role", "status", "branch")
    search_fields = ("name", "employee_code", "phone")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant", "job_role", "role", "branch", "is_platform_admin")
    list_filter = ("tenant", "job_role", "role", "is_platform_admin", "branch")
    search_fields = ("user__username", "user__email")


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
            return mark_safe('<span style="color: #7d6c59;">بدون باقة</span>')
        return format_html('<span style="color: #ac4a1a; font-weight: bold;">💎 {}</span>', obj.tenant.subscription_plan.name)

    @admin.display(description="حالة الاشتراك")
    def subscription_status(self, obj):
        if not obj.tenant:
            return "—"
        st = obj.tenant.subscription_status
        if st == "active":
            return mark_safe('<span style="color: #257a4e; font-weight: bold;">نشط ✓</span>')
        elif st == "trial":
            return mark_safe('<span style="color: #1f6e7e; font-weight: bold;">تجريبي</span>')
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
            return mark_safe('<span style="color: #257a4e;">فعال</span>')
        return mark_safe('<span style="color: #b53a2b;">معطل</span>')
