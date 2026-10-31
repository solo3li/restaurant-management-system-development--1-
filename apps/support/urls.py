from django.urls import path
from apps.support import views

urlpatterns = [
    path("support/", views.support_tickets_view, name="support_tickets"),
    path("support/tickets/", views.support_tickets_view, name="support_tickets_list"),
    path("support/tickets/<int:ticket_id>/", views.support_ticket_detail_view, name="support_ticket_detail"),

    # Support APIs
    path("api/support/tickets/create/", views.api_create_ticket, name="api_create_ticket"),
    path("api/support/tickets/<int:ticket_id>/reply/", views.api_ticket_reply, name="api_ticket_reply"),
    path("api/support/tickets/<int:ticket_id>/status/", views.api_ticket_update_status, name="api_ticket_update_status"),
]
