"""Plain data structures shared across the package.

These are deliberately dumb containers (frozen dataclasses) with a couple of
derived convenience properties. All parsing lives in :mod:`origami.gilad` and
:mod:`origami.bookshop`; all combination logic lives in :mod:`origami.crossref`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .skill import Difficulty


@dataclass(frozen=True)
class Design:
    """A single origami model/diagram as it appears inside one book."""

    name: str
    designer: str = ""
    subject: str = ""        # Gilad's subject taxonomy, e.g. "Imaginary beings - Dragons"
    page: str = ""           # page number within the book (string; may be blank)
    paper: str = ""          # starting paper shape / notes, e.g. "Square", "Rectangle - 1X2"
    photo_url: str = ""      # absolute URL of a folded photo, if any
    has_crease_pattern: bool = False


@dataclass(frozen=True)
class GiladBook:
    """An origami book/publication as catalogued by Gilad's database."""

    book_id: str             # "" for legacy /BO_*.html review pages
    title: str
    author: str = ""
    url: str = ""            # absolute Gilad page URL
    cover_url: str = ""
    isbn13: str | None = None
    amazon_asins: tuple[str, ...] = ()
    difficulty: Difficulty = field(default_factory=lambda: Difficulty(0, 0))
    designs: tuple[Design, ...] = ()
    technical: dict[str, str] = field(default_factory=dict)

    @property
    def design_count(self) -> int:
        return len(self.designs)

    @property
    def has_isbn(self) -> bool:
        return bool(self.isbn13)


@dataclass(frozen=True)
class BookshopListing:
    """A product on Bookshop.org, parsed from its JSON-LD."""

    isbn13: str
    title: str
    url: str
    authors: tuple[str, ...] = ()
    publisher: str = ""
    price: float | None = None
    currency: str = "USD"
    availability: str = ""   # e.g. "InStock", "OutOfStock"
    image_url: str = ""
    description: str = ""

    @property
    def in_stock(self) -> bool:
        return "instock" in self.availability.lower()


@dataclass(frozen=True)
class CrossRef:
    """A Gilad book joined to its Bookshop listing (if found)."""

    book: GiladBook
    listing: BookshopListing | None = None

    @property
    def on_bookshop(self) -> bool:
        return self.listing is not None

    @property
    def title(self) -> str:
        return self.book.title

    @property
    def difficulty(self) -> Difficulty:
        return self.book.difficulty
