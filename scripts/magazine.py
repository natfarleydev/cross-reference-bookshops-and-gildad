"""Build a browsable, magazine-style PDF of the origami catalogue.

Lays out the Bookshop.org catalogue as an illustrated guide with a cover, a
contents/legend page, and one section per skill level (Beginner / Intermediate /
Complex). Each book is a card with its cover image, author, skill band, price,
stock, and a sample of the models inside it (from Gilad).

    python -m scripts.magazine                 # -> out/origami_magazine.pdf
    python -m scripts.magazine --out mag.pdf

Cover images are downloaded once into out/covers/ and reused.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
from pathlib import Path

import requests
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from origami import config, gilad, skill
from origami.cache import HttpClient
from origami.catalog import Catalog

# --- palette ---------------------------------------------------------------
INK = colors.HexColor("#1f2430")
PAPER = colors.HexColor("#fbfaf7")
ACCENT = colors.HexColor("#c2410c")
SIMPLE = colors.HexColor("#2f9e44")
INTER = colors.HexColor("#1c7ed6")
COMPLEX = colors.HexColor("#ae3ec9")
MUTED = colors.HexColor("#6b7280")
CARD_BG = colors.HexColor("#ffffff")
LINE = colors.HexColor("#e6e2da")

BUCKET_COLOR = {"simple": SIMPLE, "intermediate": INTER, "complex": COMPLEX}

SECTIONS = [
    ("simple", "Beginner", "Simple folds and first models — a gentle place to start."),
    ("intermediate", "Intermediate",
     "The sweet spot: shaping, sinks and modular work without the white-knuckle complexity."),
    ("complex", "Complex",
     "Many-step insects, dragons and tessellations for experienced folders."),
]

PAGE_W, PAGE_H = A4
MARGIN = 14 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

COVERS_DIR = Path("out/covers")
COVERS_90_DIR = Path("out/covers_180dpi")
GILAD_IMG_DIR = Path("out/gilad_imgs")
TARGET_DPI = 180


# --- helpers ---------------------------------------------------------------


def _price(book) -> str:
    if book.price is None:
        return "—"
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(book.currency, "")
    return f"{symbol}{book.price:.2f}"


def _primary_bucket(book) -> str:
    """One section per book: use the midpoint of its skill band."""
    mid = round((book.difficulty.low + book.difficulty.high) / 2)
    return skill.level_to_bucket(mid) or "intermediate"


def download_cover(isbn: str, url: str) -> Path | None:
    if not url:
        return None
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    path = COVERS_DIR / f"{isbn}.jpg"
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


def download_image(url: str, into: Path) -> Path | None:
    """Fetch an arbitrary image URL once, cached by URL hash."""
    if not url:
        return None
    into.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    path = into / f"{name}.jpg"
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


def downsample_cover(path: Path, disp_w: float, disp_h: float) -> Path:
    """Resample the cover to TARGET_DPI for its on-page display size (points).

    Keeps embedded pixels ~= display_inches * TARGET_DPI so the PDF stays light.
    """
    target_w = max(1, round(disp_w / 72 * TARGET_DPI))
    target_h = max(1, round(disp_h / 72 * TARGET_DPI))
    COVERS_90_DIR.mkdir(parents=True, exist_ok=True)
    out = COVERS_90_DIR / f"{path.stem}_{target_w}x{target_h}.jpg"
    if out.exists() and out.stat().st_size > 0:
        return out
    with PILImage.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((target_w, target_h), PILImage.LANCZOS)
        im.save(out, "JPEG", quality=80, dpi=(TARGET_DPI, TARGET_DPI), optimize=True)
    return out


def fit_image(path: Path, max_w: float, max_h: float) -> Image | None:
    try:
        iw, ih = ImageReader(str(path)).getSize()
        if iw <= 0 or ih <= 0:
            return None
    except Exception:
        return None
    scale = min(max_w / iw, max_h / ih)
    disp_w, disp_h = iw * scale, ih * scale
    try:
        small = downsample_cover(path, disp_w, disp_h)
    except Exception:
        small = path
    return Image(str(small), width=disp_w, height=disp_h)


def book_anchor(book) -> str:
    """Stable in-document anchor id for a book's detail page."""
    return f"book_{book.isbn13}"


def get_designs(book, client: HttpClient) -> list:
    """Full list of designs/models in a book (cached Gilad page)."""
    if not book.gilad_url:
        return []
    gb = gilad.get_book(book.gilad_url, client)
    return list(gb.designs) if gb else []


def sample_models(book, client: HttpClient) -> list[str]:
    """A few representative model names from the book (cached Gilad page)."""
    names: list[str] = []
    for d in get_designs(book, client):
        if d.name and d.name not in names:
            names.append(d.name)
        if len(names) >= 6:
            break
    return names


