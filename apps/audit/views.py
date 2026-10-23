from django.http import JsonResponse
from django.contrib.auth.decorators import login_required

from apps.tenants.helpers import get_active_tenant
from apps.accounts.helpers import user_has_perm
from apps.audit.models import AuditLog


@login_required
def api_audit_logs(request):
    """API endpoint to query sensitive system audit logs for tenant owners/administrators."""
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (
        user_has_perm(request.user, "system_view_audit_logs") or
        user_has_perm(request.user, "system_manage_roles") or
        user_has_perm(request.user, "manage_roles")
    ):
        return JsonResponse({"error": "غير مصرح لك باستعراض سجل التدقيق الأمني"}, status=403)

    logs = AuditLog.objects.filter(tenant=tenant).select_related("user")[:100]
    data = []
    for l in logs:
        user_display = "النظام"
        if l.user:
            user_display = l.user.get_full_name() or l.user.username
        data.append({
            "id": l.id,
            "action": l.action,
            "user": user_display,
            "targetModel": l.target_model,
            "targetId": l.target_id,
            "description": l.description,
            "ipAddress": l.ip_address,
            "createdAt": l.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        })
    return JsonResponse({"ok": True, "logs": data})
