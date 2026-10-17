"""Unit and integration tests for Settings, Library, Dashboard, and Stats (Step 8)."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.cards.models import ReviewLog, WordCard
from apps.services.models import UserApiKey

User = get_user_model()


@pytest.fixture
def user_a(db):
    u = User.objects.create_user(username="usera@example.com", email="usera@example.com")
    u.profile.daily_limit = 20
    u.profile.enabled_card_types = [1, 2, 3]
    u.profile.accent = "uk"
    u.profile.save()
    return u


@pytest.fixture
def user_b(db):
    u = User.objects.create_user(username="userb@example.com", email="userb@example.com")
    u.profile.daily_limit = 15
    u.profile.enabled_card_types = [1, 2]
    u.profile.save()
    return u


@pytest.fixture
def client_a(user_a):
    c = Client()
    c.force_login(user_a)
    return c


@pytest.fixture
def client_b(user_b):
    c = Client()
    c.force_login(user_b)
    return c


# =====================================================================
# Dashboard Tests
# =====================================================================
def test_dashboard_view_anonymous_redirects(client):
    """Anonymous user is redirected to Google login / landing."""
    resp = client.get("/dashboard/")
    assert resp.status_code == 302


def test_dashboard_view_metrics(client_a, user_a):
    """Dashboard accurately displays due, new, and reviewed counts."""
    today = user_a.profile.get_local_date()

    # 1 due card
    WordCard.objects.create(
        user=user_a,
        word="due_word",
        context_sentence="A due word.",
        ctx_start=2,
        ctx_end=10,
        stage=2,
        next_review_date=today,
    )
    # 1 new card
    WordCard.objects.create(
        user=user_a,
        word="new_word",
        context_sentence="A new word.",
        ctx_start=2,
        ctx_end=10,
        stage=0,
    )
    # 1 reviewed log today
    c3 = WordCard.objects.create(
        user=user_a,
        word="done_word",
        context_sentence="A done word.",
        ctx_start=2,
        ctx_end=11,
        stage=3,
    )
    ReviewLog.objects.create(
        user=user_a,
        card=c3,
        local_date=today,
        display_type=1,
        meaning_correct=True,
        stage_before=2,
        stage_after=3,
        target_type_before=1,
        target_type_after=1,
        interval_after=4,
        outcome=1,
    )

    resp = client_a.get("/dashboard/")
    assert resp.status_code == 200
    assert resp.context["due_cards_count"] == 1
    assert resp.context["new_cards_count"] == 1
    assert resp.context["reviewed_today_count"] == 1
    assert resp.context["is_recovery"] is False


def test_dashboard_recovery_banner_after_7_days(client_a, user_a):
    """Dashboard shows recovery alert when user absent >= 7 days."""
    today = user_a.profile.get_local_date()
    user_a.profile.last_active_date = today - timedelta(days=8)
    user_a.profile.save()

    resp = client_a.get("/dashboard/")
    assert resp.status_code == 200
    assert resp.context["is_recovery"] is True


# =====================================================================
# Library & Card Actions Tests (incl. IDOR)
# =====================================================================
def test_library_view_isolation_and_filters(client_a, client_b, user_a, user_b):
    """User A only sees their own cards; search and stage filters work."""
    card_a1 = WordCard.objects.create(
        user=user_a,
        word="serendipity",
        meaning="کشف نامنتظره و خوش‌یمن",
        stage=1,
        context_sentence="A serendipity moment.",
        ctx_start=2,
        ctx_end=13,
    )
    card_a2 = WordCard.objects.create(
        user=user_a,
        word="ephemeral",
        meaning="",  # No meaning
        stage=8,
        context_sentence="Ephemeral joy.",
        ctx_start=0,
        ctx_end=9,
    )
    card_b1 = WordCard.objects.create(
        user=user_b,
        word="b_secret_word",
        meaning="کلمه کاربر ب",
        stage=1,
        context_sentence="Secret.",
        ctx_start=0,
        ctx_end=6,
    )

    # 1. User A sees their cards, not User B's
    resp_a = client_a.get("/library/")
    assert resp_a.status_code == 200
    cards_a = list(resp_a.context["cards"])
    assert card_a1 in cards_a
    assert card_a2 in cards_a
    assert card_b1 not in cards_a

    # 2. Search query filter
    resp_search = client_a.get("/library/?q=serendip")
    cards_search = list(resp_search.context["cards"])
    assert card_a1 in cards_search
    assert card_a2 not in cards_search

    # 3. Filter by stage
    resp_stage8 = client_a.get("/library/?stage=8")
    assert card_a2 in list(resp_stage8.context["cards"])
    assert card_a1 not in list(resp_stage8.context["cards"])

    # 4. Filter by phase: mastered
    resp_phase = client_a.get("/library/?phase=mastered")
    assert card_a2 in list(resp_phase.context["cards"])

    # 5. Filter by no_meaning
    resp_no_meaning = client_a.get("/library/?no_meaning=1")
    assert card_a2 in list(resp_no_meaning.context["cards"])
    assert card_a1 not in list(resp_no_meaning.context["cards"])


def test_card_crud_and_idor_protection(client_a, client_b, user_a, user_b):
    """User B cannot edit, suspend, reset, or delete User A's card (IDOR 404)."""
    card_a = WordCard.objects.create(
        user=user_a,
        word="tenacity",
        pos="noun",
        meaning="پشتکار",
        stage=4,
        context_sentence="Her tenacity won the race.",
        ctx_start=4,
        ctx_end=12,
    )

    # --- IDOR checks: User B tries actions on User A's card ---
    assert client_b.post(f"/api/cards/{card_a.id}/edit/", data={}, content_type="application/json").status_code == 404
    assert client_b.post(f"/api/cards/{card_a.id}/suspend/").status_code == 404
    assert client_b.post(f"/api/cards/{card_a.id}/reset/").status_code == 404
    assert client_b.post(f"/api/cards/{card_a.id}/delete/").status_code == 404

    # --- Legitimate actions by User A ---
    # Edit
    edit_resp = client_a.post(
        f"/api/cards/{card_a.id}/edit/",
        data={
            "word": "tenacity",
            "pos": "noun",
            "meaning": "سرخ‌سختی و پشتکار بالا",
            "context_sentence": "Great tenacity.",
        },
        content_type="application/json",
    )
    assert edit_resp.status_code == 200
    card_a.refresh_from_db()
    assert card_a.meaning == "سرخ‌سختی و پشتکار بالا"

    # Suspend / Unsuspend
    suspend_resp = client_a.post(f"/api/cards/{card_a.id}/suspend/")
    assert suspend_resp.status_code == 200
    card_a.refresh_from_db()
    assert card_a.is_suspended is True

    # Reset progress
    reset_resp = client_a.post(f"/api/cards/{card_a.id}/reset/")
    assert reset_resp.status_code == 200
    card_a.refresh_from_db()
    assert card_a.stage == 0
    assert card_a.target_type == 1

    # Delete
    del_resp = client_a.post(f"/api/cards/{card_a.id}/delete/")
    assert del_resp.status_code == 200
    assert not WordCard.objects.filter(pk=card_a.id).exists()


