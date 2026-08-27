"""The SFI3 freeze gate must be able to come back red, and also green.

INC-V2-036 was a guard placed where its failure was structurally impossible. A
freeze gate that could never refuse would be the same defect at the worst possible
place, since the thing on the other side of it is irreversible: after the freeze
the first fresh lineage may be read, and a corpus once looked at is spent.

So both directions are asserted here. A gate that always refuses is no more useful
than one that always permits — it would simply be routed around.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "compiler"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import freeze_sfi3_protocol as gate  # noqa: E402


@pytest.fixture
def under_ns(tmp_path_factory):
    """A scratch directory INSIDE the repository tree.

    pytest's `tmp_path` lives on C: while this repository is on D:, and
    `common.rel()` computes a repo-relative path — it raises ValueError across
    drives. Patching `rel` away in tests would make them pass while deleting the
    exact path handling every real run depends on, so the fixture moves instead.
    """
    root = pathlib.Path(NS) / "artifacts" / "development" / "_scratch_freeze_gate"
    root.mkdir(parents=True, exist_ok=True)
    scratch = pathlib.Path(tempfile.mkdtemp(dir=root))
    yield scratch
    shutil.rmtree(scratch, ignore_errors=True)


@pytest.fixture(autouse=True)
def _never_run_the_real_suite(monkeypatch):
    """No test here may invoke the real suite runner.

    The gate runs the whole suite; the suite contains this file. A test that called
    the real `_suite_is_green` would spawn a suite that spawns a suite, and the
    first symptom was this file hanging rather than failing. The tool now refuses
    nested invocations on its own (see REENTRY_FLAG), and this fixture makes the
    tests independent of that guard rather than reliant on it.
    """
    real = gate._suite_is_green

    def stub() -> dict:
        return {"verdict": gate.CONDITION_FAILED, "detail": "stubbed in tests"}

    monkeypatch.setattr(gate, "_suite_is_green", stub)
    #: Matched by the BOUND FUNCTION, not by key. `CHECKS` is built at import time
    #: from the protocol's condition strings, so several checks carry the real
    #: runner under names like "suite stable" and "Windows stale-lock resolved".
    #: An earlier version matched `c.key == "suite_is_green"`, a key that stopped
    #: existing when the checklist began deriving from the protocol — so nothing
    #: was stubbed, the real runner fired, and this file hung instead of failing.
    monkeypatch.setattr(
        gate,
        "CHECKS",
        tuple(
            gate.Check(c.key, c.describe, stub) if c.run is real else c
            for c in gate.CHECKS
        ),
    )


def _all_met(monkeypatch) -> None:
    """Every condition met, so the gate's green path is reachable."""
    monkeypatch.setattr(
        gate,
        "CHECKS",
        tuple(
            gate.Check(check.key, check.describe, lambda: {"verdict": gate.CONDITION_MET})
            for check in gate.CHECKS
        ),
    )


# --------------------------------------------------------------------------
# the gate refuses


def test_the_gate_refuses_while_any_condition_is_unmet():
    """Run against the real repository, which is not ready to freeze."""
    report = gate.evaluate_all()
    assert report["may_freeze"] is False
    assert report["blocking"]


def test_refusing_returns_a_nonzero_exit_code(capsys):
    code = gate.main(["--dry-run"])
    assert code == 4
    assert "REFUSING TO FREEZE" in capsys.readouterr().err


def test_a_check_that_raises_blocks_rather_than_passing():
    """An exception is not a licence.

    A gate that treated a broken check as a satisfied one would be easiest to pass
    when it was most broken.
    """

    def explode() -> dict:
        raise RuntimeError("the check itself is broken")

    row = gate.Check("boom", "a check that raises", explode).evaluate()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "the check itself raised" in row["detail"]


def test_unverifiable_blocks_exactly_as_a_failure_does():
    """UNVERIFIABLE is not a third, softer outcome.

    The correct response to a condition nothing can check is to build the check,
    never to let the freeze proceed on the grounds that no one could tell.
    """
    checks = (gate.Check("unknown", "cannot be checked", lambda: {"verdict": gate.UNVERIFIABLE}),)
    rows = [check.evaluate() for check in checks]
    blocking = [row for row in rows if row["verdict"] != gate.CONDITION_MET]
    assert blocking


