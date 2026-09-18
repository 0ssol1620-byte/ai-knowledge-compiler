from __future__ import annotations

import json
from pathlib import Path

from . import execution_input_admission
from .finalize_model_execution import (
    _canonical_request_sha256,
    evaluate_finalization,
    main,
)
from .preflight_mixed_holdout import digest


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _world(tmp_path: Path) -> dict[str, Path]:
    outputs = tmp_path / "outputs"
    receipts = tmp_path / "receipts"
    snapshots = tmp_path / "snapshots"
    billing = tmp_path / "billing"
    for root in (outputs, receipts, snapshots, billing):
        root.mkdir(parents=True)

    requests: list[dict[str, object]] = []
    statuses: list[dict[str, object]] = []
    attempts: list[dict[str, object]] = []
    for index, status in enumerate(("SUCCESS", "FAILED")):
        request_id = "sha256:" + str(index + 1) * 64
        request: dict[str, object] = {
            "request_id": request_id,
            "unit_id": f"unit-{index}",
            "model_key": "model-a",
            "source_sha256": "sha256:" + "a" * 64,
            "target_locator": {"page_index": index},
            "render_sha256": "sha256:" + "b" * 64,
            "router_policy_sha256": "sha256:" + "c" * 64,
            "runtime_sha256": "sha256:" + "d" * 64,
            "bundle_sha256": "sha256:" + "e" * 64,
            "inference_config_sha256": "sha256:" + "f" * 64,
            "base_image": "example/image@sha256:" + "7" * 64,
        }
        requests.append(request)
        if status == "SUCCESS":
            output_path = outputs / f"{index}.json"
            envelope = {
                "schema": "tavonel.router_model_output_envelope.v1",
                **{
                    field: request[field]
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
                },
                "status": "SUCCESS",
                "model_output": {"text": "truth-free model output"},
            }
            _write_json(output_path, envelope)
            relative: str | None = output_path.name
            output_hash: str | None = digest(output_path.read_bytes())
            output_size: int | None = output_path.stat().st_size
            error: str | None = None
        else:
            relative = None
            output_hash = None
            output_size = None
            error = "MODEL_FAILED"
        statuses.append(
            {
                **{
                    field: request[field]
                    for field in (
                        "request_id",
                        "unit_id",
                        "model_key",
                        "source_sha256",
                        "render_sha256",
                    )
                },
                "status": status,
                "output_relative_path": relative,
                "output_sha256": output_hash,
                "output_size_bytes": output_size,
                "error_code": error,
            }
        )
        started = "2026-09-10T00:00:00Z"
        completed = "2026-09-10T00:00:01Z"
        cost = 0.01
        event_path = receipts / f"{index}.provider-event.json"
        _write_json(
            event_path,
            {
                "id": "pod-1",
                "name": "tavonel-router-holdout-test-model-a",
                "desiredStatus": "RUNNING",
                "adjustedCostPerHr": 36,
                "image": "example/image@sha256:" + "7" * 64,
                "lastStartedAt": "2026-09-10T00:00:00Z",
                "env": {
                    "TAVONEL_CAMPAIGN_ID": "holdout-test",
                    "TAVONEL_MODEL_KEY": "model-a",
                    "TAVONEL_RUNTIME_SHA256": request["runtime_sha256"],
                    "TAVONEL_BUNDLE_SHA256": request["bundle_sha256"],
                    "TAVONEL_INFERENCE_CONFIG_SHA256": request[
                        "inference_config_sha256"
                    ],
                },
            },
        )
        receipt_path = receipts / f"{index}.json"
        _write_json(
            receipt_path,
            {
                "schema": "tavonel.runpod_attempt_receipt.v1",
                "provider": "runpod",
                "attempt_id": f"attempt-{index}",
                "request_id": request_id,
                "model_key": "model-a",
                "pod_id": "pod-1",
                "status": status,
                "started_at_utc": started,
                "completed_at_utc": completed,
                "elapsed_seconds": 1,
                "hourly_rate_usd": 36,
                "estimated_cost_usd": cost,
                "provider_observed_at_utc": completed,
                "provider_event_method": "GET",
                "provider_event_endpoint": (
                    "https://rest.runpod.io/v1/pods/pod-1"
                ),
                "provider_event_query": {},
                "provider_event_request_sha256": _canonical_request_sha256(
                    "GET", "https://rest.runpod.io/v1/pods/pod-1", {}
                ),
                "provider_event_status_code": 200,
                "base_image": request["base_image"],
                "provider_event_relative_path": event_path.name,
                "provider_event_sha256": digest(event_path.read_bytes()),
            },
        )
        attempts.append(
            {
                "attempt_id": f"attempt-{index}",
                "request_id": request_id,
                "model_key": "model-a",
                "pod_id": "pod-1",
                "started_at_utc": started,
                "completed_at_utc": completed,
                "status": status,
                "cost_usd": cost,
                "provider_receipt_relative_path": receipt_path.name,
                "provider_receipt_sha256": digest(receipt_path.read_bytes()),
                "base_image": request["base_image"],
            }
        )

    request_path = tmp_path / "requests.jsonl"
    status_path = tmp_path / "statuses.jsonl"
    attempt_path = tmp_path / "attempts.jsonl"
    _write_jsonl(request_path, requests)
    _write_jsonl(status_path, statuses)
    _write_jsonl(attempt_path, attempts)
    limits_path = tmp_path / "limits.json"
    _write_json(
        limits_path,
        {
            "schema": "tavonel.router_execution_limits.v1",
            "state": "FROZEN_BEFORE_EXECUTION",
            "campaign_id": "holdout-test",
            "maximum_model_unit_calls": 2,
            "maximum_new_gpu_spend_usd": 1,
            "maximum_parallel_pods": 1,
        },
    )
    truth_root = tmp_path / "truth"
    admission_path = tmp_path / "admission.json"
    _write_json(
        admission_path,
        {
            "schema": "tavonel.router_execution_input_admission.v1",
            "passed": True,
            "blockers": [],
            "units": 2,
            "rendered_units": 2,
            "models": 1,
            "requests": 2,
            "input_digests": {
                key: (
                    digest(request_path.read_bytes())
                    if key == "request_manifest"
                    else digest(limits_path.read_bytes())
                    if key == "execution_limits"
                    else digest(str(truth_root.resolve()).encode())
                    if key == "truth_root_path"
                    else "sha256:" + "9" * 64
                )
                for key in execution_input_admission.ADMISSION_INPUT_DIGEST_FIELDS
            },
            "gate_sha256": digest(
                Path(execution_input_admission.__file__).read_bytes()
            ),
            "actual_source_bytes_verified": True,
            "actual_render_bytes_verified": True,
            "actual_model_artifact_bytes_verified": True,
            "truth_opened": False,
            "model_calls_before_admission": 0,
            "model_call_authorized": True,
            "production_promotion": False,
        },
    )

    provider_snapshot = snapshots / "zero.json"
    provider_response = snapshots / "zero.provider-response.json"
    _write_json(provider_response, [])
    _write_json(
        provider_snapshot,
        {
            "schema": "tavonel.runpod_campaign_snapshot.v1",
            "provider": "runpod",
            "campaign_id": "holdout-test",
            "checked_at_utc": "2026-09-10T00:01:00Z",
            "live_campaign_pod_ids": [],
            "provider_response_method": "GET",
            "provider_response_endpoint": "https://rest.runpod.io/v1/pods",
            "provider_response_query": {},
            "provider_response_request_sha256": _canonical_request_sha256(
                "GET", "https://rest.runpod.io/v1/pods", {}
            ),
            "provider_response_status_code": 200,
            "provider_response_relative_path": provider_response.name,
            "provider_response_sha256": digest(provider_response.read_bytes()),
        },
    )
    teardown_path = tmp_path / "teardown.json"
    _write_json(
        teardown_path,
        {
            "schema": "tavonel.router_pod_teardown.v1",
            "created_pod_ids": ["pod-1"],
            "terminated_pod_ids": ["pod-1"],
            "live_campaign_pod_ids": [],
            "peak_parallel_pods": 1,
            "provider_snapshot_relative_path": provider_snapshot.name,
            "provider_snapshot_sha256": digest(provider_snapshot.read_bytes()),
        },
    )
    billing_response = billing / "campaign-billing-response.json"
    _write_json(
        billing_response,
        {
            "records": [
                {
                    "amount": 0.02,
                    "diskSpaceBilledGb": 0,
                    "endpointId": None,
                    "gpuTypeId": "test-gpu",
                    "podId": "pod-1",
                    "time": "2026-09-10T00:00:00Z",
                    "timeBilledMs": 2000,
                }
            ],
            "metadata": {
                "recordCount": 1,
                "uniquePodCount": 1,
                "totals": {
                    "totalAmount": 0.02,
                    "gpuAmount": 0.02,
                    "diskAmount": 0,
                },
            },
        },
    )
    billing_receipt = tmp_path / "billing-receipt.json"
    _write_json(
        billing_receipt,
        {
            "schema": "tavonel.runpod_billing_receipt.v1",
            "provider": "runpod",
            "campaign_id": "holdout-test",
            "query_start_utc": "2026-09-10T00:00:00Z",
            "query_end_utc": "2026-09-10T00:01:00Z",
            "bucket_size": "hour",
            "grouping": "podId",
            "pod_ids": ["pod-1"],
            "checked_at_utc": "2026-09-10T00:02:00Z",
            "provider_queries": [
                {
                    "method": "GET",
                    "endpoint": "https://rest.runpod.io/v1/billing/pods",
                    "query": {
                        "bucketSize": "hour",
                        "endTime": "2026-09-10T00:01:00Z",
                        "podId": "pod-1",
                        "startTime": "2026-09-10T00:00:00Z",
                    },
                    "request_sha256": _canonical_request_sha256(
                        "GET",
                        "https://rest.runpod.io/v1/billing/pods",
                        {
                            "bucketSize": "hour",
                            "endTime": "2026-09-10T00:01:00Z",
                            "podId": "pod-1",
                            "startTime": "2026-09-10T00:00:00Z",
                        },
                    ),
                    "status_code": 200,
                    "response_schema": (
                        "runpod_rest_v1_billing_records_envelope"
                    ),
                    "response_relative_path": billing_response.name,
                    "response_sha256": digest(billing_response.read_bytes()),
                }
            ],
            "observed_spend_usd": 0.02,
        },
    )
    return {
        "admission_path": admission_path,
        "request_manifest_path": request_path,
        "output_status_path": status_path,
        "output_root": outputs,
        "attempt_ledger_path": attempt_path,
        "provider_receipt_root": receipts,
        "teardown_path": teardown_path,
        "provider_snapshot_root": snapshots,
        "execution_limits_path": limits_path,
        "billing_receipt_path": billing_receipt,
        "provider_billing_root": billing,
        "truth_root": truth_root,
    }


