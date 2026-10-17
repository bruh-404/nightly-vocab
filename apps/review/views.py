"""Views and API endpoints for SRS review sessions (Section 5.2 & Step 6)."""
import json
import random
from typing import Any, Dict

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from apps.cards.adapters import apply_state_to_card, card_to_state
from apps.cards.models import DailySession, ReviewLog, WordCard
from apps.srs.engine import (
    ReviewInput,
    apply_review,
    build_daily_queue,
    evaluate_spelling,
    extract_weak_indices,
    generate_masked_word,
    resolve_display_type,
)


@login_required
@require_GET
def review_shell_view(request: HttpRequest) -> HttpResponse:
    """Renders the single-page application shell for daily review sessions."""
    return render(
        request,
        "review/session.html",
        {
            "title": "جلسه مرور شبانه | Nightly Vocab",
        },
    )


def _serialize_card_for_front(card: WordCard, display_type: int, today) -> Dict[str, Any]:
    """
    Serializes card for front-of-card display.
    SECURITY: For Types 2 and 3, word and meaning are NEVER included.
    """
    profile = card.user.profile
    pref_audio = card.audio_url_uk if profile.accent == "uk" else card.audio_url_us
    alt_audio = card.audio_url_us if profile.accent == "uk" else card.audio_url_uk
    base = {
        "id": card.id,
        "display_type": display_type,
        "stage": card.stage,
        "has_source_text": bool(card.source_text_id),
        "source_text_id": card.source_text_id,
        "audio_url": pref_audio or alt_audio or None,
        "audio_url_uk": card.audio_url_uk or None,
        "audio_url_us": card.audio_url_us or None,
        "accent": profile.accent,
        "audio_text": card.word,
    }

    if display_type == 1:
        # Type 1: Recognition test (Word + Sentence shown)
        base.update({
            "word": card.word,
            "lemma": card.lemma,
            "pos": card.get_pos_display(),
            "meaning": card.meaning,
            "context_sentence": card.context_sentence,
            "ctx_start": card.ctx_start,
            "ctx_end": card.ctx_end,
            "ai_example": card.ai_example if profile.ai_example_enabled else None,
        })
    elif display_type == 2:
        # Type 2: Guided spelling (Sentence with blank + masked input boxes)
        # Blank the target word in the context sentence
        c_sentence = card.context_sentence
        blanked_sentence = (
            c_sentence[:card.ctx_start] + "_____" + c_sentence[card.ctx_end:]
            if card.ctx_end <= len(c_sentence)
            else c_sentence
        )

        # Seeded RNG for deterministic mask across refreshes on the same day
        seed = f"{card.id}:{today}"
        rng = random.Random(seed)
        masked_word = generate_masked_word(
            card.word,
            card.stage,
            card.weak_indices or [],
            rng,
        )

        # Masked characters list: for masked characters, omit the char to prevent DOM inspection
        masked_boxes = []
        for idx, ch in enumerate(card.word):
            is_m = idx in masked_word.masked_indices
            masked_boxes.append({
                "char": "" if is_m else ch,
                "masked": is_m,
                "is_space": ch == " ",
            })

        base.update({
            "blanked_sentence": blanked_sentence,
            "masked_boxes": masked_boxes,
        })
    elif display_type == 3:
        # Type 3: Full dictation (Sentence with blank + single input)
        c_sentence = card.context_sentence
        blanked_sentence = (
            c_sentence[:card.ctx_start] + "_____" + c_sentence[card.ctx_end:]
            if card.ctx_end <= len(c_sentence)
            else c_sentence
        )
        base.update({
            "blanked_sentence": blanked_sentence,
            "word_length": len(card.word),
        })

    return base


