"""Tests for the cache-first HTTP client (no real network)."""

from __future__ import annotations

import time

import pytest

from origami.cache import CacheMiss, HttpClient


class FakeResponse:
    def __init__(self, url, status_code=200, text="body"):
        self.url = url
        self.status_code = status_code
        self.text = text


class FakeSession:
    """Counts calls so we can assert the cache prevents network hits."""

    def __init__(self, responses=None):
        self.headers = {}
        self.calls = 0
        self.responses = responses or {}

    def get(self, url, timeout=None, allow_redirects=True):
        self.calls += 1
        resp = self.responses.get(url)
        if resp is None:
            return FakeResponse(url, 200, f"live:{url}:{self.calls}")
        return resp


def make_client(session=None, **kw):
    kw.setdefault("request_delay", 0)
    return HttpClient(db_path=":memory:", session=session or FakeSession(), **kw)


def test_first_fetch_is_live_then_cached():
    session = FakeSession()
    client = make_client(session)

    r1 = client.get("http://x/a")
    assert r1.from_cache is False
    assert session.calls == 1

    r2 = client.get("http://x/a")
    assert r2.from_cache is True
    assert r2.text == r1.text
    assert session.calls == 1  # no second network call


def test_force_refresh_bypasses_cache():
    session = FakeSession()
    client = make_client(session)
    client.get("http://x/a")
    client.get("http://x/a", force_refresh=True)
    assert session.calls == 2


def test_stale_entry_refetched():
    session = FakeSession()
    client = make_client(session, ttl_seconds=0)
    client.get("http://x/a")
    time.sleep(0.01)
    r2 = client.get("http://x/a")
    assert r2.from_cache is False
    assert session.calls == 2


def test_offline_serves_stale_but_raises_on_miss():
    session = FakeSession()
    client = make_client(session)
    client.get("http://x/a")  # populate

    offline = HttpClient(db_path=":memory:", session=session, request_delay=0, offline=True)
    # offline client shares no DB with the first (in-memory, separate), so miss:
    with pytest.raises(CacheMiss):
        offline.get("http://x/a")


def test_offline_serves_existing_cache():
    session = FakeSession()
    client = make_client(session)
    client.get("http://x/a")
    client.offline = True
    # Past TTL but offline -> still served from cache.
    client.ttl_seconds = 0
    r = client.get("http://x/a")
    assert r.from_cache is True
    assert session.calls == 1


def test_5xx_not_cached():
    session = FakeSession({"http://x/err": FakeResponse("http://x/err", 503, "down")})
    client = make_client(session)
    client.get("http://x/err")
    client.get("http://x/err")
    assert session.calls == 2  # retried, not cached


def test_404_is_cached():
    session = FakeSession({"http://x/missing": FakeResponse("http://x/missing", 404, "nope")})
    client = make_client(session)
    client.get("http://x/missing")
    client.get("http://x/missing")
    assert session.calls == 1  # 404 is a stable answer, cached


def test_stats():
    client = make_client()
    client.get("http://x/a")
    client.get("http://x/b")
    stats = client.stats()
    assert stats["total"] == 2
    assert stats["fresh"] == 2
