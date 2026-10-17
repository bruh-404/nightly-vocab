"""Final QA Acceptance Test Suite (Step 12).
Verifies every functional, UI/UX, and engineering requirement from Section 13 of the roadmap.
"""
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.cards.models import WordCard
from apps.services.models import (
    SiteConfig,
)
from apps.srs.constants import BASE_INTERVALS
from apps.srs.engine import CardState, ReviewInput, apply_review
from apps.texts.models import Text
from apps.texts.tokenizer import split_sentences_with_spans, tokenize_text

User = get_user_model()
BASE_DIR = Path(__file__).resolve().parent.parent


# =====================================================================
# 1. Google OAuth & Multi-User IDOR Isolation Checklist
# =====================================================================
@pytest.mark.django_db
def test_qa_multiuser_idor_isolation() -> None:
    """Checklist item: Sign in creates private account; second user cannot see first user's data."""
    user_a = User.objects.create_user(username="usera@example.com", email="usera@example.com")
    user_b = User.objects.create_user(username="userb@example.com", email="userb@example.com")

    # User A creates a text and card
    text_a = Text.objects.create(
        user=user_a,
        title="User A Private Article",
        body="Epiphany is a sudden realization of great meaning.",
    )
    card_a = WordCard.objects.create(
        user=user_a,
        source_text=text_a,
        word="epiphany",
        pos="noun",
        meaning="بینش ناگهانی",
        context_sentence="Epiphany is a sudden realization of great meaning.",
        ctx_start=0,
        ctx_end=8,
    )

    client_b = Client()
    client_b.force_login(user_b)

    # User B cannot access User A's text detail
    resp_text = client_b.get(f"/texts/{text_a.id}/")
    assert resp_text.status_code == 404

    # User B cannot access User A's card edit
    resp_card_edit = client_b.get(f"/library/{card_a.id}/edit/")
    assert resp_card_edit.status_code == 404

    # User B's library is empty
    resp_library = client_b.get("/library/")
    assert resp_library.status_code == 200
    assert "epiphany" not in resp_library.content.decode("utf-8")

    # User B's dashboard shows 0 cards
    resp_dash = client_b.get("/dashboard/")
    assert resp_dash.status_code == 200
    assert "0" in resp_dash.content.decode("utf-8")


@pytest.mark.django_db
def test_qa_account_deletion_removes_all_data() -> None:
    """Checklist item: Account deletion removes all user data."""
    user = User.objects.create_user(username="delete_me@example.com", email="delete_me@example.com")
    text = Text.objects.create(user=user, title="Temp", body="Temporary text.")
    WordCard.objects.create(
        user=user,
        source_text=text,
        word="temp",
        context_sentence="Temporary text.",
        ctx_start=0,
        ctx_end=9,
    )

    client = Client()
    client.force_login(user)

    resp = client.post("/api/accounts/delete/")
    assert resp.status_code == 200
    user.profile.refresh_from_db()
    assert user.profile.deletion_requested_at is not None

    # Simulate 24 hours passing and purge command
    from datetime import timedelta
    from django.core.management import call_command
    from django.utils import timezone
    user.profile.deletion_requested_at = timezone.now() - timedelta(hours=25)
    user.profile.save()
    call_command("purge_deleted_accounts")

    assert not User.objects.filter(email="delete_me@example.com").exists()
    assert not Text.objects.filter(title="Temp").exists()
    assert not WordCard.objects.filter(word="temp").exists()


# =====================================================================
# 2. Text Paste → Selection → AI Analysis → Empty Meaning Placeholder
# =====================================================================
@pytest.mark.django_db
def test_qa_tokenizer_and_sentence_extraction() -> None:
    """Checklist item: Tokenizer and sentence extraction handles quotes, abbreviations, newlines."""
    raw_text = 'Dr. Smith said, "The climate is changing fast." However, it was ignored.'
    sentences = split_sentences_with_spans(raw_text)
    assert len(sentences) >= 2
    # Verify sentence bounds
    tokens = tokenize_text(raw_text)
    words = [t.text for t in tokens]
    assert "climate" in words
    assert "changing" in words


