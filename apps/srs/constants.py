"""Constants for the 8-Stage Spaced Repetition System (SRS).

Pure Python module with zero external or Django dependencies.
"""
from typing import Dict, Tuple

# Base intervals in days per stage
BASE_INTERVALS: Dict[int, int] = {
    0: 0,
    1: 1,
    2: 3,
    3: 4,
    4: 7,
    5: 14,
    6: 30,
    7: 60,
    8: 90,
}

# Mapping of stage to its intrinsic flashcard target type (1, 2, or 3)
STAGE_TARGET_TYPES: Dict[int, int] = {
    0: 1,
    1: 1,
    2: 1,
    3: 2,
    4: 2,
    5: 3,
    6: 3,
    7: 3,
    8: 3,
}

# Tricky digraphs and silent-letter letter combinations scored with high priority (75)
DIGRAPHS: Tuple[str, ...] = (
    "ie",
    "ei",
    "ea",
    "ou",
    "gh",
    "ph",
    "kn",
    "wr",
    "sc",
    "mn",
    "mb",
    "ps",
    "rh",
    "gu",
)

# Medial vowel candidates (scored 60)
VOWELS: Tuple[str, ...] = ("a", "e", "i", "o", "u", "y")

# Common easy suffixes for words with >= 6 alpha characters (scored 15)
COMMON_SUFFIXES: Tuple[str, ...] = ("ing", "ed", "ly")
