from django.contrib import admin
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
)


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "plan", "is_active", "phone", "created_at")
    list_filter = ("plan", "is_active")
    search_fields = ("name", "slug", "phone", "email")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "city", "phone", "status", "created_at")
    list_filter = ("tenant", "status", "city")
    search_fields = ("name", "city", "phone")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("name", "employee_code", "role", "tenant", "branch", "phone", "salary", "status")
    list_filter = ("tenant", "role", "status", "branch")
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
    list_display = ("user", "tenant", "role", "branch", "is_platform_admin")
    list_filter = ("tenant", "role", "is_platform_admin", "branch")
    search_fields = ("user__username", "user__email")


@admin.register(BranchMenuAvailability)
class BranchMenuAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("branch", "menu_item", "is_available")
    list_filter = ("branch__tenant", "branch", "is_available", "menu_item__category")
    search_fields = ("menu_item__name", "branch__name")
