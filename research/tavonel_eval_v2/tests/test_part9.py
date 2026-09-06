"""The P4g result, and the shape of the response to it.

Eligible Q1 = 174 against a floor of 190. Every test here exists because the
cheapest way to reach 190 from 174 is to change something that should not
change, and each of those routes is closed by a specific line somewhere in the
repository. These check the lines are still there.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(NS / "canonicalization"))
sys.path.insert(0, str(NS / "tools"))

RECEIPT = sorted((NS / "receipts").glob("p4g--*.json"))
PROTOCOL = NS / "protocols" / "P4h_cohort_expansion.yaml"


@pytest.fixture(scope="module")
def result() -> dict:
    assert RECEIPT, "no P4g receipt"
    return json.loads(RECEIPT[-1].read_text(encoding="utf-8"))


def test_the_cohort_was_scored_exactly_once(result: dict) -> None:
    """A run that dies before producing a figure has not consumed the budget."""
    assert len(RECEIPT) == 1, [path.name for path in RECEIPT]
    assert result["gates"]["G_P4G_SCORED_ONCE"]["passed"] is True


def test_the_recorded_figure(result: dict) -> None:
    assert result["totals"]["locally_complete_q1"] == 174
    assert result["totals"]["q1_questions"] == 1014
    assert result["totals"]["questions_scored"] == 3710
    assert result["cohort"]["documents"] == 321


def test_the_floor_was_not_lowered_to_meet_the_figure(result: dict) -> None:
    gate = result["decision_gate"]
    assert gate["hard_minimum_eligible_Q1"] == 190
    assert gate["meets_floor"] is False
    assert gate["outcome"] == "REPORT_AND_STOP_NO_GPU_REQUEST"


def test_no_gpu_was_authorised_and_nothing_was_spent(result: dict) -> None:
    assert result["gpu_authorised_by_this_result"] is False
    assert result["gpu_seconds"] == 0
    assert result["estimated_cost_usd"] == 0.0


def test_the_scale_gate_failed_and_was_not_quietly_passed(result: dict) -> None:
    """321 of 400. The measurement is not reported as if the cohort were full."""
    assert result["verdict"] == "FAIL"
    assert result["gates"]["G_P4G_SCALE"]["passed"] is False
    others = {
        name: gate["passed"]
        for name, gate in result["gates"].items()
        if name != "G_P4G_SCALE"
    }
    assert all(others.values()), others


def test_all_four_families_are_in_the_scored_cohort(result: dict) -> None:
    assert set(result["cohort"]["family_counts"]) == {
        "encyclopedia_wikipedia",
        "git_docs",
        "regulation_ecfr",
        "sec_edgar",
    }
    assert result["gates"]["G_P4G_NO_NARROWING"]["passed"] is True


def test_a_family_that_yielded_nothing_is_still_reported(result: dict) -> None:
    """sec_edgar contributed 0 eligible Q1 and stays in the record."""
    assert result["q1_by_family"]["sec_edgar"] == 56
    assert result["locally_complete_q1_by_family"].get("sec_edgar", 0) == 0


def test_position_is_no_longer_the_limitation(result: dict) -> None:
    assert result["location_unverifiable_spans"] == 0


def test_the_ecfr_family_was_unlocked_by_the_markup_policy(result: dict) -> None:
    """0 eligible under Locality v2; 58 here. The workstream did something."""
    assert result["locally_complete_q1_by_family"]["regulation_ecfr"] == 58


def test_class_drives_the_unresolved_refusals(result: dict) -> None:
    drivers = result["unresolved_drivers"]
    assert drivers["attr:class"] == 1795
    assert result["witness_failures_by_reason"]["UNRESOLVED_SOURCE_FACT_IN_CLOSURE"] == 1878


def test_class_is_still_unresolved_after_seeing_the_number() -> None:
    """The one-line change that would clear the floor. It must not have happened."""
    from markup_policy import EXTERNAL_DEPENDENCY, UNRESOLVED  # noqa: PLC0415
    from markup_semantics import blocks_completeness, classify_attribute  # noqa: PLC0415

    for name in ("class", "style"):
        got = classify_attribute(name)
        assert got["state"] == UNRESOLVED, name
        assert got["facet"] == EXTERNAL_DEPENDENCY
        assert blocks_completeness(got["state"])


def test_the_instrument_that_produced_174_is_the_one_p4h_freezes() -> None:
    from run_p4g import composite_identity  # noqa: PLC0415

    text = PROTOCOL.read_text(encoding="utf-8")
    assert "composite_at_freeze: " + composite_identity()["composite"] in text


def test_p4h_keeps_the_floor_and_refuses_to_reweight_the_mix() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "hard_minimum_eligible_Q1: 190" in text
    assert "G_P4H_MIX_NOT_REWEIGHTED" in text
    assert "not lowered to 174" in text
    assert "source_documents: 550" in text


def test_p4h_quotas_keep_the_balance_rule() -> None:
    import re  # noqa: PLC0415

    text = PROTOCOL.read_text(encoding="utf-8")
    block = text.split("family_quota:", 1)[1].split("balance_rule:", 1)[0]
    quotas = {
        name: int(value) for name, value in re.findall(r"(\w+): (\d+)", block)
    }
    assert set(quotas) == {
        "git_docs",
        "regulation_ecfr",
        "encyclopedia_wikipedia",
        "sec_edgar",
    }
    assert max(quotas.values()) / sum(quotas.values()) <= 0.31


def test_p4h_has_no_composite_identity_escape_clause() -> None:
    """P4g needed one for INC-V2-013. There is no known further gap."""
    text = PROTOCOL.read_text(encoding="utf-8")
    identity = text.split("gate:", 1)[1].split("the_specific_temptation", 1)[0]
    assert "recorded incident explains" not in identity


def test_p4h_was_frozen_before_any_further_acquisition() -> None:
    receipts = sorted((NS / "receipts").glob("p4h-cohort-expansion--*.json"))
    assert receipts
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    assert body["frozen_before_any_result"] is True
    assert body["protocol_sha256"].startswith("sha256:")


def test_the_predecessors_were_not_rescored(result: dict) -> None:
    assert set(result["predecessors_not_rescored"]) >= {
        "P0d",
        "P4e",
        "SOURCE_LOCALITY_V2",
    }
    for pattern in ("locality-v2--*.json", "p4e-provenance-retrieval--*.json"):
        assert sorted((NS / "receipts").glob(pattern)), pattern
