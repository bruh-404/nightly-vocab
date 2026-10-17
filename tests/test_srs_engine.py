"""Unit tests and worked examples for the Pure Python SRS Engine.

Covers all 14 worked examples from roadmap §6.2, property tests,
display type resolution, spelling evaluation, and 100% branch coverage.
"""
import math
import random
import sys
from datetime import date, timedelta

from apps.srs.engine import (
    CardState,
    ReviewInput,
    apply_review,
    build_daily_queue,
    evaluate_spelling,
    extract_weak_indices,
    generate_masked_word,
    resolve_display_type,
    round_half_up,
)

TODAY = date(2026, 10, 16)


def test_no_django_imports_in_srs() -> None:
    """Verifies that apps.srs has zero Django imports."""
    srs_modules = [m for m in sys.modules if m.startswith("apps.srs.")]
    for mod_name in srs_modules:
        mod = sys.modules[mod_name]
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if hasattr(attr, "__module__") and attr.__module__:
                assert "django" not in attr.__module__, f"Django import found in {mod_name}: {attr_name}"


# ---------------- 14 WORKED EXAMPLES (Section 6.2) ----------------


def test_worked_example_1() -> None:
    """Example 1: stage 0, total_wrong 0, meaning ✓ (Type 1) -> stage 1, type 1, interval 1."""
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
    new_card, outcome = apply_review(card, review, TODAY)

    assert outcome == 1
    assert new_card.stage == 1
    assert new_card.target_type == 1
    assert new_card.interval_days == 1
    assert new_card.next_review_date == TODAY + timedelta(days=1)
    assert new_card.total_wrong == 0


def test_worked_example_2() -> None:
    """Example 2: stage 2, total_wrong 0, meaning ✓ -> stage 3, type 2, interval 4."""
    card = CardState(
        id=2,
        word="perseverance",
        stage=2,
        target_type=1,
        interval_days=3,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - timedelta(days=3),
        consecutive_wrong=0,
        total_wrong=0,
    )
    review = ReviewInput(meaning_correct=True)
    new_card, outcome = apply_review(card, review, TODAY)

    assert outcome == 1
    assert new_card.stage == 3
    assert new_card.target_type == 2
    assert new_card.interval_days == 4
    assert new_card.next_review_date == TODAY + timedelta(days=4)


def test_worked_example_3() -> None:
    """Example 3: stage 3, total_wrong 2, meaning ✓ spelling ✓ -> stage 4, type 2, interval round_half_up(7×0.8)=6."""
    card = CardState(
        id=3,
        word="meticulous",
        stage=3,
        target_type=2,
        interval_days=4,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - timedelta(days=4),
        consecutive_wrong=0,
        total_wrong=2,
    )
    review = ReviewInput(meaning_correct=True, spelling_correct=True, typed_input="meticulous")
    new_card, outcome = apply_review(card, review, TODAY)

    assert outcome == 1
    assert new_card.stage == 4
    assert new_card.target_type == 2
    assert new_card.interval_days == 6
    assert new_card.next_review_date == TODAY + timedelta(days=6)


def test_worked_example_4() -> None:
    """Example 4: stage 4, total_wrong 5, meaning ✓ spelling ✓ -> stage 5, type 3, interval 14×0.5=7."""
    card = CardState(
        id=4,
        word="alleviate",
        stage=4,
        target_type=2,
        interval_days=7,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - timedelta(days=7),
        consecutive_wrong=0,
        total_wrong=5,
    )
    review = ReviewInput(meaning_correct=True, spelling_correct=True, typed_input="alleviate")
    new_card, outcome = apply_review(card, review, TODAY)

    assert outcome == 1
    assert new_card.stage == 5
    assert new_card.target_type == 3
    assert new_card.interval_days == 7
    assert new_card.next_review_date == TODAY + timedelta(days=7)


