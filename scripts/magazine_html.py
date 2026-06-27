"""Build the magazine PDF via HTML/CSS rendered by Gotenberg (headless Chromium).

This replaces the ReportLab layout in ``scripts/magazine.py``: the model lists
that overflowed an A4 ``Table`` now flow naturally as CSS multi-column blocks,
and Chromium handles pagination. No Chrome/GTK on the host — the renderer lives
in the ``gotenberg`` Docker container (see ``docker-compose.yml``).

    docker compose up -d gotenberg
    PYTHONPATH=. .venv/Scripts/python scripts/magazine_html.py    # -> out/origami_magazine.pdf

Data still comes from the Python catalogue (Bookshop) enriched by Gilad — this
script is presentation only. Images are downsampled and inlined as base64 data
URIs so the request to Gotenberg is a single self-contained ``index.html``.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import os
from pathlib import Path

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image as PILImage

from origami import config, gilad, skill
from origami.cache import HttpClient
from origami.catalog import Catalog

GOTENBERG_URL = os.environ.get("GOTENBERG_URL", "http://localhost:3000")
TEMPLATE_DIR = Path(__file__).parent / "templates"

COVERS_DIR = Path("out/covers")
COVERS_RS_DIR = Path("out/covers_rs")
GILAD_IMG_DIR = Path("out/gilad_imgs")
GILAD_RS_DIR = Path("out/gilad_rs")

COVER_MAX_PX = 520     # ~70mm tall @ ~190 DPI; reused (scaled down) for small cards
THUMB_MAX_PX = 230     # ~30mm square @ ~190 DPI

SECTIONS = [
    ("simple", "simple", "Beginner",
     "Simple folds and first models — a gentle place to start."),
    ("intermediate", "inter", "Intermediate",
     "The sweet spot: shaping, sinks and modular work without the white-knuckle complexity."),
    ("complex", "complex", "Complex",
     "Many-step insects, dragons and tessellations for experienced folders."),
]
# Difficulty key, rendered as real emoji (Gotenberg's Chromium ships Noto Color Emoji).
EMOJI = {"simple": "🟢", "intermediate": "🔵", "complex": "🟣"}


# --- data / images ---------------------------------------------------------


def _price(book) -> str:
    if book.price is None:
        return "—"
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(book.currency, "")
    return f"{symbol}{book.price:.2f}"


def _stock(book) -> str:
    return "In stock" if book.in_stock else (book.status or "—").capitalize()


def _bucket(book) -> str:
    """One section/colour per book: midpoint of its skill band."""
    mid = round((book.difficulty.low + book.difficulty.high) / 2)
    return skill.level_to_bucket(mid) or "intermediate"


def _download(url: str, into: Path, name: str) -> Path | None:
    if not url:
        return None
    into.mkdir(parents=True, exist_ok=True)
    path = into / name
    if path.exists() and path.stat().st_size > 0:
        return path
    try:
        r = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=20)
        if r.status_code == 200 and r.content:
            path.write_bytes(r.content)
            return path
    except requests.RequestException:
        return None
    return None


def _resample(src: Path, out_dir: Path, max_px: int, *, cover: bool) -> Path:
    """Shrink to ``max_px`` on the long side (covers) or to a square (thumbs)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{src.stem}_{max_px}.jpg"
    if out.exists() and out.stat().st_size > 0:
        return out
    with PILImage.open(src) as im:
        im = im.convert("RGB")
        if cover:
            im.thumbnail((max_px, max_px), PILImage.LANCZOS)
        else:  # square crop for thumbnails
            w, h = im.size
            s = min(w, h)
            im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
            im = im.resize((max_px, max_px), PILImage.LANCZOS)
        im.save(out, "JPEG", quality=80, optimize=True)
    return out


