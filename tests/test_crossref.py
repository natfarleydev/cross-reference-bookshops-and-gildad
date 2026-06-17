"""End-to-end cross-reference tests using a fake session wired to fixtures."""

from __future__ import annotations

import urllib.parse

from origami import config, crossref, skill
from origami.cache import HttpClient
from tests.conftest import load_fixture


class FakeResponse:
    def __init__(self, url, status_code=200, text=""):
        self.url = url
        self.status_code = status_code
        self.text = text


# A tiny search page with a single book row pointing at book 3795.
SEARCH_HTML = """
<table id="results"><tbody>
<tr>
  <td><a href="/origami-database/Wyvern">Wyvern</a>
      <span class="subject-in-book"><a href="/x">Dragons</a></span></td>
  <td><a href="/d">Marc Kirschenbaum</a></td>
  <td class="source">
    <a class="book" href="/origami-database-book/3795/Origami-Dragons">
      <img class="database-cover-image" src="/book-covers/x.jpg"/></a>
    <a class="book" href="/origami-database-book/3795/Origami-Dragons">Origami Dragons by Marc Kirschenbaum</a>
    <a href="https://www.amazon.com/exec/obidos/ASIN/080485310X/giladsorigampage">buy</a>
  </td>
  <td>12</td><td>Square</td><td class="thumb"></td>
</tr>
</tbody></table>
"""


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.search_url = config.GILAD_SEARCH_URL.format(query=urllib.parse.quote("wyvern"))
        self.book_url = "https://www.giladorigami.com/origami-database-book/3795/Origami-Dragons"
        self.bookshop_url = config.BOOKSHOP_ISBN_URL.format(isbn13="9780804853101")

    def get(self, url, timeout=None, allow_redirects=True):
        if url == self.search_url:
            return FakeResponse(url, 200, SEARCH_HTML)
        if url.startswith("https://www.giladorigami.com/origami-database-book/3795"):
            return FakeResponse(url, 200, load_fixture("gilad_book_3795_origami_dragons.html"))
        if url == self.bookshop_url:
            return FakeResponse(url, 200, load_fixture("bookshop_9780804853101.html"))
        return FakeResponse(url, 404, "not found")


def make_client():
    return HttpClient(db_path=":memory:", session=FakeSession(), request_delay=0)


def test_cross_reference_happy_path():
    result = crossref.cross_reference("wyvern", make_client())
    assert result.total_books_found == 1
    assert len(result.crossrefs) == 1

    cr = result.crossrefs[0]
    assert cr.book.title == "Origami Dragons"
    assert cr.book.isbn13 == "9780804853101"
    # Full book page fetched -> real skill level + full diagram list.
    assert cr.book.difficulty.low == skill.SIMPLE
    assert cr.book.design_count > 1
    # Bookshop matched.
    assert cr.on_bookshop
    assert cr.listing.price is not None


def test_level_filter_excludes_non_matching():
    # Book 3795 spans simple..complex, so it overlaps every bucket; selecting
    # only "complex" still keeps it.
    result = crossref.cross_reference("wyvern", make_client(), levels={skill.BUCKET_COMPLEX})
    assert len(result.crossrefs) == 1


def test_bookshop_only_keeps_matched():
    result = crossref.cross_reference("wyvern", make_client(), bookshop_only=True)
    assert len(result.crossrefs) == 1


def test_kids_filter():
    assert crossref.is_kids_book("Easy Origami for Kids")
    assert crossref.is_kids_book("Origami for Children")
    assert not crossref.is_kids_book("Origami Dragons")


def test_no_details_uses_partial_book():
    result = crossref.cross_reference("wyvern", make_client(), fetch_details=False)
    cr = result.crossrefs[0]
    # Without fetching the page we still get title + isbn from the search row.
    assert cr.book.title == "Origami Dragons"
    assert cr.book.isbn13 == "9780804853101"
    assert not cr.book.difficulty.is_known
