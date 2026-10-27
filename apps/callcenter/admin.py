from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.urls import path
from .models import TenantApiKey, PlatformVoiceAssistantConfig, LandingVoiceLead, LandingKnowledgeDocument
from apps.callcenter import views as cc_views
from apps.callcenter.landing_assistant_service import (
    ensure_landing_sales_client,
    sync_landing_assistant_live_context,
    get_landing_assistant_redis_status,
)


@admin.register(LandingKnowledgeDocument)
class LandingKnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "source_type_badge",
        "file_type",
        "formatted_size",
        "partner_doc_id",
        "created_at",
    )
    list_filter = ("source_type", "file_type")
    search_fields = ("title", "content")
    readonly_fields = ("created_at", "updated_at", "partner_doc_id", "file_size")

    @admin.display(description="نوع المصدر")
    def source_type_badge(self, obj):
        if obj.source_type == "file":
            return mark_safe('<span style="color:#0284c7;font-weight:bold;">📄 مستند مرفوع</span>')
        return mark_safe('<span style="color:#10b981;font-weight:bold;">❓ سؤال وجواب (FAQ)</span>')

    @admin.display(description="حجم الملف")
    def formatted_size(self, obj):
        if not obj.file_size:
            return "—"
        if obj.file_size >= 1024 * 1024:
            return f"{obj.file_size / (1024*1024):.1f} MB"
        return f"{obj.file_size / 1024:.1f} KB"