def test_complete_denominator_with_retained_failure_passes(tmp_path: Path) -> None:
    result = evaluate_finalization(**_world(tmp_path))
    assert result.passed
    assert result.successes == 1
    assert result.failures_retained == 1


def test_missing_status_or_attempt_fails_closed(tmp_path: Path) -> None:
    world = _world(tmp_path / "status")
    rows = world["output_status_path"].read_text().splitlines()
    world["output_status_path"].write_text(rows[0] + "\n")
    assert "OUTPUT_STATUS_DENOMINATOR_MISMATCH" in evaluate_finalization(
        **world
    ).blockers
    world = _world(tmp_path / "attempt")
    rows = world["attempt_ledger_path"].read_text().splitlines()
    world["attempt_ledger_path"].write_text(rows[0] + "\n")
    assert "ATTEMPT_REQUEST_DENOMINATOR_MISMATCH" in evaluate_finalization(
        **world
    ).blockers


def test_output_drift_and_incomplete_teardown_fail_closed(tmp_path: Path) -> None:
    world = _world(tmp_path / "output")
    (world["output_root"] / "0.json").write_bytes(b"drift")
    assert "OUTPUT_0000_OUTPUT_DIGEST_MISMATCH" in evaluate_finalization(
        **world
    ).blockers
    world = _world(tmp_path / "teardown")
    teardown = json.loads(world["teardown_path"].read_text())
    teardown["live_campaign_pod_ids"] = ["pod-1"]
    _write_json(world["teardown_path"], teardown)
    assert "POD_TEARDOWN_INCOMPLETE" in evaluate_finalization(**world).blockers


