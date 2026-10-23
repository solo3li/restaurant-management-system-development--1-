from django.shortcuts import redirect
from django.http import JsonResponse
from django.contrib.auth import logout
from .models import Tenant, UserProfile


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        request.is_platform_admin = False
        request.custom_domain_tenant = None

        # Check for Custom Domain binding
        try:
            host = request.get_host().split(":")[0].lower()
            if host not in ["localhost", "127.0.0.1", "testserver"] and not host.endswith(".nip.io"):
                custom_t = Tenant.objects.filter(custom_domain__iexact=host, is_active=True).first()
                if custom_t:
                    request.custom_domain_tenant = custom_t
                    if not request.user.is_authenticated:
                        request.tenant = custom_t
                    if request.path in ["/", ""]:
                        from core.views import digital_menu_view
                        return digital_menu_view(request, slug=custom_t.slug)
        except Exception:
            pass

        if request.user.is_authenticated:
            profile = getattr(request.user, "profile", None)
            is_platform_admin = request.user.is_superuser or (profile and profile.is_platform_admin)
            request.is_platform_admin = is_platform_admin

            if is_platform_admin:
                # Platform admins can view cross-tenant or switch tenant in session
                active_t_id = request.session.get("active_tenant_id")
                if active_t_id:
                    request.tenant = Tenant.objects.filter(id=active_t_id).first()
                elif profile and profile.tenant:
                    request.tenant = profile.tenant
                else:
                    request.tenant = Tenant.objects.filter(is_active=True).first()
            else:
                # Tenant users (owners, managers, employees) are strictly bound to their tenant
                if profile and profile.tenant:
                    request.tenant = profile.tenant
                else:
                    emp = getattr(request.user, "employee_profile", None)
                    if emp and emp.tenant:
                        request.tenant = emp.tenant
                    else:
                        request.tenant = None

            # Enforce Tenant Suspension Lifecycle
            if request.tenant and not request.tenant.is_active and not is_platform_admin:
                path = request.path
                exempt_paths = [
                    "/logout/",
                    "/logout",
                    "/set-language/",
                    "/admin/",
                ]
                is_exempt = any(path.startswith(ep) for ep in exempt_paths)
                if not is_exempt:
                    is_owner = (profile and profile.role == "owner")
                    is_subscription_allowed = (
                        path.startswith("/subscription/") or
                        path.startswith("/subscription") or
                        path.startswith("/profile/") or
                        path.startswith("/profile") or
                        path.startswith("/user/profile/") or
                        path.startswith("/user/profile") or
                        path.startswith("/api/subscription/")
                    )

                    if is_owner:
                        if not is_subscription_allowed:
                            if request.headers.get("x-requested-with") == "XMLHttpRequest" or path.startswith("/api/"):
                                return JsonResponse({
                                    "error": "تم إيقاف حساب هذه المنشأة مؤقتاً. يرجى مراجعة صفحة الاشتراكات لتسوية الحساب.",
                                    "suspended": True
                                }, status=403)
                            return redirect("owner_subscription")
                    else:
                        # Non-owner staff/employees are completely blocked from suspended tenants
                        if request.headers.get("x-requested-with") == "XMLHttpRequest" or path.startswith("/api/"):
                            return JsonResponse({
                                "error": "تم إيقاف حساب هذه المنشأة مؤقتاً. يرجى مراجعة إدارة المطعم.",
                                "suspended": True
                            }, status=403)
                        logout(request)
                        return redirect("/login/?suspended=1")

        response = self.get_response(request)
        return response

