from django.urls import path
from . import views

urlpatterns = [
    path("kitchen/", views.kitchen_view, name="kitchen"),
    path("api/kitchen/stream/", views.kitchen_stream_view, name="kitchen_stream"),
    path("api/kitchen/live/", views.kitchen_live_view, name="kitchen_live"),
]
