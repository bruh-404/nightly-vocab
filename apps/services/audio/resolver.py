"""Audio resolver service: fetches and caches audio URLs for cards (Section 7.2)."""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Dict, List, Optional, Sequence

from django.db import close_old_connections
from django.utils import timezone

from apps.cards.models import WordCard
from apps.services.audio.free_dictionary import FreeDictionaryProvider

logger = logging.getLogger(__name__)

# Dedicated thread pool for non-blocking background audio lookups
_audio_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="audio_resolver")


def resolve_and_cache_audio(
    card_id: int,
    provider: Optional[FreeDictionaryProvider] = None,
) -> Dict[str, Optional[str]]:
    """
    Resolves human audio pronunciation for a WordCard and caches it in the database.
    - Single words only (phrases containing whitespace skip API lookup).
    - Throttles lookups: re-checks missing audio at most once every 30 days.
    - Updates `audio_url_uk`, `audio_url_us`, and `audio_checked_at`.
    """
    card = WordCard.objects.filter(pk=card_id).first()
    if not card:
        return {"uk": None, "us": None}

    clean_word = card.word.strip()

    # Phrases skip lookup; browser TTS will be used
    if not clean_word or " " in clean_word:
        card.audio_checked_at = timezone.now()
        card.save(update_fields=["audio_checked_at"])
        return {
            "uk": card.audio_url_uk or None,
            "us": card.audio_url_us or None,
        }

    now = timezone.now()

    # Check 30-day throttle if already checked
    if card.audio_checked_at:
        elapsed = now - card.audio_checked_at
        # If both audio URLs exist, never re-fetch
        if card.audio_url_uk and card.audio_url_us:
            return {"uk": card.audio_url_uk, "us": card.audio_url_us}
        # If checked within the last 30 days, skip re-check
        if elapsed < timedelta(days=30):
            return {
                "uk": card.audio_url_uk or None,
                "us": card.audio_url_us or None,
            }

    api_provider = provider or FreeDictionaryProvider()

    # First try the surface word, then lemma if different and clean
    lookup_word = clean_word
    urls = api_provider.get_audio_urls(lookup_word)

    if not urls.get("uk") and not urls.get("us") and card.lemma:
        clean_lemma = card.lemma.strip()
        if clean_lemma and clean_lemma.lower() != clean_word.lower() and " " not in clean_lemma:
            lemma_urls = api_provider.get_audio_urls(clean_lemma)
            if lemma_urls.get("uk") or lemma_urls.get("us"):
                urls = lemma_urls

    updated_fields = ["audio_checked_at"]
    card.audio_checked_at = now

    if urls.get("uk") and not card.audio_url_uk:
        card.audio_url_uk = urls["uk"]
        updated_fields.append("audio_url_uk")
    elif urls.get("uk"):
        card.audio_url_uk = urls["uk"]
        if "audio_url_uk" not in updated_fields:
            updated_fields.append("audio_url_uk")

    if urls.get("us") and not card.audio_url_us:
        card.audio_url_us = urls["us"]
        updated_fields.append("audio_url_us")
    elif urls.get("us"):
        card.audio_url_us = urls["us"]
        if "audio_url_us" not in updated_fields:
            updated_fields.append("audio_url_us")

    card.save(update_fields=updated_fields)

    return {
        "uk": card.audio_url_uk or None,
        "us": card.audio_url_us or None,
    }


def _worker_resolve_cards(card_ids: List[int]) -> None:
    """Worker function executed in background thread."""
    close_old_connections()
    try:
        for cid in card_ids:
            try:
                resolve_and_cache_audio(cid)
            except Exception as exc:
                logger.warning("Background audio resolution failed for card %s: %s", cid, exc)
    finally:
        close_old_connections()


def schedule_audio_resolution(card_ids: Sequence[int]) -> None:
    """
    Schedules background audio resolution for the given list of card IDs
    using the ThreadPoolExecutor.
    """
    ids = list(card_ids)
    if not ids:
        return
    _audio_executor.submit(_worker_resolve_cards, ids)
