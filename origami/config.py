"""Central configuration.

Everything tunable lives here so the rest of the package never hard-codes a URL,
a timeout, or a cache policy. Values can be overridden with environment variables
(prefixed ``ORIGAMI_``) which makes the app easy to configure without code edits.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Paths -----------------------------------------------------------------

# Repo root (this file lives in <root>/origami/config.py).
ROOT_DIR = Path(__file__).resolve().parent.parent

# Where the SQLite HTTP cache lives. Kept out of version control (see .gitignore).
DATA_DIR = Path(os.environ.get("ORIGAMI_DATA_DIR", ROOT_DIR / "data"))
CACHE_DB_PATH = Path(os.environ.get("ORIGAMI_CACHE_DB", DATA_DIR / "http_cache.sqlite"))


# --- HTTP / scraping politeness -------------------------------------------

# A real browser UA is required: both sites 403 the default crawler agents.
USER_AGENT = os.environ.get(
    "ORIGAMI_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
)

# Seconds to wait between *live* (cache-miss) requests to the same host, so we
# stay a polite scraper. Cache hits are never delayed.
REQUEST_DELAY_SECONDS = float(os.environ.get("ORIGAMI_REQUEST_DELAY", "1.0"))

# Per-request network timeout.
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("ORIGAMI_REQUEST_TIMEOUT", "20"))

# How long a cached response stays fresh. Book metadata barely changes, so we
# cache *very* aggressively by default (30 days). Prices change more often but
# are not worth hammering the site for; the UI exposes a manual refresh.
CACHE_TTL_SECONDS = int(os.environ.get("ORIGAMI_CACHE_TTL", str(30 * 24 * 3600)))

# When True, the HTTP client never hits the network and only serves cache hits
# (raises on a miss). Useful for tests and offline browsing.
OFFLINE = os.environ.get("ORIGAMI_OFFLINE", "").lower() in {"1", "true", "yes"}


# --- Source URLs -----------------------------------------------------------

GILAD_BASE = "https://www.giladorigami.com"
# Free-form database search. Returns one row per (design, book) pairing.
GILAD_SEARCH_URL = GILAD_BASE + "/origami-database/{query}"
# Canonical book page, e.g. /origami-database-book/3795/Origami-Dragons-...
GILAD_BOOK_URL = GILAD_BASE + "/origami-database-book/{book_id}"

BOOKSHOP_BASE = "https://bookshop.org"
# Stable ISBN -> product-page redirect. Only ISBN-13 resolves (ISBN-10 404s).
BOOKSHOP_ISBN_URL = BOOKSHOP_BASE + "/book/{isbn13}"