@admin.register(PlatformVoiceAssistantConfig)
class PlatformVoiceAssistantConfigAdmin(admin.ModelAdmin):
    change_form_template = "admin/core/platformvoiceassistantconfig/change_form.html"
    readonly_fields = ("partner_client_id",)
    list_display = (
        "assistant_name",
        "is_active_badge",
        "partner_client_id_display",
        "voice_name",
        "language",
        "accent",
        "max_call_duration_seconds",
        "max_daily_calls_per_ip",
        "updated_at",
    )
    fieldsets = (
        ("هوية المساعد والشخصية (Identity & Brain)", {
            "fields": (
                "is_active",
                "landing_profile_id",
                "assistant_name",
                "system_prompt",
                "welcome_message",
            ),
            "description": "تحديد هوية المساعد الصوتي، توجيهات الشخصية والذكاء، والرسالة الترحيبية الأولى لزوار صفحة الهبوط."
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

    @admin.display(description="معرف العميل لدى مزود الاتصالات (Partner Client ID)")
    def partner_client_id(self, obj):
        cid = (obj.partner_client_id if obj else None) or "662"
        return format_html(
            '<div style="display:inline-flex;align-items:center;gap:10px;padding:6px 14px;background:#1e293b;border-radius:8px;border:1px solid #475569;">'
            '<span style="font-family:monospace;font-size:1.1rem;font-weight:bold;color:#38bdf8;">🔒 {}</span>'
            '<span class="badge" style="background:#0f766e;color:#ccfbf1;padding:5px 10px;border-radius:6px;font-size:0.8rem;font-weight:bold;">'
            '🔒 معرف نظامي معزول ومقفول'
            '</span>'
            '</div>'
            '<div class="help text-muted" style="margin-top:6px;font-size:0.8rem;">'
            'هذا المعرف معزول ومقفول ضد التعديل اليدوي، ومسؤول عنه حصراً زر [ 🔄 فحص وربط الحساب الآن ] بالأعلى للمزامنة التلقائية مع حساب Landing-Sales-Client (معرف 662).'
            '</div>',
            cid
        )

    @admin.display(description="معرف العميل")
    def partner_client_id_display(self, obj):
        cid = (obj.partner_client_id if obj else None) or "662"
        return format_html(
            '<span style="font-family:monospace;font-weight:bold;color:#0284c7;background:#0f172a;padding:2px 8px;border-radius:6px;">🔒 {}</span>',
            cid
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

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            # 1. Isolated Knowledge Documents
            extra_context["documents"] = obj.knowledge_documents.all().order_by("-created_at")
            # 2. Landing Leads & Voice Calls
            extra_context["leads"] = LandingVoiceLead.objects.all().order_by("-created_at")[:100]
            extra_context["total_leads_count"] = LandingVoiceLead.objects.count()
            extra_context["connected_calls_count"] = LandingVoiceLead.objects.filter(call_status__in=["connected", "completed"]).count()
            extra_context["converted_leads_count"] = LandingVoiceLead.objects.filter(lead_status="converted").count()
            extra_context["new_leads_count"] = LandingVoiceLead.objects.filter(lead_status="new").count()
            # 3. Redis Live Context
            extra_context["redis_status"] = get_landing_assistant_redis_status(obj)
            # 4. Partner Account Check
            extra_context["partner_client_info"] = ensure_landing_sales_client(obj)
            extra_context["lead_status_choices"] = LandingVoiceLead.LEAD_STATUS_CHOICES
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def save_model(self, request, obj, form, change):
        if change and obj.pk:
            orig = PlatformVoiceAssistantConfig.objects.filter(pk=obj.pk).values_list("partner_client_id", flat=True).first()
            if orig:
                obj.partner_client_id = orig
        elif not obj.partner_client_id:
            obj.partner_client_id = "662"
        super().save_model(request, obj, form, change)
        try:
            ensure_landing_sales_client(obj)
            sync_landing_assistant_live_context(obj)
        except Exception as e:
            pass

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("documents/list/", self.admin_site.admin_view(cc_views.api_landing_assistant_documents_list), name="core_platformvoiceassistantconfig_documents_list"),
            path("documents/add-faq/", self.admin_site.admin_view(cc_views.api_landing_assistant_add_faq), name="core_platformvoiceassistantconfig_documents_add_faq"),
            path("documents/upload/", self.admin_site.admin_view(cc_views.api_landing_assistant_upload_document), name="core_platformvoiceassistantconfig_documents_upload"),
            path("documents/<int:doc_id>/edit/", self.admin_site.admin_view(cc_views.api_landing_assistant_edit_document), name="core_platformvoiceassistantconfig_documents_edit"),
            path("documents/<int:doc_id>/delete/", self.admin_site.admin_view(cc_views.api_landing_assistant_delete_document), name="core_platformvoiceassistantconfig_documents_delete"),
            path("leads/<int:lead_id>/status/", self.admin_site.admin_view(cc_views.api_landing_assistant_lead_status), name="core_platformvoiceassistantconfig_lead_status"),
            path("redis/status/", self.admin_site.admin_view(cc_views.api_landing_assistant_redis_status), name="core_platformvoiceassistantconfig_redis_status"),
            path("redis/sync/", self.admin_site.admin_view(cc_views.api_landing_assistant_redis_sync), name="core_platformvoiceassistantconfig_redis_sync"),
            path("partner-client/ensure/", self.admin_site.admin_view(cc_views.api_landing_assistant_ensure_partner_client), name="core_platformvoiceassistantconfig_ensure_partner_client"),
        ]
        return custom_urls + urls


@admin.register(LandingVoiceLead)
class LandingVoiceLeadAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "whatsapp_button",
        "full_phone",
        "language_display",
        "dialect_display",
        "voice_display",
        "call_status_badge",
        "formatted_duration_display",
        "lead_status",
        "created_at",
    )
    list_editable = ("lead_status",)
    list_filter = (
        "lead_status",
        "call_status",
        "language",
        "dialect",
        "voice_name",
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
        "language_display",
        "dialect_display",
        "voice_display",
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
        ("التفضيلات الصوتية واللغوية (Voice & Language Preferences)", {
            "fields": (
                "language",
                "dialect",
                "voice_name",
            ),
            "description": "خيارات اللغة واللهجة ونبرة الصوت التي اختارها الزائر قبل بدء المكالمة."
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

    @admin.display(description="اللغة")
    def language_display(self, obj):
        if not obj or not getattr(obj, "language", None):
            return "—"
        flags = {
            "ar": "🇸🇦 العربية",
            "en": "🇬🇧 English",
            "fr": "🇫🇷 Français",
            "tr": "🇹🇷 Türkçe",
            "de": "🇩🇪 Deutsch",
        }
        val = flags.get(obj.language, obj.get_language_display() or obj.language)
        return format_html('<span style="font-weight:600;color:#f8fafc;">{}</span>', val)

    @admin.display(description="اللهجة")
    def dialect_display(self, obj):
        if not obj or not getattr(obj, "dialect", None):
            return "—"
        return format_html('<span style="font-weight:500;color:#93c5fd;">{}</span>', obj.get_dialect_display() or obj.dialect)

    @admin.display(description="بروفايل الصوت")
    def voice_display(self, obj):
        if not obj or not getattr(obj, "voice_name", None):
            return "—"
        voices = {
            "Aoede": "👩 سارة (Aoede)",
            "Puck": "👨 أحمد (Puck)",
            "Fenrir": "👨 عمر (Fenrir)",
            "Kore": "👩 مريم (Kore)",
            "Charon": "👨 خالد (Charon)",
        }
        val = voices.get(obj.voice_name, obj.voice_name)
        return format_html('<span style="font-weight:600;color:#a7f3d0;">{}</span>', val)

    @admin.display(description="محادثة واتساب")
    def whatsapp_button(self, obj):
        if not obj:
            return mark_safe('<span style="color:#94a3b8;">—</span>')
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
        if not obj:
            return mark_safe('<span style="color:#94a3b8;">—</span>')
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
        if not obj:
            return mark_safe('<span style="color:#94a3b8;">—</span>')
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
        if not obj or obj.duration_seconds is None:
            return mark_safe('<span style="font-family:monospace;font-weight:bold;color:#0f172a;">00:00</span>')
        mins = obj.duration_seconds // 60
        secs = obj.duration_seconds % 60
        duration_str = f"{mins:02d}:{secs:02d}"
        return format_html('<span style="font-family:monospace;font-weight:bold;color:#0f172a;">{}</span>', duration_str)