# --- flowables -------------------------------------------------------------


def make_styles():
    styles = getSampleStyleSheet()
    s = {}
    s["title"] = ParagraphStyle("title", parent=styles["BodyText"], fontName="Helvetica-Bold",
                                fontSize=10, leading=12, textColor=ACCENT, spaceAfter=1)
    s["author"] = ParagraphStyle("author", parent=styles["BodyText"], fontSize=8,
                                 leading=10, textColor=MUTED, spaceAfter=2)
    s["meta"] = ParagraphStyle("meta", parent=styles["BodyText"], fontSize=8, leading=11)
    s["inside"] = ParagraphStyle("inside", parent=styles["BodyText"], fontSize=7.2,
                                 leading=9, textColor=INK, spaceBefore=2)
    s["nocover"] = ParagraphStyle("nocover", parent=styles["BodyText"], fontSize=7,
                                  leading=9, textColor=MUTED, alignment=TA_CENTER)
    # --- detail-page styles ---
    s["d_title"] = ParagraphStyle("d_title", parent=styles["BodyText"], fontName="Helvetica-Bold",
                                  fontSize=18, leading=21, textColor=INK, spaceAfter=2)
    s["d_author"] = ParagraphStyle("d_author", parent=styles["BodyText"], fontSize=11,
                                   leading=14, textColor=MUTED, spaceAfter=6)
    s["d_meta"] = ParagraphStyle("d_meta", parent=styles["BodyText"], fontSize=10,
                                 leading=15, textColor=INK, spaceAfter=2)
    s["d_h"] = ParagraphStyle("d_h", parent=styles["BodyText"], fontName="Helvetica-Bold",
                              fontSize=11, leading=14, textColor=INK, spaceBefore=8, spaceAfter=4)
    s["d_model"] = ParagraphStyle("d_model", parent=styles["BodyText"], fontSize=8,
                                  leading=10.5, textColor=INK)
    s["d_caption"] = ParagraphStyle("d_caption", parent=styles["BodyText"], fontSize=6.5,
                                    leading=8, textColor=MUTED, alignment=TA_CENTER)
    return s


def entry_card(book, client, styles) -> Table:
    bucket = _primary_bucket(book)
    color = BUCKET_COLOR[bucket].hexval()[2:]  # 'RRGGBB'

    cover = None
    path = download_cover(book.isbn13, book.cover_url)
    if path:
        cover = fit_image(path, 26 * mm, 36 * mm)
    cover_cell = cover or Paragraph("no cover", styles["nocover"])

    # Title links to this book's full-detail page later in the document.
    title_html = f'<a href="#{book_anchor(book)}" color="#c2410c">{book.title}</a>'
    title = Paragraph(title_html, styles["title"])
    author = Paragraph(book.author or "Various", styles["author"])

    stock = "In stock" if book.in_stock else (book.status or "—").capitalize()
    meta_html = (
        f'<font color="#{color}"><b>{book.difficulty.label}</b></font> · '
        f'{book.design_count} diagrams<br/>'
        f'<b>{_price(book)}</b> · {book.format_category or "—"} · {stock}'
    )
    meta = Paragraph(meta_html, styles["meta"])

    flow = [title, author, meta]
    models = sample_models(book, client)
    if models:
        shown = ", ".join(models)
        more = book.design_count - len(models)
        extra = f" +{more} more" if more > 0 else ""
        flow.append(Paragraph(f'<i>Inside:</i> {shown}{extra}', styles["inside"]))

    inner = Table([[cover_cell, flow]], colWidths=[27 * mm, 58 * mm])
    inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (1, 0), (1, 0), 0, CARD_BG),
    ]))
    return inner


def section_divider(label: str, blurb: str, count: int, color) -> Table:
    style = ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=16, leading=18,
                           textColor=colors.white)
    blurb_style = ParagraphStyle("secb", fontSize=9, leading=12, textColor=colors.white)
    cell = [
        Paragraph(f"{label} &nbsp;<font size=10>· {count} books</font>", style),
        Paragraph(blurb, blurb_style),
    ]
    t = Table([[cell]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def two_col_grid(cards: list) -> Table:
    rows = []
    for i in range(0, len(cards), 2):
        left = cards[i]
        right = cards[i + 1] if i + 1 < len(cards) else ""
        rows.append([left, right])
    grid = Table(rows, colWidths=[CONTENT_W / 2, CONTENT_W / 2])
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 8),
        ("LEFTPADDING", (1, 0), (1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
    ]))
    return grid


