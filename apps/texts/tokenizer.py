"""Server-side tokenizer and sentence extractor for English texts."""
import re
from dataclasses import dataclass
from typing import List, Tuple

# Common abbreviations that should not trigger a sentence split on their trailing period
ABBREVIATIONS = {
    "dr",
    "mr",
    "mrs",
    "ms",
    "prof",
    "sr",
    "jr",
    "vs",
    "etc",
    "e.g",
    "i.e",
    "u.s",
    "u.k",
}

# Regex to match words, allowing internal hyphens and apostrophes (both ASCII ' and Unicode ’)
TOKEN_REGEX = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*")

# Sentence boundary delimiters
SENT_SPLIT_REGEX = re.compile(r"([.!?…]+(?:\s+|\Z)|\n{2,})")

# Punctuation that should not be bridged inside a phrase
PHRASE_DELIMITER_CHARS = {",", ";", ":", "—", "(", ")", '"', "'", "“", "”"}


@dataclass(frozen=True)
class Token:
    """Represents a single word token in the text with precise character offsets."""

    text: str
    start: int
    end: int
    sent_idx: int


def is_abbreviation_at(body: str, match_end: int) -> bool:
    """Checks if the period at match_end belongs to a known abbreviation."""
    # Look back up to 8 characters before the period
    prev_text = body[:match_end].rstrip(".!?… \t\n")
    words = prev_text.split()
    if not words:
        return False
    last_word = words[-1].lower()
    return last_word in ABBREVIATIONS


def split_sentences_with_spans(body: str) -> List[Tuple[int, int]]:
    """
    Splits body into sentences while preserving character spans (start, end).
    Handles abbreviations (e.g. Dr., Mr., e.g.).
    """
    spans: List[Tuple[int, int]] = []
    current_start = 0
    i = 0
    n = len(body)

    while i < n:
        # Check blank line split (\n\n+)
        if body[i : i + 2] == "\n\n":
            span_end = i
            if span_end > current_start and body[current_start:span_end].strip():
                spans.append((current_start, span_end))
            while i < n and body[i] == "\n":
                i += 1
            current_start = i
            continue

        # Check sentence ending punctuation followed by optional closing quotes and whitespace or EOF
        if body[i] in ".!?…":
            # Check if it's an abbreviation like Dr. or Mr.
            if body[i] == "." and is_abbreviation_at(body, i):
                i += 1
                continue

            punct_end = i
            while punct_end < n and body[punct_end] in ".!?…":
                punct_end += 1
            while punct_end < n and body[punct_end] in "\"'”’)]}":
                punct_end += 1

            if punct_end >= n or body[punct_end].isspace():
                span_end = punct_end
                if body[current_start:span_end].strip():
                    spans.append((current_start, span_end))

                while punct_end < n and body[punct_end].isspace():
                    punct_end += 1
                current_start = punct_end
                i = punct_end
                continue

        i += 1

    if current_start < n and body[current_start:].strip():
        spans.append((current_start, n))

    return spans if spans else [(0, n)]


def tokenize_text(body: str) -> List[Token]:
    """
    Tokenizes the text into word tokens with exact Python string offsets and sentence IDs.
    Punctuation and spaces are omitted from tokens (rendered as plain text in template).
    """
    sentence_spans = split_sentences_with_spans(body)
    tokens: List[Token] = []

    for sent_idx, (sent_start, sent_end) in enumerate(sentence_spans):
        sent_body = body[sent_start:sent_end]
        for match in TOKEN_REGEX.finditer(sent_body):
            token_text = match.group(0)
            token_start = sent_start + match.start()
            token_end = sent_start + match.end()
            tokens.append(
                Token(
                    text=token_text,
                    start=token_start,
                    end=token_end,
                    sent_idx=sent_idx,
                )
            )

    return tokens


def extract_sentence_for_span(
    body: str, char_start: int, char_end: int
) -> Tuple[str, int, int]:
    """
    Extracts the containing sentence for a target word/phrase span [char_start:char_end].
    Returns (sentence_text, ctx_start, ctx_end).
    Capped at 400 characters around the word if the sentence is excessively long.
    """
    sentence_spans = split_sentences_with_spans(body)
    target_sentence_span = (0, len(body))

    for sent_start, sent_end in sentence_spans:
        if sent_start <= char_start and char_end <= sent_end:
            target_sentence_span = (sent_start, sent_end)
            break

    s_start, s_end = target_sentence_span
    raw_sentence = body[s_start:s_end]

    # Trim leading/trailing whitespace and adjust offsets
    l_strip = len(raw_sentence) - len(raw_sentence.lstrip())
    sentence = raw_sentence.strip()
    adj_s_start = s_start + l_strip

    ctx_start = char_start - adj_s_start
    ctx_end = char_end - adj_s_start

    # Cap length at 400 characters if sentence is exceptionally long
    if len(sentence) > 400:
        window_radius = 180
        w_start = max(0, ctx_start - window_radius)
        w_end = min(len(sentence), ctx_end + window_radius)

        # Snap to word boundaries
        if w_start > 0:
            next_space = sentence.find(" ", w_start)
            if next_space != -1 and next_space < ctx_start:
                w_start = next_space + 1
        if w_end < len(sentence):
            prev_space = sentence.rfind(" ", ctx_end, w_end)
            if prev_space != -1:
                w_end = prev_space

        sentence_slice = sentence[w_start:w_end]
        prefix = "… " if w_start > 0 else ""
        suffix = " …" if w_end < len(sentence) else ""

        ctx_start = ctx_start - w_start + len(prefix)
        ctx_end = ctx_end - w_start + len(prefix)
        sentence = f"{prefix}{sentence_slice}{suffix}"

    return sentence, ctx_start, ctx_end
