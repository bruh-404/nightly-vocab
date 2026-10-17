"""URLs for telegram_bot app."""
from django.urls import path

from . import views

app_name = "telegram_bot"

urlpatterns = [
    path("telegram/webhook/", views.telegram_webhook_view, name="webhook"),
]
