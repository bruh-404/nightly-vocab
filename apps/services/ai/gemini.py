"""Gemini implementation for structured JSON vocabulary analysis (Section 7.1)."""
import json
import logging
from typing import Dict, List

import httpx
from pydantic import ValidationError

from apps.services.crypto import sanitize_error_message

from .base import AIProvider
from .prompts import SYSTEM_PROMPT, build_analysis_payload
from .schemas import ALLOWED_POS, AnalysisItem, AnalysisResponse, AnalysisResult, Target

logger = logging.getLogger(__name__)

GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiAIError(Exception):
    """Raised when the Gemini API returns an error or communication fails."""

    def __init__(self, message: str, status_code: int = 500, is_quota: bool = False):
        super().__init__(sanitize_error_message(message))
        self.status_code = status_code
        self.is_quota = is_quota


class GeminiProvider(AIProvider):
    """
    Google Gemini AI client with structured JSON output, timeout handling,
    schema validation, and 1-attempt automatic retry.
    """

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def _build_request_body(self, text: str, targets: List[Target], want_example: bool) -> dict:
        user_content = build_analysis_payload(text, targets, want_example)
        return {
            "system_instruction": {
                "parts": [{"text": SYSTEM_PROMPT}]
            },
            "contents": [
                {
                    "parts": [{"text": user_content}]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "response_schema": {
                    "type": "OBJECT",
                    "properties": {
                        "items": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "index": {"type": "INTEGER"},
                                    "lemma": {"type": "STRING"},
                                    "pos": {"type": "STRING"},
                                    "meaning_fa": {"type": "STRING"},
                                    "example_en": {"type": "STRING"},
                                },
                                "required": ["index", "lemma", "pos", "meaning_fa"],
                            },
                        }
                    },
                    "required": ["items"],
                },
                "temperature": 0.2,
            },
        }

    def _execute_request(self, url: str, body: dict) -> httpx.Response:
        """Executes HTTP POST with a 30s timeout and 1 automatic retry on transient failures."""
        attempts = 0
        last_exception = None

        while attempts < 2:
            attempts += 1
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, json=body)

                if resp.status_code == 200:
                    return resp

                # Handle client or quota errors (do not retry 4xx errors)
                if 400 <= resp.status_code < 500:
                    err_msg = resp.text
                    is_quota = resp.status_code == 429 or "RESOURCE_EXHAUSTED" in err_msg
                    raise GeminiAIError(
                        f"Gemini API returned error {resp.status_code}: {err_msg}",
                        status_code=resp.status_code,
                        is_quota=is_quota,
                    )

                # 5xx server error, may retry once
                if attempts == 1:
                    logger.warning("Gemini 5xx error, retrying once...")
                    continue
                raise GeminiAIError(
                    f"Gemini API server error {resp.status_code}: {resp.text}",
                    status_code=resp.status_code,
                )

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exception = exc
                if attempts == 1:
                    logger.warning("Network or timeout error calling Gemini, retrying once...")
                    continue
                raise GeminiAIError(
                    f"Failed to communicate with Gemini API: {exc}",
                    status_code=504,
                ) from exc

        if last_exception:
            raise GeminiAIError(f"Gemini communication failed: {last_exception}")
        raise GeminiAIError("Unknown error occurred calling Gemini API.")

    def analyze(
        self,
        text: str,
        targets: List[Target],
        want_example: bool,
        api_key: str,
        model: str = "gemini-1.5-flash",
    ) -> AnalysisResult:
        if not api_key:
            raise GeminiAIError("No API key provided for Gemini provider.", status_code=401)

        url = f"{GEMINI_API_URL_TEMPLATE.format(model=model)}?key={api_key}"
        body = self._build_request_body(text, targets, want_example)

        resp = self._execute_request(url, body)

        try:
            data = resp.json()
        except Exception as exc:
            raise GeminiAIError(f"Failed to parse Gemini API JSON response: {exc}") from exc

        # Extract tokens usage
        usage_meta = data.get("usageMetadata", {})
        input_tokens = usage_meta.get("promptTokenCount", 0)
        output_tokens = usage_meta.get("candidatesTokenCount", 0)

        # Extract candidates text
        candidates = data.get("candidates", [])
        if not candidates:
            raise GeminiAIError("No candidates returned from Gemini.")

        raw_parts = candidates[0].get("content", {}).get("parts", [])
        if not raw_parts:
            raise GeminiAIError("Candidate contains no content parts.")

        raw_text = raw_parts[0].get("text", "{}")

        # Validate with Pydantic
        try:
            parsed = AnalysisResponse.model_validate_json(raw_text)
        except (ValidationError, json.JSONDecodeError):
            # Try cleaning Markdown code fences if any
            clean_text = raw_text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.startswith("```"):
                clean_text = clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            try:
                parsed = AnalysisResponse.model_validate_json(clean_text.strip())
            except Exception as exc:
                raise GeminiAIError(f"Invalid structured JSON received from Gemini: {exc}") from exc

        # Map by index, ignore unknown indices, fill missing items
        target_map: Dict[int, Target] = {t.index: t for t in targets}
        found_map: Dict[int, AnalysisItem] = {}

        for item in parsed.items:
            if item.index in target_map:
                # Normalize POS
                pos = item.pos.lower().strip()
                if pos not in ALLOWED_POS:
                    pos = "phrase" if " " in target_map[item.index].surface else "noun"
                found_map[item.index] = AnalysisItem(
                    index=item.index,
                    lemma=item.lemma or target_map[item.index].surface.lower(),
                    pos=pos,
                    meaning_fa=item.meaning_fa.strip(),
                    example_en=item.example_en if want_example else None,
                )

        # Ensure every requested target has an item
        final_items: List[AnalysisItem] = []
        for t in targets:
            if t.index in found_map:
                final_items.append(found_map[t.index])
            else:
                is_phrase = " " in t.surface
                final_items.append(
                    AnalysisItem(
                        index=t.index,
                        lemma=t.surface.lower(),
                        pos="phrase" if is_phrase else "noun",
                        meaning_fa="",
                        example_en=None,
                    )
                )

        return AnalysisResult(
            items=final_items,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    @classmethod
    def test_api_key(cls, raw_key: str, model: str = "gemini-2.5-flash") -> tuple[bool, str]:
        """Tests an API key against Google Generative Language API with a lightweight call."""
        cleaned_key = (raw_key or "").strip()
        if not cleaned_key:
            return False, "کلید API نمی‌تواند خالی باشد."

        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={cleaned_key}"
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                resp = client.get(url)

            if resp.status_code == 200:
                return True, ""

            err_msg = "کلید API نامعتبر است."
            try:
                err_data = resp.json()
                err_msg = err_data.get("error", {}).get("message", err_msg)
            except Exception:
                pass
            return False, sanitize_error_message(err_msg)
        except Exception as exc:
            return False, sanitize_error_message(f"خطای ارتباط با سرور: {exc}")

