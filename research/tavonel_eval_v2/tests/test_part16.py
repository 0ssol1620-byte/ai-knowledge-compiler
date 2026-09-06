"""Part 16 — the evidence-hygiene pass, and what it is allowed to conclude.

These tests guard the corrections, not the results. The results were frozen
before this file existed and nothing here may move one. What can go wrong is
subtler and is exactly what a later reader would miss:

* a demotion quietly folded back into "development", so the fact that a study
  was *demoted* stops being visible;
* the forensic confirmation drifting into a rate;
* the rename being applied to the frozen protocol to tidy it up;
* a superseded receipt being edited rather than superseded.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

RECEIPTS = NS / "receipts"


def latest(prefix: str) -> dict:
    matches = sorted(RECEIPTS.glob(prefix + "--*.json"))
    assert matches, "no receipt for " + prefix
    return json.loads(matches[-1].read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# the hygiene pass itself


def test_the_hygiene_test_is_one_sided():
    """Absence of proof of exposure is not proof of absence, and the tool says so."""
    body = latest("evidence-hygiene-pass")
    for study in body["studies"].values():
        assert study["split_before"] == "held_out"
        assert study["split_after"] == "development_diagnostic"
        assert study["pre_amendment_outcome_exposures"], (
            "a demotion with no exposure listed would be an assertion, not a finding"
        )


def test_both_studies_were_frozen_after_their_runs_began():
    """The worse fact, and the one the ruling's test did not ask for."""
    body = latest("evidence-hygiene-pass")
    for study in body["studies"].values():
        assert study["executions_before_the_first_freeze"], (
            "a protocol frozen before its data would not need demoting on this ground"
        )


def test_the_demotion_is_derived_from_timestamps_not_from_recollection():
    body = latest("evidence-hygiene-pass")
    for study in body["studies"].values():
        for exposure in study["pre_amendment_outcome_exposures"]:
            assert exposure["generated_at"] < study["amendment_freeze_at"]
            assert exposure["outcome_keys_present"], (
                "an exposure with no outcome key present is not an exposure"
            )


def test_development_diagnostic_is_a_third_value_and_not_a_fold():
    """Folding it into 'development' would hide that these studies were demoted."""
    import build_claim_matrix as matrix

    assert "development_diagnostic" in matrix.SPLITS
    assert "development" in matrix.SPLITS
    assert "held_out" in matrix.SPLITS


# --------------------------------------------------------------------------
# supersession without mutation


def test_pre_amendment_receipts_are_superseded_and_not_edited():
    body = latest("pre-amendment-supersession")
    pinned = body["executions"] + body["late_freezes"]
    assert pinned
    for row in pinned:
        assert row["edited"] is False
        assert row["exists"], row["path"]
        digest = hashlib.sha256((NS / row["path"].split("tavonel_eval_v2/")[-1]).read_bytes())
        assert "sha256:" + digest.hexdigest() == row["file_sha256"], (
            "a superseded receipt whose bytes moved has been edited: " + row["path"]
        )


def test_the_interrupted_run_is_partial_and_never_a_result():
    body = latest("pre-amendment-supersession")
    interrupted = body["interrupted_run"]
    assert interrupted["state"] == "PARTIAL_EXECUTION_NO_RESULT_WRITTEN"
    assert interrupted["cohort_receipt_written"] is False


def test_the_studies_that_keep_their_split_are_named():
    body = latest("pre-amendment-supersession")
    assert set(body["not_affected"]) == {
        "VALUE_BEARING_COHORT_V1",
        "VALUE_BEARING_COHORT_V2",
        "STOP-V2-005",
    }


def test_no_number_moved_in_either_frozen_result():
    """The demotion changes a split. It is not allowed to change a count."""
    sfh1 = latest("sfh1-source-faithfulness")
    assert sfh1["verdict"] == "FAIL"
    assert sfh1["summary"]["pairs_scored"] == 310
    assert sfh1["summary"]["unclassified_changed_regions"] == 0
    assert sfh1["summary"]["pairs_with_a_silent_drop"] == 30

    study = latest("oracle-independence-v2")
    assert study["verdict"] == "FAIL"
    assert study["summary"]["pairs_judged"] == 164
    assert study["summary"]["divergent"] == 50
    assert study["summary"]["stale_escapes"] == 4


# --------------------------------------------------------------------------
# the forensic confirmation


def test_all_four_divergences_confirm_against_production_alone():
    body = latest("forensic-stale-escape")
    assert body["cases_examined"] == 4
    assert body["confirmed_selective_stale_escapes"] == 4
    for case in body["cases"]:
        assert case["verdict"] == "CONFIRMED_SELECTIVE_STALE_ESCAPE"
        carried = set(case["confirmed_stale_artifacts"])
        assert carried
        assert carried <= set(case["clean_full_rebuild"]["artifacts_that_moved"]), (
            "a confirmed escape must be an artifact the clean rebuild actually moved"
        )


def test_the_forensic_check_never_consults_the_second_implementation():
    source = (NS / "tools" / "forensic_stale_escape.py").read_text(encoding="utf-8")
    for module in ("source_derived_expected", "compare_recompilation"):
        assert "import " + module not in source, (
            "the production-only check imported " + module
        )


def test_four_cases_are_not_a_denominator():
    body = latest("forensic-stale-escape")
    disclaimed = " ".join(body["what_this_is_not"]).casefold()
    assert "not a denominator" in disclaimed
    assert "rescore" in disclaimed
    assert "rate estimate" in disclaimed


