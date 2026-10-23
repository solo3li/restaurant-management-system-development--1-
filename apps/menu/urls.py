from django.urls import path
from . import views

urlpatterns = [
    path("branch/menu/", views.branch_menu_view, name="branch_menu"),
    path("api/branch-menu/toggle/<int:item_id>/", views.api_toggle_branch_menu, name="api_toggle_branch_menu"),
    path("api/branches/<int:branch_id>/menu/<int:item_id>/price/", views.api_update_branch_item_price, name="api_update_branch_item_price"),
    path("api/menu-items/<int:item_id>/branch-prices/", views.api_get_item_branch_prices, name="api_get_item_branch_prices"),
    path("api/menu-items/<int:item_id>/branch-prices/update/", views.api_update_item_branch_prices, name="api_update_item_branch_prices"),
    path("api/menu/toggle/<int:item_id>/", views.api_toggle_menu_item, name="api_toggle_menu_item"),
    path("api/menu/create/", views.api_create_menu_item, name="api_create_menu_item"),
    path("api/menu/<int:item_id>/", views.api_update_menu_item, name="api_update_menu_item"),
    path("api/menu/<int:item_id>/delete/", views.api_delete_menu_item, name="api_delete_menu_item"),
    path("api/menu/categories/", views.api_list_categories, name="api_list_categories"),
    path("api/menu/categories/create/", views.api_create_category, name="api_create_category"),
    path("api/menu/categories/<int:cat_id>/", views.api_update_category, name="api_update_category"),
    path("api/menu/categories/<int:cat_id>/delete/", views.api_delete_category, name="api_delete_category"),

    # Digital Menu (QR & Online ordering)
    path("m/<slug:slug>/", views.digital_menu_view, name="digital_menu"),
    path("m/<slug:slug>/branch/<int:branch_id>/", views.digital_menu_view, name="digital_menu_branch"),
    path("api/m/<slug:slug>/areas/<int:branch_id>/", views.api_digital_menu_branch_areas, name="api_digital_menu_branch_areas"),
    path("api/m/<slug:slug>/order/", views.api_digital_menu_place_order, name="api_digital_menu_place_order"),
]
