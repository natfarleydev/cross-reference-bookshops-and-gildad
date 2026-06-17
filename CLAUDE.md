# CLAUDE.md

Guidance for working in this repo. Read this first.

## What this is

A small **monolithic** web app for browsing origami books **you can buy on
Bookshop.org (UK)**, filtered the way an origami folder actually thinks:

- by **skill level** (simple / intermediate / complex),
- by **author**, **format**, **in-stock**, audience (hide kids' books),
- and showing, per book, **which diagrams/models are inside it**.

The original problem: Bookshop.org sells origami stuff but is hard to browse —
you can't filter by ability, and you can't see what models a book contains.
Gilad's Origami Database knows skill levels and the diagram lists, but isn't a
shop. This app joins the two.

## The core design decision: Bookshop-first, Gilad-supplements

**Bookshop.org is the source of truth for what exists / what you can buy.**
Gilad only *supplements* each book with a skill level and its list of diagrams.
**We never show a book that isn't on Bookshop.org.**

The join key is the **ISBN-13**.

```
Bookshop.org (UK)  ──harvest──►  catalogue (SQLite)  ──enrich by ISBN──►  Gilad
   (what to buy)                  (browse instantly)                  (skill + diagrams)
```

### Why these data sources work the way they do

- **Bookshop.org has no public API.** Its storefront is a Next.js + Cloudflare
  app whose search is **instant-meilisearch**. There is an unauthenticated proxy
  at `/api/next/instantsearch/multi-search` that speaks Meilisearch's
  `/multi-search` protocol and returns clean structured JSON per product (title,
  `ean`/ISBN, author, price in **minor units** i.e. pence, stock status, cover,
  format). We use this instead of scraping HTML — it's structured and stable.
  - Region matters: `uk.bookshop.org` gives GBP, `bookshop.org` gives USD. See
    `Region` in `origami/config.py`. Default is UK.
  - There are ~500–550 origami titles; we page through them all with `offset`.
  - A separate stable redirect `…/book/<isbn13>` → product page also exists
    (ISBN-13 only; ISBN-10 404s). We don't need it now but it's documented in
    `config.Region.isbn_url`.
- **Gilad's database** (giladorigami.com) is server-rendered HTML (200 OK with a
  browser User-Agent; default crawler UAs get 403). Two page types matter:
  - search `…/database-redirect.php?dbq=<q>` → `…/origami-database/<q>`: one row
    per (design, book). **Crucially, free-text search accepts an ISBN** and
    returns the matching book — that's our enrichment lookup.
  - book page `…/origami-database-book/<id>/<slug>`: title, author (from the meta
    description, *not* the first `<h1>` which is the site header), ISBN-13/10, a
    "Skill Level" technical field, and the full diagram list.

Both sites require a real browser `User-Agent` (configured in `config.py`).

## Aggressive caching (a hard requirement)

Every outbound HTTP request — GET or POST — goes through `origami/cache.py`
(`HttpClient`), a cache-first SQLite store. A fresh entry (within
`CACHE_TTL_SECONDS`, default **30 days**) never touches the network. 404s are
cached (stable answer); 5xx are not (so retries can succeed). POST bodies are
folded into the cache key so different search pages cache separately. There's a
politeness delay between live requests and an `OFFLINE` mode that serves only
cache. **Do not add code paths that bypass `HttpClient`.**

The enriched results live in a second SQLite DB, the **catalogue**
(`origami/catalog.py`), so browsing/filtering is instant and works offline.

Both DBs live in `data/` and are **git-ignored** (regenerable).

## Project structure

