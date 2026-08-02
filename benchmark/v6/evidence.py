"""Canonical Ed25519 evidence envelopes; unsigned evidence cannot promote."""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .contracts import (
    ContractError,
    canonical_json_bytes,
    canonical_sha256,
    require_commit,
    require_sha256,
)

_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_REQUIRED_PROMOTION_GATES = tuple(
    [f"G{index}" for index in range(9)] + [f"MP{index}" for index in range(7)]
)
_GATE_STATUSES = frozenset({"pass", "fail", "blocked", "not_run"})
PUBLIC_CORE_BENCHMARK_IDS = ("olmocr-bench", "omnidocbench", "parsebench")


def build_evidence_payload(
    *,
    candidate_id: str,
    incumbent_candidate_id: str,
    requested_target: str,
    release_commit: str,
    source_tree_sha256: str,
    candidate_registry_sha256: str,
    public_core_registry_sha256: str,
    gate_results: Mapping[str, object],
    critical_failure_count: int,
    run_records: Sequence[Mapping[str, object]],
    failure_bundles: Sequence[Mapping[str, object]],
    endpoint_cleanup: Sequence[Mapping[str, object]],
    actual_cost_report: Mapping[str, object],
    champion_matrix_sha256: str,
    mandatory_test_omissions: list[str],
    production_evidence: bool,
) -> dict[str, object]:
    require_commit(release_commit, "release_commit")
    require_sha256(source_tree_sha256, "source_tree_sha256")
    require_sha256(candidate_registry_sha256, "candidate_registry_sha256")
    require_sha256(public_core_registry_sha256, "public_core_registry_sha256")
    require_sha256(champion_matrix_sha256, "champion_matrix_sha256")
    if not candidate_id.strip() or not incumbent_candidate_id.strip():
        raise ContractError("candidate and incumbent identities are required")
    if candidate_id == incumbent_candidate_id:
        raise ContractError("candidate and incumbent identities must differ")
    if requested_target not in {"shadow", "canary", "production"}:
        raise ContractError("requested_target must be shadow, canary, or production")
    normalized_gates = _normalize_gate_results(gate_results)
    if (
        isinstance(critical_failure_count, bool)
        or not isinstance(critical_failure_count, int)
        or critical_failure_count < 0
    ):
        raise ContractError("critical_failure_count must be a non-negative integer")
    if not run_records:
        raise ContractError("signed evidence must include run records")
    if production_evidence and mandatory_test_omissions:
        raise ContractError("production evidence cannot omit mandatory tests")
    if production_evidence:
        _validate_external_run_records(run_records)
        _validate_public_core_coverage(
            run_records,
            candidate_id=candidate_id,
            incumbent_candidate_id=incumbent_candidate_id,
        )
        if any(status != "pass" for status in normalized_gates.values()):
            raise ContractError("production evidence requires every promotion gate to pass")
        if critical_failure_count != 0:
            raise ContractError("production evidence cannot contain critical failures")
        if not endpoint_cleanup:
            raise ContractError("production evidence requires endpoint cleanup receipts")
        if any(str(item.get("state")) != "deleted" for item in endpoint_cleanup):
            raise ContractError(
                "production evidence requires every temporary endpoint to be deleted"
            )
        if actual_cost_report.get("actual") is not True:
            raise ContractError("production evidence requires an actual cost report")
        if "provider_cost_usd" not in actual_cost_report:
            raise ContractError("production evidence requires provider_cost_usd")
    payload: dict[str, object] = {
        "schema_version": "6.0.0",
        "evidence_mode": "external_actual" if production_evidence else "local_contract_only",
        "production_evidence": production_evidence,
        "candidate_id": candidate_id,
        "incumbent_candidate_id": incumbent_candidate_id,
        "requested_target": requested_target,
        "release_commit": release_commit,
        "source_tree_sha256": source_tree_sha256,
        "candidate_registry_sha256": candidate_registry_sha256,
        "public_core_registry_sha256": public_core_registry_sha256,
        "required_benchmark_ids": list(PUBLIC_CORE_BENCHMARK_IDS),
        "gate_results": normalized_gates,
        "critical_failure_count": critical_failure_count,
        "run_records": sorted(
            (dict(item) for item in run_records), key=lambda item: str(item.get("run_id", ""))
        ),
        "failure_bundles": sorted(
            (dict(item) for item in failure_bundles), key=lambda item: str(item.get("run_id", ""))
        ),
        "endpoint_cleanup": sorted(
            (dict(item) for item in endpoint_cleanup),
            key=lambda item: str(item.get("endpoint_id", "")),
        ),
        "actual_cost_report": dict(actual_cost_report),
        "champion_matrix_sha256": champion_matrix_sha256,
        "mandatory_test_omissions": sorted(set(mandatory_test_omissions)),
    }
    _validate_evidence_payload(payload)
    canonical_json_bytes(payload)
    return payload