def test_manual_add_card_api(client_a, user_a):
    """User can add a card manually; validates length and creates WordCard."""
    # Valid single word
    resp = client_a.post(
        "/api/cards/new/",
        data={
            "word": "magnificent",
            "pos": "adjective",
            "meaning": "با شکوه",
            "context_sentence": "A magnificent view.",
        },
        content_type="application/json",
    )
    assert resp.status_code == 200
    card_id = resp.json()["card_id"]
    card = WordCard.objects.get(pk=card_id, user=user_a)
    assert card.word == "magnificent"
    assert card.pos == "adjective"
    assert card.stage == 0

    # Phrase > 5 words rejected
    resp_toolong = client_a.post(
        "/api/cards/new/",
        data={"word": "one two three four five six"},
        content_type="application/json",
    )
    assert resp_toolong.status_code == 400


# =====================================================================
# Settings & Validation Tests
# =====================================================================
def test_settings_get_and_post_persistence(client_a, user_a):
    """Settings form persists daily_limit, card_types, accent, and reminder."""
    # 1. GET page
    resp = client_a.get("/settings/")
    assert resp.status_code == 200

    # 2. POST update
    post_data = {
        "action": "save_general",
        "daily_limit": "30",
        "enabled_card_types": ["2", "3"],
        "accent": "us",
        "timezone": "Asia/Tehran",
        "reminder_enabled": "1",
        "reminder_time": "21:30",
        "telegram_chat_id": "987654321",
    }
    resp_post = client_a.post("/settings/", data=post_data)
    assert resp_post.status_code == 200

    user_a.profile.refresh_from_db()
    assert user_a.profile.daily_limit == 30
    assert user_a.profile.enabled_card_types == [2, 3]
    assert user_a.profile.accent == "us"
    assert user_a.profile.timezone == "Asia/Tehran"
    assert user_a.profile.reminder_enabled is True
    assert user_a.profile.reminder_time.hour == 21
    assert user_a.profile.reminder_time.minute == 30
    assert user_a.profile.telegram_chat_id == 987654321


