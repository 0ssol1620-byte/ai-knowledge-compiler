"""The pre-holdout gate must close, and must close for the right reason.

Opening the v8 holdout is irreversible: a title read once is development data
forever. So the gate defaults to refusal, and what needs testing is not that it
can say yes --- it is that each condition can independently say no.

The gate ships its own break-controls, which are asserted here rather than
re-implemented. What this file adds is the failure path for the control itself,
and the specific defect this programme already shipped once: a guard that read a
key the seal does not have, found nothing, and therefore passed everything.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "research/experiments/H1-W6-SAME-INTELLIGENCE-01"


def load(relative: str, name: str) -> Any:
    path = ROOT / relative
    if not path.exists():
        pytest.skip(f"{relative} is not present")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> Any:
    return load(
        "research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/preflight_holdout_v8.py",
        "t_preflight_v8")


@pytest.fixture(scope="module")
def controls(gate) -> dict[str, Any]:
    return gate.preflight_controls()


def test_the_shipped_break_controls_separate(controls):
    assert controls["separates"], controls["synthetic_baseline_failed_conditions"]


def test_every_condition_has_at_least_one_break_that_refuses(controls):
    """A condition no break can trip is a condition that never fires."""
    assert controls["every_break_refused"]
    assert all(b["refused"] for b in controls["breaks"].values())


@pytest.mark.parametrize("break_name", sorted([
    "empty_seal_titles", "missing_seal", "missing_config_freeze", "missing_arm_source",
    "source_drift", "stub_model", "undecided_raw_budget_policy",
    "undecided_separability_disposition", "repository_red", "controls_did_not_separate",
    "fairness_violated", "taint_gate_not_live", "residual_control_did_not_separate",
    "holdout_already_opened", "statistics_config_absent", "unattested_model_runtime",
    "model_name_substituted", "unknown_model_context_window",
    "raw_budget_policy_reverted_to_shared",
    "separability_cited_as_difficulty_evidence", "identity_chain_mismatch",
    "identity_chain_not_ready", "identity_registry_ambiguous",
    "identity_controls_inert"]))
def test_each_named_break_is_refused(controls, break_name):
    assert controls["breaks"][break_name]["refused"]


def test_an_empty_seal_title_list_refuses_rather_than_passing_silently(gate, controls):
    """The defect this programme actually shipped.

    The generator's overlap guard read `development_titles`; the seal stores the
    list under `development_titles_excluded_from_v8.titles`. The lookup returned
    empty, so the overlap set was empty, so the guard passed everything. An empty
    list must now be a refusal, never a vacuous pass.
    """
    failed = controls["breaks"]["empty_seal_titles"]["failed_conditions"]
    assert "v7_titles_present_in_seal" in failed


def test_an_unattested_runtime_is_refused(controls):
    """MODEL_RUNTIME_NOT_READY: a name pins nothing, and there is no fallback."""
    assert "model_runtime_attested" in controls["breaks"][
        "unattested_model_runtime"]["failed_conditions"]


def test_a_substituted_model_is_refused(controls):
    assert "model_runtime_attested" in controls["breaks"][
        "model_name_substituted"]["failed_conditions"]


def test_reverting_to_the_shared_raw_budget_is_refused(controls):
    """Option B was decided on measured evidence; reverting reintroduces the defect."""
    assert "raw_context_budget_policy_decided" in controls["breaks"][
        "raw_budget_policy_reverted_to_shared"]["failed_conditions"]


def test_replacing_the_separability_metric_is_refused(controls):
    """Option A: a replacement chosen after seeing results ends the confirmatory claim."""
    assert "separability_metric_disposition_decided" in controls["breaks"][
        "separability_cited_as_difficulty_evidence"]["failed_conditions"]


def test_a_stub_model_cannot_open_the_holdout(controls):
    """The development model performs no inference; the holdout is not spent on it."""
    assert "model_is_pinned_and_real" in controls["breaks"]["stub_model"]["failed_conditions"]


def test_source_drift_refuses_even_when_everything_else_is_ready(controls):
    failed = controls["breaks"]["source_drift"]["failed_conditions"]
    assert failed == ["no_source_drift"]


def test_a_red_repository_refuses(controls):
    assert "full_repository_green" in controls["breaks"]["repository_red"]["failed_conditions"]


def test_an_already_opened_holdout_can_never_be_reopened(controls):
    failed = controls["breaks"]["holdout_already_opened"]["failed_conditions"]
    assert "holdout_status_unopened" in failed


def test_the_gate_reads_no_holdout_path(gate):
    """The gate inspects development state only; reading a holdout title here
    would itself be the act it exists to prevent."""
    source = (EXP / "scripts/preflight_holdout_v8.py").read_text(encoding="utf-8")
    assert "holdout" in source.lower()
    for forbidden in ("corpus-v8", "holdout_corpus", "acquisition-v8"):
        assert forbidden not in source


def test_every_condition_states_why_it_exists(gate):
    result = gate.evaluate(gate.gather_state())
    for name, condition in result["conditions"].items():
        assert condition["why"].strip(), f"{name} has no rationale"


def test_the_live_gate_currently_refuses_and_names_its_reasons(gate):
    """Not an aspiration: right now the freeze is absent and decisions are open.

    If this ever starts passing without those being resolved, the gate has been
    weakened rather than satisfied.
    """
    result = gate.evaluate(gate.gather_state())
    path = EXP / "receipts/v8-config-freeze.json"
    if path.exists():
        pytest.skip("a config freeze exists; this test covers the pre-freeze state")
    assert not result["passes"]
    assert "config_freeze_exists" in result["failed"]
    assert "model_is_pinned_and_real" in result["failed"]


def test_the_preflight_receipt_declares_it_opened_nothing():
    path = EXP / "receipts/v8-holdout-preflight-2026-08-19.json"
    if not path.exists():
        pytest.skip("the preflight has not been run")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["run_class"] == "DEVELOPMENT_ONLY"
    assert receipt["holdout_status"] == "UNOPENED"
    assert receipt["controls_separate"]
    # The gate's *verdict* is allowed to become True --- that is what satisfying
    # every condition means. What may never drift is that running the gate opens
    # nothing itself, and that the verdict agrees with the conditions rather than
    # being asserted independently of them. This line previously hard-coded
    # `is False`, which was the state on 2026-08-19 and stopped being true on
    # 2026-08-20 when the runtime was attested and the freeze written; a
    # hard-coded snapshot of a legitimate transition is a stale expectation, not a
    # guard, and it would have to be deleted rather than satisfied.
    assert receipt["holdout_may_be_opened"] == (not receipt["failed_conditions"])
