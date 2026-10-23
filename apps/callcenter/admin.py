from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import TenantApiKey


@admin.register(TenantApiKey)
class TenantApiKeyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "tenant",
        "key_preview",
        "assigned_branch",
        "total_orders_placed",
        "last_used_at",
        "is_active_badge",
        "created_at",
    )
    list_filter = ("tenant", "is_active", "assigned_branch")
    search_fields = ("name", "key", "tenant__name")
    readonly_fields = ("created_at", "last_used_at", "total_orders_placed")

    @admin.display(description="مفتاح الدخول (Access Key)")
    def key_preview(self, obj):
        prefix = obj.key[:14]
        return format_html('<code style="background: #f4eee2; padding: 2px 6px; border-radius: 4px; font-weight: bold;">{}...</code>', prefix)

    @admin.display(description="الحالة")
    def is_active_badge(self, obj):
        if obj.is_active:
            return mark_safe('<span style="color: #257a4e; font-weight: bold;">مفعل ✓</span>')
        return mark_safe('<span style="color: #b53a2b; font-weight: bold;">معطل ✕</span>')
