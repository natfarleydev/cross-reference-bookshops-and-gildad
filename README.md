# Origami Book Finder

Browse origami books you can **buy on [Bookshop.org](https://uk.bookshop.org)**,
filtered the way a folder actually thinks — by **skill level**, **author**,
**format**, and availability — with the **list of diagrams inside each book**
pulled from [Gilad's Origami Database](https://www.giladorigami.com/).

Bookshop.org sells origami books but is hard to browse: you can't filter by
ability and you can't see what models a book contains. This app fixes that.

![browse](docs/screenshot.png)

## How it works

- **Bookshop.org is the source of truth** for what you can buy (UK store, GBP).
  Books are discovered through Bookshop's own Meilisearch endpoint — structured
  data, no fragile HTML scraping.
- **Gilad's database supplements** each book *by ISBN* with a skill level and the
  full diagram list.
- You only ever see books that are actually on Bookshop.org.
- Everything is **aggressively cached** (SQLite) so it's fast and kind to both
  sites.

It's a single server-rendered app (FastAPI + Jinja) — no separate front end.

## Quick start

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Windows
# source .venv/bin/activate && pip install -r requirements-dev.txt   # macOS/Linux

python -m origami.ingest      # build the catalogue (first run takes a few minutes; cached after)
python app.py                 # open http://127.0.0.1:8000
```

Switch region/currency with `ORIGAMI_REGION=us` (default `uk`).

## Develop

```bash
.venv/Scripts/python -m pytest        # tests (run against real saved fixtures)
.venv/Scripts/python -m ruff check app.py origami tests
```

See [CLAUDE.md](CLAUDE.md) for architecture, data-source notes, and gotchas.

## Data & etiquette

This tool reads public pages from Bookshop.org and Gilad's Origami Database for
personal use, caches aggressively to minimise requests, and links back to both.
Please buy through the Bookshop.org links to support independent bookshops, and
visit Gilad's site — it's a labour of love.
