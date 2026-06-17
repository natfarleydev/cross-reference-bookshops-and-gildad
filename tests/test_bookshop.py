"""Parser tests against a real saved Bookshop.org product page."""

from __future__ import annotations

from origami import bookshop


def test_parse_product_core_fields(bookshop_html):
    listing = bookshop.parse_product(bookshop_html, url="https://bookshop.org/p/x")
    assert listing is not None
    assert listing.isbn13 == "9780804853101"
    assert "Origami Dragons" in listing.title
    assert "Marc Kirschenbaum" in listing.authors
    assert listing.publisher == "Tuttle Publishing"


def test_parse_product_price_and_stock(bookshop_html):
    listing = bookshop.parse_product(bookshop_html)
    assert listing.price is not None and listing.price > 0
    assert listing.currency == "USD"
    assert listing.in_stock is True


def test_parse_product_image(bookshop_html):
    listing = bookshop.parse_product(bookshop_html)
    assert listing.image_url.startswith("http")
    assert "9780804853101" in listing.image_url


def test_parse_product_no_jsonld_returns_none():
    assert bookshop.parse_product("<html><body>nothing</body></html>") is None
