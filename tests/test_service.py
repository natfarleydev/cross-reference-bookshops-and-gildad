"""Tests for the service layer: browsing, filtering, enrichment, detail."""

from __future__ import annotations

from origami import service, skill
from origami.catalog import Catalog
from origami.models import CatalogBook
from origami.service import BrowseFilters
from origami.skill import Difficulty
from tests.conftest import load_fixture

# --------------------------------------------------------------------------
# Browsing / filtering (pure, over a hand-built catalogue)
# --------------------------------------------------------------------------


def _catalog() -> Catalog:
    cat = Catalog(":memory:")
    cat.upsert_many([
        CatalogBook(isbn13="1", title="Origami Dragons", author="Marc K", status="in stock",
                    price=15.0, format_category="Paperback", design_count=10,
                    difficulty=Difficulty(skill.SIMPLE, skill.COMPLEX, "simple to complex"),
                    enriched=True),
        CatalogBook(isbn13="2", title="Easy Origami for Kids", author="John M", status="backorder",
                    price=5.0, format_category="Paperback", design_count=20,
                    difficulty=Difficulty(skill.SIMPLE, skill.SIMPLE, "simple"), enriched=True),
        CatalogBook(isbn13="3", title="Complex Origami", author="Marc K", status="in stock",
                    price=30.0, format_category="Hardback", design_count=5,
                    difficulty=Difficulty(skill.COMPLEX, skill.SUPER_COMPLEX, "complex"),
                    enriched=True),
    ])
    return cat


def test_browse_text_filter():
    res = service.browse(_catalog(), BrowseFilters(text="dragon"))
    assert [b.isbn13 for b in res.items] == ["1"]


def test_browse_in_stock_filter():
    res = service.browse(_catalog(), BrowseFilters(in_stock_only=True))
    assert {b.isbn13 for b in res.items} == {"1", "3"}


def test_browse_hide_kids():
    res = service.browse(_catalog(), BrowseFilters(hide_kids=True))
    assert "2" not in {b.isbn13 for b in res.items}


def test_browse_level_filter():
    res = service.browse(_catalog(), BrowseFilters(levels={skill.BUCKET_COMPLEX}))
    # Book 1 spans simple..complex (overlaps), book 3 is complex; book 2 is simple only.
    assert {b.isbn13 for b in res.items} == {"1", "3"}


def test_browse_author_filter():
    res = service.browse(_catalog(), BrowseFilters(author="Marc K"))
    assert {b.isbn13 for b in res.items} == {"1", "3"}


def test_browse_sort_price():
    res = service.browse(_catalog(), BrowseFilters(sort="price_asc"))
    assert [b.isbn13 for b in res.items] == ["2", "1", "3"]


def test_browse_facets():
    res = service.browse(_catalog(), BrowseFilters())
    authors = {f.value: f.count for f in res.authors}
    assert authors["Marc K"] == 2
    formats = {f.value: f.count for f in res.formats}
    assert formats["Paperback"] == 2
    assert res.catalog_size == 3


def test_browse_pagination():
    res = service.browse(_catalog(), BrowseFilters(page=1, page_size=2))
    assert len(res.items) == 2
    assert res.pages == 2


# --------------------------------------------------------------------------
# Catalogue building / enrichment (fake client wired to fixtures)
# --------------------------------------------------------------------------


class FakeResp:
    def __init__(self, text, status=200, url="http://x"):
        self.text, self.status_code, self.url = text, status, url


class FakeClient:
    def __init__(self):
        self.meili = load_fixture("bookshop_meili_origami.json")
        self.search = load_fixture("gilad_search_wyvern.html")
        self.book = load_fixture("gilad_book_3795_origami_dragons.html")
        self._posts = 0

    def post_json(self, url, payload, force_refresh=False):
        self._posts += 1
        if self._posts == 1:
            return FakeResp(self.meili)
        return FakeResp('{"results":[{"hits":[],"estimatedTotalHits":546}]}')

    def get(self, url, force_refresh=False):
        if "origami-database-book" in url:
            return FakeResp(self.book, url=url)
        return FakeResp(self.search, url=url)  # database-redirect search


def test_ensure_catalog_harvests():
    cat = Catalog(":memory:")
    n = service.ensure_catalog(cat, FakeClient())
    assert n == 5
    assert cat.count() == 5
    # Idempotent: second call doesn't re-harvest.
    assert service.ensure_catalog(cat, FakeClient()) == 5


def test_enrich_book_adds_skill():
    cat = Catalog(":memory:")
    service.ensure_catalog(cat, FakeClient())
    target = cat.all()[0].isbn13
    enriched = service.enrich_book(cat, FakeClient(), target)
    assert enriched.enriched
    assert enriched.difficulty.is_known
    assert enriched.gilad_book_id          # resolved a Gilad book page
    assert enriched.design_count > 0


def test_get_detail_returns_designs():
    cat = Catalog(":memory:")
    service.ensure_catalog(cat, FakeClient())
    isbn = cat.all()[0].isbn13
    book, designs = service.get_detail(cat, FakeClient(), isbn)
    assert book.enriched
    assert len(designs) > 0
    assert any(d.name == "Dragon footprint" for d in designs)
