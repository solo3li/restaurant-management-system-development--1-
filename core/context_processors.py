from .models import Branch, UserProfile


def branch_context(request):
    if not request.user.is_authenticated:
        return {}

    all_branches = Branch.objects.filter(status="active").order_by("id")
    profile = getattr(request.user, "profile", None)

    is_owner = request.user.is_superuser or (profile and profile.role == "owner")

    if not is_owner and profile and profile.branch:
        # Branch staff are locked to their assigned branch
        current_branch = profile.branch
        can_switch = False
    else:
        can_switch = True
        active_id = request.session.get("active_branch_id")
        if active_id:
            current_branch = Branch.objects.filter(id=active_id).first()
        else:
            current_branch = None

    is_hq_mode = current_branch is None

    return {
        "current_branch": current_branch,
        "is_hq_mode": is_hq_mode,
        "can_switch_branches": can_switch,
        "all_branches": all_branches,
        "user_profile": profile,
    }
