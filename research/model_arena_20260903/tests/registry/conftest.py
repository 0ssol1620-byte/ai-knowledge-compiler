"""Shared fixtures for the registry tests.

``FIXTURE_DIR`` holds the verbatim JSON that lane A3 fetched from
huggingface.co and api.github.com on 2026-09-03. It is public data and is
committed so `python -m arena.registry resolve --offline` reproduces the exact
registry that was published, with no network access at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from arena.registry.http import FixtureStore, OfflineFetcher

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def fixture_store() -> FixtureStore:
    return FixtureStore(FIXTURE_DIR)


@pytest.fixture(scope="session")
def offline_fetcher(fixture_store: FixtureStore) -> OfflineFetcher:
    return OfflineFetcher(fixture_store)


@pytest.fixture(scope="session")
def ovisocr2_payload(fixture_store: FixtureStore) -> Any:
    return fixture_store.read("https://huggingface.co/api/models/ATH-MaaS/OvisOCR2?blobs=true")


@pytest.fixture(scope="session")
def pdf_extract_kit_payload(fixture_store: FixtureStore) -> Any:
    return fixture_store.read(
        "https://huggingface.co/api/models/opendatalab/PDF-Extract-Kit-1.0?blobs=true"
    )
