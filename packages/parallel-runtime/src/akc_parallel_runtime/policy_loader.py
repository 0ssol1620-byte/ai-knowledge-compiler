"""Strict offline loader for frozen calibrated policy bundles and scheduler wiring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .calibrated_router import (
    CalibratedRoutingPolicyRouter,
    CalibratedScoreRow,
    CalibratedScoreTable,
)
from .calibration import CanaryReceipt, ReceiptVerifier, evaluate_policy_authority
from .identity import canonical_json, require_sha256, sha256_hex
from .policy_artifact import (
    CalibratedPolicyArtifact,
    FamilySplitBinding,
    ModelIdentityBinding,
    RepeatRunBinding,
)
from .routing import QualityEstimate, RoutingAuthorityRouter

POLICY_SCHEMA = "akc.router.calibrated-policy.v1"
SCORE_TABLE_SCHEMA = "akc.router.calibrated-score-table.v1"
CANARY_RECEIPT_SCHEMA = "akc.router.canary-receipt.v1"


class PolicyBundleLoadError(ValueError):
    """A downloaded policy blob is untrusted, malformed, or outside its binding."""


def _reject_constant(value: str) -> None:
    raise PolicyBundleLoadError(f"non-finite JSON constant is forbidden: {value}")


def _decode(blob: bytes, *, name: str) -> dict[str, Any]:
    if not isinstance(blob, bytes) or not blob:
        raise PolicyBundleLoadError(f"{name} must be non-empty downloaded bytes")
    try:
        value = json.loads(blob.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PolicyBundleLoadError(f"{name} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise PolicyBundleLoadError(f"{name} must be a JSON object")
    return value


def _exact(value: object, keys: set[str], *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise PolicyBundleLoadError(f"{name} schema fields do not match exactly")
    return value


def _string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyBundleLoadError(f"{name} must be a non-empty string")
    return value


def _sha(value: object, *, name: str) -> str:
    try:
        return require_sha256(_string(value, name=name), field_name=name)
    except ValueError as exc:
        raise PolicyBundleLoadError(str(exc)) from exc


def _integer(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise PolicyBundleLoadError(f"{name} must be an integer")
    return value


def _boolean(value: object, *, name: str) -> bool:
    if type(value) is not bool:
        raise PolicyBundleLoadError(f"{name} must be a bool")
    return value


def _number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyBundleLoadError(f"{name} must be an explicit JSON number")
    return value


def _timestamp(value: object, *, name: str) -> datetime:
    text = _string(value, name=name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PolicyBundleLoadError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PolicyBundleLoadError(f"{name} must be timezone-aware")
    return parsed


def _string_set(value: object, *, name: str) -> frozenset[str]:
    if not isinstance(value, list) or not value:
        raise PolicyBundleLoadError(f"{name} must be a non-empty JSON array")
    items = tuple(_string(item, name=name) for item in value)
    if len(set(items)) != len(items):
        raise PolicyBundleLoadError(f"{name} cannot contain duplicates")
    return frozenset(items)


def _verify_blob(blob: bytes, expected_sha256: str, *, name: str) -> None:
    expected = _sha(expected_sha256, name=f"expected_{name}_sha256")
    if sha256_hex(blob) != expected:
        raise PolicyBundleLoadError(f"{name} downloaded blob sha256 mismatch")


def _model(value: object) -> ModelIdentityBinding:
    item = _exact(
        value,
        {
            "provider",
            "model_id",
            "revision",
            "input_mode",
            "settings_sha256",
            "capability_receipt_sha256",
        },
        name="model_identity",
    )
    return ModelIdentityBinding(
        provider=_string(item["provider"], name="provider"),
        model_id=_string(item["model_id"], name="model_id"),
        revision=_string(item["revision"], name="revision"),
        input_mode=_string(item["input_mode"], name="input_mode"),
        settings_sha256=_sha(item["settings_sha256"], name="settings_sha256"),
        capability_receipt_sha256=_sha(
            item["capability_receipt_sha256"], name="capability_receipt_sha256"
        ),
    )


def _run(value: object) -> RepeatRunBinding:
    item = _exact(
        value,
        {
            "run_id",
            "run_receipt_sha256",
            "result_sha256",
            "experiment_binding_sha256",
            "completed_at",
        },
        name="repeat_run",
    )
    return RepeatRunBinding(
        run_id=_string(item["run_id"], name="run_id"),
        run_receipt_sha256=_sha(item["run_receipt_sha256"], name="run_receipt_sha256"),
        result_sha256=_sha(item["result_sha256"], name="result_sha256"),
        experiment_binding_sha256=_sha(
            item["experiment_binding_sha256"], name="experiment_binding_sha256"
        ),
        completed_at=_timestamp(item["completed_at"], name="completed_at"),
    )


def _load_policy(blob: bytes) -> CalibratedPolicyArtifact:
    root = _exact(_decode(blob, name="policy"), {"schema_version", "artifact"}, name="policy")
    if root["schema_version"] != POLICY_SCHEMA:
        raise PolicyBundleLoadError("unsupported calibrated policy schema")
    item = _exact(
        root["artifact"],
        {
            "policy_version",
            "created_at",
            "corpus_manifest_sha256",
            "family_split",
            "prompt_calibration_corpus_sha256",
            "prompt_calibration_family_ids",
            "evaluator_registry_sha256",
            "model_identities",
            "price_measurements_sha256",
            "price_evidence_kind",
            "price_measurement_count",
            "prompt_receipt_sha256",
            "hardware_receipt_sha256",
            "hardware_measurement_count",
            "preregistration_sha256",
            "calibration_table_sha256",
            "repeat_runs",
            "artifact_sha256",
        },
        name="policy.artifact",
    )
    split = _exact(
        item["family_split"],
        {"train_family_ids", "calibration_family_ids", "holdout_family_ids"},
        name="family_split",
    )
    models = item["model_identities"]
    runs = item["repeat_runs"]
    if not isinstance(models, list) or not isinstance(runs, list):
        raise PolicyBundleLoadError("model identities and repeat runs must be arrays")
    artifact = CalibratedPolicyArtifact(
        policy_version=_string(item["policy_version"], name="policy_version"),
        created_at=_timestamp(item["created_at"], name="created_at"),
        corpus_manifest_sha256=_sha(
            item["corpus_manifest_sha256"], name="corpus_manifest_sha256"
        ),
        family_split=FamilySplitBinding(
            train_family_ids=_string_set(
                split["train_family_ids"], name="train_family_ids"
            ),
            calibration_family_ids=_string_set(
                split["calibration_family_ids"], name="calibration_family_ids"
            ),
            holdout_family_ids=_string_set(
                split["holdout_family_ids"], name="holdout_family_ids"
            ),
        ),
        prompt_calibration_corpus_sha256=_sha(
            item["prompt_calibration_corpus_sha256"],
            name="prompt_calibration_corpus_sha256",
        ),
        prompt_calibration_family_ids=_string_set(
            item["prompt_calibration_family_ids"],
            name="prompt_calibration_family_ids",
        ),
        evaluator_registry_sha256=_sha(
            item["evaluator_registry_sha256"], name="evaluator_registry_sha256"
        ),
        model_identities=tuple(_model(model) for model in models),
        price_measurements_sha256=_sha(
            item["price_measurements_sha256"], name="price_measurements_sha256"
        ),
        price_evidence_kind=_string(item["price_evidence_kind"], name="price_evidence_kind"),
        price_measurement_count=_integer(
            item["price_measurement_count"], name="price_measurement_count"
        ),
        prompt_receipt_sha256=_sha(
            item["prompt_receipt_sha256"], name="prompt_receipt_sha256"
        ),
        hardware_receipt_sha256=_sha(
            item["hardware_receipt_sha256"], name="hardware_receipt_sha256"
        ),
        hardware_measurement_count=_integer(
            item["hardware_measurement_count"], name="hardware_measurement_count"
        ),
        preregistration_sha256=_sha(
            item["preregistration_sha256"], name="preregistration_sha256"
        ),
        calibration_table_sha256=_sha(
            item["calibration_table_sha256"], name="calibration_table_sha256"
        ),
        repeat_runs=tuple(_run(run) for run in runs),
        artifact_sha256=_sha(item["artifact_sha256"], name="artifact_sha256"),
    )
    artifact.verify_integrity()
    return artifact


_ESTIMATE_FIELDS = {
    "pass_hard_gate",
    "numeric_exact",
    "row_complete",
    "repetition_probability",
    "timeout_probability",
    "oom_probability",
    "expected_latency_seconds",
    "expected_cost",
}


def _score_row(value: object) -> CalibratedScoreRow:
    item = _exact(
        value,
        {
            "recipe_id",
            "worker_id",
            "model_revision",
            "runtime_image_digest",
            "model_identity_sha256",
            "estimate",
        },
        name="score_row",
    )
    estimate = _exact(item["estimate"], _ESTIMATE_FIELDS, name="score_row.estimate")
    return CalibratedScoreRow(
        recipe_id=_string(item["recipe_id"], name="recipe_id"),
        worker_id=_string(item["worker_id"], name="worker_id"),
        model_revision=_string(item["model_revision"], name="model_revision"),
        runtime_image_digest=_string(
            item["runtime_image_digest"], name="runtime_image_digest"
        ),
        model_identity_sha256=_sha(
            item["model_identity_sha256"], name="model_identity_sha256"
        ),
        estimate=QualityEstimate(
            **{
                field: _number(estimate[field], name=field)
                for field in _ESTIMATE_FIELDS
            }
        ),
    )


def _load_score_table(blob: bytes) -> CalibratedScoreTable:
    root = _exact(
        _decode(blob, name="score_table"),
        {"schema_version", "score_table"},
        name="score_table",
    )
    if root["schema_version"] != SCORE_TABLE_SCHEMA:
        raise PolicyBundleLoadError("unsupported calibrated score-table schema")
    item = _exact(
        root["score_table"],
        {"evaluator_registry_sha256", "model_identities_sha256", "rows", "table_sha256"},
        name="score_table.payload",
    )
    rows = item["rows"]
    if not isinstance(rows, list):
        raise PolicyBundleLoadError("score-table rows must be an array")
    table = CalibratedScoreTable(
        evaluator_registry_sha256=_sha(
            item["evaluator_registry_sha256"], name="evaluator_registry_sha256"
        ),
        model_identities_sha256=_sha(
            item["model_identities_sha256"], name="model_identities_sha256"
        ),
        rows=tuple(_score_row(row) for row in rows),
        table_sha256=_sha(item["table_sha256"], name="table_sha256"),
    )
    table.verify_integrity()
    return table


@dataclass(frozen=True, slots=True)
class FrozenCalibratedPolicyBundle:
    policy_artifact: CalibratedPolicyArtifact
    score_table: CalibratedScoreTable

    def __post_init__(self) -> None:
        CalibratedRoutingPolicyRouter(
            policy_artifact=self.policy_artifact,
            score_table=self.score_table,
        )


def load_calibrated_policy_bundle_bytes(
    *,
    policy_bytes: bytes,
    score_table_bytes: bytes,
    expected_policy_blob_sha256: str,
    expected_score_table_blob_sha256: str,
) -> FrozenCalibratedPolicyBundle:
    _verify_blob(policy_bytes, expected_policy_blob_sha256, name="policy_blob")
    _verify_blob(score_table_bytes, expected_score_table_blob_sha256, name="score_table_blob")
    return FrozenCalibratedPolicyBundle(
        policy_artifact=_load_policy(policy_bytes),
        score_table=_load_score_table(score_table_bytes),
    )


def _read_rooted(trusted_root: Path, relative_path: Path, *, name: str) -> bytes:
    if relative_path.is_absolute():
        raise PolicyBundleLoadError(f"{name} must be relative to the trusted root")
    try:
        root = trusted_root.resolve(strict=True)
        resolved = (root / relative_path).resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise PolicyBundleLoadError(f"{name} escapes the trusted root or does not exist") from exc
    if not resolved.is_file():
        raise PolicyBundleLoadError(f"{name} must resolve to a regular file")
    return resolved.read_bytes()


def load_calibrated_policy_bundle_paths(
    *,
    trusted_root: Path,
    policy_relative_path: Path,
    score_table_relative_path: Path,
    expected_policy_blob_sha256: str,
    expected_score_table_blob_sha256: str,
) -> FrozenCalibratedPolicyBundle:
    return load_calibrated_policy_bundle_bytes(
        policy_bytes=_read_rooted(trusted_root, policy_relative_path, name="policy path"),
        score_table_bytes=_read_rooted(
            trusted_root, score_table_relative_path, name="score-table path"
        ),
        expected_policy_blob_sha256=expected_policy_blob_sha256,
        expected_score_table_blob_sha256=expected_score_table_blob_sha256,
    )


def _load_canary_receipt(blob: bytes) -> CanaryReceipt:
    root = _exact(
        _decode(blob, name="canary_receipt"),
        {"schema_version", "receipt"},
        name="canary_receipt",
    )
    if root["schema_version"] != CANARY_RECEIPT_SCHEMA:
        raise PolicyBundleLoadError("unsupported canary receipt schema")
    item = _exact(
        root["receipt"],
        {
            "policy_artifact_sha256",
            "calibration_table_sha256",
            "cohort_id",
            "eligible",
            "low_risk_only",
            "valid_from",
            "expires_at",
            "signer_key_id",
            "signature",
            "receipt_sha256",
        },
        name="canary_receipt.payload",
    )
    return CanaryReceipt(
        policy_artifact_sha256=_sha(
            item["policy_artifact_sha256"], name="policy_artifact_sha256"
        ),
        calibration_table_sha256=_sha(
            item["calibration_table_sha256"], name="calibration_table_sha256"
        ),
        cohort_id=_string(item["cohort_id"], name="cohort_id"),
        eligible=_boolean(item["eligible"], name="eligible"),
        low_risk_only=_boolean(item["low_risk_only"], name="low_risk_only"),
        valid_from=_timestamp(item["valid_from"], name="valid_from"),
        expires_at=_timestamp(item["expires_at"], name="expires_at"),
        signer_key_id=_string(item["signer_key_id"], name="signer_key_id"),
        signature=_string(item["signature"], name="signature"),
        receipt_sha256=_sha(item["receipt_sha256"], name="receipt_sha256"),
    )


@dataclass(frozen=True, slots=True)
class CalibratedSchedulerRouterConfig:
    policy_artifact: CalibratedPolicyArtifact
    canary_receipt: CanaryReceipt
    verifier: ReceiptVerifier
    routing_authority_router: RoutingAuthorityRouter

    def as_coordinator_kwargs(self) -> dict[str, object]:
        return {
            "router_authority_evaluator": evaluate_policy_authority,
            "router_policy_artifact": self.policy_artifact,
            "router_canary_receipt": self.canary_receipt,
            "router_canary_verifier": self.verifier,
            "routing_authority_router": self.routing_authority_router,
        }


def build_scheduler_router_config(
    *,
    bundle: FrozenCalibratedPolicyBundle,
    canary_receipt_bytes: bytes,
    expected_receipt_blob_sha256: str,
    verifier: ReceiptVerifier,
    now: datetime,
    expected_cohort_id: str,
    low_risk_cohort: bool,
    maximum_cost: float | None,
) -> CalibratedSchedulerRouterConfig:
    if maximum_cost is None:
        raise PolicyBundleLoadError(
            "an explicit maximum cost snapshot is required for canary configuration"
        )
    _verify_blob(
        canary_receipt_bytes,
        expected_receipt_blob_sha256,
        name="canary_receipt_blob",
    )
    receipt = _load_canary_receipt(canary_receipt_bytes)
    authority = evaluate_policy_authority(
        requested_mode="canary",
        policy_artifact=bundle.policy_artifact,
        canary_receipt=receipt,
        verifier=verifier,
        now=now,
        low_risk_cohort=low_risk_cohort,
        expected_cohort_id=expected_cohort_id,
    )
    if authority.effective_mode != "canary":
        reason = ",".join(authority.reason_codes) or "unknown"
        raise PolicyBundleLoadError(f"canary scheduler configuration denied: {reason}")
    calibrated = CalibratedRoutingPolicyRouter(
        policy_artifact=bundle.policy_artifact,
        score_table=bundle.score_table,
        maximum_cost=maximum_cost,
    )
    return CalibratedSchedulerRouterConfig(
        policy_artifact=bundle.policy_artifact,
        canary_receipt=receipt,
        verifier=verifier,
        routing_authority_router=RoutingAuthorityRouter(calibrated=calibrated),
    )


def encode_policy_artifact(artifact: CalibratedPolicyArtifact) -> bytes:
    artifact.verify_integrity()
    payload = {
        "policy_version": artifact.policy_version,
        "created_at": artifact.created_at,
        "corpus_manifest_sha256": artifact.corpus_manifest_sha256,
        "family_split": {
            "train_family_ids": sorted(artifact.family_split.train_family_ids),
            "calibration_family_ids": sorted(artifact.family_split.calibration_family_ids),
            "holdout_family_ids": sorted(artifact.family_split.holdout_family_ids),
        },
        "prompt_calibration_corpus_sha256": artifact.prompt_calibration_corpus_sha256,
        "prompt_calibration_family_ids": sorted(artifact.prompt_calibration_family_ids),
        "evaluator_registry_sha256": artifact.evaluator_registry_sha256,
        "model_identities": artifact.model_identities,
        "price_measurements_sha256": artifact.price_measurements_sha256,
        "price_evidence_kind": artifact.price_evidence_kind,
        "price_measurement_count": artifact.price_measurement_count,
        "prompt_receipt_sha256": artifact.prompt_receipt_sha256,
        "hardware_receipt_sha256": artifact.hardware_receipt_sha256,
        "hardware_measurement_count": artifact.hardware_measurement_count,
        "preregistration_sha256": artifact.preregistration_sha256,
        "calibration_table_sha256": artifact.calibration_table_sha256,
        "repeat_runs": artifact.repeat_runs,
        "artifact_sha256": artifact.artifact_sha256,
    }
    return canonical_json({"schema_version": POLICY_SCHEMA, "artifact": payload}).encode()


def encode_score_table(score_table: CalibratedScoreTable) -> bytes:
    score_table.verify_integrity()
    return canonical_json(
        {"schema_version": SCORE_TABLE_SCHEMA, "score_table": score_table}
    ).encode()


def encode_canary_receipt(receipt: CanaryReceipt) -> bytes:
    receipt.verify_integrity()
    return canonical_json(
        {"schema_version": CANARY_RECEIPT_SCHEMA, "receipt": receipt}
    ).encode()


__all__ = [
    "CANARY_RECEIPT_SCHEMA",
    "POLICY_SCHEMA",
    "SCORE_TABLE_SCHEMA",
    "CalibratedSchedulerRouterConfig",
    "FrozenCalibratedPolicyBundle",
    "PolicyBundleLoadError",
    "build_scheduler_router_config",
    "encode_canary_receipt",
    "encode_policy_artifact",
    "encode_score_table",
    "load_calibrated_policy_bundle_bytes",
    "load_calibrated_policy_bundle_paths",
]
