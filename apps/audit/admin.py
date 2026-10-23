from django.contrib import admin
from .models import AuditLog, KnowledgeDocument


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "tenant", "user", "target_model", "target_id", "ip_address")
    list_filter = ("action", "tenant", "target_model", "created_at")
    search_fields = ("action", "target_model", "description", "target_id")
    readonly_fields = ("created_at",)


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "tenant", "source_type", "file_type", "file_size", "created_at")
    list_filter = ("source_type", "tenant", "file_type")
    search_fields = ("title", "tenant__name")
