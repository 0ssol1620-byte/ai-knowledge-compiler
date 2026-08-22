from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from benchmark.v6.contracts import ContractError
from benchmark.v6.evidence import build_evidence_payload, sign_evidence, verify_signed_evidence
from benchmark.v6.promotion import (
    REQUIRED_GATES,
    GateStatus,
    PromotionDecision,
    build_champion_matrix,
    evaluate_promotion,
)
from benchmark.v6.registry import CandidateSpec

_INCUMBENT_ID = "incumbent-stable"
_RELEASE_COMMIT = "b" * 40
_SOURCE_TREE_SHA256 = "sha256:" + "c" * 64
_CANDIDATE_REGISTRY_SHA256 = "sha256:" + "6" * 64
_PUBLIC_CORE_REGISTRY_SHA256 = "sha256:" + "7" * 64
_CHAMPION_MATRIX_SHA256 = "sha256:" + "d" * 64
_PUBLIC_CORE = ("olmocr-bench", "omnidocbench", "parsebench")


def _run_records(
    *,
    candidate_id: str = "candidate-ready",
    incumbent_candidate_id: str = _INCUMBENT_ID,
    benchmarks: tuple[str, ...] = _PUBLIC_CORE,
) -> list[dict[str, object]]:
    return [
        {
            "run_id": f"run-{benchmark_id}-{model_id}-{index}",
            "cohort_id": f"cohort-{benchmark_id}-actual-001",
            "candidate_id": model_id,
            "benchmark_id": benchmark_id,
            "repeat_index": index,
            "status": "passed",
            "production_actual": True,
            "critical_failure_count": 0,
            "gt_leakage_count": 0,
            "actual_cost_usd": 1.25,
            "environment_sha256": "sha256:" + str(benchmark_number) * 64,
            "prediction_root": f"{benchmark_id}/{model_id}/run-{index}/predictions",
            "log_root": f"{benchmark_id}/{model_id}/run-{index}/logs",
            "prediction_archive_sha256": "sha256:" + "b" * 64,
            "official_output_sha256": "sha256:" + "c" * 64,
            "critical_output_sha256": "sha256:" + "d" * 64,
            "failure_bundle_sha256": "sha256:" + "e" * 64,
            "started_at": f"2026-08-01T00:0{index}:00Z",
            "finished_at": f"2026-08-01T00:1{index}:00Z",
            "gpu_seconds": 60.0,
        }
        for benchmark_number, benchmark_id in enumerate(benchmarks, start=1)
        for model_id in (candidate_id, incumbent_candidate_id)
        for index in (1, 2, 3)
    ]


