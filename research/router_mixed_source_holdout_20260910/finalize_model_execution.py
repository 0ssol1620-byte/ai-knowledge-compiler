"""Close the complete model-call denominator before holdout truth can open."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from . import execution_input_admission
from .execution_input_admission import _streaming_digest, _write_immutable_receipt
from .preflight_mixed_holdout import _contains_forbidden_key, digest, load_json, load_jsonl

SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
FINAL_STATUSES = frozenset({"SUCCESS", "FAILED", "TIMEOUT", "REFUSED"})
MAXIMUM_OUTPUT_BYTES = 64 * 1024 * 1024
MAXIMUM_AGGREGATE_OUTPUT_BYTES = 16 * 1024 * 1024 * 1024
ADMISSION_FIELDS = frozenset(
    {
        "schema",
        "passed",
        "blockers",
        "units",
        "rendered_units",
        "models",
        "requests",
        "input_digests",
        "gate_sha256",
        "actual_source_bytes_verified",
        "actual_render_bytes_verified",
        "actual_model_artifact_bytes_verified",
        "truth_opened",
        "model_calls_before_admission",
        "model_call_authorized",
        "production_promotion",
    }
)
OUTPUT_ENVELOPE_FIELDS = frozenset(
    {
        "schema",
        "request_id",
        "unit_id",
        "model_key",
        "source_sha256",
        "render_sha256",
        "router_policy_sha256",
        "runtime_sha256",
        "bundle_sha256",
        "inference_config_sha256",
        "base_image",
        "status",
        "model_output",
    }
)
PROVIDER_RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "provider",
        "attempt_id",
        "request_id",
        "model_key",
        "pod_id",
        "status",
        "started_at_utc",
        "completed_at_utc",
        "elapsed_seconds",
        "hourly_rate_usd",
        "estimated_cost_usd",
        "provider_observed_at_utc",
        "provider_event_method",
        "provider_event_endpoint",
        "provider_event_query",
        "provider_event_request_sha256",
        "provider_event_status_code",
        "base_image",
        "provider_event_relative_path",
        "provider_event_sha256",
    }
)
TEARDOWN_FIELDS = frozenset(
    {
        "schema",
        "created_pod_ids",
        "terminated_pod_ids",
        "live_campaign_pod_ids",
        "peak_parallel_pods",
        "provider_snapshot_relative_path",
        "provider_snapshot_sha256",
    }
)
PROVIDER_SNAPSHOT_FIELDS = frozenset(
    {
        "schema",
        "provider",
        "campaign_id",
        "checked_at_utc",
        "live_campaign_pod_ids",
        "provider_response_method",
        "provider_response_endpoint",
        "provider_response_query",
        "provider_response_request_sha256",
        "provider_response_status_code",
        "provider_response_relative_path",
        "provider_response_sha256",
    }
)
BILLING_RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "provider",
        "campaign_id",
        "query_start_utc",
        "query_end_utc",
        "bucket_size",
        "grouping",
        "pod_ids",
        "checked_at_utc",
        "provider_queries",
        "observed_spend_usd",
    }
)
BILLING_QUERY_FIELDS = frozenset(
    {
        "method",
        "endpoint",
        "query",
        "request_sha256",
        "status_code",
        "response_schema",
        "response_relative_path",
        "response_sha256",
    }
)
BILLING_RECORD_FIELDS = frozenset(
    {
        "amount",
        "diskSpaceBilledGb",
        "endpointId",
        "gpuTypeId",
        "podId",
        "time",
        "timeBilledMs",
    }
)
BILLING_ENVELOPE_FIELDS = frozenset({"records", "metadata"})
BILLING_METADATA_FIELDS = frozenset(
    {"recordCount", "uniquePodCount", "totals"}
)
BILLING_TOTAL_FIELDS = frozenset({"totalAmount", "gpuAmount", "diskAmount"})


def _canonical_request_sha256(
    method: str, endpoint: str, query: Mapping[str, object]
) -> str:
    payload = json.dumps(
        {"method": method, "endpoint": endpoint, "query": query},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return digest(payload)
OUTPUT_FIELDS = frozenset(
    {
        "request_id",
        "unit_id",
        "model_key",
        "source_sha256",
        "render_sha256",
        "status",
        "output_relative_path",
        "output_sha256",
        "output_size_bytes",
        "error_code",
    }
)
ATTEMPT_FIELDS = frozenset(
    {
        "attempt_id",
        "request_id",
        "model_key",
        "pod_id",
        "started_at_utc",
        "completed_at_utc",
        "status",
        "cost_usd",
        "provider_receipt_relative_path",
        "provider_receipt_sha256",
        "base_image",
    }
)


@dataclass(frozen=True, slots=True)
class FinalizationResult:
    passed: bool
    blockers: tuple[str, ...]
    expected_requests: int
    final_statuses: int
    attempts: int
    successes: int
    failures_retained: int
    spend_usd: float
    created_pods: int
    terminated_pods: int
    input_digests: Mapping[str, str]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.router_execution_finalization.v1",
            "passed": self.passed,
            "blockers": list(self.blockers),
            "expected_requests": self.expected_requests,
            "final_statuses": self.final_statuses,
            "attempts": self.attempts,
            "successes": self.successes,
            "failures_retained": self.failures_retained,
            "spend_usd": self.spend_usd,
            "created_pods": self.created_pods,
            "terminated_pods": self.terminated_pods,
            "input_digests": dict(sorted(self.input_digests.items())),
            "all_requested_units_retained": self.final_statuses
            == self.expected_requests,
            "truth_opened": False,
            "production_promotion": False,
        }


def _safe_file(root: Path, relative: object) -> Path | None:
    if not isinstance(relative, str) or not relative:
        return None
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        return None
    resolved_root = root.resolve()
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo == UTC else None


def _load_json_value_bounded(path: Path, maximum_bytes: int = 16 * 1024 * 1024) -> object:
    size = path.stat().st_size
    if size <= 0 or size > maximum_bytes:
        raise ValueError("JSON_SIZE_INVALID")
    return json.loads(path.read_bytes())


def _runpod_rate(value: Mapping[str, Any]) -> float | None:
    raw = value.get("adjustedCostPerHr", value.get("costPerHr"))
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    try:
        rate = float(raw)
    except ValueError:
        return None
    return rate if math.isfinite(rate) and rate >= 0 else None


def _expected_pod_name(campaign_id: object, model_key: object) -> str | None:
    if not isinstance(campaign_id, str) or not isinstance(model_key, str):
        return None
    value = f"tavonel-router-{campaign_id}-{model_key}".replace("_", "-")
    return value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,190}", value) else None


def evaluate_finalization(
    *,
    admission_path: Path,
    request_manifest_path: Path,
    output_status_path: Path,
    output_root: Path,
    attempt_ledger_path: Path,
    provider_receipt_root: Path,
    teardown_path: Path,
    provider_snapshot_root: Path,
    execution_limits_path: Path,
    billing_receipt_path: Path,
    provider_billing_root: Path,
    truth_root: Path,
) -> FinalizationResult:
    blockers: list[str] = []
    admission = load_json(admission_path)
    requests = load_jsonl(request_manifest_path)
    statuses = load_jsonl(output_status_path)
    attempts = load_jsonl(attempt_ledger_path)
    teardown = load_json(teardown_path)
    limits = load_json(execution_limits_path)
    input_digests = {
        "admission": digest(admission_path.read_bytes()),
        "request_manifest": digest(request_manifest_path.read_bytes()),
        "output_status_manifest": digest(output_status_path.read_bytes()),
        "attempt_ledger": digest(attempt_ledger_path.read_bytes()),
        "teardown": digest(teardown_path.read_bytes()),
        "execution_limits": digest(execution_limits_path.read_bytes()),
        "billing_receipt": digest(billing_receipt_path.read_bytes()),
    }
    if (
        set(admission) != ADMISSION_FIELDS
        or admission.get("schema") != "tavonel.router_execution_input_admission.v1"
        or admission.get("passed") is not True
        or admission.get("blockers") != []
        or admission.get("actual_source_bytes_verified") is not True
        or admission.get("actual_render_bytes_verified") is not True
        or admission.get("actual_model_artifact_bytes_verified") is not True
        or admission.get("model_call_authorized") is not True
        or admission.get("truth_opened") is not False
        or admission.get("model_calls_before_admission") != 0
        or admission.get("production_promotion") is not False
        or admission.get("gate_sha256")
        != digest(Path(execution_input_admission.__file__).read_bytes())
    ):
        blockers.append("INPUT_ADMISSION_INVALID")
    raw_admission_digests = admission.get("input_digests")
    admission_digests = (
        raw_admission_digests if isinstance(raw_admission_digests, Mapping) else {}
    )
    if set(admission_digests) != execution_input_admission.ADMISSION_INPUT_DIGEST_FIELDS:
        blockers.append("INPUT_ADMISSION_DIGEST_SCHEMA_INVALID")
    if admission_digests.get("request_manifest") != input_digests["request_manifest"]:
        blockers.append("REQUEST_MANIFEST_ADMISSION_MISMATCH")
    if admission_digests.get("execution_limits") != input_digests["execution_limits"]:
        blockers.append("EXECUTION_LIMITS_ADMISSION_MISMATCH")
    if admission.get("requests") != len(requests):
        blockers.append("REQUEST_COUNT_ADMISSION_MISMATCH")
    if admission_digests.get("truth_root_path") != digest(
        str(truth_root.resolve()).encode("utf-8")
    ):
        blockers.append("TRUTH_ROOT_ADMISSION_MISMATCH")
    if truth_root.exists() and any(truth_root.iterdir()):
        blockers.append("HOLDOUT_TRUTH_OPENED_BEFORE_FINALIZATION")
    for name, value in (
        ("OUTPUT_STATUS", statuses),
        ("ATTEMPT_LEDGER", attempts),
        ("TEARDOWN", teardown),
        ("EXECUTION_LIMITS", limits),
    ):
        if _contains_forbidden_key(value):
            blockers.append(f"{name}_TRUTH_FIELD_FORBIDDEN")

    request_by_id: dict[str, Mapping[str, Any]] = {}
    request_pairs: set[tuple[str, str]] = set()
    request_units: set[str] = set()
    request_models: set[str] = set()
    for index, row in enumerate(requests):
        if set(row) != execution_input_admission.REQUEST_FIELDS:
            blockers.append(f"REQUEST_{index:04d}_SCHEMA_INVALID")
        request_id = row.get("request_id")
        if not isinstance(request_id, str) or request_id in request_by_id:
            blockers.append(f"REQUEST_{index:04d}_IDENTITY_INVALID_OR_DUPLICATE")
        else:
            request_by_id[request_id] = row
        unit_id = row.get("unit_id")
        model_key = row.get("model_key")
        if not isinstance(unit_id, str) or not unit_id:
            blockers.append(f"REQUEST_{index:04d}_UNIT_INVALID")
        elif not isinstance(model_key, str) or not model_key:
            blockers.append(f"REQUEST_{index:04d}_MODEL_INVALID")
        elif (unit_id, model_key) in request_pairs:
            blockers.append(f"REQUEST_{index:04d}_UNIT_MODEL_DUPLICATE")
        else:
            request_pairs.add((unit_id, model_key))
            request_units.add(unit_id)
            request_models.add(model_key)
    expected_pairs = {
        (unit_id, model_key)
        for unit_id in request_units
        for model_key in request_models
    }
    if request_pairs != expected_pairs:
        blockers.append("REQUEST_UNIT_MODEL_MATRIX_INCOMPLETE")
    if (
        admission.get("rendered_units") != len(request_units)
        or admission.get("models") != len(request_models)
        or admission.get("requests") != len(request_pairs)
        or not isinstance(admission.get("units"), int)
        or isinstance(admission.get("units"), bool)
        or int(admission.get("units", 0)) < len(request_units)
    ):
        blockers.append("INPUT_ADMISSION_COUNT_RELATION_INVALID")

    status_by_id: dict[str, Mapping[str, Any]] = {}
    used_output_paths: set[str] = set()
    successes = 0
    failures = 0
    aggregate_output_bytes = 0
    for index, row in enumerate(statuses):
        prefix = f"OUTPUT_{index:04d}"
        if set(row) != OUTPUT_FIELDS:
            blockers.append(f"{prefix}_SCHEMA_INVALID")
        request_id = row.get("request_id")
        if not isinstance(request_id, str) or request_id in status_by_id:
            blockers.append(f"{prefix}_IDENTITY_INVALID_OR_DUPLICATE")
            continue
        status_by_id[request_id] = row
        request = request_by_id.get(request_id)
        if request is None:
            blockers.append(f"{prefix}_REQUEST_UNKNOWN")
            continue
        for field in ("unit_id", "model_key", "source_sha256", "render_sha256"):
            if row.get(field) != request.get(field):
                blockers.append(f"{prefix}_{field.upper()}_MISMATCH")
        status = row.get("status")
        if status not in FINAL_STATUSES:
            blockers.append(f"{prefix}_STATUS_INVALID")
        elif status == "SUCCESS":
            successes += 1
            path = _safe_file(output_root, row.get("output_relative_path"))
            relative_output = row.get("output_relative_path")
            if not isinstance(relative_output, str) or relative_output in used_output_paths:
                blockers.append(f"{prefix}_OUTPUT_PATH_INVALID_OR_REUSED")
            else:
                used_output_paths.add(relative_output)
            if path is None or not path.is_file():
                blockers.append(f"{prefix}_OUTPUT_MISSING")
            else:
                actual_output_size = path.stat().st_size
                aggregate_output_bytes += actual_output_size
                if actual_output_size > MAXIMUM_OUTPUT_BYTES:
                    blockers.append(f"{prefix}_OUTPUT_SIZE_LIMIT_EXCEEDED")
                if _streaming_digest(path) != row.get("output_sha256"):
                    blockers.append(f"{prefix}_OUTPUT_DIGEST_MISMATCH")
                if path.stat().st_size != row.get("output_size_bytes"):
                    blockers.append(f"{prefix}_OUTPUT_SIZE_MISMATCH")
                try:
                    envelope = _load_json_value_bounded(
                        path, maximum_bytes=MAXIMUM_OUTPUT_BYTES
                    )
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                    blockers.append(f"{prefix}_OUTPUT_ENVELOPE_INVALID")
                else:
                    if not isinstance(envelope, Mapping):
                        blockers.append(f"{prefix}_OUTPUT_ENVELOPE_SCHEMA_INVALID")
                        continue
                    if set(envelope) != OUTPUT_ENVELOPE_FIELDS:
                        blockers.append(f"{prefix}_OUTPUT_ENVELOPE_SCHEMA_INVALID")
                    expected_envelope = {
                        field: request.get(field)
                        for field in (
                            "request_id",
                            "unit_id",
                            "model_key",
                            "source_sha256",
                            "render_sha256",
                            "router_policy_sha256",
                            "runtime_sha256",
                            "bundle_sha256",
                            "inference_config_sha256",
                            "base_image",
                        )
                    }
                    if any(
                        envelope.get(field) != expected_value
                        for field, expected_value in expected_envelope.items()
                    ):
                        blockers.append(f"{prefix}_OUTPUT_ENVELOPE_BINDING_MISMATCH")
                    if (
                        envelope.get("schema")
                        != "tavonel.router_model_output_envelope.v1"
                        or envelope.get("status") != "SUCCESS"
                    ):
                        blockers.append(f"{prefix}_OUTPUT_ENVELOPE_STATE_INVALID")
            if row.get("error_code") is not None:
                blockers.append(f"{prefix}_SUCCESS_ERROR_CODE_PRESENT")
        else:
            failures += 1
            if any(
                row.get(field) is not None
                for field in (
                    "output_relative_path",
                    "output_sha256",
                    "output_size_bytes",
                )
            ):
                blockers.append(f"{prefix}_FAILURE_OUTPUT_PRESENT")
            if not isinstance(row.get("error_code"), str) or not row.get("error_code"):
                blockers.append(f"{prefix}_FAILURE_ERROR_CODE_REQUIRED")
    if set(status_by_id) != set(request_by_id) or len(statuses) != len(requests):
        blockers.append("OUTPUT_STATUS_DENOMINATOR_MISMATCH")
    if aggregate_output_bytes > MAXIMUM_AGGREGATE_OUTPUT_BYTES:
        blockers.append("OUTPUT_AGGREGATE_SIZE_LIMIT_EXCEEDED")

    seen_attempts: set[str] = set()
    attempted_requests: set[str] = set()
    attempt_outcomes: dict[str, list[tuple[datetime, str]]] = {}
    attempt_started_times: list[datetime] = []
    attempt_completed_times: list[datetime] = []
    provider_observed_times: list[datetime] = []
    estimated_spend = 0.0
    attempt_pods: set[str] = set()
    for index, row in enumerate(attempts):
        prefix = f"ATTEMPT_{index:04d}"
        if set(row) != ATTEMPT_FIELDS:
            blockers.append(f"{prefix}_SCHEMA_INVALID")
        attempt_id = row.get("attempt_id")
        request_id = row.get("request_id")
        if not isinstance(attempt_id, str) or attempt_id in seen_attempts:
            blockers.append(f"{prefix}_IDENTITY_INVALID_OR_DUPLICATE")
        else:
            seen_attempts.add(attempt_id)
        if request_id not in request_by_id:
            blockers.append(f"{prefix}_REQUEST_UNKNOWN")
        else:
            attempted_requests.add(str(request_id))
            if row.get("model_key") != request_by_id[str(request_id)].get("model_key"):
                blockers.append(f"{prefix}_MODEL_MISMATCH")
            if row.get("base_image") != request_by_id[str(request_id)].get("base_image"):
                blockers.append(f"{prefix}_BASE_IMAGE_MISMATCH")
        pod_id = row.get("pod_id")
        if not isinstance(pod_id, str) or not pod_id:
            blockers.append(f"{prefix}_POD_ID_INVALID")
        else:
            attempt_pods.add(pod_id)
        cost = row.get("cost_usd")
        if (
            not isinstance(cost, (int, float))
            or isinstance(cost, bool)
            or not math.isfinite(float(cost))
            or cost < 0
        ):
            blockers.append(f"{prefix}_COST_INVALID")
        else:
            estimated_spend += float(cost)
        receipt = _safe_file(
            provider_receipt_root, row.get("provider_receipt_relative_path")
        )
        if receipt is None or not receipt.is_file():
            blockers.append(f"{prefix}_PROVIDER_RECEIPT_MISSING")
        elif _streaming_digest(receipt) != row.get("provider_receipt_sha256"):
            blockers.append(f"{prefix}_PROVIDER_RECEIPT_DIGEST_MISMATCH")
        else:
            try:
                provider_receipt = load_json(receipt)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                blockers.append(f"{prefix}_PROVIDER_RECEIPT_INVALID")
            else:
                if set(provider_receipt) != PROVIDER_RECEIPT_FIELDS:
                    blockers.append(f"{prefix}_PROVIDER_RECEIPT_SCHEMA_INVALID")
                for field in (
                    "attempt_id",
                    "request_id",
                    "model_key",
                    "pod_id",
                    "status",
                    "started_at_utc",
                    "completed_at_utc",
                    "estimated_cost_usd",
                    "base_image",
                ):
                    attempt_field = (
                        field if field != "estimated_cost_usd" else "cost_usd"
                    )
                    if provider_receipt.get(field) != row.get(attempt_field):
                        blockers.append(f"{prefix}_PROVIDER_{field.upper()}_MISMATCH")
                provider_event = _safe_file(
                    provider_receipt_root,
                    provider_receipt.get("provider_event_relative_path"),
                )
                if provider_event is None or not provider_event.is_file():
                    blockers.append(f"{prefix}_PROVIDER_EVENT_MISSING")
                    provider_event_value: object = None
                elif _streaming_digest(provider_event) != provider_receipt.get(
                    "provider_event_sha256"
                ):
                    blockers.append(f"{prefix}_PROVIDER_EVENT_DIGEST_MISMATCH")
                    provider_event_value = None
                else:
                    try:
                        provider_event_value = _load_json_value_bounded(provider_event)
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        blockers.append(f"{prefix}_PROVIDER_EVENT_INVALID")
                        provider_event_value = None
                started = _utc(provider_receipt.get("started_at_utc"))
                completed = _utc(provider_receipt.get("completed_at_utc"))
                elapsed = provider_receipt.get("elapsed_seconds")
                rate = provider_receipt.get("hourly_rate_usd")
                provider_cost = provider_receipt.get("estimated_cost_usd")
                provider_observed = _utc(
                    provider_receipt.get("provider_observed_at_utc")
                )
                if started is not None:
                    attempt_started_times.append(started)
                if completed is not None:
                    attempt_completed_times.append(completed)
                if provider_observed is not None:
                    provider_observed_times.append(provider_observed)
                canonical_event = (
                    provider_event_value
                    if isinstance(provider_event_value, Mapping)
                    else {}
                )
                event_env_value = canonical_event.get("env")
                event_env = (
                    event_env_value if isinstance(event_env_value, Mapping) else {}
                )
                observed_rate = _runpod_rate(canonical_event)
                event_started = _utc(canonical_event.get("lastStartedAt"))
                request = (
                    request_by_id.get(str(request_id))
                    if isinstance(request_id, str)
                    else None
                )
                expected_name = _expected_pod_name(
                    limits.get("campaign_id"),
                    row.get("model_key"),
                )
                event_endpoint = f"https://rest.runpod.io/v1/pods/{pod_id}"
                event_query: dict[str, object] = {}
                if (
                    provider_receipt.get("schema")
                    != "tavonel.runpod_attempt_receipt.v1"
                    or provider_receipt.get("provider") != "runpod"
                    or provider_receipt.get("provider_event_method") != "GET"
                    or provider_receipt.get("provider_event_endpoint")
                    != event_endpoint
                    or provider_receipt.get("provider_event_query") != event_query
                    or provider_receipt.get("provider_event_request_sha256")
                    != _canonical_request_sha256("GET", event_endpoint, event_query)
                    or provider_receipt.get("provider_event_status_code") != 200
                    or provider_receipt.get("status") not in FINAL_STATUSES
                    or started is None
                    or completed is None
                    or completed < started
                    or provider_observed is None
                    or provider_observed < completed
                    or not isinstance(elapsed, (int, float))
                    or isinstance(elapsed, bool)
                    or not math.isfinite(float(elapsed))
                    or elapsed < 0
                    or abs(elapsed - (completed - started).total_seconds()) > 1
                    or not isinstance(rate, (int, float))
                    or isinstance(rate, bool)
                    or not math.isfinite(float(rate))
                    or rate < 0
                    or observed_rate is None
                    or abs(float(rate) - observed_rate) > 0.000001
                    or not isinstance(provider_cost, (int, float))
                    or isinstance(provider_cost, bool)
                    or not math.isfinite(float(provider_cost))
                    or abs(provider_cost - (float(elapsed) * float(rate) / 3600))
                    > 0.000001
                    or not SHA.fullmatch(
                        str(provider_receipt.get("provider_event_sha256"))
                    )
                    or provider_event_value is None
                    or canonical_event.get("id") != pod_id
                    or canonical_event.get("desiredStatus") != "RUNNING"
                    or canonical_event.get("image") != row.get("base_image")
                    or expected_name is None
                    or canonical_event.get("name") != expected_name
                    or event_env.get("TAVONEL_CAMPAIGN_ID")
                    != limits.get("campaign_id")
                    or event_env.get("TAVONEL_MODEL_KEY") != row.get("model_key")
                    or request is None
                    or event_env.get("TAVONEL_RUNTIME_SHA256")
                    != request.get("runtime_sha256")
                    or event_env.get("TAVONEL_BUNDLE_SHA256")
                    != request.get("bundle_sha256")
                    or event_env.get("TAVONEL_INFERENCE_CONFIG_SHA256")
                    != request.get("inference_config_sha256")
                    or event_started is None
                    or (
                        event_started is not None
                        and started is not None
                        and event_started > started
                    )
                ):
                    blockers.append(f"{prefix}_PROVIDER_RECEIPT_CONTENT_INVALID")
                row_status = row.get("status")
                if (
                    isinstance(request_id, str)
                    and isinstance(row_status, str)
                    and row_status in FINAL_STATUSES
                    and completed is not None
                ):
                    attempt_outcomes.setdefault(request_id, []).append(
                        (completed, row_status)
                    )
    if attempted_requests != set(request_by_id):
        blockers.append("ATTEMPT_REQUEST_DENOMINATOR_MISMATCH")
    for request_id, output in status_by_id.items():
        outcomes = attempt_outcomes.get(request_id, [])
        if not outcomes:
            blockers.append(f"REQUEST_{request_id}_TERMINAL_ATTEMPT_MISSING")
            continue
        latest_time = max(completed for completed, _ in outcomes)
        latest_statuses = {
            status for completed, status in outcomes if completed == latest_time
        }
        if len(latest_statuses) != 1 or output.get("status") not in latest_statuses:
            blockers.append(f"REQUEST_{request_id}_TERMINAL_STATUS_MISMATCH")
    maximum_calls = limits.get("maximum_model_unit_calls")
    maximum_spend = limits.get("maximum_new_gpu_spend_usd")
    maximum_parallel = limits.get("maximum_parallel_pods")
    calls_valid = (
        isinstance(maximum_calls, int)
        and not isinstance(maximum_calls, bool)
        and maximum_calls >= 0
    )
    spend_valid = (
        isinstance(maximum_spend, (int, float))
        and not isinstance(maximum_spend, bool)
        and math.isfinite(float(maximum_spend))
        and maximum_spend >= 0
    )
    parallel_valid = (
        isinstance(maximum_parallel, int)
        and not isinstance(maximum_parallel, bool)
        and maximum_parallel >= 0
    )
    maximum_calls_value = cast(int, maximum_calls) if calls_valid else -1
    maximum_spend_value = cast(float, maximum_spend) if spend_valid else -1.0
    maximum_parallel_value = cast(int, maximum_parallel) if parallel_valid else -1
    if (
        set(limits) != {
            "schema",
            "state",
            "campaign_id",
            "maximum_model_unit_calls",
            "maximum_new_gpu_spend_usd",
            "maximum_parallel_pods",
        }
        or limits.get("schema") != "tavonel.router_execution_limits.v1"
        or limits.get("state") != "FROZEN_BEFORE_EXECUTION"
        or not isinstance(limits.get("campaign_id"), str)
        or not limits.get("campaign_id")
        or not calls_valid
        or maximum_calls_value > 600
        or not spend_valid
        or maximum_spend_value > 20
        or not parallel_valid
        or maximum_parallel_value > 3
    ):
        blockers.append("EXECUTION_HARD_CAP_INVALID")
    if (
        not calls_valid or len(attempts) > maximum_calls_value
    ):
        blockers.append("ATTEMPT_CALL_LIMIT_EXCEEDED")
    if (
        not spend_valid
    ):
        blockers.append("EXECUTION_SPEND_LIMIT_EXCEEDED")

    created = teardown.get("created_pod_ids")
    terminated = teardown.get("terminated_pod_ids")
    live = teardown.get("live_campaign_pod_ids")
    created_list = (
        created
        if isinstance(created, list) and all(isinstance(item, str) for item in created)
        else []
    )
    terminated_list = (
        terminated
        if isinstance(terminated, list)
        and all(isinstance(item, str) for item in terminated)
        else []
    )
    created_set = set(created_list)
    terminated_set = set(terminated_list)
    peak_parallel = teardown.get("peak_parallel_pods")
    if (
        set(teardown) != TEARDOWN_FIELDS
        or teardown.get("schema") != "tavonel.router_pod_teardown.v1"
        or not created_set
        or created_set != terminated_set
        or len(created_set) != len(created_list)
        or len(terminated_set) != len(terminated_list)
        or live != []
        or not attempt_pods.issubset(created_set)
    ):
        blockers.append("POD_TEARDOWN_INCOMPLETE")
    if (
        not isinstance(peak_parallel, int)
        or isinstance(peak_parallel, bool)
        or peak_parallel < 0
        or not parallel_valid
        or peak_parallel > maximum_parallel_value
    ):
        blockers.append("POD_LIMIT_EXCEEDED")
    snapshot = _safe_file(
        provider_snapshot_root, teardown.get("provider_snapshot_relative_path")
    )
    if snapshot is None or not snapshot.is_file():
        blockers.append("PROVIDER_ZERO_POD_SNAPSHOT_MISSING")
    elif _streaming_digest(snapshot) != teardown.get("provider_snapshot_sha256"):
        blockers.append("PROVIDER_ZERO_POD_SNAPSHOT_DIGEST_MISMATCH")
    else:
        try:
            snapshot_value = load_json(snapshot)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            blockers.append("PROVIDER_ZERO_POD_SNAPSHOT_INVALID")
        else:
            snapshot_checked = _utc(snapshot_value.get("checked_at_utc"))
            snapshot_endpoint = "https://rest.runpod.io/v1/pods"
            snapshot_query: dict[str, object] = {}
            if (
                set(snapshot_value) != PROVIDER_SNAPSHOT_FIELDS
                or snapshot_value.get("schema")
                != "tavonel.runpod_campaign_snapshot.v1"
                or snapshot_value.get("provider") != "runpod"
                or snapshot_value.get("campaign_id") != limits.get("campaign_id")
                or snapshot_value.get("live_campaign_pod_ids") != []
                or snapshot_checked is None
                or snapshot_value.get("provider_response_method") != "GET"
                or snapshot_value.get("provider_response_endpoint")
                != snapshot_endpoint
                or snapshot_value.get("provider_response_query") != snapshot_query
                or snapshot_value.get("provider_response_request_sha256")
                != _canonical_request_sha256(
                    "GET", snapshot_endpoint, snapshot_query
                )
                or snapshot_value.get("provider_response_status_code") != 200
                or not SHA.fullmatch(
                    str(snapshot_value.get("provider_response_sha256"))
                )
            ):
                blockers.append("PROVIDER_ZERO_POD_SNAPSHOT_CONTENT_INVALID")
            latest_execution_observation = max(
                (*attempt_completed_times, *provider_observed_times),
                default=None,
            )
            if (
                snapshot_checked is None
                or latest_execution_observation is None
                or snapshot_checked < latest_execution_observation
            ):
                blockers.append("PROVIDER_ZERO_POD_SNAPSHOT_TIME_INVALID")
            response = _safe_file(
                provider_snapshot_root,
                snapshot_value.get("provider_response_relative_path"),
            )
            if response is None or not response.is_file():
                blockers.append("PROVIDER_ZERO_POD_RESPONSE_MISSING")
            elif _streaming_digest(response) != snapshot_value.get(
                "provider_response_sha256"
            ):
                blockers.append("PROVIDER_ZERO_POD_RESPONSE_DIGEST_MISMATCH")
            else:
                try:
                    response_value = _load_json_value_bounded(response)
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                    blockers.append("PROVIDER_ZERO_POD_RESPONSE_INVALID")
                else:
                    if not isinstance(response_value, list) or any(
                        not isinstance(pod, Mapping)
                        or not isinstance(pod.get("id"), str)
                        or pod.get("desiredStatus")
                        not in {"RUNNING", "EXITED", "TERMINATED"}
                        for pod in response_value
                    ):
                        blockers.append("PROVIDER_ZERO_POD_RESPONSE_SCHEMA_INVALID")
                    elif any(
                        pod.get("id") in created_set
                        and pod.get("desiredStatus") != "TERMINATED"
                        for pod in response_value
                        if isinstance(pod, Mapping)
                    ):
                        blockers.append("PROVIDER_ZERO_POD_RESPONSE_NOT_EMPTY")

    billing_receipt = load_json(billing_receipt_path)
    observed_spend = 0.0
    if set(billing_receipt) != BILLING_RECEIPT_FIELDS:
        blockers.append("PROVIDER_BILLING_RECEIPT_SCHEMA_INVALID")
    billing_start = _utc(billing_receipt.get("query_start_utc"))
    billing_end = _utc(billing_receipt.get("query_end_utc"))
    billing_checked = _utc(billing_receipt.get("checked_at_utc"))
    snapshot_checked_for_billing: datetime | None = None
    if snapshot is not None and snapshot.is_file():
        try:
            snapshot_for_billing = _load_json_value_bounded(snapshot)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            snapshot_for_billing = None
        if isinstance(snapshot_for_billing, Mapping):
            snapshot_checked_for_billing = _utc(
                snapshot_for_billing.get("checked_at_utc")
            )
    earliest_execution_start = min(attempt_started_times, default=None)
    latest_execution_observation = max(
        (*attempt_completed_times, *provider_observed_times),
        default=None,
    )
    billing_pods = billing_receipt.get("pod_ids")
    billing_queries = billing_receipt.get("provider_queries")
    if (
        billing_receipt.get("schema") != "tavonel.runpod_billing_receipt.v1"
        or billing_receipt.get("provider") != "runpod"
        or billing_receipt.get("campaign_id") != limits.get("campaign_id")
        or billing_start is None
        or billing_end is None
        or billing_checked is None
        or billing_end < billing_start
        or billing_checked < billing_end
        or earliest_execution_start is None
        or billing_start > earliest_execution_start
        or latest_execution_observation is None
        or billing_end < latest_execution_observation
        or snapshot_checked_for_billing is None
        or billing_end < snapshot_checked_for_billing
        or billing_checked < snapshot_checked_for_billing
        or billing_receipt.get("bucket_size") != "hour"
        or billing_receipt.get("grouping") != "podId"
        or not isinstance(billing_pods, list)
        or any(not isinstance(pod, str) for pod in billing_pods)
        or set(billing_pods) != created_set
        or len(billing_pods) != len(created_set)
        or not isinstance(billing_queries, list)
        or len(billing_queries) != len(created_set)
    ):
        blockers.append("PROVIDER_BILLING_RECEIPT_CONTENT_INVALID")

    covered_pods: set[str] = set()
    queried_pods: set[str] = set()
    if isinstance(billing_queries, list):
        for query_index, query_receipt_value in enumerate(billing_queries):
            prefix = f"PROVIDER_BILLING_QUERY_{query_index:04d}"
            if not isinstance(query_receipt_value, Mapping):
                blockers.append(f"{prefix}_INVALID")
                continue
            query_receipt = query_receipt_value
            query = query_receipt.get("query")
            pod_id = query.get("podId") if isinstance(query, Mapping) else None
            endpoint = "https://rest.runpod.io/v1/billing/pods"
            expected_query = {
                "bucketSize": "hour",
                "endTime": billing_receipt.get("query_end_utc"),
                "podId": pod_id,
                "startTime": billing_receipt.get("query_start_utc"),
            }
            if (
                set(query_receipt) != BILLING_QUERY_FIELDS
                or query_receipt.get("method") != "GET"
                or query_receipt.get("endpoint") != endpoint
                or query != expected_query
                or pod_id not in created_set
                or not isinstance(pod_id, str)
                or pod_id in queried_pods
                or query_receipt.get("request_sha256")
                != _canonical_request_sha256("GET", endpoint, expected_query)
                or query_receipt.get("status_code") != 200
                or query_receipt.get("response_schema")
                not in {
                    "runpod_rest_v1_billing_records_array",
                    "runpod_rest_v1_billing_records_envelope",
                }
                or not SHA.fullmatch(str(query_receipt.get("response_sha256")))
            ):
                blockers.append(f"{prefix}_CONTENT_INVALID")
                continue
            queried_pods.add(pod_id)
            billing_response = _safe_file(
                provider_billing_root,
                query_receipt.get("response_relative_path"),
            )
            if billing_response is None or not billing_response.is_file():
                blockers.append(f"{prefix}_RESPONSE_MISSING")
                continue
            if _streaming_digest(billing_response) != query_receipt.get(
                "response_sha256"
            ):
                blockers.append(f"{prefix}_RESPONSE_DIGEST_MISMATCH")
                continue
            try:
                billing_rows = _load_json_value_bounded(billing_response)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                blockers.append(f"{prefix}_RESPONSE_INVALID")
                continue
            response_schema = query_receipt.get("response_schema")
            envelope_totals: Mapping[str, Any] | None = None
            envelope_unique_count: int | None = None
            if response_schema == "runpod_rest_v1_billing_records_array":
                records = billing_rows if isinstance(billing_rows, list) else None
            elif response_schema == "runpod_rest_v1_billing_records_envelope":
                if (
                    not isinstance(billing_rows, Mapping)
                    or set(billing_rows) != BILLING_ENVELOPE_FIELDS
                    or not isinstance(billing_rows.get("records"), list)
                    or not isinstance(billing_rows.get("metadata"), Mapping)
                ):
                    records = None
                else:
                    metadata = billing_rows["metadata"]
                    assert isinstance(metadata, Mapping)
                    totals = metadata.get("totals")
                    if (
                        set(metadata) != BILLING_METADATA_FIELDS
                        or not isinstance(totals, Mapping)
                        or set(totals) != BILLING_TOTAL_FIELDS
                        or isinstance(metadata.get("recordCount"), bool)
                        or not isinstance(metadata.get("recordCount"), int)
                        or metadata.get("recordCount")
                        != len(billing_rows["records"])
                        or isinstance(metadata.get("uniquePodCount"), bool)
                        or not isinstance(metadata.get("uniquePodCount"), int)
                    ):
                        records = None
                    else:
                        records = billing_rows["records"]
                        envelope_totals = totals
                        envelope_unique_count = metadata["uniquePodCount"]
            else:
                records = None
            if records is None:
                blockers.append(f"{prefix}_RESPONSE_SCHEMA_INVALID")
                continue
            query_spend = 0.0
            query_covered = False
            for record_index, row in enumerate(records):
                row_prefix = f"{prefix}_ROW_{record_index:04d}"
                if not isinstance(row, Mapping):
                    blockers.append(f"{row_prefix}_INVALID")
                    continue
                if not set(row).issubset(BILLING_RECORD_FIELDS) or not {
                    "amount",
                    "podId",
                    "time",
                    "timeBilledMs",
                }.issubset(row):
                    blockers.append(f"{row_prefix}_SCHEMA_INVALID")
                    continue
                amount = row.get("amount")
                time_billed = row.get("timeBilledMs")
                timestamp = _utc(row.get("time"))
                if (
                    row.get("podId") != pod_id
                    or isinstance(amount, bool)
                    or not isinstance(amount, (int, float))
                    or not math.isfinite(float(amount))
                    or amount < 0
                    or isinstance(time_billed, bool)
                    or not isinstance(time_billed, int)
                    or time_billed < 0
                    or timestamp is None
                    or billing_start is None
                    or billing_end is None
                    or not (billing_start <= timestamp <= billing_end)
                ):
                    blockers.append(f"{row_prefix}_CONTENT_INVALID")
                    continue
                query_covered = True
                query_spend += float(amount)
            if query_covered:
                covered_pods.add(pod_id)
            observed_spend += query_spend
            if envelope_totals is not None:
                total_amount = envelope_totals.get("totalAmount")
                if (
                    isinstance(total_amount, bool)
                    or not isinstance(total_amount, (int, float))
                    or not math.isfinite(float(total_amount))
                    or abs(float(total_amount) - query_spend) > 0.000001
                ):
                    blockers.append(f"{prefix}_TOTAL_MISMATCH")
                expected_unique = 1 if query_covered else 0
                if envelope_unique_count != expected_unique:
                    blockers.append(f"{prefix}_UNIQUE_POD_COUNT_MISMATCH")
    if queried_pods != created_set:
        blockers.append("PROVIDER_BILLING_QUERY_DENOMINATOR_MISMATCH")
    if covered_pods != created_set:
        blockers.append("PROVIDER_BILLING_POD_DENOMINATOR_MISMATCH")
    receipt_spend = billing_receipt.get("observed_spend_usd")
    if (
        isinstance(receipt_spend, bool)
        or not isinstance(receipt_spend, (int, float))
        or not math.isfinite(float(receipt_spend))
        or abs(float(receipt_spend) - observed_spend) > 0.000001
    ):
        blockers.append("PROVIDER_BILLING_SPEND_MISMATCH")
    if spend_valid and observed_spend > maximum_spend_value:
        blockers.append("EXECUTION_SPEND_LIMIT_EXCEEDED")
    if estimated_spend + 0.000001 < observed_spend:
        blockers.append("ATTEMPT_COST_ESTIMATE_UNDER_BILLING")

    ordered = tuple(dict.fromkeys(blockers))
    return FinalizationResult(
        passed=not ordered,
        blockers=ordered,
        expected_requests=len(requests),
        final_statuses=len(statuses),
        attempts=len(attempts),
        successes=successes,
        failures_retained=failures,
        spend_usd=round(observed_spend, 8),
        created_pods=len(created_set),
        terminated_pods=len(terminated_set),
        input_digests=input_digests,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    for name in (
        "admission",
        "request-manifest",
        "output-status",
        "output-root",
        "attempt-ledger",
        "provider-receipt-root",
        "teardown",
        "provider-snapshot-root",
        "execution-limits",
        "billing-receipt",
        "provider-billing-root",
        "truth-root",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        for path in (
            args.admission,
            args.request_manifest,
            args.output_status,
            args.attempt_ledger,
            args.teardown,
            args.execution_limits,
            args.billing_receipt,
        ):
            if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError("CONTROL_INPUT_MISSING_OR_OVERSIZED")
        result = evaluate_finalization(
            admission_path=args.admission,
            request_manifest_path=args.request_manifest,
            output_status_path=args.output_status,
            output_root=args.output_root,
            attempt_ledger_path=args.attempt_ledger,
            provider_receipt_root=args.provider_receipt_root,
            teardown_path=args.teardown,
            provider_snapshot_root=args.provider_snapshot_root,
            execution_limits_path=args.execution_limits,
            billing_receipt_path=args.billing_receipt,
            provider_billing_root=args.provider_billing_root,
            truth_root=args.truth_root,
        )
    except Exception as error:  # fail closed at the immutable CLI receipt boundary
        result = FinalizationResult(
            passed=False,
            blockers=(f"FINALIZATION_INPUT_{type(error).__name__.upper()}",),
            expected_requests=0,
            final_statuses=0,
            attempts=0,
            successes=0,
            failures_retained=0,
            spend_usd=0.0,
            created_pods=0,
            terminated_pods=0,
            input_digests={},
        )
    payload = (json.dumps(result.as_dict(), indent=2) + "\n").encode()
    _write_immutable_receipt(args.output, payload)
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
