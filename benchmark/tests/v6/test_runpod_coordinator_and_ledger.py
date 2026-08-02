from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from benchmark.v6.contracts import ContractError, EnvironmentIdentity
from benchmark.v6.ledger import EvidenceLedger
from benchmark.v6.repeats import build_exact_repeat_plan
from benchmark.v6.runpod_coordinator import (
    ExactThreeRunPodCoordinator,
    make_run_tag,
)
from infra.runpod.v6.cli import main as runpod_cli
from infra.runpod.v6.client import (
    BillingHistory,
    ProviderAbsenceReceipt,
    QueueJob,
    RunPodClientError,
    RunPodV2Client,
)
from infra.runpod.v6.orchestration import SpendGuard, SpendPolicy, SpendState

IMAGE = "registry.example/worker@sha256:" + ("b" * 64)


def _endpoint(run_tag: str, *, workers: tuple[int, int] = (0, 0)) -> dict[str, Any]:
    endpoint_id = "ep-cohort"
    return {
        "id": endpoint_id,
        "name": "cohort-endpoint",
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
        "env": {"AKC_RUN_TAG": run_tag},
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


def _coordinator(
    tmp_path: Path,
    environment: EnvironmentIdentity,
    client: RunPodV2Client,
    *,
    ledger_path: Path | None = None,
) -> tuple[ExactThreeRunPodCoordinator, EvidenceLedger]:
    runs = build_exact_repeat_plan(
        base_root=tmp_path / "runs",
        benchmark_id="parsebench",
        environment=environment,
    )
    ledger = EvidenceLedger(
        ledger_path or (tmp_path / "evidence.jsonl"),
        cohort_id=runs[0].cohort_id,
        run_tag=make_run_tag(runs),
    )
    coordinator = ExactThreeRunPodCoordinator(
        runs=runs,
        endpoint_id="ep-cohort",
        client=client,
        ledger=ledger,
        spend_guard=SpendGuard(
            run_id=runs[0].cohort_id,
            policy=SpendPolicy(expected_cost_usd=Decimal("10")),
        ),
    )
    return coordinator, ledger


def _inputs(coordinator: ExactThreeRunPodCoordinator) -> dict[str, dict[str, object]]:
    return {
        run.run_id: {"manifest_sha256": "sha256:" + str(run.repeat_index) * 64}
        for run in coordinator.runs
    }


def test_ledger_detects_tampering_truncation_and_duplicate_dispatch_intent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = EvidenceLedger(path, cohort_id="cohort-test", run_tag="v6-cohort-test")
    ledger.append("cohort.plan.frozen.v1", {"plan_sha256": "sha256:" + "a" * 64})
    ledger.append(
        "job.dispatch.intent.v1",
        {
            "logical_work_id": "run-1",
            "idempotency_key": "idem-" + "b" * 64,
            "input_sha256": "sha256:" + "c" * 64,
        },
    )
    with pytest.raises(ContractError, match="duplicate dispatch intent"):
        ledger.append(
            "job.dispatch.intent.v1",
            {
                "logical_work_id": "run-1",
                "idempotency_key": "idem-" + "b" * 64,
                "input_sha256": "sha256:" + "c" * 64,
            },
        )

    original = path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in original.splitlines()]
    records[0]["payload"]["plan_sha256"] = "sha256:" + "f" * 64
    path.write_text(
        "\n".join(json.dumps(item, sort_keys=True) for item in records) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="hash mismatch"):
        ledger.replay()

    path.write_text(original[:-1], encoding="utf-8")
    with pytest.raises(ContractError, match="truncated"):
        ledger.replay()