# --- per-book detail page --------------------------------------------------


def _model_line(d, styles) -> Paragraph:
    bits = [d.name]
    if d.designer:
        bits.append(f'<font color="#6b7280"> — {d.designer}</font>')
    if d.page:
        bits.append(f'<font color="#6b7280"> · p.{d.page}</font>')
    cp = ' <font color="#ae3ec9">[CP]</font>' if d.has_crease_pattern else ""
    return Paragraph("".join(bits) + cp, styles["d_model"])


def gilad_thumbs(designs: list, client, styles) -> Table | None:
    """A row of up to 5 sample model photos from Gilad (if any have images)."""
    cells = []
    for d in designs:
        if len(cells) >= 5:
            break
        if not d.photo_url:
            continue
        path = download_image(d.photo_url, GILAD_IMG_DIR)
        if not path:
            continue
        img = fit_image(path, 30 * mm, 30 * mm)
        if img:
            cells.append([img, Paragraph(d.name, styles["d_caption"])])
    if not cells:
        return None
    col_w = CONTENT_W / 5
    t = Table([[Table([[c[0]], [c[1]]]) for c in cells]],
              colWidths=[col_w] * len(cells))
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def models_grid(designs: list, styles) -> Table:
    """Full model list as a 3-column table."""
    lines = [_model_line(d, styles) for d in designs]
    cols = 3
    rows = []
    for i in range(0, len(lines), cols):
        row = lines[i:i + cols]
        row += [""] * (cols - len(row))
        rows.append(row)
    t = Table(rows, colWidths=[CONTENT_W / cols] * cols)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


def book_page(book, client, styles) -> list:
    bucket = _primary_bucket(book)
    color = BUCKET_COLOR[bucket].hexval()[2:]
    designs = get_designs(book, client)

    flow: list = []
    flow.append(Paragraph(f'<a name="{book_anchor(book)}"/>{book.title}', styles["d_title"]))
    if book.subtitle:
        flow.append(Paragraph(book.subtitle, styles["d_author"]))
    flow.append(Paragraph(book.author or "Various", styles["d_author"]))

    stock = "In stock" if book.in_stock else (book.status or "—").capitalize()
    meta_html = (
        f'<font color="#{color}"><b>{book.difficulty.label}</b></font> · '
        f'{book.design_count} diagrams &nbsp;·&nbsp; '
        f'<b>{_price(book)}</b> · {book.format_category or "—"} · {stock}'
    )
    flow.append(Paragraph(meta_html, styles["d_meta"]))
    if book.url:
        flow.append(Paragraph(
            f'<a href="{book.url}" color="#c2410c"><b>Buy on Bookshop.org »</b></a>',
            styles["d_meta"]))
    flow.append(Spacer(1, 6))

    # Cover (left) beside the sampled Gilad model photos (right).
    cover = None
    path = download_cover(book.isbn13, book.cover_url)
    if path:
        cover = fit_image(path, 50 * mm, 70 * mm)
    cover_cell = cover or Paragraph("no cover", styles["nocover"])
    thumbs = gilad_thumbs(designs, client, styles)
    right = thumbs or Paragraph("No model photos on Gilad for this title.",
                                styles["d_caption"])
    top = Table([[cover_cell, right]], colWidths=[54 * mm, CONTENT_W - 54 * mm])
    top.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    flow.append(top)

    if designs:
        flow.append(Paragraph(f"All {len(designs)} models", styles["d_h"]))
        flow.append(models_grid(designs, styles))
    else:
        flow.append(Paragraph("No model list available from Gilad.", styles["d_h"]))
    return flow


# --- cover / legend --------------------------------------------------------


