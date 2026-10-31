from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils import timezone
from apps.support.models import SupportTicket, TicketMessage, TicketAttachment


class TicketAttachmentInline(admin.TabularInline):
    model = TicketAttachment
    extra = 0
    readonly_fields = ["file_type", "file_name", "formatted_size", "created_at", "file_preview"]
    fields = ["file", "file_type", "file_name", "formatted_size", "file_preview", "created_at"]

    def file_preview(self, obj):
        if not obj or not obj.file:
            return "-"
        if obj.file_type == "image":
            return format_html('<img src="{}" style="height:40px; border-radius:4px; border:1px solid #334155;" />', obj.file.url)
        elif obj.file_type == "audio":
            return format_html('<audio controls style="height:30px; max-width:200px;"><source src="{}"></audio>', obj.file.url)
        elif obj.file_type == "video":
            return format_html('<video controls style="height:40px; max-width:120px;"><source src="{}"></video>', obj.file.url)
        return format_html('<a href="{}" target="_blank">تحميل المستند</a>', obj.file.url)
    file_preview.short_description = "معاينة الملف"


class TicketMessageInline(admin.StackedInline):
    model = TicketMessage
    extra = 0
    readonly_fields = ["created_at"]
    fields = ["sender", "sender_type", "is_internal", "message", "created_at"]


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    change_form_template = "admin/core/supportticket/change_form.html"
    list_display = ["ticket_number", "tenant", "subject", "category", "priority_badge", "status_badge", "creator", "created_at"]
    list_filter = ["status", "priority", "category", "created_at"]
    search_fields = ["ticket_number", "subject", "description", "tenant__name"]
    readonly_fields = ["ticket_number", "created_at", "updated_at", "resolved_at", "closed_at"]
    inlines = [TicketMessageInline, TicketAttachmentInline]
    actions = ["action_mark_in_progress", "action_mark_resolved", "action_mark_closed", "action_reopen"]

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        extra_context = extra_context or {}
        if object_id:
            ticket = self.get_object(request, object_id)
            if ticket:
                extra_context["ticket_messages"] = (
                    ticket.messages.select_related("sender")
                    .prefetch_related("attachments")
                    .order_by("created_at")
                )
                extra_context["ticket_attachments"] = (
                    ticket.attachments.filter(message__isnull=True).order_by("created_at")
                )
                extra_context["ticket_obj"] = ticket
                extra_context["status_choices"] = SupportTicket.STATUS_CHOICES
        return super().changeform_view(request, object_id, form_url, extra_context=extra_context)

    fieldsets = (
        ("بيانات التذكرة الأساسية", {
            "fields": ("ticket_number", "tenant", "creator", "subject", "description")
        }),
        ("الحالة والتصنيف", {
            "fields": ("category", "priority", "status", "assigned_to")
        }),
        ("التواريخ ومؤشرات الإغلاق", {
            "fields": ("created_at", "updated_at", "resolved_at", "closed_at"),
            "classes": ("collapse",)
        }),
    )

    def priority_badge(self, obj):
        colors = {
            "urgent": "#ef4444",
            "high": "#f97316",
            "medium": "#eab308",
            "low": "#64748b",
        }
        color = colors.get(obj.priority, "#64748b")
        return format_html(
            '<span style="background:{}; color:#fff; padding:2px 8px; border-radius:6px; font-size:11px; font-weight:bold;">{}</span>',
            color,
            obj.get_priority_display()
        )
    priority_badge.short_description = "الأولوية"

    def status_badge(self, obj):
        colors = {
            "open": "#3b82f6",
            "in_progress": "#8b5cf6",
            "resolved": "#10b981",
            "closed": "#475569",
        }
        color = colors.get(obj.status, "#64748b")
        return format_html(
            '<span style="background:{}; color:#fff; padding:3px 10px; border-radius:6px; font-size:11px; font-weight:bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = "الحالة"

    @admin.action(description="تحويل إلى: قيد المعالجة (In Progress)")
    def action_mark_in_progress(self, request, queryset):
        queryset.update(status="in_progress")
        self.message_user(request, "تم تحديث حالة التذاكر إلى: قيد المعالجة.", level=messages.SUCCESS)

    @admin.action(description="تحويل إلى: تم الحل (Resolved)")
    def action_mark_resolved(self, request, queryset):
        queryset.update(status="resolved", resolved_at=timezone.now())
        self.message_user(request, "تم اعتماد حل التذاكر المختارة.", level=messages.SUCCESS)

    @admin.action(description="تحويل إلى: مغلقة (Closed)")
    def action_mark_closed(self, request, queryset):
        queryset.update(status="closed", closed_at=timezone.now())
        self.message_user(request, "تم إغلاق التذاكر المختارة نهائياً.", level=messages.SUCCESS)

    @admin.action(description="إعادة فتح التذكرة (Reopen)")
    def action_reopen(self, request, queryset):
        queryset.update(status="open")
        self.message_user(request, "تمت إعادة فتح التذاكر المختارة.", level=messages.SUCCESS)


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = ["ticket", "sender", "sender_type", "is_internal", "message_preview", "created_at"]
    list_filter = ["sender_type", "is_internal", "created_at"]
    search_fields = ["ticket__ticket_number", "sender__username", "message"]
    readonly_fields = ["created_at"]

    def message_preview(self, obj):
        return obj.message[:80] + "..." if len(obj.message) > 80 else obj.message
    message_preview.short_description = "مقتطف الرد"


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ["ticket", "file_name", "file_type", "formatted_size", "created_at"]
    list_filter = ["file_type", "created_at"]
    search_fields = ["ticket__ticket_number", "file_name"]
    readonly_fields = ["created_at", "formatted_size"]
