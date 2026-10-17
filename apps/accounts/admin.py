"""Admin configuration for accounts app."""
from django.contrib import admin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "daily_limit",
        "accent",
        "timezone",
        "reminder_enabled",
        "telegram_chat_id",
        "last_active_date",
    )
    list_filter = ("accent", "reminder_enabled", "daily_limit")
    search_fields = ("user__email", "user__username", "telegram_chat_id")
