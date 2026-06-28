"""Tests for the SQLite catalogue store (in-memory)."""

from __future__ import annotations

from dataclasses import replace

from origami import skill
from origami.catalog import Catalog
from origami.models import CatalogBook
from origami.skill import Difficulty


def make_book(isbn="9780000000001", **kw) -> CatalogBook:
    base = dict(isbn13=isbn, title="Test Book", author="A Person", price=12.5, status="in stock")
    base.update(kw)
    return CatalogBook(**base)


def test_gilad_status_states():
    # Fresh from Bookshop: lookup not yet attempted.
    pending = make_book()
    assert not pending.in_gilad
    assert pending.gilad_status == "pending"

    # Enriched but Gilad has no matching record: still a valid book, just absent.
    absent = replace(pending, enriched=True)
    assert not absent.in_gilad
    assert absent.gilad_status == "absent"

    # Enriched with a real Gilad match.
    found = replace(pending, enriched=True, gilad_book_id="3795",
                    gilad_url="https://www.giladorigami.com/origami-database-book/3795")
    assert found.in_gilad
    assert found.gilad_status == "found"


def test_upsert_and_get():
    cat = Catalog(":memory:")
    cat.upsert(make_book())
    got = cat.get("9780000000001")
    assert got is not None
    assert got.title == "Test Book"
    assert got.price == 12.5
    assert got.in_stock


def test_upsert_preserves_enrichment_on_reharvest():
    cat = Catalog(":memory:")
    cat.upsert(make_book())
    enriched = replace(
        cat.get("9780000000001"),
        difficulty=Difficulty(skill.INTERMEDIATE, skill.INTERMEDIATE, "Intermediate"),
        design_count=12, gilad_book_id="3795", enriched=True,
    )
    cat.set_enrichment(enriched)

    # Re-harvest writes the same book again (bookshop columns only) ...
    cat.upsert(make_book(price=9.99))
    got = cat.get("9780000000001")
    assert got.price == 9.99               # bookshop field updated
    assert got.enriched                    # enrichment preserved
    assert got.design_count == 12
    assert got.difficulty.low == skill.INTERMEDIATE


def test_counts_and_all():
    cat = Catalog(":memory:")
    cat.upsert_many([make_book("9780000000001"), make_book("9780000000002")])
    assert cat.count() == 2
    assert cat.enriched_count() == 0
    assert {b.isbn13 for b in cat.all()} == {"9780000000001", "9780000000002"}
    assert not cat.is_empty()


def test_clear():
    cat = Catalog(":memory:")
    cat.upsert(make_book())
    cat.clear()
    assert cat.is_empty()
