from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import TenantApiKey, PlatformVoiceAssistantConfig, LandingVoiceLead


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


@admin.register(LandingVoiceLead)
class LandingVoiceLeadAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "whatsapp_button",
        "full_phone",
        "country_code",
        "call_status_badge",
        "formatted_duration_display",
        "lead_status",
        "created_at",
    )
    list_editable = ("lead_status",)
    list_filter = (
        "lead_status",
        "call_status",
        "country_code",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = ("name", "phone", "full_phone", "ip_address", "call_id")
    readonly_fields = (
        "created_at",
        "updated_at",
        "whatsapp_link_display",
        "full_phone",
        "call_id",
        "ip_address",
        "formatted_duration_display",
    )
    list_per_page = 25
    date_hierarchy = "created_at"

    fieldsets = (
        ("بيانات الزائر والاتصال (Visitor & Contact Details)", {
            "fields": (
                "name",
                "phone",
                "country_code",
                "full_phone",
                "whatsapp_link_display",
            ),
            "description": "بيانات العميل المحتمل المستلمة من نافذة بدء المكالمة في صفحة الهبوط."
        }),
        ("حالة المكالمة الفنية (Technical Call Session)", {
            "fields": (
                "call_status",
                "duration_seconds",
                "formatted_duration_display",
                "call_id",
                "ip_address",
            ),
            "description": "تفاصيل جلسة WebRTC عبر خادم LiveKit ومزود الاتصالات."
        }),
        ("إدارة ومتابعة المبيعات (Sales Follow-up & Pipeline)", {
            "fields": (
                "lead_status",
                "notes",
            ),
            "description": "تحديث حالة تقدم العميل في مسار المبيعات وتدوين الملاحظات."
        }),
        ("التوقيتات (Timestamps)", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="محادثة واتساب")
    def whatsapp_button(self, obj):
        url = obj.whatsapp_url
        if not url:
            return mark_safe('<span style="color:#94a3b8;">—</span>')
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer" '
            'style="display:inline-flex;align-items:center;gap:4px;background:#10b981;color:#ffffff;'
            'padding:3px 9px;border-radius:6px;font-size:11px;font-weight:bold;text-decoration:none;'
            'box-shadow:0 1px 2px rgba(0,0,0,0.1);">'
            '<span>💬 واتساب</span>'
            '</a>',
            url
        )

    @admin.display(description="رابط واتساب المباشر")
    def whatsapp_link_display(self, obj):
        url = obj.whatsapp_url
        if not url:
            return mark_safe('<span style="color:#94a3b8;">لا يوجد رقم صالح</span>')
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer" '
            'style="display:inline-flex;align-items:center;gap:6px;background:#10b981;color:#ffffff;'
            'padding:6px 12px;border-radius:8px;font-size:12px;font-weight:bold;text-decoration:none;">'
            '<span>💬 بدء محادثة واتساب فورية ({})</span>'
            '</a>',
            url, obj.full_phone
        )

    @admin.display(description="حالة المكالمة")
    def call_status_badge(self, obj):
        color_map = {
            "completed": ("#059669", "#d1fae5", "مكتملة ✓"),
            "connected": ("#2563eb", "#dbeafe", "متصلة 🎧"),
            "initiated": ("#d97706", "#fef3c7", "قيد البدء ⏳"),
            "missed": ("#dc2626", "#fee2e2", "لم تكتمل ✕"),
            "failed": ("#991b1b", "#fee2e2", "فشلت ✕"),
        }
        color, bg, label = color_map.get(obj.call_status, ("#64748b", "#f1f5f9", obj.get_call_status_display()))
        return format_html(
            '<span style="display:inline-block;padding:2px 8px;border-radius:9999px;font-size:11px;font-weight:bold;'
            'color:{};background:{};border:1px solid {}40;">{}</span>',
            color, bg, color, label
        )

    @admin.display(description="مدة المكالمة")
    def formatted_duration_display(self, obj):
        mins = obj.duration_seconds // 60
        secs = obj.duration_seconds % 60
        duration_str = f"{mins:02d}:{secs:02d}"
        return format_html('<span style="font-family:monospace;font-weight:bold;color:#0f172a;">{}</span>', duration_str)


