"""Comprehensive unit and integration tests for Super-Admin Panel (Step 10 / Patch B)."""
import json
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Profile
from apps.services.models import (
    AdminAuditLog,
    AiUsage,
    SiteConfig,
    TelegramUsage,
    UserApiKey,
    UserControl,
)

User = get_user_model()


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(
        username="admin@lexicontext.app",
        email="admin@lexicontext.app",
        password="SuperPassword123!",
    )


@pytest.fixture
def normal_user(db):
    u = User.objects.create_user(
        username="regular@lexicontext.app",
        email="regular@lexicontext.app",
    )
    Profile.objects.get_or_create(user=u)
    UserControl.objects.get_or_create(user=u)
    return u


@pytest.fixture
def admin_client(superuser):
    c = Client()
    c.force_login(superuser)
    return c


@pytest.fixture
def user_client(normal_user):
    c = Client()
    c.force_login(normal_user)
    return c


@pytest.fixture
def anon_client():
    return Client()


# =====================================================================
# 1. Access Control Tests (Patch B.5 - Must return 404 for non-superusers)
# =====================================================================
@pytest.mark.parametrize(
    "path",
    [
        "/manage/",
        "/manage/settings/",
        "/manage/users/",
        "/manage/users/export/",
    ],
)
def test_manage_panel_anonymous_gets_404(anon_client, path):
    """Anonymous visitors receive 404 Not Found (obscurity)."""
    resp = anon_client.get(path)
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/manage/",
        "/manage/settings/",
        "/manage/users/",
        "/manage/users/export/",
    ],
)
def test_manage_panel_regular_user_gets_404(user_client, path):
    """Normal authenticated users receive 404 Not Found."""
    resp = user_client.get(path)
    assert resp.status_code == 404


def test_manage_user_detail_non_superuser_gets_404(user_client, normal_user):
    """Normal user accessing /manage/users/<id>/ gets 404."""
    resp = user_client.get(f"/manage/users/{normal_user.id}/")
    assert resp.status_code == 404


def test_manage_api_non_superuser_gets_404(user_client, normal_user):
    """Normal user POSTing to manage APIs gets 404."""
    resp = user_client.post(
        f"/api/manage/users/{normal_user.id}/quick-action/",
        data=json.dumps({"action": "disable_ai"}),
        content_type="application/json",
    )
    assert resp.status_code == 404


# =====================================================================
# 2. Management Dashboard (/manage/)
# =====================================================================
def test_manage_dashboard_view(admin_client, superuser, normal_user):
    """Superuser can access dashboard and view accurate metrics."""
    today = timezone.localdate()
    # Create some usage
    AiUsage.objects.create(user=normal_user, date=today, source="shared", calls=5, input_tokens=100, output_tokens=50)
    TelegramUsage.objects.create(user=normal_user, date=today, messages_sent=3)

    resp = admin_client.get("/manage/")
    assert resp.status_code == 200
    assert "مدیریت ارشد سامانه" in resp.content.decode("utf-8")
    assert "سقف روزانه کل فراخوانی‌ها" in resp.content.decode("utf-8")
    assert normal_user.email in resp.content.decode("utf-8")


# =====================================================================
# 3. Management Settings (/manage/settings/)
# =====================================================================
def test_manage_settings_view_get(admin_client):
    """Superuser can view the settings page."""
    resp = admin_client.get("/manage/settings/")
    assert resp.status_code == 200
    assert "تنظیمات سراسری و سقف‌ها" in resp.content.decode("utf-8")


