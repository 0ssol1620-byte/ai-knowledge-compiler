from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from benchmark.v6.contracts import ContractError
from infra.runpod.v6.cli import main as runpod_cli
from infra.runpod.v6.client import (
    BillingHistory,
    BillingQuery,
    DryRunReceipt,
    EndpointCreateSpec,
    EndpointSummary,
    OrphanAuditReceipt,
    ProviderAbsenceReceipt,
    QueueJob,
    RunPodClientError,
    RunPodProtocolError,
    RunPodV2Client,
    ScalingPolicy,
    WorkerBounds,
    make_idempotency_key,
)

RUN_TAG = "v6-cohort-client-test"
IMAGE = "registry.example/worker@sha256:" + ("a" * 64)


def _endpoint(
    endpoint_id: str = "ep-test",
    *,
    workers: tuple[int, int] = (0, 3),
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "id": endpoint_id,
        "name": "structara-test",
        "type": "QUEUE",
        "requestUrls": {
            "run": f"https://api.runpod.ai/v2/{endpoint_id}/run",
            "runSync": f"https://api.runpod.ai/v2/{endpoint_id}/runsync",
            "status": f"https://api.runpod.ai/v2/{endpoint_id}/status/{{job_id}}",
            "stream": f"https://api.runpod.ai/v2/{endpoint_id}/stream/{{job_id}}",
            "cancel": f"https://api.runpod.ai/v2/{endpoint_id}/cancel/{{job_id}}",
            "retry": f"https://api.runpod.ai/v2/{endpoint_id}/retry/{{job_id}}",
            "purgeQueue": f"https://api.runpod.ai/v2/{endpoint_id}/purge-queue",
            "health": f"https://api.runpod.ai/v2/{endpoint_id}/health",
        },
        "image": IMAGE,
        "args": "",
        "disk": 20,
        "ports": [],
        "env": env or {"STRUCTARA_RUN_TAG": RUN_TAG},
        "registry": None,
        "gpu": {"pools": ["ADA_24"], "count": 1},
        "cpu": None,
        "workers": {"min": workers[0], "max": workers[1], "idleTimeout": 300},
        "scaling": {"type": "QUEUE_DELAY", "queueDelay": 4},
        "dataCenterIds": [],
        "networkVolumes": [],
        "timeout": 300000,
        "flashboot": "OFF",
        "createdAt": "2026-08-01T00:00:00Z",
    }


def _spec() -> EndpointCreateSpec:
    return EndpointCreateSpec(
        name="structara-test",
        image=IMAGE,
        gpu_pools=("ADA_24",),
        run_tag=RUN_TAG,
    )


