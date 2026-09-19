from .models import Tenant, Branch, UserProfile


def branch_context(request):
    if not request.user.is_authenticated:
        return {}

    tenant = getattr(request, "tenant", None)
    profile = getattr(request.user, "profile", None)
    is_platform_admin = getattr(request, "is_platform_admin", False)

    # Scoped branches for the active tenant
    if tenant:
        all_branches = Branch.objects.filter(tenant=tenant, status="active").order_by("id")
    else:
        all_branches = Branch.objects.filter(status="active").order_by("id")

    is_owner = request.user.is_superuser or is_platform_admin or (profile and profile.role == "owner")

    if not is_owner and profile and profile.branch:
        # Branch staff are locked to their assigned branch
        current_branch = profile.branch
        can_switch = False
    else:
        can_switch = True
        active_id = request.session.get("active_branch_id")
        if active_id and tenant:
            current_branch = Branch.objects.filter(id=active_id, tenant=tenant).first()
        elif active_id:
            current_branch = Branch.objects.filter(id=active_id).first()
        else:
            current_branch = None

    is_hq_mode = current_branch is None

    all_tenants = Tenant.objects.filter(is_active=True).order_by("name") if is_platform_admin else None

    return {
        "active_tenant": tenant,
        "tenant_name": tenant.name if tenant else "منصة إدارة المطاعم",
        "tenant_logo": tenant.logo_emoji if tenant else "🍽️",
        "all_tenants": all_tenants,
        "is_platform_admin": is_platform_admin,
        "current_branch": current_branch,
        "is_hq_mode": is_hq_mode,
        "can_switch_branches": can_switch,
        "all_branches": all_branches,
        "user_profile": profile,
    }
