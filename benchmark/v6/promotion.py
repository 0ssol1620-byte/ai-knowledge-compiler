"""Champion matrix and fail-closed autonomous promotion arbitration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .contracts import ContractError, canonical_sha256, require_commit, require_sha256
from .evidence import PUBLIC_CORE_BENCHMARK_IDS, verify_signed_evidence
from .registry import CandidateSpec


class GateStatus(StrEnum):
    # This is a gate state, not a credential.
    PASS = "pass"  # noqa: S105  # nosec B105
    FAIL = "fail"
    BLOCKED = "blocked"
    NOT_RUN = "not_run"


REQUIRED_GATES = tuple([f"G{index}" for index in range(9)] + [f"MP{index}" for index in range(7)])
_PAGE_CLASSES = (
    "native_pdf",
    "normal_scan",
    "korean_financial_table",
    "english_filing",
    "photographed_document",
    "formula_heavy",
    "cross_page_table",
    "handwriting_form",
)


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    candidate_id: str
    requested_target: str
    decision: str
    gate_g9: GateStatus
    blockers: tuple[str, ...]
    failed_gates: tuple[str, ...]
    pending_gates: tuple[str, ...]
    evidence_sha256: str | None
    decision_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "requested_target": self.requested_target,
            "decision": self.decision,
            "gate_g9": self.gate_g9.value,
            "blockers": list(self.blockers),
            "failed_gates": list(self.failed_gates),
            "pending_gates": list(self.pending_gates),
            "evidence_sha256": self.evidence_sha256,
            "decision_sha256": self.decision_sha256,
        }


def evaluate_promotion(
    *,
    candidate: CandidateSpec,
    incumbent_candidate_id: str,
    requested_target: str,
    release_commit: str,
    source_tree_sha256: str,
    candidate_registry_sha256: str,
    public_core_registry_sha256: str,
    champion_matrix_sha256: str,
    gates: Mapping[str, GateStatus | str],
    repeat_receipts: Sequence[Mapping[str, object]],
    signed_evidence: Mapping[str, Any] | None,
    evidence_public_key: Ed25519PublicKey | None,
    critical_failure_count: int,
    skipped_mandatory_tests: Sequence[str],
) -> PromotionDecision:
    """Return production/canary only when every independent proof is present."""

    if requested_target not in {"shadow", "canary", "production"}:
        raise ContractError("requested_target must be shadow, canary, or production")
    if not incumbent_candidate_id.strip() or incumbent_candidate_id == candidate.candidate_id:
        raise ContractError("a distinct incumbent_candidate_id is required")
    require_commit(release_commit, "release_commit")
    require_sha256(source_tree_sha256, "source_tree_sha256")
    require_sha256(candidate_registry_sha256, "candidate_registry_sha256")
    require_sha256(public_core_registry_sha256, "public_core_registry_sha256")
    require_sha256(champion_matrix_sha256, "champion_matrix_sha256")
    normalized: dict[str, GateStatus] = {}
    unexpected = sorted(set(gates) - set(REQUIRED_GATES))
    if unexpected:
        raise ContractError(f"unknown gate ids: {unexpected}")
    for gate_id in REQUIRED_GATES:
        raw = gates.get(gate_id, GateStatus.NOT_RUN)
        try:
            normalized[gate_id] = raw if isinstance(raw, GateStatus) else GateStatus(str(raw))
        except ValueError as exc:
            raise ContractError(f"invalid status for {gate_id}: {raw!r}") from exc

    failed = tuple(gate for gate, status in normalized.items() if status is GateStatus.FAIL)
    pending = tuple(
        gate
        for gate, status in normalized.items()
        if status in {GateStatus.BLOCKED, GateStatus.NOT_RUN}
    )
    blockers: list[str] = []
    if not candidate.promotion_eligible:
        blockers.append("CANDIDATE_REGISTRY_NOT_PROMOTION_ELIGIBLE")
    if candidate.license_status not in {"approved", "approved_with_conditions"}:
        blockers.append("LICENSE_NOT_APPROVED")
    if candidate.commercial_use not in {"allowed", "conditional"}:
        blockers.append("COMMERCIAL_USE_NOT_APPROVED")
    if critical_failure_count != 0:
        blockers.append("CRITICAL_FAILURES_PRESENT")
    if skipped_mandatory_tests:
        blockers.append("MANDATORY_TESTS_SKIPPED")

    repeat_blocker = _validate_repeat_receipts(
        repeat_receipts,
        candidate_id=candidate.candidate_id,
        incumbent_candidate_id=incumbent_candidate_id,
    )
    if repeat_blocker is not None:
        blockers.append(repeat_blocker)

    evidence_sha256: str | None = None
    if signed_evidence is None or evidence_public_key is None:
        blockers.append("SIGNED_EXTERNAL_EVIDENCE_MISSING")
    else:
        try:
            verified = verify_signed_evidence(signed_evidence, public_key=evidence_public_key)
            evidence_sha256 = str(verified["payload_sha256"])
            if not verified["production_evidence"]:
                blockers.append("EVIDENCE_IS_LOCAL_CONTRACT_ONLY")
            payload = verified.get("payload")
            if not isinstance(payload, Mapping) or not _signed_scope_matches(
                payload,
                candidate_id=candidate.candidate_id,
                incumbent_candidate_id=incumbent_candidate_id,
                requested_target=requested_target,
                release_commit=release_commit,
                source_tree_sha256=source_tree_sha256,
                candidate_registry_sha256=candidate_registry_sha256,
                public_core_registry_sha256=public_core_registry_sha256,
                champion_matrix_sha256=champion_matrix_sha256,
                normalized_gates=normalized,
                repeat_receipts=repeat_receipts,
                critical_failure_count=critical_failure_count,
                skipped_mandatory_tests=skipped_mandatory_tests,
            ):
                blockers.append("SIGNED_EVIDENCE_SCOPE_MISMATCH")
        except ContractError:
            blockers.append("SIGNED_EXTERNAL_EVIDENCE_INVALID")

    hard_failure = bool(failed) or any(
        blocker
        in {
            "LICENSE_NOT_APPROVED",
            "COMMERCIAL_USE_NOT_APPROVED",
            "CRITICAL_FAILURES_PRESENT",
            "SIGNED_EXTERNAL_EVIDENCE_INVALID",
            "SIGNED_EVIDENCE_SCOPE_MISMATCH",
        }
        for blocker in blockers
    )
    all_pass = not failed and not pending and not blockers
    if all_pass:
        decision = requested_target
        gate_g9 = GateStatus.PASS
    elif hard_failure:
        decision = "reject"
        gate_g9 = GateStatus.FAIL
    else:
        decision = "shadow"
        gate_g9 = GateStatus.BLOCKED

    decision_material = {
        "candidate_id": candidate.candidate_id,
        "requested_target": requested_target,
        "decision": decision,
        "gate_g9": gate_g9.value,
        "blockers": sorted(set(blockers)),
        "failed_gates": list(failed),
        "pending_gates": list(pending),
        "evidence_sha256": evidence_sha256,
    }
    return PromotionDecision(
        candidate_id=candidate.candidate_id,
        requested_target=requested_target,
        decision=decision,
        gate_g9=gate_g9,
        blockers=tuple(sorted(set(blockers))),
        failed_gates=failed,
        pending_gates=pending,
        evidence_sha256=evidence_sha256,
        decision_sha256=canonical_sha256(decision_material),
    )


def build_champion_matrix(
    selections: Mapping[str, Mapping[str, object]],
    decisions: Mapping[str, PromotionDecision],
) -> dict[str, object]:
    unexpected = sorted(set(selections) - set(_PAGE_CLASSES))
    if unexpected:
        raise ContractError(f"unknown page classes: {unexpected}")
    champions: dict[str, object] = {}
    for page_class in _PAGE_CLASSES:
        selection = dict(selections.get(page_class, {}))
        primary = selection.get("primary")
        basis = selection.get("selection_basis")
        if basis == "majority_vote":
            raise ContractError("model majority may not be used as authority")
        if primary is not None:
            if not isinstance(primary, str) or primary not in decisions:
                raise ContractError(f"{page_class}: primary lacks a promotion decision")
            if decisions[primary].decision != "production":
                raise ContractError(f"{page_class}: non-production candidate cannot be champion")
            if basis not in {
                "authoritative_source",
                "deterministic_validation",
                "measured_benchmark",
            }:
                raise ContractError(f"{page_class}: an admissible selection_basis is required")
        champions[page_class] = {
            "primary": primary,
            "fallback": selection.get("fallback"),
            "recovery": selection.get("recovery"),
            "authority": selection.get("authority"),
            "selection_basis": basis,
            "evidence_sha256": decisions[primary].evidence_sha256
            if isinstance(primary, str)
            else None,
            "status": "production" if primary is not None else "unresolved",
        }
    matrix: dict[str, object] = {"schema_version": "6.0.0", "champions": champions}
    matrix["matrix_sha256"] = canonical_sha256(matrix)
    return matrix


def _validate_repeat_receipts(
    receipts: Sequence[Mapping[str, object]],
    *,
    candidate_id: str,
    incumbent_candidate_id: str,
) -> str | None:
    identities = (candidate_id, incumbent_candidate_id)
    expected = {
        (benchmark_id, model_id, repeat_index)
        for benchmark_id in PUBLIC_CORE_BENCHMARK_IDS
        for model_id in identities
        for repeat_index in (1, 2, 3)
    }
    observed = [
        (receipt.get("benchmark_id"), receipt.get("candidate_id"), receipt.get("repeat_index"))
        for receipt in receipts
    ]
    if len(receipts) != len(expected) or set(observed) != expected:
        return "EXACT_PUBLIC_CORE_REPEATS_NOT_PROVEN"
    if len({receipt.get("run_id") for receipt in receipts}) != len(receipts):
        return "REPEAT_RUN_IDENTITIES_NOT_UNIQUE"
    for benchmark_id in PUBLIC_CORE_BENCHMARK_IDS:
        cohort = [receipt for receipt in receipts if receipt.get("benchmark_id") == benchmark_id]
        cohort_ids = {receipt.get("cohort_id") for receipt in cohort}
        if len(cohort_ids) != 1 or not next(iter(cohort_ids), None):
            return "REPEAT_COHORT_IDENTITY_MISMATCH"
        environments = {receipt.get("environment_sha256") for receipt in cohort}
        if len(environments) != 1:
            return "REPEAT_ENVIRONMENT_IDENTITY_MISMATCH"
        environment = next(iter(environments))
        if not isinstance(environment, str):
            return "REPEAT_ENVIRONMENT_IDENTITY_MISSING"
        try:
            require_sha256(environment, "repeat.environment_sha256")
        except ContractError:
            return "REPEAT_ENVIRONMENT_IDENTITY_INVALID"
    if any(receipt.get("status") != "passed" for receipt in receipts):
        return "REPEAT_NOT_PASSED"
    if any(receipt.get("production_actual") is not True for receipt in receipts):
        return "REPEAT_IS_NOT_ACTUAL_EXTERNAL_EVIDENCE"
    if len({receipt.get("prediction_root") for receipt in receipts}) != len(receipts):
        return "REPEAT_PREDICTION_ISOLATION_NOT_PROVEN"
    if len({receipt.get("log_root") for receipt in receipts}) != len(receipts):
        return "REPEAT_LOG_ISOLATION_NOT_PROVEN"
    return None


def _signed_scope_matches(
    payload: Mapping[str, object],
    *,
    candidate_id: str,
    incumbent_candidate_id: str,
    requested_target: str,
    release_commit: str,
    source_tree_sha256: str,
    candidate_registry_sha256: str,
    public_core_registry_sha256: str,
    champion_matrix_sha256: str,
    normalized_gates: Mapping[str, GateStatus],
    repeat_receipts: Sequence[Mapping[str, object]],
    critical_failure_count: int,
    skipped_mandatory_tests: Sequence[str],
) -> bool:
    expected_scalars: Mapping[str, object] = {
        "candidate_id": candidate_id,
        "incumbent_candidate_id": incumbent_candidate_id,
        "requested_target": requested_target,
        "release_commit": release_commit,
        "source_tree_sha256": source_tree_sha256,
        "candidate_registry_sha256": candidate_registry_sha256,
        "public_core_registry_sha256": public_core_registry_sha256,
        "champion_matrix_sha256": champion_matrix_sha256,
        "critical_failure_count": critical_failure_count,
    }
    if any(payload.get(key) != value for key, value in expected_scalars.items()):
        return False
    if payload.get("required_benchmark_ids") != list(PUBLIC_CORE_BENCHMARK_IDS):
        return False
    expected_gates = {gate_id: status.value for gate_id, status in normalized_gates.items()}
    if payload.get("gate_results") != expected_gates:
        return False
    if payload.get("mandatory_test_omissions") != sorted(set(skipped_mandatory_tests)):
        return False
    signed_records = payload.get("run_records")
    if not isinstance(signed_records, list) or any(
        not isinstance(record, Mapping) for record in signed_records
    ):
        return False
    identities = {candidate_id, incumbent_candidate_id}
    signed_public_core = [
        record
        for record in signed_records
        if record.get("candidate_id") in identities
        and record.get("benchmark_id") in PUBLIC_CORE_BENCHMARK_IDS
    ]
    expected_hashes = sorted(canonical_sha256(dict(receipt)) for receipt in repeat_receipts)
    signed_hashes = sorted(canonical_sha256(dict(receipt)) for receipt in signed_public_core)
    return signed_hashes == expected_hashes
