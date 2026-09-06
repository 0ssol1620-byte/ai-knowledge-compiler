"""FOUR_LINK_ACCEPTANCE_V1 — a green receipt is not authorization for a cohort.

The four-link gate has a green receipt over 20,018 eligible records and the
independent validator re-derived every one of their four link digests. That is
good evidence and it stays. It is not permission to spend GPU time, because it
answers a question about *a* manifest, and the question that decides a launch is
whether that manifest is the one about to run.

`test_a_green_receipt_over_a_different_manifest_is_refused` is the point of this
file. Everything else guards the ways that answer could be faked: a receipt whose
own manifest digest disagrees, a floor taken from the artifact being gated rather
than from the GPU study's declaration, a classification that covers fewer
candidates than the manifest holds, or a validator result recorded beside the
gate instead of re-run against it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "source_fact_ir")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import four_link_acceptance as fla  # noqa: E402
import four_link_gate as gate  # noqa: E402
import ir  # noqa: E402


def _witness(**overrides: Any) -> dict[str, Any]:
    witness = {
        "construct": "md-inline-link",
        "byte_start": 100,
        "byte_end": 140,
        "excerpt": "[load rule](../operations/rule-configuration.md#load-rules)",
        "unit_path": ["git:fixture/repo:doc.md", "Section"],
    }
    witness.update(overrides)
    return witness


def _candidate(index: int, **overrides: Any) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "fact_id": f"fact-{index}",
        "kind": ir.REFERENCE_TARGET,
        "state": ir.REPRESENTED,
        "witness": _witness(),
        "representation": {"normalized": "../operations/rule-configuration.md#load-rules"},
        "policy_ref": None,
        "reason": None,
        "extra": {},
    }
    candidate.update(overrides)
    return candidate


@pytest.fixture
def cohort(tmp_path, monkeypatch):
    """A manifest, its gate receipt and a verified acceptance, under a fake ROOT."""
    monkeypatch.setattr(fla, "ROOT", tmp_path)
    monkeypatch.setattr(fla, "ACCEPTED_FLOOR", 5)

    def build(count: int = 8, *, facts_key: str = "facts", floor: int | None = None):
        candidates = [_candidate(index) for index in range(count)]
        manifest = tmp_path / "successor_manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema": "tavonel.v2.successor_cohort_manifest.v1",
                    facts_key: candidates,
                    "source_sfi3_acceptance": {
                        "protocol_id": "SOURCE_FACT_IR_HELDOUT_V3",
                        "verdict": "PASS",
                    },
                    "provenance": {
                        "receipt_stem": "successor-candidate-universe",
                        "run_id": "SFI3_SUCCESSOR_UNIVERSE_V1",
                        "immutable": True,
                    },
                }
            ),
            encoding="utf-8",
        )
        receipt = gate.gate(candidates, floor=floor if floor is not None else 5)
        receipt["manifest"] = str(manifest)
        receipt["manifest_sha256"] = fla._sha_file(manifest)
        receipt_path = tmp_path / "four-link-gate.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        acceptance = {
            "schema": fla.SCHEMA,
            "manifest": str(manifest),
            "manifest_sha256": fla._sha_file(manifest),
            "gate_receipt": str(receipt_path),
            "gate_receipt_sha256": fla._sha_file(receipt_path),
            "facts_key": facts_key,
            "eligible_count": receipt["by_state"][gate.STATE_ELIGIBLE],
            "floor": receipt["floor"],
            "provenance": {
                "receipt_stem": fla.STEM,
                "run_id": fla.AUTHORITY_RUN_ID,
                "immutable": True,
            },
        }
        return manifest, receipt_path, acceptance

    return build


# ---------------------------------------------------------------------------
# the green direction


def test_a_matching_cohort_is_accepted(cohort):
    _manifest, _receipt, acceptance = cohort()
    held = fla.verify(acceptance, launch_manifest_sha256=acceptance["manifest_sha256"])
    assert held["held"] is True
    assert held["verdict"] == "READY"
    assert held["eligible_count"] == 8
    assert held["by_state"][gate.STATE_ELIGIBLE] == 8
    assert held["validator"]["agrees_with_classifier"] is True
    assert held["validator"]["eligible_records_evidence_rederived"] == 8


def test_every_candidate_lands_in_exactly_one_of_the_six_states(cohort):
    _manifest, _receipt, acceptance = cohort()
    held = fla.verify(acceptance)
    assert set(held["by_state"]) == set(gate.ELIGIBILITY_STATES)
    assert sum(held["by_state"].values()) == held["candidates_considered"]


def test_build_drafts_and_verifies_in_one_step(cohort):
    manifest, receipt, _acceptance = cohort()
    draft = fla.build(manifest, receipt)
    assert fla.verify(draft, require_authority=False)["held"] is True


# ---------------------------------------------------------------------------
# the cohort identity question -- paragraph 8


def test_a_green_receipt_over_a_different_manifest_is_refused(cohort):
    """The whole point. Green says nothing about which cohort it was green over."""
    _manifest, _receipt, acceptance = cohort()
    with pytest.raises(fla.AcceptanceRefused, match="not the cohort about to run"):
        fla.verify(acceptance, launch_manifest_sha256="sha256:" + "0" * 64)


def test_a_changed_manifest_is_refused(cohort):
    manifest, _receipt, acceptance = cohort()
    body = json.loads(manifest.read_text(encoding="utf-8"))
    body["facts"].append(_candidate(999))
    manifest.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(fla.AcceptanceRefused, match="has changed since it was accepted"):
        fla.verify(acceptance)


def test_a_gate_receipt_produced_over_another_manifest_is_refused(cohort, tmp_path):
    """Both files intact, both digests honest, and they are about different things."""
    _manifest, receipt_path, acceptance = cohort()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["manifest_sha256"] = "sha256:" + "9" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    acceptance["gate_receipt_sha256"] = fla._sha_file(receipt_path)
    with pytest.raises(
        fla.AcceptanceRefused,
        match="not a successor candidate universe|produced over a different manifest",
    ):
        fla.verify(acceptance)


def test_a_changed_gate_receipt_is_refused(cohort, tmp_path):
    _manifest, receipt_path, acceptance = cohort()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["verdict"] = "READY"
    receipt["note"] = "edited"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(fla.AcceptanceRefused, match="has changed since it was accepted"):
        fla.verify(acceptance)


# ---------------------------------------------------------------------------
# the floor


def test_a_stop_verdict_is_refused(cohort):
    _manifest, _receipt, acceptance = cohort(count=3)
    with pytest.raises(fla.AcceptanceRefused, match="not READY"):
        fla.verify(acceptance)


def test_one_below_the_floor_is_refused(cohort, monkeypatch):
    monkeypatch.setattr(fla, "ACCEPTED_FLOOR", 9)
    _manifest, _receipt, acceptance = cohort(count=8, floor=9)
    with pytest.raises(fla.AcceptanceRefused, match="not READY"):
        fla.verify(acceptance)


def test_the_floor_is_taken_from_the_gpu_declaration_not_the_receipt(cohort):
    """A receipt carrying its own lower floor cannot lower the bar it is judged by."""
    _manifest, receipt_path, acceptance = cohort(count=8, floor=1)
    acceptance["floor"] = 1
    acceptance["gate_receipt_sha256"] = fla._sha_file(receipt_path)
    with pytest.raises(fla.AcceptanceRefused, match="never taken from the artifact"):
        fla.verify(acceptance)


def test_the_declared_floor_is_the_gpu_successor_floor():
    """Not a copy. A second constant here would be a second floor."""
    import four_link_acceptance as fresh
    import gpu_successor_preflight as gsp

    assert fresh.ACCEPTED_FLOOR == gsp.COHORT_FLOOR == 120


# ---------------------------------------------------------------------------
# classifier / validator agreement, and total classification


def test_a_flipped_state_is_refused_by_the_validator(cohort, tmp_path):
    _manifest, receipt_path, acceptance = cohort()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["records"][0]["eligibility_state"] = gate.STATE_UNRESOLVED_CHAIN
    receipt["by_state"][gate.STATE_ELIGIBLE] -= 1
    receipt["by_state"][gate.STATE_UNRESOLVED_CHAIN] += 1
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    acceptance["gate_receipt_sha256"] = fla._sha_file(receipt_path)
    acceptance["eligible_count"] -= 1
    with pytest.raises(fla.AcceptanceRefused, match="validator does not confirm"):
        fla.verify(acceptance)


def test_a_dropped_candidate_is_refused(cohort, tmp_path):
    """What result-based filtering looks like from outside: a shorter record list."""
    _manifest, receipt_path, acceptance = cohort()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["records"] = receipt["records"][:-1]
    receipt["by_state"][gate.STATE_ELIGIBLE] -= 1
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    acceptance["gate_receipt_sha256"] = fla._sha_file(receipt_path)
    acceptance["eligible_count"] -= 1
    with pytest.raises(fla.AcceptanceRefused, match=r"does not confirm|silently widened"):
        fla.verify(acceptance)


def test_an_invented_eligibility_state_is_refused(cohort, tmp_path, monkeypatch):
    _manifest, receipt_path, acceptance = cohort()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["records"][0]["eligibility_state"] = "PROBABLY_FINE"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    acceptance["gate_receipt_sha256"] = fla._sha_file(receipt_path)
    monkeypatch.setattr(
        fla.validator, "validate", lambda receipt, facts_key="facts": {
            "schema": "x", "eligible_count": acceptance["eligible_count"],
            "eligible_records_evidence_rederived": 0, "required_evidence": [],
        }
    )
    with pytest.raises(fla.AcceptanceRefused, match="not one of the six"):
        fla.verify(acceptance)


def test_a_count_the_acceptance_disagrees_with_is_refused(cohort):
    _manifest, _receipt, acceptance = cohort()
    acceptance["eligible_count"] = 7
    with pytest.raises(fla.AcceptanceRefused, match="acceptance records 7 eligible"):
        fla.verify(acceptance)


def test_the_validator_is_rerun_not_read_from_a_stored_result(cohort, monkeypatch):
    """A recorded validator output is a claim about a check; running it is the check."""
    calls: list[str] = []
    real = fla.validator.validate

    def spy(receipt, facts_key="facts"):
        calls.append(facts_key)
        return real(receipt, facts_key=facts_key)

    monkeypatch.setattr(fla.validator, "validate", spy)
    _manifest, _receipt, acceptance = cohort()
    fla.verify(acceptance)
    assert calls == ["facts"]


# ---------------------------------------------------------------------------
# bindings and shapes


@pytest.mark.parametrize("field", fla.REQUIRED_BINDINGS)
def test_an_acceptance_missing_any_binding_is_refused(cohort, field):
    _manifest, _receipt, acceptance = cohort()
    acceptance.pop(field)
    with pytest.raises(fla.AcceptanceRefused, match="carries no"):
        fla.verify(acceptance)


def test_a_foreign_gate_schema_is_refused(cohort, tmp_path):
    _manifest, receipt_path, acceptance = cohort()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["schema"] = "tavonel.v2.something_else.v1"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    acceptance["gate_receipt_sha256"] = fla._sha_file(receipt_path)
    with pytest.raises(fla.AcceptanceRefused, match="not a four-link gate result"):
        fla.verify(acceptance)


def test_a_foreign_acceptance_schema_is_refused():
    with pytest.raises(fla.AcceptanceRefused, match="not a four-link acceptance"):
        fla.verify({"schema": "something.else.v1"})


def test_an_unsealed_acceptance_draft_is_not_authority(cohort):
    _manifest, _receipt, acceptance = cohort()
    acceptance.pop("provenance")
    with pytest.raises(fla.AcceptanceRefused, match="single immutable"):
        fla.verify(acceptance)


def test_an_absent_manifest_is_refused(cohort):
    _manifest, _receipt, acceptance = cohort()
    acceptance["manifest"] = "never-written.json"
    with pytest.raises(fla.AcceptanceRefused, match="not on disk"):
        fla.verify(acceptance)


def test_an_empty_manifest_is_refused(cohort, tmp_path):
    """A classification over zero candidates agrees with anything."""
    _manifest, _receipt, acceptance = cohort()
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"facts": []}), encoding="utf-8")
    acceptance["manifest"] = str(empty)
    acceptance["manifest_sha256"] = fla._sha_file(empty)
    with pytest.raises(
        fla.AcceptanceRefused,
        match="not a successor candidate universe|produced over a different manifest",
    ):
        fla.verify(acceptance)


def test_the_module_offers_no_search():
    """One authority, one immutable path, one digest."""
    assert not hasattr(fla, "latest_acceptance")


# ---------------------------------------------------------------------------
# the existing 20,018 receipt is preserved, and not promoted by assumption


def test_the_real_development_cohort_is_not_successor_authority():
    """The historical pre-SFI3 cohort stays evidence, never GPU authority."""
    manifest = NS / "artifacts" / "development" / "typed_fact_cohort.json"
    receipts = sorted((NS / "receipts").glob("four-link-gate--*.json"))
    if not manifest.is_file() or not receipts:
        pytest.skip("the development four-link cohort is not present")
    with pytest.raises(
        fla.AcceptanceRefused,
        match="successor candidate universe|successor-universe authority",
    ):
        fla.build(manifest, receipts[-1])


def test_seal_uses_one_fixed_authority_and_no_pointer(cohort, monkeypatch):
    manifest, receipt, _acceptance = cohort()
    captured = {}

    def fake_write(stem, body, **kwargs):
        captured.update({"stem": stem, "body": body, **kwargs})
        return {"receipt": "sealed.json", "run_id": kwargs["run_id"]}

    monkeypatch.setattr(fla, "write_immutable", fake_write)
    written = fla.seal(manifest, receipt)
    assert written["run_id"] == fla.AUTHORITY_RUN_ID
    assert captured["pointer"] is False
    assert captured["stem"] == fla.STEM


def test_a_second_four_link_authority_is_refused(cohort, monkeypatch):
    manifest, receipt, _acceptance = cohort()

    def duplicate(*args, **kwargs):
        raise fla.ReceiptExists("held")

    monkeypatch.setattr(fla, "write_immutable", duplicate)
    with pytest.raises(fla.AcceptanceRefused, match="second is forbidden"):
        fla.seal(manifest, receipt)
