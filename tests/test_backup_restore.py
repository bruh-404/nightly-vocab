"""Unit tests for user backup export and safe import / merging."""
import io
import json
from datetime import date, timedelta
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.cards.models import WordCard
from apps.services.backup_service import generate_user_backup_dict, restore_user_backup
from apps.texts.models import Text

User = get_user_model()


@pytest.fixture
def user(db):
    u = User.objects.create_user(username="backupuser@example.com", email="backupuser@example.com")
    u.profile.daily_limit = 25
    u.profile.save()
    return u


@pytest.mark.django_db
def test_restore_user_backup_merge_no_overwrite(user):
    """Verifies that existing texts and cards are never overwritten or deleted."""
    # Existing text & card
    orig_text = Text.objects.create(user=user, title="Original Text", body="Original body")
    orig_card = WordCard.objects.create(
        user=user,
        source_text=orig_text,
        word="apple",
        meaning="سیب قرمز",
        context_sentence="I eat an apple.",
        ctx_start=10,
        ctx_end=15,
        stage=3,
        interval_days=7,
    )

    backup_data = {
        "export_type": "nightly_vocab_user_personal_data",
        "texts": [
            {"title": "Original Text", "body": "Modified incoming body which should be ignored!"},
            {"title": "Brand New Text", "body": "Brand new text body."},
        ],
        "cards": [
            {
                "word": "apple",
                "meaning": "سیب عوض شده",
                "context_sentence": "I eat an apple.",
                "stage": 5,
            },
            {
                "word": "banana",
                "meaning": "موز تازه",
                "context_sentence": "Monkeys love banana.",
                "source_text_title": "Brand New Text",
                "stage": 2,
                "interval_days": 4,
            },
        ],
    }

    # Restore with reset_review=True
    stats = restore_user_backup(user, backup_data, reset_review=True)
    assert stats["new_texts"] == 1
    assert stats["existing_texts"] == 1
    assert stats["new_cards"] == 1
    assert stats["existing_cards"] == 1

    # Verify original text body was NOT changed
    orig_text.refresh_from_db()
    assert orig_text.body == "Original body"

    # Verify original card meaning and stage were NOT overwritten
    orig_card.refresh_from_db()
    assert orig_card.meaning == "سیب قرمز"
    assert orig_card.stage == 3

    # Verify new card was added with stage 0 because reset_review=True
    new_card = WordCard.objects.get(user=user, word="banana")
    assert new_card.meaning == "موز تازه"
    assert new_card.stage == 0
    assert new_card.interval_days == 0
    assert new_card.next_review_date == timezone.localdate()
    assert new_card.source_text.title == "Brand New Text"


@pytest.mark.django_db
def test_restore_user_backup_preserve_review_progress(user):
    """Verifies that reset_review=False keeps the saved stages and intervals."""
    backup_data = {
        "export_type": "nightly_vocab_user_personal_data",
        "texts": [
            {"title": "Advanced Article", "body": "Some deep article content."},
        ],
        "cards": [
            {
                "word": "serendipity",
                "meaning": "کشف غیرمنتظره خوش‌یمن",
                "context_sentence": "It was pure serendipity.",
                "source_text_title": "Advanced Article",
                "stage": 4,
                "interval_days": 14,
                "next_review_date": (timezone.localdate() + timedelta(days=14)).isoformat(),
            },
        ],
    }

    stats = restore_user_backup(user, backup_data, reset_review=False)
    assert stats["new_cards"] == 1

    card = WordCard.objects.get(user=user, word="serendipity")
    assert card.stage == 4
    assert card.interval_days == 14
    assert card.next_review_date == timezone.localdate() + timedelta(days=14)


@pytest.mark.django_db
def test_user_import_backup_api_endpoint(user):
    """Tests the /api/user/backup/import/ API with file upload and options."""
    client = Client()
    client.force_login(user)

    payload = {
        "export_type": "nightly_vocab_user_personal_data",
        "texts": [{"title": "API Imported Text", "body": "Imported via endpoint"}],
        "cards": [
            {
                "word": "endpoint",
                "meaning": "نقطه پایانی",
                "context_sentence": "Test the API endpoint.",
                "stage": 1,
            }
        ],
    }
    json_bytes = json.dumps(payload).encode("utf-8")
    upload_file = io.BytesIO(json_bytes)
    upload_file.name = "backup.json"

    res = client.post(
        "/api/user/backup/import/",
        {"backup_file": upload_file, "reset_review": "true"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["stats"]["new_cards"] == 1
    assert data["stats"]["new_texts"] == 1

    card = WordCard.objects.get(user=user, word="endpoint")
    assert card.stage == 0  # reset to 0
