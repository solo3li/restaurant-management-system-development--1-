from .models import Tenant, UserProfile


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        request.is_platform_admin = False

        if request.user.is_authenticated:
            profile = getattr(request.user, "profile", None)
            is_platform_admin = request.user.is_superuser or (profile and profile.is_platform_admin)
            request.is_platform_admin = is_platform_admin

            if is_platform_admin:
                # Platform admins can view cross-tenant or switch tenant in session
                active_t_id = request.session.get("active_tenant_id")
                if active_t_id:
                    request.tenant = Tenant.objects.filter(id=active_t_id, is_active=True).first()
                elif profile and profile.tenant:
                    request.tenant = profile.tenant
                else:
                    # Default to first tenant if available
                    request.tenant = Tenant.objects.filter(is_active=True).first()
            else:
                # Tenant users (owners, managers, employees) are strictly bound to their tenant
                if profile and profile.tenant:
                    request.tenant = profile.tenant
                else:
                    # Fallback to first active tenant
                    request.tenant = Tenant.objects.filter(is_active=True).first()

        response = self.get_response(request)
        return response
