"""Aggressive SQLite-backed HTTP cache.

Every outbound request in the whole app goes through :class:`HttpClient.get`.
A cache hit (fresh by TTL) never touches the network; this is what keeps us from
hammering Gilad and Bookshop. Responses are stored permanently and only
*considered stale* once older than the TTL, so even an "expired" entry survives
to back offline mode and manual inspection.

The client is deliberately tiny and dependency-light: ``requests`` for fetching,
``sqlite3`` (stdlib) for storage.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from . import config


@dataclass(frozen=True)
class CachedResponse:
    """The result of a :meth:`HttpClient.get` call."""

    url: str            # final URL after redirects
    status_code: int
    text: str
    fetched_at: float   # unix epoch the body was actually downloaded
    from_cache: bool    # True if served without a network round-trip


_SCHEMA = """
CREATE TABLE IF NOT EXISTS http_cache (
    request_url   TEXT PRIMARY KEY,   -- the URL we were asked to fetch
    final_url     TEXT NOT NULL,      -- URL after following redirects
    status_code   INTEGER NOT NULL,
    body          TEXT NOT NULL,
    fetched_at    REAL NOT NULL
);
"""


class CacheMiss(RuntimeError):
    """Raised when offline mode is on and a URL is not cached."""


class HttpClient:
    """Cache-first HTTP client.

    Parameters mirror :mod:`origami.config` but are injectable so tests can use a
    throwaway database, a zero delay, and offline mode.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        ttl_seconds: int | None = None,
        user_agent: str | None = None,
        request_delay: float | None = None,
        timeout: float | None = None,
        offline: bool | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else config.CACHE_DB_PATH
        self.ttl_seconds = ttl_seconds if ttl_seconds is not None else config.CACHE_TTL_SECONDS
        self.user_agent = user_agent or config.USER_AGENT
        self.request_delay = request_delay if request_delay is not None else config.REQUEST_DELAY_SECONDS
        self.timeout = timeout if timeout is not None else config.REQUEST_TIMEOUT_SECONDS
        self.offline = offline if offline is not None else config.OFFLINE
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": self.user_agent})
        self._last_request_at = 0.0
        self._lock = threading.Lock()
        self._init_db()

    # --- storage ----------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self.db_path != Path(":memory:"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        # Keep a single shared connection for an in-memory DB, otherwise each
        # connection would see an empty database.
        if str(self.db_path) == ":memory:":
            self._mem_conn: sqlite3.Connection | None = sqlite3.connect(
                ":memory:", check_same_thread=False
            )
            self._mem_conn.row_factory = sqlite3.Row
            self._mem_conn.executescript(_SCHEMA)
        else:
            self._mem_conn = None
            with self._connect() as conn:
                conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        return self._mem_conn if self._mem_conn is not None else self._connect()

    def _read(self, url: str) -> sqlite3.Row | None:
        conn = self._conn()
        try:
            cur = conn.execute(
                "SELECT * FROM http_cache WHERE request_url = ?", (url,)
            )
            return cur.fetchone()
        finally:
            if self._mem_conn is None:
                conn.close()

    def _write(self, url: str, resp: CachedResponse) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO http_cache "
                "(request_url, final_url, status_code, body, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (url, resp.url, resp.status_code, resp.text, resp.fetched_at),
            )
            conn.commit()
        finally:
            if self._mem_conn is None:
                conn.close()

    # --- fetching ---------------------------------------------------------

    def _is_fresh(self, fetched_at: float) -> bool:
        return (time.time() - fetched_at) < self.ttl_seconds

    def _throttle(self) -> None:
        if self.request_delay <= 0:
            return
        elapsed = time.time() - self._last_request_at
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request_at = time.time()

    def get(self, url: str, *, force_refresh: bool = False) -> CachedResponse:
        """Return the (possibly cached) response for a GET ``url``."""
        return self._cached(
            url,
            lambda: self._session.get(url, timeout=self.timeout, allow_redirects=True),
            force_refresh=force_refresh,
        )

    def post_json(self, url: str, payload: dict, *, force_refresh: bool = False) -> CachedResponse:
        """POST ``payload`` as JSON and cache the response.

        The cache key folds in a stable hash of the body so different payloads to
        the same endpoint (e.g. different search pages) are cached separately.
        """
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
        cache_key = f"POST {url}#{digest}"
        return self._cached(
            cache_key,
            lambda: self._session.post(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            ),
            force_refresh=force_refresh,
        )

    def _cached(self, cache_key, do_fetch, *, force_refresh: bool) -> CachedResponse:
        """Shared cache-first logic for any request.

        - Fresh hit -> returned immediately, ``from_cache=True``.
        - Stale/missing -> fetched live (subject to the politeness delay), stored,
          and returned. In offline mode a stale entry is still served and a true
          miss raises :class:`CacheMiss`.
        """
        with self._lock:
            row = self._read(cache_key)
            if row is not None and not force_refresh:
                if self._is_fresh(row["fetched_at"]) or self.offline:
                    return CachedResponse(
                        url=row["final_url"],
                        status_code=row["status_code"],
                        text=row["body"],
                        fetched_at=row["fetched_at"],
                        from_cache=True,
                    )

            if self.offline:
                raise CacheMiss(f"offline and no cached copy of {cache_key!r}")

            self._throttle()
            http = do_fetch()
            resp = CachedResponse(
                url=http.url,
                status_code=http.status_code,
                text=http.text,
                fetched_at=time.time(),
                from_cache=False,
            )
            # Cache successful and "not found" responses; both are stable answers.
            # Transient 5xx are not cached so a later retry can succeed.
            if http.status_code < 500:
                self._write(cache_key, resp)
            return resp

    # --- introspection ----------------------------------------------------

    def stats(self) -> dict[str, int]:
        conn = self._conn()
        try:
            total = conn.execute("SELECT COUNT(*) AS n FROM http_cache").fetchone()["n"]
            cutoff = time.time() - self.ttl_seconds
            fresh = conn.execute(
                "SELECT COUNT(*) AS n FROM http_cache WHERE fetched_at >= ?", (cutoff,)
            ).fetchone()["n"]
        finally:
            if self._mem_conn is None:
                conn.close()
        return {"total": total, "fresh": fresh, "stale": total - fresh}

    def clear(self) -> None:
        conn = self._conn()
        try:
            conn.execute("DELETE FROM http_cache")
            conn.commit()
        finally:
            if self._mem_conn is None:
                conn.close()