def test_truth_and_spend_fail_closed(tmp_path: Path) -> None:
    world = _world(tmp_path / "truth")
    world["truth_root"].mkdir()
    (world["truth_root"] / "truth.json").write_text("{}")
    assert "HOLDOUT_TRUTH_OPENED_BEFORE_FINALIZATION" in evaluate_finalization(
        **world
    ).blockers
    world = _world(tmp_path / "spend")
    attempts = [
        json.loads(line)
        for line in world["attempt_ledger_path"].read_text().splitlines()
    ]
    attempts[0]["cost_usd"] = 2
    _write_jsonl(world["attempt_ledger_path"], attempts)
    assert "ATTEMPT_0000_PROVIDER_ESTIMATED_COST_USD_MISMATCH" in evaluate_finalization(
        **world
    ).blockers


def test_forged_admission_or_raised_hard_cap_fails_closed(tmp_path: Path) -> None:
    world = _world(tmp_path / "admission")
    admission = json.loads(world["admission_path"].read_text())
    admission["actual_render_bytes_verified"] = False
    _write_json(world["admission_path"], admission)
    assert "INPUT_ADMISSION_INVALID" in evaluate_finalization(**world).blockers
    world = _world(tmp_path / "incomplete-digests")
    admission = json.loads(world["admission_path"].read_text())
    admission["input_digests"] = {
        key: admission["input_digests"][key]
        for key in ("request_manifest", "execution_limits", "truth_root_path")
    }
    admission["units"] = 999
    admission["rendered_units"] = 999
    admission["models"] = 999
    _write_json(world["admission_path"], admission)
    result = evaluate_finalization(**world)
    assert "INPUT_ADMISSION_DIGEST_SCHEMA_INVALID" in result.blockers
    assert "INPUT_ADMISSION_COUNT_RELATION_INVALID" in result.blockers
    world = _world(tmp_path / "limits")
    limits = json.loads(world["execution_limits_path"].read_text())
    limits["maximum_new_gpu_spend_usd"] = 21
    _write_json(world["execution_limits_path"], limits)
    assert "EXECUTION_HARD_CAP_INVALID" in evaluate_finalization(**world).blockers


