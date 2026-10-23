from django.contrib import admin
from .models import MenuCategory, MenuItem, MenuItemVariant, BranchMenuAvailability, BranchVariantPrice


class MenuItemVariantInline(admin.TabularInline):
    model = MenuItemVariant
    extra = 1


@admin.register(MenuCategory)
class MenuCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "name_en", "tenant", "ordering", "is_active", "created_at")
    list_filter = ("tenant", "is_active")
    search_fields = ("name", "name_en")


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "category", "price", "cost", "available")
    list_filter = ("tenant", "category", "available")
    search_fields = ("name", "category")
    inlines = [MenuItemVariantInline]


@admin.register(BranchMenuAvailability)
class BranchMenuAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("branch", "menu_item", "is_available", "custom_price")
    list_filter = ("branch__tenant", "branch", "is_available", "menu_item__category")
    search_fields = ("menu_item__name", "branch__name")


@admin.register(BranchVariantPrice)
class BranchVariantPriceAdmin(admin.ModelAdmin):
    list_display = ("branch", "variant", "custom_price", "is_available")
    list_filter = ("branch__tenant", "branch", "is_available")
    search_fields = ("variant__name", "variant__menu_item__name", "branch__name")
