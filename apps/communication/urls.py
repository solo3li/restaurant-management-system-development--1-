from django.urls import path
from apps.communication import views

urlpatterns = [
    path("forgot-password/", views.forgot_password_view, name="forgot_password"),
    path("verify-code/", views.verify_code_view, name="verify_code"),
    path("reset-password/", views.reset_password_view, name="reset_password"),

    # Direct API aliases
    path("api/auth/forgot-password/", views.forgot_password_view, name="api_forgot_password"),
    path("api/auth/verify-code/", views.verify_code_view, name="api_verify_code"),
    path("api/auth/reset-password/", views.reset_password_view, name="api_reset_password"),

    # Brevo Webhooks
    path("api/brevo/webhook/inbound/", views.brevo_inbound_webhook_view, name="brevo_inbound_webhook"),
    path("api/brevo/webhook/events/", views.brevo_inbound_webhook_view, name="brevo_events_webhook"),
]