def test_output_reuse_and_unbound_envelope_fail_closed(tmp_path: Path) -> None:
    world = _world(tmp_path / "reuse")
    statuses = [
        json.loads(line)
        for line in world["output_status_path"].read_text().splitlines()
    ]
    statuses[1]["status"] = "SUCCESS"
    statuses[1]["output_relative_path"] = statuses[0]["output_relative_path"]
    statuses[1]["output_sha256"] = statuses[0]["output_sha256"]
    statuses[1]["output_size_bytes"] = statuses[0]["output_size_bytes"]
    statuses[1]["error_code"] = None
    _write_jsonl(world["output_status_path"], statuses)
    assert "OUTPUT_0001_OUTPUT_PATH_INVALID_OR_REUSED" in evaluate_finalization(
        **world
    ).blockers
    world = _world(tmp_path / "binding")
    output = world["output_root"] / "0.json"
    envelope = json.loads(output.read_text())
    envelope["unit_id"] = "other-unit"
    _write_json(output, envelope)
    statuses = [
        json.loads(line)
        for line in world["output_status_path"].read_text().splitlines()
    ]
    statuses[0]["output_sha256"] = digest(output.read_bytes())
    statuses[0]["output_size_bytes"] = output.stat().st_size
    _write_jsonl(world["output_status_path"], statuses)
    assert "OUTPUT_0000_OUTPUT_ENVELOPE_BINDING_MISMATCH" in evaluate_finalization(
        **world
    ).blockers


