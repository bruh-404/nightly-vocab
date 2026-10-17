"""Pydantic schemas for AI request/response validation (Section 7.1)."""
from typing import List, Optional

from pydantic import BaseModel, Field

ALLOWED_POS = {
    "noun",
    "verb",
    "adjective",
    "adverb",
    "preposition",
    "conjunction",
    "pronoun",
    "determiner",
    "interjection",
    "phrasal verb",
    "idiom",
    "phrase",
}


class Target(BaseModel):
    """A target word or phrase to analyze with surrounding context window."""

    index: int
    surface: str
    context_window: str


class AnalysisItem(BaseModel):
    """Model output for a single target word/phrase."""

    index: int
    lemma: str = ""
    pos: str = "noun"
    meaning_fa: str = ""
    example_en: Optional[str] = None


class AnalysisResponse(BaseModel):
    """Top-level structured JSON output returned by AI provider."""

    items: List[AnalysisItem] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Result package returned to the caller including token usage metrics."""

    items: List[AnalysisItem]
    input_tokens: int = 0
    output_tokens: int = 0
