from django.urls import path
from . import views

urlpatterns = [
    path("subscription/", views.owner_subscription_view, name="owner_subscription"),
    path("api/subscription/request-upgrade/", views.api_request_upgrade, name="api_request_upgrade"),
]
