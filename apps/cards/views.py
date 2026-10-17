"""Views for card management, Library browsing, and card CRUD actions (Step 8)."""
import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from apps.cards.models import WordCard
from apps.services.audio.resolver import schedule_audio_resolution


@login_required
@require_GET
def library_view(request: HttpRequest) -> HttpResponse:
    """
    Renders the Library view showing all flashcards for the current user.
    Supports search (word, meaning, lemma), stage/phase filters, no-meaning filter,
    suspended filter, and pagination.
    """
    user = request.user
    cards_qs = WordCard.objects.filter(user=user).select_related("source_text").order_by("-id")

    # Search filter
    query = request.GET.get("q", "").strip()
    if query:
        cards_qs = cards_qs.filter(
            Q(word__icontains=query)
            | Q(meaning__icontains=query)
            | Q(lemma__icontains=query)
        )

    # Stage filter (0 to 8)
    stage_param = request.GET.get("stage", "").strip()
    if stage_param != "" and stage_param.isdigit():
        stage_num = int(stage_param)
        if 0 <= stage_num <= 8:
            cards_qs = cards_qs.filter(stage=stage_num)

    # Phase filter
    phase_param = request.GET.get("phase", "").strip()
    if phase_param == "new":
        cards_qs = cards_qs.filter(stage=0)
    elif phase_param == "learning":
        cards_qs = cards_qs.filter(stage__in=[1, 2, 3])
    elif phase_param == "reviewing":
        cards_qs = cards_qs.filter(stage__in=[4, 5, 6, 7])
    elif phase_param == "mastered":
        cards_qs = cards_qs.filter(stage=8)

    # No-meaning filter
    no_meaning = request.GET.get("no_meaning", "").strip()
    if no_meaning in ("1", "true", "yes"):
        cards_qs = cards_qs.filter(Q(meaning="") | Q(meaning__isnull=True))

    # Suspended filter
    suspended_param = request.GET.get("suspended", "").strip()
    if suspended_param == "1":
        cards_qs = cards_qs.filter(is_suspended=True)
    elif suspended_param == "0":
        cards_qs = cards_qs.filter(is_suspended=False)

    # Stats for filter tabs
    total_count = WordCard.objects.filter(user=user).count()
    no_meaning_count = WordCard.objects.filter(
        user=user, meaning=""
    ).count()
    suspended_count = WordCard.objects.filter(user=user, is_suspended=True).count()

    # Pagination: 25 cards per page
    paginator = Paginator(cards_qs, 25)
    page_number = request.GET.get("page", 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    return render(
        request,
        "library/index.html",
        {
            "cards": page_obj,
            "page_obj": page_obj,
            "total_count": total_count,
            "no_meaning_count": no_meaning_count,
            "suspended_count": suspended_count,
            "query": query,
            "stage_param": stage_param,
            "phase_param": phase_param,
            "no_meaning": no_meaning,
            "suspended_param": suspended_param,
            "pos_choices": WordCard.POS_CHOICES,
            "title": "کتابخانه واژگان | Nightly Vocab",
        },
    )


@login_required
@require_POST
def edit_card_api(request: HttpRequest, card_id: int) -> JsonResponse:
    """
    Updates word details (word, lemma, pos, meaning, context_sentence).
    Secured: scoped to request.user.
    """
    card = get_object_or_404(WordCard, pk=card_id, user=request.user)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "فرمت داده‌ها نامعتبر است."}, status=400)

    word = data.get("word", "").strip()
    if not word:
        return JsonResponse({"error": "کلمه نمی‌تواند خالی باشد."}, status=400)

    lemma = data.get("lemma", "").strip()
    pos = data.get("pos", card.pos).strip()
    meaning = data.get("meaning", "").strip()
    context_sentence = data.get("context_sentence", card.context_sentence).strip()

    card.word = word
    card.lemma = lemma or word.lower()
    card.pos = pos
    card.meaning = meaning
    card.context_sentence = context_sentence
    card.save()

    return JsonResponse({
        "success": True,
        "card": {
            "id": card.id,
            "word": card.word,
            "lemma": card.lemma,
            "pos": card.get_pos_display(),
            "meaning": card.meaning,
            "context_sentence": card.context_sentence,
            "stage": card.stage,
        },
    })


@login_required
@require_POST
def toggle_suspend_card_api(request: HttpRequest, card_id: int) -> JsonResponse:
    """Toggles the is_suspended status of a card."""
    card = get_object_or_404(WordCard, pk=card_id, user=request.user)
    card.is_suspended = not card.is_suspended
    card.save(update_fields=["is_suspended"])

    return JsonResponse({
        "success": True,
        "is_suspended": card.is_suspended,
    })


@login_required
@require_POST
def reset_card_progress_api(request: HttpRequest, card_id: int) -> JsonResponse:
    """
    Resets card progress back to Stage 0, Target Type 1, clearing SRS intervals
    and wrong streaks.
    """
    card = get_object_or_404(WordCard, pk=card_id, user=request.user)
    card.stage = 0
    card.target_type = 1
    card.interval_days = 1
    card.next_review_date = None
    card.consecutive_wrong = 0
    card.weak_indices = []
    card.save()

    return JsonResponse({
        "success": True,
        "stage": card.stage,
        "target_type": card.target_type,
    })


@login_required
@require_POST
def delete_card_api(request: HttpRequest, card_id: int) -> JsonResponse:
    """Deletes a card permanently. Scoped to request.user."""
    card = get_object_or_404(WordCard, pk=card_id, user=request.user)
    card.delete()

    return JsonResponse({"success": True})


@login_required
@require_POST
def manual_add_card_api(request: HttpRequest) -> JsonResponse:
    """
    Allows user to add a flashcard manually without uploading a text.
    Validates word, POS, meaning, and context sentence.
    Triggers audio resolution asynchronously.
    """
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "فرمت داده‌ها نامعتبر است."}, status=400)

    word = data.get("word", "").strip()
    if not word:
        return JsonResponse({"error": "کلمه یا عبارت الزامی است."}, status=400)

    if len(word.split()) > 5:
        return JsonResponse({"error": "عبارت نمی‌تواند بیش از ۵ کلمه باشد."}, status=400)

    lemma = data.get("lemma", "").strip() or word.lower()
    pos = data.get("pos", "noun").strip()
    meaning = data.get("meaning", "").strip()
    sentence = data.get("context_sentence", "").strip() or word

    # If context sentence was provided, find word position or default
    ctx_start = sentence.lower().find(word.lower())
    if ctx_start >= 0:
        ctx_end = ctx_start + len(word)
    else:
        ctx_start = 0
        ctx_end = len(word)

    card = WordCard.objects.create(
        user=request.user,
        source_text=None,
        word=word,
        lemma=lemma,
        pos=pos,
        meaning=meaning,
        context_sentence=sentence,
        ctx_start=ctx_start,
        ctx_end=ctx_end,
        stage=0,
        target_type=1,
        next_review_date=None,
    )

    # Schedule background audio lookup
    schedule_audio_resolution([card.id])

    return JsonResponse({
        "success": True,
        "card_id": card.id,
    })