def test_manage_settings_update_ai(admin_client, superuser):
    """Updating AI section encrypts new key and logs audit action."""
    raw_key = "AIzaSySecretTestingKey1234"
    resp = admin_client.post(
        "/manage/settings/",
        {
            "section": "ai",
            "ai_provider": "gemini",
            "ai_model": "gemini-2.5-flash",
            "ai_master_switch": "on",
            "new_shared_ai_key": raw_key,
        },
    )
    assert resp.status_code == 200
    assert "تنظیمات هوش مصنوعی با موفقیت به‌روزرسانی شد" in resp.content.decode("utf-8")

    config = SiteConfig.get()
    assert config.ai_provider == "gemini"
    assert config.ai_model == "gemini-2.5-flash"
    assert config.ai_master_switch is True
    assert config.get_shared_ai_key() == raw_key
    assert config.masked_shared_ai_key == "••••1234"

    # Audit log check
    log = AdminAuditLog.objects.filter(admin=superuser, action="update_settings_ai").first()
    assert log is not None
    assert log.details["shared_ai_key"] == "••••1234"
    # Never leak raw key in audit log
    assert raw_key not in json.dumps(log.details)


def test_manage_settings_update_telegram(admin_client, superuser):
    """Updating Telegram section encrypts new token, updates rate limits and multi-channel force join."""
    raw_token = "123456:ABC-DEF1234ghIkl-zyx5678"
    resp = admin_client.post(
        "/manage/settings/",
        {
            "section": "telegram",
            "tg_bot_username": "@LexiBot",
            "tg_enabled": "on",
            "tg_rate_limit_type": "hourly",
            "tg_user_rate_limit": "50",
            "tg_force_join_enabled": "on",
            "force_channel_id[]": ["@Channel1", "@Channel2"],
            "force_channel_title[]": ["کانال اخبار", "کانال آموزشی"],
            "force_channel_link[]": ["https://t.me/Channel1", "https://t.me/Channel2"],
            "new_tg_bot_token": raw_token,
        },
    )
    assert resp.status_code == 200
    config = SiteConfig.get()
    assert config.tg_bot_username == "@LexiBot"
    assert config.tg_enabled is True
    assert config.tg_rate_limit_type == "hourly"
    assert config.tg_user_rate_limit == 50
    assert config.tg_force_join_enabled is True
    channels = config.get_force_join_channels()
    assert len(channels) == 2
    assert channels[0]["channel"] == "@Channel1"
    assert channels[1]["channel"] == "@Channel2"
    assert config.get_tg_bot_token() == raw_token
    assert config.masked_tg_bot_token == "••••5678"

    log = AdminAuditLog.objects.filter(admin=superuser, action="update_settings_telegram").first()
    assert log is not None
    assert raw_token not in json.dumps(log.details)


def test_manage_settings_update_caps(admin_client, superuser):
    """Updating caps & defaults."""
    resp = admin_client.post(
        "/manage/settings/",
        {
            "section": "caps",
            "default_ai_daily_limit": "25",
            "default_ai_monthly_limit": "400",
            "default_max_targets_per_call": "7",
            "global_ai_daily_cap": "500",
            "global_ai_monthly_cap": "12000",
            "default_ai_access": "own_only",
            "default_telegram_access": "allowed",
        },
    )
    assert resp.status_code == 200
    config = SiteConfig.get()
    assert config.default_ai_daily_limit == 25
    assert config.default_ai_monthly_limit == 400
    assert config.default_max_targets_per_call == 7
    assert config.global_ai_daily_cap == 500
    assert config.global_ai_monthly_cap == 12000
    assert config.default_ai_access == "own_only"


def test_manage_settings_update_access(admin_client, superuser):
    """Updating signups and whitelist."""
    resp = admin_client.post(
        "/manage/settings/",
        {
            "section": "access",
            "allowed_emails": "test1@example.com\ntest2@example.com",
        },
    )
    assert resp.status_code == 200
    config = SiteConfig.get()
    assert config.signups_open is False
    assert "test1@example.com" in config.allowed_emails