def test_opaque_receipt_and_malformed_teardown_fail_closed(tmp_path: Path) -> None:
    world = _world(tmp_path / "receipt")
    receipt = world["provider_receipt_root"] / "0.json"
    _write_json(receipt, {})
    attempts = [
        json.loads(line)
        for line in world["attempt_ledger_path"].read_text().splitlines()
    ]
    attempts[0]["provider_receipt_sha256"] = digest(receipt.read_bytes())
    _write_jsonl(world["attempt_ledger_path"], attempts)
    assert "ATTEMPT_0000_PROVIDER_RECEIPT_SCHEMA_INVALID" in evaluate_finalization(
        **world
    ).blockers
    world = _world(tmp_path / "malformed")
    teardown = json.loads(world["teardown_path"].read_text())
    teardown["created_pod_ids"] = {"pod-1": True}
    _write_json(world["teardown_path"], teardown)
    assert "POD_TEARDOWN_INCOMPLETE" in evaluate_finalization(**world).blockers


def test_output_and_terminal_attempt_status_must_match(tmp_path: Path) -> None:
    world = _world(tmp_path)
    attempts = [
        json.loads(line)
        for line in world["attempt_ledger_path"].read_text().splitlines()
    ]
    attempts[0]["status"] = "FAILED"
    receipt = world["provider_receipt_root"] / "0.json"
    receipt_value = json.loads(receipt.read_text())
    receipt_value["status"] = "FAILED"
    _write_json(receipt, receipt_value)
    attempts[0]["provider_receipt_sha256"] = digest(receipt.read_bytes())
    _write_jsonl(world["attempt_ledger_path"], attempts)
    result = evaluate_finalization(**world)
    assert any(blocker.endswith("_TERMINAL_STATUS_MISMATCH") for blocker in result.blockers)


def test_provider_event_and_zero_pod_response_bytes_are_bound(tmp_path: Path) -> None:
    world = _world(tmp_path / "event")
    (world["provider_receipt_root"] / "0.provider-event.json").write_text("{}\n")
    assert "ATTEMPT_0000_PROVIDER_EVENT_DIGEST_MISMATCH" in evaluate_finalization(
        **world
    ).blockers

    world = _world(tmp_path / "snapshot")
    response = world["provider_snapshot_root"] / "zero.provider-response.json"
    _write_json(
        response,
        [
            {
                "id": "pod-1",
                "desiredStatus": "RUNNING",
            }
        ],
    )
    snapshot = json.loads(
        (world["provider_snapshot_root"] / "zero.json").read_text()
    )
    snapshot["provider_response_sha256"] = digest(response.read_bytes())
    _write_json(world["provider_snapshot_root"] / "zero.json", snapshot)
    teardown = json.loads(world["teardown_path"].read_text())
    teardown["provider_snapshot_sha256"] = digest(
        (world["provider_snapshot_root"] / "zero.json").read_bytes()
    )
    _write_json(world["teardown_path"], teardown)
    assert "PROVIDER_ZERO_POD_RESPONSE_NOT_EMPTY" in evaluate_finalization(
        **world
    ).blockers


def test_snapshot_endpoint_and_execution_time_order_are_bound(tmp_path: Path) -> None:
    world = _world(tmp_path / "stale")
    snapshot_path = world["provider_snapshot_root"] / "zero.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["checked_at_utc"] = "2020-01-01T00:00:00Z"
    snapshot["provider_response_endpoint"] = "https://rest.runpod.io/v1/pods/pod-1"
    _write_json(snapshot_path, snapshot)
    teardown = json.loads(world["teardown_path"].read_text())
    teardown["provider_snapshot_sha256"] = digest(snapshot_path.read_bytes())
    _write_json(world["teardown_path"], teardown)

    result = evaluate_finalization(**world)

    assert "PROVIDER_ZERO_POD_SNAPSHOT_CONTENT_INVALID" in result.blockers
    assert "PROVIDER_ZERO_POD_SNAPSHOT_TIME_INVALID" in result.blockers


