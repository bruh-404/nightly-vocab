"""Unit and integration tests for AI services, crypto, access control, and analyze API (Step 5)."""
import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.services.ai.access import (
    AiDenied,
    record_ai_tokens,
    release_ai_reservation_on_failure,
    reserve_ai_call,
    resolve_ai_source,
)
from apps.services.ai.gemini import GeminiAIError, GeminiProvider
from apps.services.ai.prompts import build_analysis_payload
from apps.services.ai.schemas import AnalysisItem, AnalysisResponse, Target
from apps.services.crypto import (
    decrypt_secret,
    encrypt_secret,
    mask_secret,
    sanitize_error_message,
)
from apps.services.models import AiUsage, SiteConfig, UserApiKey
from apps.texts.models import Text


@pytest.mark.django_db
class TestCryptoAndSanitization:
    """Test suite for secret encryption and error message sanitation."""

    def test_encryption_roundtrip(self):
        secret = "AIzaSyD-Secret-API-Key-12345"
        enc = encrypt_secret(secret)
        assert enc != secret
        dec = decrypt_secret(enc)
        assert dec == secret

    def test_empty_and_corrupt_ciphertext(self):
        assert encrypt_secret("") == ""
        assert decrypt_secret("") == ""
        assert decrypt_secret("invalid-not-fernet-token") == ""

    def test_mask_secret(self):
        assert mask_secret("") == ""
        assert mask_secret("123") == "••••"
        assert mask_secret("AIzaSyD-abcdef1234") == "••••••••1234"

    def test_sanitize_error_message(self):
        msg = "Error calling https://generativelanguage.googleapis.com?key=AIzaSyD1234567890123456789012345678 with Bearer secret_token_xyz"
        sanitized = sanitize_error_message(msg)
        assert "AIzaSyD1234567890123456789012345678" not in sanitized
        assert "secret_token_xyz" not in sanitized
        assert "[REDACTED" in sanitized


@pytest.mark.django_db
class TestPromptsAndSchemas:
    """Test suite for prompts formatting and Pydantic response validation."""

    def test_build_analysis_payload(self):
        targets = [
            Target(index=1, surface="dense", context_window="through the [[dense]] forest"),
            Target(index=2, surface="safe and sound", context_window="arrived [[safe and sound]] after"),
        ]
        payload = build_analysis_payload("Full text here", targets, want_example=True)
        assert "### FULL TEXT:" in payload
        assert "want_example=true" in payload
        assert '[1] Target: "dense"' in payload
        assert '[2] Target: "safe and sound"' in payload

    def test_analysis_response_schema_validation(self):
        raw = {
            "items": [
                {
                    "index": 1,
                    "lemma": "dense",
                    "pos": "adjective",
                    "meaning_fa": "متراکم، انبوه",
                    "example_en": "A dense forest.",
                }
            ]
        }
        res = AnalysisResponse.model_validate(raw)
        assert len(res.items) == 1
        assert res.items[0].lemma == "dense"
        assert res.items[0].pos == "adjective"


