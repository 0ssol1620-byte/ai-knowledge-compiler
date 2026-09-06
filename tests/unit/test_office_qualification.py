"""The Office qualification corpus and receipts (lane C-3).

Two things are pinned here. The corpus rebuilds to the same bytes, so the
committed fixtures are the ones the builder describes rather than a snapshot
nobody can reproduce. And every committed receipt equals a fresh run of the
qualifier over those bytes, so a receipt cannot drift away from the code that
produced it — the failure mode where a status keeps citing a measurement that
the current reader would no longer produce.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures.office_corpus.build_office_corpus import (
    CORPUS_ROOT,
    EXPECTED_PATH,
    FORMATS,
    build_corpus,
    write_expected,
)
from tools.office.qualify_office_readers import (
    OBSERVERS,
    UNOBSERVABLE,
    build_receipt,
    receipt_path,
    serialise,
)


def _without_runtime(receipt: dict[str, object]) -> dict[str, object]:
    """Everything the committed bytes must reproduce.

    ``runtime`` is the interpreter and library pin of the machine that ran the
    qualification. It is recorded because §22 requires a runtime digest, and it
    is excluded from the byte comparison because a different Python patch
    release or a rebuilt parser legitimately changes it — the suite runs on 3.12
    and 3.13. Nothing the qualifier *decides* lives in that block.
    """
    return {key: value for key, value in receipt.items() if key != "runtime"}


def test_the_corpus_rebuilds_to_the_committed_bytes(tmp_path: Path) -> None:
    manifest = build_corpus(tmp_path)
    write_expected(manifest, tmp_path / "expected.json")

    assert (tmp_path / "expected.json").read_bytes() == EXPECTED_PATH.read_bytes()
    for entry in manifest["files"]:
        rebuilt = tmp_path / str(entry["path"])
        committed = CORPUS_ROOT / str(entry["path"])
        assert committed.is_file(), f"{entry['path']} is described but not committed"
        assert rebuilt.read_bytes() == committed.read_bytes(), entry["path"]


def test_the_corpus_covers_ten_files_per_format() -> None:
    manifest = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    for source_format in FORMATS:
        entries = [entry for entry in manifest["files"] if entry["format"] == source_format]
        assert len(entries) >= 10, source_format


@pytest.mark.parametrize("source_format", FORMATS)
def test_the_committed_receipt_matches_a_fresh_run(source_format: str) -> None:
    path = receipt_path(source_format)
    assert path.is_file(), f"no committed receipt for {source_format}"
    committed = json.loads(path.read_text(encoding="utf-8"))
    fresh = build_receipt(source_format)

    assert serialise(_without_runtime(fresh)) == serialise(_without_runtime(committed))
    assert str(committed["runtime"]["digest"]).startswith("sha256:")


@pytest.mark.parametrize("source_format", FORMATS)
def test_the_receipt_status_follows_from_its_rows(source_format: str) -> None:
    """A status above BEST_EFFORT requires every row to pass. No exceptions."""
    receipt = json.loads(receipt_path(source_format).read_text(encoding="utf-8"))
    failed = [row for row in receipt["rows"] if not row["pass"]]
    assert receipt["totals"]["failed"] == len(failed)
    assert receipt["status"] == ("BEST_EFFORT" if failed else "VERIFIED_NATIVE")
    assert receipt["failedCapabilities"] == sorted({row["capability"] for row in failed})


def test_every_expected_capability_has_an_observer_or_a_stated_reason() -> None:
    """A capability with neither is a row that could never be measured."""
    manifest = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    named = {row["capability"] for entry in manifest["files"] for row in entry["rows"]}
    assert named <= set(OBSERVERS)
    for capability in named & set(UNOBSERVABLE):
        assert UNOBSERVABLE[capability].strip(), capability


def test_an_unobservable_row_is_never_recorded_as_a_pass() -> None:
    """The honest failure mode: no observer means fail, never a silent skip."""
    for source_format in FORMATS:
        receipt = json.loads(receipt_path(source_format).read_text(encoding="utf-8"))
        for row in receipt["rows"]:
            if "unobservable" in row:
                assert row["observed"] is None
                assert row["pass"] is False