def test_an_existing_freeze_receipt_blocks_a_second_freeze(monkeypatch, under_ns):
    """Two freeze receipts would make it ambiguous which rules were in force."""
    receipts = under_ns / "receipts"
    receipts.mkdir()
    (receipts / f"{gate.STEM}--20260823T000000Z-abc.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gate, "NS", under_ns)
    assert gate._no_prior_freeze()["verdict"] == gate.CONDITION_FAILED


def test_an_existing_fresh_corpus_artifact_blocks_the_freeze(monkeypatch, under_ns):
    """Freezing after the corpus was opened would be theatre."""
    lineages = under_ns / "artifacts" / "development"
    lineages.mkdir(parents=True)
    (lineages / "sfi3_lineages.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gate, "NS", under_ns)
    row = gate._no_fresh_lineage_was_opened()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "already present" in row["detail"]


def test_a_missing_root_preflight_receipt_blocks_the_freeze(monkeypatch, under_ns):
    (under_ns / "receipts").mkdir()
    monkeypatch.setattr(gate, "NS", under_ns)
    assert gate._root_availability_preflight()["verdict"] == gate.CONDITION_FAILED


def test_a_structurally_impossible_floor_blocks_the_freeze(monkeypatch, under_ns):
    """A family that failed wholesale cannot be discovered after the freeze."""
    receipts = under_ns / "receipts"
    receipts.mkdir()
    (receipts / "sfi3-root-availability--20260823T000000Z-abc.json").write_text(
        json.dumps({"floor_structurally_impossible": True, "valid_by_family": {"git": 0}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "NS", under_ns)
    assert gate._root_availability_preflight()["verdict"] == gate.CONDITION_FAILED


# --------------------------------------------------------------------------
# the gate permits


def test_the_gate_can_go_green_when_every_condition_is_met(monkeypatch):
    """Without this, `test_the_gate_refuses...` would pass on an always-red gate."""
    _all_met(monkeypatch)
    report = gate.evaluate_all()
    assert report["may_freeze"] is True
    assert report["blocking"] == []


def test_a_dry_run_never_writes_a_receipt(monkeypatch, capsys):
    """Even fully green, `--dry-run` must not freeze anything."""
    _all_met(monkeypatch)
    written: list[object] = []
    monkeypatch.setattr(gate, "write_immutable", lambda *a, **k: written.append(a) or {})
    assert gate.main(["--dry-run"]) == 0
    assert written == []
    assert json.loads(capsys.readouterr().out)["may_freeze"] is True


# --------------------------------------------------------------------------
# the conditions themselves


def test_every_condition_has_a_distinct_key():
    keys = [check.key for check in gate.CHECKS]
    assert len(keys) == len(set(keys))


def test_no_check_in_the_live_checklist_still_holds_the_real_suite_runner():
    """After the fixture, nothing in CHECKS may still carry the real runner.

    This is the invariant whose violation hung this file. `CHECKS` is built at
    import time from the protocol's condition strings, and FIVE of them map to the
    same suite runner under names like "suite stable" and "Windows stale-lock
    resolved". The fixture originally matched `c.key == "suite_is_green"` — a key
    that stopped existing when the checklist began deriving from the protocol — so
    nothing was stubbed, the real runner spawned a suite that spawned a suite, and
    the symptom was a hang rather than a failure.

    Matching by name rather than by identity is deliberate here: the fixture
    already substituted the module attribute, so identity against it proves
    nothing, whereas the real runner's `__name__` survives into any check that
    still holds it.
    """
    still_real = [c.key for c in gate.CHECKS if c.run.__name__ == "_suite_is_green"]
    assert not still_real, still_real


def test_more_than_one_condition_maps_to_the_suite_runner():
    """The premise of the test above, asserted so it cannot quietly become vacuous.

    If only one condition ever used the runner, matching by a single key would
    have been adequate and the test above would prove nothing.
    """
    mapped = [
        condition
        for condition, run in gate.CONDITION_CHECKS.items()
        if run.__name__ == "_suite_is_green"
    ]
    assert len(mapped) > 1, mapped


def test_the_suite_check_uses_the_project_interpreter_not_whichever_python_is_on_path():
    """INC-V2-039. A freeze satisfied from the wrong environment repeats it."""
    assert gate.VENV_PYTHON.name == "python.exe"
    assert ".venv" in str(gate.VENV_PYTHON)
    assert "sys.executable" not in gate._suite_is_green.__code__.co_names


def test_a_nested_invocation_refuses_instead_of_recursing(monkeypatch):
    """The gate runs the suite, and the suite contains this file.

    Without the guard the first symptom is a hang, which is the worst failure mode
    for a gate: it neither permits nor refuses, and a hanging gate invites being
    routed around.
    """
    monkeypatch.undo()
    monkeypatch.setenv(gate.REENTRY_FLAG, "1")
    row = gate._suite_is_green()
    assert row["verdict"] == gate.UNVERIFIABLE
    assert "nested" in row["detail"]


def test_the_suite_command_is_recorded_so_a_reader_can_rerun_it():
    """A green result reported without its scope is not a result.

    Asserted against the declared command rather than by running it.
    """
    assert "pytest" in " ".join(gate.SUITE_COMMAND)
    assert "no:cacheprovider" in gate.SUITE_COMMAND

# --------------------------------------------------------------------------
# the two conditions that used to be fixed FAIL strings
#
# `_identity_change_separation_complete` and `_five_channel_contract_complete`
# each returned a hardcoded CONDITION_FAILED describing the state of the tree
# when they were written. Both statements became false without the checks
# noticing, which is the same defect as a guard placed where failure is
# impossible -- only pointed the other way. They now measure. These tests exist
# because replacing "always FAIL" with "always PASS" would be no better, and
# would be much harder to notice.


_GOOD_BENCHMARK = {
    "overall": {
        "pairs_resolved": 538,
        "pairs_unresolved": 0,
        "matched_pairs_total": 2536,
        "under_fire_rate_over_matched_pairs": 0.0,
        "pairs_with_any_under_fire": 0,
        "identity_records_disagree_pairs": 0,
        "over_fire_rate_over_matched_pairs": 0.011041,
        "over_fires_on_confirmed_defect_lineages": 14,
    }
}
_GOOD_CANARY = {
    "verdict": "PASS",
    "non_tautological_checks_passed": 5,
    "non_tautological_checks_total": 5,
}
_CLEAN_PROBE = {
    "identity_folds_equal": True,
    "stale_artifacts": [],
    "carried_forward_count": 3,
}


def _closure_body(*, overall="PASS", verdicts=None, pairs=240):
    """A V2R4-shaped measurement, complete enough for the acceptance to read.

    The invariant ids come from `invariant_domain.CANONICAL_INVARIANTS` rather
    than being spelled `INVARIANT_1`..`INVARIANT_8` here. The earlier fixture
    used the short ordinals, which no scorer or protocol has ever emitted -- so
    it tested a receipt shape that could not occur, and the acceptance's set
    equality would have refused it for the wrong reason.
    """
    import invariant_domain as dom

    return {
        "schema": "tavonel.v2.identity_change_migration_closure.v2r4_result.v1",
        "protocol_id": "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4",
        "protocol_sha256": "sha256:" + "a" * 64,
        "universe_sha256": "sha256:" + "b" * 64,
        "provenance": {"run_id": "20260901T000000Z-fixture00000"},
        "pairs_resolved": pairs,
        "by_family": {"git_docs": 90, "regulation_ecfr": 80, "sec_edgar": 70},
        "overall": overall,
        "invariants": {
            name: {"verdict": (verdicts or {}).get(name, "MET")}
            for name in dom.CANONICAL_INVARIANTS
        },
    }


#: A prospective closure that closes. No real one exists yet -- V2R4 has not been
#: measured -- so the green direction has to be supplied here or the red tests
#: below would all pass vacuously.
_GOOD_CLOSURE = _closure_body()


def _with_ladder(
    monkeypatch, under_ns, benchmark, canary, probe=None, closure=None, accepted=True
):
    """Point the identity check at fixture receipts and a fixture probe.

    The closure is no longer resolved by a stem glob. It arrives through an
    explicit MIGRATION_CLOSURE_ACCEPTANCE_V1 receipt naming its protocol id, run
    id and digests -- see INC-V2-069, where a glob on
    `identity-change-migration-closure--*.json` was found to match only V1 and
    to have been invisible to four successors in a row.

    `accepted=False` stands for "no acceptance receipt exists at all", which is
    a different state from "an acceptance exists and does not hold".
    """
    import migration_closure_acceptance as mca

    paths = {}
    for name, body in (("benchmark", benchmark), ("canary", canary)):
        path = under_ns / f"{name}.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        paths[name] = path

    monkeypatch.setattr(
        gate,
        "_latest_receipt",
        lambda stem: paths["benchmark"] if "benchmark" in stem else paths["canary"],
    )
    monkeypatch.setattr(gate, "_case_only_probe", lambda: dict(probe or _CLEAN_PROBE))

    if not accepted:
        monkeypatch.setattr(mca, "latest_acceptance", lambda receipts=None: None)
        return

    body = closure if closure is not None else _GOOD_CLOSURE
    measurement = under_ns / "closure.json"
    measurement.write_text(json.dumps(body), encoding="utf-8")
    acceptance_path = under_ns / "acceptance.json"
    acceptance_path.write_text(
        json.dumps(
            {
                "schema": mca.SCHEMA,
                "protocol_id": body.get("protocol_id"),
                "measurement_receipt": "closure.json",
                "measurement_run_id": (body.get("provenance") or {}).get("run_id"),
                "measurement_sha256": mca._sha_file(measurement),
                "protocol_sha256": body.get("protocol_sha256"),
                "universe_sha256": body.get("universe_sha256"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mca, "ROOT", under_ns)
    monkeypatch.setattr(mca, "latest_acceptance", lambda receipts=None: acceptance_path)


def test_identity_separation_passes_on_a_clean_ladder(monkeypatch, under_ns):
    """The green direction, so the red ones below are not vacuously satisfied."""
    _with_ladder(monkeypatch, under_ns, _GOOD_BENCHMARK, _GOOD_CANARY)
    assert gate._identity_change_separation_complete()["verdict"] == gate.CONDITION_MET


def test_identity_separation_blocks_when_the_ladder_has_no_benchmark(monkeypatch, under_ns):
    """The Protected Core rule: the legacy path stays authoritative until a
    benchmark says the new one is not worse. A switch with no benchmark receipt
    has skipped a rung, however well it behaves today."""
    monkeypatch.setattr(gate, "_latest_receipt", lambda stem: None)
    row = gate._identity_change_separation_complete()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "benchmark" in row["detail"]


def test_identity_separation_blocks_on_a_single_under_fire(monkeypatch, under_ns):
    """Under-fire is the regression this migration exists to prevent: something
    the old predicate caught and the new one misses."""
    benchmark = {"overall": dict(_GOOD_BENCHMARK["overall"])}
    benchmark["overall"]["pairs_with_any_under_fire"] = 1
    benchmark["overall"]["under_fire_rate_over_matched_pairs"] = 0.0004
    _with_ladder(monkeypatch, under_ns, benchmark, _GOOD_CANARY)
    assert gate._identity_change_separation_complete()["verdict"] == gate.CONDITION_FAILED


def test_identity_separation_blocks_when_identity_records_disagree(monkeypatch, under_ns):
    """Which units MATCH must be untouched. A non-zero count here is the
    signature of the fold having been made content-sensitive -- the one repair
    the founder ruled out, and the one that would otherwise look like success."""
    benchmark = {"overall": dict(_GOOD_BENCHMARK["overall"])}
    benchmark["overall"]["identity_records_disagree_pairs"] = 2
    _with_ladder(monkeypatch, under_ns, benchmark, _GOOD_CANARY)
    assert gate._identity_change_separation_complete()["verdict"] == gate.CONDITION_FAILED


def test_identity_separation_blocks_when_the_benchmark_resolved_nothing(monkeypatch, under_ns):
    """A benchmark over zero pairs reports 0 under-fire truthfully and proves
    nothing; every rate it carries has an empty denominator."""
    benchmark = {"overall": dict(_GOOD_BENCHMARK["overall"])}
    benchmark["overall"]["pairs_resolved"] = 0
    _with_ladder(monkeypatch, under_ns, benchmark, _GOOD_CANARY)
    assert gate._identity_change_separation_complete()["verdict"] == gate.CONDITION_FAILED


def test_identity_separation_blocks_when_the_canary_failed(monkeypatch, under_ns):
    _with_ladder(
        monkeypatch, under_ns, _GOOD_BENCHMARK, {**_GOOD_CANARY, "verdict": "FAIL"}
    )
    assert gate._identity_change_separation_complete()["verdict"] == gate.CONDITION_FAILED


def test_identity_separation_blocks_when_the_fold_stopped_folding(monkeypatch, under_ns):
    """Receipts alone cannot satisfy this condition.

    Every receipt is clean and only live production has regressed: the identity
    fold no longer folds a case-only pair equal. The check must still block, or
    it is reading history rather than the system it gates.
    """
    _with_ladder(
        monkeypatch,
        under_ns,
        _GOOD_BENCHMARK,
        _GOOD_CANARY,
        probe={**_CLEAN_PROBE, "identity_folds_equal": False},
    )
    row = gate._identity_change_separation_complete()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "identity continuity" in row["detail"]


def test_identity_separation_blocks_when_a_stale_artifact_returns(monkeypatch, under_ns):
    _with_ladder(
        monkeypatch,
        under_ns,
        _GOOD_BENCHMARK,
        _GOOD_CANARY,
        probe={**_CLEAN_PROBE, "stale_artifacts": ["section:u:whatever"]},
    )
    assert gate._identity_change_separation_complete()["verdict"] == gate.CONDITION_FAILED


def test_identity_separation_blocks_when_the_probe_carried_nothing(monkeypatch, under_ns):
    """An empty stale list is only evidence if something was carried to be
    stale. A probe that rebuilt everything would report clean while watching
    nothing."""
    _with_ladder(
        monkeypatch,
        under_ns,
        _GOOD_BENCHMARK,
        _GOOD_CANARY,
        probe={**_CLEAN_PROBE, "carried_forward_count": 0},
    )
    assert gate._identity_change_separation_complete()["verdict"] == gate.CONDITION_FAILED


def test_identity_separation_blocks_while_the_prospective_closure_fails(
    monkeypatch, under_ns
):
    """The condition this gate actually turns on.

    The benchmark and canary are RETROSPECTIVE: measured after the production
    switch shipped, by the agent that also wrote the check grading them
    (INC-V2-042). The founder reclassified them as a safety regression and
    required a prospectively frozen closure. So a clean retrospective pair must
    NOT be able to carry this condition on its own — otherwise the gate reports
    whichever of two measurements is more comfortable.
    """
    failing = _closure_body(
        overall="FAIL",
        verdicts={"INVARIANT_6_ambiguous_identity_stays_unresolved": "VIOLATED"},
    )
    _with_ladder(
        monkeypatch, under_ns, _GOOD_BENCHMARK, _GOOD_CANARY, closure=failing
    )
    row = gate._identity_change_separation_complete()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "not PASS" in row["detail"]


def test_identity_separation_blocks_on_a_closure_missing_seven_invariants(
    monkeypatch, under_ns
):
    """INC-V2-067's receipt shape, refused at the SFI3 gate.

    A closure reporting one invariant and an `overall` cannot satisfy a pass
    rule over eight, and the acceptance refuses it as a domain break rather than
    reading the one verdict it does carry.
    """
    partial = _closure_body()
    partial["invariants"] = {
        "INVARIANT_6_ambiguous_identity_stays_unresolved": {"verdict": "MET"}
    }
    _with_ladder(monkeypatch, under_ns, _GOOD_BENCHMARK, _GOOD_CANARY, closure=partial)
    row = gate._identity_change_separation_complete()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "declared invariant set" in row["detail"]


def test_identity_separation_blocks_when_there_is_no_prospective_closure_at_all(
    monkeypatch, under_ns
):
    """A retrospective regression with no prospective closure is the state
    INC-V2-042 records, not a state that satisfies it."""

    import migration_closure_acceptance as mca

    _with_ladder(
        monkeypatch, under_ns, _GOOD_BENCHMARK, _GOOD_CANARY, accepted=False
    )
    row = gate._identity_change_separation_complete()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert f"no {mca.STEM} receipt for {mca.ACCEPTED_PROTOCOL_ID}" in row["detail"]
    assert row["closure_acceptance_receipt"] is None


def test_the_retrospective_receipts_are_labelled_as_what_they_are(
    monkeypatch, under_ns
):
    """The classification travels with the reading, so a later reader cannot
    mistake a safety regression for ladder qualification."""
    _with_ladder(monkeypatch, under_ns, _GOOD_BENCHMARK, _GOOD_CANARY)
    row = gate._identity_change_separation_complete()
    assert "RETROSPECTIVE" in row["retrospective_receipts_classification"]
    assert "not sufficient" in row["retrospective_receipts_classification"]


# --- five-channel ---------------------------------------------------------


class _FakeDecision:
    def __init__(self, dependents):
        self.dependents = frozenset(dependents)
        self.verdict = type("V", (), {"value": "seed_set"})()


class _FakeResult:
    def __init__(self, name, verdict="PASS", silent=(), dependents=("section:u:1",)):
        self.channel_name = name
        self.verdict = verdict
        self.silent_disappearance = frozenset(silent)
        self.decision = _FakeDecision(dependents)


_FIVE = ("SEMANTIC", "STRUCTURAL", "LOCATOR", "TEMPORAL", "METADATA")


def _with_channels(monkeypatch, results):
    import sys

    sys.path.insert(0, str(NS / "compiler"))
    import e9_oracle

    monkeypatch.setattr(e9_oracle, "run_all", lambda: tuple(results))


def test_five_channel_passes_when_every_channel_resolves(monkeypatch):
    _with_channels(monkeypatch, [_FakeResult(name) for name in _FIVE])
    assert gate._five_channel_contract_complete()["verdict"] == gate.CONDITION_MET


def test_five_channel_blocks_on_a_single_silent_disappearance(monkeypatch):
    """The failure this endpoint is named for: a detected typed change that
    reaches no seed and is absorbed into 'no change reached it'."""
    results = [_FakeResult(name) for name in _FIVE]
    results[2] = _FakeResult("LOCATOR", verdict="FAIL", silent=("section:u:1",))
    _with_channels(monkeypatch, results)
    row = gate._five_channel_contract_complete()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "LOCATOR" in row["detail"]


def test_five_channel_blocks_when_fewer_than_five_channels_were_measured(monkeypatch):
    """Non-vacuity. Measuring two channels and reporting that all of them passed
    is the shape of a check that has quietly stopped watching."""
    _with_channels(monkeypatch, [_FakeResult(name) for name in _FIVE[:2]])
    row = gate._five_channel_contract_complete()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "measured 2" in row["detail"]


def test_five_channel_blocks_on_an_empty_seed_set(monkeypatch):
    """A channel that resolves to SEED_SET with no dependents has named nothing
    to rebuild, which is a silent disappearance wearing the right label."""
    results = [_FakeResult(name) for name in _FIVE]
    results[3] = _FakeResult("TEMPORAL", dependents=())
    _with_channels(monkeypatch, results)
    assert gate._five_channel_contract_complete()["verdict"] == gate.CONDITION_FAILED


# ---------------------------------------------------------------------------
# condition 21 -- the reverse half of the cross-study root reservation
#
# V2R4's INVARIANT_8 briefly required disjointness from every lineage id in
# SFI3's frozen acquisition, which cannot exist when V2R4 needs it: the order is
# V2R4 PASS -> SFI3 acquisition -> SFI3 PASS -> four-link -> GPU. The repair
# reserves SFI3's CONTAINERS in advance and has V2R4 choose outside them. This
# condition is the other direction -- a reservation binding only V2R4 would leave
# SFI3 free to draw from a container nobody told V2R4 to avoid.


def _pinned_handoff(under_ns, monkeypatch):
    """Install a protocol fixture that names one exact administrative handoff."""
    import v2r4_sfi3_reservation_handoff as handoff

    receipt = under_ns / "handoff.json"
    receipt.write_text(json.dumps({"fixture": True}), encoding="utf-8")
    protocol = under_ns / "protocol.yaml"
    relative = receipt.relative_to(gate.ROOT).as_posix()
    protocol.write_text(
        "predecessor_handoff:\n"
        f"  schema: {handoff.SCHEMA}\n"
        f"  receipt: {relative}\n"
        f"  sha256: {gate.sha_file(receipt)}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "PROTOCOL", protocol)
    monkeypatch.setattr(
        handoff,
        "verify",
        lambda body: {
            "held": True,
            "schema": handoff.SCHEMA,
            "handoff_id": handoff.SCHEMA,
            "declared_containers_sha256": "sha256:containers",
            "collision_count": 0,
        },
    )
    return receipt, protocol, handoff


def test_reservation_condition_consumes_the_exact_protocol_pinned_handoff(
    under_ns, monkeypatch
):
    receipt, _protocol, _handoff = _pinned_handoff(under_ns, monkeypatch)
    row = gate._sfi3_root_reservation_honoured()
    assert row["verdict"] == gate.CONDITION_MET
    assert row["handoff_receipt"] == receipt.relative_to(gate.ROOT).as_posix()
    assert row["collision_count"] == 0
    assert row["no_v2r4_outcome_was_read"] is True


def test_reservation_condition_fails_when_the_pinned_handoff_moves(under_ns, monkeypatch):
    receipt, _protocol, _handoff = _pinned_handoff(under_ns, monkeypatch)
    receipt.write_text(json.dumps({"fixture": "moved"}), encoding="utf-8")
    row = gate._sfi3_root_reservation_honoured()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "digest mismatch" in row["detail"]


def test_reservation_condition_fails_when_the_exact_handoff_is_absent(
    under_ns, monkeypatch
):
    receipt, _protocol, _handoff = _pinned_handoff(under_ns, monkeypatch)
    receipt.unlink()
    row = gate._sfi3_root_reservation_honoured()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "missing predecessor handoff" in row["detail"]


def test_reservation_condition_fails_on_wrong_handoff_schema(under_ns, monkeypatch):
    _receipt, protocol, _handoff = _pinned_handoff(under_ns, monkeypatch)
    protocol.write_text(protocol.read_text(encoding="utf-8").replace(
        "V2R4_SFI3_RESERVATION_HANDOFF_V1", "WRONG_SCHEMA"
    ), encoding="utf-8")
    assert gate._sfi3_root_reservation_honoured()["verdict"] == gate.CONDITION_FAILED


def test_reservation_condition_fails_on_traversal_instead_of_searching(
    under_ns, monkeypatch
):
    _receipt, protocol, _handoff = _pinned_handoff(under_ns, monkeypatch)
    lines = protocol.read_text(encoding="utf-8").splitlines()
    protocol.write_text(
        "\n".join("  receipt: ../outside.json" if "receipt:" in line else line for line in lines)
        + "\n",
        encoding="utf-8",
    )
    row = gate._sfi3_root_reservation_honoured()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "repository-relative" in row["detail"]


def test_reservation_condition_fails_when_the_handoff_verifier_refuses(
    under_ns, monkeypatch
):
    _receipt, _protocol, handoff = _pinned_handoff(under_ns, monkeypatch)

    def refuse(_body):
        raise handoff.HandoffRefused("collision")

    monkeypatch.setattr(handoff, "verify", refuse)
    row = gate._sfi3_root_reservation_honoured()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "collision" in row["detail"]


def test_the_protocol_declares_the_condition_the_gate_maps():
    """Declared == mapped. A condition nothing checks is attested, not verified."""
    declared = gate._protocol_conditions()
    condition = next(c for c in declared if "SFI3_ROOT_RESERVATION_V1" in c)
    assert gate.CONDITION_CHECKS.get(condition) is gate._sfi3_root_reservation_honoured