def draw_cover_bg(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(INK)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    # Folded-paper triangles.
    canvas.setFillColor(ACCENT)
    canvas.setFillAlpha(0.9)
    p = canvas.beginPath()
    p.moveTo(0, PAGE_H)
    p.lineTo(0, PAGE_H - 120)
    p.lineTo(120, PAGE_H)
    p.close()
    canvas.drawPath(p, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#9a330a"))
    p = canvas.beginPath()
    p.moveTo(PAGE_W, 0)
    p.lineTo(PAGE_W, 160)
    p.lineTo(PAGE_W - 160, 0)
    p.close()
    canvas.drawPath(p, fill=1, stroke=0)
    canvas.setFillAlpha(1)
    canvas.restoreState()


def draw_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 8 * mm, "Origami Book Finder · sourced from uk.bookshop.org & Gilad's Origami Database")
    canvas.drawRightString(PAGE_W - MARGIN, 8 * mm, f"page {doc.page}")
    canvas.restoreState()


def cover_flowables(total_rated: int, by_section: dict, region_host: str) -> list:
    white = ParagraphStyle("cw", fontName="Helvetica-Bold", fontSize=40, leading=42,
                           textColor=colors.white, alignment=TA_LEFT)
    sub = ParagraphStyle("cs", fontSize=13, leading=18, textColor=colors.white)
    small = ParagraphStyle("csm", fontSize=10, leading=15, textColor=colors.HexColor("#cbd2dc"))
    now = dt.datetime.now()
    issue = now.strftime("%B %Y")
    generated = now.strftime("%Y-%m-%d %H:%M")
    flow = [Spacer(1, 70)]
    flow.append(Paragraph("The Origami<br/>Book Guide", white))
    flow.append(Spacer(1, 14))
    flow.append(Paragraph(f"Folder&rsquo;s edition &middot; {issue}", sub))
    flow.append(Paragraph(f"Generated {generated}", small))
    flow.append(Spacer(1, 26))
    flow.append(Paragraph(
        f"{total_rated} origami books you can buy on <b>{region_host}</b>, "
        f"hand-sorted by skill level with the models inside each one.", sub))
    flow.append(Spacer(1, 40))
    teaser = (
        f"Beginner &middot; {by_section.get('simple', 0)} books<br/>"
        f"Intermediate &middot; {by_section.get('intermediate', 0)} books<br/>"
        f"Complex &middot; {by_section.get('complex', 0)} books"
    )
    flow.append(Paragraph(teaser, small))
    return flow


def legend_flowables(styles, catalog_size: int, rated: int) -> list:
    h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=INK, spaceAfter=6)
    body = ParagraphStyle("b", fontSize=9.5, leading=14, textColor=INK, spaceAfter=6)
    flow = [Paragraph("How to use this guide", h)]
    flow.append(Paragraph(
        "Every book here is in stock or orderable on Bookshop.org (UK) — buy through the "
        "linked title to support independent bookshops. Skill levels and the list of models "
        "inside each book come from <b>Gilad&rsquo;s Origami Database</b>.", body))
    flow.append(Paragraph(
        f"The shop carries {catalog_size} origami titles; {rated} of them have a published "
        "skill rating and appear in the sections that follow. The rest (paper packs, "
        "unrated reprints, e-books) are browsable in the companion web app.", body))
    flow.append(Spacer(1, 6))
    flow.append(Paragraph("Skill levels", h))
    for key, label, blurb in SECTIONS:
        c = BUCKET_COLOR[key].hexval()[2:]
        flow.append(Paragraph(f'<font color="#{c}"><b>{label}</b></font> — {blurb}', body))
    return flow


# --- build -----------------------------------------------------------------


def build(out_path: Path) -> dict:
    catalog = Catalog()
    client = HttpClient()
    rated = [b for b in catalog.all() if b.difficulty.is_known]

    # A book appears in every level its skill band serves, so each section is a
    # genuine "books you can fold at this level" shelf (ranges show up in all
    # the levels they span).
    grouped: dict[str, list] = {key: [] for key, _, _ in SECTIONS}
    for b in rated:
        for key in grouped:
            if b.difficulty.matches_bucket(key):
                grouped[key].append(b)
    for key in grouped:
        grouped[key].sort(key=lambda b: (b.author.lower(), b.title.lower()))
    counts = {k: len(v) for k, v in grouped.items()}

    styles = make_styles()
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=16 * mm,
        title="The Origami Book Guide", author="Origami Book Finder",
    )

    story = []
    story += cover_flowables(len(rated), counts, config.REGION.host)
    story.append(PageBreak())
    story += legend_flowables(styles, catalog.count(), len(rated))
    story.append(PageBreak())

    for key, label, blurb in SECTIONS:
        books = grouped[key]
        if not books:
            continue
        story.append(section_divider(label, blurb, len(books), BUCKET_COLOR[key]))
        story.append(Spacer(1, 8))
        cards = [entry_card(b, client, styles) for b in books]
        story.append(two_col_grid(cards))
        story.append(PageBreak())

    # One full-detail page per (unique) book, sorted like the sections.
    detail_books = sorted(rated, key=lambda b: (b.author.lower(), b.title.lower()))
    for b in detail_books:
        story += book_page(b, client, styles)
        story.append(PageBreak())

    doc.build(story, onFirstPage=draw_cover_bg, onLaterPages=draw_footer)
    return {"rated": len(rated), **{f"section_{k}": v for k, v in counts.items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the origami magazine PDF.")
    parser.add_argument("--out", type=Path, default=Path("out") / "origami_magazine.pdf")
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    stats = build(args.out)
    print(f"Wrote {args.out}: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
