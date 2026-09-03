"""Smoke-test the one confirmatory test on synthetic data, before it runs once.

`confirmatory_test.py` executes exactly once against the frozen holdout, and the
protocol forbids touching it afterwards. A plumbing bug found after that run
cannot be fixed by re-running -- re-running is precisely what the design
prohibits. So the arithmetic is exercised here, on a fixture whose right answers
are known by hand, where no holdout outcome is visible.

The fixture is deliberately tiny and hand-checkable. It is *not* a sample of the
holdout and contains none of its pages: the point is to verify the machine, not
to preview the measurement.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = (
    ROOT / "research" / "experiments" / "H1-A9-01" / "scripts" / "confirmatory_test.py"
)

# 10 pages, built so every branch of the gate is exercised and every count is
# obvious on inspection:
#
#   p01  stable, agreeing, clean      -> accepted, not severe
#   p02  stable, agreeing, clean      -> accepted, not severe
#   p03  stable, agreeing, SEVERE     -> accepted, severe   (the gate's miss)
#   p04  UNSTABLE, agreeing, SEVERE   -> abstained, severe
#   p05  UNSTABLE, agreeing, clean    -> abstained, not severe
#   p06  stable, DISAGREEING, SEVERE  -> abstained, severe
#   p07  stable, DISAGREEING, clean   -> abstained, not severe
#   p08  stable, NO SECOND PARSER     -> abstained (amendment 01), severe
#   p09  stable, agreeing, clean      -> accepted, not severe
#   p10  stable, agreeing, clean      -> accepted, not severe   (no official score)
#
# p10 carries no entry in the edit map, so it must be dropped entirely: 9 tested.
# Accepted 4 (p01 p02 p03 p09), of which 1 severe.
# Abstained 5 (p04..p08), of which 3 severe.

CLEAN = "the quick brown fox jumps over the lazy dog\n"
SEVERE_EDIT = 0.42
CLEAN_EDIT = 0.01


def disagreeing_text() -> str:
    """Enough critical-token mismatch to exceed the frozen floor of 21."""
    return "".join(f"value {index} on 2026-01-{index:02d} is ${index}00.50\n"
                   for index in range(1, 30))


@pytest.fixture
def fixture(tmp_path: Path) -> dict:
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    other = tmp_path / "second_parser"
    for directory in (run_a, run_b, other):
        directory.mkdir()

    pages = [f"p{index:02d}.jpg" for index in range(1, 11)]
    unstable = {"p04.jpg", "p05.jpg"}
    disagreeing = {"p06.jpg", "p07.jpg"}
    no_second_parser = {"p08.jpg"}
    severe = {"p03.jpg", "p04.jpg", "p06.jpg", "p08.jpg"}
    unscored = {"p10.jpg"}

    edit = {}
    for page in pages:
        stem = Path(page).stem
        (run_a / f"{stem}.md").write_text(CLEAN, encoding="utf-8")
        (run_b / f"{stem}.md").write_text(
            CLEAN + ("drift\n" if page in unstable else ""), encoding="utf-8"
        )
        if page not in no_second_parser:
            (other / f"{stem}.md").write_text(
                disagreeing_text() if page in disagreeing else CLEAN, encoding="utf-8"
            )
        if page not in unscored:
            edit[page] = SEVERE_EDIT if page in severe else CLEAN_EDIT

    holdout = {
        "status": "FROZEN",
        "page_count": len(pages),
        "pages": [
            {"image_path": page, "document_id": f"doc-{index // 3}"}
            for index, page in enumerate(pages)
        ],
    }
    holdout_path = tmp_path / "holdout.json"
    holdout_path.write_text(json.dumps(holdout), encoding="utf-8")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "text_block_per_page_edit.json").write_text(
        json.dumps(edit), encoding="utf-8"
    )

    output = tmp_path / "result.json"
    completed = subprocess.run(  # noqa: S603
        [
            sys.executable, str(SCRIPT),
            "--holdout", str(holdout_path),
            "--run-a-predictions", str(run_a),
            "--run-b-predictions", str(run_b),
            "--second-parser-predictions", str(other),
            "--artifacts", str(artifacts),
            "--output", str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(output.read_text(encoding="utf-8"))


def test_pages_without_an_official_score_leave_the_denominator(fixture: dict) -> None:
    assert fixture["pages_tested"] == 9
    assert fixture["pages_without_an_official_score"] == ["p10.jpg"]


def test_the_gate_partitions_exactly_as_designed(fixture: dict) -> None:
    primary = fixture["primary"]
    assert primary["accepted_pages"] == 4
    assert primary["abstained_pages"] == 5
    assert primary["accepted_pages"] + primary["abstained_pages"] == 9


def test_severe_counts_land_on_the_right_side(fixture: dict) -> None:
    primary = fixture["primary"]
    assert primary["accepted_severe"] == 1
    assert primary["abstained_severe"] == 3


def test_a_missing_second_parser_abstains_rather_than_accepts(fixture: dict) -> None:
    """Amendment 01. p08 is stable and would otherwise have been accepted."""
    page = next(p for p in fixture["pages"] if p["image_path"] == "p08.jpg")
    assert page["stable"] is True
    assert page["second_parser_available"] is False
    assert page["accepted"] is False
    assert fixture["secondary"]["pages_abstained_only_for_a_missing_second_parser"] == 1


def test_rates_and_reductions_are_computed_from_those_counts(fixture: dict) -> None:
    secondary = fixture["secondary"]
    assert secondary["coverage"] == pytest.approx(4 / 9)
    assert secondary["abstention_rate"] == pytest.approx(5 / 9)
    assert secondary["selective_severe_error_rate"] == pytest.approx(1 / 4)
    assert secondary["abstained_severe_error_rate"] == pytest.approx(3 / 5)
    assert secondary["baseline_severe_error_rate"] == pytest.approx(4 / 9)
    assert secondary["absolute_risk_reduction"] == pytest.approx(4 / 9 - 1 / 4)
    assert secondary["relative_risk_reduction"] == pytest.approx(
        (4 / 9 - 1 / 4) / (4 / 9)
    )


def test_per_signal_attribution_separates_the_two_halves(fixture: dict) -> None:
    per_signal = fixture["per_signal_secondary"]
    assert per_signal["unstable_pages"] == 2
    assert per_signal["low_agreement_pages"] == 2
    assert per_signal["severe_caught_by_stability"] == 1  # p04
    assert per_signal["severe_caught_by_agreement"] == 1  # p06
    assert per_signal["severe_caught_by_neither"] == 1  # p03


def test_the_frozen_operating_point_is_reported_verbatim(fixture: dict) -> None:
    point = fixture["frozen_operating_point"]
    assert point["agreement_max_critical_token_mismatches"] == 21
    assert point["severe_error_definition"] == (
        "official text-block edit distance > 0.10"
    )
    assert point["missing_second_parser_prediction"] == "abstain (amendment 01)"


def test_it_refuses_an_unfrozen_holdout(tmp_path: Path) -> None:
    """The one guard that stops this running against a manifest still in flux."""
    holdout = tmp_path / "draft.json"
    holdout.write_text(json.dumps({"status": "DRAFT", "page_count": 0, "pages": []}),
                       encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "text_block_per_page_edit.json").write_text("{}", encoding="utf-8")
    completed = subprocess.run(  # noqa: S603
        [
            sys.executable, str(SCRIPT),
            "--holdout", str(holdout),
            "--run-a-predictions", str(empty),
            "--run-b-predictions", str(empty),
            "--second-parser-predictions", str(empty),
            "--artifacts", str(artifacts),
            "--output", str(tmp_path / "out.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "FROZEN" in completed.stderr
