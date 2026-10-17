"""URLs for accounts, dashboard, settings, and learning statistics (Step 8)."""
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("settings/", views.settings_view, name="settings"),
    path("stats/", views.stats_view, name="stats"),
    path("api/settings/ai-key/", views.save_and_test_user_key_api, name="save_and_test_user_key"),
    path("api/settings/ai-key/toggle/", views.toggle_user_key_api, name="toggle_user_key"),
    path("api/settings/ai-key/delete/", views.delete_user_key_api, name="delete_user_key"),
    path("api/settings/telegram/disconnect/", views.disconnect_telegram_api, name="disconnect_telegram"),
    path("api/accounts/delete/", views.delete_account_api, name="delete_account"),
    path("api/accounts/timezone/", views.timezone_sync_view, name="timezone_sync"),
    path("api/user/backup/export/", views.user_export_backup_api, name="user_export_backup"),
    path("api/user/backup/import/", views.user_import_backup_api, name="user_import_backup"),
    path("login/", views.password_login_view, name="password_login"),
    path("api/settings/password/", views.set_password_api, name="set_password"),
]
