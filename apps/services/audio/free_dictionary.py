"""Free Dictionary API client for human pronunciation recordings (Section 7.2)."""
import logging
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

FREE_DICT_API_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"


class FreeDictionaryProvider:
    """
    Fetches real human pronunciation recordings from the public Free Dictionary API.
    Normalizes protocol-relative URLs and classifies recordings by accent (UK / US).
    Never raises exceptions to the caller; returns None on failure/timeout.
    """

    def __init__(self, timeout: float = 3.0):
        self.timeout = timeout

    def get_audio_urls(self, word: str) -> Dict[str, Optional[str]]:
        """
        Retrieves human audio recordings for an English word.
        Returns dict: {'uk': url | None, 'us': url | None}.
        """
        result: Dict[str, Optional[str]] = {"uk": None, "us": None}
        cleaned_word = word.strip().lower()

        # Phrases or empty words do not have single dictionary recordings
        if not cleaned_word or " " in cleaned_word:
            return result

        url = FREE_DICT_API_URL.format(word=cleaned_word)

        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(url)

            if resp.status_code != 200:
                return result

            data = resp.json()
            if not isinstance(data, list) or not data:
                return result

            # Collect all audio entries across phonetics
            for entry in data:
                phonetics = entry.get("phonetics", [])
                for p in phonetics:
                    audio_url = p.get("audio", "").strip()
                    if not audio_url:
                        continue

                    # Normalize protocol-relative URLs
                    if audio_url.startswith("//"):
                        audio_url = "https:" + audio_url
                    elif not audio_url.startswith("http"):
                        audio_url = "https://" + audio_url

                    # Classify by filename / path hints
                    lower_url = audio_url.lower()
                    if any(h in lower_url for h in ("-uk", "_uk", "/uk/", "-gb", "_gb", "/gb/")):
                        if not result["uk"]:
                            result["uk"] = audio_url
                    elif any(h in lower_url for h in ("-us", "_us", "/us/", "-ca", "_ca", "/ca/")):
                        if not result["us"]:
                            result["us"] = audio_url
                    elif any(h in lower_url for h in ("-au", "_au", "/au/")):
                        # Australian recordings serve as fallback for UK if UK is empty
                        if not result["uk"]:
                            result["uk"] = audio_url
                    else:
                        # General recording without accent hint: assign to US or UK if empty
                        if not result["us"]:
                            result["us"] = audio_url
                        elif not result["uk"]:
                            result["uk"] = audio_url

                    # Stop early if both are found
                    if result["uk"] and result["us"]:
                        break

        except (httpx.HTTPError, httpx.TimeoutException, ValueError, Exception) as exc:
            logger.debug("Free Dictionary API lookup failed for %s: %s", cleaned_word, exc)
            return result

        return result
