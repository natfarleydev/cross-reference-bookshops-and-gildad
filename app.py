"""FastAPI monolith: the whole UI in one server-rendered app.

No separate front end, no JSON API to maintain — routes render Jinja templates
directly. Collaborators are injected with ``Depends`` (see origami.deps); state
lives in the SQLite catalogue and HTTP cache.

Run it::

    python app.py                       # http://127.0.0.1:8000
    uvicorn app:app --reload            # alternative

First load harvests the Bookshop catalogue (~6 requests). Gilad enrichment (skill
levels + diagram counts) is filled in by ``python -m origami.ingest`` or the
"Enrich more" button.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from origami import service, skill
from origami.cache import HttpClient
from origami.catalog import Catalog
from origami.deps import Settings, get_catalog, get_client, get_settings
from origami.service import BrowseFilters

app = FastAPI(title="Origami Book Finder")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def _currency_symbol(currency: str) -> str:
    return {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency, "")


def price_filter(book) -> str:
    if book is None or book.price is None:
        return ""
    return f"{_currency_symbol(book.currency)}{book.price:.2f}"


templates.env.filters["price"] = price_filter


def merge_query(request: Request, **overrides) -> str:
    """Rebuild the current query string with ``overrides`` applied.

    Used by pagination links so they preserve every active filter.
    """
    dropped = set(overrides)
    params = [(k, v) for k, v in request.query_params.multi_items() if k not in dropped]
    for key, value in overrides.items():
        if value is None:
            continue
        if isinstance(value, list | set | tuple):
            params.extend((key, item) for item in value)
        else:
            params.append((key, value))
    return urlencode(params)


templates.env.globals["merge_query"] = merge_query


@app.get("/")
def browse(
    request: Request,
    q: str = "",
    author: str = "",
    format: list[str] = Query(default=[]),
    language: list[str] = Query(default=[]),
    level: list[str] = Query(default=[]),
    in_stock: bool = False,
    hide_kids: bool = False,
    sort: str = "relevance",
    page: int = 1,
    catalog: Catalog = Depends(get_catalog),
    client: HttpClient = Depends(get_client),
    settings: Settings = Depends(get_settings),
):
    # Lazily build the catalogue on first visit (fast: a handful of requests).
    service.ensure_catalog(catalog, client)

    filters = BrowseFilters(
        text=q.strip(),
        author=author,
        formats=set(format),
        languages=set(language),
        levels={lv for lv in level if lv in skill.BUCKETS},
        in_stock_only=in_stock,
        hide_kids=hide_kids,
        sort=sort if sort in service.SORTS else "relevance",
        page=page,
    )
    result = service.browse(catalog, filters)

    return templates.TemplateResponse(
        request,
        "browse.html",
        {
            "result": result,
            "filters": filters,
            "sorts": service.SORTS,
            "buckets": skill.BUCKETS,
            "settings": settings,
        },
    )


@app.get("/book/{isbn13}")
def book_detail(
    request: Request,
    isbn13: str,
    catalog: Catalog = Depends(get_catalog),
    client: HttpClient = Depends(get_client),
    settings: Settings = Depends(get_settings),
):
    detail = service.get_detail(catalog, client, isbn13)
    if detail is None:
        return templates.TemplateResponse(
            request, "not_found.html", {"isbn13": isbn13, "settings": settings},
            status_code=404,
        )
    book, designs = detail
    return templates.TemplateResponse(
        request,
        "book.html",
        {"book": book, "designs": designs, "settings": settings},
    )


@app.post("/catalog/enrich")
def catalog_enrich(
    n: int = Query(default=25, ge=1, le=200),
    catalog: Catalog = Depends(get_catalog),
    client: HttpClient = Depends(get_client),
):
    """Enrich a batch of books with Gilad data (progressive, via the UI button)."""
    service.enrich_all(catalog, client, limit=n)
    return RedirectResponse(url="/", status_code=303)


@app.post("/catalog/refresh")
def catalog_refresh(
    catalog: Catalog = Depends(get_catalog),
    client: HttpClient = Depends(get_client),
):
    """Re-harvest the Bookshop catalogue from scratch."""
    service.ensure_catalog(catalog, client, force=True)
    return RedirectResponse(url="/", status_code=303)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
