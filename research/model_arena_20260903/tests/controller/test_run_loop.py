"""End-to-end dispatch against a fake worker: checkpoint, failure, budget.

The worker here is a real :class:`WorkerClient` driven by an httpx transport,
so the section 4 contract and the checksum gate are exercised for real rather
than stubbed out.
"""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest
from arena.constants import CAMPAIGN_ID
from arena.controller.events import EventLog
from arena.controller.paths import CampaignPaths
from arena.controller.plan import ModelPlanEntry, SourceSample, build_plan
from arena.controller.queue import CampaignQueue
from arena.controller.run import (
    ReadinessError,
    RunError,
    apply_budget,
    dispatch_page,
    eligibility,
    poll_until_ready,
    record_error,
    write_run_summary,
)
from arena.controller.watchdogs import BudgetWatchdog
from arena.provider.safety import sha256_text
from arena.provider.worker_client import WorkerClient
from tests.controller.conftest import MODEL_KEY, sample_bytes
from tests.controller.fake_worker import (
    BEARER,
    CANONICAL,
    RAW,
    FakeWorkerTransport,
    fake_worker_client,
)
from tests.controller.fake_worker import worker_response_body as _response_body


def _worker(transport: httpx.BaseTransport) -> WorkerClient:
    return fake_worker_client(transport)


# ------------------------------------------------------------- eligibility


def test_full_run_requires_a_canary_pass(paths: CampaignPaths, entry: ModelPlanEntry) -> None:
    pending = replace(entry, canary_status="PENDING")
    gate = eligibility(pending, paths)
    assert gate.allowed is False
    assert "requires PASS" in gate.reason


def test_bootstrap_full_run_needs_a_founder_waiver(
    paths: CampaignPaths, entry: ModelPlanEntry
) -> None:
    bootstrap = replace(entry, runtime_mode_allowed=("bootstrap",))
    gate = eligibility(bootstrap, paths)
    assert gate.allowed is False
    assert "waiver" in gate.reason

    waiver = paths.bootstrap_waiver(entry.model_key)
    waiver.write_text(
        json.dumps({"model_key": entry.model_key, "approved_by": "founder"}), encoding="utf-8"
    )
    allowed = eligibility(bootstrap, paths)
    assert allowed.allowed is True
    assert allowed.runtime_mode == "bootstrap"


def test_a_waiver_for_another_model_does_not_count(
    paths: CampaignPaths, entry: ModelPlanEntry
) -> None:
    bootstrap = replace(entry, runtime_mode_allowed=("bootstrap",))
    paths.bootstrap_waiver(entry.model_key).write_text(
        json.dumps({"model_key": "some_other_model"}), encoding="utf-8"
    )
    assert eligibility(bootstrap, paths).allowed is False


def test_baked_image_with_a_canary_pass_is_allowed(
    paths: CampaignPaths, entry: ModelPlanEntry
) -> None:
    assert eligibility(entry, paths).allowed is True


# --------------------------------------------------------------- readiness


def test_readiness_polls_through_both_stages() -> None:
    transport = FakeWorkerTransport(
        stages=["IMAGE_READY", "MODEL_LOADING", "WARMING", "READY"]
    )
    client = _worker(transport)
    stage, observed = poll_until_ready(client, poll_seconds=0.0, sleep=lambda _: None)
    assert stage == "READY"
    assert observed == ("IMAGE_READY", "MODEL_LOADING", "WARMING", "READY")
    client.close()


def test_readiness_stops_at_a_terminal_stage() -> None:
    transport = FakeWorkerTransport(stages=["MODEL_LOADING", "CRASHED"])
    client = _worker(transport)
    with pytest.raises(RunError, match="terminal stage CRASHED"):
        poll_until_ready(client, poll_seconds=0.0, sleep=lambda _: None)
    client.close()


def test_readiness_gives_up_rather_than_dispatching_to_a_warming_worker() -> None:
    transport = FakeWorkerTransport(stages=["WARMING"])
    client = _worker(transport)
    with pytest.raises(RunError, match="never reached READY"):
        poll_until_ready(client, max_attempts=3, poll_seconds=0.0, sleep=lambda _: None)
    client.close()