def _data_uri(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def cover_uri(book) -> str:
    raw = _download(book.cover_url, COVERS_DIR, f"{book.isbn13}.jpg")
    if not raw:
        return ""
    try:
        return _data_uri(_resample(raw, COVERS_RS_DIR, COVER_MAX_PX, cover=True))
    except Exception:
        return ""


def thumb_uri(url: str) -> str:
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg"
    raw = _download(url, GILAD_IMG_DIR, name)
    if not raw:
        return ""
    try:
        return _data_uri(_resample(raw, GILAD_RS_DIR, THUMB_MAX_PX, cover=False))
    except Exception:
        return ""


def designs_for(book, client: HttpClient) -> list:
    if not book.gilad_url:
        return []
    gb = gilad.get_book(book.gilad_url, client)
    return list(gb.designs) if gb else []


# --- context build ---------------------------------------------------------


def _card_ctx(book, designs: list) -> dict:
    bucket = _bucket(book)
    names: list[str] = []
    for d in designs:
        if d.name and d.name not in names:
            names.append(d.name)
        if len(names) >= 6:
            break
    sample = ", ".join(names)
    more = book.design_count - len(names)
    if sample and more > 0:
        sample += f" +{more} more"
    return {
        "isbn13": book.isbn13,
        "title": book.title,
        "author": book.author or "Various",
        "difficulty": book.difficulty.label,
        "emoji": EMOJI[bucket],
        "design_count": book.design_count,
        "price": _price(book),
        "format": book.format_category or "—",
        "stock": _stock(book),
        "cover": cover_uri(book),
        "sample": sample,
    }


def _detail_ctx(book, designs: list) -> dict:
    bucket = _bucket(book)
    thumbs = []
    for d in designs:
        if len(thumbs) >= 5:
            break
        if not d.photo_url:
            continue
        img = thumb_uri(d.photo_url)
        if img:
            thumbs.append({"img": img, "name": d.name})
    models = [
        {"name": d.name, "designer": d.designer, "page": d.page, "cp": d.has_crease_pattern}
        for d in designs
    ]
    return {
        "isbn13": book.isbn13,
        "title": book.title,
        "subtitle": book.subtitle,
        "author": book.author or "Various",
        "difficulty": book.difficulty.label,
        "emoji": EMOJI[bucket],
        "design_count": book.design_count,
        "price": _price(book),
        "format": book.format_category or "—",
        "stock": _stock(book),
        "url": book.url,
        "cover": cover_uri(book),
        "thumbs": thumbs,
        "models": models,
    }


def build_html() -> tuple[str, dict]:
    catalog = Catalog()
    client = HttpClient()
    rated = [b for b in catalog.all() if b.difficulty.is_known]
    rated.sort(key=lambda b: (b.author.lower(), b.title.lower()))

    designs_cache = {b.isbn13: designs_for(b, client) for b in rated}

    grouped: dict[str, list] = {key: [] for key, _, _, _ in SECTIONS}
    for b in rated:
        for key in grouped:
            if b.difficulty.matches_bucket(key):
                grouped[key].append(b)
    counts = {k: len(v) for k, v in grouped.items()}

    sections = [
        {
            "css": css, "label": label, "blurb": blurb,
            "books": [_card_ctx(b, designs_cache[b.isbn13]) for b in grouped[key]],
        }
        for key, css, label, blurb in SECTIONS
        if grouped[key]
    ]
    details = [_detail_ctx(b, designs_cache[b.isbn13]) for b in rated]

    now = dt.datetime.now()
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    html = env.get_template("magazine.html.j2").render(
        region_host=config.REGION.host,
        issue=now.strftime("%B %Y"),
        generated=now.strftime("%Y-%m-%d %H:%M"),
        total_rated=len(rated),
        catalog_size=catalog.count(),
        counts=counts,
        sections=sections,
        details=details,
    )
    return html, {"rated": len(rated), **{f"section_{k}": v for k, v in counts.items()}}


# --- render ----------------------------------------------------------------


def render(html: str, out_path: Path) -> None:
    files = {"files": ("index.html", html.encode("utf-8"), "text/html")}
    data = {
        "preferCssPageSize": "true",
        "printBackground": "true",
        "marginTop": "0", "marginBottom": "0", "marginLeft": "0", "marginRight": "0",
    }
    resp = requests.post(
        f"{GOTENBERG_URL}/forms/chromium/convert/html",
        files=files, data=data, timeout=180,
    )
    resp.raise_for_status()
    out_path.write_bytes(resp.content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the origami magazine PDF (Gotenberg).")
    parser.add_argument("--out", type=Path, default=Path("out") / "origami_magazine.pdf")
    parser.add_argument("--html-only", action="store_true", help="write index.html, skip Gotenberg")
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    html, stats = build_html()
    if args.html_only:
        html_path = args.out.with_suffix(".html")
        html_path.write_text(html, encoding="utf-8")
        print(f"Wrote {html_path}: {stats}")
        return 0
    render(html, args.out)
    print(f"Wrote {args.out}: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