def sign_evidence(
    payload: Mapping[str, object],
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    signed_at: str,
) -> dict[str, object]:
    if not key_id.strip():
        raise ContractError("key_id is required")
    _validate_timestamp(signed_at)
    normalized = dict(payload)
    payload_bytes = canonical_json_bytes(normalized)
    signature = private_key.sign(payload_bytes)
    return {
        "schema_version": "6.0.0",
        "algorithm": "Ed25519",
        "key_id": key_id,
        "signed_at": signed_at,
        "payload_sha256": canonical_sha256(normalized),
        "payload": normalized,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def verify_signed_evidence(
    envelope: Mapping[str, Any],
    *,
    public_key: Ed25519PublicKey,
) -> dict[str, object]:
    required = {
        "schema_version",
        "algorithm",
        "key_id",
        "signed_at",
        "payload_sha256",
        "payload",
        "signature",
    }
    missing = sorted(required - envelope.keys())
    if missing:
        raise ContractError(f"signed evidence fields missing: {missing}")
    if envelope["schema_version"] != "6.0.0" or envelope["algorithm"] != "Ed25519":
        raise ContractError("unsupported evidence schema or signature algorithm")
    if not isinstance(envelope["key_id"], str) or not envelope["key_id"].strip():
        raise ContractError("signed evidence key_id is invalid")
    if not isinstance(envelope["signed_at"], str):
        raise ContractError("signed_at must be a UTC timestamp string")
    _validate_timestamp(envelope["signed_at"])
    payload = envelope["payload"]
    if not isinstance(payload, Mapping):
        raise ContractError("signed evidence payload must be an object")
    payload_sha256 = str(envelope["payload_sha256"])
    require_sha256(payload_sha256, "payload_sha256")
    actual_sha256 = canonical_sha256(payload)
    if actual_sha256 != payload_sha256:
        raise ContractError("signed evidence payload digest mismatch")
    try:
        signature = base64.b64decode(str(envelope["signature"]), validate=True)
    except (ValueError, TypeError) as exc:
        raise ContractError("signed evidence signature is not valid base64") from exc
    try:
        public_key.verify(signature, canonical_json_bytes(payload))
    except InvalidSignature as exc:
        raise ContractError("signed evidence signature verification failed") from exc
    _validate_evidence_payload(payload)
    return {
        "verified": True,
        "payload_sha256": payload_sha256,
        "key_id": envelope["key_id"],
        "production_evidence": bool(payload.get("production_evidence", False)),
        "payload": dict(payload),
    }


def _validate_timestamp(value: str) -> None:
    if not _UTC_TIMESTAMP_RE.fullmatch(value):
        raise ContractError("signed_at must be an explicit UTC RFC3339 timestamp")
    try:
        datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ContractError("signed_at is not a real timestamp") from exc


def _validate_external_run_records(records: Sequence[Mapping[str, object]]) -> None:
    run_ids: set[object] = set()
    for record in records:
        run_id = record.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ContractError("production run records require run_id")
        if run_id in run_ids:
            raise ContractError(f"duplicate production run record: {run_id}")
        run_ids.add(run_id)
        if record.get("production_actual") is not True:
            raise ContractError("production evidence may not contain mock or local-only runs")
        if record.get("status") != "passed":
            raise ContractError("production evidence may contain only passed mandatory runs")
        if record.get("critical_failure_count") != 0:
            raise ContractError("production evidence may not contain critical failures")
        if record.get("gt_leakage_count") != 0:
            raise ContractError("production evidence may not contain GT leakage")
        if "actual_cost_usd" not in record:
            raise ContractError("production run records require actual_cost_usd")


def _normalize_gate_results(values: Mapping[str, object]) -> dict[str, str]:
    unexpected = sorted(set(values) - set(_REQUIRED_PROMOTION_GATES))
    missing = sorted(set(_REQUIRED_PROMOTION_GATES) - set(values))
    if unexpected or missing:
        raise ContractError(
            f"promotion gate snapshot mismatch; missing={missing}, unexpected={unexpected}"
        )
    normalized: dict[str, str] = {}
    for gate_id in _REQUIRED_PROMOTION_GATES:
        status = str(values[gate_id])
        if status not in _GATE_STATUSES:
            raise ContractError(f"invalid signed gate status for {gate_id}: {status!r}")
        normalized[gate_id] = status
    return normalized


def _validate_public_core_coverage(
    records: Sequence[Mapping[str, object]],
    *,
    candidate_id: str,
    incumbent_candidate_id: str,
) -> None:
    identities = (candidate_id, incumbent_candidate_id)
    scoped = [
        record
        for record in records
        if record.get("candidate_id") in identities
        and record.get("benchmark_id") in PUBLIC_CORE_BENCHMARK_IDS
    ]
    expected = {
        (benchmark_id, model_id, repeat_index)
        for benchmark_id in PUBLIC_CORE_BENCHMARK_IDS
        for model_id in identities
        for repeat_index in (1, 2, 3)
    }
    observed = [
        (record.get("benchmark_id"), record.get("candidate_id"), record.get("repeat_index"))
        for record in scoped
    ]
    if len(scoped) != len(expected) or set(observed) != expected:
        raise ContractError(
            "production evidence requires exact candidate and incumbent Public Core repeats"
        )
    for benchmark_id in PUBLIC_CORE_BENCHMARK_IDS:
        cohort = [record for record in scoped if record.get("benchmark_id") == benchmark_id]
        environments = {record.get("environment_sha256") for record in cohort}
        cohorts = {record.get("cohort_id") for record in cohort}
        if len(environments) != 1 or len(cohorts) != 1:
            raise ContractError(
                f"candidate and incumbent must share one immutable cohort for {benchmark_id}"
            )


def _validate_evidence_payload(payload: Mapping[str, object]) -> None:
    required = {
        "schema_version",
        "evidence_mode",
        "production_evidence",
        "candidate_id",
        "incumbent_candidate_id",
        "requested_target",
        "release_commit",
        "source_tree_sha256",
        "candidate_registry_sha256",
        "public_core_registry_sha256",
        "required_benchmark_ids",
        "gate_results",
        "critical_failure_count",
        "run_records",
        "failure_bundles",
        "endpoint_cleanup",
        "actual_cost_report",
        "champion_matrix_sha256",
        "mandatory_test_omissions",
    }
    missing = sorted(required - payload.keys())
    unexpected = sorted(payload.keys() - required)
    if missing or unexpected:
        raise ContractError(
            f"signed evidence payload fields mismatch; missing={missing}, unexpected={unexpected}"
        )
    if payload["schema_version"] != "6.0.0":
        raise ContractError("unsupported signed evidence payload schema")
    production = payload["production_evidence"]
    if not isinstance(production, bool):
        raise ContractError("production_evidence must be boolean")
    expected_mode = "external_actual" if production else "local_contract_only"
    if payload["evidence_mode"] != expected_mode:
        raise ContractError("evidence mode contradicts production_evidence")
    candidate_id = payload["candidate_id"]
    incumbent_id = payload["incumbent_candidate_id"]
    if (
        not isinstance(candidate_id, str)
        or not candidate_id.strip()
        or not isinstance(incumbent_id, str)
        or not incumbent_id.strip()
        or candidate_id == incumbent_id
    ):
        raise ContractError("signed candidate and incumbent identities are invalid")
    if payload["requested_target"] not in {"shadow", "canary", "production"}:
        raise ContractError("signed requested_target is invalid")
    release_commit = payload["release_commit"]
    if not isinstance(release_commit, str):
        raise ContractError("signed release_commit is invalid")
    require_commit(release_commit, "release_commit")
    for field in (
        "source_tree_sha256",
        "candidate_registry_sha256",
        "public_core_registry_sha256",
        "champion_matrix_sha256",
    ):
        value = payload[field]
        if not isinstance(value, str):
            raise ContractError(f"signed {field} is invalid")
        require_sha256(value, field)
    if payload["required_benchmark_ids"] != list(PUBLIC_CORE_BENCHMARK_IDS):
        raise ContractError("signed Public Core benchmark scope is invalid")
    gate_results = payload["gate_results"]
    if not isinstance(gate_results, Mapping):
        raise ContractError("signed gate_results must be an object")
    normalized_gates = _normalize_gate_results(gate_results)
    critical_failure_count = payload["critical_failure_count"]
    if (
        isinstance(critical_failure_count, bool)
        or not isinstance(critical_failure_count, int)
        or critical_failure_count < 0
    ):
        raise ContractError("signed critical_failure_count is invalid")
    omissions = payload["mandatory_test_omissions"]
    if not isinstance(omissions, list) or any(
        not isinstance(item, str) or not item for item in omissions
    ):
        raise ContractError("signed mandatory_test_omissions is invalid")
    if omissions != sorted(set(omissions)):
        raise ContractError("signed mandatory_test_omissions must be sorted and unique")
    run_records = payload["run_records"]
    if not isinstance(run_records, list) or any(
        not isinstance(item, Mapping) for item in run_records
    ):
        raise ContractError("signed run_records must be a list of objects")
    if not isinstance(payload["failure_bundles"], list):
        raise ContractError("signed failure_bundles must be a list")
    cleanup = payload["endpoint_cleanup"]
    cost = payload["actual_cost_report"]
    if not isinstance(cleanup, list) or any(not isinstance(item, Mapping) for item in cleanup):
        raise ContractError("signed endpoint_cleanup must be a list of objects")
    if not isinstance(cost, Mapping):
        raise ContractError("signed actual_cost_report must be an object")
    if production:
        _validate_external_run_records(run_records)
        _validate_public_core_coverage(
            run_records,
            candidate_id=candidate_id,
            incumbent_candidate_id=incumbent_id,
        )
        if omissions:
            raise ContractError("production evidence cannot omit mandatory tests")
        if critical_failure_count != 0:
            raise ContractError("production evidence cannot contain critical failures")
        if any(status != "pass" for status in normalized_gates.values()):
            raise ContractError("production evidence requires every promotion gate to pass")
        if not cleanup or any(item.get("state") != "deleted" for item in cleanup):
            raise ContractError("production evidence requires endpoint cleanup receipts")
        if cost.get("actual") is not True or "provider_cost_usd" not in cost:
            raise ContractError("production evidence requires an actual provider cost report")