class _Ticks:
    """A clock the fake sleep advances, so a deadline can pass in no time."""

    def __init__(self) -> None:
        from datetime import UTC, datetime

        self.moment = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)

    def __call__(self):
        return self.moment

    def sleep(self, seconds: float) -> None:
        from datetime import timedelta

        self.moment += timedelta(seconds=seconds)


def test_a_proxy_error_is_not_ready_yet_rather_than_a_failure() -> None:
    """404 / 502 / 503 from the RunPod proxy mean nothing is on 8000 yet."""

    transport = FakeWorkerTransport(ready_answers=[404, 502, 503, 200], stages=["READY"])
    client = _worker(transport)
    ticks = _Ticks()
    stage, observed = poll_until_ready(
        client,
        max_attempts=None,
        poll_seconds=20.0,
        deadline_seconds=2700.0,
        sleep=ticks.sleep,
        now=ticks,
    )
    client.close()
    assert stage == "READY"
    assert observed == ("READY",)  # the proxy answers were never stages
    assert transport.ready_calls == 4


def test_a_transport_failure_is_also_not_ready_yet() -> None:
    transport = FakeWorkerTransport(
        ready_answers=[httpx.ConnectError("nothing listening"), 200], stages=["READY"]
    )
    client = _worker(transport)
    ticks = _Ticks()
    stage, _ = poll_until_ready(
        client,
        max_attempts=None,
        poll_seconds=20.0,
        deadline_seconds=2700.0,
        sleep=ticks.sleep,
        now=ticks,
    )
    client.close()
    assert stage == "READY"


def test_a_rejected_bearer_ends_the_poll_at_once() -> None:
    """No amount of waiting turns a 401 into a READY worker."""

    transport = FakeWorkerTransport(ready_answers=[401])
    client = _worker(transport)
    ticks = _Ticks()
    with pytest.raises(ReadinessError, match="refused the campaign bearer") as caught:
        poll_until_ready(
            client,
            max_attempts=None,
            poll_seconds=20.0,
            deadline_seconds=2700.0,
            sleep=ticks.sleep,
            now=ticks,
        )
    client.close()
    assert caught.value.last_status == "HTTP 401"
    assert transport.ready_calls == 1


def test_the_deadline_ends_the_poll_and_names_the_last_status() -> None:
    transport = FakeWorkerTransport(ready_answers=[404])
    client = _worker(transport)
    ticks = _Ticks()
    with pytest.raises(ReadinessError) as caught:
        poll_until_ready(
            client,
            max_attempts=None,
            poll_seconds=60.0,
            deadline_seconds=600.0,
            sleep=ticks.sleep,
            now=ticks,
        )
    client.close()
    assert caught.value.last_status == "HTTP 404"
    assert "HTTP 404" in str(caught.value)
    assert caught.value.polls == 11  # 10 minutes at one poll per minute
    assert caught.value.elapsed_seconds >= 600.0


def test_a_provider_that_reports_the_pod_dead_ends_the_poll_first() -> None:
    transport = FakeWorkerTransport(ready_answers=[404])
    client = _worker(transport)
    with pytest.raises(ReadinessError, match="reports the pod as EXITED") as caught:
        poll_until_ready(
            client,
            max_attempts=10,
            poll_seconds=0.0,
            sleep=lambda _: None,
            pod_status=lambda: "EXITED",
        )
    client.close()
    assert caught.value.provider_status == "EXITED"
    assert transport.ready_calls == 0  # the provider was asked first


def test_an_unbounded_poll_is_refused() -> None:
    """A GPU is billing the whole time; waiting forever is not on offer."""

    transport = FakeWorkerTransport(ready_answers=[404])
    client = _worker(transport)
    with pytest.raises(RunError, match="needs a bound"):
        poll_until_ready(client, max_attempts=None, deadline_seconds=None)
    client.close()


