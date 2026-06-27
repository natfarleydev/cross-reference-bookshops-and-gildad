"""Export the catalogue to JSON + on-disk images for the Typst magazine.

The Typst generator (`scripts/magazine.typ`) is presentation-only and reads this
JSON via Typst's `json()`; Typst loads the image *files* directly (referenced as
`/out/...` under `typst compile --root .`), so this script just downloads and
downsamples the images and records their repo-relative paths.

    PYTHONPATH=. .venv/Scripts/python scripts/export_magazine_data.py
    typst compile --root . scripts/magazine.typ out/origami_magazine_typst.pdf

Data comes from the Python catalogue (Bookshop, the source of truth) enriched by
Gilad. All HTTP for the Gilad pages goes through the cache-first ``HttpClient``;
cover/photo binaries are fetched once with ``requests`` and cached on disk.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter
from pathlib import Path

import requests
from PIL import Image as PILImage

from origami import config, gilad, skill
from origami.cache import HttpClient
from origami.catalog import Catalog

OUT_JSON = Path("out/magazine_data.json")
COVERS_DIR = Path("out/covers")            # original covers (from Bookshop)
COVERS_RS_DIR = Path("out/covers_rs")      # downsampled covers
GILAD_IMG_DIR = Path("out/gilad_imgs")     # original Gilad model photos
GILAD_FIT_DIR = Path("out/gilad_fit")      # downsampled, aspect-preserved (no crop)

COVER_MAX_PX = 520     # ~70mm tall @ ~190 DPI; reused (scaled down) for small cards
THUMB_MAX_PX = 230     # ~30mm box @ ~190 DPI

SECTIONS = [
    ("simple", "Beginner",
     "Simple folds and first models — a gentle place to start."),
    ("intermediate", "Intermediate",
     "The sweet spot: shaping, sinks and modular work without the white-knuckle complexity."),
    ("complex", "Complex",
     "Many-step insects, dragons and tessellations for experienced folders."),
]


# --- formatting ------------------------------------------------------------


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


# --- images ----------------------------------------------------------------


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


def _resample(src: Path, out_dir: Path, max_px: int) -> Path:
    """Downsample to ``max_px`` on the long side, preserving aspect ratio."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{src.stem}_{max_px}.jpg"
    if out.exists() and out.stat().st_size > 0:
        return out
    with PILImage.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((max_px, max_px), PILImage.LANCZOS)
        im.save(out, "JPEG", quality=80, optimize=True)
    return out


def _rel(path: Path | None) -> str:
    """Repo-relative posix path for Typst (referenced as /<path> under --root)."""
    if not path or not path.exists():
        return ""
    return path.as_posix()


def cover_path(book) -> str:
    raw = _download(book.cover_url, COVERS_DIR, f"{book.isbn13}.jpg")
    if not raw:
        return ""
    try:
        return _rel(_resample(raw, COVERS_RS_DIR, COVER_MAX_PX))
    except Exception:
        return ""


def thumb_path(url: str) -> str:
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg"
    raw = _download(url, GILAD_IMG_DIR, name)
    if not raw:
        return ""
    try:
        return _rel(_resample(raw, GILAD_FIT_DIR, THUMB_MAX_PX))
    except Exception:
        return ""


def designs_for(book, client: HttpClient) -> list:
    if not book.gilad_url:
        return []
    gb = gilad.get_book(book.gilad_url, client)
    return list(gb.designs) if gb else []


# --- context build ---------------------------------------------------------


def _card(book, designs: list) -> dict:
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
        "bucket": _bucket(book),
        "design_count": book.design_count,
        "price": _price(book),
        "format": book.format_category or "—",
        "stock": _stock(book),
        "cover": cover_path(book),
        "gilad": book.gilad_url,
        "url": book.url,
        "sample": sample,
    }


def _dominant_designer(designs: list) -> str:
    """The designer behind >80% of a book's models, else "" (mixed authorship)."""
    if not designs:
        return ""
    name, count = Counter(d.designer for d in designs).most_common(1)[0]
    return name if name and count / len(designs) > 0.8 else ""


def _detail(book, designs: list) -> dict:
    thumbs = []
    for d in designs:
        if len(thumbs) >= 5:
            break
        if not d.photo_url:
            continue
        img = thumb_path(d.photo_url)
        if img:
            thumbs.append({"img": img, "name": d.name})
    return {
        "isbn13": book.isbn13,
        "title": book.title,
        "subtitle": book.subtitle,
        "author": book.author or "Various",
        "difficulty": book.difficulty.label,
        "bucket": _bucket(book),
        "design_count": book.design_count,
        "price": _price(book),
        "format": book.format_category or "—",
        "stock": _stock(book),
        "url": book.url,
        "cover": cover_path(book),
        "gilad": book.gilad_url,
        "thumbs": thumbs,
        "dominant_designer": _dominant_designer(designs),
        "models": [
            {"name": d.name, "designer": d.designer, "page": d.page,
             "cp": d.has_crease_pattern}
            for d in designs
        ],
    }


def main() -> int:
    catalog = Catalog()
    client = HttpClient()
    rated = [b for b in catalog.all() if b.difficulty.is_known]
    # Simple -> complex: order by the band's ceiling, then by its floor, so a
    # diluted band (e.g. simple–complex) sorts before the pure band at the same
    # ceiling (complex). Author/title break ties.
    rated.sort(key=lambda b: (
        b.difficulty.high, b.difficulty.low, b.author.lower(), b.title.lower(),
    ))
    designs_cache = {b.isbn13: designs_for(b, client) for b in rated}

    grouped: dict[str, list] = {key: [] for key, _, _ in SECTIONS}
    for b in rated:
        for key in grouped:
            if b.difficulty.matches_bucket(key):
                grouped[key].append(b)
    counts = {k: len(v) for k, v in grouped.items()}

    now = dt.datetime.now()
    data = {
        "meta": {
            "region_host": config.REGION.host,
            "issue": now.strftime("%B %Y"),
            "generated": now.strftime("%Y-%m-%d %H:%M"),
            "total_rated": len(rated),
            "catalog_size": catalog.count(),
            "counts": counts,
        },
        "sections": [
            {
                "key": key, "label": label, "blurb": blurb,
                "books": [_card(b, designs_cache[b.isbn13]) for b in grouped[key]],
            }
            for key, label, blurb in SECTIONS
            if grouped[key]
        ],
        "details": [_detail(b, designs_cache[b.isbn13]) for b in rated],
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote {OUT_JSON}: {len(rated)} books, counts={counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