@pytest.mark.django_db
class TestGeminiProvider:
    """Test suite for Gemini AI provider with mocks for network/JSON behaviors."""

    @patch("apps.services.ai.gemini.httpx.Client")
    def test_gemini_successful_parse(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps({
                                    "items": [
                                        {
                                            "index": 1,
                                            "lemma": "dense",
                                            "pos": "adjective",
                                            "meaning_fa": "متراکم",
                                            "example_en": "The forest was dense.",
                                        }
                                    ]
                                })
                            }
                        ]
                    }
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 120,
                "candidatesTokenCount": 45,
            },
        }

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        provider = GeminiProvider()
        targets = [Target(index=1, surface="dense", context_window="[[dense]]")]
        res = provider.analyze("Text", targets, want_example=True, api_key="test-key")

        assert len(res.items) == 1
        assert res.items[0].meaning_fa == "متراکم"
        assert res.items[0].example_en == "The forest was dense."
        assert res.input_tokens == 120
        assert res.output_tokens == 45

    @patch("apps.services.ai.gemini.httpx.Client")
    def test_gemini_unknown_indices_ignored_and_missing_filled(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps({
                                    "items": [
                                        # Index 99 is unknown
                                        {"index": 99, "lemma": "foo", "pos": "noun", "meaning_fa": "بار"},
                                        # Index 1 is known
                                        {"index": 1, "lemma": "cat", "pos": "noun", "meaning_fa": "گربه"},
                                        # Index 2 is missing from AI response
                                    ]
                                })
                            }
                        ]
                    }
                }
            ]
        }
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        provider = GeminiProvider()
        targets = [
            Target(index=1, surface="cat", context_window="[[cat]]"),
            Target(index=2, surface="safe and sound", context_window="[[safe and sound]]"),
        ]
        res = provider.analyze("Text", targets, want_example=False, api_key="test-key")

        assert len(res.items) == 2
        # Target 1 found
        assert res.items[0].index == 1
        assert res.items[0].meaning_fa == "گربه"
        # Target 2 missing -> filled with empty meaning and valid pos
        assert res.items[1].index == 2
        assert res.items[1].meaning_fa == ""
        assert res.items[1].pos == "phrase"

    @patch("apps.services.ai.gemini.httpx.Client")
    def test_gemini_retry_on_network_or_5xx(self, mock_client_cls):
        # 1st call fails with 500, 2nd call succeeds with 200
        resp_err = MagicMock()
        resp_err.status_code = 500
        resp_err.text = "Internal error"

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"text": '{"items": [{"index": 1, "lemma": "a", "pos": "noun", "meaning_fa": "الف"}]}'}]}}
            ]
        }

        mock_client = MagicMock()
        mock_client.post.side_effect = [resp_err, resp_ok]
        mock_client_cls.return_value.__enter__.return_value = mock_client

        provider = GeminiProvider()
        targets = [Target(index=1, surface="a", context_window="[[a]]")]
        res = provider.analyze("Text", targets, want_example=False, api_key="test-key")

        assert len(res.items) == 1
        assert res.items[0].meaning_fa == "الف"
        assert mock_client.post.call_count == 2


