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

    user_perms = set()
    if is_owner:
        user_perms = {
            "view_hq_dashboard", "view_branch_dashboard", "view_financials",
            "pos_access", "view_orders", "edit_orders", "cancel_orders", "delete_orders",
            "kds_access", "call_center_access", "delivery_access",
            "manage_menu", "manage_inventory", "manage_branches", "manage_employees", "manage_roles"
        }
    elif profile:
        if profile.job_role and profile.job_role.permissions:
            user_perms = set(profile.job_role.permissions)
        elif hasattr(request.user, "employee_profile") and request.user.employee_profile and request.user.employee_profile.job_role:
            user_perms = set(request.user.employee_profile.job_role.permissions)
        else:
            if profile.role == "branch_manager":
                user_perms = {"view_branch_dashboard", "pos_access", "view_orders", "edit_orders", "cancel_orders", "kds_access", "delivery_access", "manage_menu", "manage_inventory", "manage_employees"}
            elif profile.role == "cashier":
                user_perms = {"pos_access", "view_orders"}
            elif profile.role == "chef":
                user_perms = {"kds_access"}
            elif profile.role == "driver":
                user_perms = {"delivery_access"}
            elif profile.role == "call_center":
                user_perms = {"call_center_access", "view_orders"}

    return {
        "active_tenant": tenant,
        "tenant_name": tenant.name if tenant else "منصة إدارة المطاعم",
        "tenant_logo": tenant.logo_emoji if tenant else "🍽️",
        "all_tenants": all_tenants,
        "is_platform_admin": is_platform_admin,
        "is_owner": is_owner,
        "current_branch": current_branch,
        "is_hq_mode": is_hq_mode,
        "can_switch_branches": can_switch,
        "all_branches": all_branches,
        "user_profile": profile,
        "user_perms": user_perms,
    }
