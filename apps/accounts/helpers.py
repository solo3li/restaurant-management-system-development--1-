from django.core.cache import cache
from apps.accounts.models import RESTAURANT_PERMISSIONS


def _get_client_ip(request):
    """Safely extracts client IP address from HTTP request headers."""
    if not request:
        return None
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _check_rate_limit(key, max_attempts=5):
    """Checks if key is currently rate-limited (blocked)."""
    try:
        attempts = cache.get(key, 0)
        return attempts >= max_attempts
    except Exception:
        return False


def _record_failed_attempt(key, timeout_seconds=900):
    """Increments failed attempt count with 15 minutes expiration."""
    try:
        attempts = cache.get(key, 0) + 1
        cache.set(key, attempts, timeout=timeout_seconds)
        return attempts
    except Exception:
        return 1


def _clear_rate_limit(key):
    """Clears failed attempt count on successful login."""
    try:
        cache.delete(key)
    except Exception:
        pass


def user_has_perm(user, perm_key):
    """
    Unified pure Django auth permission check.
    Bypasses for superuser and tenant owner / platform admin.
    All staff authorization is strictly verified through Django's native
    Group and Permission engine: user.has_perm('core.<codename>') and user.groups.
    Includes symmetric synonym resolution and self-healing group synchronization.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    if profile and (profile.is_platform_admin or profile.role in ["owner", "platform_admin"]):
        return True

    clean_key = perm_key.split(".")[-1]

    # Symmetric permission synonyms (legacy compatibility with new granular taxonomy)
    SYNONYM_MAP = {
        "manage_branches": "branch_manage_branches",
        "branch_manage_branches": "manage_branches",
        "manage_roles": "system_manage_roles",
        "system_manage_roles": "manage_roles",
        "view_hq_dashboard": "hq_view_master_dashboard",
        "hq_view_master_dashboard": "view_hq_dashboard",
        "view_branch_dashboard": "branch_view_dashboard",
        "branch_view_dashboard": "view_branch_dashboard",
        "cancel_orders": "pos_cancel_order",
        "pos_cancel_order": "cancel_orders",
    }
    keys_to_check = [clean_key]
    if clean_key in SYNONYM_MAP:
        keys_to_check.append(SYNONYM_MAP[clean_key])

    # Implied permissions mapping
    IMPLIED_PERMS = {
        "view_financials": ["finance_view_sales", "finance_view_reports", "finance_view_profit_loss"],
        "menu_view": ["manage_menu"],
        "inventory_view": ["manage_inventory"],
        "hr_view_employees": ["manage_employees"],
    }
    if clean_key in IMPLIED_PERMS:
        for ik in IMPLIED_PERMS[clean_key]:
            if ik not in keys_to_check:
                keys_to_check.append(ik)

    for k in keys_to_check:
        if user.has_perm(f"core.{k}"):
            return True
        # Direct check on user's groups to guarantee 0ms latency even before permission cache refresh
        if user.groups.filter(permissions__codename=k).exists():
            return True

    # Self-healing fallback: verify through assigned JobRole if user's group association lagged
    job_role = None
    if profile and profile.job_role:
        job_role = profile.job_role
    elif hasattr(user, "employee_profile") and user.employee_profile and user.employee_profile.job_role:
        job_role = user.employee_profile.job_role

    if job_role:
        for k in keys_to_check:
            if job_role.has_perm(k):
                # Auto-sync group to user immediately
                grp = job_role.sync_with_django_group()
                if grp:
                    user.groups.add(grp)
                return True

    return False


def get_post_login_redirect(user):
    """Determine the optimal starting view dynamically based on user roles and permissions."""
    if not user or not user.is_authenticated:
        return "login"

    profile = getattr(user, "profile", None)
    if user.is_superuser or (profile and profile.is_platform_admin):
        return "/admin/"

    is_owner = (profile and profile.role == "owner")
    if profile and profile.tenant and not profile.tenant.is_active:
        return "owner_subscription" if is_owner else "login"

    if is_owner or user_has_perm(user, "view_hq_dashboard"):
        return "dashboard"

    if user_has_perm(user, "view_branch_dashboard"):
        return "branch_dashboard"

    # Route by operational permission priority
    if user_has_perm(user, "pos_access") or user_has_perm(user, "pos_create_order"):
        return "pos"
    if user_has_perm(user, "kds_access"):
        return "kitchen"
    if user_has_perm(user, "call_center_access") or user_has_perm(user, "call_center_create_order"):
        return "call_center"
    if user_has_perm(user, "delivery_access"):
        return "delivery"
    if user_has_perm(user, "view_orders"):
        return "branch_orders"
    if user_has_perm(user, "manage_menu") or user_has_perm(user, "menu_view") or user_has_perm(user, "menu_toggle_availability"):
        return "branch_menu"
    if user_has_perm(user, "manage_inventory") or user_has_perm(user, "inventory_view"):
        return "inventory"
    if user_has_perm(user, "manage_employees") or user_has_perm(user, "hr_view_employees"):
        return "employees"
    if user_has_perm(user, "manage_branches"):
        return "branches"

    return "branch_dashboard"