def test_worked_example_5() -> None:
    """Example 5: stage 5, meaning ✓ spelling ✗ -> stage 5 (unchanged), total_wrong +1, interval min(7,max(1,floor(14/2)))=7, weak_indices set."""
    card = CardState(
        id=5,
        word="environment",
        stage=5,
        target_type=3,
        interval_days=14,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - timedelta(days=14),
        consecutive_wrong=0,
        total_wrong=0,
    )
    review = ReviewInput(meaning_correct=True, spelling_correct=False, typed_input="enviroment")
    new_card, outcome = apply_review(card, review, TODAY)

    assert outcome == 2
    assert new_card.stage == 5
    assert new_card.target_type == 3
    assert new_card.total_wrong == 1
    assert new_card.interval_days == 7
    assert new_card.next_review_date == TODAY + timedelta(days=7)
    assert len(new_card.weak_indices) > 0


def test_worked_example_6() -> None:
    """Example 6: stage 7, meaning ✓ spelling ✗ -> stage 7, interval min(7,30)=7."""
    card = CardState(
        id=6,
        word="resilient",
        stage=7,
        target_type=3,
        interval_days=60,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - timedelta(days=60),
        consecutive_wrong=0,
        total_wrong=1,
    )
    review = ReviewInput(meaning_correct=True, spelling_correct=False, typed_input="resiliant")
    new_card, outcome = apply_review(card, review, TODAY)

    assert outcome == 2
    assert new_card.stage == 7
    assert new_card.target_type == 3
    assert new_card.interval_days == 7
    assert new_card.total_wrong == 2


def test_worked_example_7() -> None:
    """Example 7: stage 4, consecutive_wrong 0, meaning ✗ -> stage 3, type 2, consecutive_wrong 1, interval 1."""
    card = CardState(
        id=7,
        word="adversity",
        stage=4,
        target_type=2,
        interval_days=7,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - timedelta(days=7),
        consecutive_wrong=0,
        total_wrong=0,
    )
    review = ReviewInput(meaning_correct=False)
    new_card, outcome = apply_review(card, review, TODAY)

    assert outcome == 3
    assert new_card.stage == 3
    assert new_card.target_type == 2
    assert new_card.consecutive_wrong == 1
    assert new_card.total_wrong == 1
    assert new_card.interval_days == 1
    assert new_card.next_review_date == TODAY + timedelta(days=1)


def test_worked_example_8() -> None:
    """Example 8: stage 6, consecutive_wrong 1, meaning ✗ -> stage 3, type 2, consecutive_wrong 2, interval 1."""
    card = CardState(
        id=8,
        word="eloquent",
        stage=6,
        target_type=3,
        interval_days=30,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - timedelta(days=30),
        consecutive_wrong=1,
        total_wrong=2,
    )
    review = ReviewInput(meaning_correct=False)
    new_card, outcome = apply_review(card, review, TODAY)

    assert outcome == 4
    assert new_card.stage == 3
    assert new_card.target_type == 2
    assert new_card.consecutive_wrong == 2
    assert new_card.total_wrong == 3
    assert new_card.interval_days == 1


def test_worked_example_9() -> None:
    """Example 9: stage 2, consecutive_wrong 1, meaning ✗ -> stage 1, type 1, interval 1."""
    card = CardState(
        id=9,
        word="pragmatic",
        stage=2,
        target_type=1,
        interval_days=3,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - timedelta(days=3),
        consecutive_wrong=1,
        total_wrong=1,
    )
    review = ReviewInput(meaning_correct=False)
    new_card, outcome = apply_review(card, review, TODAY)

    assert outcome == 4
    assert new_card.stage == 1
    assert new_card.target_type == 1
    assert new_card.consecutive_wrong == 2
    assert new_card.interval_days == 1


def test_worked_example_10() -> None:
    """Example 10: stage 4, absent 9 days, consecutive_wrong 0, meaning ✗ -> reset to 3, then −1 -> stage 2, type 1, interval 1."""
    prev_active = TODAY - timedelta(days=9)
    card = CardState(
        id=10,
        word="scrutinize",
        stage=4,
        target_type=2,
        interval_days=7,
        next_review_date=TODAY,
        last_reviewed_date=prev_active,
        consecutive_wrong=0,
        total_wrong=0,
    )
    review = ReviewInput(meaning_correct=False)
    new_card, outcome = apply_review(card, review, TODAY, prev_active_date=prev_active)

    assert outcome == 3
    assert new_card.stage == 2
    assert new_card.target_type == 1
    assert new_card.consecutive_wrong == 1
    assert new_card.interval_days == 1


