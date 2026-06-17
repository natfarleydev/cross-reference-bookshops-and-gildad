"""Tests for the Bookshop Meilisearch client against a real saved response."""

from __future__ import annotations

from origami import bookshop
from origami.config import REGIONS


def test_parse_results(bookshop_meili_json):
    books, total = bookshop.parse_results(bookshop_meili_json, REGIONS["uk"])
    assert total == 546
    assert len(books) == 5
    b = books[0]
    assert b.isbn13 and len(b.isbn13) == 13
    assert b.title
    assert b.author


def test_price_converted_to_major_units(bookshop_meili_json):
    books, _ = bookshop.parse_results(bookshop_meili_json, REGIONS["uk"])
    # Prices come back in pence; every parsed price should be a sensible £ value.
    priced = [b for b in books if b.price is not None]
    assert priced
    for b in priced:
        assert 0 < b.price < 200
        assert b.currency == "GBP"


def test_product_url_and_stock(bookshop_meili_json):
    books, _ = bookshop.parse_results(bookshop_meili_json, REGIONS["uk"])
    b = books[0]
    assert b.url.startswith("https://uk.bookshop.org/")
    # in_stock reflects the status string.
    assert b.in_stock == (b.status.lower().strip() == "in stock")


class FakeResp:
    def __init__(self, text, status=200, url="http://x"):
        self.text, self.status_code, self.url = text, status, url


class FakeClient:
    """Returns the same fixture page once, then an empty page (ends pagination)."""

    def __init__(self, text):
        self.text = text
        self.posts = 0

    def post_json(self, url, payload, force_refresh=False):
        self.posts += 1
        if self.posts == 1:
            return FakeResp(self.text)
        return FakeResp('{"results":[{"hits":[],"estimatedTotalHits":546}]}')


def test_harvest_dedupes_and_paginates(bookshop_meili_json):
    client = FakeClient(bookshop_meili_json)
    books = bookshop.harvest(client, region=REGIONS["uk"], page_size=5, max_books=5)
    assert len(books) == 5
    isbns = [b.isbn13 for b in books]
    assert len(isbns) == len(set(isbns))  # deduped
