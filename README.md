# Origami Book Finder

Browse origami books you can **buy on [Bookshop.org](https://uk.bookshop.org)**,
filtered the way a folder actually thinks — by **skill level**, **author**,
**format**, and availability — with the **list of diagrams inside each book**
pulled from [Gilad's Origami Database](https://www.giladorigami.com/).

Bookshop.org sells origami books but is hard to browse: you can't filter by
ability and you can't see what models a book contains. This app fixes that.

> 🛠️ **Vibe-coded.** Built conversationally with Claude Code — described what I
> wanted, iterated on the results, kept what worked. Architecture, tests, and
> docs are real, but the process was exploratory rather than spec-first. Treat it
> as a personal tool, not production software.

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

### Skip the build: download the prebuilt catalogue

The first `ingest` takes a few minutes (it harvests Bookshop and enriches every
book against Gilad). To skip it, grab the prebuilt catalogue from the
[**Releases**](https://github.com/natfarleydev/cross-reference-bookshops-and-gildad/releases)
page — a [daily workflow](.github/workflows/daily-release.yml) publishes a fresh,
gzipped `catalog.sqlite` (tagged `catalog-YYYY-MM-DD`) with current prices/stock:

```bash
# download origami-catalog-<date>.sqlite.gz from the latest release, then:
gzip -dc origami-catalog-*.sqlite.gz > data/catalog.sqlite
python app.py
```

Now `python app.py` serves instantly with no harvest. (Bookshop's text query for
"origami" plus the BIC/Thema subject filter "Origami & paper engineering"
(`WFTM`/`WFT`) gives ~1150 books.)

Each daily release also attaches the **illustrated magazine PDF** (`*.pdf`, the
Typst "Bookshop.org × Gilad" guide) — so you can read or print it without
building it yourself.

## Export a PDF

Turn the catalogue into a printable, magazine-style guide:

- a **cover** with the generation date/time,
- a how-to-use page,
- one **section per skill level**, each book a card whose title links to its
  full page, and
- one **full page per book** — bigger cover, a sampling of model photos from
  Gilad, the *complete* list of models inside, the skill rating, and a link to
  the book's Bookshop.org page.

```bash
PYTHONPATH=. .venv/Scripts/python scripts/magazine.py    # -> out/origami_magazine.pdf
PYTHONPATH=. .venv/Scripts/python scripts/magazine.py --out mag.pdf
```

Images are downloaded once (`out/covers/`, `out/gilad_imgs/`) and downsampled to
180 DPI (`out/covers_180dpi/`) to keep the PDF reasonable. There's also a simpler
per-level table export at
`scripts/export_pdf.py --level {simple,intermediate,complex}`.

### "Bookshop.org × Gilad" (Typst)

The richer magazine — gradient skill-band headers, hero covers, gradient-sorted
books — is generated with [Typst](https://typst.app): a Python step exports the
data + images, then Typst lays out the PDF (a single static binary, no browser):

```bash
PYTHONPATH=. .venv/Scripts/python scripts/export_magazine_data.py
typst compile --root . scripts/magazine.typ out/origami_magazine_typst.pdf
```

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

The generated magazine, **"Bookshop.org × Gilad"**, is an **unofficial** guide —
not affiliated with or endorsed by either Bookshop.org or Gilad's Origami Database.

## License

This project's own code and templates are released under
[CC0 1.0 Universal](LICENSE) (public-domain dedication). The underlying book and
diagram data remain the property of Bookshop.org and Gilad's Origami Database.
