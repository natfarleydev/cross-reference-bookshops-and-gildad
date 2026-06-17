"""Flask monolith: the whole UI in one server-rendered app.

There is no separate front end and no JSON API to speak of — routes render Jinja
templates directly. State lives in the SQLite HTTP cache (see origami.cache).

Run it with::

    python app.py            # http://127.0.0.1:5000
    flask --app app run      # alternative
"""

from __future__ import annotations

from flask import Flask, redirect, render_template, request, url_for

from origami import bookshop, config, crossref, gilad, skill
from origami.cache import HttpClient

app = Flask(__name__)

# One shared, thread-safe, cache-first HTTP client for the process.
client = HttpClient()


def _selected_levels(args) -> set[str] | None:
    """Read skill-bucket checkboxes from the query string.

    No boxes ticked -> ``None`` (no filtering, show everything).
    """
    chosen = {lvl for lvl in args.getlist("level") if lvl in skill.BUCKETS}
    return chosen or None


def _flag(args, name: str, default: bool = False) -> bool:
    if name not in args:
        return default
    return args.get(name, "").lower() in {"1", "true", "on", "yes"}


@app.route("/")
def index():
    return render_template(
        "index.html",
        popular=crossref.POPULAR_SUBJECTS,
        buckets=skill.BUCKETS,
        cache_stats=client.stats(),
    )


@app.route("/search")
def search():
    query = (request.args.get("q") or "").strip()
    if not query:
        return redirect(url_for("index"))

    levels = _selected_levels(request.args)
    include_kids = not _flag(request.args, "hide_kids", default=False)
    bookshop_only = _flag(request.args, "bookshop_only", default=False)

    result = crossref.cross_reference(
        query,
        client,
        levels=levels,
        include_kids=include_kids,
        bookshop_only=bookshop_only,
    )

    return render_template(
        "results.html",
        result=result,
        query=query,
        buckets=skill.BUCKETS,
        selected_levels=levels or set(),
        include_kids=include_kids,
        bookshop_only=bookshop_only,
        cache_stats=client.stats(),
    )


@app.route("/book/<book_id>")
def book(book_id: str):
    url = config.GILAD_BOOK_URL.format(book_id=book_id)
    gilad_book = gilad.get_book(url, client)
    if gilad_book is None:
        return render_template("not_found.html", book_id=book_id), 404

    listing = None
    if gilad_book.isbn13:
        listing = bookshop.lookup(gilad_book.isbn13, client)

    return render_template(
        "book.html",
        book=gilad_book,
        listing=listing,
        cache_stats=client.stats(),
    )


@app.route("/cache/clear", methods=["POST"])
def cache_clear():
    client.clear()
    return redirect(request.referrer or url_for("index"))


@app.template_filter("price")
def _price(listing) -> str:
    if listing is None or listing.price is None:
        return ""
    symbol = {"USD": "$", "GBP": "£", "EUR": "€"}.get(listing.currency, "")
    return f"{symbol}{listing.price:.2f}"


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
