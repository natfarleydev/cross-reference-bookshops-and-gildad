"""ISBN / ASIN helpers.

Gilad's database links to Amazon via ``/ASIN/<code>/`` URLs. For ordinary trade
books that ASIN *is* the ISBN-10 (or sometimes a bare ISBN-13). Bookshop.org's
``/book/<isbn>`` endpoint only resolves ISBN-13, so the key job here is:

    raw ASIN/ISBN string  ->  validated, normalised ISBN-13  (or None)

Anything that is not a real book identifier (Amazon "B0..." product codes,
junk) is rejected so we never send garbage to Bookshop.
"""

from __future__ import annotations

import re

_CLEAN_RE = re.compile(r"[\s-]")


def clean(code: str) -> str:
    """Strip spaces/hyphens and upper-case (for the X check digit)."""
    return _CLEAN_RE.sub("", code or "").upper()


def is_valid_isbn10(code: str) -> bool:
    code = clean(code)
    if len(code) != 10 or not re.fullmatch(r"\d{9}[\dX]", code):
        return False
    total = 0
    for i, ch in enumerate(code):
        value = 10 if ch == "X" else int(ch)
        total += value * (10 - i)
    return total % 11 == 0


def is_valid_isbn13(code: str) -> bool:
    code = clean(code)
    if len(code) != 13 or not code.isdigit():
        return False
    total = sum((1 if i % 2 == 0 else 3) * int(ch) for i, ch in enumerate(code))
    return total % 10 == 0


def isbn10_to_13(code: str) -> str | None:
    """Convert a valid ISBN-10 to its ISBN-13 form, else None."""
    code = clean(code)
    if not is_valid_isbn10(code):
        return None
    core = "978" + code[:9]
    check = (10 - sum((1 if i % 2 == 0 else 3) * int(ch) for i, ch in enumerate(core)) % 10) % 10
    return core + str(check)


def to_isbn13(code: str) -> str | None:
    """Normalise any book identifier to a valid ISBN-13, or None if it isn't one.

    Accepts ISBN-13 directly, converts valid ISBN-10s, and rejects everything
    else (notably Amazon non-book ASINs like ``B0...``).
    """
    code = clean(code)
    if is_valid_isbn13(code):
        return code
    if is_valid_isbn10(code):
        return isbn10_to_13(code)
    return None


def looks_like_isbn(code: str) -> bool:
    """True if the code is a valid ISBN-10 or ISBN-13."""
    return to_isbn13(code) is not None