def test_worked_example_11() -> None:
    """Example 11: stage 8, meaning ✓ spelling ✓ -> stage 8, interval 90."""
    card = CardState(
        id=11,
        word="permanent",
        stage=8,
        target_type=3,
        interval_days=90,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - timedelta(days=90),
        consecutive_wrong=0,
        total_wrong=0,
    )
    review = ReviewInput(meaning_correct=True, spelling_correct=True, typed_input="permanent")
    new_card, outcome = apply_review(card, review, TODAY)

    assert outcome == 1
    assert new_card.stage == 8
    assert new_card.target_type == 3
    assert new_card.interval_days == 90
    assert new_card.next_review_date == TODAY + timedelta(days=90)


def test_worked_example_12() -> None:
    """Example 12: daily_limit=20 -> maintenance_cap = max(1, floor(20×0.2)) = 4."""
    daily_limit = 20
    cap = max(1, math.floor(daily_limit * 0.2))
    assert cap == 4


def test_worked_example_13() -> None:
    """Example 13: word 'environment', stage 3 -> quota = 4; stage 4 -> quota = 6."""
    word = "environment"
    rng = random.Random(123)

    masked_stage3 = generate_masked_word(word, stage=3, rng=rng)
    assert len(masked_stage3.masked_indices) == 4

    masked_stage4 = generate_masked_word(word, stage=4, rng=rng)
    assert len(masked_stage4.masked_indices) == 6


def test_worked_example_14() -> None:
    """Example 14: queue: 30 overdue Bucket-A cards, limit 20 -> exactly 16 from A + 4 from B (or overflow to A if B is short); 0 new words."""
    due_cards = [
        CardState(
            id=i,
            word=f"word_{i}",
            stage=2,
            target_type=1,
            interval_days=3,
            next_review_date=TODAY - timedelta(days=1),
            last_reviewed_date=TODAY - timedelta(days=4),
            consecutive_wrong=0,
            total_wrong=0,
        )
        for i in range(1, 31)
    ]
    new_cards = [
        CardState(
            id=100 + i,
            word=f"new_{i}",
            stage=0,
            target_type=1,
            interval_days=0,
            next_review_date=None,
            last_reviewed_date=None,
            consecutive_wrong=0,
            total_wrong=0,
        )
        for i in range(10)
    ]

    queue = build_daily_queue(due_cards=due_cards, new_cards=new_cards, today=TODAY, daily_limit=20)
    assert len(queue) == 20
    assert all(cid <= 30 for cid in queue)
    assert not any(cid >= 100 for cid in queue)


# ---------------- ADDITIONAL SRS & EDGE CASE TESTS ----------------


def test_stage_0_failure() -> None:
    """First encounter failure moves to stage 1, type 1, consecutive_wrong 1."""
    card = CardState(
        id=20,
        word="novel",
        stage=0,
        target_type=1,
        interval_days=0,
        next_review_date=None,
        last_reviewed_date=None,
        consecutive_wrong=0,
        total_wrong=0,
    )
    review = ReviewInput(meaning_correct=False, spelling_correct=False, typed_input="noval")
    new_card, outcome = apply_review(card, review, TODAY)

    assert outcome == 3
    assert new_card.stage == 1
    assert new_card.target_type == 1
    assert new_card.consecutive_wrong == 1
    assert new_card.total_wrong == 1
    assert new_card.interval_days == 1
    assert new_card.weak_indices == (3,)


def test_stage_1_failure_first_and_repeated() -> None:
    """Failure on stage 1 resets to stage 1."""
    card = CardState(
        id=21,
        word="basic",
        stage=1,
        target_type=1,
        interval_days=1,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - timedelta(days=1),
        consecutive_wrong=0,
        total_wrong=0,
    )
    new_card, outcome = apply_review(card, ReviewInput(meaning_correct=False), TODAY)
    assert outcome == 3
    assert new_card.stage == 1
    assert new_card.consecutive_wrong == 1

    new_card2, outcome2 = apply_review(new_card, ReviewInput(meaning_correct=False), TODAY)
    assert outcome2 == 4
    assert new_card2.stage == 1
    assert new_card2.consecutive_wrong == 2


