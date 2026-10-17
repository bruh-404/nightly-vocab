"""Unit tests for database models, constraints, and adapters (Step 3)."""
from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.cards.adapters import apply_state_to_card, card_to_state
from apps.cards.models import DailySession, ReviewLog, WordCard
from apps.services.models import AiUsage
from apps.srs.engine import CardState
from apps.texts.models import Text

User = get_user_model()
TODAY = date(2026, 10, 16)


@pytest.fixture
def test_user(db):
    return User.objects.create_user(username="testuser", email="test@example.com")


@pytest.fixture
def sample_text(test_user):
    return Text.objects.create(
        user=test_user,
        title="Chapter 1 - Habits",
        body="Good habits alleviate stress and lead to enduring progress.",
        text_date=TODAY,
    )


@pytest.mark.django_db
def test_text_auto_title_and_newline_normalization(test_user):
    """Text auto-generates title if blank and normalizes CRLF newlines."""
    text = Text.objects.create(
        user=test_user,
        title="",
        body="Line 1\r\nLine 2\rLine 3",
        text_date=TODAY,
    )
    assert text.title == f"Text — {TODAY.isoformat()}"
    assert "\r" not in text.body
    assert text.body == "Line 1\nLine 2\nLine 3"


@pytest.mark.django_db
def test_text_body_readonly_when_cards_reference_it(test_user, sample_text):
    """Text body cannot be altered once any card references the text."""
    # When no cards exist, editing body is allowed
    sample_text.body = "Updated content without cards."
    sample_text.save()

    # Now add a referencing card
    WordCard.objects.create(
        user=test_user,
        source_text=sample_text,
        word="habits",
        context_sentence="Good habits alleviate stress.",
        ctx_start=5,
        ctx_end=11,
        char_start=5,
        char_end=11,
    )

    # Attempting to edit body must raise ValidationError
    sample_text.body = "Trying to change body when card exists."
    with pytest.raises(ValidationError) as excinfo:
        sample_text.save()
    assert "متن اصلی دارای کلمات ذخیره‌شده است" in excinfo.value.messages[0]

    # But editing title is allowed!
    sample_text.refresh_from_db()
    sample_text.title = "New Title Only"
    sample_text.save()
    sample_text.refresh_from_db()
    assert sample_text.title == "New Title Only"


@pytest.mark.django_db
def test_wordcard_constraints_stage_and_target_type(test_user):
    """CheckConstraints validate that 0 <= stage <= 8 and 1 <= target_type <= 3."""
    # Valid card
    card = WordCard.objects.create(
        user=test_user,
        word="resilient",
        context_sentence="She is resilient.",
        ctx_start=7,
        ctx_end=16,
        stage=0,
        target_type=1,
    )
    assert card.pk is not None

    # Invalid stage > 8
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            WordCard.objects.create(
                user=test_user,
                word="invalid_stage",
                context_sentence="Invalid stage.",
                ctx_start=0,
                ctx_end=13,
                stage=9,
                target_type=1,
            )

    # Invalid stage < 0
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            WordCard.objects.create(
                user=test_user,
                word="invalid_stage_neg",
                context_sentence="Invalid stage neg.",
                ctx_start=0,
                ctx_end=17,
                stage=-1,
                target_type=1,
            )

    # Invalid target_type (e.g. 0 or 4)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            WordCard.objects.create(
                user=test_user,
                word="invalid_type",
                context_sentence="Invalid type.",
                ctx_start=0,
                ctx_end=12,
                stage=1,
                target_type=4,
            )


@pytest.mark.django_db
def test_unique_text_span_per_user(test_user, sample_text):
    """User cannot add the exact same text span twice from the same source text."""
    WordCard.objects.create(
        user=test_user,
        source_text=sample_text,
        word="alleviate",
        context_sentence="Good habits alleviate stress.",
        ctx_start=12,
        ctx_end=21,
        char_start=12,
        char_end=21,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            WordCard.objects.create(
                user=test_user,
                source_text=sample_text,
                word="alleviate",
                context_sentence="Good habits alleviate stress.",
                ctx_start=12,
                ctx_end=21,
                char_start=12,
                char_end=21,
            )


@pytest.mark.django_db
def test_review_log_unique_per_card_per_day(test_user):
    """ReviewLog enforces idempotency (1 review per card per local day)."""
    card = WordCard.objects.create(
        user=test_user,
        word="ubiquitous",
        context_sentence="Ubiquitous tech.",
        ctx_start=0,
        ctx_end=10,
    )

    ReviewLog.objects.create(
        user=test_user,
        card=card,
        local_date=TODAY,
        display_type=1,
        meaning_correct=True,
        stage_before=0,
        stage_after=1,
        target_type_before=1,
        target_type_after=1,
        interval_after=1,
        outcome=1,
    )

    # Second review on the same local_date violates unique_review_per_card_per_day
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ReviewLog.objects.create(
                user=test_user,
                card=card,
                local_date=TODAY,
                display_type=1,
                meaning_correct=True,
                stage_before=1,
                stage_after=2,
                target_type_before=1,
                target_type_after=1,
                interval_after=3,
                outcome=1,
            )


@pytest.mark.django_db
def test_daily_session_uniqueness(test_user):
    """DailySession enforces 1 session per user per local day."""
    DailySession.objects.create(
        user=test_user,
        local_date=TODAY,
        card_ids=[1, 2, 3],
        review_count=3,
        new_count=0,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DailySession.objects.create(
                user=test_user,
                local_date=TODAY,
                card_ids=[4, 5],
                review_count=2,
                new_count=0,
            )


@pytest.mark.django_db
def test_card_adapters_round_trip(test_user):
    """card_to_state and apply_state_to_card correctly convert between model and dataclass."""
    card = WordCard.objects.create(
        user=test_user,
        word="meticulous",
        context_sentence="He is meticulous.",
        ctx_start=6,
        ctx_end=16,
        stage=3,
        target_type=2,
        interval_days=4,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - date.resolution,
        consecutive_wrong=1,
        total_wrong=2,
        weak_indices=[2, 4],
    )

    state = card_to_state(card)
    assert isinstance(state, CardState)
    assert state.id == card.id
    assert state.word == "meticulous"
    assert state.stage == 3
    assert state.target_type == 2
    assert state.interval_days == 4
    assert state.weak_indices == (2, 4)

    # Mutate state and apply back
    new_state = CardState(
        id=card.id,
        word="meticulous",
        stage=4,
        target_type=2,
        interval_days=7,
        next_review_date=TODAY + date.resolution * 7,
        last_reviewed_date=TODAY,
        consecutive_wrong=0,
        total_wrong=2,
        weak_indices=(),
    )
    apply_state_to_card(card, new_state)
    assert card.stage == 4
    assert card.interval_days == 7
    assert card.consecutive_wrong == 0
    assert card.weak_indices == []


@pytest.mark.django_db
def test_ai_usage_model(test_user):
    """AiUsage correctly tracks shared vs own key calls per date."""
    usage_shared = AiUsage.objects.create(
        user=test_user,
        date=TODAY,
        source="shared",
        calls=5,
        failed_calls=0,
    )
    assert usage_shared.calls == 5

    # Can have a separate record on the same date for "own" source (Patch B)
    usage_own = AiUsage.objects.create(
        user=test_user,
        date=TODAY,
        source="own",
        calls=2,
    )
    assert usage_own.calls == 2

    # Duplicate (user, date, source) raises IntegrityError
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AiUsage.objects.create(
                user=test_user,
                date=TODAY,
                source="shared",
                calls=1,
            )
