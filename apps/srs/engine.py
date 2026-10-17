"""Pure Python Spaced Repetition System (SRS) Engine.

Follows SRS_SPEC.md and roadmap Section 6 clarifications strictly.
ZERO Django imports allowed in this module.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import FrozenSet, List, Sequence, Set, Tuple

from .constants import (
    BASE_INTERVALS,
    COMMON_SUFFIXES,
    DIGRAPHS,
    STAGE_TARGET_TYPES,
    VOWELS,
)


@dataclass(frozen=True)
class CardState:
    """Immutable state representation of a vocabulary card in SRS."""

    id: int
    word: str
    stage: int
    target_type: int
    interval_days: int
    next_review_date: date | None
    last_reviewed_date: date | None
    consecutive_wrong: int
    total_wrong: int
    weak_indices: Tuple[int, ...] = ()


@dataclass(frozen=True)
class ReviewInput:
    """Input signals provided by the user and spelling evaluator."""

    meaning_correct: bool
    spelling_correct: bool | None = None
    typed_input: str | None = None


@dataclass(frozen=True)
class MaskedWord:
    """Masked representation of a word for Type 2 guided spelling."""

    display: str
    masked_indices: FrozenSet[int]


def round_half_up(x: float) -> int:
    """Rounds half up (floor(x + 0.5)) per Section 6.2 clarification."""
    return math.floor(x + 0.5)


def normalize_spelling(text: str) -> str:
    """Trims, lowercases, and collapses whitespace runs to a single space."""
    return " ".join(text.strip().lower().split())


def evaluate_spelling(word: str, user_input: str) -> bool:
    """Evaluates whether the user's typed spelling matches the card word."""
    return normalize_spelling(word) == normalize_spelling(user_input)


def extract_weak_indices(word: str, user_input: str) -> List[int]:
    """
    Extracts up to 4 character indices where the user misspelled the word.
    If user input is shorter than target, missing positions count as mismatches.
    """
    target = word.strip().lower()
    inp = user_input.strip().lower()
    mismatches: List[int] = []

    for i in range(len(target)):
        if i >= len(inp) or inp[i] != target[i]:
            mismatches.append(i)
            if len(mismatches) == 4:
                break

    return mismatches


def resolve_display_type(target_type: int, enabled_card_types: Sequence[int]) -> int:
    """
    Decouples true card type from user display settings (Fallback Mapper).
    Selects the closest enabled type per SRS_SPEC.md Section 6.
    """
    if target_type in enabled_card_types:
        return target_type

    enabled_set = set(enabled_card_types)
    if not enabled_set:
        return target_type

    if target_type == 3:
        return 2 if 2 in enabled_set else 1
    elif target_type == 1:
        return 2 if 2 in enabled_set else 3
    elif target_type == 2:
        return 1 if 1 in enabled_set else 3

    return 1


# ---------------- Review Outcome Helper Functions ----------------


def _handle_stage_0(
    card: CardState, review: ReviewInput, today: date
) -> Tuple[CardState, int]:
    """Handles first encounter (stage 0) transitions per Section 6.4."""
    if review.meaning_correct:
        return (
            CardState(
                id=card.id,
                word=card.word,
                stage=1,
                target_type=1,
                interval_days=1,
                next_review_date=today + timedelta(days=1),
                last_reviewed_date=today,
                consecutive_wrong=0,
                total_wrong=card.total_wrong,
                weak_indices=(),
            ),
            1,
        )

    weak = ()
    if review.spelling_correct is False and review.typed_input is not None:
        weak = tuple(extract_weak_indices(card.word, review.typed_input))

    return (
        CardState(
            id=card.id,
            word=card.word,
            stage=1,
            target_type=1,
            interval_days=1,
            next_review_date=today + timedelta(days=1),
            last_reviewed_date=today,
            consecutive_wrong=1,
            total_wrong=card.total_wrong + 1,
            weak_indices=weak,
        ),
        3,
    )


def _handle_outcome_1(
    card: CardState, today: date
) -> Tuple[CardState, int]:
    """Outcome 1: Fully Correct."""
    new_stage = min(8, card.stage + 1)
    new_target_type = STAGE_TARGET_TYPES[new_stage]

    if new_stage <= 5:
        penalty_factor = max(0.50, 1.0 - (card.total_wrong * 0.10))
        raw_interval = BASE_INTERVALS[new_stage] * penalty_factor
        interval_days = max(1, round_half_up(raw_interval))
    else:
        interval_days = BASE_INTERVALS[new_stage]

    return (
        CardState(
            id=card.id,
            word=card.word,
            stage=new_stage,
            target_type=new_target_type,
            interval_days=interval_days,
            next_review_date=today + timedelta(days=interval_days),
            last_reviewed_date=today,
            consecutive_wrong=0,
            total_wrong=card.total_wrong,
            weak_indices=(),
        ),
        1,
    )


