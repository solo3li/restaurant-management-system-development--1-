from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import TenantApiKey, PlatformVoiceAssistantConfig


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


@admin.register(PlatformVoiceAssistantConfig)
class PlatformVoiceAssistantConfigAdmin(admin.ModelAdmin):
    list_display = (
        "assistant_name",
        "is_active_badge",
        "voice_name",
        "language",
        "accent",
        "max_call_duration_seconds",
        "max_daily_calls_per_ip",
        "updated_at",
    )
    fieldsets = (
        ("الحالة وهوية المساعد (Identity & Activation)", {
            "fields": (
                "is_active",
                "landing_profile_id",
                "assistant_name",
                "welcome_message",
            ),
            "description": "تحديد هوية المساعد الصوتي ورسالته الترحيبية الأولى لزوار صفحة الهبوط العامة."
        }),
        ("قاعدة المعرفة والشخصية (Prompt Engineering & Brain)", {
            "fields": (
                "system_prompt",
            ),
            "description": "تعليمات الذكاء الاصطناعي ومعرفته بمنتجات المنصة وباقاتها وأسعارها للإجابة عن أسئلة الزوار."
        }),
        ("إعدادات الصوت والاتصال (Gemini Live & Telephony)", {
            "fields": (
                "partner_client_id",
                "voice_name",
                "language",
                "accent",
            ),
            "description": "الربط التقني مع مزود المكالمات السحابية ونبرة صوت Google Gemini Live واللهجة المعتمدة."
        }),
        ("حدود الاستهلاك وحماية التكاليف (Usage Quotas & Limits)", {
            "fields": (
                "max_call_duration_seconds",
                "max_daily_calls_per_ip",
            ),
            "description": "حماية رصيد المنصة من الاستنزاف عبر تحديد أقصى مدة للمكالمة الواحدة وأقصى عدد مكالمات لكل عنوان IP يومياً."
        }),
    )

    @admin.display(description="الحالة")
    def is_active_badge(self, obj):
        if obj.is_active:
            return mark_safe('<span style="color: #257a4e; font-weight: bold;">مفعل في صفحة الهبوط ✓</span>')
        return mark_safe('<span style="color: #b53a2b; font-weight: bold;">معطل ✕</span>')

    def has_add_permission(self, request):
        return not PlatformVoiceAssistantConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

