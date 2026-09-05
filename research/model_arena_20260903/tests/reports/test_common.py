"""``arena.reports.common``: the NA sentinel, safe readers, CSV writer."""

from __future__ import annotations

from pathlib import Path

import pytest
from arena.reports.common import (
    NA,
    Cell,
    ReportInputError,
    TableSpec,
    na_reason,
    read_json_optional,
    read_jsonl_optional,
    to_cell,
    write_csv,
    write_json,
)


def test_read_json_optional_missing_file_returns_reason(tmp_path: Path) -> None:
    value, reason = read_json_optional(tmp_path / "absent.json")
    assert value is None
    assert reason is not None
    assert "missing" in reason


def test_read_json_optional_present_file(tmp_path: Path) -> None:
    path = tmp_path / "present.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    value, reason = read_json_optional(path)
    assert value == {"a": 1}
    assert reason is None


def test_read_json_optional_malformed_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ReportInputError):
        read_json_optional(path)


def test_read_jsonl_optional_missing_returns_reason(tmp_path: Path) -> None:
    rows, reason = read_jsonl_optional(tmp_path / "absent.jsonl")
    assert rows is None
    assert reason is not None


def test_read_jsonl_optional_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text('{"a": 1}\n\n{"a": 2}\n', encoding="utf-8")
    rows, reason = read_jsonl_optional(path)
    assert reason is None
    assert rows == [{"a": 1}, {"a": 2}]


def test_read_jsonl_optional_non_object_line_raises(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text("[1, 2]\n", encoding="utf-8")
    with pytest.raises(ReportInputError):
        read_jsonl_optional(path)


def test_read_jsonl_optional_malformed_line_raises(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text('{"a": 1}\nnot json\n', encoding="utf-8")
    with pytest.raises(ReportInputError):
        read_jsonl_optional(path)


def test_cell_rendered_na_for_missing_value() -> None:
    assert na_reason("no data").rendered() == NA
    assert to_cell(None).rendered() == NA


def test_cell_rendered_never_defaults_a_missing_number_to_zero() -> None:
    cell = na_reason("not measured")
    assert cell.value is None
    assert cell.rendered() != "0"
    assert cell.rendered() == NA


def test_cell_rendered_formats_float_compactly() -> None:
    assert to_cell(0.123456789).rendered() == "0.123457"


def test_write_csv_header_present_with_zero_rows(tmp_path: Path) -> None:
    path = tmp_path / "out.csv"
    write_csv(path, TableSpec(header=("a", "b"), rows=[]))
    text = path.read_text(encoding="utf-8")
    assert text.strip() == "a,b"


def test_write_csv_renders_cells_and_missing_columns_as_na(tmp_path: Path) -> None:
    path = tmp_path / "out.csv"
    write_csv(
        path,
        TableSpec(
            header=("a", "b", "c"),
            rows=[{"a": to_cell(1), "b": na_reason("no b")}],
        ),
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "a,b,c"
    assert lines[1] == f"1,{NA},{NA}"


def test_write_json_returns_matching_sha256(tmp_path: Path) -> None:
    path = tmp_path / "out.json"
    digest = write_json(path, {"a": 1})
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def test_cell_is_frozen_dataclass() -> None:
    cell = Cell(value=1, reason=None)
    with pytest.raises(AttributeError):
        cell.value = 2  # type: ignore[misc]