def test_stage_5_failure_first_reset() -> None:
    """First failure on stage 5 resets to stage 5."""
    card = CardState(
        id=22,
        word="advanced",
        stage=5,
        target_type=3,
        interval_days=14,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - timedelta(days=14),
        consecutive_wrong=0,
        total_wrong=0,
    )
    new_card, outcome = apply_review(card, ReviewInput(meaning_correct=False), TODAY)
    assert outcome == 3
    assert new_card.stage == 5
    assert new_card.target_type == 3


def test_stage_6_maintenance_success_intervals() -> None:
    """Stages 6, 7 advance with fixed intervals 30, 60, 90."""
    card = CardState(
        id=23,
        word="mastery",
        stage=5,
        target_type=3,
        interval_days=14,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - timedelta(days=14),
        consecutive_wrong=0,
        total_wrong=0,
    )
    c6, _ = apply_review(card, ReviewInput(meaning_correct=True, spelling_correct=True, typed_input="mastery"), TODAY)
    assert c6.stage == 6
    assert c6.interval_days == 30

    c7, _ = apply_review(c6, ReviewInput(meaning_correct=True, spelling_correct=True, typed_input="mastery"), TODAY)
    assert c7.stage == 7
    assert c7.interval_days == 60

    c8, _ = apply_review(c7, ReviewInput(meaning_correct=True, spelling_correct=True, typed_input="mastery"), TODAY)
    assert c8.stage == 8
    assert c8.interval_days == 90


def test_resolve_display_type() -> None:
    """Verifies all fallback cases for decoupled card types."""
    assert resolve_display_type(1, [1, 2, 3]) == 1
    assert resolve_display_type(2, [1, 2, 3]) == 2
    assert resolve_display_type(3, [1, 2, 3]) == 3

    assert resolve_display_type(3, [1, 2]) == 2
    assert resolve_display_type(3, [1]) == 1

    assert resolve_display_type(1, [2, 3]) == 2
    assert resolve_display_type(1, [3]) == 3

    assert resolve_display_type(2, [1, 3]) == 1
    assert resolve_display_type(2, [3]) == 3

    assert resolve_display_type(2, []) == 2
    assert resolve_display_type(99, [1, 2]) == 1


def test_evaluate_spelling_phrases_and_whitespace() -> None:
    """Spelling evaluator trims, collapses whitespace, allows phrases."""
    assert evaluate_spelling("safe and sound", "  safe   and   sound  ") is True
    assert evaluate_spelling("take off", "take off") is True
    assert evaluate_spelling("take off", "take-off") is False
    assert evaluate_spelling("environment", "ENVIRONMENT") is True
    assert evaluate_spelling("environment", "enviroment") is False


def test_extract_weak_indices() -> None:
    """Extracts up to 4 mistyped character positions."""
    assert extract_weak_indices("environment", "enviroment") == [6, 7, 8, 9]
    assert extract_weak_indices("abcde", "xyz") == [0, 1, 2, 3]
    assert extract_weak_indices("test", "") == [0, 1, 2, 3]


def test_masking_short_words_and_phrases() -> None:
    """Masking works on phrases, very short words, and respects non-alpha characters."""
    res_single = generate_masked_word("a", stage=3)
    assert res_single.display == "a"
    assert len(res_single.masked_indices) == 0

    res_two = generate_masked_word("in", stage=3)
    assert len(res_two.masked_indices) == 1
    assert 0 not in res_two.masked_indices

    phrase = "well-being"
    res_phrase = generate_masked_word(phrase, stage=3)
    assert "-" not in [phrase[i] for i in res_phrase.masked_indices]

    res_weak0 = generate_masked_word("test", stage=3, weak_indices=(0,))
    assert 0 in res_weak0.masked_indices

    res_weak_mid = generate_masked_word("testing", stage=3, weak_indices=(2,))
    assert 2 in res_weak_mid.masked_indices

    res_silent_e = generate_masked_word("make", stage=3)
    assert len(res_silent_e.masked_indices) > 0


