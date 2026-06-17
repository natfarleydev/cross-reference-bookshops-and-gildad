"""SQLite-backed catalogue of origami books.

This is the persistent store the browse UI reads from. Each row is a
:class:`~origami.models.CatalogBook` – a Bookshop.org product plus (once
enriched) Gilad's skill level and diagram count. Keeping it in its own table
means browsing is instant and works offline; rebuilding it is the job of the
ingest step (see :mod:`origami.service` and ``python -m origami.ingest``).

The class is a thin repository: storage and retrieval only. All filtering and
orchestration lives in :mod:`origami.service`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config
from .models import CatalogBook
from .skill import Difficulty

_SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    isbn13          TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    subtitle        TEXT,
    author          TEXT,
    price           REAL,
    currency        TEXT,
    status          TEXT,
    cover_url       TEXT,
    url             TEXT,
    publish_date    TEXT,
    format_category TEXT,
    language        TEXT,
    series_name     TEXT,
    gilad_book_id   TEXT,
    gilad_url       TEXT,
    skill_low       INTEGER DEFAULT 0,
    skill_high      INTEGER DEFAULT 0,
    skill_raw       TEXT,
    design_count    INTEGER DEFAULT 0,
    enriched        INTEGER DEFAULT 0
);
"""


def _row_to_book(row: sqlite3.Row) -> CatalogBook:
    return CatalogBook(
        isbn13=row["isbn13"],
        title=row["title"],
        subtitle=row["subtitle"] or "",
        author=row["author"] or "",
        price=row["price"],
        currency=row["currency"] or config.REGION.currency,
        status=row["status"] or "",
        cover_url=row["cover_url"] or "",
        url=row["url"] or "",
        publish_date=row["publish_date"] or "",
        format_category=row["format_category"] or "",
        language=row["language"] or "",
        series_name=row["series_name"] or "",
        gilad_book_id=row["gilad_book_id"] or "",
        gilad_url=row["gilad_url"] or "",
        difficulty=Difficulty(row["skill_low"] or 0, row["skill_high"] or 0, row["skill_raw"] or ""),
        design_count=row["design_count"] or 0,
        enriched=bool(row["enriched"]),
    )


class Catalog:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path is not None else config.CATALOG_DB_PATH
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
        else:
            # Keep one shared connection alive for in-memory DBs.
            if not hasattr(self, "_mem"):
                self._mem = sqlite3.connect(":memory:", check_same_thread=False)
            conn = self._mem
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        conn.executescript(_SCHEMA)
        conn.commit()
        if str(self.db_path) != ":memory:":
            conn.close()

    # --- writes -----------------------------------------------------------

    def upsert(self, book: CatalogBook) -> None:
        self.upsert_many([book])

    def upsert_many(self, books: list[CatalogBook]) -> None:
        conn = self._connect()
        try:
            conn.executemany(
                """
                INSERT INTO books (isbn13, title, subtitle, author, price, currency,
                    status, cover_url, url, publish_date, format_category, language,
                    series_name, gilad_book_id, gilad_url, skill_low, skill_high,
                    skill_raw, design_count, enriched)
                VALUES (:isbn13, :title, :subtitle, :author, :price, :currency,
                    :status, :cover_url, :url, :publish_date, :format_category, :language,
                    :series_name, :gilad_book_id, :gilad_url, :skill_low, :skill_high,
                    :skill_raw, :design_count, :enriched)
                ON CONFLICT(isbn13) DO UPDATE SET
                    title=excluded.title, subtitle=excluded.subtitle, author=excluded.author,
                    price=excluded.price, currency=excluded.currency, status=excluded.status,
                    cover_url=excluded.cover_url, url=excluded.url,
                    publish_date=excluded.publish_date, format_category=excluded.format_category,
                    language=excluded.language, series_name=excluded.series_name
                """,
                [self._params(b) for b in books],
            )
            conn.commit()
        finally:
            if str(self.db_path) != ":memory:":
                conn.close()

    def set_enrichment(self, book: CatalogBook) -> None:
        """Update only the Gilad-supplied columns for an existing row."""
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE books SET gilad_book_id=:gilad_book_id, gilad_url=:gilad_url,
                    skill_low=:skill_low, skill_high=:skill_high, skill_raw=:skill_raw,
                    design_count=:design_count, enriched=1
                WHERE isbn13=:isbn13
                """,
                self._params(book),
            )
            conn.commit()
        finally:
            if str(self.db_path) != ":memory:":
                conn.close()

    @staticmethod
    def _params(b: CatalogBook) -> dict:
        return {
            "isbn13": b.isbn13, "title": b.title, "subtitle": b.subtitle,
            "author": b.author, "price": b.price, "currency": b.currency,
            "status": b.status, "cover_url": b.cover_url, "url": b.url,
            "publish_date": b.publish_date, "format_category": b.format_category,
            "language": b.language, "series_name": b.series_name,
            "gilad_book_id": b.gilad_book_id, "gilad_url": b.gilad_url,
            "skill_low": b.difficulty.low, "skill_high": b.difficulty.high,
            "skill_raw": b.difficulty.raw, "design_count": b.design_count,
            "enriched": 1 if b.enriched else 0,
        }

    def clear(self) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM books")
            conn.commit()
        finally:
            if str(self.db_path) != ":memory:":
                conn.close()

    # --- reads ------------------------------------------------------------

    def get(self, isbn13: str) -> CatalogBook | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM books WHERE isbn13=?", (isbn13,)).fetchone()
            return _row_to_book(row) if row else None
        finally:
            if str(self.db_path) != ":memory:":
                conn.close()

    def all(self) -> list[CatalogBook]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM books").fetchall()
            return [_row_to_book(r) for r in rows]
        finally:
            if str(self.db_path) != ":memory:":
                conn.close()

    def count(self) -> int:
        conn = self._connect()
        try:
            return conn.execute("SELECT COUNT(*) AS n FROM books").fetchone()["n"]
        finally:
            if str(self.db_path) != ":memory:":
                conn.close()

    def enriched_count(self) -> int:
        conn = self._connect()
        try:
            return conn.execute("SELECT COUNT(*) AS n FROM books WHERE enriched=1").fetchone()["n"]
        finally:
            if str(self.db_path) != ":memory:":
                conn.close()

    def is_empty(self) -> bool:
        return self.count() == 0
