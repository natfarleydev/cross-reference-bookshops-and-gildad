"""Cross-reference orchestration.

Joins the two sources into the thing the user actually wants: a list of origami
*books* that contain diagrams for what they searched, each annotated with its
skill level (from Gilad) and its Bookshop.org price/availability/buy link.

Flow for a query:

    Gilad search  ->  group rows by book  ->  fetch each book page (skill level
    + full diagram list, cached)  ->  look the book up on Bookshop by ISBN
    (cached)  ->  apply filters (skill, kids, bookshop-only)  ->  sorted results.

Everything is cache-first, so the first search for a term is slow (it warms the
cache) and every search after it is effectively instant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import bookshop, gilad, skill
from .cache import HttpClient
from .gilad import SearchHit
from .models import CrossRef, Design, GiladBook

# Handy entry points for the homepage – common things people fold.
POPULAR_SUBJECTS = (
    "dragon", "rose", "crane", "modular", "box", "star",
    "elephant", "butterfly", "dollar bill", "tessellation",
)

# Title patterns that strongly imply a children's / very-beginner book. Used for
# the optional "hide kids' books" filter (off by default – we don't exclude them
# unless asked).
_KIDS_RE = re.compile(
    r"\b(kids?|children|child|toddler|preschool|kindergarten|"
    r"for beginners|year[\s-]?olds?|ages?\s*\d)\b",
    re.IGNORECASE,
)


def is_kids_book(title: str) -> bool:
    return bool(_KIDS_RE.search(title or ""))


@dataclass
class SearchResult:
    """Everything the results view needs to render."""

    query: str
    crossrefs: list[CrossRef] = field(default_factory=list)
    total_books_found: int = 0       # before filtering
    filtered_out: int = 0
    bookshop_misses: int = 0         # books with no Bookshop listing


def _group_hits(hits: list[SearchHit]) -> dict[str, list[SearchHit]]:
    groups: dict[str, list[SearchHit]] = {}
    for hit in hits:
        groups.setdefault(hit.book_key, []).append(hit)
    return groups


def _book_from_hits(hits: list[SearchHit]) -> GiladBook:
    """Build a *partial* book (no skill level / full diagram list) purely from
    search rows – used when we can't or don't fetch the full book page."""
    first = hits[0]
    asins: list[str] = []
    for h in hits:
        for code in h.amazon_asins:
            if code not in asins:
                asins.append(code)
    from . import isbn as isbn_utils

    isbn13 = None
    for code in asins:
        isbn13 = isbn_utils.to_isbn13(code)
        if isbn13:
            break
    designs = tuple(h.design for h in hits)
    return GiladBook(
        book_id=first.book_id,
        title=first.book_title,
        author=first.book_author,
        url=first.book_url,
        cover_url=first.cover_url,
        isbn13=isbn13,
        amazon_asins=tuple(asins),
        difficulty=skill.parse(None),  # unknown
        designs=designs,
        technical={},
    )


def _matched_designs(book: GiladBook, hits: list[SearchHit]) -> tuple[Design, ...]:
    """The designs from this book that actually matched the search (by name)."""
    wanted = {h.design.name.lower() for h in hits}
    matched = tuple(d for d in book.designs if d.name.lower() in wanted)
    return matched or tuple(h.design for h in hits)


def cross_reference(
    query: str,
    client: HttpClient,
    *,
    levels: set[str] | None = None,
    include_kids: bool = True,
    bookshop_only: bool = False,
    fetch_details: bool = True,
    detail_limit: int = 60,
    lookup_bookshop: bool = True,
) -> SearchResult:
    """Search Gilad for ``query`` and cross-reference each book with Bookshop.

    Parameters
    ----------
    levels:
        Coarse skill buckets to keep (subset of :data:`origami.skill.BUCKETS`).
        ``None`` keeps everything. Books with unknown difficulty are always
        kept (we never silently drop a book for lacking a rating).
    include_kids:
        When ``False``, books whose title looks like a children's book are
        dropped.
    bookshop_only:
        When ``True``, only books with a live Bookshop listing are returned.
    fetch_details:
        When ``True`` (default), each book's full page is fetched to obtain its
        skill level and complete diagram list. Capped by ``detail_limit``.
    """
    hits = gilad.search(query, client)
    groups = _group_hits(hits)

    result = SearchResult(query=query, total_books_found=len(groups))

    for idx, (_key, group) in enumerate(groups.items()):
        want_detail = fetch_details and idx < detail_limit and group[0].book_id
        book: GiladBook | None = None
        if want_detail:
            book = gilad.get_book(group[0].book_url, client)
        if book is None:
            book = _book_from_hits(group)
        else:
            # Preserve the cover from search if the book page lacked one, and
            # narrow the diagram list shown in results to what matched.
            if not book.cover_url:
                book = _replace_cover(book, group[0].cover_url)

        # Skill-level filter.
        if levels is not None and not any(book.difficulty.matches_bucket(b) for b in levels):
            result.filtered_out += 1
            continue
        # Kids filter.
        if not include_kids and is_kids_book(book.title):
            result.filtered_out += 1
            continue

        listing = None
        if lookup_bookshop and book.isbn13:
            listing = bookshop.lookup(book.isbn13, client)
        if listing is None:
            result.bookshop_misses += 1
            if bookshop_only:
                result.filtered_out += 1
                continue

        result.crossrefs.append(CrossRef(book=book, listing=listing))

    # Sort: on Bookshop first, then more diagrams, then title.
    result.crossrefs.sort(
        key=lambda c: (not c.on_bookshop, -c.book.design_count, c.title.lower())
    )
    return result


def _replace_cover(book: GiladBook, cover_url: str) -> GiladBook:
    from dataclasses import replace

    return replace(book, cover_url=cover_url)