# =====================================================================
# 4. Users List, Search, Filter & CSV Export
# =====================================================================
def test_manage_users_view(admin_client, normal_user):
    """Users list renders users and supports search."""
    resp = admin_client.get("/manage/users/")
    assert resp.status_code == 200
    assert normal_user.email in resp.content.decode("utf-8")

    # Search existing
    resp_s = admin_client.get(f"/manage/users/?q={normal_user.email}")
    assert resp_s.status_code == 200
    assert normal_user.email in resp_s.content.decode("utf-8")

    # Search nonexistent
    resp_none = admin_client.get("/manage/users/?q=nonexistent_query_xyz")
    assert resp_none.status_code == 200
    assert "هیچ کاربری با معیارهای جستجو یافت نشد" in resp_none.content.decode("utf-8")


def test_manage_users_filter(admin_client, normal_user):
    """Filtering users by status."""
    ctrl = normal_user.control
    ctrl.is_blocked = True
    ctrl.save()

    resp = admin_client.get("/manage/users/?status=blocked")
    assert resp.status_code == 200
    assert normal_user.email in resp.content.decode("utf-8")

    resp_own = admin_client.get("/manage/users/?status=own_only")
    assert resp_own.status_code == 200
    assert normal_user.email not in resp_own.content.decode("utf-8")


def test_manage_users_export_csv(admin_client, normal_user):
    """CSV export returns BOM and user data."""
    resp = admin_client.get("/manage/users/export/")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    content = resp.content
    # Check UTF-8 BOM
    assert content.startswith(b"\xef\xbb\xbf")
    decoded = content.decode("utf-8")
    assert "شناسه,ایمیل,نام کاربری" in decoded
    assert normal_user.email in decoded


# =====================================================================
# 5. User Detail & Overrides (/manage/users/<id>/)
# =====================================================================
def test_manage_user_detail_view(admin_client, normal_user):
    """User detail displays user info and 30-day table."""
    resp = admin_client.get(f"/manage/users/{normal_user.id}/")
    assert resp.status_code == 200
    assert normal_user.email in resp.content.decode("utf-8")
    assert "تاریخچه مصرف ۳۰ روز گذشته" in resp.content.decode("utf-8")


def test_manage_user_save_overrides(admin_client, superuser, normal_user):
    """Saving per-user overrides updates UserControl and writes AdminAuditLog."""
    resp = admin_client.post(
        f"/manage/users/{normal_user.id}/",
        {
            "action": "save_overrides",
            "ai_access": "own_only",
            "ai_daily_limit": "50",
            "ai_monthly_limit": "800",
            "max_targets_per_call": "10",
            "telegram_access": "blocked",
            "is_blocked": "on",
            "admin_note": "Suspicious activity detected.",
        },
    )
    assert resp.status_code == 200
    ctrl = UserControl.objects.get(user=normal_user)
    assert ctrl.ai_access == "own_only"
    assert ctrl.ai_daily_limit == 50
    assert ctrl.ai_monthly_limit == 800
    assert ctrl.max_targets_per_call == 10
    assert ctrl.telegram_access == "blocked"
    assert ctrl.is_blocked is True
    assert ctrl.admin_note == "Suspicious activity detected."

    log = AdminAuditLog.objects.filter(admin=superuser, target_user=normal_user, action="update_user_overrides").first()
    assert log is not None
    assert log.details["ai_access"] == "own_only"
    assert log.details["is_blocked"] is True