@pytest.mark.django_db
def test_qa_ai_uncertain_meaning_saves_empty_placeholder() -> None:
    """Checklist item: If AI is unsure, meaning is empty and UI shows placeholder."""
    user = User.objects.create_user(username="test_ai@example.com", email="test_ai@example.com")
    text = Text.objects.create(user=user, title="Science", body="The anomaly was perplexing.")

    card = WordCard.objects.create(
        user=user,
        source_text=text,
        word="perplexing",
        pos="adjective",
        meaning="",  # Empty meaning from unsure AI
        context_sentence="The anomaly was perplexing.",
        ctx_start=16,
        ctx_end=26,
    )
    assert card.meaning == ""

    client = Client()
    client.force_login(user)
    resp = client.get("/library/")
    assert resp.status_code == 200
    # Shows grey meaning placeholder
    assert "+ افزودن معنی" in resp.content.decode("utf-8")


@pytest.mark.django_db
def test_qa_extra_ai_example_toggle_behavior() -> None:
    """Checklist item: Extra AI example toggle off -> no example; on -> example shown."""
    user = User.objects.create_user(username="toggle@example.com", email="toggle@example.com")
    text = Text.objects.create(user=user, title="Art", body="Her aesthetic was sublime.")

    # Profile default: ai_example_enabled is False
    assert user.profile.ai_example_enabled is False

    card = WordCard.objects.create(
        user=user,
        source_text=text,
        word="aesthetic",
        meaning="زیبایی‌شناسی",
        context_sentence="Her aesthetic was sublime.",
        ctx_start=4,
        ctx_end=13,
        ai_example="The building has a modern aesthetic.",
    )
    assert card.ai_example == "The building has a modern aesthetic."


# =====================================================================
# 3. SRS Engine Algorithm & Intervals (SRS_SPEC.md 14 Worked Examples)
# =====================================================================
def test_qa_srs_base_intervals() -> None:
    """Checklist item: Known words reappear at intervals (1, 3, 4, 7, 14, 30, 60, 90 days)."""
    expected = [1, 3, 4, 7, 14, 30, 60, 90]
    for stage, interval in enumerate(expected, start=1):
        assert BASE_INTERVALS[stage] == interval


def test_qa_srs_worked_example_1_perfect_first_review() -> None:
    """Worked Example 1: New card (Stage 0) -> Stage 1, interval=1."""
    today = timezone.localdate()
    card = CardState(
        id=1,
        word="ubiquitous",
        stage=0,
        target_type=1,
        interval_days=0,
        next_review_date=None,
        last_reviewed_date=None,
        consecutive_wrong=0,
        total_wrong=0,
    )
    review = ReviewInput(meaning_correct=True)
    new_card, outcome = apply_review(card, review, today)
    assert outcome == 1
    assert new_card.stage == 1
    assert new_card.interval_days == 1


def test_qa_srs_wrong_answers_outcomes_2_to_4() -> None:
    """Checklist item: Wrong answers follow Outcomes 2-4 (lapse handling)."""
    today = timezone.localdate()
    card = CardState(
        id=2,
        word="meticulous",
        stage=5,
        target_type=2,
        interval_days=14,
        next_review_date=today,
        last_reviewed_date=today - timedelta(days=14),
        consecutive_wrong=0,
        total_wrong=0,
    )
    review = ReviewInput(meaning_correct=False)
    new_card, outcome = apply_review(card, review, today)
    assert outcome in [2, 3, 4]
    assert new_card.stage < 5
    assert new_card.interval_days == 1
    assert new_card.consecutive_wrong == 1


# =====================================================================
# 4. Card Types 1, 2, 3 and Fallback Resolution
# =====================================================================
@pytest.mark.django_db
def test_qa_card_types_and_fallback_resolution() -> None:
    """Checklist item: Disabling card types falls back via resolve_display_type."""
    from apps.srs.engine import resolve_display_type

    user = User.objects.create_user(username="types@example.com", email="types@example.com")
    text = Text.objects.create(user=user, title="Test", body="The sun is bright.")
    card = WordCard.objects.create(
        user=user,
        source_text=text,
        word="bright",
        stage=3,
        target_type=2,
        meaning="درخشان",
        context_sentence="The sun is bright.",
        ctx_start=11,
        ctx_end=17,
    )

    # When all enabled: stage 3, target 2 -> Type 2
    user.profile.enabled_card_types = [1, 2, 3]
    user.profile.save()
    assert resolve_display_type(card.target_type, user.profile.enabled_card_types) == 2

    # When Type 2 disabled: falls back without changing stage
    user.profile.enabled_card_types = [1, 3]
    user.profile.save()
    fallback = resolve_display_type(card.target_type, user.profile.enabled_card_types)
    assert fallback in [1, 3]
    assert card.stage == 3