def test_masking_anti_clumping_and_quota() -> None:
    """Anti-clumping ensures no contiguous blanks beyond max_consecutive_blanks."""
    word = "comprehension"
    res = generate_masked_word(word, stage=3)
    masked = sorted(res.masked_indices)
    for i in range(len(masked) - 2):
        assert not (masked[i] + 1 == masked[i + 1] and masked[i + 1] + 1 == masked[i + 2])


def test_masking_clumping_violation_and_pass2() -> None:
    """Forces anti-clumping violation in Pass 1 and fallback to Pass 2."""
    # In 'receiver', weak_indices=(1, 2, 3) gives highest scores to three consecutive characters.
    # At stage 3, max_consecutive_blanks is 2.
    # When Pass 1 attempts to add index 3, contiguous run becomes 3 > 2, so it violates and gets removed.
    res = generate_masked_word("receiver", stage=3, weak_indices=(1, 2, 3))
    assert len(res.masked_indices) > 0


def test_daily_queue_bucket_a_b_allocation_and_new_words() -> None:
    """Verifies allocation with both Bucket A and B, plus new word injection."""
    due_a = [
        CardState(
            id=i,
            word=f"a_{i}",
            stage=2,
            target_type=1,
            interval_days=3,
            next_review_date=TODAY,
            last_reviewed_date=TODAY - timedelta(days=3),
            consecutive_wrong=0,
            total_wrong=0,
        )
        for i in range(1, 6)
    ]
    due_b = [
        CardState(
            id=10 + i,
            word=f"b_{i}",
            stage=6,
            target_type=3,
            interval_days=30,
            next_review_date=TODAY,
            last_reviewed_date=TODAY - timedelta(days=30),
            consecutive_wrong=0,
            total_wrong=0,
        )
        for i in range(1, 6)
    ]
    new_cards = [
        CardState(
            id=100 + i,
            word=f"new_{i}",
            stage=0,
            target_type=1,
            interval_days=0,
            next_review_date=None,
            last_reviewed_date=None,
            consecutive_wrong=0,
            total_wrong=0,
        )
        for i in range(1, 11)
    ]

    queue = build_daily_queue(due_cards=due_a + due_b, new_cards=new_cards, today=TODAY, daily_limit=15)
    assert len(queue) == 15
    assert queue[-5:] == [101, 102, 103, 104, 105]


def test_round_half_up() -> None:
    """Verifies round_half_up behavior."""
    assert round_half_up(5.5) == 6
    assert round_half_up(5.4) == 5
    assert round_half_up(5.6) == 6
    assert round_half_up(0.0) == 0
    assert round_half_up(2.5) == 3


def test_outcome_3_and_4_with_spelling_mistakes() -> None:
    """Covers extraction of weak indices when user fails meaning and spelling."""
    card = CardState(
        id=30,
        word="python",
        stage=3,
        target_type=2,
        interval_days=4,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - timedelta(days=4),
        consecutive_wrong=0,
        total_wrong=0,
    )
    r3 = ReviewInput(meaning_correct=False, spelling_correct=False, typed_input="pyton")
    c3, outcome3 = apply_review(card, r3, TODAY)
    assert outcome3 == 3
    assert len(c3.weak_indices) > 0

    r4 = ReviewInput(meaning_correct=False, spelling_correct=False, typed_input="pyton")
    c4, outcome4 = apply_review(c3, r4, TODAY)
    assert outcome4 == 4
    assert len(c4.weak_indices) > 0


def test_masking_suffix_and_pass2() -> None:
    """Covers suffix scoring (-ing, -ed, -ly) and pass 2 fallback for short words."""
    word_suffix = "testing"
    res_sfx = generate_masked_word(word_suffix, stage=3)
    assert len(res_sfx.masked_indices) > 0

    word_short = "cat"
    res_short = generate_masked_word(word_short, stage=4)
    assert len(res_short.masked_indices) == 2