def test_distinct_answers_are_noted_once_each_not_once_per_poll() -> None:
    transport = FakeWorkerTransport(ready_answers=[404, 404, 404, 503, 200], stages=["READY"])
    client = _worker(transport)
    ticks = _Ticks()
    notes: list[str] = []
    poll_until_ready(
        client,
        max_attempts=None,
        poll_seconds=20.0,
        deadline_seconds=2700.0,
        sleep=ticks.sleep,
        now=ticks,
        note=notes.append,
    )
    client.close()
    assert sum("HTTP 404" in note for note in notes) == 1
    assert sum("HTTP 503" in note for note in notes) == 1


# ---------------------------------------------------------------- dispatch


def _setup(
    paths: CampaignPaths, samples: tuple[SourceSample, ...], entry: ModelPlanEntry
) -> tuple[CampaignQueue, EventLog, list]:
    plan = build_plan(model_key=MODEL_KEY, samples=samples, entry=entry)
    queue = CampaignQueue(paths.queue_db)
    queue.upsert_shards(plan.shards)
    queue.enqueue(plan.jobs)
    return queue, EventLog(paths.events_log), list(plan.jobs)


def test_a_successful_page_is_checkpointed_before_success_is_marked(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    queue, events, jobs = _setup(paths, samples, entry)
    transport = FakeWorkerTransport()
    client = _worker(transport)
    job = queue.get_job(jobs[0].inference_job_id)
    assert job is not None
    sample = next(item for item in samples if item.case_key == job.case_key)

    outcome = dispatch_page(
        worker=client,
        worker_id="paddleocr_vl_1_6-w0-pod_fake",
        pod_id="pod_fake",
        gpu_type="NVIDIA GeForce RTX 4090",
        job=job,
        sample=sample,
        entry=entry,
        paths=paths,
        queue=queue,
        events=events,
        image_bytes=sample_bytes(sample),
    )
    assert outcome.succeeded
    raw_path = paths.raw_dir(MODEL_KEY) / f"{job.case_key}.raw.txt"
    canonical_path = paths.canonical_dir(MODEL_KEY) / f"{job.case_key}.md"
    receipt_path = paths.receipt_dir(MODEL_KEY) / f"{job.case_key}.json"
    assert raw_path.read_text(encoding="utf-8") == RAW
    assert canonical_path.read_text(encoding="utf-8") == CANONICAL
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "SUCCESS"
    assert receipt["campaign_id"] == CAMPAIGN_ID
    assert receipt["prompt_sha256"] == entry.prompt_sha256
    assert receipt["inference_config_sha256"] == entry.inference_config_sha256
    assert receipt["runtime_mode"] == "baked"
    assert receipt["shard_id"] == job.shard_id
    assert receipt["total_ms"] == 3560
    stored = queue.get_job(job.inference_job_id)
    assert stored is not None and stored.state == "SUCCESS"
    assert stored.raw_output_sha256 == sha256_text(RAW)
    queue.close()
    client.close()


def test_a_re_dispatch_of_a_success_job_is_refused(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    queue, events, jobs = _setup(paths, samples, entry)
    transport = FakeWorkerTransport()
    client = _worker(transport)
    job = queue.get_job(jobs[0].inference_job_id)
    assert job is not None
    sample = next(item for item in samples if item.case_key == job.case_key)
    kwargs = {
        "worker": client,
        "worker_id": "w0",
        "pod_id": "pod_fake",
        "gpu_type": "NVIDIA GeForce RTX 4090",
        "sample": sample,
        "entry": entry,
        "paths": paths,
        "queue": queue,
        "events": events,
        "image_bytes": sample_bytes(sample),
    }
    dispatch_page(job=job, **kwargs)  # type: ignore[arg-type]
    assert len(transport.run_calls) == 1
    settled = queue.get_job(job.inference_job_id)
    assert settled is not None
    with pytest.raises(Exception, match="already SUCCESS"):
        dispatch_page(job=settled, **kwargs)  # type: ignore[arg-type]
    assert len(transport.run_calls) == 1  # no second paid inference
    queue.close()
    client.close()


def test_a_checksum_mismatch_is_never_accepted(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    queue, events, jobs = _setup(paths, samples, entry)
    transport = FakeWorkerTransport(
        run_override=lambda job_id: _response_body(
            job_id, raw_output_sha256="sha256:" + "0" * 64
        )
    )
    client = _worker(transport)
    job = queue.get_job(jobs[0].inference_job_id)
    assert job is not None
    sample = next(item for item in samples if item.case_key == job.case_key)

    outcome = dispatch_page(
        worker=client,
        worker_id="w0",
        pod_id="pod_fake",
        gpu_type=None,
        job=job,
        sample=sample,
        entry=entry,
        paths=paths,
        queue=queue,
        events=events,
        image_bytes=sample_bytes(sample),
    )
    assert not outcome.succeeded
    assert outcome.error_class == "CHECKSUM"
    assert not (paths.raw_dir(MODEL_KEY) / f"{job.case_key}.raw.txt").exists()
    assert not (paths.receipt_dir(MODEL_KEY) / f"{job.case_key}.json").exists()
    stored = queue.get_job(job.inference_job_id)
    assert stored is not None and stored.state == "QUARANTINED"
    queue.close()
    client.close()


def test_wrong_page_bytes_are_caught_before_the_worker_is_paid(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    queue, events, jobs = _setup(paths, samples, entry)
    transport = FakeWorkerTransport()
    client = _worker(transport)
    job = queue.get_job(jobs[0].inference_job_id)
    assert job is not None
    sample = next(item for item in samples if item.case_key == job.case_key)

    outcome = dispatch_page(
        worker=client,
        worker_id="w0",
        pod_id="pod_fake",
        gpu_type=None,
        job=job,
        sample=sample,
        entry=entry,
        paths=paths,
        queue=queue,
        events=events,
        image_bytes=b"these are not the manifest's bytes",
    )
    assert outcome.error_class == "CHECKSUM"
    assert transport.run_calls == []  # no inference was requested at all
    queue.close()
    client.close()


def test_a_model_failure_is_classified_and_retried_per_the_table(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    queue, events, jobs = _setup(paths, samples, entry)
    transport = FakeWorkerTransport(
        run_override=lambda job_id: _response_body(
            job_id, status="FAILED", error_class="CUDA_OOM", error_message="out of memory"
        )
    )
    client = _worker(transport)
    job = queue.get_job(jobs[0].inference_job_id)
    assert job is not None
    sample = next(item for item in samples if item.case_key == job.case_key)
    kwargs = {
        "worker": client,
        "worker_id": "w0",
        "pod_id": "pod_fake",
        "gpu_type": None,
        "sample": sample,
        "entry": entry,
        "paths": paths,
        "queue": queue,
        "events": events,
        "image_bytes": sample_bytes(sample),
    }
    first = dispatch_page(job=job, **kwargs)  # type: ignore[arg-type]
    assert first.error_class == "CUDA_OOM"
    assert first.retried is True
    requeued = queue.get_job(job.inference_job_id)
    assert requeued is not None and requeued.state == "PENDING" and requeued.retry_count == 1

    second = dispatch_page(job=requeued, **kwargs)  # type: ignore[arg-type]
    assert second.retried is False
    settled = queue.get_job(job.inference_job_id)
    assert settled is not None and settled.state in {"FAILED", "QUARANTINED"}
    assert settled.inference_job_id not in {
        item.inference_job_id for item in queue.pending_jobs(model_key=MODEL_KEY, limit=100)
    }
    queue.close()
    client.close()


def test_a_deterministic_runtime_error_is_quarantined_not_retried(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    queue, events, jobs = _setup(paths, samples, entry)
    transport = FakeWorkerTransport(
        run_override=lambda job_id: _response_body(
            job_id, status="FAILED", error_class="TENSOR_SHAPE", error_message="shape 3x1"
        )
    )
    client = _worker(transport)
    job = queue.get_job(jobs[0].inference_job_id)
    assert job is not None
    sample = next(item for item in samples if item.case_key == job.case_key)
    outcome = dispatch_page(
        worker=client,
        worker_id="w0",
        pod_id="pod_fake",
        gpu_type=None,
        job=job,
        sample=sample,
        entry=entry,
        paths=paths,
        queue=queue,
        events=events,
        image_bytes=sample_bytes(sample),
    )
    assert outcome.retried is False
    assert outcome.status == "QUARANTINED"
    assert len(transport.run_calls) == 1
    queue.close()
    client.close()


def test_events_are_appended_for_every_transition(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    queue, events, jobs = _setup(paths, samples, entry)
    client = _worker(FakeWorkerTransport())
    job = queue.get_job(jobs[0].inference_job_id)
    assert job is not None
    sample = next(item for item in samples if item.case_key == job.case_key)
    dispatch_page(
        worker=client,
        worker_id="w0",
        pod_id="pod_fake",
        gpu_type=None,
        job=job,
        sample=sample,
        entry=entry,
        paths=paths,
        queue=queue,
        events=events,
        image_bytes=sample_bytes(sample),
    )
    lines = paths.events_log.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    record = json.loads(lines[-1])
    assert record["entity_kind"] == "job"
    assert record["to_state"] == "SUCCESS"
    assert record["campaign_id"] == CAMPAIGN_ID
    queue.close()
    client.close()


# ------------------------------------------------------------------ budget


def test_hard_cap_pauses_the_queue_without_killing_an_in_flight_page(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    """Masterplan 15.13: drain to the checkpoint, never kill mid-page."""

    queue, events, jobs = _setup(paths, samples, entry)
    in_flight = jobs[0].inference_job_id
    queue.mark_running(in_flight, "w0")

    assessment = BudgetWatchdog().evaluate(
        spent_usd=499.0,
        running_worker_rates_usd_per_hour=[2.0],
        seconds_to_next_checkpoint=3600.0,
    )
    drained: list[str] = []
    applied = apply_budget(
        assessment,
        queue=queue,
        events=events,
        workers=["w0"],
        drain=drained.append,
    )
    assert assessment.state == "HARD_CAP"
    assert applied["paused_jobs"] == 5
    assert drained == ["w0"]
    running = queue.get_job(in_flight)
    assert running is not None
    assert running.state == "RUNNING"  # the page in flight was not touched
    assert queue.flag("budget_state") == "HARD_CAP"

    # And the page that was running can still checkpoint to SUCCESS.
    client = _worker(FakeWorkerTransport())
    sample = next(item for item in samples if item.case_key == running.case_key)
    outcome = dispatch_page(
        worker=client,
        worker_id="w0",
        pod_id="pod_fake",
        gpu_type=None,
        job=running,
        sample=sample,
        entry=entry,
        paths=paths,
        queue=queue,
        events=events,
        image_bytes=sample_bytes(sample),
    )
    assert outcome.succeeded
    queue.close()
    client.close()


def test_soft_cap_leaves_the_queue_alone(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    queue, events, _jobs = _setup(paths, samples, entry)
    assessment = BudgetWatchdog().evaluate(
        spent_usd=299.9,
        running_worker_rates_usd_per_hour=[6.0],
        seconds_to_next_checkpoint=120.0,
    )
    applied = apply_budget(assessment, queue=queue, events=events, workers=["w0"])
    assert assessment.state == "SOFT_CAP"
    assert applied["paused_jobs"] == 0
    assert queue.counts_by_state(model_key=MODEL_KEY)["PENDING"] == 6
    queue.close()


# ------------------------------------------------------- errors and summary


def test_error_records_land_in_the_failures_log(paths: CampaignPaths) -> None:
    record_error(
        paths.errors_log,
        model_key=MODEL_KEY,
        error_class="TENSOR_SHAPE",
        signature="TENSOR_SHAPE:mismatch 3x1",
        runtime_image_digest="sha256:" + "b" * 64,
        gpu_type="NVIDIA GeForce RTX 4090",
        retryable=False,
        wasted_gpu_seconds=42.5,
        root_cause="concurrency above 1",
        resolution="pin to concurrency 1",
    )
    line = json.loads(paths.errors_log.read_text(encoding="utf-8").strip())
    assert line["error_class"] == "TENSOR_SHAPE"
    assert line["wasted_gpu_seconds"] == pytest.approx(42.5)
    assert line["retryable"] is False


def test_run_summary_records_the_gate_and_the_policy_source(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    queue, _events, _jobs = _setup(paths, samples, entry)
    path = write_run_summary(
        paths,
        model_key=MODEL_KEY,
        queue=queue,
        entry=entry,
        eligibility_result=eligibility(entry, paths),
        budget=None,
        breaker=None,
        started_at="2026-09-03T10:00:00Z",
    )
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["eligibility"]["allowed"] is True
    assert summary["job_counts"]["PENDING"] == 6
    assert summary["retry_policy_source"]
    queue.close()


# ------------------------------------------------------------ secret hygiene


def test_no_secret_reaches_any_file_the_run_writes(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    """Grep every file the campaign root holds after a full dispatch."""

    queue, events, jobs = _setup(paths, samples, entry)
    client = _worker(FakeWorkerTransport())
    for record in jobs:
        job = queue.get_job(record.inference_job_id)
        assert job is not None
        sample = next(item for item in samples if item.case_key == job.case_key)
        dispatch_page(
            worker=client,
            worker_id="w0",
            pod_id="pod_fake",
            gpu_type="NVIDIA GeForce RTX 4090",
            job=job,
            sample=sample,
            entry=entry,
            paths=paths,
            queue=queue,
            events=events,
            image_bytes=sample_bytes(sample),
        )
    queue.close()
    client.close()

    written = [path for path in paths.root.rglob("*") if path.is_file()]
    assert written
    for path in written:
        if path.suffix in {".sqlite", ".sqlite-wal", ".sqlite-shm"}:
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        assert BEARER.reveal() not in content
        assert "Authorization" not in content
        assert "Bearer " not in content


# --------------------------------- a worker that refused is not a bad network
#
# All 13 pages of the 2026-09-03 GLM-OCR canary were recorded as
# INFRA_NETWORK, whose masterplan 15.9 row buys three retries with backoff.
# The pod had not dropped a packet: it had refused a request it will refuse
# every time, and the receipts named neither the check nor the two hashes.


def test_a_422_refusal_is_classified_from_its_code_not_as_a_network_fault(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    detail = (
        f"worker inference_config_sha256 sha256:{'2' * 64} != "
        f"request {entry.inference_config_sha256}"
    )
    transport = FakeWorkerTransport(
        run_status=422,
        run_override=lambda job_id: {"error": "CONFIG_MISMATCH", "detail": detail},
    )
    queue, events, jobs = _setup(paths, samples, entry)
    client = _worker(transport)
    job = queue.get_job(jobs[0].inference_job_id)
    assert job is not None
    sample = next(item for item in samples if item.case_key == job.case_key)

    outcome = dispatch_page(
        worker=client,
        worker_id="w0",
        pod_id="pod_fake",
        gpu_type=None,
        job=job,
        sample=sample,
        entry=entry,
        paths=paths,
        queue=queue,
        events=events,
        image_bytes=sample_bytes(sample),
    )

    assert outcome.error_class == "UNKNOWN"
    assert outcome.error_class != "INFRA_NETWORK"
    # No retry: the same request would be refused the same way forever.
    assert outcome.retried is False
    assert outcome.error_message is not None
    assert "CONFIG_MISMATCH" in outcome.error_message
    assert entry.inference_config_sha256 in outcome.error_message
    queue.close()
    client.close()


def test_a_proxy_error_is_still_a_network_fault_whatever_its_body_says(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    """422 is the worker's refusal channel. A 502 body was written by the proxy."""

    transport = FakeWorkerTransport(
        run_status=502,
        run_override=lambda job_id: {"error": "CONFIG_MISMATCH", "error_class": "CHECKSUM"},
    )
    queue, events, jobs = _setup(paths, samples, entry)
    client = _worker(transport)
    job = queue.get_job(jobs[0].inference_job_id)
    assert job is not None
    sample = next(item for item in samples if item.case_key == job.case_key)

    outcome = dispatch_page(
        worker=client,
        worker_id="w0",
        pod_id="pod_fake",
        gpu_type=None,
        job=job,
        sample=sample,
        entry=entry,
        paths=paths,
        queue=queue,
        events=events,
        image_bytes=sample_bytes(sample),
    )

    assert outcome.error_class == "INFRA_NETWORK"
    assert outcome.retried is True
    queue.close()
    client.close()
