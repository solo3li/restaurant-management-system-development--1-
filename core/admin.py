from django.contrib import admin
from .models import Branch, Employee, MenuItem, InventoryItem, Customer, Order, OrderItem, UserProfile, BranchMenuAvailability



@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "phone", "status", "created_at")
    list_filter = ("status", "city")
    search_fields = ("name", "city", "phone")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("name", "role", "branch", "phone", "salary", "status")
    list_filter = ("role", "status", "branch")
    search_fields = ("name", "phone")


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "cost", "available")
    list_filter = ("category", "available")
    search_fields = ("name", "category")


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "quantity", "min_quantity", "unit", "supplier")
    list_filter = ("branch", "unit")
    search_fields = ("name", "supplier")


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "address", "created_at")
    search_fields = ("name", "phone", "address")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "order_type", "channel", "branch", "customer_name", "total", "status", "created_at")
    list_filter = ("order_type", "channel", "status", "branch")
    search_fields = ("order_number", "customer_name", "customer_phone")
    inlines = [OrderItemInline]


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "branch")
    list_filter = ("role", "branch")
    search_fields = ("user__username", "user__email")


@admin.register(BranchMenuAvailability)
class BranchMenuAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("branch", "menu_item", "is_available")
    list_filter = ("branch", "is_available", "menu_item__category")
    search_fields = ("menu_item__name", "branch__name")



