"""Dependency-injection providers for the FastAPI app.

Each collaborator (settings, the cache-first HTTP client, the catalogue) is built
by a cached provider so FastAPI hands the *same* instance to every request via
``Depends``. Tests override these with ``app.dependency_overrides`` to inject
fakes — no globals to monkeypatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from . import config
from .cache import HttpClient
from .catalog import Catalog
from .config import Region


@dataclass(frozen=True)
class Settings:
    region: Region
    catalog_queries: tuple[str, ...]

    @property
    def currency(self) -> str:
        return self.region.currency

    @property
    def catalog_query(self) -> str:
        """First catalogue query (back-compat single-value accessor)."""
        return self.catalog_queries[0]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(region=config.REGION, catalog_queries=config.CATALOG_QUERIES)


@lru_cache(maxsize=1)
def get_client() -> HttpClient:
    return HttpClient()


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    return Catalog()