```
app.py                  FastAPI app: routes + Jinja rendering (the monolith entry)
origami/
  config.py             All tunables + Region definitions. Env overrides: ORIGAMI_*
  cache.py              HttpClient — cache-first SQLite HTTP (GET + post_json)
  isbn.py               ISBN-10/13 validation + ISBN-10→13 conversion
  skill.py              Skill-level taxonomy + parsing ("simple".."super complex")
  models.py             Frozen dataclasses: Design, GiladBook, BookshopBook, CatalogBook
  bookshop.py           Bookshop Meilisearch client: parse / search_page / harvest / lookup
  gilad.py              Gilad scraper/parser: parse_search / parse_book / find_book_by_isbn
  catalog.py            SQLite catalogue repository (storage only)
  service.py            Orchestration: ensure_catalog, enrich_*, get_detail, browse()
  deps.py               FastAPI dependency providers (Settings, HttpClient, Catalog)
  ingest.py             CLI: python -m origami.ingest  (harvest + enrich)
templates/              base / browse / book / not_found  (server-rendered Jinja)
static/style.css        single stylesheet
tests/                  pytest; fixtures/ holds real saved HTML + a Meili JSON response
data/                   SQLite caches (git-ignored, regenerable)
.claude/launch.json     dev-server config for the preview tool
```

### Layering (don't violate this)

```
app.py  ──►  origami.service  ──►  origami.{bookshop,gilad,catalog}  ──►  origami.cache
                  ▲                          │
              origami.deps (DI)          origami.{models,isbn,skill,config}
```

- The web layer (`app.py`) only calls `service` + `deps`. It never imports
  `bookshop`/`gilad`/`catalog` directly except for types.
- `service` functions take their collaborators (`Catalog`, `HttpClient`) as
  **arguments** — this is what makes them testable and what FastAPI injects via
  `Depends`. No module-level singletons except the cached providers in `deps.py`.
- Parsing is pure: `parse_*` take a string and return dataclasses, so they're
  tested directly against saved fixtures with no network.

## Dependency injection

FastAPI `Depends` is used throughout (the user specifically wants this — and
specifically does **not** want Flask). Providers in `origami/deps.py` are
`lru_cache`d so every request shares one `HttpClient` and one `Catalog`. Tests
swap them with `app.dependency_overrides` — no monkeypatching of globals.

## Running it

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt
python -m origami.ingest          # build the catalogue (harvest + enrich); ~minutes first run, cached after
python app.py                     # http://127.0.0.1:8000   (or: uvicorn app:app --reload)
```

The app also lazily harvests the Bookshop catalogue on first page load if it's
empty, but skill-level data only appears after enrichment (`ingest`, or the
"Enrich more" button which does 25 at a time).

### Useful env vars (see `config.py`)
`ORIGAMI_REGION` (uk/us), `ORIGAMI_CATALOG_QUERY` (default "origami"),
`ORIGAMI_CACHE_TTL`, `ORIGAMI_REQUEST_DELAY`, `ORIGAMI_OFFLINE`,
`ORIGAMI_DATA_DIR`.

## Testing

```bash
.venv/Scripts/python -m pytest      # all tests
.venv/Scripts/python -m ruff check app.py origami tests
```

Test philosophy: **liberal, and against real data.** Parsers are tested on real
saved fixtures in `tests/fixtures/` (Gilad search + book pages, a Bookshop Meili
response). Network is never hit in tests — fakes implement the tiny
`HttpClient` surface (`get`, `post_json`). When a site's markup/JSON shape
surprises you, **save a new fixture and add a regression test** rather than
patching blindly (that's how the `contributors: null` and "first `<h1>` is the
site header" bugs were caught).

## Gotchas / lessons learned

- Bookshop prices are integer **minor units** (pence) — divide by 100.
- Bookshop JSON has `null` fields (`contributors`, `primary_contributor`); the
  parser coerces null→"" (`_parse_hit`). Don't assume keys are present *and*
  non-null.
- Gilad book **title/author** come from the `<meta name="description">`
  ("…about <Title> by <Author> on Gilad's Origami Page"), because the first
  `<h1>` is the site banner.
- Gilad ISBN search returns ISBN-10 and ISBN-13 equally; conventions/magazines
  have no ISBN and simply won't match (they're not on Bookshop anyway).
- Windows: Git Bash `/tmp` ≠ Python's `/tmp`. Pipe between tools or use repo paths.

## Conventions

- Python ≥ 3.11, `from __future__ import annotations`, type hints, frozen
  dataclasses for data. Ruff (`E,F,I,UP,B`; `B008` ignored for FastAPI `Depends`).
- Commit early and often; messages explain *why*.
