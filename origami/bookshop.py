"""Bookshop.org lookup by ISBN.

Bookshop's search UI is a client-side Algolia app (not scrapeable from static
HTML), but it exposes a stable redirect: ``/book/<isbn13>`` -> the product page.
The product page embeds a clean ``application/ld+json`` Product/Book blob with
title, authors, publisher, price, availability and cover image. That JSON-LD is
all we parse, which makes us robust to front-end churn.

Only ISBN-13 resolves (ISBN-10 404s), so callers must normalise first; the
``lookup`` helper does this for you.
"""

from __future__ import annotations

import json

from bs4 import BeautifulSoup

from . import config
from . import isbn as isbn_utils
from .cache import HttpClient
from .models import BookshopListing


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _find_book_node(data) -> dict | None:
    """Locate the Product/Book object inside a parsed JSON-LD document."""
    if isinstance(data, list):
        for item in data:
            node = _find_book_node(item)
            if node:
                return node
        return None
    if isinstance(data, dict):
        types = _as_list(data.get("@type"))
        if any(t in ("Book", "Product") for t in types):
            return data
        if "@graph" in data:
            return _find_book_node(data["@graph"])
    return None


def _extract_authors(node: dict) -> tuple[str, ...]:
    authors = []
    for a in _as_list(node.get("author")):
        if isinstance(a, dict) and a.get("name"):
            authors.append(a["name"])
        elif isinstance(a, str):
            authors.append(a)
    return tuple(authors)


def _extract_price(node: dict) -> tuple[float | None, str]:
    offers = node.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if not isinstance(offers, dict):
        # Some pages put price directly on the node.
        price = node.get("price")
        currency = node.get("priceCurrency", "USD")
    else:
        price = offers.get("price")
        currency = offers.get("priceCurrency", "USD")
    try:
        price = float(price) if price is not None and price != "" else None
    except (TypeError, ValueError):
        price = None
    return price, (currency or "USD").upper()


def _availability(node: dict) -> str:
    offers = node.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    avail = ""
    if isinstance(offers, dict):
        avail = offers.get("availability", "")
    if not avail:
        avail = node.get("availability", "")
    # Normalise "https://schema.org/InStock" -> "InStock".
    return avail.rsplit("/", 1)[-1] if avail else ""


def parse_product(html: str, url: str = "") -> BookshopListing | None:
    """Parse a Bookshop product page (via its JSON-LD) into a listing."""
    soup = BeautifulSoup(html, "lxml")
    node = None
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        if not script.string and not script.text:
            continue
        try:
            data = json.loads(script.string or script.text)
        except (json.JSONDecodeError, TypeError):
            continue
        node = _find_book_node(data)
        if node:
            break
    if node is None:
        return None

    isbn13 = node.get("isbn") or node.get("gtin13") or node.get("sku") or ""
    isbn13 = isbn_utils.to_isbn13(isbn13) or isbn13
    image = node.get("image")
    if isinstance(image, list):
        image = image[0] if image else ""
    brand = node.get("brand")
    publisher = ""
    if isinstance(brand, dict):
        publisher = brand.get("name", "")
    elif isinstance(node.get("publisher"), dict):
        publisher = node["publisher"].get("name", "")

    price, currency = _extract_price(node)

    return BookshopListing(
        isbn13=isbn13,
        title=node.get("name", ""),
        url=url,
        authors=_extract_authors(node),
        publisher=publisher,
        price=price,
        currency=currency,
        availability=_availability(node),
        image_url=image or "",
        description=node.get("description", ""),
    )


def lookup(isbn_code: str, client: HttpClient) -> BookshopListing | None:
    """Look up a book on Bookshop by any ISBN-10/13.

    Returns ``None`` if the identifier isn't a real ISBN or Bookshop has no
    listing (404). The 404 itself is cached, so unavailable books are only
    queried once.
    """
    isbn13 = isbn_utils.to_isbn13(isbn_code)
    if not isbn13:
        return None
    url = config.BOOKSHOP_ISBN_URL.format(isbn13=isbn13)
    resp = client.get(url)
    if resp.status_code != 200:
        return None
    listing = parse_product(resp.text, url=resp.url or url)
    return listing