# =====================================================================
# 6. Quick Action API (/api/manage/users/<id>/quick-action/)
# =====================================================================
@pytest.mark.parametrize(
    ("action", "check_attr", "expected_val"),
    [
        ("disable_ai", "ai_access", "disabled"),
        ("require_own_key", "ai_access", "own_only"),
        ("block_telegram", "telegram_access", "blocked"),
        ("toggle_block_user", "is_blocked", True),
    ],
)
def test_manage_quick_action_api(admin_client, normal_user, action, check_attr, expected_val):
    """Quick actions modify the targeted setting directly."""
    resp = admin_client.post(
        f"/api/manage/users/{normal_user.id}/quick-action/",
        data=json.dumps({"action": action}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    ctrl = UserControl.objects.get(user=normal_user)
    assert getattr(ctrl, check_attr) == expected_val


def test_manage_quick_action_reset_today(admin_client, normal_user):
    """Quick action reset_today_usage resets today's calls count to 0."""
    today = timezone.localdate()
    AiUsage.objects.create(user=normal_user, date=today, source="shared", calls=15)

    resp = admin_client.post(
        f"/api/manage/users/{normal_user.id}/quick-action/",
        data=json.dumps({"action": "reset_today_usage"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    usage = AiUsage.objects.get(user=normal_user, date=today)
    assert usage.calls == 0


# =====================================================================
# 7. Test AI Key and Test Telegram APIs
# =====================================================================
@patch.object(SiteConfig, "get_shared_ai_key", return_value="AIzaSyTestMockKey999")
def test_manage_test_ai_key_api_success(mock_key, admin_client):
    """Test AI key returns success when GeminiProvider validates."""
    with patch("apps.services.ai.gemini.GeminiProvider.test_api_key", return_value=(True, None)):
        resp = admin_client.post(
            "/api/manage/test-ai-key/",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "موفقیت" in data["message"]


def test_manage_test_ai_key_api_failure(admin_client):
    """Test AI key returns 400 when key is invalid."""
    with patch("apps.services.ai.gemini.GeminiProvider.test_api_key", return_value=(False, "Invalid API key")):
        resp = admin_client.post(
            "/api/manage/test-ai-key/",
            data=json.dumps({"api_key": "bad_key"}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "Invalid API key" in resp.json()["error"]


def test_manage_test_telegram_api(admin_client):
    """Test telegram API connects and registers webhook."""
    config = SiteConfig.get()
    config.set_tg_bot_token("123456:ABC-DEF")
    config.save()

    with patch("apps.services.manage_views.TelegramClient") as MockClient:
        instance = MockClient.return_value
        instance.get_me.return_value = {"username": "MockVocabBot"}
        instance.set_webhook.return_value = {"ok": True}

        resp = admin_client.post("/api/manage/test-telegram/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["bot_username"] == "MockVocabBot"
        assert "/telegram/webhook/" in data["webhook_url"]


# =====================================================================
# 8. Secret Scrubbing Test (No raw secrets in HTML or JSON)
# =====================================================================
def test_secrets_never_leak_in_responses(admin_client, superuser, normal_user):
    """Verify that plaintext API keys and bot tokens are never rendered in HTML."""
    raw_ai_key = "AIzaSySuperSecretKeyDoNotLeak9988"
    raw_tg_token = "99887766:SecretBotTokenDoNotLeak1122"

    config = SiteConfig.get()
    config.set_shared_ai_key(raw_ai_key)
    config.set_tg_bot_token(raw_tg_token)
    config.save()

    # Create BYOK for user
    key_obj, _ = UserApiKey.objects.get_or_create(user=normal_user, provider="gemini")
    key_obj.set_key("AIzaSyUserBYOKKeyDoNotLeak5566")
    key_obj.save()

    # 1. Settings page
    resp_settings = admin_client.get("/manage/settings/")
    content_settings = resp_settings.content.decode("utf-8")
    assert raw_ai_key not in content_settings
    assert raw_tg_token not in content_settings
    assert "••••9988" in content_settings
    assert "••••1122" in content_settings

    # 2. User detail page
    resp_detail = admin_client.get(f"/manage/users/{normal_user.id}/")
    content_detail = resp_detail.content.decode("utf-8")
    assert "AIzaSyUserBYOKKeyDoNotLeak5566" not in content_detail

    # 3. Users list page
    resp_users = admin_client.get("/manage/users/")
    content_users = resp_users.content.decode("utf-8")
    assert raw_ai_key not in content_users
    assert raw_tg_token not in content_users
