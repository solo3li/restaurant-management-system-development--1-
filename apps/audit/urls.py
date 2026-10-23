from django.urls import path
from . import views

urlpatterns = [
    path("api/audit-logs/", views.api_audit_logs, name="api_audit_logs"),
]
