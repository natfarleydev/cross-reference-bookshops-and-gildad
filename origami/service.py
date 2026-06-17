"""Application service layer.

Sits between the (FastAPI) web layer and the data modules. Responsibilities:

* **Catalogue building** – harvest Bookshop products, enrich them with Gilad.
* **Browsing** – filter / sort / paginate the catalogue and compute facet counts.

The web layer only ever calls functions here; it never touches Bookshop, Gilad,
or SQLite directly. Everything takes its collaborators (``Catalog``,
``HttpClient``) as arguments, so the whole layer is trivially testable and plays
nicely with FastAPI's dependency injection.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import bookshop, gilad, skill
from .cache import HttpClient
from .catalog import Catalog
from .models import CatalogBook, Design

SORTS = {
    "relevance": "In stock, then title",
    "title": "Title A–Z",
    "price_asc": "Price: low to high",
    "price_desc": "Price: high to low",
    "newest": "Newest first",
    "diagrams": "Most diagrams",
}


# --------------------------------------------------------------------------
# Catalogue building
# --------------------------------------------------------------------------


def ensure_catalog(catalog: Catalog, client: HttpClient, *, force: bool = False) -> int:
    """Harvest Bookshop into the catalogue if it's empty (or ``force``)."""
    if not force and not catalog.is_empty():
        return catalog.count()
    books = bookshop.harvest(client, force_refresh=force)
    catalog.upsert_many([CatalogBook.from_bookshop(b) for b in books])
    return len(books)


def enrich_book(catalog: Catalog, client: HttpClient, isbn13: str) -> CatalogBook | None:
    """Attach Gilad skill level + diagram count to one catalogue row."""
    book = catalog.get(isbn13)
    if book is None:
        return None
    gilad_book = gilad.find_book_by_isbn(isbn13, client)
    if gilad_book is not None:
        book = replace(
            book,
            gilad_book_id=gilad_book.book_id,
            gilad_url=gilad_book.url,
            difficulty=gilad_book.difficulty,
            design_count=gilad_book.design_count,
            enriched=True,
        )
    else:
        # Mark as attempted so we don't re-query a book Gilad doesn't have.
        book = replace(book, enriched=True)
    catalog.set_enrichment(book)
    return book


def enrich_all(catalog: Catalog, client: HttpClient, *, limit: int | None = None,
               on_progress=None) -> int:
    """Enrich every not-yet-enriched book. Returns how many were processed."""
    pending = [b for b in catalog.all() if not b.enriched]
    if limit is not None:
        pending = pending[:limit]
    for i, book in enumerate(pending, 1):
        enrich_book(catalog, client, book.isbn13)
        if on_progress:
            on_progress(i, len(pending), book)
    return len(pending)


def get_detail(catalog: Catalog, client: HttpClient, isbn13: str
               ) -> tuple[CatalogBook, list[Design]] | None:
    """Return a book plus its full diagram list (enriching on demand)."""
    book = catalog.get(isbn13)
    if book is None:
        return None
    if not book.enriched:
        book = enrich_book(catalog, client, isbn13) or book
    designs: list[Design] = []
    if book.gilad_url:
        gilad_book = gilad.get_book(book.gilad_url, client)
        if gilad_book:
            designs = list(gilad_book.designs)
    return book, designs


# --------------------------------------------------------------------------
# Browsing
# --------------------------------------------------------------------------


@dataclass
class BrowseFilters:
    text: str = ""
    author: str = ""
    formats: set[str] = field(default_factory=set)
    languages: set[str] = field(default_factory=set)
    levels: set[str] = field(default_factory=set)
    in_stock_only: bool = False
    hide_kids: bool = False
    sort: str = "relevance"
    page: int = 1
    page_size: int = 24


@dataclass
class Facet:
    value: str
    count: int


@dataclass
class BrowseResult:
    items: list[CatalogBook]
    total: int                       # books matching the filters
    page: int
    page_size: int
    pages: int
    catalog_size: int
    enriched_count: int
    authors: list[Facet]
    formats: list[Facet]
    languages: list[Facet]
    levels: list[Facet]


def _matches(book: CatalogBook, f: BrowseFilters) -> bool:
    if f.text:
        haystack = f"{book.title} {book.subtitle} {book.author} {book.series_name}".lower()
        if f.text.lower() not in haystack:
            return False
    if f.author and book.author != f.author:
        return False
    if f.formats and book.format_category not in f.formats:
        return False
    if f.languages and book.language not in f.languages:
        return False
    if f.in_stock_only and not book.in_stock:
        return False
    if f.hide_kids and book.is_kids:
        return False
    if f.levels:
        # An explicit skill filter excludes books whose level is unknown (e.g.
        # paper packs Gilad doesn't rate) — only show confirmed matches.
        if not book.difficulty.is_known:
            return False
        if not any(book.difficulty.matches_bucket(b) for b in f.levels):
            return False
    return True


_SORT_KEYS = {
    "relevance": lambda b: (not b.in_stock, b.title.lower()),
    "title": lambda b: b.title.lower(),
    "price_asc": lambda b: (b.price is None, b.price or 0.0),
    "price_desc": lambda b: (b.price is None, -(b.price or 0.0)),
    "newest": lambda b: b.publish_date or "",
    "diagrams": lambda b: -b.design_count,
}


def _facet_counts(books: list[CatalogBook], key) -> list[Facet]:
    counts: dict[str, int] = {}
    for b in books:
        value = key(b)
        if value:
            counts[value] = counts.get(value, 0) + 1
    return [Facet(v, c) for v, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def browse(catalog: Catalog, filters: BrowseFilters) -> BrowseResult:
    """Filter, sort, paginate the catalogue and compute facets."""
    all_books = catalog.all()

    matched = [b for b in all_books if _matches(b, filters)]

    reverse = filters.sort == "newest"
    key = _SORT_KEYS.get(filters.sort, _SORT_KEYS["relevance"])
    matched.sort(key=key, reverse=reverse)

    total = len(matched)
    page_size = max(1, filters.page_size)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, filters.page), pages)
    start = (page - 1) * page_size
    items = matched[start:start + page_size]

    # Facets are computed over the whole catalogue so the sidebar is stable.
    level_facets = _level_facets(all_books)

    return BrowseResult(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
        catalog_size=len(all_books),
        enriched_count=sum(1 for b in all_books if b.enriched),
        authors=_facet_counts(all_books, lambda b: b.author)[:60],
        formats=_facet_counts(all_books, lambda b: b.format_category),
        languages=_facet_counts(all_books, lambda b: b.language),
        levels=level_facets,
    )


def _level_facets(books: list[CatalogBook]) -> list[Facet]:
    counts = {b: 0 for b in skill.BUCKETS}
    for book in books:
        for bucket in book.difficulty.buckets:
            counts[bucket] += 1
    return [Facet(b, counts[b]) for b in skill.BUCKETS]


def catalog_stats(catalog: Catalog) -> dict[str, int]:
    return {"total": catalog.count(), "enriched": catalog.enriched_count()}
