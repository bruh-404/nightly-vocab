"""Admin configuration for texts app."""
from django.contrib import admin

from .models import Text


@admin.register(Text)
class TextAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "text_date", "created_at")
    list_filter = ("text_date", "created_at")
    search_fields = ("title", "body", "user__email", "user__username")
    readonly_fields = ("created_at",)
