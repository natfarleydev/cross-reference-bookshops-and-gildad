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


def test_parse_handles_null_fields():
    # Bookshop sometimes sends contributors:null and missing price/path.
    payload = (
        '{"results":[{"estimatedTotalHits":1,"hits":[{'
        '"ean":"9780000000001","title":"X","contributors":null,'
        '"primary_contributor":null}]}]}'
    )
    books, total = bookshop.parse_results(payload, REGIONS["uk"])
    assert total == 1
    assert books[0].contributors == ()
    assert books[0].author == ""
    assert books[0].price is None


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


class RecordingClient:
    """Serves the same fixture once per query, recording the queries it saw."""

    def __init__(self, text):
        self.text = text
        self.seen_queries: list[str] = []

    def post_json(self, url, payload, force_refresh=False):
        q = payload["queries"][0]["q"]
        # First page of each query returns the fixture; the next page is empty.
        if self.seen_queries.count(q) == 0 and payload["queries"][0]["offset"] == 0:
            self.seen_queries.append(q)
            return FakeResp(self.text)
        return FakeResp('{"results":[{"hits":[],"estimatedTotalHits":546}]}')


def test_harvest_merges_multiple_queries_deduped(bookshop_meili_json):
    # Two queries that both return the same fixture must merge to one deduped set,
    # and each query must actually be issued. subjects=() keeps this focused on
    # the text-query merge (no extra subject-filter pass).
    client = RecordingClient(bookshop_meili_json)
    books = bookshop.harvest(
        client,
        queries=["origami", "paper engineering"],
        subjects=(),
        region=REGIONS["uk"],
        page_size=5,
    )
    assert client.seen_queries == ["origami", "paper engineering"]
    isbns = [b.isbn13 for b in books]
    assert len(isbns) == len(set(isbns))  # deduped across queries
    assert len(books) == 5  # identical fixtures collapse to a single set


def test_search_page_filters_by_subjects(bookshop_meili_json):
    # Passing subjects must add a Meilisearch OR-filter on the subjects attribute.
    captured: dict = {}

    class Capturing:
        def post_json(self, url, payload, force_refresh=False):
            captured["payload"] = payload
            return FakeResp(bookshop_meili_json)

    bookshop.search_page(Capturing(), "", subjects=["WFTM", "WFT"], region=REGIONS["uk"])
    assert captured["payload"]["queries"][0]["filter"] == [
        ["subjects = WFTM", "subjects = WFT"]
    ]


def test_harvest_runs_text_and_subject_searches(bookshop_meili_json):
    # harvest must issue the text query *and* a subject-filter search (q=""),
    # then merge both into one deduped set.
    served: set = set()
    calls: list = []

    class SubjectAware:
        def post_json(self, url, payload, force_refresh=False):
            q0 = payload["queries"][0]
            fkey = tuple(tuple(x) for x in q0["filter"]) if q0.get("filter") else None
            calls.append((q0["q"], fkey))
            key = (q0["q"], fkey)
            # First page of each distinct (query, filter) returns the fixture.
            if q0["offset"] == 0 and key not in served:
                served.add(key)
                return FakeResp(bookshop_meili_json)
            return FakeResp('{"results":[{"hits":[],"estimatedTotalHits":546}]}')

    books = bookshop.harvest(
        SubjectAware(),
        queries=["origami"],
        subjects=["WFTM", "WFT"],
        region=REGIONS["uk"],
        page_size=5,
    )
    text_calls = [c for c in calls if c[1] is None]
    subj_calls = [c for c in calls if c[1] is not None]
    assert ("origami", None) in text_calls
    assert subj_calls[0][1] == (("subjects = WFTM", "subjects = WFT"),)
    assert subj_calls[0][0] == ""  # subject pass uses an empty text query
    isbns = [b.isbn13 for b in books]
    assert len(isbns) == len(set(isbns))  # deduped across both searches
    assert len(books) == 5  # identical fixtures collapse to a single set


def test_default_scope_is_origami_text_plus_subject_filter():
    from origami import config

    # Text scope is tight (just "origami"); breadth comes from the subject filter.
    assert config.CATALOG_QUERIES == ("origami",)
    # BIC/Thema "Origami & paper engineering" is a real server-side filter now.
    assert "WFTM" in config.BOOKSHOP_SUBJECTS  # origami & paper folding
    assert "WFT" in config.BOOKSHOP_SUBJECTS  # paper crafts & paper engineering
