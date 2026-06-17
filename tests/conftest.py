"""Shared test helpers and fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def gilad_search_html() -> str:
    return load_fixture("gilad_search_wyvern.html")


@pytest.fixture
def gilad_book_html() -> str:
    return load_fixture("gilad_book_3795_origami_dragons.html")


@pytest.fixture
def gilad_convention_html() -> str:
    return load_fixture("gilad_book_3232_pcoc2017.html")


@pytest.fixture
def bookshop_meili_json() -> str:
    return load_fixture("bookshop_meili_origami.json")
