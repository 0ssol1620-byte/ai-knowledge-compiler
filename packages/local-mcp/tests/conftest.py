"""Shared fixtures for the akc-local-mcp tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from akc_local_mcp import LocalWorldStore

TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
WORLD_STATE_FIXTURE_DIR = FIXTURES_DIR / "world-state"


@pytest.fixture()
def fixture_world_state_dir() -> Path:
    return WORLD_STATE_FIXTURE_DIR


@pytest.fixture()
def store(fixture_world_state_dir: Path) -> LocalWorldStore:
    return LocalWorldStore(fixture_world_state_dir)


@pytest.fixture()
def empty_world_state_dir(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "worlds-that-never-were"
    yield root
