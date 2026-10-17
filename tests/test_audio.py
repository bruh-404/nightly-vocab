"""Unit and integration tests for Audio Service (Step 7 / Section 7.2)."""
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.cards.models import WordCard
from apps.services.audio.cambridge import CambridgeNotConfigured, CambridgeProvider, NotConfigured
from apps.services.audio.free_dictionary import FreeDictionaryProvider
from apps.services.audio.resolver import (
    resolve_and_cache_audio,
    schedule_audio_resolution,
)

User = get_user_model()


@pytest.fixture
def test_user(db):
    user = User.objects.create_user(username="audiotester", email="audio@example.com")
    profile = user.profile
    profile.daily_limit = 20
    profile.enabled_card_types = [1, 2, 3]
    profile.accent = "uk"
    profile.save()
    return user


def test_cambridge_provider_raises_not_configured():
    """Cambridge provider is a stub and must raise CambridgeNotConfigured / NotConfigured."""
    provider = CambridgeProvider()
    with pytest.raises(CambridgeNotConfigured):
        provider.get_audio_urls("word")

    with pytest.raises(NotConfigured):
        provider.get_audio_urls("word")


def test_free_dictionary_skips_phrases_and_empty():
    """Phrases with spaces or empty strings skip network calls and return None."""
    provider = FreeDictionaryProvider()
    assert provider.get_audio_urls("") == {"uk": None, "us": None}
    assert provider.get_audio_urls("   ") == {"uk": None, "us": None}
    assert provider.get_audio_urls("safe and sound") == {"uk": None, "us": None}


@patch("httpx.Client.get")
def test_free_dictionary_success_parsing(mock_get):
    """Parses Free Dictionary API JSON, normalizes protocol-relative URLs, and classifies accents."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "word": "environment",
            "phonetics": [
                {
                    "text": "/ɪnˈvaɪ.rən.mənt/",
                    "audio": "//ssl.gstatic.com/dictionary/static/sounds/20200429/environment--_gb_1.mp3",
                },
                {
                    "text": "/ɪnˈvaɪ.rən.mənt/",
                    "audio": "https://api.dictionaryapi.dev/media/pronunciations/en/environment-us.mp3",
                },
            ],
        }
    ]
    mock_get.return_value = mock_resp

    provider = FreeDictionaryProvider()
    urls = provider.get_audio_urls("environment")

    assert urls["uk"] == "https://ssl.gstatic.com/dictionary/static/sounds/20200429/environment--_gb_1.mp3"
    assert urls["us"] == "https://api.dictionaryapi.dev/media/pronunciations/en/environment-us.mp3"


@patch("httpx.Client.get")
def test_free_dictionary_australian_fallback_and_generic(mock_get):
    """Australian pronunciation serves as fallback for UK if UK is missing."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "word": "harbour",
            "phonetics": [
                {
                    "audio": "https://api.dictionaryapi.dev/media/pronunciations/en/harbour-au.mp3",
                },
                {
                    "audio": "https://api.dictionaryapi.dev/media/pronunciations/en/harbour.mp3",
                },
            ],
        }
    ]
    mock_get.return_value = mock_resp

    provider = FreeDictionaryProvider()
    urls = provider.get_audio_urls("harbour")

    # -au matches UK fallback; generic matches US
    assert urls["uk"] == "https://api.dictionaryapi.dev/media/pronunciations/en/harbour-au.mp3"
    assert urls["us"] == "https://api.dictionaryapi.dev/media/pronunciations/en/harbour.mp3"


@patch("httpx.Client.get")
def test_free_dictionary_network_error_never_raises(mock_get):
    """Network errors or 404/500 never raise exceptions to caller and return None."""
    mock_get.side_effect = Exception("Connection timeout")

    provider = FreeDictionaryProvider()
    urls = provider.get_audio_urls("glitch")

    assert urls == {"uk": None, "us": None}


def test_resolver_skips_phrases(test_user):
    """Resolver skips phrase cards without calling API and marks audio_checked_at."""
    card = WordCard.objects.create(
        user=test_user,
        word="take for granted",
        context_sentence="Don't take for granted what you have.",
        ctx_start=6,
        ctx_end=22,
    )

    mock_provider = MagicMock()
    res = resolve_and_cache_audio(card.id, provider=mock_provider)

    mock_provider.get_audio_urls.assert_not_called()
    card.refresh_from_db()
    assert card.audio_checked_at is not None
    assert card.audio_url_uk == ""
    assert res == {"uk": None, "us": None}


def test_resolver_caches_single_word(test_user):
    """Resolver fetches audio for single word and caches into WordCard."""
    card = WordCard.objects.create(
        user=test_user,
        word="splendid",
        context_sentence="What a splendid day!",
        ctx_start=7,
        ctx_end=15,
    )

    mock_provider = MagicMock()
    mock_provider.get_audio_urls.return_value = {
        "uk": "https://audio.example.com/uk/splendid.mp3",
        "us": "https://audio.example.com/us/splendid.mp3",
    }

    res = resolve_and_cache_audio(card.id, provider=mock_provider)

    mock_provider.get_audio_urls.assert_called_once_with("splendid")
    card.refresh_from_db()
    assert card.audio_url_uk == "https://audio.example.com/uk/splendid.mp3"
    assert card.audio_url_us == "https://audio.example.com/us/splendid.mp3"
    assert card.audio_checked_at is not None
    assert res["uk"] == "https://audio.example.com/uk/splendid.mp3"