def test_no_confirmed_escape_was_a_missed_substantive_edit():
    body = latest("forensic-stale-escape-root-cause")
    classes = body["stale_artifact_difference_classes"]
    assert "substantive" not in classes, (
        "if one were substantive the finding would be a lost edit, not an "
        "alignment failure, and the report says the wrong thing"
    )
    assert sum(classes.values()) == 4


def test_the_normalisation_ladder_is_declared_and_ordered():
    import forensic_stale_escape_root_cause as root

    assert root.LADDER[0][0] == "identical"
    names = [name for name, _ in root.LADDER]
    assert names.index("whitespace") < names.index("alphanumeric")

    # cumulative: a rung agrees on everything an earlier rung agreed on
    pair = ("The  “value”", "The &quot;value&quot;")
    assert root.difference_class(*pair) != "identical"
    assert root.difference_class("a b", "a  b") == "whitespace"
    assert root.difference_class("alpha", "beta") == root.SUBSTANTIVE


# --------------------------------------------------------------------------
# the rename


def test_the_frozen_protocol_was_not_edited_to_carry_the_new_name():
    body = latest("study-rename")
    protocol = next(
        row for row in body["not_renamed"] if row["path"].endswith("ORACLE_INDEPENDENCE_V2.yaml")
    )
    pinned = NS / protocol["pinned_by"].split("tavonel_eval_v2/")[-1]
    freeze = json.loads(pinned.read_text(encoding="utf-8"))
    actual = hashlib.sha256((NS / "protocols" / "ORACLE_INDEPENDENCE_V2.yaml").read_bytes())
    assert "sha256:" + actual.hexdigest() == freeze["protocol_sha256"]
    assert protocol["sha256"] == freeze["protocol_sha256"]


def test_the_result_receipt_was_not_edited_either():
    body = latest("study-rename")
    result = next(row for row in body["not_renamed"] if "receipts/" in row["path"])
    path = NS / result["path"].split("tavonel_eval_v2/")[-1]
    assert "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() == result["sha256"]


def test_the_new_name_reaches_every_surface_that_asserts_one():
    body = latest("study-rename")
    for row in body["renamed_surfaces"]:
        #: collapsed and casefolded, because prose wraps the name across lines
        #: and a heading capitalises it. Neither is a different name.
        text = " ".join((NS / row["path"]).read_text(encoding="utf-8").split()).casefold()
        assert body["name_is"].casefold() in text, (
            row["path"] + " does not carry the new name"
        )


def test_the_retired_name_is_forbidden_wording():
    matrix = yaml.safe_load((NS / "paper" / "CLAIM_MATRIX.yaml").read_text(encoding="utf-8"))
    phrases = {
        phrase.casefold()
        for entry in matrix["forbidden_claims"]
        for phrase in entry["phrases"]
    }
    assert "independent oracle verification" in phrases
    assert "independently verified" in phrases


def test_the_draft_uses_no_forbidden_phrase():
    """Only the draft. The report must be able to *name* a forbidden claim in
    order to record that it is forbidden, and does; the draft is the surface
    that would assert one."""
    surface = "paper/TAVONEL_PAPER_DRAFT_INTERNAL.md"
    matrix = yaml.safe_load((NS / "paper" / "CLAIM_MATRIX.yaml").read_text(encoding="utf-8"))
    text = (NS / surface).read_text(encoding="utf-8").casefold()
    for entry in matrix["forbidden_claims"]:
        for phrase in entry["phrases"]:
            assert phrase.casefold() not in text, (
                f"{surface} carries forbidden phrase {phrase!r} ({entry['id']})"
            )


# --------------------------------------------------------------------------
# the corrected readiness wording


def test_negative_held_out_studies_are_not_described_as_development_only():
    matrix = yaml.safe_load((NS / "paper" / "CLAIM_MATRIX.yaml").read_text(encoding="utf-8"))
    gap = next(row for row in matrix["paper_readiness_gaps"] if row["id"] == "G-01")
    assert "what_this_gap_is_not" in gap, (
        "G-01 must distinguish a missing confirmatory mechanism result from the "
        "held-out negative closure evidence the programme does have"
    )


def test_the_draft_separates_the_two_demoted_studies_from_the_held_out_negatives():
    text = (NS / "paper" / "TAVONEL_PAPER_DRAFT_INTERNAL.md").read_text(encoding="utf-8")
    assert "development diagnostic" in text
    assert "negative closure evidence" in text


def test_the_draft_bounds_the_equivalence_result_by_the_confirmed_escapes():
    text = (NS / "paper" / "TAVONEL_PAPER_DRAFT_INTERNAL.md").read_text(encoding="utf-8")
    assert "not reproducible by a clean rebuild" in text


def test_the_report_marks_part_13_superseded_in_framing_only():
    text = (NS / "V2_CONSOLIDATED_REPORT_2026-08-21.md").read_text(encoding="utf-8")
    assert "superseded in its framing by Part 14" in text
    assert "Every number below\n> stands exactly as executed" in text


def test_the_programme_still_spent_no_gpu():
    for prefix in ("evidence-hygiene-pass", "pre-amendment-supersession",
                   "forensic-stale-escape", "forensic-stale-escape-root-cause",
                   "study-rename", "claim-matrix"):
        body = latest(prefix)
        assert body["gpu_seconds"] == 0
        assert body["estimated_cost_usd"] == 0.0
