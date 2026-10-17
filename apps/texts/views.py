"""Views for text management, tokenized selection, and card creation."""
import json
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.cards.models import WordCard
from apps.services.ai.access import (
    AiDenied,
    record_ai_tokens,
    release_ai_reservation_on_failure,
    reserve_ai_call,
    resolve_ai_source,
)
from apps.services.ai.gemini import GeminiAIError, GeminiProvider
from apps.services.ai.schemas import Target
from apps.services.audio.resolver import schedule_audio_resolution

from apps.cards.verbs import format_verb_meaning, get_irregular_verb_info, lemmatize_word
from .models import Text
from .tokenizer import extract_sentence_for_span, tokenize_text


@login_required
@require_GET
def text_list_view(request: HttpRequest) -> HttpResponse:
    """Displays the list of texts entered by the user."""
    texts = Text.objects.filter(user=request.user).prefetch_related("cards")
    return render(
        request,
        "texts/text_list.html",
        {
            "texts": texts,
            "title": "متن‌های من | Nightly Vocab",
        },
    )


@login_required
def text_create_view(request: HttpRequest) -> HttpResponse:
    """View to paste a new nightly text and start selection."""
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        body = request.POST.get("body", "").strip()

        if not body:
            return render(
                request,
                "texts/text_create.html",
                {
                    "error": "لطفاً متن انگلیسی را وارد کنید.",
                    "title_val": title,
                    "body_val": body,
                },
            )

        text = Text(user=request.user, title=title, body=body)
        text.save()
        return redirect("texts:select", text_id=text.id)

    return render(
        request,
        "texts/text_create.html",
        {
            "title": "ورود متن جدید | Nightly Vocab",
        },
    )


@login_required
@require_GET
def text_detail_view(request: HttpRequest, text_id: int) -> HttpResponse:
    """Displays text detail with already-saved words highlighted."""
    text = get_object_or_404(Text, pk=text_id, user=request.user)
    saved_cards = list(text.cards.all())

    # Build highlighted text representation using character spans safely
    # Sort cards by char_start to avoid overlap collisions
    sorted_cards = sorted(
        [c for c in saved_cards if c.char_start is not None and c.char_end is not None],
        key=lambda c: c.char_start,
    )

    rendered_segments = []
    last_idx = 0
    for card in sorted_cards:
        if card.char_start >= last_idx:
            # Plain text before card
            rendered_segments.append(
                {"type": "plain", "content": text.body[last_idx : card.char_start]}
            )
            # Saved card token
            rendered_segments.append(
                {
                    "type": "card",
                    "content": text.body[card.char_start : card.char_end],
                    "card": card,
                }
            )
            last_idx = card.char_end

    if last_idx < len(text.body):
        rendered_segments.append(
            {"type": "plain", "content": text.body[last_idx:]}
        )

    return render(
        request,
        "texts/text_detail.html",
        {
            "text": text,
            "segments": rendered_segments,
            "saved_cards": saved_cards,
            "title": f"{text.title} | Nightly Vocab",
        },
    )


@login_required
@require_GET
def text_select_view(request: HttpRequest, text_id: int) -> HttpResponse:
    """
    Renders tokenized interactive reading view for word & phrase selection.
    Tokens are wrapped in <span class="tok">; whitespace and punctuation are plain text nodes.
    Marks already-saved cards so user clearly sees previously extracted words.
    """
    import re

    text = get_object_or_404(Text, pk=text_id, user=request.user)
    tokens = tokenize_text(text.body)

    # Fetch existing cards for this text
    saved_cards = list(WordCard.objects.filter(user=request.user, source_text=text))
    for card in saved_cards:
        if card.char_start is None or card.char_end is None:
            pattern = re.compile(r"\b" + re.escape(card.word) + r"\b", re.IGNORECASE)
            m = pattern.search(text.body)
            if m:
                card.char_start = m.start()
                card.char_end = m.end()
                card.save(update_fields=["char_start", "char_end"])

    saved_intervals = [
        (c.char_start, c.char_end, c)
        for c in saved_cards
        if c.char_start is not None and c.char_end is not None
    ]

    # Build segments list: interleave plain text and token objects
    segments = []
    last_idx = 0
    for tok in tokens:
        if tok.start > last_idx:
            segments.append({"type": "plain", "text": text.body[last_idx : tok.start]})

        matching_card = None
        for s_start, s_end, c in saved_intervals:
            if tok.start >= s_start and tok.end <= s_end:
                matching_card = c
                break

        segments.append({
            "type": "token",
            "tok": tok,
            "is_saved": matching_card is not None,
            "saved_card": matching_card,
        })
        last_idx = tok.end

    if last_idx < len(text.body):
        segments.append({"type": "plain", "text": text.body[last_idx:]})

    profile = request.user.profile
    return render(
        request,
        "texts/text_select.html",
        {
            "text": text,
            "segments": segments,
            "saved_cards": saved_cards,
            "ai_example_enabled": profile.ai_example_enabled,
            "pos_choices": WordCard.POS_CHOICES,
            "title": f"انتخاب کلمات — {text.title}",
        },
    )