def test_resolver_respects_30_day_throttle(test_user):
    """Missing audio is not re-checked if checked less than 30 days ago."""
    two_weeks_ago = timezone.now() - timedelta(days=14)
    card = WordCard.objects.create(
        user=test_user,
        word="obscure",
        context_sentence="An obscure word.",
        ctx_start=3,
        ctx_end=10,
        audio_checked_at=two_weeks_ago,
    )

    mock_provider = MagicMock()
    res = resolve_and_cache_audio(card.id, provider=mock_provider)

    # Within 30 days, provider should NOT be called
    mock_provider.get_audio_urls.assert_not_called()
    assert res == {"uk": None, "us": None}


def test_resolver_rechecks_after_30_days(test_user):
    """Missing audio is re-checked if last check was more than 30 days ago."""
    thirty_five_days_ago = timezone.now() - timedelta(days=35)
    card = WordCard.objects.create(
        user=test_user,
        word="resilience",
        context_sentence="The resilience was tested.",
        ctx_start=4,
        ctx_end=14,
        audio_checked_at=thirty_five_days_ago,
    )

    mock_provider = MagicMock()
    mock_provider.get_audio_urls.return_value = {
        "uk": "https://audio.example.com/uk/resilience.mp3",
        "us": None,
    }

    res = resolve_and_cache_audio(card.id, provider=mock_provider)

    mock_provider.get_audio_urls.assert_called_once_with("resilience")
    card.refresh_from_db()
    assert card.audio_url_uk == "https://audio.example.com/uk/resilience.mp3"
    assert res["uk"] == "https://audio.example.com/uk/resilience.mp3"


def test_resolver_lemma_fallback(test_user):
    """If surface word yields no audio, resolver tries the lemma."""
    card = WordCard.objects.create(
        user=test_user,
        word="running",
        lemma="run",
        context_sentence="He was running fast.",
        ctx_start=7,
        ctx_end=14,
    )

    mock_provider = MagicMock()
    # "running" yields nothing, "run" yields audio
    def fake_lookup(term):
        if term == "running":
            return {"uk": None, "us": None}
        if term == "run":
            return {"uk": "https://audio.example.com/uk/run.mp3", "us": "https://audio.example.com/us/run.mp3"}
        return {"uk": None, "us": None}

    mock_provider.get_audio_urls.side_effect = fake_lookup

    res = resolve_and_cache_audio(card.id, provider=mock_provider)

    card.refresh_from_db()
    assert card.audio_url_uk == "https://audio.example.com/uk/run.mp3"
    assert res["uk"] == "https://audio.example.com/uk/run.mp3"


def test_schedule_audio_resolution_handles_empty_list():
    """schedule_audio_resolution safely accepts empty list without crashing."""
    schedule_audio_resolution([])


def test_review_session_api_accent_preference(client, test_user):
    """Review session selects preferred audio based on profile.accent ('uk')."""
    client.force_login(test_user)

    WordCard.objects.create(
        user=test_user,
        word="accented",
        context_sentence="An accented word.",
        ctx_start=3,
        ctx_end=11,
        stage=1,
        target_type=1,
        next_review_date=test_user.profile.get_local_date(),
        audio_url_uk="https://audio.example.com/uk.mp3",
        audio_url_us="https://audio.example.com/us.mp3",
    )

    resp = client.get("/api/review/session/")
    assert resp.status_code == 200
    data = resp.json()
    card_data = data["cards"][0]

    # test_user has accent='uk', so audio_url must be the UK URL
    assert card_data["audio_url"] == "https://audio.example.com/uk.mp3"
    assert card_data["audio_url_uk"] == "https://audio.example.com/uk.mp3"
    assert card_data["audio_url_us"] == "https://audio.example.com/us.mp3"
    assert card_data["accent"] == "uk"

    # Now switch accent to US
    test_user.profile.accent = "us"
    test_user.profile.save()

    resp2 = client.get("/api/review/session/")
    card_data2 = resp2.json()["cards"][0]
    assert card_data2["audio_url"] == "https://audio.example.com/us.mp3"
    assert card_data2["accent"] == "us"


def test_check_spelling_api_returns_audio(client, test_user):
    """Spelling check API response includes audio info for the revealed card."""
    client.force_login(test_user)

    card = WordCard.objects.create(
        user=test_user,
        word="beacon",
        meaning="فانوس دریایی",
        context_sentence="A shining beacon in the dark.",
        ctx_start=10,
        ctx_end=16,
        stage=3,
        target_type=2,
        next_review_date=test_user.profile.get_local_date(),
        audio_url_uk="https://audio.example.com/beacon-uk.mp3",
    )

    resp = client.post(
        "/api/review/check/",
        data={"card_id": card.id, "typed_input": "beacon"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["spelling_correct"] is True
    assert data["audio_url"] == "https://audio.example.com/beacon-uk.mp3"
    assert data["audio_url_uk"] == "https://audio.example.com/beacon-uk.mp3"
    assert data["accent"] == "uk"