def test_client_is_network_free_and_does_not_require_a_key_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    calls = 0

    def forbidden(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("dry-run attempted network access")

    client = RunPodV2Client(execute=False, transport=httpx.MockTransport(forbidden))
    key = make_idempotency_key({"test": "dry"})
    receipts = (
        client.inventory_endpoints(),
        client.create_endpoint(_spec(), idempotency_key=key),
        client.drain_endpoint("ep-test", run_tag=RUN_TAG, idempotency_key=key),
        client.delete_endpoint(
            "ep-test",
            confirmation_endpoint_id="ep-test",
            run_tag=RUN_TAG,
            idempotency_key=key,
        ),
        client.run_job(
            "ep-test", {"document": "manifest"}, run_tag=RUN_TAG, idempotency_key=key
        ),
        client.job_status("ep-test", "job-test"),
        client.cancel_job(
            "ep-test", "job-test", run_tag=RUN_TAG, idempotency_key=key
        ),
        client.billing_history(BillingQuery()),
    )

    assert calls == 0
    assert all(isinstance(item, DryRunReceipt) for item in receipts)
    assert "RUNPOD_API_KEY" not in repr(client)


def test_execute_requires_only_runpod_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    with pytest.raises(ContractError, match="RUNPOD_API_KEY"):
        RunPodV2Client(execute=True)


def test_management_queue_and_billing_operations_follow_documented_v2_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = "provider-key-must-never-appear"
    monkeypatch.setenv("RUNPOD_API_KEY", credential)
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {credential}"
        requests.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/v2/serverless":
            return httpx.Response(
                200,
                json={"endpoints": [_endpoint()]},
                headers={"content-type": "application/json"},
            )
        if request.method == "POST" and request.url.path == "/v2/serverless":
            assert request.headers["idempotency-key"].startswith("idem-")
            assert request.headers["x-structara-run-tag"] == RUN_TAG
            body = json.loads(request.content)
            assert body["type"] == "QUEUE"
            assert body["workers"] == {"min": 0, "max": 3, "idleTimeout": 300}
            assert body["scaling"] == {"type": "QUEUE_DELAY", "queueDelay": 4.0}
            return httpx.Response(
                201,
                json=_endpoint(),
                headers={"content-type": "application/json"},
            )
        if request.method == "PATCH" and request.url.path == "/v2/serverless/ep-test":
            body = json.loads(request.content)
            workers = (body["workers"]["min"], body["workers"]["max"])
            return httpx.Response(
                200,
                json=_endpoint(workers=workers),
                headers={"content-type": "application/json"},
            )
        if request.method == "DELETE" and request.url.path == "/v2/serverless/ep-test":
            return httpx.Response(204)
        if request.method == "GET" and request.url.path == "/v2/serverless/ep-test":
            return httpx.Response(404, json={"title": "Not Found"})
        if request.method == "POST" and request.url.path == "/v2/ep-test/run":
            assert json.loads(request.content) == {"input": {"document": "manifest"}}
            return httpx.Response(
                200,
                json={"id": "job-test", "status": "IN_QUEUE"},
                headers={"content-type": "application/json"},
            )
        if request.method == "GET" and request.url.path == "/v2/ep-test/status/job-test":
            return httpx.Response(
                200,
                json={"id": "job-test", "status": "COMPLETED", "output": {"ok": True}},
                headers={"content-type": "application/json"},
            )
        if request.method == "POST" and request.url.path == "/v2/ep-test/cancel/job-test":
            return httpx.Response(
                200,
                json={"id": "job-test", "status": "CANCELLED"},
                headers={"content-type": "application/json"},
            )
        if request.method == "GET" and request.url.path == "/v2/billing/serverless":
            return httpx.Response(
                200,
                json={
                    "records": [
                        {
                            "serverlessId": "ep-test",
                            "startTime": "2026-08-01T00:00:00Z",
                            "endTime": "2026-08-02T00:00:00Z",
                            "totalAmount": 3.25,
                            "gpuAmount": 3,
                            "cpuAmount": 0,
                            "diskAmount": 0.2,
                            "feeAmount": 0.05,
                        }
                    ],
                    "metadata": {
                        "query": {
                            "startTime": "2026-08-01T00:00:00Z",
                            "endTime": "2026-08-02T00:00:00Z",
                            "bucketSize": "day",
                            "serverlessId": "ep-test",
                        },
                        "recordCount": 1,
                        "uniqueServerlessCount": 1,
                        "totals": {
                            "totalAmount": 3.25,
                            "gpuAmount": 3,
                            "cpuAmount": 0,
                            "diskAmount": 0.2,
                            "feeAmount": 0.05,
                        },
                    },
                },
                headers={"content-type": "application/json"},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    key = make_idempotency_key({"operation": "client-test"})
    with RunPodV2Client(
        execute=True, transport=httpx.MockTransport(handler)
    ) as client:
        inventory = client.inventory_endpoints()
        created = client.create_endpoint(_spec(), idempotency_key=key)
        drained = client.drain_endpoint("ep-test", run_tag=RUN_TAG, idempotency_key=key)
        deleted = client.delete_endpoint(
            "ep-test",
            confirmation_endpoint_id="ep-test",
            run_tag=RUN_TAG,
            idempotency_key=key,
        )
        absence = client.verify_endpoint_absent("ep-test")
        queued = client.run_job(
            "ep-test", {"document": "manifest"}, run_tag=RUN_TAG, idempotency_key=key
        )
        completed = client.job_status("ep-test", "job-test")
        cancelled = client.cancel_job(
            "ep-test", "job-test", run_tag=RUN_TAG, idempotency_key=key
        )
        billing = client.billing_history(BillingQuery(endpoint_id="ep-test"))

    assert isinstance(inventory, tuple) and len(inventory) == 1
    assert isinstance(created, EndpointSummary)
    assert isinstance(drained, EndpointSummary) and drained.workers == WorkerBounds(0, 0)
    assert deleted.to_dict()["status_code"] == 204
    assert isinstance(absence, ProviderAbsenceReceipt)
    assert isinstance(queued, QueueJob) and queued.status == "IN_QUEUE"
    assert isinstance(completed, QueueJob) and completed.output_sha256 is not None
    assert isinstance(cancelled, QueueJob) and cancelled.status == "CANCELLED"
    assert isinstance(billing, BillingHistory)
    assert str(billing.provider_total_usd) == "3.25"
    assert billing.to_dict()["user_charge_usd"] is None
    assert ("GET", "/v2/billing/serverless") in requests


def test_response_drift_and_unknown_queue_status_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNPOD_API_KEY", "test-key")

    def drift(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/serverless":
            row = _endpoint()
            row["undocumented"] = True
            return httpx.Response(
                200,
                json={"endpoints": [row]},
                headers={"content-type": "application/json"},
            )
        return httpx.Response(
            200,
            json={"id": "job-test", "status": "MYSTERY"},
            headers={"content-type": "application/json"},
        )

    with RunPodV2Client(execute=True, transport=httpx.MockTransport(drift)) as client:
        with pytest.raises(RunPodProtocolError, match="shape drift"):
            client.inventory_endpoints()
        with pytest.raises(RunPodProtocolError, match="unknown status"):
            client.job_status("ep-test", "job-test")


def test_live_request_count_scaling_shape_omits_idle_timeout() -> None:
    spec = EndpointCreateSpec(
        name="request-count",
        image=IMAGE,
        gpu_pools=("ADA_24",),
        run_tag=RUN_TAG,
        workers=WorkerBounds(0, 3, None),
        scaling=ScalingPolicy("REQUEST_COUNT", Decimal("4")),
    )
    payload = spec.to_payload()
    assert payload["type"] == "QUEUE"
    assert payload["workers"] == {"min": 0, "max": 3}
    assert payload["scaling"] == {"type": "REQUEST_COUNT", "requestCount": 4}

    with pytest.raises(ContractError, match="must omit"):
        EndpointCreateSpec(
            name="invalid-request-count",
            image=IMAGE,
            gpu_pools=("ADA_24",),
            run_tag=RUN_TAG,
            workers=WorkerBounds(0, 3, 300),
            scaling=ScalingPolicy("REQUEST_COUNT", Decimal("4")),
        )


def test_provider_error_and_repr_never_expose_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = "super-secret-provider-key"
    monkeypatch.setenv("RUNPOD_API_KEY", credential)

    def failure(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"reflected={credential}")

    client = RunPodV2Client(execute=True, transport=httpx.MockTransport(failure))
    with pytest.raises(RunPodClientError) as error:
        client.inventory_endpoints()
    assert credential not in str(error.value)
    assert credential not in repr(client)
    client.close()


def test_delete_confirmed_orphan_audit_and_zero_provider_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNPOD_API_KEY", "test-key")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/v2/serverless/ep-deleted":
            return httpx.Response(404, json={"title": "Not Found"})
        if request.url.path == "/v2/serverless":
            return httpx.Response(
                200,
                json={"endpoints": [_endpoint("ep-active")]},
                headers={"content-type": "application/json"},
            )
        raise AssertionError(f"unexpected orphan audit request: {request.url}")

    with RunPodV2Client(
        execute=True, transport=httpx.MockTransport(handler)
    ) as client:
        assert client.provider_retry_count == 0
        audit = client.audit_orphans(
            run_tag=RUN_TAG,
            active_endpoint_ids=("ep-active",),
            deleted_endpoint_ids=("ep-deleted",),
        )

    assert isinstance(audit, OrphanAuditReceipt)
    assert audit.passed is True
    assert audit.orphan_endpoint_ids == ()
    assert len(audit.delete_confirmations) == 1
    assert audit.delete_confirmations[0].observation == "GET_404_NOT_FOUND"
    assert calls == ["/v2/serverless/ep-deleted", "/v2/serverless"]


def test_delete_requires_exact_target_confirmation() -> None:
    client = RunPodV2Client()
    with pytest.raises(ContractError, match="exactly match"):
        client.delete_endpoint(
            "ep-test",
            confirmation_endpoint_id="ep-other",
            run_tag=RUN_TAG,
            idempotency_key=make_idempotency_key("delete"),
        )


def test_cli_defaults_to_dry_run_without_reading_a_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    spec_path = tmp_path / "endpoint.json"
    spec_path.write_text(
        json.dumps(
            {
                "name": "structara-test",
                "image": IMAGE,
                "gpu_pools": ["ADA_24"],
                "run_tag": RUN_TAG,
            }
        ),
        encoding="utf-8",
    )
    exit_code = runpod_cli(
        [
            "create",
            "--spec",
            str(spec_path),
            "--idempotency-key",
            make_idempotency_key("cli"),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"mode": "dry-run"' in captured.out
    assert "RUNPOD_API_KEY" not in captured.out
    assert captured.err == ""