def test_exact_three_dry_run_is_network_free_and_resumable(
    tmp_path: Path,
    environment: EnvironmentIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    calls = 0

    def forbidden(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("dry run reached provider")

    client = RunPodV2Client(transport=httpx.MockTransport(forbidden))
    coordinator, ledger = _coordinator(tmp_path, environment, client)
    first = coordinator.dispatch_exact_three(_inputs(coordinator))
    second = coordinator.dispatch_exact_three(_inputs(coordinator))

    assert calls == 0
    assert len(first) == len(second) == 3
    assert {item.status for item in first} == {"DRY_RUN"}
    assert len(tuple(ledger.iter_type("job.dispatch.dry_run.v1"))) == 3
    assert len(tuple(ledger.iter_type("job.dispatch.intent.v1"))) == 0


def test_execute_writes_intent_before_exact_three_dispatch_and_resume_never_duplicates(
    tmp_path: Path,
    environment: EnvironmentIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNPOD_API_KEY", "test-key")
    holder: dict[str, EvidenceLedger] = {}
    run_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal run_calls
        assert request.url.path == "/v2/ep-cohort/run"
        run_calls += 1
        assert len(tuple(holder["ledger"].iter_type("job.dispatch.intent.v1"))) == run_calls
        return httpx.Response(
            200,
            json={"id": f"job-{run_calls}", "status": "IN_QUEUE"},
            headers={"content-type": "application/json"},
        )

    ledger_path = tmp_path / "cohort.jsonl"
    with RunPodV2Client(
        execute=True, transport=httpx.MockTransport(handler)
    ) as client:
        coordinator, ledger = _coordinator(
            tmp_path, environment, client, ledger_path=ledger_path
        )
        holder["ledger"] = ledger
        first = coordinator.dispatch_exact_three(_inputs(coordinator))

    def no_duplicate(_: httpx.Request) -> httpx.Response:
        raise AssertionError("resume attempted a duplicate provider write")

    with RunPodV2Client(
        execute=True, transport=httpx.MockTransport(no_duplicate)
    ) as resumed_client:
        resumed, _ = _coordinator(
            tmp_path, environment, resumed_client, ledger_path=ledger_path
        )
        second = resumed.dispatch_exact_three(_inputs(resumed))

    assert run_calls == 3
    assert len(first) == len(second) == 3
    assert all(item.recovered for item in second)
    assert len(tuple(ledger.iter_type("job.dispatched.v1"))) == 3


def test_ambiguous_provider_write_hard_stops_without_automatic_retry(
    tmp_path: Path,
    environment: EnvironmentIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNPOD_API_KEY", "test-key")
    calls = 0

    def ambiguous(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("unknown write outcome", request=request)

    ledger_path = tmp_path / "ambiguous.jsonl"
    with RunPodV2Client(
        execute=True, transport=httpx.MockTransport(ambiguous)
    ) as client:
        coordinator, ledger = _coordinator(
            tmp_path, environment, client, ledger_path=ledger_path
        )
        with pytest.raises(RunPodClientError):
            coordinator.dispatch_exact_three(_inputs(coordinator))
        assert coordinator.spend_guard.state is SpendState.HARD_STOP_RUNAWAY

    assert calls == 1
    assert len(tuple(ledger.iter_type("job.dispatch.intent.v1"))) == 1
    assert len(tuple(ledger.iter_type("job.dispatched.v1"))) == 0
    assert ledger.latest("safety.hard_stop.v1") is not None


def test_accepted_only_user_billing_stays_separate_from_provider_spend_and_cleanup(
    tmp_path: Path,
    environment: EnvironmentIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNPOD_API_KEY", "test-key")
    run_tag_holder: dict[str, str] = {}
    run_count = 0
    deleted = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal run_count, deleted
        path = request.url.path
        if request.method == "POST" and path == "/v2/ep-cohort/run":
            run_count += 1
            return httpx.Response(
                200,
                json={"id": f"job-{run_count}", "status": "IN_QUEUE"},
                headers={"content-type": "application/json"},
            )
        if request.method == "GET" and path.startswith("/v2/ep-cohort/status/job-"):
            job_id = path.rsplit("/", 1)[1]
            return httpx.Response(
                200,
                json={"id": job_id, "status": "COMPLETED", "output": {"job": job_id}},
                headers={"content-type": "application/json"},
            )
        if request.method == "PATCH" and path == "/v2/serverless/ep-cohort":
            return httpx.Response(
                200,
                json=_endpoint(run_tag_holder["tag"]),
                headers={"content-type": "application/json"},
            )
        if request.method == "DELETE" and path == "/v2/serverless/ep-cohort":
            deleted = True
            return httpx.Response(204)
        if request.method == "GET" and path == "/v2/serverless/ep-cohort":
            assert deleted
            return httpx.Response(404, json={"title": "Not Found"})
        raise AssertionError(f"unexpected request: {request.method} {path}")

    with RunPodV2Client(
        execute=True, transport=httpx.MockTransport(handler)
    ) as client:
        coordinator, ledger = _coordinator(tmp_path, environment, client)
        run_tag_holder["tag"] = coordinator.run_tag
        outcomes = coordinator.dispatch_exact_three(_inputs(coordinator))
        statuses = coordinator.refresh_statuses()
        jobs = [item for item in statuses if isinstance(item, QueueJob)]
        assert len(jobs) == 3
        coordinator.accept_completed(
            logical_work_id=outcomes[0].logical_work_id,
            job=jobs[0],
            validation_receipt_sha256="sha256:" + "7" * 64,
            final_integrity_state="verified",
            user_charge_usd="0.20",
        )
        coordinator.finalize_nonbillable(
            logical_work_id=outcomes[1].logical_work_id,
            final_integrity_state="unresolved",
            failure_receipt_sha256="sha256:" + "8" * 64,
        )
        coordinator.record_provider_billing(
            BillingHistory(
                records=(),
                provider_total_usd=Decimal("4.00"),
                response_sha256="sha256:" + "9" * 64,
            ),
            cause="planned",
        )
        absence = coordinator.cleanup_endpoint(
            artifacts_uploaded=True,
            evidence_receipt_sha256="sha256:" + "a" * 64,
            grace_window_elapsed=True,
        )
        report = coordinator.report()

    assert isinstance(absence, ProviderAbsenceReceipt)
    assert absence.observation == "GET_404_NOT_FOUND"
    assert report["provider_cost_usd"] == "4.00"
    assert report["user_charge_usd"] == "0.20"
    assert report["accepted_only_billing"] is True
    assert report["terminal_provider_absence"] is True
    assert ledger.latest("endpoint.provider_absent.v1") is not None
    assert len(tuple(ledger.iter_type("user.charge.settled.v1"))) == 1
    assert len(tuple(ledger.iter_type("provider.billing.recorded.v1"))) == 1


def test_duplicate_billing_receipt_hard_stops_runaway_accounting(
    tmp_path: Path,
    environment: EnvironmentIdentity,
) -> None:
    coordinator, _ = _coordinator(tmp_path, environment, RunPodV2Client())
    history = BillingHistory(
        records=(),
        provider_total_usd=Decimal("1"),
        response_sha256="sha256:" + "d" * 64,
    )
    coordinator.record_provider_billing(history, cause="planned")
    with pytest.raises(ContractError, match="already recorded"):
        coordinator.record_provider_billing(history, cause="planned")
    assert coordinator.spend_guard.state is SpendState.HARD_STOP_RUNAWAY


def test_exact_three_cli_writes_immutable_dry_run_receipt_and_ledger(
    tmp_path: Path,
    environment: EnvironmentIdentity,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    runs = build_exact_repeat_plan(
        base_root=tmp_path / "runs",
        benchmark_id="parsebench",
        environment=environment,
    )
    ledger_path = (tmp_path / "cli-ledger.jsonl").resolve()
    manifest_path = tmp_path / "cohort-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "6.0.0",
                "endpoint_id": "ep-cohort",
                "ledger_path": str(ledger_path),
                "expected_cost_usd": "10",
                "runs": [run.to_dict() for run in runs],
                "inputs_by_run": {
                    run.run_id: {"repeat_index": run.repeat_index} for run in runs
                },
            }
        ),
        encoding="utf-8",
    )
    receipt_path = tmp_path / "03-exact-three-dry-run.json"

    exit_code = runpod_cli(
        [
            "--receipt-out",
            str(receipt_path),
            "cohort-dispatch",
            "--manifest",
            str(manifest_path),
        ]
    )
    output = capsys.readouterr()

    assert exit_code == 0
    assert receipt_path.is_file()
    assert ledger_path.is_file()
    assert output.err == ""
    rendered = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert len(rendered["outcomes"]) == 3
    assert {item["status"] for item in rendered["outcomes"]} == {"DRY_RUN"}

    assert runpod_cli(
        [
            "--receipt-out",
            str(receipt_path),
            "cohort-dispatch",
            "--manifest",
            str(manifest_path),
        ]
    ) == 2
    assert "will not be overwritten" in capsys.readouterr().err
