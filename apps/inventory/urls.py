from django.urls import path
from . import views

urlpatterns = [
    path("inventory/", views.inventory_view, name="inventory"),
    path("api/inventory/adjust/<int:item_id>/", views.api_adjust_inventory, name="api_adjust_inventory"),
    path("api/inventory/create/", views.api_create_inventory, name="api_create_inventory"),
    path("api/inventory/delete/<int:item_id>/", views.api_delete_inventory, name="api_delete_inventory"),
]
