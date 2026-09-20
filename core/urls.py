from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard_view, name="home"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("hq/orders/", views.hq_orders_view, name="hq_orders"),
    path("platform/", views.platform_dashboard_view, name="platform_dashboard"),
    path("platform/switch-tenant/<int:tenant_id>/", views.switch_tenant_view, name="switch_tenant"),
    path("branch/", views.branch_dashboard_view, name="branch_dashboard"),
    path("branch/switch/<str:branch_id>/", views.switch_branch_view, name="switch_branch"),
    path("kitchen/", views.kitchen_view, name="kitchen"),
    path("branch/orders/", views.branch_orders_view, name="branch_orders"),
    path("branch/menu/", views.branch_menu_view, name="branch_menu"),

    path("pos/", views.pos_view, name="pos"),
    path("call-center/", views.call_center_view, name="call_center"),
    path("delivery/", views.delivery_view, name="delivery"),
    path("inventory/", views.inventory_view, name="inventory"),
    path("branches/", views.branches_view, name="branches"),
    path("employees/", views.employees_view, name="employees"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    
    path("orders/<int:order_id>/", views.order_detail_view, name="order_detail"),
    path("orders/<int:order_id>/edit/", views.order_edit_view, name="order_edit"),

    # Internal JSON APIs
    path("api/tenants/create/", views.api_create_tenant, name="api_create_tenant"),
    path("api/orders/", views.api_create_order, name="api_create_order"),
    path("api/orders/<int:order_id>/", views.api_update_order, name="api_update_order"),
    path("api/orders/<int:order_id>/cancel/", views.api_cancel_order, name="api_cancel_order"),
    path("api/orders/<int:order_id>/delete/", views.api_delete_order, name="api_delete_order"),
    path("api/branch-menu/toggle/<int:item_id>/", views.api_toggle_branch_menu, name="api_toggle_branch_menu"),
    path("api/customers/search/", views.api_search_customers, name="api_search_customers"),
    path("api/menu/toggle/<int:item_id>/", views.api_toggle_menu_item, name="api_toggle_menu_item"),
    path("api/menu/create/", views.api_create_menu_item, name="api_create_menu_item"),
    path("api/inventory/adjust/<int:item_id>/", views.api_adjust_inventory, name="api_adjust_inventory"),
    path("api/inventory/create/", views.api_create_inventory, name="api_create_inventory"),
    path("api/inventory/delete/<int:item_id>/", views.api_delete_inventory, name="api_delete_inventory"),
    path("api/branches/create/", views.api_create_branch, name="api_create_branch"),
    path("api/branches/toggle/<int:branch_id>/", views.api_toggle_branch, name="api_toggle_branch"),
    path("api/branches/<int:branch_id>/areas/", views.api_branch_delivery_areas, name="api_branch_delivery_areas"),
    path("api/employees/create/", views.api_create_employee, name="api_create_employee"),
    path("api/employees/update/<int:emp_id>/", views.api_update_employee, name="api_update_employee"),
]