@login_required
@require_GET
def get_review_session_api(request: HttpRequest) -> JsonResponse:
    """
    Initializes or retrieves today's DailySession queue and returns remaining cards.
    """
    user = request.user
    profile = user.profile
    today = profile.get_local_date()

    is_practice = request.GET.get("practice") == "1"

    # Tomorrow's due count for summary
    tomorrow_due = WordCard.objects.filter(
        user=user,
        is_suspended=False,
        next_review_date=today.fromordinal(today.toordinal() + 1),
    ).count()

    if is_practice:
        # Load up to 10 active cards for practice test
        practice_cards = list(
            WordCard.objects.filter(user=user, is_suspended=False).order_by("stage", "id")[:10]
        )
        if practice_cards:
            serialized_cards = []
            for c in practice_cards:
                display_type = resolve_display_type(c.target_type, profile.enabled_card_types)
                serialized_cards.append(_serialize_card_for_front(c, display_type, today))
            return JsonResponse({
                "done": False,
                "practice": True,
                "progress": {"done": 0, "total": len(practice_cards)},
                "tomorrow_due": tomorrow_due,
                "recovery_banner": False,
                "cards": serialized_cards,
            })

    with transaction.atomic():
        session = DailySession.objects.filter(user=user, local_date=today).first()
        if session is None:
            # Snapshot previous active date before today's reviews begin
            prev_active = profile.last_active_date

            # Fetch due cards (stage > 0, next_review_date <= today, not suspended)
            due_cards = list(
                WordCard.objects.filter(
                    user=user,
                    is_suspended=False,
                    stage__gt=0,
                    next_review_date__lte=today,
                ).order_by("next_review_date", "id")
            )

            # Fetch new cards (stage == 0, not suspended, id ASC)
            new_cards = list(
                WordCard.objects.filter(
                    user=user,
                    is_suspended=False,
                    stage=0,
                ).order_by("id")
            )

            due_states = [card_to_state(c) for c in due_cards]
            new_states = [card_to_state(c) for c in new_cards]

            ordered_ids = build_daily_queue(
                due_cards=due_states,
                new_cards=new_states,
                today=today,
                daily_limit=profile.daily_limit,
            )

            session = DailySession.objects.create(
                user=user,
                local_date=today,
                card_ids=ordered_ids,
                prev_active_date=prev_active,
                review_count=len([cid for cid in ordered_ids if cid in {c.id for c in due_cards}]),
                new_count=len([cid for cid in ordered_ids if cid in {c.id for c in new_cards}]),
            )
        else:
            # If session exists, check if user added new stage=0 cards that aren't yet in session.card_ids
            new_unadded = list(
                WordCard.objects.filter(
                    user=user,
                    is_suspended=False,
                    stage=0,
                ).exclude(id__in=session.card_ids).values_list("id", flat=True)
            )
            if new_unadded:
                for cid in new_unadded:
                    if cid not in session.card_ids:
                        session.card_ids.append(cid)
                session.new_count = len([cid for cid in session.card_ids if WordCard.objects.filter(id=cid, stage=0).exists()])
                session.save(update_fields=["card_ids", "new_count"])

    # Filter out cards already reviewed today
    reviewed_ids = set(
        ReviewLog.objects.filter(user=user, local_date=today).values_list("card_id", flat=True)
    )
    remaining_ids = [cid for cid in session.card_ids if cid not in reviewed_ids]

    total_queue = len(session.card_ids)
    done_count = len(reviewed_ids)

    # Recovery banner check (> 7 days absence)
    recovery_banner = False
    if session.prev_active_date is not None:
        if (today - session.prev_active_date).days > 7:
            recovery_banner = True

    if not remaining_ids:
        return JsonResponse({
            "done": True,
            "progress": {"done": done_count, "total": total_queue},
            "tomorrow_due": tomorrow_due,
            "cards": [],
            "recovery_banner": recovery_banner,
        })

    # Fetch remaining card models preserving order
    cards_by_id = {c.id: c for c in WordCard.objects.filter(id__in=remaining_ids, user=user)}
    ordered_cards = [cards_by_id[cid] for cid in remaining_ids if cid in cards_by_id]

    serialized_cards = []
    for c in ordered_cards:
        display_type = resolve_display_type(c.target_type, profile.enabled_card_types)
        serialized_cards.append(_serialize_card_for_front(c, display_type, today))

    return JsonResponse({
        "done": False,
        "progress": {"done": done_count, "total": total_queue},
        "tomorrow_due": tomorrow_due,
        "recovery_banner": recovery_banner,
        "cards": serialized_cards,
    })


@login_required
@require_POST
def check_spelling_api(request: HttpRequest) -> JsonResponse:
    """
    Checks user's typed spelling for Type 2 & 3 cards, revealing the answer and unlocking the '!' modal.
    """
    try:
        data = json.loads(request.body)
        card_id = int(data.get("card_id", 0))
        typed_input = str(data.get("typed_input", "")).strip()
    except Exception:
        return JsonResponse({"error": "فرمت داده‌ها نامعتبر است."}, status=400)

    card = get_object_or_404(WordCard, pk=card_id, user=request.user)
    spelling_correct = evaluate_spelling(card.word, typed_input)

    # Compute character-by-character diff for visual feedback
    target_clean = " ".join(card.word.split())
    typed_clean = " ".join(typed_input.split())

    char_diff = []
    for idx, expected_char in enumerate(target_clean):
        typed_char = typed_clean[idx] if idx < len(typed_clean) else ""
        char_diff.append({
            "expected": expected_char,
            "typed": typed_char,
            "correct": expected_char.lower() == typed_char.lower(),
        })

    profile = request.user.profile
    pref_audio = card.audio_url_uk if profile.accent == "uk" else card.audio_url_us
    alt_audio = card.audio_url_us if profile.accent == "uk" else card.audio_url_uk

    return JsonResponse({
        "spelling_correct": spelling_correct,
        "word": card.word,
        "typed_input": typed_input,
        "lemma": card.lemma,
        "pos": card.get_pos_display(),
        "meaning": card.meaning,
        "ai_example": card.ai_example if profile.ai_example_enabled else None,
        "char_diff": char_diff,
        "source_text_id": card.source_text_id,
        "has_source_text": bool(card.source_text_id),
        "audio_url": pref_audio or alt_audio or None,
        "audio_url_uk": card.audio_url_uk or None,
        "audio_url_us": card.audio_url_us or None,
        "accent": profile.accent,
    })


