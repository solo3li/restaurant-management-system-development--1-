from django.shortcuts import redirect, render
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
                    from apps.callcenter.platform_hq import get_or_create_platform_hq_tenant
                    request.tenant = get_or_create_platform_hq_tenant()
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

            # Enforce 3-Tier Subscription Lifecycle & Hard Lockout
            if request.tenant and not is_platform_admin:
                path = request.path
                exempt_paths = [
                    "/logout/",
                    "/logout",
                    "/set-language/",
                    "/admin/",
                    "/api/inngest/",
                ]
                is_exempt = any(path.startswith(ep) for ep in exempt_paths)

                if not is_exempt:
                    is_owner = (profile and (profile.role == "owner" or profile.is_platform_admin))
                    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest" or path.startswith("/api/")

                    # TIER 3: Post-Grace Period Hard Lockout (Read-Only Mode) or Inactive
                    if request.tenant.is_locked_out():
                        if is_owner:
                            # Owner can access subscription & profile management
                            is_sub_allowed = (
                                path.startswith("/subscription/") or
                                path.startswith("/subscription") or
                                path.startswith("/profile/") or
                                path.startswith("/profile") or
                                path.startswith("/user/profile/") or
                                path.startswith("/user/profile") or
                                path.startswith("/api/subscription/")
                            )
                            # Owner can view past invoices/reports in read-only mode (GET only)
                            is_read_only_view = (
                                request.method in ["GET", "HEAD", "OPTIONS"] and (
                                    path.startswith("/dashboard") or
                                    path.startswith("/hq/orders") or
                                    path.startswith("/branch/orders") or
                                    path.startswith("/analytics") or
                                    path.startswith("/reports")
                                )
                            )

                            if not is_sub_allowed and not is_read_only_view:
                                if is_ajax or request.method in ["POST", "PUT", "PATCH", "DELETE"]:
                                    return JsonResponse({
                                        "error": "انتهت فترة الاشتراك. النظام حالياً في وضع القراءة فقط. يرجى تجديد الاشتراك.",
                                        "read_only": True,
                                        "locked": True,
                                        "suspended": True
                                    }, status=403)
                                return redirect("owner_subscription")
                            elif request.method in ["POST", "PUT", "PATCH", "DELETE"] and not is_sub_allowed:
                                # Zero mutations allowed outside subscription renewal
                                return JsonResponse({
                                    "error": "غير مسموح بإجراء أي تعديلات أو تسجيل طلبات جديدة أثناء توقف الاشتراك.",
                                    "read_only": True,
                                    "locked": True
                                }, status=403)
                        else:
                            # Cashier and staff: blocked with elegant multilingual block screen
                            if is_ajax:
                                return JsonResponse({
                                    "error": "انتهت صلاحية اشتراك المنشأة. يرجى مراجعة إدارة المطعم لتجديد الاشتراك.",
                                    "locked": True,
                                    "suspended": True
                                }, status=403)
                            return render(request, "subscription_expired_block.html", {
                                "tenant": request.tenant,
                            }, status=403)

                    # TIER 2: Grace Period (3 days post-expiration)
                    elif request.tenant.is_in_grace_period():
                        # POS & Order Creation are functional.
                        # Settings, menu editing, branch/employee management are locked.
                        management_prefixes = [
                            "/branches/",
                            "/employees/",
                            "/branch/menu/",
                            "/restaurant/profile/",
                            "/api/settings/",
                            "/api/branches/",
                            "/api/employees/",
                            "/api/menu/",
                            "/inventory/",
                        ]
                        is_management = any(path.startswith(p) for p in management_prefixes)
                        if is_management and request.method in ["POST", "PUT", "PATCH", "DELETE"]:
                            return JsonResponse({
                                "error": "تعديل الإعدادات والمنيو والفروع مقفل خلال فترة السماح. يرجى تجديد الاشتراك لاستعادة كافة الصلاحيات.",
                                "grace_period": True
                            }, status=403)

        response = self.get_response(request)
        return response
