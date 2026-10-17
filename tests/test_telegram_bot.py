"""Unit and integration tests for Telegram Bot, Webhook, and Reminders (Step 9)."""
from datetime import time
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.cards.models import DailySession, ReviewLog, WordCard
from apps.services.models import SiteConfig, TelegramUsage, UserControl
from apps.telegram_bot.client import BotBlocked, BotNotConfigured, TelegramClient

User = get_user_model()


@pytest.fixture
def test_user(db):
    user = User.objects.create_user(username="tguser@example.com", email="tguser@example.com")
    profile = user.profile
    profile.daily_limit = 20
    profile.enabled_card_types = [1, 2, 3]
    profile.reminder_enabled = True
    profile.reminder_time = time(21, 0)
    profile.telegram_chat_id = 12345678
    profile.save()
    return user


@pytest.fixture
def site_config(db):
    config = SiteConfig.get()
    config.set_tg_bot_token("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
    config.tg_webhook_secret_enc = config.set_tg_bot_token.__globals__["encrypt_secret"]("secret-webhook-key-999")
    config.tg_bot_username = "NightlyVocabBot"
    config.tg_enabled = True
    config.save()
    return config


# =====================================================================
# TelegramClient Unit Tests
# =====================================================================
def test_client_raises_bot_not_configured_when_no_token(db):
    """TelegramClient raises BotNotConfigured when bot token is absent."""
    config = SiteConfig.get()
    config.tg_bot_token_enc = ""
    config.save()

    with pytest.raises(BotNotConfigured):
        TelegramClient()


def test_client_raises_bot_not_configured_when_bot_disabled(site_config):
    """TelegramClient raises BotNotConfigured when bot is disabled globally."""
    site_config.tg_enabled = False
    site_config.save()

    with pytest.raises(BotNotConfigured):
        TelegramClient()


@patch("httpx.Client.post")
def test_client_send_message_success(mock_post, site_config):
    """TelegramClient formats payload and returns result on success."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 99}}
    mock_post.return_value = mock_resp

    client = TelegramClient(token="test-token")
    res = client.send_message(
        chat_id=123,
        text="Test notification",
        reply_markup={"inline_keyboard": [[{"text": "Button", "url": "https://example.com"}]]},
    )

    assert res["message_id"] == 99
    call_args = mock_post.call_args[1]
    assert call_args["json"]["chat_id"] == 123
    assert call_args["json"]["parse_mode"] == "HTML"
    assert "reply_markup" in call_args["json"]


@patch("httpx.Client.post")
def test_client_send_message_raises_bot_blocked_on_403(mock_post, site_config):
    """TelegramClient raises BotBlocked when API responds with 403 Forbidden."""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_post.return_value = mock_resp

    client = TelegramClient(token="test-token")
    with pytest.raises(BotBlocked):
        client.send_message(chat_id=123, text="Hello")


# =====================================================================
# Webhook Endpoint Tests
# =====================================================================
def test_webhook_wrong_secret_returns_403(client, site_config):
    """Webhook rejects request with 403 when secret token header is missing or invalid."""
    resp_no_header = client.post(
        "/telegram/webhook/",
        data={"message": {"chat": {"id": 123}, "text": "/start"}},
        content_type="application/json",
    )
    assert resp_no_header.status_code == 403

    resp_wrong_header = client.post(
        "/telegram/webhook/",
        data={"message": {"chat": {"id": 123}, "text": "/start"}},
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="wrong-secret",
    )
    assert resp_wrong_header.status_code == 403


@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_webhook_start_linking_success(mock_send, client, test_user, site_config):
    """Webhook handles /start <token> and links user profile."""
    profile = test_user.profile
    profile.telegram_chat_id = None
    profile.telegram_link_token = "valid-token-xyz-123"
    profile.save()

    resp = client.post(
        "/telegram/webhook/",
        data={
            "message": {
                "chat": {"id": 88877766},
                "text": "/start valid-token-xyz-123",
            }
        },
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="secret-webhook-key-999",
    )

    assert resp.status_code == 200
    profile.refresh_from_db()
    assert profile.telegram_chat_id == 88877766
    assert profile.telegram_link_token is None
    assert profile.reminder_enabled is True
    mock_send.assert_called_once()
    assert "متصل شد" in mock_send.call_args[1]["text"]


@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_webhook_stop_unlinks_profile(mock_send, client, test_user, site_config):
    """Webhook handles /stop and unlinks user profile."""
    profile = test_user.profile
    profile.telegram_chat_id = 99112233
    profile.reminder_enabled = True
    profile.save()

    resp = client.post(
        "/telegram/webhook/",
        data={
            "message": {
                "chat": {"id": 99112233},
                "text": "/stop",
            }
        },
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="secret-webhook-key-999",
    )

    assert resp.status_code == 200
    profile.refresh_from_db()
    assert profile.telegram_chat_id is None
    assert profile.reminder_enabled is False
    mock_send.assert_called_once()
    assert "قطع شد" in mock_send.call_args[1]["text"]


@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_webhook_start_blocked_user_denied(mock_send, client, test_user, site_config):
    """Blocked user cannot link telegram via webhook."""
    profile = test_user.profile
    profile.telegram_chat_id = None
    profile.telegram_link_token = "token-for-blocked"
    profile.save()

    control, _ = UserControl.objects.get_or_create(user=test_user)
    control.telegram_access = "blocked"
    control.save()

    resp = client.post(
        "/telegram/webhook/",
        data={
            "message": {
                "chat": {"id": 555},
                "text": "/start token-for-blocked",
            }
        },
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="secret-webhook-key-999",
    )

    assert resp.status_code == 200
    profile.refresh_from_db()
    assert profile.telegram_chat_id is None  # Not linked
    assert "محدود شده است" in mock_send.call_args[1]["text"]


# =====================================================================
# send_reminders Management Command Tests
# =====================================================================
@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_send_reminders_sends_to_due_user(mock_send, test_user, site_config):
    """send_reminders delivers reminder to due user and logs TelegramUsage."""
    today = test_user.profile.get_local_date()

    # Create due card
    WordCard.objects.create(
        user=test_user,
        word="due_vocab",
        context_sentence="A due sentence.",
        ctx_start=2,
        ctx_end=12,
        stage=1,
        next_review_date=today,
    )

    call_command("send_reminders", force=True)

    mock_send.assert_called_once()
    call_args = mock_send.call_args[1]
    assert call_args["chat_id"] == test_user.profile.telegram_chat_id
    assert "وقت مرور شبانه‌ست" in call_args["text"]

    test_user.profile.refresh_from_db()
    assert test_user.profile.last_reminder_sent_date == today

    # Verify TelegramUsage incremented
    usage = TelegramUsage.objects.get(user=test_user, date=today)
    assert usage.messages_sent == 1


@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_send_reminders_idempotent_once_per_day(mock_send, test_user, site_config):
    """send_reminders does not send duplicate reminder if already sent today."""
    today = test_user.profile.get_local_date()
    test_user.profile.last_reminder_sent_date = today
    test_user.profile.save()

    WordCard.objects.create(
        user=test_user,
        word="due_vocab",
        context_sentence="Due.",
        ctx_start=0,
        ctx_end=3,
        stage=1,
        next_review_date=today,
    )

    call_command("send_reminders")
    mock_send.assert_not_called()


@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_send_reminders_skipped_when_nothing_due(mock_send, test_user, site_config):
    """send_reminders skips users with 0 cards due and 0 new cards."""
    # No cards created
    call_command("send_reminders", force=True)
    mock_send.assert_not_called()


@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_send_reminders_skipped_when_session_finished(mock_send, test_user, site_config):
    """send_reminders skips users who have already finished today's session."""
    today = test_user.profile.get_local_date()
    card = WordCard.objects.create(
        user=test_user,
        word="reviewed_card",
        context_sentence="Reviewed.",
        ctx_start=0,
        ctx_end=8,
        stage=1,
        next_review_date=today,
    )
    ReviewLog.objects.create(
        user=test_user,
        card=card,
        local_date=today,
        display_type=1,
        meaning_correct=True,
        stage_before=1,
        stage_after=2,
        target_type_before=1,
        target_type_after=1,
        interval_after=3,
        outcome=1,
    )
    DailySession.objects.create(
        user=test_user,
        local_date=today,
        card_ids=[card.id],
    )

    call_command("send_reminders", force=True)
    mock_send.assert_not_called()


@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_send_reminders_unlinks_on_bot_blocked(mock_send, test_user, site_config):
    """send_reminders unlinks chat_id and disables reminder if Telegram returns 403 BotBlocked."""
    mock_send.side_effect = BotBlocked("Blocked")
    today = test_user.profile.get_local_date()

    WordCard.objects.create(
        user=test_user,
        word="due_card",
        context_sentence="Due sentence.",
        ctx_start=0,
        ctx_end=3,
        stage=1,
        next_review_date=today,
    )

    call_command("send_reminders", force=True)

    test_user.profile.refresh_from_db()
    assert test_user.profile.telegram_chat_id is None
    assert test_user.profile.reminder_enabled is False


# =====================================================================
# set_telegram_webhook Management Command Tests
# =====================================================================
@patch("apps.telegram_bot.client.TelegramClient.get_me")
@patch("apps.telegram_bot.client.TelegramClient.set_webhook")
def test_set_telegram_webhook_command(mock_set_webhook, mock_get_me, site_config):
    """set_telegram_webhook registers webhook URL and updates bot username."""
    mock_get_me.return_value = {"username": "MyNewTestBot"}
    mock_set_webhook.return_value = True

    call_command("set_telegram_webhook", url="https://example.com")

    mock_set_webhook.assert_called_once()
    call_args = mock_set_webhook.call_args[1]
    assert call_args["webhook_url"] == "https://example.com/telegram/webhook/"

    site_config.refresh_from_db()
    assert site_config.tg_bot_username == "MyNewTestBot"


# =====================================================================
# Status Assessment, Reminder Time, and Anti-Spam Rate Limiting Tests
# =====================================================================
@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_webhook_status_command(mock_send, client, test_user, site_config):
    """Webhook /status returns user rank, assessment, today's review status, and reminder time."""
    today = test_user.profile.get_local_date()
    # Add a card
    WordCard.objects.create(
        user=test_user,
        word="perspicacious",
        context_sentence="A perspicacious scholar.",
        ctx_start=2,
        ctx_end=15,
        stage=5,
        next_review_date=today,
    )

    resp = client.post(
        "/telegram/webhook/",
        data={
            "message": {
                "chat": {"id": test_user.profile.telegram_chat_id},
                "text": "/status",
            }
        },
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="secret-webhook-key-999",
    )

    assert resp.status_code == 200
    mock_send.assert_called_once()
    sent_text = mock_send.call_args[1]["text"]
    assert "ارزیابی و وضعیت یادگیری شما" in sent_text
    assert "سطح و رنک" in sent_text
    assert "ساعت یادآوری امروز: 21:00" in sent_text
    assert "موظف نیستید" in sent_text
    markup = mock_send.call_args[1].get("reply_markup")
    assert markup is not None
    assert "inline_keyboard" in markup


@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_webhook_time_command_valid(mock_send, client, test_user, site_config):
    """Webhook /time HH:MM successfully updates profile.reminder_time."""
    resp = client.post(
        "/telegram/webhook/",
        data={
            "message": {
                "chat": {"id": test_user.profile.telegram_chat_id},
                "text": "/time 22:30",
            }
        },
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="secret-webhook-key-999",
    )

    assert resp.status_code == 200
    test_user.profile.refresh_from_db()
    assert test_user.profile.reminder_time == time(22, 30)
    mock_send.assert_called_once()
    assert "22:30" in mock_send.call_args[1]["text"]


@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_webhook_time_command_invalid(mock_send, client, test_user, site_config):
    """Webhook /time with invalid format informs user without updating time."""
    old_time = test_user.profile.reminder_time
    resp = client.post(
        "/telegram/webhook/",
        data={
            "message": {
                "chat": {"id": test_user.profile.telegram_chat_id},
                "text": "/time 99:99",
            }
        },
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="secret-webhook-key-999",
    )

    assert resp.status_code == 200
    test_user.profile.refresh_from_db()
    assert test_user.profile.reminder_time == old_time
    mock_send.assert_called_once()
    assert "نامعتبر" in mock_send.call_args[1]["text"]


@patch("apps.telegram_bot.client.TelegramClient.answer_callback_query")
@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_webhook_callback_query_set_time(mock_send, mock_answer_cq, client, test_user, site_config):
    """Webhook processes inline button click callback_query to set reminder time."""
    resp = client.post(
        "/telegram/webhook/",
        data={
            "callback_query": {
                "id": "cq_test_123",
                "data": "set_time:20:00",
                "message": {
                    "chat": {"id": test_user.profile.telegram_chat_id},
                },
            }
        },
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="secret-webhook-key-999",
    )

    assert resp.status_code == 200
    test_user.profile.refresh_from_db()
    assert test_user.profile.reminder_time == time(20, 0)
    mock_answer_cq.assert_called_once()
    assert "20:00" in mock_answer_cq.call_args[1]["text"]
    mock_send.assert_called_once()
    assert "20:00" in mock_send.call_args[1]["text"]


@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_telegram_rate_limiting_anti_spam(mock_send, client, test_user, site_config):
    """
    Anti-spam rate limiter allows messages up to limit, sends a single warning at limit+1,
    and ignores subsequent messages completely.
    """
    from django.core.cache import cache
    cache.clear()

    site_config.tg_user_rate_limit = 2
    site_config.tg_rate_limit_type = "daily"
    site_config.save()

    chat_id = test_user.profile.telegram_chat_id
    payload = {
        "message": {
            "chat": {"id": chat_id},
            "text": "/status",
        }
    }

    # Message 1: allowed
    r1 = client.post("/telegram/webhook/", data=payload, content_type="application/json",
                     HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="secret-webhook-key-999")
    assert r1.status_code == 200
    assert mock_send.call_count == 1

    # Message 2: allowed (reaches limit)
    r2 = client.post("/telegram/webhook/", data=payload, content_type="application/json",
                     HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="secret-webhook-key-999")
    assert r2.status_code == 200
    assert mock_send.call_count == 2

    # Message 3: limit exceeded! Sends warning message
    r3 = client.post("/telegram/webhook/", data=payload, content_type="application/json",
                     HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="secret-webhook-key-999")
    assert r3.status_code == 200
    assert mock_send.call_count == 3
    assert "محدودیت تعداد پیام" in mock_send.call_args[1]["text"]

    # Message 4: spammer completely ignored! No API call made
    r4 = client.post("/telegram/webhook/", data=payload, content_type="application/json",
                     HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="secret-webhook-key-999")
    assert r4.status_code == 200
    assert mock_send.call_count == 3  # Still 3, call was completely suppressed!


@patch("apps.telegram_bot.client.TelegramClient.get_chat_member")
@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_telegram_force_join_blocks_non_member(mock_send, mock_get_chat_member, client, test_user, site_config):
    """When force join is enabled, non-member users are blocked with join prompt."""
    from django.core.cache import cache
    cache.clear()

    site_config.tg_force_join_enabled = True
    site_config.tg_force_join_channel = "@MyChannel"
    site_config.tg_force_join_link = "https://t.me/MyChannel"
    site_config.save()

    mock_get_chat_member.return_value = {"status": "left"}

    resp = client.post(
        "/telegram/webhook/",
        data={
            "message": {
                "chat": {"id": test_user.profile.telegram_chat_id},
                "text": "/status",
            }
        },
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="secret-webhook-key-999",
    )

    assert resp.status_code == 200
    mock_send.assert_called_once()
    assert "الزامی است" in mock_send.call_args[1]["text"]


@patch("apps.telegram_bot.client.TelegramClient.get_chat_member")
@patch("apps.telegram_bot.client.TelegramClient.send_message")
def test_telegram_force_join_allows_member(mock_send, mock_get_chat_member, client, test_user, site_config):
    """When force join is enabled, verified members can use bot normally."""
    from django.core.cache import cache
    cache.clear()

    site_config.tg_force_join_enabled = True
    site_config.tg_force_join_channel = "@MyChannel"
    site_config.save()

    mock_get_chat_member.return_value = {"status": "member"}

    resp = client.post(
        "/telegram/webhook/",
        data={
            "message": {
                "chat": {"id": test_user.profile.telegram_chat_id},
                "text": "/status",
            }
        },
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="secret-webhook-key-999",
    )

    assert resp.status_code == 200
    mock_send.assert_called_once()
    assert "ارزیابی و وضعیت یادگیری شما" in mock_send.call_args[1]["text"]