@login_required
@require_POST
def save_cards_api(request: HttpRequest, text_id: int) -> JsonResponse:
    """
    API endpoint to save selected words/phrases as WordCard entries.
    Validates spans, ensures max 5 words, extracts sentence context.
    Safely upserts if a card already exists at the span.
    """
    text = get_object_or_404(Text, pk=text_id, user=request.user)

    try:
        data = json.loads(request.body)
        items = data.get("cards", [])
    except Exception:
        return JsonResponse({"error": "فرمت داده‌های ورودی نامعتبر است."}, status=400)

    if not items or not isinstance(items, list):
        return JsonResponse({"error": "هیچ کلمه‌ای برای ذخیره ارسال نشده است."}, status=400)

    if len(items) > 30:
        return JsonResponse({"error": "حداکثر ۳۰ کلمه در هر درخواست قابل ذخیره است."}, status=400)

    created_cards = []
    for item in items:
        start = item.get("start")
        end = item.get("end")
        pos = item.get("pos", "noun").strip()
        meaning = item.get("meaning", "").strip()

        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end > len(text.body) or start >= end:
            return JsonResponse({"error": "مختصات کلمه در متن نامعتبر است."}, status=400)

        marked_text = text.body[start:end]
        words_in_span = marked_text.split()
        if len(words_in_span) > 5:
            return JsonResponse(
                {"error": f"عبارت «{marked_text}» بیش از ۵ کلمه است ({len(words_in_span)} کلمه)."},
                status=400,
            )

        # Normalize collapsed whitespace
        normalized_word = " ".join(words_in_span)

        # Sentence extraction
        sentence, ctx_start, ctx_end = extract_sentence_for_span(text.body, start, end)

        raw_lemma = item.get("lemma", "").strip()
        is_noun_or_verb = (pos or "").lower() in ("noun", "verb")
        if is_noun_or_verb:
            lemma = raw_lemma or lemmatize_word(normalized_word, pos)
            card_word = lemma if lemma and len(normalized_word.split()) == 1 else normalized_word
        else:
            lemma = normalized_word
            card_word = normalized_word
        formatted_meaning = format_verb_meaning(meaning, lemma or normalized_word, pos)
        ai_example = item.get("example", "").strip() if item.get("example") else ""

        # Upsert: If card exists for this text & span or by card_id, update it
        card_id = item.get("card_id")
        existing_card = None
        if card_id:
            existing_card = WordCard.objects.filter(user=request.user, id=card_id).first()
        if not existing_card:
            existing_card = WordCard.objects.filter(
                user=request.user,
                source_text=text,
                char_start=start,
                char_end=end,
            ).first()

        if existing_card:
            existing_card.word = card_word
            existing_card.pos = pos
            existing_card.meaning = formatted_meaning
            if lemma:
                existing_card.lemma = lemma
            if ai_example:
                existing_card.ai_example = ai_example
            existing_card.save()
            created_cards.append(existing_card.id)
            continue

        try:
            card = WordCard(
                user=request.user,
                source_text=text,
                word=card_word,
                lemma=lemma,
                pos=pos,
                meaning=formatted_meaning,
                ai_example=ai_example,
                context_sentence=sentence,
                ctx_start=ctx_start,
                ctx_end=ctx_end,
                char_start=start,
                char_end=end,
                stage=0,
                target_type=1,
                next_review_date=None,
            )
            card.save()
            created_cards.append(card.id)
        except Exception as exc:
            return JsonResponse({"error": f"خطا در ذخیره واژه «{normalized_word}»: {exc}"}, status=400)

    # Schedule non-blocking background audio resolution for newly created cards
    schedule_audio_resolution(created_cards)

    # Immediately include newly created cards into today's DailySession queue
    try:
        from apps.cards.models import DailySession
        today = request.user.profile.get_local_date()
        session = DailySession.objects.filter(user=request.user, local_date=today).first()
        if session:
            for cid in created_cards:
                if cid not in session.card_ids:
                    session.card_ids.append(cid)
            session.new_count = len([cid for cid in session.card_ids if WordCard.objects.filter(id=cid, stage=0).exists()])
            session.save(update_fields=["card_ids", "new_count"])
    except Exception:
        pass

    return JsonResponse({
        "success": True,
        "saved_count": len(created_cards),
        "card_ids": created_cards,
    })


