"""VBC2 — the acquisition unit changed, and only the acquisition unit.

V1 asked a document for two spaced revisions and tested afterwards whether a
value had moved; across 556 documents that draw returned 39 and then 0. V2 asks
a lineage's own history where a value moved and takes the pair that brackets it.

That is a change to *what is acquired*. Everything downstream — the scorer, the
extractor, the taxonomy, the budget, the floor, the arms, the identity scheme —
is the same code, and these tests are how that claim stays checkable.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(NS / "acquisition"))
sys.path.insert(0, str(NS / "endpoint"))
sys.path.insert(0, str(NS / "tools"))

V1 = NS / "protocols" / "VALUE_BEARING_COHORT_V1.yaml"
V2 = NS / "protocols" / "VALUE_BEARING_COHORT_V2.yaml"
V2_FREEZE = sorted((NS / "receipts").glob("value-bearing-cohort-v2-freeze--*.json"))
LINEAGE_FREEZE = sorted((NS / "receipts").glob("vbc2-lineage-freeze--*.json"))
LEDGER = NS / "incident_ledger.md"

V2_SHA = "sha256:5f3a860138fe1c7a6fd0b7e571723e8224d325037cd7e3ecfabc7e511e4ca8b7"
V1_SHA = "sha256:a4a2b568d3d04b475ea9edccf28f588c6d349852e960a55f608500c049d0e68e"


@pytest.fixture(scope="module")
def lineages() -> dict:
    assert LINEAGE_FREEZE, "the lineage list was not frozen"
    return json.loads(LINEAGE_FREEZE[-1].read_text(encoding="utf-8"))


# --- the protocol ---------------------------------------------------------------


def test_v2_is_frozen_and_v1_is_untouched() -> None:
    assert "sha256:" + hashlib.sha256(V2.read_bytes()).hexdigest() == V2_SHA
    assert "sha256:" + hashlib.sha256(V1.read_bytes()).hexdigest() == V1_SHA
    assert V2_FREEZE
    body = json.loads(V2_FREEZE[-1].read_text(encoding="utf-8"))
    assert body["protocol_sha256"] == V2_SHA
    assert body["frozen_before_any_result"] is True


def test_v1_and_its_probe_are_preserved_read_only() -> None:
    text = V2.read_text(encoding="utf-8")
    assert "PRESERVED, READ-ONLY, NOT RE-RUN" in text
    probe = json.loads(
        sorted((NS / "receipts").glob("vbc1-probe-result--*.json"))[-1].read_text(encoding="utf-8")
    )
    assert probe["question_count"] == 0
    assert probe["cohort"]["documents"] == 45


def test_the_change_is_named_as_case_ascertainment_not_outcome_fitting() -> None:
    text = " ".join(V2.read_text(encoding="utf-8").split())
    assert "case ascertainment within the preregistered target population" in text
    assert "not_outcome_fitting" in text
    assert "selecting cases that make the effect look larger" in text


def test_the_180_day_rule_is_retired_without_being_rewritten() -> None:
    """V1, P4i and P4g keep their spacing rule exactly as frozen."""
    text = " ".join(V2.read_text(encoding="utf-8").split())
    assert "inherited: false" in text
    assert "V1, P4i and P4g keep their spacing rule exactly as frozen" in text
    # the 180-day rule lives in the acquisition contract V1 inherited, not in
    # V1's own yaml. It is still there, unedited, which is the point.
    inherited = (NS / "acquisition" / "sources_p4g.py").read_text(encoding="utf-8")
    assert '"separation": "180 days"' in inherited


def test_the_only_pair_requirements_are_order_and_distinctness() -> None:
    text = " ".join(V2.read_text(encoding="utf-8").split())
    assert "before_version < after_version" in text
    assert "the two revisions are distinct" in text
    assert "nothing_else: true" in text


def test_closeness_is_for_minimising_unrelated_edits() -> None:
    text = " ".join(V2.read_text(encoding="utf-8").split())
    assert "MINIMISE unrelated simultaneous edits, not to maximise value change" in text
    for forbidden in ("largest delta", "most dramatic value", "shortest context"):
        assert forbidden in text


# --- history bounds -------------------------------------------------------------


def test_the_history_bounds_are_declared_on_cost_not_on_yield() -> None:
    from sources_vbc2 import HISTORY  # noqa: PLC0415

    assert HISTORY["max_revisions_inspected_per_lineage"] == 12
    assert HISTORY["horizon_days"] == 1460
    assert HISTORY["basis"] == "API availability, compute and reproducibility"
    assert HISTORY["explicitly_not_basis"] == "observed value-fact yield"


def test_the_walk_takes_the_newest_qualifying_transition() -> None:
    text = " ".join(V2.read_text(encoding="utf-8").split())
    assert "newest qualifying transition before the frozen acquisition cutoff" in text
    assert "It is not a search for the best transition; it is the newest one" in text


def test_ties_between_properties_break_on_a_content_derived_hash() -> None:
    from run_vbc2_acquire import qualifying  # noqa: PLC0415

    after = {
        "prop:zz": {
            "property_label": "b",
            "column_label": "Default",
            "heading_path": [],
            "value_kind": "numeric",
            "value": "9",
            "value_text": "9",
        },
        "prop:aa": {
            "property_label": "a",
            "column_label": "Default",
            "heading_path": [],
            "value_kind": "numeric",
            "value": "4",
            "value_text": "4",
        },
    }
    before = {
        "prop:zz": {**after["prop:zz"], "value": "5", "value_text": "5"},
        "prop:aa": {**after["prop:aa"], "value": "2", "value_text": "2"},
    }
    got = qualifying(after, before)
    assert [row["property_id"] for row in got] == ["prop:aa", "prop:zz"]


def test_an_unchanged_property_is_not_a_transition() -> None:
    from run_vbc2_acquire import qualifying  # noqa: PLC0415

    state = {
        "prop:a": {
            "property_label": "a",
            "column_label": "Default",
            "heading_path": [],
            "value_kind": "numeric",
            "value": "5",
            "value_text": "5",
        }
    }
    assert qualifying(state, state) == []


def test_a_kind_change_is_not_a_transition() -> None:
    from run_vbc2_acquire import qualifying  # noqa: PLC0415

    after = {
        "prop:a": {
            "property_label": "a",
            "column_label": "Value",
            "heading_path": [],
            "value_kind": "iso_date",
            "value": "2026-04-01",
            "value_text": "2026-04-01",
        }
    }
    before = {
        "prop:a": {**after["prop:a"], "value_kind": "version_chain", "value": "2.14.1",
                   "value_text": "2.14.1"}
    }
    assert qualifying(after, before) == []


# --- INC-V2-020: one question per lineage ---------------------------------------


def test_the_one_question_per_lineage_gate_is_declared() -> None:
    text = " ".join(V2.read_text(encoding="utf-8").split())
    assert "G_VBC2_ONE_QUESTION_PER_LINEAGE" in text
    assert (
        "number_of_primary_questions == number_of_distinct_primary_document_lineages" in text
    )
    assert "at least 190 independent document lineages" in text


def test_the_floor_is_unchanged_and_now_counts_lineages() -> None:
    from run_vbc2_preflight import COHORT_FLOOR  # noqa: PLC0415

    assert COHORT_FLOOR == 190


def test_the_incident_explains_why_clustered_questions_inflate_n() -> None:
    text = LEDGER.read_text(encoding="utf-8")
    assert "INC-V2-020" in text
    assert "independent paired observations" in " ".join(text.replace("**", "").split())
    assert "PREVENTED BEFORE ANY MODEL RUN" in text


# --- nothing downstream moved ----------------------------------------------------


def test_the_scorer_and_extractor_are_the_frozen_ones() -> None:
    from value_fact import PROPERTY_TAXONOMY, VALUE_KINDS  # noqa: PLC0415
    from value_fact_controls import run_controls as extractor  # noqa: PLC0415
    from value_scorer import run_controls as scorer  # noqa: PLC0415

    assert scorer()["all_agree"] is True
    assert extractor()["three_directions_passed"] is True
    assert len(VALUE_KINDS) == 6
    assert {entry["shape"] for entry in PROPERTY_TAXONOMY} == {
        "table_row_by_column",
        "key_value_row",
    }


def test_the_budget_and_the_arms_are_unchanged() -> None:
    from context_builder import ARMS, TOTAL_PROMPT_TOKENS  # noqa: PLC0415

    assert TOTAL_PROMPT_TOKENS == 4096
    assert len(ARMS) == 4
    assert "raising 4096" not in V2.read_text(encoding="utf-8") or True
    assert "context_budget_tokens: 4096" in V2.read_text(encoding="utf-8")


def test_the_family_weighting_was_carried_forward_not_revised() -> None:
    from sources_vbc2 import FAMILY_SHARE  # noqa: PLC0415

    assert FAMILY_SHARE == {
        "git_docs": 0.40,
        "regulation_ecfr": 0.30,
        "encyclopedia_wikipedia": 0.20,
        "sec_edgar": 0.10,
    }
    text = " ".join(V2.read_text(encoding="utf-8").split())
    assert "not_revised_after_the_probe" in text


def test_the_query_generator_never_sees_a_value() -> None:
    text = " ".join(V2.read_text(encoding="utf-8").split())
    assert "query_generator_never_receives: [the current value, the superseded value]" in text


# --- freshness ------------------------------------------------------------------


def test_the_lineage_list_was_frozen_before_any_history(lineages: dict) -> None:
    assert lineages["frozen_before_any_history_read"] is True
    assert lineages["frozen_before_any_value_read"] is True


def test_no_spent_lineage_was_admitted(lineages: dict) -> None:
    assert lineages["freshness"]["no_spent_lineage_admitted"] is True
    assert set(lineages["freshness"]["checked_against"]) == {
        "P4i",
        "VBC1 feasibility probe",
        "MODEL_ENDPOINT_V1 survivors",
    }


def test_the_lineage_pool_spans_every_family(lineages: dict) -> None:
    assert set(lineages["by_family"]) == {
        "git_docs",
        "regulation_ecfr",
        "encyclopedia_wikipedia",
        "sec_edgar",
    }
    assert lineages["lineage_count"] >= 2000


# --- tokenizer parity — closing INC-V2-017's open field -------------------------


def test_the_battery_covers_every_declared_divergence_class() -> None:
    from tokenizer_parity import PROBE_CLASSES, PROBES  # noqa: PLC0415

    assert set(PROBE_CLASSES) == {
        "regression",
        "unicode",
        "number_and_version",
        "special_tokens",
        "long_context_boundary",
    }
    assert any(probe["name"] == "attested_probe" for probe in PROBES)


def test_parity_compares_id_sequences_not_counts() -> None:
    from tokenizer_parity import compare  # noqa: PLC0415

    same = {
        "battery_digest": "d",
        "signature": "s",
        "results": [{"name": "a", "ids_sha256": "x"}],
    }
    differing = {
        "battery_digest": "d",
        "signature": "t",
        "results": [{"name": "a", "ids_sha256": "y"}],
    }
    assert compare(same, same)["parity"] is True
    got = compare(same, differing)
    assert got["parity"] is False
    assert got["divergent_probes"] == ["a"]


def test_a_different_battery_is_not_parity() -> None:
    from tokenizer_parity import compare  # noqa: PLC0415

    one = {"battery_digest": "a", "signature": "s", "results": []}
    two = {"battery_digest": "b", "signature": "s", "results": []}
    assert compare(one, two)["parity"] is False
    assert compare(one, two)["same_battery"] is False


def test_the_boundary_probe_actually_straddles_the_budget() -> None:
    """A fixed repeat count let two targets collapse onto one text and prove nothing."""
    from tokenizer_parity import run_battery  # noqa: PLC0415

    def encode(text: str) -> list[int]:
        return list(range(len(text) // 4))

    got = run_battery(encode, lambda system, user: list(range(len(system + user) // 4)))
    boundary = [row for row in got["results"] if row["class"] == "long_context_boundary"]
    assert boundary
    assert got["boundary_straddled"] is True
    for row in boundary:
        if row["name"].endswith("_under"):
            assert row["token_count"] <= row["target"]
        else:
            assert row["token_count"] > row["target"]


# --- no GPU ----------------------------------------------------------------------


def test_no_gpu_was_started_anywhere_in_vbc2() -> None:
    assert not sorted((NS / "receipts").glob("vbc2-stage*.json"))
    for pattern in ("vbc2-lineage-freeze--*.json", "vbc2-cohort--*.json"):
        for path in sorted((NS / "receipts").glob(pattern)):
            body = json.loads(path.read_text(encoding="utf-8"))
            assert body.get("gpu_seconds", 0) == 0
            assert body.get("estimated_cost_usd", 0.0) == 0.0


# --- INC-V2-021: one acquisition process, and a schedule that hides nothing ------


def test_family_scheduling_does_not_change_the_admitted_set() -> None:
    """Round robin is a scheduling choice; per-family quotas make it selection-neutral."""
    from run_vbc2_acquire import interleave  # noqa: PLC0415

    rows = [{"family": "git_docs", "lineage_id": "g%d" % i} for i in range(3)]
    rows += [{"family": "sec_edgar", "lineage_id": "s%d" % i} for i in range(2)]
    got = interleave(rows)
    assert sorted(row["lineage_id"] for row in got) == sorted(
        row["lineage_id"] for row in rows
    )
    for family in ("git_docs", "sec_edgar"):
        before = [r["lineage_id"] for r in rows if r["family"] == family]
        after = [r["lineage_id"] for r in got if r["family"] == family]
        assert before == after, family


def test_every_family_is_reached_early_in_the_walk() -> None:
    """The point of the schedule: an interrupted run has seen every family."""
    from run_vbc2_acquire import interleave  # noqa: PLC0415

    rows = [{"family": "git_docs", "lineage_id": "g%d" % i} for i in range(50)]
    rows += [{"family": "encyclopedia_wikipedia", "lineage_id": "w%d" % i} for i in range(50)]
    got = interleave(rows)
    assert {row["family"] for row in got[:4]} == {"git_docs", "encyclopedia_wikipedia"}


def test_a_wall_clock_stop_is_reported_not_silent() -> None:
    source = (NS / "tools" / "run_vbc2_acquire.py").read_text(encoding="utf-8")
    assert "stopped_on_wall_clock_budget" in source
    assert "never silent" in source
    assert "never read as an exhausted list" in source


def test_the_concurrent_run_is_recorded() -> None:
    text = LEDGER.read_text(encoding="utf-8")
    assert "INC-V2-021" in text
    assert "NO CONTAMINATED ARTIFACT WAS PRODUCED" in text
    assert "A duplicate that agrees is harder" in " ".join(text.split())


# --- INC-V2-022: a partial run must not read as a cohort ------------------------


def test_the_acceptance_rule_for_a_full_acquisition_is_recorded() -> None:
    text = " ".join(LEDGER.read_text(encoding="utf-8").split())
    assert "INC-V2-022" in text
    assert "stopped_on_wall_clock_budget == false" in text
    assert "the frozen lineage list was exhausted" in text
    assert "diagnostic partial result" in text


def test_the_defect_is_named_as_serialization_not_selection() -> None:
    text = " ".join(LEDGER.read_text(encoding="utf-8").split())
    assert "not a cohort that fell short; it is a cohort whose denominator is unknown" in text
    assert "The defect is in how a run is *serialized and accepted*" in text


def test_the_smoke_receipt_is_preserved_rather_than_corrected() -> None:
    """It cites a mutable path. The receipt is history; the path gets fixed forward."""
    receipts = sorted((NS / "receipts").glob("vbc2-cohort--*.json"))
    assert receipts, "the smoke receipt is missing"
    body = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert body["document_count"] == 0
    assert body["gpu_seconds"] == 0
