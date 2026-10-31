import requests
from django.contrib import admin, messages
from django.urls import path, reverse
from django.shortcuts import redirect, render
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin

from apps.communication.models import BrevoConfiguration, EmailLog, InboundEmailLog, VerificationCode
from apps.communication.views import admin_send_direct_email_view
from apps.orders.models import Customer


@admin.register(BrevoConfiguration)
class BrevoConfigurationAdmin(admin.ModelAdmin):
    """
    لوحة تحكم إعدادات مزود البريد Brevo (Singleton):
    تتيح فحص الاتصال بمزود الخدمة والاطلاع على رصيد الرسائل وإرسال بريد مخصص.
    """
    list_display = ["sender_name", "sender_email", "is_active_badge", "total_sent_count", "updated_at"]
    readonly_fields = ["total_sent_count", "created_at", "updated_at", "api_status_inspect", "webhook_endpoint_info"]
    fieldsets = (
        ("بيانات الاعتماد والربط مع Brevo", {
            "fields": ("api_key", "is_active", "api_status_inspect"),
            "description": "أدخل مفتاح Brevo API المعتمد (xkeysib-...) لتفعيل الإرسال السحابي للرسائل المعاملاتية."
        }),
        ("هوية وبيانات المرسل الرسمية", {
            "fields": ("sender_name", "sender_email"),
            "description": "بيانات المرسل المعتمدة التي ستظهر لجميع العملاء في صندوق البريد الوارد."
        }),
        ("استقبال البريد الوارد والويب هوك (Inbound Webhook)", {
            "fields": ("inbound_domain", "webhook_secret", "webhook_endpoint_info"),
            "description": "إعدادات الربط مع Brevo Inbound Webhook لاستقبال وتفكيك ردود العملاء البريدية."
        }),
        ("إحصائيات الإرسال والنظام", {
            "fields": ("total_sent_count", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def has_add_permission(self, request):
        return not BrevoConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color:#10b981; font-weight:bold;">● مفعل</span>')
        return format_html('<span style="color:#ef4444; font-weight:bold;">● معطل</span>')
    is_active_badge.short_description = "الحالة"

    def api_status_inspect(self, obj):
        return format_html(
            '<div style="margin-top:6px;">'
            '<a href="{}" class="button" style="background:#8b5cf6; color:#fff; padding:6px 14px; border-radius:8px; text-decoration:none; font-weight:bold; margin-inline-end:8px;">'
            '⚡ فحص الاتصال مع Brevo'
            '</a>'
            '<a href="{}" class="button" style="background:#0ea5e9; color:#fff; padding:6px 14px; border-radius:8px; text-decoration:none; font-weight:bold;">'
            '✉️ إرسال بريد إلكتروني مخصص'
            '</a>'
            '</div>',
            reverse("admin:brevo_test_connection"),
            reverse("admin:admin_brevo_send_email")
        )
    api_status_inspect.short_description = "إجراءات وأدوات Brevo السريعة"


    def webhook_endpoint_info(self, obj):
        return mark_safe(
            '<div style="font-family:monospace; background:#0f172a; color:#a78bfa; padding:10px 14px; border-radius:8px; direction:ltr; text-align:left;">'
            'POST https://uggu.space/api/brevo/webhook/inbound/'
            '</div>'
            '<small style="color:#64748b; display:block; margin-top:4px;">قم بنسخ هذا الرابط وضبطه في لوحة Brevo > Transactional > Webhooks لاستقبال البريد الوارد تلقائياً.</small>'
        )
    webhook_endpoint_info.short_description = "رابط استقبال الويب هوك"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("test-connection/", self.admin_site.admin_view(self.test_connection_view), name="brevo_test_connection"),
            path("send-email/", self.admin_site.admin_view(admin_send_direct_email_view), name="admin_brevo_send_email"),
        ]
        return custom_urls + urls

    def test_connection_view(self, request):
        config = self.model.get_config()
        if not config.api_key:
            self.message_user(request, "لم يتم ضبط مفتاح Brevo API.", level=messages.ERROR)
            return redirect("admin:core_brevoconfiguration_change", config.pk)

        try:
            headers = {"accept": "application/json", "api-key": config.api_key}
            resp = requests.get("https://api.brevo.com/v3/account", headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                credits = "N/A"
                if "plan" in data and len(data["plan"]) > 0:
                    credits = data["plan"][0].get("credits", "Free")
                email = data.get("email", "")
                company = data.get("companyName", "")
                self.message_user(
                    request,
                    f"تم الاتصال بحساب Brevo بنجاح! الشركة: {company} | الحساب: {email} | الرصيد المتاح: {credits} رسالة.",
                    level=messages.SUCCESS
                )
            else:
                self.message_user(request, f"فشل فحص Brevo [HTTP {resp.status_code}]: {resp.text}", level=messages.ERROR)
        except Exception as ex:
            self.message_user(request, f"حدث خطأ أثناء الاتصال مع Brevo: {str(ex)}", level=messages.ERROR)

        return redirect("admin:core_brevoconfiguration_change", config.pk)


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ["recipient_email", "subject", "status_badge", "brevo_message_id", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["recipient_email", "subject", "brevo_message_id", "error_message"]
    readonly_fields = ["recipient_email", "recipient_name", "subject", "body_preview", "status", "brevo_message_id", "error_message", "created_at"]

    def has_add_permission(self, request):
        return False

    def status_badge(self, obj):
        colors = {
            "sent": "#10b981",
            "queued": "#f59e0b",
            "failed": "#ef4444",
        }
        color = colors.get(obj.status, "#64748b")
        return format_html(
            '<span style="background:{}; color:#fff; padding:3px 8px; border-radius:6px; font-size:11px; font-weight:bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = "الحالة"


@admin.register(InboundEmailLog)
class InboundEmailLogAdmin(admin.ModelAdmin):
    list_display = ["sender_email", "subject", "recipient_email", "ticket_badge", "is_processed_badge", "created_at"]
    list_filter = ["is_processed", "created_at"]
    search_fields = ["sender_email", "subject", "body_text", "message_id"]
    readonly_fields = ["message_id", "sender_email", "sender_name", "recipient_email", "subject", "body_text", "rendered_body_html", "ticket", "is_processed", "raw_payload", "headers", "created_at"]

    def has_add_permission(self, request):
        return False

    def ticket_badge(self, obj):
        if obj.ticket:
            return format_html(
                '<a href="{}" style="font-family:monospace; font-weight:bold; color:#8b5cf6;">{}</a>',
                reverse("admin:core_supportticket_change", args=[obj.ticket.pk]),
                obj.ticket.ticket_number
            )
        return format_html('<span style="color:#94a3b8;">غير مرتبط</span>')
    ticket_badge.short_description = "تذكرة الدعم"

    def is_processed_badge(self, obj):
        if obj.is_processed:
            return format_html('<span style="color:#10b981; font-weight:bold;">✔ تمت المعالجة</span>')
        return format_html('<span style="color:#f59e0b; font-weight:bold;">⏳ قيد الانتظار</span>')
    is_processed_badge.short_description = "المعالجة"

    def rendered_body_html(self, obj):
        if obj.body_html:
            return format_html(
                '<div style="background:#ffffff; color:#0f172a; padding:16px; border:1px solid #cbd5e1; border-radius:8px; max-height:400px; overflow-y:auto;">{}</div>',
                format_html(obj.body_html)
            )
        return format_html('<span style="color:#94a3b8;">لا يوجد محتوى HTML</span>')
    rendered_body_html.short_description = "معاينة HTML المستلمة"


@admin.register(VerificationCode)
class VerificationCodeAdmin(admin.ModelAdmin):
    list_display = ["email", "code", "purpose", "is_valid_badge", "expires_at", "is_used", "created_at"]
    list_filter = ["purpose", "is_used", "created_at"]
    search_fields = ["email", "code"]
    readonly_fields = ["user", "email", "code", "purpose", "expires_at", "is_used", "created_at"]

    def has_add_permission(self, request):
        return False

    def is_valid_badge(self, obj):
        if obj.is_valid:
            return format_html('<span style="background:#10b981; color:#fff; padding:2px 8px; border-radius:6px; font-weight:bold; font-size:11px;">نشط وصالح</span>')
        if obj.is_used:
            return format_html('<span style="background:#64748b; color:#fff; padding:2px 8px; border-radius:6px; font-size:11px;">مستخدم</span>')
        return format_html('<span style="background:#ef4444; color:#fff; padding:2px 8px; border-radius:6px; font-size:11px;">منتهي الصلاحية</span>')
    is_valid_badge.short_description = "الصلاحية"


# Add Admin action to User model for sending direct custom email via Brevo
@admin.action(description="✉️ إرسال بريد إلكتروني مخصص عبر Brevo")
def send_custom_brevo_email_to_users(modeladmin, request, queryset):
    emails = [u.email for u in queryset if u.email]
    if not emails:
        modeladmin.message_user(request, "المستخدمون المختارون ليس لديهم عناوين بريد إلكتروني صالحة.", level=messages.WARNING)
        return
    first_email = emails[0]
    return redirect(f"{reverse('admin:admin_brevo_send_email')}?email={first_email}")

try:
    admin.site._registry[User].actions.append(send_custom_brevo_email_to_users)
except Exception:
    pass

# Add Admin action to Customer model
@admin.action(description="✉️ إرسال بريد إلكتروني مخصص للعميل عبر Brevo")
def send_custom_brevo_email_to_customers(modeladmin, request, queryset):
    emails = [c.email for c in queryset if getattr(c, "email", None)]
    if not emails:
        modeladmin.message_user(request, "العملاء المختارون ليس لديهم عناوين بريد إلكتروني صالحة.", level=messages.WARNING)
        return
    first_email = emails[0]
    return redirect(f"{reverse('admin:admin_brevo_send_email')}?email={first_email}")


try:
    admin.site._registry[Customer].actions.append(send_custom_brevo_email_to_customers)
except Exception:
    pass
