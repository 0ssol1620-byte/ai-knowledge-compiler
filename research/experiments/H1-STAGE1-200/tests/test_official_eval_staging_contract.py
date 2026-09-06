"""Staging must refuse rather than let the evaluator score a miss as a zero.

Measured 2026-08-18: handing the official OmniDocBench evaluator the Pod's own
output directory produced `!!!WARNING: No prediction for <page>, evaluate as
empty page` for 184 of 200 pages. Nothing crashed. A complete
`evaluation-summary.json` was written, and every number in it understated the
model badly. These tests exist because that failure is invisible by default.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "research" / "experiments" / "H1-STAGE1-200" / "scripts"
SCRIPT = SCRIPTS / "stage_stage1_predictions_for_official_eval.py"


@pytest.fixture(scope="module")
def staging():
    spec = importlib.util.spec_from_file_location("stage1_eval_staging", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifest(tmp_path: Path, cases: list[tuple[str, str]], declared: int | None = None) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "input_count": len(cases) if declared is None else declared,
                "inputs": [
                    {"case_id": case, "source_relative_path": f"images/{page}.png"}
                    for case, page in cases
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _predictions(tmp_path: Path, case_ids: list[str]) -> Path:
    source = tmp_path / "output" / "markdown-repeat-1"
    source.mkdir(parents=True)
    for case in case_ids:
        (source / f"{case}.md").write_text(f"# {case}\n", encoding="utf-8")
    return source.parent


def test_predictions_are_renamed_to_page_identity(staging, tmp_path) -> None:
    manifest = _manifest(tmp_path, [("omnidocbench-aaa", "newspaper_page_033")])
    root = _predictions(tmp_path, ["omnidocbench-aaa"])
    staged = staging.stage_repeat(
        root / "markdown-repeat-1",
        tmp_path / "staged" / "markdown-repeat-1",
        staging.case_to_page_name(manifest),
    )
    assert (tmp_path / "staged" / "markdown-repeat-1" / "newspaper_page_033.md").is_file()
    assert staged[0]["case_id"] == "omnidocbench-aaa"
    assert staged[0]["page_name"] == "newspaper_page_033"


def test_prediction_bytes_are_not_edited(staging, tmp_path) -> None:
    """Staging restores a name. Anything it changed in the content would make the
    scored artifact something other than what the Pod produced."""
    manifest = _manifest(tmp_path, [("omnidocbench-aaa", "page_1")])
    root = _predictions(tmp_path, ["omnidocbench-aaa"])
    original = (root / "markdown-repeat-1" / "omnidocbench-aaa.md").read_bytes()
    staging.stage_repeat(
        root / "markdown-repeat-1",
        tmp_path / "staged" / "markdown-repeat-1",
        staging.case_to_page_name(manifest),
    )
    assert (tmp_path / "staged" / "markdown-repeat-1" / "page_1.md").read_bytes() == original


def test_a_manifest_case_with_no_prediction_is_refused(staging, tmp_path) -> None:
    """This is the exact 184/200 case. Left alone the evaluator scores it as an
    empty page, which looks like a bad model instead of a missing file."""
    manifest = _manifest(tmp_path, [("omnidocbench-aaa", "page_1"), ("omnidocbench-bbb", "page_2")])
    root = _predictions(tmp_path, ["omnidocbench-aaa"])
    with pytest.raises(RuntimeError, match="have no prediction"):
        staging.stage_repeat(
            root / "markdown-repeat-1",
            tmp_path / "staged" / "markdown-repeat-1",
            staging.case_to_page_name(manifest),
        )


def test_a_prediction_with_no_manifest_entry_is_refused(staging, tmp_path) -> None:
    """Predictions and manifest from different runs would silently mis-score."""
    manifest = _manifest(tmp_path, [("omnidocbench-aaa", "page_1")])
    root = _predictions(tmp_path, ["omnidocbench-aaa", "omnidocbench-zzz"])
    with pytest.raises(RuntimeError, match="no manifest entry"):
        staging.stage_repeat(
            root / "markdown-repeat-1",
            tmp_path / "staged" / "markdown-repeat-1",
            staging.case_to_page_name(manifest),
        )


def test_two_cases_on_one_page_are_refused(staging, tmp_path) -> None:
    """A collision would overwrite one prediction with another and score both
    against the wrong ground truth."""
    manifest = _manifest(tmp_path, [("omnidocbench-aaa", "page_1"), ("omnidocbench-bbb", "page_1")])
    with pytest.raises(ValueError, match="resolve to page"):
        staging.case_to_page_name(manifest)


def test_a_manifest_that_lost_entries_is_refused(staging, tmp_path) -> None:
    manifest = _manifest(tmp_path, [("omnidocbench-aaa", "page_1")], declared=200)
    with pytest.raises(ValueError, match="declares 200"):
        staging.case_to_page_name(manifest)


def test_an_empty_prediction_directory_is_refused(staging, tmp_path) -> None:
    manifest = _manifest(tmp_path, [("omnidocbench-aaa", "page_1")])
    empty = tmp_path / "output" / "markdown-repeat-1"
    empty.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="holds no predictions"):
        staging.stage_repeat(
            empty, tmp_path / "staged" / "markdown-repeat-1", staging.case_to_page_name(manifest)
        )


def test_staging_will_not_overwrite_an_existing_staged_run(staging, tmp_path) -> None:
    """Re-staging into a populated directory would mix two runs' predictions."""
    manifest = _manifest(tmp_path, [("omnidocbench-aaa", "page_1")])
    root = _predictions(tmp_path, ["omnidocbench-aaa"])
    destination = tmp_path / "staged" / "markdown-repeat-1"
    destination.mkdir(parents=True)
    with pytest.raises(FileExistsError):
        staging.stage_repeat(
            root / "markdown-repeat-1", destination, staging.case_to_page_name(manifest)
        )