@pytest.mark.django_db
class TestAccessAndRateLimiting:
    """Test suite for AI quota enforcement, access rules, and atomic reservation."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="testuser@example.com", email="testuser@example.com")

    def test_default_shared_key_access(self, user):
        config = SiteConfig.get()
        config.set_shared_ai_key("shared-test-key-12345")
        config.save()

        res = resolve_ai_source(user, num_targets=1)
        assert res.source == "shared"
        assert res.api_key == "shared-test-key-12345"
        assert res.daily_limit == 30

    def test_user_with_own_key_bypasses_shared_limit(self, user):
        config = SiteConfig.get()
        config.set_shared_ai_key("shared-key")
        config.save()

        # Add user own key
        own_key = UserApiKey(user=user, provider="gemini")
        own_key.set_key("my-own-gemini-key")
        own_key.save()

        res = resolve_ai_source(user, num_targets=1)
        assert res.source == "own"
        assert res.api_key == "my-own-gemini-key"

    def test_blocked_user_denied(self, user):
        control = user.control
        control.is_blocked = True
        control.save()

        with pytest.raises(AiDenied) as exc:
            resolve_ai_source(user)
        assert exc.value.reason == "blocked"

    def test_daily_limit_exceeded(self, user):
        config = SiteConfig.get()
        config.set_shared_ai_key("shared-key")
        config.default_ai_daily_limit = 5
        config.save()

        # Create usage record with 5 calls
        AiUsage.objects.create(user=user, date=date.today(), source="shared", calls=5)

        with pytest.raises(AiDenied) as exc:
            resolve_ai_source(user)
        assert exc.value.reason == "user_limit_daily"
        assert "سهمیهٔ امروزِ هوش مصنوعی تمام شد" in exc.value.user_message

    def test_disabled_and_own_only_policies(self, user):
        config = SiteConfig.get()
        config.set_shared_ai_key("shared-key")
        config.save()

        # Disabled access
        control = user.control
        control.ai_access = "disabled"
        control.save()
        with pytest.raises(AiDenied) as exc:
            resolve_ai_source(user)
        assert exc.value.reason == "disabled"

        # Own-only access
        control.ai_access = "own_only"
        control.save()
        with pytest.raises(AiDenied) as exc:
            resolve_ai_source(user)
        assert exc.value.reason == "own_key_required"

    def test_too_many_targets_denied(self, user):
        config = SiteConfig.get()
        config.set_shared_ai_key("shared-key")
        config.default_max_targets_per_call = 10
        config.save()

        with pytest.raises(AiDenied) as exc:
            resolve_ai_source(user, num_targets=15)
        assert exc.value.reason == "too_many_targets"

    def test_global_cap_denied(self, user):
        config = SiteConfig.get()
        config.set_shared_ai_key("shared-key")
        config.global_ai_daily_cap = 50
        config.save()

        # Simulate total today is 50
        other_user = User.objects.create_user(username="other@example.com", email="other@example.com")
        AiUsage.objects.create(user=other_user, date=date.today(), source="shared", calls=50)

        with pytest.raises(AiDenied) as exc:
            resolve_ai_source(user)
        assert exc.value.reason == "global_cap"

    def test_usage_summary_helper(self, user):
        from apps.services.ai.usage import get_user_ai_usage_summary

        config = SiteConfig.get()
        config.default_ai_daily_limit = 30
        config.save()

        AiUsage.objects.create(user=user, date=date.today(), source="shared", calls=3)
        summary = get_user_ai_usage_summary(user)
        assert summary["today_shared"] == 3
        assert summary["has_own_key"] is False
        assert summary["daily_remaining"] == 27

    def test_atomic_reservation_and_release(self, user):
        today = date.today()
        # Reserve call
        usage = reserve_ai_call(user, source="shared", today=today, max_limit=10)
        assert usage.calls == 1

        # Record tokens
        record_ai_tokens(usage.id, input_tokens=100, output_tokens=50)
        usage.refresh_from_db()
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50

        # Simulate failure -> release reservation
        release_ai_reservation_on_failure(usage.id)
        usage.refresh_from_db()
        assert usage.calls == 0
        assert usage.failed_calls == 1


@pytest.mark.django_db
class TestAnalyzeTextAPIView:
    """Test suite for POST /api/texts/<id>/analyze/ endpoint."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="author@example.com", email="author@example.com")

    @pytest.fixture
    def client(self, user):
        c = Client()
        c.force_login(user)
        return c

    @pytest.fixture
    def text(self, user):
        return Text.objects.create(
            user=user,
            title="Nightly Journey",
            body="We walked along the dark pathway. We felt safe and sound.",
        )

    @patch("apps.texts.views.GeminiProvider.analyze")
    def test_analyze_api_success(self, mock_analyze, client, text):
        config = SiteConfig.get()
        config.set_shared_ai_key("test-shared-key")
        config.save()

        start = text.body.index("safe and sound")
        end = start + len("safe and sound")

        mock_analyze.return_value = MagicMock(
            items=[
                AnalysisItem(
                    index=1,
                    lemma="safe and sound",
                    pos="idiom",
                    meaning_fa="سالم و سلامت",
                    example_en="They arrived safe and sound.",
                )
            ],
            input_tokens=80,
            output_tokens=30,
        )

        res = client.post(
            f"/api/texts/{text.id}/analyze/",
            data=json.dumps({
                "targets": [{"start": start, "end": end}],
                "want_example": True,
            }),
            content_type="application/json",
        )

        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["word"] == "safe and sound"
        assert item["pos"] == "idiom"
        assert item["meaning"] == "سالم و سلامت"
        assert item["example"] == "They arrived safe and sound."

    def test_analyze_api_rate_limit_fallback(self, client, text, user):
        config = SiteConfig.get()
        config.set_shared_ai_key("test-shared-key")
        config.default_ai_daily_limit = 2
        config.save()

        # Simulate already at limit
        AiUsage.objects.create(user=user, date=date.today(), source="shared", calls=2)

        start = text.body.index("pathway")
        end = start + len("pathway")

        res = client.post(
            f"/api/texts/{text.id}/analyze/",
            data=json.dumps({"targets": [{"start": start, "end": end}]}),
            content_type="application/json",
        )

        assert res.status_code == 429
        data = res.json()
        assert "سهمیهٔ امروزِ هوش مصنوعی تمام شد" in data["error"]

    def test_analyze_api_idor_protection(self, text):
        user_b = User.objects.create_user(username="intruder@example.com", email="intruder@example.com")
        client_b = Client()
        client_b.force_login(user_b)

        res = client_b.post(
            f"/api/texts/{text.id}/analyze/",
            data=json.dumps({"targets": [{"start": 0, "end": 2}]}),
            content_type="application/json",
        )
        assert res.status_code == 404

    @patch("apps.texts.views.GeminiProvider.analyze")
    def test_analyze_api_provider_failure_fallback(self, mock_analyze, client, text):
        config = SiteConfig.get()
        config.set_shared_ai_key("test-shared-key")
        config.save()

        start = text.body.index("dark")
        end = start + len("dark")

        mock_analyze.side_effect = GeminiAIError("Service timeout", status_code=504)

        res = client.post(
            f"/api/texts/{text.id}/analyze/",
            data=json.dumps({"targets": [{"start": start, "end": end}]}),
            content_type="application/json",
        )

        assert res.status_code == 503
        data = res.json()
        assert data["fallback"] is True
        assert "سرویس هوش مصنوعی در دسترس نیست" in data["error"]
