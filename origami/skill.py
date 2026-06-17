"""Origami skill-level taxonomy and parsing.

Gilad records a book's difficulty as free text in the "Skill Level" row of each
book page, using the community-standard ladder:

    simple < low intermediate < intermediate < high intermediate
           < complex < super complex

Books (especially anthologies and convention collections) often give a *range*,
e.g. "From simple to complex". We model difficulty as an inclusive ``[low, high]``
band on a 1..6 ordinal scale plus a coarse 3-bucket label, which is what the UI
filters on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Ordinal scale. Higher == harder. 0 is reserved for "unknown".
UNKNOWN = 0
SIMPLE = 1
LOW_INTERMEDIATE = 2
INTERMEDIATE = 3
HIGH_INTERMEDIATE = 4
COMPLEX = 5
SUPER_COMPLEX = 6

LEVEL_NAMES = {
    UNKNOWN: "Unknown",
    SIMPLE: "Simple",
    LOW_INTERMEDIATE: "Low intermediate",
    INTERMEDIATE: "Intermediate",
    HIGH_INTERMEDIATE: "High intermediate",
    COMPLEX: "Complex",
    SUPER_COMPLEX: "Super complex",
}

# Coarse 3-bucket grouping used by the main filter UI.
BUCKET_SIMPLE = "simple"
BUCKET_INTERMEDIATE = "intermediate"
BUCKET_COMPLEX = "complex"
BUCKETS = (BUCKET_SIMPLE, BUCKET_INTERMEDIATE, BUCKET_COMPLEX)


def level_to_bucket(level: int) -> str | None:
    if level in (SIMPLE,):
        return BUCKET_SIMPLE
    if level in (LOW_INTERMEDIATE, INTERMEDIATE, HIGH_INTERMEDIATE):
        return BUCKET_INTERMEDIATE
    if level in (COMPLEX, SUPER_COMPLEX):
        return BUCKET_COMPLEX
    return None


# Order matters: match the most specific / longest phrases first so that
# "low intermediate" is not swallowed by "intermediate", etc.
_PHRASES: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"super[\s-]*complex|very\s+complex"), SUPER_COMPLEX),
    (re.compile(r"high[\s-]*intermediate|upper[\s-]*intermediate"), HIGH_INTERMEDIATE),
    (re.compile(r"low[\s-]*intermediate|lower[\s-]*intermediate|easy[\s-]*intermediate"), LOW_INTERMEDIATE),
    (re.compile(r"complex|advanced|difficult"), COMPLEX),
    (re.compile(r"intermediate|medium|moderate"), INTERMEDIATE),
    (re.compile(r"simple|easy|beginner|basic"), SIMPLE),
]


@dataclass(frozen=True)
class Difficulty:
    """An inclusive difficulty band parsed from a book's skill-level text."""

    low: int
    high: int
    raw: str = ""

    @property
    def is_known(self) -> bool:
        return self.low != UNKNOWN or self.high != UNKNOWN

    @property
    def label(self) -> str:
        if not self.is_known:
            return "Unknown"
        if self.low == self.high:
            return LEVEL_NAMES[self.low]
        return f"{LEVEL_NAMES[self.low]} – {LEVEL_NAMES[self.high]}"

    @property
    def buckets(self) -> set[str]:
        """All coarse buckets this band spans (used by filtering)."""
        out = set()
        for lvl in range(self.low, self.high + 1):
            b = level_to_bucket(lvl)
            if b:
                out.add(b)
        return out

    def matches_bucket(self, bucket: str) -> bool:
        """True if an unknown band (we don't exclude unknowns) or it overlaps."""
        if not self.is_known:
            return True
        return bucket in self.buckets


def parse(text: str | None) -> Difficulty:
    """Parse free-text skill level into a :class:`Difficulty` band.

    Handles single levels ("Intermediate"), ranges ("From simple to complex",
    "simple-intermediate", "simple to high intermediate") and unknown/empty.
    """
    if not text:
        return Difficulty(UNKNOWN, UNKNOWN, raw=text or "")

    raw = text.strip()
    lowered = raw.lower()

    found: list[int] = []
    scratch = lowered
    for pattern, level in _PHRASES:
        if pattern.search(scratch):
            found.append(level)
            # Blank out matched text so a later, broader pattern doesn't re-match
            # the same words (e.g. "complex" inside "super complex").
            scratch = pattern.sub(" ", scratch)

    if not found:
        return Difficulty(UNKNOWN, UNKNOWN, raw=raw)

    return Difficulty(min(found), max(found), raw=raw)