def _handle_outcome_2(
    card: CardState, review: ReviewInput, today: date
) -> Tuple[CardState, int]:
    """Outcome 2: Meaning Correct, Spelling Wrong (Type 2 or 3)."""
    weak = ()
    if review.typed_input is not None:
        weak = tuple(extract_weak_indices(card.word, review.typed_input))

    interval_days = min(7, max(1, math.floor(BASE_INTERVALS[card.stage] / 2)))
    return (
        CardState(
            id=card.id,
            word=card.word,
            stage=card.stage,
            target_type=card.target_type,
            interval_days=interval_days,
            next_review_date=today + timedelta(days=interval_days),
            last_reviewed_date=today,
            consecutive_wrong=0,
            total_wrong=card.total_wrong + 1,
            weak_indices=weak,
        ),
        2,
    )


def _handle_outcome_3(
    card: CardState, review: ReviewInput, today: date, prev_active_date: date | None
) -> Tuple[CardState, int]:
    """Outcome 3: Meaning Wrong — First Failure (prior consecutive_wrong == 0)."""
    weak = ()
    if review.spelling_correct is False and review.typed_input is not None:
        weak = tuple(extract_weak_indices(card.word, review.typed_input))

    if card.target_type == 1:
        stage_reset, type_reset = 1, 1
    elif card.target_type == 2:
        stage_reset, type_reset = 3, 2
    else:
        stage_reset, type_reset = 5, 3

    # Long-Absence Soft Penalty Override (Section 6.6)
    if 2 <= card.stage <= 5 and prev_active_date is not None:
        if (today - prev_active_date).days > 7:
            stage_reset = max(1, stage_reset - 1)
            type_reset = STAGE_TARGET_TYPES[stage_reset]

    return (
        CardState(
            id=card.id,
            word=card.word,
            stage=stage_reset,
            target_type=type_reset,
            interval_days=1,
            next_review_date=today + timedelta(days=1),
            last_reviewed_date=today,
            consecutive_wrong=1,
            total_wrong=card.total_wrong + 1,
            weak_indices=weak,
        ),
        3,
    )


def _handle_outcome_4(
    card: CardState, review: ReviewInput, today: date
) -> Tuple[CardState, int]:
    """Outcome 4: Meaning Wrong — Repeated Consecutive Failure (prior consecutive_wrong >= 1)."""
    weak = ()
    if review.spelling_correct is False and review.typed_input is not None:
        weak = tuple(extract_weak_indices(card.word, review.typed_input))

    if card.target_type == 3:
        stage_demoted, type_demoted = 3, 2
    else:
        stage_demoted, type_demoted = 1, 1

    return (
        CardState(
            id=card.id,
            word=card.word,
            stage=stage_demoted,
            target_type=type_demoted,
            interval_days=1,
            next_review_date=today + timedelta(days=1),
            last_reviewed_date=today,
            consecutive_wrong=card.consecutive_wrong + 1,
            total_wrong=card.total_wrong + 1,
            weak_indices=weak,
        ),
        4,
    )


def apply_review(
    card: CardState,
    review: ReviewInput,
    today: date,
    prev_active_date: date | None = None,
) -> Tuple[CardState, int]:
    """
    Applies review outcome to card state and returns (new_state, outcome_code 1..4).
    Follows SRS_SPEC.md §5 and Section 6 clarifications.
    """
    if card.stage == 0:
        return _handle_stage_0(card, review, today)

    if review.meaning_correct and (
        review.spelling_correct is True or review.spelling_correct is None
    ):
        return _handle_outcome_1(card, today)

    if review.meaning_correct and review.spelling_correct is False:
        return _handle_outcome_2(card, review, today)

    if not review.meaning_correct and card.consecutive_wrong == 0:
        return _handle_outcome_3(card, review, today, prev_active_date)

    return _handle_outcome_4(card, review, today)


# ---------------- Masking Helpers ----------------


def _find_digraph_and_suffix_spans(
    lower_word: str, alpha_count: int
) -> Tuple[Set[int], Set[int]]:
    """Identifies indices covered by tricky digraphs and common suffixes."""
    digraph_indices: Set[int] = set()
    for dg in DIGRAPHS:
        start = 0
        while True:
            idx = lower_word.find(dg, start)
            if idx == -1:
                break
            digraph_indices.update(range(idx, idx + len(dg)))
            start = idx + 1

    suffix_indices: Set[int] = set()
    if alpha_count >= 6:
        for sfx in COMMON_SUFFIXES:
            if lower_word.endswith(sfx):
                sfx_start = len(lower_word) - len(sfx)
                suffix_indices.update(range(sfx_start, len(lower_word)))
                break

    return digraph_indices, suffix_indices