def test_billing_window_must_cover_execution_and_zero_pod_snapshot(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    receipt = json.loads(world["billing_receipt_path"].read_text())
    receipt["query_start_utc"] = "2020-01-01T00:00:00Z"
    receipt["query_end_utc"] = "2020-01-01T01:00:00Z"
    receipt["checked_at_utc"] = "2020-01-01T02:00:00Z"
    response = world["provider_billing_root"] / "campaign-billing-response.json"
    payload = json.loads(response.read_text())
    payload["records"][0]["time"] = "2020-01-01T00:00:00Z"
    _write_json(response, payload)
    receipt["provider_queries"][0]["response_sha256"] = digest(
        response.read_bytes()
    )
    _write_json(world["billing_receipt_path"], receipt)

    result = evaluate_finalization(**world)

    assert "PROVIDER_BILLING_RECEIPT_CONTENT_INVALID" in result.blockers


def test_provider_event_requires_canonical_runpod_pod_schema(tmp_path: Path) -> None:
    world = _world(tmp_path)
    event = world["provider_receipt_root"] / "0.provider-event.json"
    _write_json(event, {"arbitrary": "pod-1"})
    receipt = world["provider_receipt_root"] / "0.json"
    receipt_value = json.loads(receipt.read_text())
    receipt_value["provider_event_sha256"] = digest(event.read_bytes())
    _write_json(receipt, receipt_value)
    attempts = [
        json.loads(line)
        for line in world["attempt_ledger_path"].read_text().splitlines()
    ]
    attempts[0]["provider_receipt_sha256"] = digest(receipt.read_bytes())
    _write_jsonl(world["attempt_ledger_path"], attempts)

    result = evaluate_finalization(**world)

    assert "ATTEMPT_0000_PROVIDER_RECEIPT_CONTENT_INVALID" in result.blockers


def test_provider_event_binds_campaign_model_and_artifact_identities(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    event = world["provider_receipt_root"] / "0.provider-event.json"
    event_value = json.loads(event.read_text())
    event_value["name"] = "tavonel-router-wrong-campaign-model-a"
    event_value["env"]["TAVONEL_CAMPAIGN_ID"] = "wrong-campaign"
    event_value["env"]["TAVONEL_BUNDLE_SHA256"] = "sha256:" + "0" * 64
    _write_json(event, event_value)
    receipt = world["provider_receipt_root"] / "0.json"
    receipt_value = json.loads(receipt.read_text())
    receipt_value["provider_event_sha256"] = digest(event.read_bytes())
    _write_json(receipt, receipt_value)
    attempts = [
        json.loads(line)
        for line in world["attempt_ledger_path"].read_text().splitlines()
    ]
    attempts[0]["provider_receipt_sha256"] = digest(receipt.read_bytes())
    _write_jsonl(world["attempt_ledger_path"], attempts)

    result = evaluate_finalization(**world)

    assert "ATTEMPT_0000_PROVIDER_RECEIPT_CONTENT_INVALID" in result.blockers


def test_provider_http_method_status_and_request_digest_are_bound(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path / "attempt")
    receipt = world["provider_receipt_root"] / "0.json"
    value = json.loads(receipt.read_text())
    value["provider_event_method"] = "POST"
    value["provider_event_status_code"] = 201
    value["provider_event_request_sha256"] = "sha256:" + "0" * 64
    _write_json(receipt, value)
    attempts = [
        json.loads(line)
        for line in world["attempt_ledger_path"].read_text().splitlines()
    ]
    attempts[0]["provider_receipt_sha256"] = digest(receipt.read_bytes())
    _write_jsonl(world["attempt_ledger_path"], attempts)
    result = evaluate_finalization(**world)
    assert "ATTEMPT_0000_PROVIDER_RECEIPT_CONTENT_INVALID" in result.blockers

    world = _world(tmp_path / "snapshot")
    snapshot = world["provider_snapshot_root"] / "zero.json"
    value = json.loads(snapshot.read_text())
    value["provider_response_status_code"] = 500
    _write_json(snapshot, value)
    teardown = json.loads(world["teardown_path"].read_text())
    teardown["provider_snapshot_sha256"] = digest(snapshot.read_bytes())
    _write_json(world["teardown_path"], teardown)
    result = evaluate_finalization(**world)
    assert "PROVIDER_ZERO_POD_SNAPSHOT_CONTENT_INVALID" in result.blockers


def test_billing_query_exactly_binds_method_status_parameters_and_response(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    receipt = json.loads(world["billing_receipt_path"].read_text())
    query = receipt["provider_queries"][0]
    query["query"]["podId"] = "pod-other"
    query["status_code"] = 500
    query["request_sha256"] = "sha256:" + "0" * 64
    _write_json(world["billing_receipt_path"], receipt)
    result = evaluate_finalization(**world)
    assert "PROVIDER_BILLING_QUERY_0000_CONTENT_INVALID" in result.blockers
    assert "PROVIDER_BILLING_QUERY_DENOMINATOR_MISMATCH" in result.blockers


def test_official_openapi_billing_array_is_explicitly_bound(tmp_path: Path) -> None:
    world = _world(tmp_path)
    response = world["provider_billing_root"] / "campaign-billing-response.json"
    payload = json.loads(response.read_text())
    _write_json(response, payload["records"])
    receipt = json.loads(world["billing_receipt_path"].read_text())
    receipt["provider_queries"][0]["response_schema"] = (
        "runpod_rest_v1_billing_records_array"
    )
    receipt["provider_queries"][0]["response_sha256"] = digest(
        response.read_bytes()
    )
    _write_json(world["billing_receipt_path"], receipt)

    result = evaluate_finalization(**world)

    assert result.passed, result.blockers


def test_provider_billing_is_authoritative_for_spend(tmp_path: Path) -> None:
    world = _world(tmp_path)
    response = world["provider_billing_root"] / "campaign-billing-response.json"
    payload = json.loads(response.read_text())
    payload["records"][0]["amount"] = 2
    payload["metadata"]["totals"]["totalAmount"] = 2
    _write_json(response, payload)
    receipt = json.loads(world["billing_receipt_path"].read_text())
    receipt["provider_queries"][0]["response_sha256"] = digest(
        response.read_bytes()
    )
    receipt["observed_spend_usd"] = 2
    _write_json(world["billing_receipt_path"], receipt)

    result = evaluate_finalization(**world)

    assert "EXECUTION_SPEND_LIMIT_EXCEEDED" in result.blockers
    assert result.spend_usd == 2


def test_alternate_truth_path_and_malformed_limits_fail_closed(tmp_path: Path) -> None:
    world = _world(tmp_path / "truth-path")
    world["truth_root"] = tmp_path / "other-truth"
    assert "TRUTH_ROOT_ADMISSION_MISMATCH" in evaluate_finalization(**world).blockers
    world = _world(tmp_path / "bad-limits")
    limits = json.loads(world["execution_limits_path"].read_text())
    limits["maximum_model_unit_calls"] = "600"
    _write_json(world["execution_limits_path"], limits)
    result = evaluate_finalization(**world)
    assert "EXECUTION_HARD_CAP_INVALID" in result.blockers
    assert "ATTEMPT_CALL_LIMIT_EXCEEDED" in result.blockers


def test_cli_malformed_json_writes_immutable_failure_receipt(tmp_path: Path) -> None:
    world = _world(tmp_path)
    world["admission_path"].write_text("{truncated", encoding="utf-8")
    output = tmp_path / "finalization.json"
    argv: list[str] = []
    argument_names = {
        "admission": "admission_path",
        "request-manifest": "request_manifest_path",
        "output-status": "output_status_path",
        "output-root": "output_root",
        "attempt-ledger": "attempt_ledger_path",
        "provider-receipt-root": "provider_receipt_root",
        "teardown": "teardown_path",
        "provider-snapshot-root": "provider_snapshot_root",
        "execution-limits": "execution_limits_path",
        "billing-receipt": "billing_receipt_path",
        "provider-billing-root": "provider_billing_root",
        "truth-root": "truth_root",
    }
    for argument, key in argument_names.items():
        argv.extend([f"--{argument}", str(world[key])])
    argv.extend(["--output", str(output)])

    assert main(argv) == 2
    receipt = json.loads(output.read_text())
    assert receipt["passed"] is False
    assert receipt["blockers"] == ["FINALIZATION_INPUT_JSONDECODEERROR"]