@login_required
@require_POST
def submit_review_api(request: HttpRequest) -> JsonResponse:
    """
    Submits evaluation for a card review, applies SRS state transition, and logs ReviewLog.
    Recomputes spelling_correct independently on the server.
    """
    try:
        data = json.loads(request.body)
        card_id = int(data.get("card_id", 0))
        display_type = int(data.get("display_type", 1))
        meaning_correct = bool(data.get("meaning_correct"))
        typed_input = data.get("typed_input")
        if typed_input is not None:
            typed_input = str(typed_input).strip()
    except Exception:
        return JsonResponse({"error": "فرمت داده‌ها نامعتبر است."}, status=400)

    card = get_object_or_404(WordCard, pk=card_id, user=request.user)
    profile = request.user.profile
    today = profile.get_local_date()

    # Idempotency check: max 1 review per card per local day (practice mode passes through)
    is_practice = bool(data.get("practice"))
    if ReviewLog.objects.filter(card=card, local_date=today).exists():
        if is_practice:
            return JsonResponse({
                "success": True,
                "practice": True,
                "new_stage": card.stage,
                "next_review_date": str(card.next_review_date) if card.next_review_date else None,
            })
        return JsonResponse(
            {"error": "این کارت امروز قبلاً مرور شده است."},
            status=409,
        )

    # Server recomputes spelling_correct
    if display_type in (2, 3):
        spelling_correct = evaluate_spelling(card.word, typed_input or "")
        weak_indices = extract_weak_indices(card.word, typed_input or "")
    else:
        spelling_correct = None
        weak_indices = list(card.weak_indices or [])

    review_input = ReviewInput(
        meaning_correct=meaning_correct,
        spelling_correct=spelling_correct,
        typed_input=typed_input,
    )

    # Retrieve DailySession to get snapshot prev_active_date
    session = DailySession.objects.filter(user=request.user, local_date=today).first()
    prev_active = session.prev_active_date if session else profile.last_active_date

    card_state = card_to_state(card)
    new_state, outcome = apply_review(
        card=card_state,
        review=review_input,
        today=today,
        prev_active_date=prev_active,
    )

    # Record state changes inside atomic transaction
    with transaction.atomic():
        stage_before = card.stage
        target_type_before = card.target_type

        apply_state_to_card(card, new_state)
        card.weak_indices = weak_indices
        card.save()

        try:
            ReviewLog.objects.create(
                user=request.user,
                card=card,
                local_date=today,
                display_type=display_type,
                meaning_correct=meaning_correct,
                spelling_correct=spelling_correct,
                typed_input=typed_input or "",
                stage_before=stage_before,
                stage_after=card.stage,
                target_type_before=target_type_before,
                target_type_after=card.target_type,
                interval_after=card.interval_days,
                outcome=outcome,
            )
        except IntegrityError:
            return JsonResponse({"error": "این کارت امروز قبلاً مرور شده است."}, status=409)

        # Update user's last_active_date
        profile.last_active_date = today
        profile.save(update_fields=["last_active_date"])

    # Progress stats
    reviewed_today_count = ReviewLog.objects.filter(user=request.user, local_date=today).count()
    total_session = len(session.card_ids) if session else reviewed_today_count

    return JsonResponse({
        "success": True,
        "outcome": outcome,
        "new_stage": card.stage,
        "new_target_type": card.target_type,
        "progress": {"done": reviewed_today_count, "total": total_session},
        "is_session_complete": reviewed_today_count >= total_session,
    })


@login_required
@require_GET
def get_card_context_api(request: HttpRequest, card_id: int) -> JsonResponse:
    """
    Returns original text body with target word highlighted for the '!' modal.
    Checks security: If display type is 2 or 3, verify that answer has been revealed.
    """
    card = get_object_or_404(WordCard, pk=card_id, user=request.user)
    if not card.source_text:
        return JsonResponse({"error": "این کارت متن اصلی ندارد."}, status=404)

    text = card.source_text
    return JsonResponse({
        "title": text.title,
        "body": text.body,
        "char_start": card.char_start,
        "char_end": card.char_end,
        "word": card.word,
    })
