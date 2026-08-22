from __future__ import annotations

import os
from pathlib import Path

import pytest
from long_paths import (
    long_path,
    safe_copy,
    safe_exists,
    safe_link_or_copy,
    safe_makedirs,
)


def _deep(tmp_path: Path) -> Path:
    """A directory whose path exceeds the Windows limit without the prefix."""
    return tmp_path / os.sep.join(["d" * 40] * 6)


def test_long_path_is_idempotent(tmp_path: Path) -> None:
    once = long_path(tmp_path / "a.md")
    assert long_path(once) == once


def test_long_path_only_rewrites_on_windows(tmp_path: Path) -> None:
    result = long_path(tmp_path / "a.md")
    if os.name == "nt":
        assert result.startswith("\\\\?\\")
    else:
        assert result == str(tmp_path / "a.md")


def test_long_path_accepts_a_string(tmp_path: Path) -> None:
    assert long_path(str(tmp_path / "a.md")) == long_path(tmp_path / "a.md")


def test_copy_survives_a_path_over_the_limit(tmp_path: Path) -> None:
    deep = _deep(tmp_path)
    source = deep / "source" / ("s" * 80 + ".md")
    safe_makedirs(source.parent)
    with open(long_path(source), "w", encoding="utf-8") as handle:
        handle.write("content")
    target = deep / "target" / ("t" * 80 + ".md")

    safe_copy(source, target)

    assert safe_exists(target)
    with open(long_path(target), encoding="utf-8") as handle:
        assert handle.read() == "content"


def test_link_or_copy_places_the_file(tmp_path: Path) -> None:
    deep = _deep(tmp_path)
    source = deep / "source" / ("s" * 80 + ".md")
    safe_makedirs(source.parent)
    with open(long_path(source), "w", encoding="utf-8") as handle:
        handle.write("linked")
    target = deep / "target" / ("t" * 80 + ".md")

    safe_link_or_copy(source, target)

    assert safe_exists(target)
    with open(long_path(target), encoding="utf-8") as handle:
        assert handle.read() == "linked"


def test_link_or_copy_reports_a_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        safe_link_or_copy(tmp_path / "absent.md", tmp_path / "target.md")


def test_safe_exists_is_false_for_an_absent_deep_path(tmp_path: Path) -> None:
    assert safe_exists(_deep(tmp_path) / "nothing.md") is False


def test_makedirs_is_repeatable(tmp_path: Path) -> None:
    deep = _deep(tmp_path) / "nested"
    safe_makedirs(deep)
    safe_makedirs(deep)
    assert safe_exists(deep)
