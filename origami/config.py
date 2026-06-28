"""Central configuration.

Everything tunable lives here so the rest of the package never hard-codes a URL,
a timeout, or a cache policy. Values can be overridden with ``ORIGAMI_*``
environment variables, which makes the app configurable without code edits.

The app is **Bookshop.org-first**: Bookshop is the source of truth for *what you
can buy*; Gilad's database only supplements each book with a skill level and the
list of diagrams inside it. The default region is the UK.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# --- Paths -----------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ORIGAMI_DATA_DIR", ROOT_DIR / "data"))
CACHE_DB_PATH = Path(os.environ.get("ORIGAMI_CACHE_DB", DATA_DIR / "http_cache.sqlite"))
CATALOG_DB_PATH = Path(os.environ.get("ORIGAMI_CATALOG_DB", DATA_DIR / "catalog.sqlite"))


# --- HTTP / scraping politeness -------------------------------------------

# A real browser UA is required: both sites 403 default crawler agents.
USER_AGENT = os.environ.get(
    "ORIGAMI_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
)
REQUEST_DELAY_SECONDS = float(os.environ.get("ORIGAMI_REQUEST_DELAY", "0.4"))
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("ORIGAMI_REQUEST_TIMEOUT", "20"))

# Cache aggressively: book metadata barely changes (30 days default).
CACHE_TTL_SECONDS = int(os.environ.get("ORIGAMI_CACHE_TTL", str(30 * 24 * 3600)))
OFFLINE = os.environ.get("ORIGAMI_OFFLINE", "").lower() in {"1", "true", "yes"}


# --- Region / Bookshop -----------------------------------------------------


@dataclass(frozen=True)
class Region:
    """A Bookshop.org storefront."""

    code: str
    host: str
    currency: str

    @property
    def base(self) -> str:
        return f"https://{self.host}"

    @property
    def multi_search_url(self) -> str:
        # Bookshop's front end is an instant-meilisearch app; this proxy speaks
        # the Meilisearch /multi-search protocol and needs no API key.
        return f"{self.base}/api/next/instantsearch/multi-search"

    def isbn_url(self, isbn13: str) -> str:
        # Stable redirect to the product page (ISBN-13 only; ISBN-10 404s).
        return f"{self.base}/book/{isbn13}"


REGIONS = {
    "uk": Region("uk", "uk.bookshop.org", "GBP"),
    "us": Region("us", "bookshop.org", "USD"),
}

REGION = REGIONS[os.environ.get("ORIGAMI_REGION", "uk").lower()]

# The Meilisearch index that holds sellable products.
BOOKSHOP_INDEX = os.environ.get("ORIGAMI_BOOKSHOP_INDEX", "products")

# The full-text query/queries used to scope the catalogue to origami titles.
# Override with a comma-separated ``ORIGAMI_CATALOG_QUERY``.
#
# Note: keep this *tight*. Bookshop's Meilisearch is fuzzy and OR-matches terms,
# so a query like "paper engineering" matches any book containing "paper" *or*
# "engineering" (engineering textbooks included) — ~1000 mostly-irrelevant hits.
# Breadth comes from the subject filter below instead, not from loose text terms.
CATALOG_QUERIES = tuple(
    q.strip()
    for q in os.environ.get("ORIGAMI_CATALOG_QUERY", "origami").split(",")
    if q.strip()
) or ("origami",)
# Backwards-compatible single-query alias (first query).
CATALOG_QUERY = CATALOG_QUERIES[0]

# To broaden the catalogue to the BIC/Thema subject "Origami & paper engineering"
# we filter the index server-side by subject code (the proxy *does* accept a
# Meilisearch ``filter`` on ``subjects``, confirmed against the live API):
#   WFTM  Origami & paper folding          (the clean origami set)
#   WFT   Paper crafts & paper engineering (parent: pop-ups, cut-and-fold,
#                                           paper models, paper airplanes)
# ``harvest`` runs this as an extra search and merges by ISBN, so it adds
# paper-engineering titles that don't literally say "origami" without the noise
# of a fuzzy text query. Override with a comma-separated ``ORIGAMI_BOOKSHOP_SUBJECTS``
# (set it empty to disable the subject pass and use text queries only).
BOOKSHOP_SUBJECTS = tuple(
    s.strip()
    for s in os.environ.get("ORIGAMI_BOOKSHOP_SUBJECTS", "WFTM, WFT").split(",")
    if s.strip()
)


# --- Gilad -----------------------------------------------------------------

GILAD_BASE = "https://www.giladorigami.com"
# Free-form search; accepts ISBN-10/13 and returns the matching book.
GILAD_SEARCH_URL = GILAD_BASE + "/database-redirect.php?dbq={query}"
GILAD_BOOK_URL = GILAD_BASE + "/origami-database-book/{book_id}"
