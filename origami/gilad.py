"""Scraper + parser for Gilad's Origami Database (giladorigami.com).

Two page types matter:

1. **Search results** ``/origami-database/<query>`` – one row per (design, book)
   pairing. Used to discover *which books contain a diagram for what you want to
   fold*. Each row carries the book's cover, its Gilad page link, and Amazon
   ``/ASIN/<code>/`` buy-links (our ISBN source).

2. **Book pages** ``/origami-database-book/<id>/<slug>`` – the authoritative
   record for one book: title, author, ISBN-13/10, the "Skill Level" technical
   field, and the *full* list of designs/diagrams inside it.

Parsing is intentionally separated from fetching: ``parse_*`` take HTML strings
(so they're trivially unit-testable against saved fixtures) and ``search`` /
``get_book`` add the cache-first network layer on top.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

from bs4 import BeautifulSoup

from . import config, isbn, skill
from .cache import HttpClient
from .models import Design, GiladBook

_BOOK_ID_RE = re.compile(r"/origami-database-book/(\d+)")
_ASIN_RE = re.compile(r"/ASIN/([0-9Xx]{10,13})")
_DESC_AUTHOR_RE = re.compile(r"about\s+(?P<rest>.+?)\s+on Gilad", re.IGNORECASE)


def _abs(url: str) -> str:
    """Resolve a possibly-relative Gilad URL to an absolute one."""
    if not url:
        return ""
    return urllib.parse.urljoin(config.GILAD_BASE + "/", url)


def _book_id_from_url(url: str) -> str:
    m = _BOOK_ID_RE.search(url or "")
    return m.group(1) if m else ""


def _split_title_author(text: str) -> tuple[str, str]:
    """Split a "Title by Author" display string. Title may itself contain "by",
    so we split on the *last* ' by '."""
    text = re.sub(r"\s*\(read full review\)\s*$", "", text or "").strip()
    if " by " in text:
        title, author = text.rsplit(" by ", 1)
        return title.strip(), author.strip()
    return text, ""


# --------------------------------------------------------------------------
# Search results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchHit:
    """One (design, book) pairing from a search-results page."""

    design: Design
    book_title: str
    book_author: str
    book_url: str          # absolute Gilad page (book page or legacy /BO_*.html)
    book_id: str           # numeric id, or "" for legacy review pages
    cover_url: str
    amazon_asins: tuple[str, ...]

    @property
    def book_key(self) -> str:
        """Stable identity for grouping rows into books."""
        return self.book_id or self.book_url


def _asins_from(node) -> tuple[str, ...]:
    out: list[str] = []
    for a in node.find_all("a", href=True):
        m = _ASIN_RE.search(a["href"])
        if m:
            code = m.group(1).upper()
            if code not in out:
                out.append(code)
    return tuple(out)


def parse_search(html: str) -> list[SearchHit]:
    """Parse a search-results page into a list of :class:`SearchHit`."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find(id="results")
    if table is None:
        return []
    body = table.find("tbody") or table

    hits: list[SearchHit] = []
    for tr in body.find_all("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 4:
            continue  # header / filter / spacer rows

        design_cell, designer_cell, source_cell = cells[0], cells[1], cells[2]
        page_cell = cells[3] if len(cells) > 3 else None
        paper_cell = cells[4] if len(cells) > 4 else None
        photo_cell = cells[5] if len(cells) > 5 else None

        design_link = design_cell.find("a")
        design_name = design_link.get_text(strip=True) if design_link else design_cell.get_text(strip=True)
        if not design_name:
            continue
        subject_el = design_cell.find(class_="subject-in-book")
        subject = subject_el.get_text(strip=True) if subject_el else ""

        designer = designer_cell.get_text(strip=True)

        # The source cell holds the book: cover image link + text link + buy links.
        book_links = source_cell.find_all("a", class_="book")
        book_url = ""
        book_text = ""
        for a in book_links:
            txt = a.get_text(strip=True)
            if txt:  # the text link (not the image-only link)
                book_url = _abs(a["href"])
                book_text = txt
                break
        if not book_url and book_links:
            book_url = _abs(book_links[0]["href"])
        cover_img = source_cell.find("img", class_="database-cover-image")
        cover_url = _abs(cover_img["src"]) if cover_img and cover_img.get("src") else ""
        title, author = _split_title_author(book_text)

        page = page_cell.get_text(strip=True) if page_cell else ""
        paper = paper_cell.get_text(" ", strip=True) if paper_cell else ""
        photo_url = ""
        if photo_cell:
            img = photo_cell.find("img")
            if img and img.get("src"):
                photo_url = _abs(img["src"])

        design = Design(
            name=design_name,
            designer=designer,
            subject=subject,
            page=page,
            paper=paper,
            photo_url=photo_url,
            has_crease_pattern="crease pattern" in paper.lower(),
        )
        hits.append(
            SearchHit(
                design=design,
                book_title=title,
                book_author=author,
                book_url=book_url,
                book_id=_book_id_from_url(book_url),
                cover_url=cover_url,
                amazon_asins=_asins_from(source_cell),
            )
        )
    return hits


# --------------------------------------------------------------------------
# Book pages
# --------------------------------------------------------------------------


def _isbn13_from(technical_dl: dict[str, str], asins: tuple[str, ...]) -> str | None:
    for key in ("ISBN-13", "ISBN13", "ISBN-10", "ISBN10", "ISBN"):
        if key in technical_dl:
            got = isbn.to_isbn13(technical_dl[key])
            if got:
                return got
    for code in asins:
        got = isbn.to_isbn13(code)
        if got:
            return got
    return None


def parse_book(html: str, url: str = "") -> GiladBook:
    """Parse a Gilad book page into a fully-populated :class:`GiladBook`."""
    soup = BeautifulSoup(html, "lxml")

    # Title + author come from the meta description, which is reliably
    # "...about <Title> by <Author> on Gilad's Origami Page". (The first <h1> on
    # the page is the site header, not the book.)
    title = ""
    author = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        m = _DESC_AUTHOR_RE.search(meta["content"])
        if m:
            title, author = _split_title_author(m.group("rest"))

    # Fallback to the content <h1> (skipping the site-title header) if needed.
    if not title:
        for h1 in soup.find_all("h1"):
            text = h1.get_text(strip=True)
            if text and "gilad" not in text.lower():
                title = text
                break

    # Cover from og:image, falling back to the on-page cover element.
    cover_url = ""
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        cover_url = og["content"]
    else:
        img = soup.find("img", class_="cover-image")
        if img and img.get("src"):
            cover_url = _abs(img["src"])

    # Bibliographic <dl> (Publisher / Pages / ISBN-13 / ...).
    biblio: dict[str, str] = {}
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        for dt in dts:
            dd = dt.find_next_sibling("dd")
            key = dt.get_text(strip=True).rstrip(":")
            if key:
                biblio[key] = dd.get_text(strip=True) if dd else ""

    # Technical table (Skill Level / Clear diagrams? / ...).
    technical: dict[str, str] = {}
    tech_table = soup.find("table", class_="book-technical")
    if tech_table:
        for tr in tech_table.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if th and td:
                technical[th.get_text(" ", strip=True)] = td.get_text(" ", strip=True)

    difficulty = skill.parse(technical.get("Skill Level"))

    asins = _asins_from(soup)
    isbn13 = _isbn13_from(biblio, asins)

    designs = _parse_book_designs(soup)

    # Fold the biblio fields into `technical` so the UI can show everything.
    merged = {**biblio, **technical}

    return GiladBook(
        book_id=_book_id_from_url(url),
        title=title,
        author=author,
        url=_abs(url) if url else "",
        cover_url=cover_url,
        isbn13=isbn13,
        amazon_asins=asins,
        difficulty=difficulty,
        designs=tuple(designs),
        technical=merged,
    )


def _parse_book_designs(soup: BeautifulSoup) -> list[Design]:
    table = soup.find(id="results")
    if table is None:
        return []
    body = table.find("tbody") or table
    designs: list[Design] = []
    for tr in body.find_all("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 3:
            continue
        design_cell, designer_cell = cells[0], cells[1]
        page_cell = cells[2] if len(cells) > 2 else None
        paper_cell = cells[3] if len(cells) > 3 else None
        photo_cell = cells[4] if len(cells) > 4 else None

        link = design_cell.find("a")
        name = link.get_text(strip=True) if link else design_cell.get_text(strip=True)
        if not name:
            continue
        subject_el = design_cell.find(class_="subject-in-book")
        subject = subject_el.get_text(strip=True) if subject_el else ""
        designer = designer_cell.get_text(strip=True)
        page = page_cell.get_text(strip=True) if page_cell else ""
        paper = paper_cell.get_text(" ", strip=True) if paper_cell else ""
        photo_url = ""
        if photo_cell:
            img = photo_cell.find("img")
            if img and img.get("src"):
                photo_url = _abs(img["src"])
        designs.append(
            Design(
                name=name,
                designer=designer,
                subject=subject,
                page=page,
                paper=paper,
                photo_url=photo_url,
                has_crease_pattern="crease pattern" in paper.lower(),
            )
        )
    return designs


# --------------------------------------------------------------------------
# Network layer (cache-first)
# --------------------------------------------------------------------------


def search(query: str, client: HttpClient) -> list[SearchHit]:
    """Run a database search for ``query`` and return parsed hits."""
    encoded = urllib.parse.quote(query.strip())
    url = config.GILAD_SEARCH_URL.format(query=encoded)
    resp = client.get(url)
    if resp.status_code != 200:
        return []
    return parse_search(resp.text)


def get_book(url: str, client: HttpClient) -> GiladBook | None:
    """Fetch and parse a single book page by its (absolute or relative) URL."""
    full = _abs(url)
    resp = client.get(full)
    if resp.status_code != 200:
        return None
    return parse_book(resp.text, url=resp.url or full)