def _signed_external_evidence(
    private_key: Ed25519PrivateKey,
    *,
    candidate_id: str = "candidate-ready",
    incumbent_candidate_id: str = _INCUMBENT_ID,
    release_commit: str = _RELEASE_COMMIT,
    gate_results: dict[str, str] | None = None,
    run_records: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    records = (
        run_records
        if run_records is not None
        else _run_records(
            candidate_id=candidate_id,
            incumbent_candidate_id=incumbent_candidate_id,
        )
    )
    payload = build_evidence_payload(
        candidate_id=candidate_id,
        incumbent_candidate_id=incumbent_candidate_id,
        requested_target="production",
        release_commit=release_commit,
        source_tree_sha256=_SOURCE_TREE_SHA256,
        candidate_registry_sha256=_CANDIDATE_REGISTRY_SHA256,
        public_core_registry_sha256=_PUBLIC_CORE_REGISTRY_SHA256,
        gate_results=(
            gate_results
            if gate_results is not None
            else {gate: "pass" for gate in REQUIRED_GATES}
        ),
        critical_failure_count=0,
        run_records=records,
        failure_bundles=[],
        endpoint_cleanup=[{"endpoint_id": "ep-1", "state": "deleted"}],
        actual_cost_report={"provider_cost_usd": "3.75", "actual": True},
        champion_matrix_sha256=_CHAMPION_MATRIX_SHA256,
        mandatory_test_omissions=[],
        production_evidence=True,
    )
    return sign_evidence(
        payload,
        private_key=private_key,
        key_id="release-key-2026-08",
        signed_at="2026-08-01T12:00:00Z",
    )


def _promotion_binding() -> dict[str, str]:
    return {
        "incumbent_candidate_id": _INCUMBENT_ID,
        "release_commit": _RELEASE_COMMIT,
        "source_tree_sha256": _SOURCE_TREE_SHA256,
        "candidate_registry_sha256": _CANDIDATE_REGISTRY_SHA256,
        "public_core_registry_sha256": _PUBLIC_CORE_REGISTRY_SHA256,
        "champion_matrix_sha256": _CHAMPION_MATRIX_SHA256,
    }


def _evaluate(
    candidate: CandidateSpec,
    *,
    envelope: dict[str, object] | None,
    public_key: Ed25519PublicKey | None,
    receipts: list[dict[str, object]] | None = None,
    gates: dict[str, GateStatus] | None = None,
    release_commit: str = _RELEASE_COMMIT,
) -> PromotionDecision:
    return evaluate_promotion(
        candidate=candidate,
        incumbent_candidate_id=_INCUMBENT_ID,
        requested_target="production",
        release_commit=release_commit,
        source_tree_sha256=_SOURCE_TREE_SHA256,
        candidate_registry_sha256=_CANDIDATE_REGISTRY_SHA256,
        public_core_registry_sha256=_PUBLIC_CORE_REGISTRY_SHA256,
        champion_matrix_sha256=_CHAMPION_MATRIX_SHA256,
        gates=gates if gates is not None else {gate: GateStatus.PASS for gate in REQUIRED_GATES},
        repeat_receipts=receipts if receipts is not None else _run_records(),
        signed_evidence=envelope,
        evidence_public_key=public_key,
        critical_failure_count=0,
        skipped_mandatory_tests=[],
    )


def test_ed25519_evidence_detects_any_payload_tampering() -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope = _signed_external_evidence(private_key)
    public_key = private_key.public_key()

    assert verify_signed_evidence(envelope, public_key=public_key)["production_evidence"] is True
    tampered = copy.deepcopy(envelope)
    tampered["payload"]["actual_cost_report"]["provider_cost_usd"] = "0.01"  # type: ignore[index]
    with pytest.raises(ContractError, match="digest mismatch"):
        verify_signed_evidence(tampered, public_key=public_key)


def test_production_promotion_requires_all_gates_three_repeats_and_signed_actual_evidence(
    eligible_candidate: CandidateSpec,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope = _signed_external_evidence(private_key)
    decision = evaluate_promotion(
        candidate=eligible_candidate,
        **_promotion_binding(),
        requested_target="production",
        gates={gate: GateStatus.PASS for gate in REQUIRED_GATES},
        repeat_receipts=_run_records(),
        signed_evidence=envelope,
        evidence_public_key=private_key.public_key(),
        critical_failure_count=0,
        skipped_mandatory_tests=[],
    )

    assert decision.decision == "production"
    assert decision.gate_g9 is GateStatus.PASS
    assert decision.blockers == ()


def test_signed_evidence_cannot_be_replayed_across_candidate_release_gate_or_receipt(
    eligible_candidate: CandidateSpec,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    valid = _signed_external_evidence(private_key)

    other_candidate = _signed_external_evidence(
        private_key,
        candidate_id="candidate-other",
        run_records=_run_records(candidate_id="candidate-other"),
    )
    cross_candidate = _evaluate(
        eligible_candidate,
        envelope=other_candidate,
        public_key=public_key,
    )
    assert cross_candidate.decision == "reject"
    assert "SIGNED_EVIDENCE_SCOPE_MISMATCH" in cross_candidate.blockers

    cross_release = _evaluate(
        eligible_candidate,
        envelope=valid,
        public_key=public_key,
        release_commit="e" * 40,
    )
    assert cross_release.decision == "reject"

    gate_payload = copy.deepcopy(valid["payload"])
    gate_payload["gate_results"]["G3"] = "fail"  # type: ignore[index]
    signed_gate_failure = sign_evidence(
        gate_payload,  # type: ignore[arg-type]
        private_key=private_key,
        key_id="release-key-2026-08",
        signed_at="2026-08-01T12:01:00Z",
    )
    cross_gate = _evaluate(
        eligible_candidate,
        envelope=signed_gate_failure,
        public_key=public_key,
    )
    assert cross_gate.decision == "reject"

    changed_receipts = copy.deepcopy(_run_records())
    changed_receipts[0]["actual_cost_usd"] = 999.0
    cross_receipt = _evaluate(
        eligible_candidate,
        envelope=valid,
        public_key=public_key,
        receipts=changed_receipts,
    )
    assert cross_receipt.decision == "reject"


@pytest.mark.parametrize(
    "case",
    ["missing_all", "single_suite", "missing_incumbent", "extra_repeat", "replayed_run"],
)
def test_public_core_promotion_requires_exact_three_candidate_and_incumbent_runs(
    eligible_candidate: CandidateSpec,
    case: str,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    records = _run_records()
    envelope = _signed_external_evidence(private_key)
    if case == "missing_all":
        records = []
    elif case == "single_suite":
        records = [record for record in records if record["benchmark_id"] == "parsebench"]
    elif case == "missing_incumbent":
        records = [record for record in records if record["candidate_id"] != _INCUMBENT_ID]
    elif case == "extra_repeat":
        extra = copy.deepcopy(records[0])
        extra["run_id"] = "run-extra-fourth-repeat"
        extra["repeat_index"] = 4
        records.append(extra)
    else:
        records[1]["run_id"] = records[0]["run_id"]

    decision = _evaluate(
        eligible_candidate,
        envelope=envelope,
        public_key=private_key.public_key(),
        receipts=records,
    )
    assert decision.decision == "reject"
    expected = (
        "REPEAT_RUN_IDENTITIES_NOT_UNIQUE"
        if case == "replayed_run"
        else "EXACT_PUBLIC_CORE_REPEATS_NOT_PROVEN"
    )
    assert expected in decision.blockers


def test_missing_external_evidence_stays_shadow_and_hard_gate_failure_rejects(
    eligible_candidate: CandidateSpec,
) -> None:
    pending = evaluate_promotion(
        candidate=eligible_candidate,
        **_promotion_binding(),
        requested_target="production",
        gates={gate: GateStatus.PASS for gate in REQUIRED_GATES},
        repeat_receipts=_run_records(),
        signed_evidence=None,
        evidence_public_key=None,
        critical_failure_count=0,
        skipped_mandatory_tests=[],
    )
    assert pending.decision == "shadow"
    assert "SIGNED_EXTERNAL_EVIDENCE_MISSING" in pending.blockers

    failed_gates = {gate: GateStatus.PASS for gate in REQUIRED_GATES}
    failed_gates["G3"] = GateStatus.FAIL
    rejected = evaluate_promotion(
        candidate=eligible_candidate,
        **_promotion_binding(),
        requested_target="production",
        gates=failed_gates,
        repeat_receipts=_run_records(),
        signed_evidence=None,
        evidence_public_key=None,
        critical_failure_count=1,
        skipped_mandatory_tests=[],
    )
    assert rejected.decision == "reject"
    assert rejected.gate_g9 is GateStatus.FAIL

    robustness_failure = {gate: GateStatus.PASS for gate in REQUIRED_GATES}
    robustness_failure["G4"] = GateStatus.FAIL
    rejected_robustness = evaluate_promotion(
        candidate=eligible_candidate,
        **_promotion_binding(),
        requested_target="production",
        gates=robustness_failure,
        repeat_receipts=_run_records(),
        signed_evidence=None,
        evidence_public_key=None,
        critical_failure_count=0,
        skipped_mandatory_tests=[],
    )
    assert rejected_robustness.decision == "reject"


def test_champion_matrix_rejects_majority_vote_and_nonproduction_candidate(
    eligible_candidate: CandidateSpec,
) -> None:
    shadow = evaluate_promotion(
        candidate=eligible_candidate,
        **_promotion_binding(),
        requested_target="production",
        gates={},
        repeat_receipts=[],
        signed_evidence=None,
        evidence_public_key=None,
        critical_failure_count=0,
        skipped_mandatory_tests=[],
    )
    with pytest.raises(ContractError, match="non-production"):
        build_champion_matrix(
            {
                "native_pdf": {
                    "primary": eligible_candidate.candidate_id,
                    "selection_basis": "measured_benchmark",
                }
            },
            {eligible_candidate.candidate_id: shadow},
        )
    with pytest.raises(ContractError, match="majority"):
        build_champion_matrix(
            {"native_pdf": {"primary": None, "selection_basis": "majority_vote"}},
            {},
        )


def test_v6_json_schemas_are_valid(repo_root: Path) -> None:
    schema_root = repo_root / "benchmark/v6/schemas"
    for path in sorted(schema_root.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)

    private_key = Ed25519PrivateKey.generate()
    envelope = _signed_external_evidence(private_key)
    schema = json.loads((schema_root / "signed-evidence.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(envelope, schema)
    run_schema = json.loads((schema_root / "run-record.schema.json").read_text(encoding="utf-8"))
    for record in _run_records():
        jsonschema.validate(record, run_schema)
