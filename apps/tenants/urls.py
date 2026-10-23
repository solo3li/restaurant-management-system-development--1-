from django.urls import path
from . import views

urlpatterns = [
    path("platform/", views.platform_dashboard_view, name="platform_dashboard"),
    path("switch-tenant/<int:tenant_id>/", views.switch_tenant_view, name="switch_tenant"),
    path("branch/", views.branch_dashboard_view, name="branch_dashboard"),
    path("branch/switch/<str:branch_id>/", views.switch_branch_view, name="switch_branch"),
    path("branches/", views.branches_view, name="branches"),
    path("api/branches/create/", views.api_create_branch, name="api_create_branch"),
    path("api/branches/toggle/<int:branch_id>/", views.api_toggle_branch, name="api_toggle_branch"),
    path("api/branches/<int:branch_id>/areas/", views.api_branch_delivery_areas, name="api_branch_delivery_areas"),
    path("api/branches/<int:branch_id>/currency/", views.api_update_branch_currency, name="api_update_branch_currency"),
    path("api/tenant/currency/", views.api_update_tenant_currency, name="api_update_tenant_currency"),
    path("api/settings/branding/", views.api_update_tenant_branding, name="api_update_tenant_branding"),
    path("api/settings/custom-domain/", views.api_update_custom_domain, name="api_update_custom_domain"),
]
