"""Command-line catalogue builder.

Harvests the full Bookshop.org origami catalogue and enriches every book with
Gilad's skill level + diagram count. Everything is cached, so re-running is cheap
and incremental.

    python -m origami.ingest                # harvest (if empty) + enrich all
    python -m origami.ingest --refresh      # re-harvest from Bookshop first
    python -m origami.ingest --limit 50     # only enrich 50 books this run
"""

from __future__ import annotations

import argparse
import sys

from . import service
from .cache import HttpClient
from .catalog import Catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the origami book catalogue.")
    parser.add_argument("--refresh", action="store_true", help="re-harvest Bookshop first")
    parser.add_argument("--limit", type=int, default=None, help="max books to enrich this run")
    parser.add_argument("--no-enrich", action="store_true", help="harvest only, skip Gilad")
    args = parser.parse_args(argv)

    client = HttpClient()
    catalog = Catalog()

    print("Harvesting Bookshop catalogue...", flush=True)
    n = service.ensure_catalog(catalog, client, force=args.refresh)
    print(f"  catalogue has {catalog.count()} books (harvest touched {n}).", flush=True)

    if args.no_enrich:
        return 0

    def on_progress(i: int, total: int, book) -> None:
        mark = book.title[:48]
        print(f"  [{i}/{total}] {mark}", flush=True)

    print("Enriching with Gilad (skill level + diagrams)...", flush=True)
    done = service.enrich_all(catalog, client, limit=args.limit, on_progress=on_progress)
    stats = service.catalog_stats(catalog)
    print(f"Enriched {done} this run. Total enriched: {stats['enriched']}/{stats['total']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