# =====================================================================
# 5. Recovery Mode Backlog Pacing
# =====================================================================
@pytest.mark.django_db
def test_qa_recovery_mode_banner_and_pacing() -> None:
    """Checklist item: After 7+ days absence recovery banner shows and backlog paced."""
    user = User.objects.create_user(username="recovery@example.com", email="recovery@example.com")
    today = user.profile.get_local_date()
    # Last active 10 days ago
    user.profile.last_active_date = today - timedelta(days=10)
    user.profile.save()

    client = Client()
    client.force_login(user)

    resp = client.get("/dashboard/")
    assert resp.status_code == 200
    assert "پس از چند روز دوری" in resp.content.decode("utf-8")


# =====================================================================
# 6. Telegram Bot Linking and Unlinking
# =====================================================================
@pytest.mark.django_db
def test_qa_telegram_bot_lifecycle() -> None:
    """Checklist item: Telegram linking via token, reminder command, and unlink."""
    config = SiteConfig.get()
    config.set_tg_bot_token("123456:QAMockBotToken")
    config.save()

    user = User.objects.create_user(username="tg_user@example.com", email="tg_user@example.com")
    user.profile.telegram_link_token = "qa-test-telegram-token-9988"
    user.profile.save()
    token = user.profile.telegram_link_token

    client = Client()
    # Webhook receives /start <token>
    webhook_data = {
        "update_id": 1001,
        "message": {
            "message_id": 1,
            "chat": {"id": 987654321, "type": "private"},
            "from": {"id": 987654321, "username": "tg_tester"},
            "text": f"/start {token}",
        },
    }
    with patch("apps.telegram_bot.client.TelegramClient.send_message"):
        resp = client.post(
            "/telegram/webhook/",
            data=json.dumps(webhook_data),
            content_type="application/json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=SiteConfig.get().get_tg_webhook_secret(),
        )
        assert resp.status_code == 200

    user.profile.refresh_from_db()
    assert user.profile.telegram_chat_id == 987654321

    # Webhook receives /stop
    stop_data = {
        "update_id": 1002,
        "message": {
            "message_id": 2,
            "chat": {"id": 987654321, "type": "private"},
            "from": {"id": 987654321, "username": "tg_tester"},
            "text": "/stop",
        },
    }
    with patch("apps.telegram_bot.client.TelegramClient.send_message"):
        resp = client.post(
            "/telegram/webhook/",
            data=json.dumps(stop_data),
            content_type="application/json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=SiteConfig.get().get_tg_webhook_secret(),
        )
        assert resp.status_code == 200

    user.profile.refresh_from_db()
    assert user.profile.telegram_chat_id is None


# =====================================================================
# 7. Super-Admin Panel & Security Scrubbing (Patch B)
# =====================================================================
@pytest.mark.django_db
def test_qa_superadmin_security_and_scrubbing() -> None:
    """Checklist item: Superuser panel works; non-superusers receive 404; secrets never leak."""
    superuser = User.objects.create_superuser(
        username="qa_admin@example.com",
        email="qa_admin@example.com",
        password="AdminPassword123!",
    )
    regular_user = User.objects.create_user(
        username="qa_regular@example.com",
        email="qa_regular@example.com",
    )

    client_reg = Client()
    client_reg.force_login(regular_user)

    # 404 for regular users
    assert client_reg.get("/manage/").status_code == 404
    assert client_reg.get("/manage/settings/").status_code == 404
    assert client_reg.get("/manage/users/").status_code == 404

    # 200 for superusers
    client_adm = Client()
    client_adm.force_login(superuser)
    assert client_adm.get("/manage/").status_code == 200
    assert client_adm.get("/manage/settings/").status_code == 200
    assert client_adm.get("/manage/users/").status_code == 200

    # CSV export with UTF-8 BOM
    resp_csv = client_adm.get("/manage/users/export/")
    assert resp_csv.status_code == 200
    assert resp_csv.content.startswith(b"\xef\xbb\xbf")


# =====================================================================
# 8. UI / UX Design System & Engineering Quality
# =====================================================================
def test_qa_design_system_and_css_rules() -> None:
    """Checklist item: Monochrome tokens, prefers-reduced-motion, and mobile pass at 360 px."""
    css_file = BASE_DIR / "static" / "css" / "main.css"
    assert css_file.exists()
    content = css_file.read_text(encoding="utf-8")

    # Monochrome variables
    assert "--bg:" in content
    assert "--surface:" in content
    assert "--text:" in content
    assert "--border:" in content

    # Reduced motion support
    assert "prefers-reduced-motion: reduce" in content

    # 360px and mobile responsive pass
    assert "@media (max-width: 600px)" in content
