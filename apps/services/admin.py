"""Admin configuration for services app (Patch B)."""
from django.contrib import admin

from .models import AdminAuditLog, AiUsage, SiteConfig, TelegramUsage, UserApiKey, UserControl


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ai_provider",
        "ai_model",
        "shared_ai_enabled",
        "shared_ai_key_last4",
        "tg_enabled",
        "tg_bot_username",
        "default_ai_access",
        "default_ai_daily_limit",
    )
    readonly_fields = ("shared_ai_key_last4", "tg_bot_token_last4")


@admin.register(UserControl)
class UserControlAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "ai_access",
        "ai_daily_limit",
        "ai_monthly_limit",
        "telegram_access",
        "is_blocked",
    )
    list_filter = ("ai_access", "telegram_access", "is_blocked")
    search_fields = ("user__email", "user__username")


@admin.register(UserApiKey)
class UserApiKeyAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "key_last4", "enabled", "validated_at", "created_at")
    list_filter = ("provider", "enabled")
    search_fields = ("user__email", "user__username")
    readonly_fields = ("key_last4", "validated_at", "created_at")


@admin.register(AiUsage)
class AiUsageAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "date",
        "source",
        "calls",
        "failed_calls",
        "input_tokens",
        "output_tokens",
    )
    list_filter = ("source", "date")
    search_fields = ("user__email", "user__username")


@admin.register(TelegramUsage)
class TelegramUsageAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "messages_sent", "failures")
    list_filter = ("date",)
    search_fields = ("user__email", "user__username")


@admin.register(AdminAuditLog)
class AdminAuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "admin", "action", "target_user")
    list_filter = ("action", "created_at")
    search_fields = ("admin__email", "target_user__email", "action")
    readonly_fields = ("created_at", "admin", "action", "target_user", "details")
