"""Export a PDF of catalogue books at a given skill level.

Reads the enriched catalogue and writes a printable list of books whose Gilad
skill level overlaps the chosen bucket (default: intermediate) and that are on
Bookshop.org. Titles link to their Bookshop product page.

    python -m scripts.export_pdf                       # intermediate -> out/
    python -m scripts.export_pdf --level complex --out books.pdf
    python -m scripts.export_pdf --in-stock            # in-stock only
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from origami import skill
from origami.catalog import Catalog


def _price(book) -> str:
    if book.price is None:
        return "—"
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(book.currency, "")
    return f"{symbol}{book.price:.2f}"


def build(level: str, out_path: Path, *, in_stock_only: bool, hide_kids: bool) -> int:
    catalog = Catalog()
    books = [
        b for b in catalog.all()
        if b.difficulty.is_known and b.difficulty.matches_bucket(level)
    ]
    if in_stock_only:
        books = [b for b in books if b.in_stock]
    if hide_kids:
        books = [b for b in books if not b.is_kids]
    books.sort(key=lambda b: (b.author.lower(), b.title.lower()))

    styles = getSampleStyleSheet()
    cell = styles["BodyText"]
    cell.fontSize = 8
    cell.leading = 10
    link = styles["BodyText"].clone("link")
    link.fontSize = 8
    link.leading = 10
    link.textColor = colors.HexColor("#c2410c")

    doc = SimpleDocTemplate(
        str(out_path), pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=14 * mm, bottomMargin=12 * mm,
        title=f"Origami books — {level} level (Bookshop.org UK)",
    )

    story = []
    title_style = styles["Title"]
    title_style.fontSize = 18
    story.append(Paragraph(f"Origami books — {level.capitalize()} level", title_style))
    today = dt.date.today().strftime("%d %B %Y")
    subtitle = (
        f"{len(books)} books on Bookshop.org (UK) whose Gilad skill level includes "
        f"<b>{level}</b>{' · in stock only' if in_stock_only else ''}. "
        f"Skill &amp; diagram counts from Gilad's Origami Database. Generated {today}."
    )
    story.append(Paragraph(subtitle, styles["Normal"]))
    story.append(Spacer(1, 8))

    header = ["#", "Title (→ Bookshop)", "Author", "Skill", "Diagrams", "Format", "Price", "Stock"]
    rows = [header]
    for i, b in enumerate(books, 1):
        title_html = b.title
        if b.url:
            title_html = f'<a href="{b.url}">{b.title}</a>'
        rows.append([
            str(i),
            Paragraph(title_html, link),
            Paragraph(b.author or "—", cell),
            Paragraph(b.difficulty.label, cell),
            str(b.design_count or "—"),
            Paragraph(b.format_category or "—", cell),
            _price(b),
            "Yes" if b.in_stock else (b.status or "—"),
        ])

    col_widths = [9 * mm, 90 * mm, 50 * mm, 38 * mm, 18 * mm, 26 * mm, 18 * mm, 20 * mm]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2430")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f3ee")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9d4ca")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (4, 1), (4, -1), "CENTER"),
        ("ALIGN", (6, 1), (6, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    doc.build(story)
    return len(books)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a PDF of books at a skill level.")
    parser.add_argument("--level", choices=skill.BUCKETS, default="intermediate")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--in-stock", action="store_true")
    parser.add_argument("--hide-kids", action="store_true")
    args = parser.parse_args(argv)

    out = args.out or Path("out") / f"origami_{args.level}_books.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    n = build(args.level, out, in_stock_only=args.in_stock, hide_kids=args.hide_kids)
    print(f"Wrote {n} books to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
