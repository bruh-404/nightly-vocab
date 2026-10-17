"""Stub for Cambridge Dictionary audio provider (Section 7.2)."""
from typing import Dict, Optional


class NotConfigured(Exception):
    """Base exception for unconfigured audio providers."""

    pass


class CambridgeNotConfigured(NotConfigured):
    """Raised because Cambridge audio is proprietary and requires a commercial license."""

    pass


class CambridgeProvider:
    """
    Stub provider for Cambridge Dictionary audio (Section 7.2).
    Cambridge does not offer a free public API; scraping or hotlinking is prohibited.
    """

    def get_audio_urls(self, word: str) -> Dict[str, Optional[str]]:
        raise CambridgeNotConfigured(
            "Cambridge Dictionary audio requires a licensed commercial API subscription."
        )