def test_settings_cannot_uncheck_all_card_types(client_a, user_a):
    """Validation prevents user from disabling all card types."""
    post_data = {
        "action": "save_general",
        "daily_limit": "20",
        "enabled_card_types": [],  # Empty
    }
    resp = client_a.post("/settings/", data=post_data)
    assert resp.status_code == 200
    assert "حداقل یک نوع کارت باید فعال باشد" in resp.content.decode("utf-8")

    user_a.profile.refresh_from_db()
    assert len(user_a.profile.enabled_card_types) > 0


# =====================================================================
# BYOK Personal Key Tests (Patch B.6)
# =====================================================================
@patch("apps.services.ai.gemini.GeminiProvider.test_api_key")
def test_byok_save_toggle_and_delete(mock_test_key, client_a, user_a):
    """User can save, toggle, and delete their own Gemini key."""
    mock_test_key.return_value = (True, "")

    # 1. Save and test valid key
    resp_save = client_a.post(
        "/api/settings/ai-key/",
        data={"api_key": "AIzaSyD-ValidKey-1234"},
        content_type="application/json",
    )
    assert resp_save.status_code == 200
    data = resp_save.json()
    assert data["success"] is True
    assert data["key_last4"] == "1234"

    key_obj = UserApiKey.objects.get(user=user_a, provider="gemini")
    assert key_obj.enabled is True
    assert key_obj.get_key() == "AIzaSyD-ValidKey-1234"
    assert key_obj.validated_at is not None

    # 2. Toggle key
    resp_toggle = client_a.post("/api/settings/ai-key/toggle/")
    assert resp_toggle.status_code == 200
    key_obj.refresh_from_db()
    assert key_obj.enabled is False

    # 3. Delete key
    resp_del = client_a.post("/api/settings/ai-key/delete/")
    assert resp_del.status_code == 200
    assert not UserApiKey.objects.filter(user=user_a).exists()


@patch("apps.services.ai.gemini.GeminiProvider.test_api_key")
def test_byok_invalid_key_rejected(mock_test_key, client_a):
    """Invalid BYOK key is rejected and not saved."""
    mock_test_key.return_value = (False, "API key not found")

    resp = client_a.post(
        "/api/settings/ai-key/",
        data={"api_key": "invalid-key"},
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "کلید نامعتبر است" in resp.json()["error"]


# =====================================================================
# Account Deletion Tests
# =====================================================================
def test_account_deletion_cascades_and_logs_out(client_a, user_a):
    """Deleting account removes user, profile, cards, and redirects to /."""
    user_id = user_a.id
    WordCard.objects.create(
        user=user_a,
        word="to_be_deleted",
        context_sentence="Will be deleted.",
        ctx_start=0,
        ctx_end=13,
    )

    resp = client_a.post("/api/accounts/delete/")
    assert resp.status_code == 200
    assert resp.json()["redirect"] == "/"

    user_a.profile.refresh_from_db()
    assert user_a.profile.deletion_requested_at is not None

    # Simulate 24 hours passing and execute purge
    from datetime import timedelta
    from django.core.management import call_command
    from django.utils import timezone
    user_a.profile.deletion_requested_at = timezone.now() - timedelta(hours=25)
    user_a.profile.save()
    call_command("purge_deleted_accounts")

    assert not User.objects.filter(pk=user_id).exists()
    assert not WordCard.objects.filter(user_id=user_id).exists()


# =====================================================================
# Stats Tests
# =====================================================================
def test_stats_view_metrics_and_streak(client_a, user_a):
    """Stats view returns stage distribution, learned count, and streak."""
    today = user_a.profile.get_local_date()

    # Create cards across stages
    WordCard.objects.create(user=user_a, word="w0", stage=0, context_sentence="s", ctx_start=0, ctx_end=1)
    WordCard.objects.create(user=user_a, word="w2", stage=2, context_sentence="s", ctx_start=0, ctx_end=1)
    WordCard.objects.create(user=user_a, word="w6", stage=6, context_sentence="s", ctx_start=0, ctx_end=1)
    WordCard.objects.create(user=user_a, word="w8", stage=8, context_sentence="s", ctx_start=0, ctx_end=1)

    # Create consecutive review logs for a 3-day streak (today, yesterday, 2 days ago)
    c = WordCard.objects.first()
    for offset in range(3):
        ReviewLog.objects.create(
            user=user_a,
            card=c,
            local_date=today - timedelta(days=offset),
            display_type=1,
            meaning_correct=True,
            stage_before=1,
            stage_after=2,
            target_type_before=1,
            target_type_after=1,
            interval_after=2,
            outcome=1,
        )

    resp = client_a.get("/stats/")
    assert resp.status_code == 200
    assert resp.context["total_cards"] == 4
    assert resp.context["learned_words_count"] == 2  # stages 6 and 8
    assert resp.context["streak"] == 3
    assert resp.context["total_reviews"] == 3
    assert len(resp.context["activity_30d"]) == 30
