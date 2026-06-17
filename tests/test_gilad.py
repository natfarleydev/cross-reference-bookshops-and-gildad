"""Parser tests against real saved Gilad HTML."""

from __future__ import annotations

from origami import gilad, skill


def test_parse_search_returns_hits(gilad_search_html):
    hits = gilad.parse_search(gilad_search_html)
    assert len(hits) > 0
    h = hits[0]
    assert h.design.name
    assert h.book_title
    # Every hit should reference a book page or legacy review page.
    assert h.book_url.startswith("https://www.giladorigami.com/")


def test_search_hits_have_designers_and_books(gilad_search_html):
    hits = gilad.parse_search(gilad_search_html)
    assert any(h.design.designer for h in hits)
    # At least some books expose an Amazon ASIN we can turn into an ISBN.
    assert any(h.amazon_asins for h in hits)


def test_search_book_key_groups(gilad_search_html):
    hits = gilad.parse_search(gilad_search_html)
    keys = {h.book_key for h in hits}
    assert len(keys) >= 1
    # book_key is the numeric id when present, else the URL.
    for h in hits:
        assert h.book_key


def test_parse_book_core_fields(gilad_book_html):
    book = gilad.parse_book(gilad_book_html, url="/origami-database-book/3795/x")
    assert book.book_id == "3795"
    assert book.title == "Origami Dragons"
    assert book.author == "Marc Kirschenbaum"
    assert book.isbn13 == "9780804853101"
    assert book.cover_url.endswith(".jpg")


def test_parse_book_skill_level(gilad_book_html):
    book = gilad.parse_book(gilad_book_html)
    # "Simple to complex" spans the whole range.
    assert book.difficulty.low == skill.SIMPLE
    assert book.difficulty.high == skill.COMPLEX
    assert "Skill Level" in book.technical


def test_parse_book_designs(gilad_book_html):
    book = gilad.parse_book(gilad_book_html)
    assert book.design_count > 0
    names = [d.name for d in book.designs]
    assert "Dragon footprint" in names
    # Page numbers parsed.
    assert any(d.page for d in book.designs)


def test_parse_convention_book(gilad_convention_html):
    book = gilad.parse_book(gilad_convention_html, url="/origami-database-book/3232/PCOC-2017")
    assert book.book_id == "3232"
    assert book.design_count > 0
    # Convention books list many designers.
    designers = {d.designer for d in book.designs if d.designer}
    assert len(designers) > 1


def test_parse_book_isbn_from_asin_fallback():
    # A minimal page with no ISBN dl but an Amazon ASIN link.
    html = """
    <html><head><meta name='description' content='about Test by Someone on Gilad'></head>
    <body><h1>Test</h1>
    <a href='https://www.amazon.com/exec/obidos/ASIN/080485310X/giladsorigampage'>buy</a>
    </body></html>
    """
    book = gilad.parse_book(html, url="/origami-database-book/1/Test")
    assert book.isbn13 == "9780804853101"
    assert "080485310X" in book.amazon_asins
