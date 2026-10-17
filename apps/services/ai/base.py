"""Base protocol for AI vocabulary analysis providers (Section 7.1)."""
from typing import List, Protocol

from .schemas import AnalysisResult, Target


class AIProvider(Protocol):
    """Protocol defining the interface for AI vocabulary analysis engines."""

    def analyze(
        self,
        text: str,
        targets: List[Target],
        want_example: bool,
        api_key: str,
        model: str,
    ) -> AnalysisResult:
        """
        Analyzes target words/phrases within the contextual background of text.
        Returns AnalysisResult containing validated items and token counts.
        """
        ...