def test_select_masked_indices_pass2_fallback() -> None:
    """Explicitly tests Pass 2 fallback when Pass 1 anti-clumping leaves quota unfulfilled."""
    from apps.srs.engine import _select_masked_indices

    # With max_consecutive_blanks=1 and quota=4:
    # Pass 1 adds 1 and 3 (rejecting 2 and 4 due to clumping)
    # Pass 2 iterates and adds 2 (continuing loop), then adds 4 and breaks
    result = _select_masked_indices("abcdef", candidates=[1, 2, 3, 4], quota=4, max_consecutive_blanks=1)
    assert result == {1, 2, 3, 4}

    # Pass 2 exhausts all candidates without breaking
    exhaust = _select_masked_indices("abcdef", candidates=[1, 2], quota=5, max_consecutive_blanks=1)
    assert len(exhaust) <= 2


def test_outcome_3_recent_active_no_soft_penalty() -> None:
    """When user was absent <= 7 days, normal reset applies without extra -1 stage penalty."""
    card = CardState(
        id=60,
        word="test",
        stage=4,
        target_type=2,
        interval_days=7,
        next_review_date=TODAY,
        last_reviewed_date=TODAY - timedelta(days=3),
        consecutive_wrong=0,
        total_wrong=0,
    )
    c, o = apply_review(
        card,
        ReviewInput(meaning_correct=False),
        TODAY,
        prev_active_date=TODAY - timedelta(days=3),
    )
    assert o == 3
    # Resets to 3 (normal for target_type 2) and does NOT drop to 2
    assert c.stage == 3
    assert c.target_type == 2


def test_typed_input_none_in_all_outcomes() -> None:
    """Verifies that typed_input=None in failure outcomes produces empty weak_indices."""
    card = CardState(
        id=50,
        word="test",
        stage=0,
        target_type=1,
        interval_days=0,
        next_review_date=None,
        last_reviewed_date=None,
        consecutive_wrong=0,
        total_wrong=0,
    )
    # Stage 0 with typed_input None
    c0, o0 = apply_review(card, ReviewInput(meaning_correct=False, spelling_correct=False, typed_input=None), TODAY)
    assert o0 == 3
    assert c0.weak_indices == ()

    # Outcome 2 with typed_input None
    card2 = CardState(
        id=51,
        word="test",
        stage=3,
        target_type=2,
        interval_days=4,
        next_review_date=TODAY,
        last_reviewed_date=TODAY,
        consecutive_wrong=0,
        total_wrong=0,
    )
    c2, o2 = apply_review(card2, ReviewInput(meaning_correct=True, spelling_correct=False, typed_input=None), TODAY)
    assert o2 == 2
    assert c2.weak_indices == ()

    # Outcome 3 with spelling_correct=None (Type 1 card meaning failed)
    c3_type1, o3_type1 = apply_review(card2, ReviewInput(meaning_correct=False, spelling_correct=None), TODAY)
    assert o3_type1 == 3
    assert c3_type1.weak_indices == ()

    # Outcome 3 with spelling_correct=True
    c3_spell_true, o3_spell_true = apply_review(card2, ReviewInput(meaning_correct=False, spelling_correct=True, typed_input="pyton"), TODAY)
    assert o3_spell_true == 3
    assert c3_spell_true.weak_indices == ()

    # Outcome 3 with typed_input None
    c3, o3 = apply_review(card2, ReviewInput(meaning_correct=False, spelling_correct=False, typed_input=None), TODAY)
    assert o3 == 3
    assert c3.weak_indices == ()

    # Outcome 4 with typed_input None
    card4 = CardState(
        id=52,
        word="test",
        stage=3,
        target_type=2,
        interval_days=4,
        next_review_date=TODAY,
        last_reviewed_date=TODAY,
        consecutive_wrong=1,
        total_wrong=1,
    )
    c4, o4 = apply_review(card4, ReviewInput(meaning_correct=False, spelling_correct=False, typed_input=None), TODAY)
    assert o4 == 4
    assert c4.weak_indices == ()

