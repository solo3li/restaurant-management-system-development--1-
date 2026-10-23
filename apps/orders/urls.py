from django.urls import path
from . import views

urlpatterns = [
    path("hq/orders/", views.hq_orders_view, name="hq_orders"),
    path("branch/orders/", views.branch_orders_view, name="branch_orders"),
    path("pos/", views.pos_view, name="pos"),
    path("delivery/", views.delivery_view, name="delivery"),
    path("api/delivery/stream/", views.delivery_stream_view, name="delivery_stream"),
    path("api/delivery/live/", views.api_delivery_live, name="api_delivery_live"),
    path("orders/<int:order_id>/", views.order_detail_view, name="order_detail"),
    path("orders/<int:order_id>/edit/", views.order_edit_view, name="order_edit"),
    path("api/orders/", views.api_create_order, name="api_create_order"),
    path("api/orders/<int:order_id>/", views.api_update_order, name="api_update_order"),
    path("api/orders/<int:order_id>/cancel/", views.api_cancel_order, name="api_cancel_order"),
    path("api/orders/<int:order_id>/delete/", views.api_delete_order, name="api_delete_order"),
    path("api/customers/search/", views.api_search_customers, name="api_search_customers"),
]
