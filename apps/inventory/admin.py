from django.contrib import admin
from .models import InventoryItem


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "branch", "quantity", "min_quantity", "unit", "supplier")
    list_filter = ("tenant", "branch", "unit")
    search_fields = ("name", "supplier")
