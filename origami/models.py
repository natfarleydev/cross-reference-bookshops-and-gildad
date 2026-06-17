"""Plain data structures shared across the package.

Frozen dataclasses with a few derived convenience properties. Parsing lives in
:mod:`origami.bookshop` and :mod:`origami.gilad`; persistence in
:mod:`origami.catalog`; orchestration in :mod:`origami.service`.

The central entity is :class:`CatalogBook`: a Bookshop.org product (the thing you
can buy) optionally enriched with Gilad's skill level and diagram count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .skill import Difficulty
from .skill import parse as parse_skill

_KIDS_RE = re.compile(
    r"\b(kids?|children|child|toddler|preschool|kindergarten|"
    r"year[\s-]?olds?|ages?\s*\d)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Design:
    """A single origami model/diagram inside a book (from Gilad)."""

    name: str
    designer: str = ""
    subject: str = ""
    page: str = ""
    paper: str = ""
    photo_url: str = ""
    has_crease_pattern: bool = False


@dataclass(frozen=True)
class GiladBook:
    """An origami book as parsed from a Gilad database page (the supplement)."""

    book_id: str
    title: str
    author: str = ""
    url: str = ""
    cover_url: str = ""
    isbn13: str | None = None
    amazon_asins: tuple[str, ...] = ()
    difficulty: Difficulty = field(default_factory=lambda: parse_skill(None))
    designs: tuple[Design, ...] = ()
    technical: dict[str, str] = field(default_factory=dict)

    @property
    def design_count(self) -> int:
        return len(self.designs)


@dataclass(frozen=True)
class BookshopBook:
    """A sellable product from Bookshop.org's search index."""

    isbn13: str
    title: str
    subtitle: str = ""
    author: str = ""
    contributors: tuple[str, ...] = ()
    price: float | None = None      # in major units (e.g. pounds)
    currency: str = "GBP"
    status: str = ""                # e.g. "in stock", "backorder"
    cover_url: str = ""
    url: str = ""                   # absolute product-page URL
    publish_date: str = ""          # ISO date string
    format_category: str = ""       # e.g. "Paperback", "Hardback", "Other"
    language: str = ""
    series_name: str = ""

    @property
    def in_stock(self) -> bool:
        return self.status.lower().strip() == "in stock"


@dataclass(frozen=True)
class CatalogBook:
    """A Bookshop product enriched with Gilad's supplementary data."""

    # --- Bookshop (source of truth: what you can buy) ---
    isbn13: str
    title: str
    subtitle: str = ""
    author: str = ""
    price: float | None = None
    currency: str = "GBP"
    status: str = ""
    cover_url: str = ""
    url: str = ""
    publish_date: str = ""
    format_category: str = ""
    language: str = ""
    series_name: str = ""

    # --- Gilad supplement (may be absent until enriched) ---
    gilad_book_id: str = ""
    gilad_url: str = ""
    difficulty: Difficulty = field(default_factory=lambda: parse_skill(None))
    design_count: int = 0
    enriched: bool = False          # True once a Gilad lookup has been attempted

    @property
    def in_stock(self) -> bool:
        return self.status.lower().strip() == "in stock"

    @property
    def is_kids(self) -> bool:
        text = f"{self.title} {self.subtitle}"
        return bool(_KIDS_RE.search(text))

    @property
    def year(self) -> str:
        return self.publish_date[:4] if self.publish_date else ""

    @classmethod
    def from_bookshop(cls, b: BookshopBook) -> CatalogBook:
        return cls(
            isbn13=b.isbn13,
            title=b.title,
            subtitle=b.subtitle,
            author=b.author,
            price=b.price,
            currency=b.currency,
            status=b.status,
            cover_url=b.cover_url,
            url=b.url,
            publish_date=b.publish_date,
            format_category=b.format_category,
            language=b.language,
            series_name=b.series_name,
        )