@login_required
@require_POST
def analyze_text_api(request: HttpRequest, text_id: int) -> JsonResponse:
    """
    Analyzes selected words/phrases in context using AI (Section 7.1 & Patch B).
    Respects rate limits, BYOK resolution, and supports graceful fallback.
    """
    text = get_object_or_404(Text, pk=text_id, user=request.user)

    try:
        data = json.loads(request.body)
        raw_targets = data.get("targets", [])
        want_example = bool(data.get("want_example", False))
    except Exception:
        return JsonResponse({"error": "فرمت داده‌های ارسالی نامعتبر است."}, status=400)

    if not raw_targets or not isinstance(raw_targets, list):
        return JsonResponse({"error": "هیچ کلمه‌ای برای تحلیل انتخاب نشده است."}, status=400)

    if len(raw_targets) > 30:
        return JsonResponse({"error": "حداکثر ۳۰ کلمه در هر درخواست قابل تحلیل است."}, status=400)

    # Validate spans
    target_objs = []
    validated_spans = []
    for i, t in enumerate(raw_targets):
        start = t.get("start")
        end = t.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end > len(text.body) or start >= end:
            return JsonResponse({"error": "مختصات کلمه در متن نامعتبر است."}, status=400)

        marked_text = text.body[start:end]
        words_in_span = marked_text.split()
        if len(words_in_span) > 5:
            return JsonResponse({"error": f"عبارت «{marked_text}» بیش از ۵ کلمه است."}, status=400)

        # Context window (~80 chars each side)
        w_start = max(0, start - 80)
        w_end = min(len(text.body), end + 80)
        context_window = f"{text.body[w_start:start]}[[{marked_text}]]{text.body[end:w_end]}"

        target_objs.append(Target(index=i + 1, surface=marked_text, context_window=context_window))
        validated_spans.append((start, end, marked_text))

    # Check for overlaps
    sorted_spans = sorted(validated_spans, key=lambda s: s[0])
    for j in range(len(sorted_spans) - 1):
        if sorted_spans[j][1] > sorted_spans[j + 1][0]:
            return JsonResponse({"error": "کلمات انتخاب‌شده نباید همپوشانی داشته باشند."}, status=400)

    # Resolve AI access & quota
    try:
        res = resolve_ai_source(request.user, num_targets=len(target_objs))
    except AiDenied as exc:
        status_code = 429 if "limit" in exc.reason else 403
        return JsonResponse({"error": exc.user_message, "code": exc.reason}, status=status_code)

    # Reserve call atomically
    try:
        usage = reserve_ai_call(request.user, source=res.source, today=date.today(), max_limit=res.daily_limit)
    except AiDenied as exc:
        return JsonResponse({"error": exc.user_message, "code": exc.reason}, status=429)

    # Execute AI request with GeminiProvider
    provider = GeminiProvider(timeout=30.0)
    try:
        result = provider.analyze(
            text=text.body,
            targets=target_objs,
            want_example=want_example,
            api_key=res.api_key,
            model=res.model,
        )
        record_ai_tokens(usage.id, result.input_tokens, result.output_tokens)
    except GeminiAIError as exc:
        release_ai_reservation_on_failure(usage.id)
        return JsonResponse({
            "error": "سرویس هوش مصنوعی در دسترس نیست یا سهمیه تمام شده است. می‌توانید معانی را دستی وارد کنید.",
            "detail": str(exc),
            "fallback": True,
        }, status=503)
    except Exception as exc:
        release_ai_reservation_on_failure(usage.id)
        return JsonResponse({
            "error": "خطای غیرمنتظره در ارتباط با هوش مصنوعی. لطفاً معانی را دستی وارد کنید.",
            "detail": str(exc),
            "fallback": True,
        }, status=500)

    # Map output
    response_items = []
    for (start, end, surface), item in zip(validated_spans, result.items, strict=False):
        is_noun_or_verb = (item.pos or "").lower() in ("noun", "verb")
        if is_noun_or_verb:
            lemma = item.lemma.strip() if item.lemma else lemmatize_word(surface, item.pos)
        else:
            lemma = surface
        meaning = format_verb_meaning(item.meaning_fa, lemma, item.pos)
        response_items.append({
            "start": start,
            "end": end,
            "word": surface,
            "lemma": lemma,
            "pos": item.pos,
            "meaning": meaning,
            "example": item.example_en,
        })

    return JsonResponse({
        "success": True,
        "items": response_items,
        "source": res.source,
    })


@login_required
@require_POST
def text_delete_api(request: HttpRequest, text_id: int) -> JsonResponse:
    """
    Deletes a text owned by the user.
    If `delete_cards` is True, deletes all associated word cards as well.
    Otherwise, associated cards are preserved (source_text is detached).
    """
    text = get_object_or_404(Text, pk=text_id, user=request.user)

    try:
        data = json.loads(request.body) if request.body else {}
    except Exception:
        data = request.POST

    delete_cards = bool(data.get("delete_cards", False))

    cards_count = text.cards.count()
    if delete_cards:
        text.cards.all().delete()
        text.delete()
        msg = f"متن و {cards_count} لغت مرتبط با آن با موفقیت حذف شدند."
    else:
        text.delete()
        msg = f"متن با موفقیت حذف شد ({cards_count} لغت در سیستم یادگیری شما حفظ شدند)."

    return JsonResponse({
        "success": True,
        "message": msg,
        "redirect": "/texts/",
    })

