from apps.tenants.models import Tenant, Branch
from apps.accounts.helpers import user_has_perm


def get_active_tenant(request):
    """Resolve the active tenant for the current request."""
    if hasattr(request, "tenant") and request.tenant:
        return request.tenant

    profile = getattr(request.user, "profile", None)
    if profile and profile.tenant:
        return profile.tenant

    emp = getattr(request.user, "employee_profile", None)
    if emp and emp.tenant:
        return emp.tenant

    # Platform admin / Superuser session override
    active_t_id = request.session.get("active_tenant_id") if hasattr(request, "session") else None
    if active_t_id:
        t = Tenant.objects.filter(id=active_t_id, is_active=True).first()
        if t:
            return t

    if hasattr(request, "user") and (request.user.is_superuser or (profile and profile.is_platform_admin)):
        return Tenant.objects.filter(is_active=True).first()

    return None


def get_active_branch(request):
    """Resolve active branch within the current tenant."""
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    emp = getattr(request.user, "employee_profile", None)
    is_owner = getattr(request.user, "is_superuser", False) or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    can_operate_cross = (
        is_owner
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "call_center_access")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )

    if not can_operate_cross:
        if profile and profile.branch:
            return profile.branch
        if emp and emp.branch:
            return emp.branch

    has_session = hasattr(request, "session")
    if has_session and "active_branch_id" in request.session:
        active_id = request.session.get("active_branch_id")
        if active_id in ["all", 0, "0", None]:
            return None
        qs = Branch.objects.filter(id=active_id)
        if tenant:
            qs = qs.filter(tenant=tenant)
        b = qs.first()
        if b:
            return b

    if profile and profile.branch:
        return profile.branch
    if emp and emp.branch:
        return emp.branch

    if can_operate_cross:
        return None

    if tenant:
        return tenant.branches.filter(status="active").first() or tenant.branches.first()

    return None
