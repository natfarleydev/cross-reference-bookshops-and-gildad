"""FastAPI route tests using dependency_overrides (no real network)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as app_module
from origami.catalog import Catalog
from origami.deps import get_catalog, get_client
from origami.models import CatalogBook
from origami.skill import INTERMEDIATE, Difficulty
from tests.test_service import FakeClient


@pytest.fixture
def client():
    cat = Catalog(":memory:")
    cat.upsert_many([
        CatalogBook(isbn13="9781111111111", title="Origami Dragons", author="Marc K",
                    price=15.0, status="in stock", format_category="Paperback",
                    design_count=10, difficulty=Difficulty(INTERMEDIATE, INTERMEDIATE, "Intermediate"),
                    enriched=True),
        CatalogBook(isbn13="9782222222222", title="Kusudama Magic", author="Tomoko F",
                    price=9.0, status="backorder", format_category="Paperback", enriched=True),
    ])
    fake_client = FakeClient()
    app_module.app.dependency_overrides[get_catalog] = lambda: cat
    app_module.app.dependency_overrides[get_client] = lambda: fake_client
    yield TestClient(app_module.app)
    app_module.app.dependency_overrides.clear()


def test_browse_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Origami Dragons" in resp.text
    assert "Kusudama Magic" in resp.text
    assert "£15.00" in resp.text          # UK currency formatting


def test_browse_text_filter(client):
    resp = client.get("/?q=dragons")
    assert "Origami Dragons" in resp.text
    assert "Kusudama Magic" not in resp.text


def test_browse_in_stock_filter(client):
    resp = client.get("/?in_stock=true")
    assert "Origami Dragons" in resp.text
    assert "Kusudama Magic" not in resp.text


def test_book_detail(client):
    resp = client.get("/book/9781111111111")
    assert resp.status_code == 200
    assert "Diagrams in this book" in resp.text
    assert "Buy on Bookshop.org" in resp.text


def test_book_not_found(client):
    resp = client.get("/book/0000000000000")
    assert resp.status_code == 404
    assert "not in the catalogue" in resp.text.lower()


def test_book_without_gilad_record_is_still_shown_and_labelled(client):
    # Kusudama Magic is enriched but has no Gilad match: it must still appear in
    # browse, and be clearly labelled rather than silently blank.
    resp = client.get("/")
    assert "Kusudama Magic" in resp.text
    assert "Not in Gilad" in resp.text

    detail = client.get("/book/9782222222222")
    assert detail.status_code == 200
    assert "Not in Gilad" in detail.text
    assert "diagram database" in detail.text  # explains why there's no diagram list
