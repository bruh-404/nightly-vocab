"""Adapters between Django WordCard model and pure Python CardState dataclass."""
from apps.srs.engine import CardState

from .models import WordCard


def card_to_state(card: WordCard) -> CardState:
    """Converts a WordCard model instance into an immutable CardState dataclass."""
    return CardState(
        id=card.id,
        word=card.word,
        stage=card.stage,
        target_type=card.target_type,
        interval_days=card.interval_days,
        next_review_date=card.next_review_date,
        last_reviewed_date=card.last_reviewed_date,
        consecutive_wrong=card.consecutive_wrong,
        total_wrong=card.total_wrong,
        weak_indices=tuple(card.weak_indices or []),
    )


def apply_state_to_card(card: WordCard, state: CardState) -> WordCard:
    """
    Applies the attributes of a CardState dataclass back onto a WordCard model instance.
    Does NOT call save() automatically.
    """
    card.stage = state.stage
    card.target_type = state.target_type
    card.interval_days = state.interval_days
    card.next_review_date = state.next_review_date
    card.last_reviewed_date = state.last_reviewed_date
    card.consecutive_wrong = state.consecutive_wrong
    card.total_wrong = state.total_wrong
    card.weak_indices = list(state.weak_indices)
    return card