def _score_characters(
    word: str,
    weak_set: Set[int],
    digraph_indices: Set[int],
    suffix_indices: Set[int],
    rng: random.Random,
) -> dict[int, int]:
    """Scores character indices in strict precedence per SRS_SPEC.md §8 Step 2."""
    lower_word = word.lower()
    scores: dict[int, int] = {}

    for i, c in enumerate(word):
        if not c.isalpha():
            scores[i] = -1
        elif i == 0:
            scores[0] = 100 if 0 in weak_set else 0
        elif i in weak_set:
            scores[i] = 100
        elif i > 0 and lower_word[i] == lower_word[i - 1]:
            scores[i] = 85
        elif i in digraph_indices:
            scores[i] = 75
        elif 0 < i < len(word) - 1 and lower_word[i] in VOWELS:
            scores[i] = 60
        elif i == len(word) - 1 and lower_word[i] == "e":
            scores[i] = 50
        elif i in suffix_indices:
            scores[i] = 15
        else:
            scores[i] = 30

        if i > 0 and scores[i] > 0:
            scores[i] += rng.randint(0, 8)

    return scores


def _select_masked_indices(
    word: str, candidates: List[int], quota: int, max_consecutive_blanks: int
) -> Set[int]:
    """Applies Pass 1 (anti-clumping) and Pass 2 (fallback) selection."""
    masked_set: Set[int] = set()

    for idx in candidates:
        masked_set.add(idx)

        # Check contiguous run of blanks
        left = idx
        while left > 0 and word[left - 1].isalpha():
            left -= 1
        right = idx
        while right < len(word) - 1 and word[right + 1].isalpha():
            right += 1

        violates = False
        current_run = 0
        for pos in range(left, right + 1):
            if pos in masked_set:
                current_run += 1
                if current_run > max_consecutive_blanks:
                    violates = True
                    break
            else:
                current_run = 0

        if violates:
            masked_set.remove(idx)
        elif len(masked_set) == quota:
            break

    if len(masked_set) < quota:
        for idx in candidates:
            if idx not in masked_set and (idx != 0 or len(candidates) <= quota):
                masked_set.add(idx)
                if len(masked_set) == quota:
                    break

    return masked_set


def generate_masked_word(
    word: str,
    stage: int,
    weak_indices: Sequence[int] = (),
    rng: random.Random | None = None,
) -> MaskedWord:
    """Generates masked representation for Type 2 guided spelling per SRS_SPEC.md §8."""
    if rng is None:
        rng = random.Random(42)

    alpha_indices = [i for i, c in enumerate(word) if c.isalpha()]
    alpha_count = len(alpha_indices)

    if alpha_count <= 1:
        return MaskedWord(display=word, masked_indices=frozenset())

    ratio = 0.35 if stage <= 3 else 0.55
    quota = max(1, min(alpha_count - 1, round_half_up(alpha_count * ratio)))

    lower_word = word.lower()
    weak_set = set(weak_indices)
    digraphs, suffixes = _find_digraph_and_suffix_spans(lower_word, alpha_count)
    scores = _score_characters(word, weak_set, digraphs, suffixes, rng)

    max_consecutive_blanks = 2 if stage <= 3 else 3
    candidates = [i for i in range(len(word)) if scores.get(i, 0) > 0]
    candidates.sort(key=lambda i: (-scores[i], i))

    masked_set = _select_masked_indices(word, candidates, quota, max_consecutive_blanks)

    display_chars = ["_" if i in masked_set else c for i, c in enumerate(word)]
    display_str = " ".join(display_chars)

    return MaskedWord(display=display_str, masked_indices=frozenset(masked_set))


def build_daily_queue(
    due_cards: Sequence[CardState],
    new_cards: Sequence[CardState],
    today: date,
    daily_limit: int,
) -> List[int]:
    """Builds the prioritized daily review queue per SRS_SPEC.md §7."""
    valid_due = [
        c
        for c in due_cards
        if c.stage > 0 and c.next_review_date is not None and c.next_review_date <= today
    ]

    bucket_a = [c for c in valid_due if 1 <= c.stage <= 5]
    bucket_b = [c for c in valid_due if 6 <= c.stage <= 8]

    bucket_a.sort(
        key=lambda c: (
            0 if c.consecutive_wrong > 0 else 1,
            c.stage,
            -c.total_wrong,
            c.next_review_date or today,
            c.id,
        )
    )

    bucket_b.sort(
        key=lambda c: (
            c.next_review_date or today,
            c.stage,
            c.id,
        )
    )

    maintenance_cap = max(1, math.floor(daily_limit * 0.20))
    take_b = min(maintenance_cap, len(bucket_b))
    selected_b = bucket_b[:take_b]

    remaining_for_a = daily_limit - len(selected_b)
    take_a = min(remaining_for_a, len(bucket_a))
    selected_a = bucket_a[:take_a]

    selected_reviews = selected_a + selected_b

    free_slots = daily_limit - len(selected_reviews)
    if free_slots > 0 and len(bucket_b) > take_b:
        extra_b = bucket_b[take_b : take_b + free_slots]
        selected_reviews.extend(extra_b)

    remaining_slots = daily_limit - len(selected_reviews)
    selected_new: List[CardState] = []
    if remaining_slots > 0:
        valid_new = sorted([c for c in new_cards if c.stage == 0], key=lambda c: c.id)
        selected_new = valid_new[:remaining_slots]

    return [c.id for c in selected_reviews] + [c.id for c in selected_new]
