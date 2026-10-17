"""URLs for super-admin management panel (Patch B.3 & B.5)."""
from django.urls import path

from . import manage_views

app_name = "services"

urlpatterns = [
    path("manage/", manage_views.manage_dashboard_view, name="manage_dashboard"),
    path("manage/settings/", manage_views.manage_settings_view, name="manage_settings"),
    path("manage/users/", manage_views.manage_users_view, name="manage_users"),
    path("manage/users/export/", manage_views.manage_users_export_csv, name="manage_users_export_csv"),
    path("manage/users/<int:user_id>/", manage_views.manage_user_detail_view, name="manage_user_detail"),
    path("api/manage/users/<int:user_id>/action/", manage_views.manage_quick_action_api, name="manage_quick_action"),
    path("api/manage/users/<int:user_id>/quick-action/", manage_views.manage_quick_action_api, name="manage_quick_action_alt"),
    path("api/manage/test-ai-key/", manage_views.manage_test_ai_key_api, name="manage_test_ai_key"),
    path("api/manage/test-telegram/", manage_views.manage_test_telegram_api, name="manage_test_telegram"),
    path("manage/backup/download/", manage_views.manage_download_backup_view, name="manage_download_backup"),
    path("api/manage/backup/send-telegram/", manage_views.manage_send_backup_telegram_api, name="manage_send_backup_telegram"),
    path("manage/backup/restore/", manage_views.manage_restore_backup_view, name="manage_restore_backup"),
]
