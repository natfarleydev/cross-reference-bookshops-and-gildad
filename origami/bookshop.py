"""Bookshop.org product source (the authoritative "what can I buy" list).

Bookshop's storefront is an instant-meilisearch app. Its proxy at
``/api/next/instantsearch/multi-search`` speaks the Meilisearch ``/multi-search``
protocol and needs no API key, returning clean structured JSON per product
(title, ISBN/``ean``, author, price in minor units, stock status, cover, format).

We use it two ways:

* :func:`harvest` – page through every origami product to build the catalogue.
* :func:`lookup` – fetch a single product by ISBN (used to refresh one book).

Prices come back as integer minor units (pence/cents); we convert to major units.
"""

from __future__ import annotations

import json

from . import config
from .cache import HttpClient
from .config import Region
from .models import BookshopBook


def _parse_hit(hit: dict, region: Region) -> BookshopBook:
    price_minor = hit.get("price")
    price = None
    if isinstance(price_minor, int | float):
        price = round(price_minor / 100.0, 2)

    contributors = tuple(
        c.get("name", "") for c in (hit.get("contributors") or []) if c.get("name")
    )

    def s(key: str) -> str:
        """Get a string field, coercing JSON null/missing to ''."""
        return str(hit.get(key) or "")

    path = s("path")
    url = f"{region.base}/{path.lstrip('/')}" if path else ""
    currency = (hit.get("currency") or region.currency).upper()

    return BookshopBook(
        isbn13=s("ean"),
        title=s("title"),
        subtitle=s("subtitle"),
        author=s("primary_contributor"),
        contributors=contributors,
        price=price,
        currency=currency,
        status=s("status"),
        cover_url=s("cover_url"),
        url=url,
        publish_date=s("publish_date"),
        format_category=s("format_category"),
        language=s("language_code"),
        series_name=s("series_name"),
    )


def parse_results(text: str, region: Region) -> tuple[list[BookshopBook], int]:
    """Parse a multi-search response into (books, estimated_total)."""
    data = json.loads(text)
    results = data.get("results") or []
    if not results:
        return [], 0
    first = results[0]
    hits = [_parse_hit(h, region) for h in first.get("hits", [])]
    total = int(first.get("estimatedTotalHits", len(hits)))
    return hits, total


def search_page(
    client: HttpClient,
    query: str,
    *,
    offset: int = 0,
    limit: int = 100,
    region: Region | None = None,
    force_refresh: bool = False,
) -> tuple[list[BookshopBook], int]:
    """Fetch one page of products for ``query``."""
    region = region or config.REGION
    payload = {
        "queries": [
            {
                "indexUid": config.BOOKSHOP_INDEX,
                "q": query,
                "offset": offset,
                "limit": limit,
            }
        ]
    }
    resp = client.post_json(region.multi_search_url, payload, force_refresh=force_refresh)
    if resp.status_code != 200:
        return [], 0
    return parse_results(resp.text, region)


def harvest(
    client: HttpClient,
    *,
    query: str | None = None,
    region: Region | None = None,
    page_size: int = 100,
    max_books: int | None = None,
    force_refresh: bool = False,
) -> list[BookshopBook]:
    """Page through *all* products matching ``query`` (default: origami).

    Deduplicates by ISBN and stops at ``max_books`` if given.
    """
    region = region or config.REGION
    query = query if query is not None else config.CATALOG_QUERY

    books: list[BookshopBook] = []
    seen: set[str] = set()
    offset = 0
    total = None
    while True:
        page, total = search_page(
            client, query, offset=offset, limit=page_size,
            region=region, force_refresh=force_refresh,
        )
        if not page:
            break
        for b in page:
            if b.isbn13 and b.isbn13 not in seen:
                seen.add(b.isbn13)
                books.append(b)
        offset += page_size
        if max_books is not None and len(books) >= max_books:
            return books[:max_books]
        if offset >= total:
            break
    return books


def lookup(isbn13: str, client: HttpClient, region: Region | None = None) -> BookshopBook | None:
    """Look up a single product by ISBN via the search index."""
    region = region or config.REGION
    page, _ = search_page(client, isbn13, offset=0, limit=5, region=region)
    for b in page:
        if b.isbn13 == isbn13:
            return b
    return page[0] if page else None
