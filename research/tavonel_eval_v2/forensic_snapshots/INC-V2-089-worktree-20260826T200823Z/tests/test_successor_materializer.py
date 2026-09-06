"""Tests for `tools/materialize_successor_inputs.py` and `tools/kill_switch.py`
-- the two zero-cost, CPU-only pieces the GPU successor study's unattended
launch depends on but has not yet needed to run.

No network, no GPU, no real cohort manifest, no real Runpod usage telemetry.
Every fixture below is either a small inline stand-in shaped like
`build_successor_cohort.build_manifest`'s own output, or a directly-constructed
`kill_switch.Usage`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "source_fact_ir", "endpoint"):
    sys.path.insert(0, str(NS / _sub))

import build_successor_cohort as bsc  # noqa: E402
import gpu_successor_preflight as gsp  # noqa: E402
import ir  # noqa: E402
import kill_switch as ks  # noqa: E402
import materialize_successor_inputs as msi  # noqa: E402
import successor_prompt_schema as sps  # noqa: E402

# ===========================================================================
# materialize_successor_inputs.py
# ===========================================================================

# ---------------------------------------------------------------------------
# fixtures -- shaped like build_successor_cohort.build_manifest's own output
# ---------------------------------------------------------------------------


def _fact(*, fact_id: str, kind: str, representation: Any) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "kind": kind,
        "state": ir.REPRESENTED,
        "lineage_id": f"lineage-{fact_id}",
        "family": "fixture_family",
        "current_revision": "v2",
        "preceding_revision": "v1",
        "witness": {"excerpt": "prose that never names the target"},
        "representation": representation,
    }


def _atom(*, atom_id: str, path: str, text: str) -> dict[str, Any]:
    return {"atom_id": atom_id, "path": path, "text": text}


def _manifest(facts: list[dict[str, Any]], *, feasible: bool = True) -> dict[str, Any]:
    return {
        "schema": bsc.MANIFEST_SCHEMA,
        "study_id": gsp.STUDY_ID,
        "eligible_count": len(facts),
        "floor": gsp.COHORT_FLOOR,
        "feasible": feasible,
        "facts": facts,
        "facts_digest": "sha256:fixture",
        "prompt_schema_digest": sps.schema_digest(),
    }


def _context_for(fact_id: str) -> dict[str, list[dict[str, Any]]]:
    """One fact's context candidates for both arms -- deliberately different
    text per arm, the way a real current-revision vs preceding-revision
    context would be."""
    return {
        sps.ARM_VERIFIED_CURRENT_TYPED: [
            _atom(atom_id=f"{fact_id}-cur-1", path="doc/current.md", text="current revision text")
        ],
        sps.ARM_STALE_APPEND_ONLY: [
            _atom(
                atom_id=f"{fact_id}-stale-1",
                path="doc/preceding.md",
                text="preceding revision text, a wholly different artifact",
            )
        ],
    }


def _basic_case() -> tuple[dict[str, Any], dict[str, dict[str, list[dict[str, Any]]]]]:
    fact = _fact(fact_id="fact-1", kind=ir.LANGUAGE, representation={"iso": "en"})
    manifest = _manifest([fact])
    context_by_fact = {"fact-1": _context_for("fact-1")}
    return manifest, context_by_fact


# ---------------------------------------------------------------------------
# 1. deterministic ordering and a stable digest across two builds
# ---------------------------------------------------------------------------


def test_materialize_is_deterministic_across_two_calls():
    manifest, context_by_fact = _basic_case()
    first = msi.materialize(manifest, context_by_fact=context_by_fact)
    second = msi.materialize(manifest, context_by_fact=context_by_fact)
    assert first["set_digest"] == second["set_digest"]
    assert first["items"] == second["items"]
    assert first["set_digest"].startswith("sha256:")


def test_materialize_orders_items_by_kind_then_fact_id_regardless_of_input_order():
    facts = [
        _fact(fact_id="fact-b", kind=ir.EFFECTIVE_TIME, representation={"date": "2024-01-01"}),
        _fact(fact_id="fact-a", kind=ir.APPLICABILITY, representation={"scope": "US"}),
    ]
    manifest = _manifest(facts)
    context_by_fact = {"fact-a": _context_for("fact-a"), "fact-b": _context_for("fact-b")}

    forward = msi.materialize(manifest, context_by_fact=context_by_fact)

    manifest_reversed = dict(manifest)
    manifest_reversed["facts"] = list(reversed(facts))
    backward = msi.materialize(manifest_reversed, context_by_fact=context_by_fact)

    forward_ids = [item["fact_id"] for item in forward["items"]]
    backward_ids = [item["fact_id"] for item in backward["items"]]
    assert forward_ids == backward_ids
    assert forward["set_digest"] == backward["set_digest"]
    # APPLICABILITY < EFFECTIVE_TIME lexically, so fact-a leads
    assert forward_ids[0] == "fact-a"


# ---------------------------------------------------------------------------
# 2. both arms materialize from the same manifest, only context differs
# ---------------------------------------------------------------------------


def test_both_arms_materialize_from_the_same_manifest_only_context_differs():
    manifest, context_by_fact = _basic_case()
    result = msi.materialize(manifest, context_by_fact=context_by_fact)
    item = result["items"][0]
    comparison = item["identical_except_context"]
    assert comparison["identical_except_context"] is True
    assert comparison["mismatches"] == {}

    verified = item["arms"][sps.ARM_VERIFIED_CURRENT_TYPED]
    stale = item["arms"][sps.ARM_STALE_APPEND_ONLY]
    assert verified["context_blocks"] != stale["context_blocks"]
    assert verified["user_prompt"] != stale["user_prompt"]
    for field in sps.IDENTICAL_ACROSS_ARMS_FIELDS:
        assert verified[field] == stale[field], field


def test_arm_divergence_beyond_context_is_refused():
    manifest, context_by_fact = _basic_case()

    real_build = sps.build_arm_request

    def poisoned_build(**kwargs):
        request = real_build(**kwargs)
        if kwargs["arm"] == sps.ARM_STALE_APPEND_ONLY:
            # simulate a bug that let max_new_tokens vary by arm
            request = msi.sps.ArmRequest(**{**request.as_dict(), "max_new_tokens": 999})
        return request

    original = msi.sps.build_arm_request
    msi.sps.build_arm_request = poisoned_build
    try:
        with pytest.raises(msi.MaterializationRefused):
            msi.materialize(manifest, context_by_fact=context_by_fact)
    finally:
        msi.sps.build_arm_request = original


# ---------------------------------------------------------------------------
# 3. refuses on an infeasible manifest
# ---------------------------------------------------------------------------


def test_infeasible_manifest_is_refused():
    manifest, context_by_fact = _basic_case()
    manifest["feasible"] = False
    with pytest.raises(msi.MaterializationRefused, match="feasible"):
        msi.materialize(manifest, context_by_fact=context_by_fact)


def test_manifest_missing_feasible_key_is_refused_not_assumed_true():
    manifest, context_by_fact = _basic_case()
    del manifest["feasible"]
    with pytest.raises(msi.MaterializationRefused):
        msi.materialize(manifest, context_by_fact=context_by_fact)


# ---------------------------------------------------------------------------
# 4. refuses if the prompt schema digest does not match (or is absent)
# ---------------------------------------------------------------------------


def test_prompt_schema_digest_mismatch_is_refused():
    manifest, context_by_fact = _basic_case()
    manifest["prompt_schema_digest"] = "sha256:" + "0" * 64
    with pytest.raises(msi.MaterializationRefused, match="prompt_schema_digest"):
        msi.materialize(manifest, context_by_fact=context_by_fact)


def test_prompt_schema_digest_absent_is_refused_not_skipped():
    manifest, context_by_fact = _basic_case()
    del manifest["prompt_schema_digest"]
    with pytest.raises(msi.MaterializationRefused, match="prompt_schema_digest"):
        msi.materialize(manifest, context_by_fact=context_by_fact)


def test_matching_prompt_schema_digest_is_accepted():
    manifest, context_by_fact = _basic_case()
    assert manifest["prompt_schema_digest"] == sps.schema_digest()
    result = msi.materialize(manifest, context_by_fact=context_by_fact)
    assert result["prompt_schema_digest"] == sps.schema_digest()


# ---------------------------------------------------------------------------
# 5. refuses, per fact, if context is missing for a fact or an arm
# ---------------------------------------------------------------------------


def test_fact_with_no_context_entry_at_all_is_refused():
    manifest, _ = _basic_case()
    with pytest.raises(msi.MaterializationRefused, match="fact-1"):
        msi.materialize(manifest, context_by_fact={})


def test_fact_missing_context_for_one_arm_is_refused():
    manifest, context_by_fact = _basic_case()
    del context_by_fact["fact-1"][sps.ARM_STALE_APPEND_ONLY]
    with pytest.raises(msi.MaterializationRefused, match=sps.ARM_STALE_APPEND_ONLY):
        msi.materialize(manifest, context_by_fact=context_by_fact)


# ---------------------------------------------------------------------------
# 6. truncation is reused from context_builder, not reimplemented, and can
#    differ per arm when the candidate pools differ in size
# ---------------------------------------------------------------------------


def test_narrow_budget_truncates_via_context_builder_fit_to_budget():
    fact = _fact(fact_id="fact-budget", kind=ir.REFERENCE_TARGET, representation={"target": "x"})
    manifest = _manifest([fact])
    context_by_fact = {
        "fact-budget": {
            sps.ARM_VERIFIED_CURRENT_TYPED: [
                _atom(atom_id=f"cur-{i}", path=f"doc/{i}.md", text="word " * 50)
                for i in range(20)
            ],
            sps.ARM_STALE_APPEND_ONLY: [
                _atom(atom_id=f"stale-{i}", path=f"doc/{i}.md", text="word " * 50)
                for i in range(20)
            ],
        }
    }
    # a tiny budget: only a handful of candidates can survive
    result = msi.materialize(manifest, context_by_fact=context_by_fact, budget=200)
    item = result["items"][0]
    verified_blocks = item["arms"][sps.ARM_VERIFIED_CURRENT_TYPED]["context_blocks"]
    assert 0 < len(verified_blocks) < 20


def test_default_token_counter_is_a_declared_approximation_not_a_measurement():
    count = msi._default_token_counter("a b c", "d e")
    assert count == 5


# ---------------------------------------------------------------------------
# 7. CLI main() round-trips through evidence.write_immutable
# ---------------------------------------------------------------------------


def test_main_writes_an_immutable_receipt(tmp_path, monkeypatch):
    # Follows the same convention `tests/test_launch_gpu_successor.py` uses:
    # `write_immutable` is faked, not exercised for real, because
    # `common.rel()` requires paths under the repository ROOT and `tmp_path`
    # is not one -- this test is about `main()` wiring `materialize`'s output
    # into `write_immutable` correctly, not about `evidence.py`'s own path
    # handling, which is exercised elsewhere.
    manifest, context_by_fact = _basic_case()
    manifest_path = tmp_path / "typed_fact_cohort.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps(context_by_fact), encoding="utf-8")

    captured: dict[str, Any] = {}

    def fake_write_immutable(stem, body, **kwargs):
        captured["stem"] = stem
        captured["body"] = body
        return {"receipt": "fixture-receipt.json", "run_id": "fixture-run"}

    monkeypatch.setattr(msi, "write_immutable", fake_write_immutable)

    exit_code = msi.main([str(manifest_path), str(context_path)])
    assert exit_code == 0
    assert captured["stem"] == msi.RECEIPT_STEM
    assert captured["body"]["item_count"] == 1
    assert captured["body"]["schema"] == msi.MATERIALIZED_SCHEMA


# ===========================================================================
# kill_switch.py
# ===========================================================================

# ---------------------------------------------------------------------------
# caps are imported, never restated
# ---------------------------------------------------------------------------


def test_caps_are_imported_from_the_preflight_not_restated():
    assert ks.CAP_GPU_HOURS == gsp.CAP_GPU_HOURS
    assert ks.CAP_USD == gsp.CAP_USD
    assert ks.CAP_SECONDS == gsp.CAP_GPU_HOURS * 3600.0


def test_outcome_vocabulary_is_exactly_these_three():
    assert set(ks.OUTCOMES) == {"CONTINUE", "STOP", "STOP_CANNOT_TELL"}


# ---------------------------------------------------------------------------
# continue only when comfortably under both thresholds
# ---------------------------------------------------------------------------


def test_continue_when_well_under_both_caps():
    usage = ks.Usage(elapsed_seconds=10.0, cost_usd=1.0)
    result = ks.evaluate(usage)
    assert result["outcome"] == ks.CONTINUE
    assert result["triggers"]["elapsed_seconds_over_threshold"] is False
    assert result["triggers"]["cost_over_threshold"] is False


# ---------------------------------------------------------------------------
# two independent triggers -- either alone is sufficient
# ---------------------------------------------------------------------------


def test_time_trigger_fires_alone_even_when_cost_is_zero():
    usage = ks.Usage(elapsed_seconds=ks.CAP_SECONDS, cost_usd=0.0)
    result = ks.evaluate(usage)
    assert result["outcome"] == ks.STOP
    assert result["triggers"]["elapsed_seconds_over_threshold"] is True
    assert result["triggers"]["cost_over_threshold"] is False


def test_cost_trigger_fires_alone_even_when_time_is_zero():
    usage = ks.Usage(elapsed_seconds=0.0, cost_usd=ks.CAP_USD)
    result = ks.evaluate(usage)
    assert result["outcome"] == ks.STOP
    assert result["triggers"]["cost_over_threshold"] is True
    assert result["triggers"]["elapsed_seconds_over_threshold"] is False


def test_both_triggers_can_fire_together():
    usage = ks.Usage(elapsed_seconds=ks.CAP_SECONDS, cost_usd=ks.CAP_USD)
    result = ks.evaluate(usage)
    assert result["outcome"] == ks.STOP
    assert result["triggers"]["elapsed_seconds_over_threshold"] is True
    assert result["triggers"]["cost_over_threshold"] is True


# ---------------------------------------------------------------------------
# fires before the cap, by a declared margin -- not at it, not after it
# ---------------------------------------------------------------------------


def test_time_trigger_fires_strictly_before_the_hard_cap():
    just_under_the_actual_cap = ks.CAP_SECONDS * 0.97  # inside the 5% margin band
    usage = ks.Usage(elapsed_seconds=just_under_the_actual_cap, cost_usd=0.0)
    result = ks.evaluate(usage)
    assert result["outcome"] == ks.STOP, "must fire before the hard cap, inside the margin band"


def test_cost_trigger_fires_strictly_before_the_hard_cap():
    just_under_the_actual_cap = ks.CAP_USD * 0.97
    usage = ks.Usage(elapsed_seconds=0.0, cost_usd=just_under_the_actual_cap)
    result = ks.evaluate(usage)
    assert result["outcome"] == ks.STOP


def test_comfortably_under_the_margin_band_still_continues():
    usage = ks.Usage(elapsed_seconds=ks.CAP_SECONDS * 0.5, cost_usd=ks.CAP_USD * 0.5)
    result = ks.evaluate(usage)
    assert result["outcome"] == ks.CONTINUE


def test_margin_is_declared_and_produces_a_lower_threshold_than_the_cap():
    result = ks.evaluate(ks.Usage(elapsed_seconds=0.0, cost_usd=0.0))
    assert result["thresholds"]["time_seconds"] < result["caps"]["cap_seconds"]
    assert result["thresholds"]["cost_usd"] < result["caps"]["cap_usd"]
    assert ks.TIME_MARGIN_FRACTION > 0
    assert ks.COST_MARGIN_FRACTION > 0


# ---------------------------------------------------------------------------
# fires on unknown -- the single most important property here
# ---------------------------------------------------------------------------


def test_missing_elapsed_seconds_stops_cannot_tell_even_though_cost_is_fine():
    usage = ks.Usage(elapsed_seconds=None, cost_usd=0.0)
    result = ks.evaluate(usage)
    assert result["outcome"] == ks.STOP_CANNOT_TELL
    assert result["triggers"]["elapsed_seconds_unknown"] is True


def test_missing_cost_stops_cannot_tell_even_though_time_is_fine():
    usage = ks.Usage(elapsed_seconds=0.0, cost_usd=None)
    result = ks.evaluate(usage)
    assert result["outcome"] == ks.STOP_CANNOT_TELL
    assert result["triggers"]["cost_unknown"] is True


def test_not_retrieved_marker_stops_cannot_tell():
    usage = ks.Usage(elapsed_seconds=ks.NOT_RETRIEVED, cost_usd=ks.NOT_RETRIEVED)
    result = ks.evaluate(usage)
    assert result["outcome"] == ks.STOP_CANNOT_TELL
    assert result["triggers"]["elapsed_seconds_unknown"] is True
    assert result["triggers"]["cost_unknown"] is True


def test_not_retrieved_marker_matches_runpod_provisioners():
    import runpod_provisioner as rp

    assert ks.NOT_RETRIEVED == rp.NOT_RETRIEVED


def test_non_numeric_garbage_value_stops_cannot_tell_not_continue():
    usage = ks.Usage(elapsed_seconds={"unexpected": "shape"}, cost_usd=0.0)
    result = ks.evaluate(usage)
    assert result["outcome"] == ks.STOP_CANNOT_TELL


def test_boolean_is_not_accepted_as_a_numeric_usage_value():
    # bool is an int subclass in Python; must not silently pass as a number
    usage = ks.Usage(elapsed_seconds=True, cost_usd=0.0)
    result = ks.evaluate(usage)
    assert result["outcome"] == ks.STOP_CANNOT_TELL


def test_unknown_outranks_a_would_be_stop_trigger_in_the_reported_outcome():
    # even though cost alone would already justify STOP, an unknown time
    # value must produce STOP_CANNOT_TELL, not STOP -- the two are not
    # interchangeable in what they tell a reader about what is known.
    usage = ks.Usage(elapsed_seconds=None, cost_usd=ks.CAP_USD)
    result = ks.evaluate(usage)
    assert result["outcome"] == ks.STOP_CANNOT_TELL


def test_evaluate_never_reports_a_fourth_more_reassuring_outcome():
    for usage in (
        ks.Usage(elapsed_seconds=0.0, cost_usd=0.0),
        ks.Usage(elapsed_seconds=ks.CAP_SECONDS, cost_usd=ks.CAP_USD),
        ks.Usage(elapsed_seconds=None, cost_usd=None),
    ):
        assert ks.evaluate(usage)["outcome"] in ks.OUTCOMES


# ---------------------------------------------------------------------------
# idempotent firing
# ---------------------------------------------------------------------------


def test_kill_switch_fires_on_stop_at_most_once_across_repeated_checks():
    calls: list[dict[str, Any]] = []
    switch = ks.KillSwitch(on_stop=lambda result: calls.append(result))

    switch.check(ks.Usage(elapsed_seconds=0.0, cost_usd=0.0))
    assert calls == []
    assert switch.fired is False

    stop_usage = ks.Usage(elapsed_seconds=ks.CAP_SECONDS, cost_usd=0.0)
    switch.check(stop_usage)
    assert len(calls) == 1
    assert switch.fired is True

    # firing again must not call on_stop a second time, and must not raise
    switch.check(stop_usage)
    switch.check(stop_usage)
    assert len(calls) == 1
    assert switch.fire_count == 3


def test_kill_switch_idempotent_across_unknown_then_stop():
    calls: list[dict[str, Any]] = []
    switch = ks.KillSwitch(on_stop=lambda result: calls.append(result))

    switch.check(ks.Usage(elapsed_seconds=None, cost_usd=0.0))
    assert len(calls) == 1
    assert calls[0]["outcome"] == ks.STOP_CANNOT_TELL

    switch.check(ks.Usage(elapsed_seconds=ks.CAP_SECONDS, cost_usd=0.0))
    # already fired once on the unknown reading; a later, different-shaped
    # stop condition still does not call on_stop again
    assert len(calls) == 1
    assert switch.fire_count == 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_main_exits_nonzero_on_stop(capsys):
    exit_code = ks.main(["--elapsed-seconds", str(ks.CAP_SECONDS), "--cost-usd", "0"])
    assert exit_code == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["outcome"] == ks.STOP


def test_cli_main_exits_nonzero_when_usage_is_omitted_entirely(capsys):
    exit_code = ks.main([])
    assert exit_code == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["outcome"] == ks.STOP_CANNOT_TELL


def test_cli_main_exits_zero_on_continue(capsys):
    exit_code = ks.main(["--elapsed-seconds", "0", "--cost-usd", "0"])
    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["outcome"] == ks.CONTINUE


def test_cli_parses_not_retrieved_marker():
    exit_code = ks.main(["--elapsed-seconds", "NOT_RETRIEVED", "--cost-usd", "0"])
    assert exit_code == 1
