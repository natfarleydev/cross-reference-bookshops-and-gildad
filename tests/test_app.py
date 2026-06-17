"""Flask route smoke tests with a fake-session client (no real network)."""

from __future__ import annotations

import pytest

import app as app_module
from origami.cache import HttpClient
from tests.test_crossref import FakeSession


@pytest.fixture
def client(monkeypatch):
    # Swap the app's shared HTTP client for one wired to fixtures.
    fake = HttpClient(db_path=":memory:", session=FakeSession(), request_delay=0)
    monkeypatch.setattr(app_module, "client", fake)
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Origami Book Finder" in resp.data
    assert b"Popular" in resp.data


def test_search_renders_results(client):
    resp = client.get("/search?q=wyvern")
    assert resp.status_code == 200
    assert b"Origami Dragons" in resp.data
    assert b"Bookshop.org" in resp.data
    # Skill badge from the fetched book page.
    assert b"Simple" in resp.data


def test_search_empty_query_redirects(client):
    resp = client.get("/search?q=")
    assert resp.status_code == 302


def test_search_with_level_filter(client):
    resp = client.get("/search?q=wyvern&level=complex")
    assert resp.status_code == 200
    assert b"Origami Dragons" in resp.data


def test_book_detail_renders(client):
    resp = client.get("/book/3795")
    assert resp.status_code == 200
    assert b"Diagrams in this book" in resp.data
    assert b"Dragon footprint" in resp.data


def test_book_not_found(client):
    resp = client.get("/book/000000")
    assert resp.status_code == 404
    assert b"not found" in resp.data.lower()
