"""The corrected evaluator scores by a function of its input, and stays that way.

The frozen evaluator chose its matching algorithm from a wall-clock timeout, so
identical prediction bytes could be scored two different ways depending on
machine load. That would be a limitation if the noise were independent of what
was being measured. It was not: pages the gate abstained on hit the fallback at
12.9% against 3.7% for accepted pages (Fisher exact p = 0.0005), and the
fallback also tracked the outcome. Noise correlated with the comparison does not
merely attenuate, so the confirmatory evidence had to be re-measured.

These tests pin three things that must not drift:

  * the source correction is present and is *only* the removal of a wall-clock
    decision -- no metric, threshold or matching rule moved;
  * the measured determinism receipt actually shows one hash across every
    parallelism and page order tried, with zero fallbacks;
  * the independence test that motivated the whole correction is on the record
    with its real verdict, rather than quietly restated as an assumption.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
RECEIPTS = ROOT / "research" / "experiments" / "H1-A9-01" / "receipts"
CORRECTED = (
    ROOT / "benchmark" / "datasets" / "private" / "evaluator-checkouts"
    / "omnidocbench-deterministic-v1"
)

VERSION_RECEIPT = RECEIPTS / "evaluator-version-deterministic-v1.json"
DETERMINISM_RECEIPT = RECEIPTS / "evaluator-determinism-2026-08-18.json"
INDEPENDENCE_RECEIPT = RECEIPTS / "fallback-independence-2026-08-18.json"
LOCALITY_RECEIPT = RECEIPTS / "correction-locality-2026-08-18.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- why the correction exists ---------------------------------------------

def test_the_fallback_was_measured_to_be_dependent_on_the_gate() -> None:
    """The finding that turned a limitation into a defect in the endpoint."""
    data = load(INDEPENDENCE_RECEIPT)
    primary = data["primary_gate_vs_fallback"]
    assert primary["independent_at_0_05"] is False, (
        "if this ever reads True the correction's justification has changed and "
        "the narrative around it must be rewritten, not silently kept"
    )
    assert primary["fisher_exact_p"] < 0.05
    assert primary["abstained_fallback_rate"] > primary["accepted_fallback_rate"]
    assert data["verdict"].startswith("NOT INDEPENDENT")


# --- what the correction is -------------------------------------------------

@pytest.mark.skipif(not CORRECTED.is_dir(), reason="corrected checkout not present")
def test_deterministic_mode_disables_every_wall_clock_path() -> None:
    source = (CORRECTED / "src" / "dataset" / "end2end_dataset.py").read_text(
        encoding="utf-8"
    )
    assert "self.deterministic_matching" in source
    # Both timeouts must be neutralised together. Leaving either live
    # reintroduces load-dependent scoring through the other door.
    assert "self.match_timeout_sec = None" in source
    assert "self.quick_match_truncated_timeout_sec = None" in source
    assert "self.enable_timeout_match_fallback = False" in source
    # And the outer wrapper must be bypassed, not merely given a large timeout:
    # func_timeout runs the callable on a timer thread, which is itself a
    # scheduling-dependent path.
    assert "if self.deterministic_matching:" in source
    assert (
        "match = match_gt2pred(gt_mix, pred_dataset_mix, 'text_all', img_name)"
        in source
    )


def test_the_correction_touched_one_file_and_no_metric() -> None:
    data = load(VERSION_RECEIPT)
    assert data["files_changed"] == ["src/dataset/end2end_dataset.py"], (
        "the argument for re-measuring the holdout is that only a wall-clock "
        "decision was removed; a second changed file breaks that argument"
    )
    assert data["files_added"] == []
    assert data["files_removed"] == []
    assert data["lines_removed"] <= 2
    assert data["corrected"]["python_source_sha256"] != (
        data["derived_from"]["python_source_sha256"]
    )
    assert data["derived_from"]["revision"].startswith("193627ae9e97")


def test_the_corrected_evaluator_has_its_own_identity() -> None:
    data = load(VERSION_RECEIPT)
    assert data["version"] == "omnidocbench-deterministic-v1"
    assert len(data["corrected"]["python_source_sha256"]) == 64


# --- that it is actually deterministic --------------------------------------

@pytest.mark.skipif(
    not DETERMINISM_RECEIPT.is_file(), reason="determinism receipt not produced yet"
)
def test_one_score_hash_across_every_condition_tried() -> None:
    data = load(DETERMINISM_RECEIPT)
    assert data["evaluations"] >= 3, "at least three evaluations must be compared"
    assert data["distinct_per_page_score_hashes"] == 1
    assert data["distinct_severe_label_hashes"] == 1
    assert data["page_level_disagreements"] == []
    assert data["deterministic"] is True


@pytest.mark.skipif(
    not DETERMINISM_RECEIPT.is_file(), reason="determinism receipt not produced yet"
)
def test_no_fallback_fired_at_all() -> None:
    """Agreeing hashes while a fallback fired would be luck, not determinism.

    Counted twice on purpose. The log count can miss a fallback if a capture
    stream dies mid-run -- which happened once here, in the environment-probe
    step -- and the evaluator's own record can only be trusted if it exists at
    all. A run that cannot produce its record is unverified, not clean.
    """
    data = load(DETERMINISM_RECEIPT)
    assert data["timeout_fallback_lines_across_all_runs"] == 0
    assert data["evaluator_recorded_fallbacks_across_all_runs"] == 0
    assert data["runs_that_could_not_show_their_own_record"] == []
    assert data["runs_with_a_wall_clock_timeout_still_set"] == []


@pytest.mark.skipif(
    not DETERMINISM_RECEIPT.is_file(), reason="determinism receipt not produced yet"
)
def test_parallelism_and_page_order_were_both_varied() -> None:
    data = load(DETERMINISM_RECEIPT)
    assert len(set(data["worker_counts"])) >= 2, "worker count was not varied"
    assert "reversed" in data["page_order_variants"], "page order was not varied"


@pytest.mark.skipif(
    not DETERMINISM_RECEIPT.is_file(), reason="determinism receipt not produced yet"
)
def test_the_whole_holdout_was_re_scored_not_a_convenient_subset() -> None:
    """Determinism on a hand-picked subset would prove nothing about the endpoint.

    The contract runs the same 800-page corpus the confirmatory test uses, so it
    covers every page that used to fall back rather than a sample of them.
    """
    assert load(DETERMINISM_RECEIPT)["pages_scored"] >= 700


# --- that it changed only what it claimed to change -------------------------

@pytest.mark.skipif(
    not LOCALITY_RECEIPT.is_file(), reason="locality receipt not produced yet"
)
def test_only_pages_that_fell_back_could_move() -> None:
    """The falsifiable half of "we removed only the wall-clock decision".

    A page that never hit a fallback ran the exact matcher under both the frozen
    and the corrected evaluator, so its score cannot legitimately differ. If one
    does, the correction touched something else and the case for re-measuring
    the holdout collapses.
    """
    data = load(LOCALITY_RECEIPT)
    assert data["moved_without_any_recorded_fallback"] == []
    assert data["pages_that_fell_back_under_the_corrected_evaluator"] == 0
    assert data["locality_holds"] is True
