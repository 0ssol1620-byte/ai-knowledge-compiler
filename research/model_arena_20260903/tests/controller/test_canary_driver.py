"""The D20 canary driver, one failure at a time.

Two adversarial critics returned NO-GO on the first pass because
``canary --execute`` provisioned a pod and returned. The driver is the answer,
and the only way to believe it is to break it on purpose: a pod that never
warms, a page that times out, an evaluation that FAILs, an exception nobody
predicted, a watchdog that fires while the main thread is blocked. Every one
of those tests asserts the same thing at the end -- **the pod came back**.

Nothing here touches a network or a provider. Both clients, the worker
factory, the page loader, the clock and the sleep are injected.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from arena.controller.driver import (
    CanaryWatchdog,
    DriverError,
    classify_page_failures,
    load_page_bytes,
    run_canary,
)
from arena.controller.paths import CampaignPaths
from arena.controller.plan import ModelPlanEntry, load_source_manifest
from arena.controller.prompts import PromptRef
from arena.controller.runtime_spec import RuntimeSpecView
from arena.provider.runpod_pods import GpuPriceRow, PriceSnapshot, RunPodClientError
from tests.controller.conftest import (
    MODEL_KEY,
    PROMPT_ID,
    make_sample,
    sample_bytes,
    write_bundle_receipt,
    write_model_registry,
    write_prompt_registry,
    write_source_manifest,
)
from tests.controller.fake_worker import (
    FakeWorkerTransport,
    fake_worker_client,
    worker_response_body,
)

BUNDLE_SHA = "f" * 64
BOOTSTRAP_DIGEST = f"bootstrap:sha256:{BUNDLE_SHA}"
POD_ID = "podfakedriver1"


# ------------------------------------------------------------------ doubles


@dataclass
class _FakeReceipt:
    """The two fields the driver reads off a provider receipt."""

    summary: Mapping[str, object]
    action: str = "get_logs"


@dataclass
class FakePod:
    pod_id: str


@dataclass
class FakePodRecord:
    """The fields ``_pod_facts`` reads off a ``PodV1``, and nothing else."""

    pod_id: str
    desired_status: str = "RUNNING"
    data_center_id: str | None = "EU-RO-1"
    cost_usd_per_hour: float = 0.74
    machine_id: str | None = "s194cr8pls2z"


class FakeProvider:
    """One object standing in for both API versions.

    It records every stop and delete, and stops listing the pod once it has
    been deleted -- which is the only thing ``_confirm_gone`` accepts as
    evidence that the pod is actually gone.
    """

    def __init__(self, *, execute: bool = True, listing_survives: int = 0) -> None:
        self.execute = execute
        self.live: set[str] = set()
        self.stopped: list[str] = []
        self.deleted: list[str] = []
        self.stop_raises: Exception | None = None
        self.delete_raises: Exception | None = None
        # What ``GET /pods/{id}`` reports. A canary that is still pulling an
        # image reads RUNNING; EXITED is the provider saying it is over.
        self.desired_status = "RUNNING"
        self.get_pod_raises: Exception | None = None
        self.get_pod_calls: list[str] = []
        self.log_lines: list[dict[str, object]] = []
        self.log_raises: Exception | None = None
        self.log_sources: list[str | None] = []
        self.log_tails: list[tuple[str | None, int]] = []
        # The driver reads what each log drain did back out of ``receipts``,
        # the way it reads the create walk; a double without it would let the
        # "400 requested, 194 received" half of the note go untested.
        self.receipts: list[Any] = []
        # Receipt accounting: the driver keeps the first read, every change and
        # every tenth otherwise, and the rest never reach disk.
        self.receipts_kept: list[str] = []
        self.receipts_suppressed = 0
        # After this many ``get_pod`` reads the pod disappears, as it does when
        # an operator deletes it by hand mid-bootstrap.
        self.delete_after_reads: int | None = None
        # How many listings still show the pod *after* the delete, so a test
        # can model a provider that lags.
        self.listing_survives = listing_survives
        self._lock = threading.Lock()

    def add(self, pod_id: str) -> None:
        self.live.add(pod_id)

    def get_pod(
        self,
        pod_id: str,
        *,
        persist_receipt: bool | Any = True,
    ) -> FakePodRecord | None:
        self.get_pod_calls.append(pod_id)
        if self.get_pod_raises is not None:
            raise self.get_pod_raises
        with self._lock:
            # A pod deleted outside the driver stops existing mid-poll.
            if (
                self.delete_after_reads is not None
                and len(self.get_pod_calls) > self.delete_after_reads
            ):
                self.live.discard(pod_id)
            pod = (
                FakePodRecord(pod_id=pod_id, desired_status=self.desired_status)
                if pod_id in self.live
                else None
            )
        keep = persist_receipt(pod) if callable(persist_receipt) else bool(persist_receipt)
        if keep:
            self.receipts_kept.append(pod_id)
        else:
            self.receipts_suppressed += 1
        return pod

    def get_logs(
        self,
        pod_id: str,
        *,
        tail: int = 200,
        max_lines: int = 2000,
        source: str | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        # The real endpoint keeps container and system as separate sequences.
        # Anything not explicitly ``system`` is the runtime's own output.
        self.log_sources.append(source)
        self.log_tails.append((source, tail))
        if self.log_raises is not None:
            raise self.log_raises
        container = [entry for entry in self.log_lines if entry.get("source") != "system"]
        system = [entry for entry in self.log_lines if entry.get("source") == "system"]
        if source == "container":
            selected = container
        elif source == "system":
            selected = system
        else:
            # "both" is not a merge: the endpoint concatenates the sequences,
            # container first, so a bounded tail over it keeps only system.
            selected = container + system
        lines = tuple(selected[-max_lines:])
        self.receipts.append(
            _FakeReceipt(
                summary={
                    "source": source,
                    "tail_requested": tail,
                    "line_count": len(lines),
                    "stopped_because": "quiet",
                }
            )
        )
        return lines

    def stop_pod(self, pod_id: str) -> object:
        if self.stop_raises is not None:
            raise self.stop_raises
        with self._lock:
            self.stopped.append(pod_id)
        return {"id": pod_id}

    def delete_pod(self, pod_id: str) -> object:
        if self.delete_raises is not None:
            raise self.delete_raises
        with self._lock:
            self.deleted.append(pod_id)
            if self.listing_survives <= 0:
                self.live.discard(pod_id)
        return {"id": pod_id}

    def list_pods(self) -> list[FakePod]:
        with self._lock:
            if self.deleted and self.listing_survives > 0:
                self.listing_survives -= 1
                if self.listing_survives <= 0:
                    self.live.difference_update(self.deleted)
            return [FakePod(pod_id=pod) for pod in sorted(self.live)]


def _runtime(paths: CampaignPaths) -> RuntimeSpecView:
    return RuntimeSpecView(
        model_key=MODEL_KEY,
        path=paths.runtime_json(MODEL_KEY),
        base_image="vllm/vllm-openai:v0.11.0@sha256:" + "e" * 64,
        model_repo="PaddlePaddle/PaddleOCR-VL-1.6",
        model_revision="a" * 40,
        prompt_id=PROMPT_ID,
        gpu_count_min=1,
        gpu_pool_priority=("NVIDIA GeForce RTX 4090",),
        per_page_timeout_seconds=600,
        runtime_mode_allowed=("bootstrap",),
        license_status="verified",
        license_id="Apache-2.0",
        gpu_min_vram_gb=24,
        prompt_kind="none",
    )


def _snapshot() -> PriceSnapshot:
    return PriceSnapshot(
        captured_at="2026-09-03T12:00:00Z",
        rows=(
            GpuPriceRow(
                gpu_type_id="NVIDIA GeForce RTX 4090",
                display_name="RTX 4090",
                memory_gb=24,
                secure_available=True,
                community_available=True,
                price_secure_usd_per_hour=0.69,
                price_community_usd_per_hour=0.34,
            ),
        ),
    )


class VirtualClock:
    """A clock the fake ``sleep`` moves.

    The readiness poll gives up on a wall-clock deadline, so a test that waited
    it out for real would spend forty-five minutes proving a timeout. Sleeping
    advances this instead: the driver sees the deadline pass, the test does
    not wait for it.
    """

    def __init__(self) -> None:
        self.moment = _at(0)

    def __call__(self):
        return self.moment

    def sleep(self, seconds: float) -> None:
        from datetime import timedelta

        self.moment += timedelta(seconds=max(seconds, 0.001))


@dataclass
class Campaign:
    """Everything the driver reads, on disk, plus the doubles it is handed."""

    paths: CampaignPaths
    provider: FakeProvider
    transport: FakeWorkerTransport
    samples: tuple
    clock: VirtualClock = field(default_factory=VirtualClock)
    created: list = field(default_factory=list)

    def create_pod(
        self, image_digest: str, prompt: PromptRef
    ) -> tuple[str | None, Mapping[str, object]]:
        self.created.append((image_digest, prompt))
        self.provider.add(POD_ID)
        return POD_ID, {"name": "arena-paddleocr-vl-1-6-w0-20260903v1", "env": {}}

    def run(self, **overrides: Any) -> Any:
        kwargs: dict[str, Any] = {
            "paths": self.paths,
            "model_key": MODEL_KEY,
            "runtime": _runtime(self.paths),
            "snapshot": _snapshot(),
            "gpu_type": "NVIDIA GeForce RTX 4090",
            "hourly_rate_usd": 0.69,
            "price_row_sha256": "c" * 64,
            "v1_client": self.provider,
            "v2_client": self.provider,
            "create_pod": self.create_pod,
            "worker_factory": lambda pod_id: fake_worker_client(
                self.transport, pod_id=pod_id
            ),
            "staged_root": self.paths.root / "staged-public-core",
            "authorization_receipt_path": "receipts/authorizations/phase1-canary.json",
            "authorization_receipt_sha256": "d" * 64,
            "bootstrap_deadline_seconds": 2700.0,
            "ready_poll_seconds": 20.0,
            "sleep": self.clock.sleep,
            "now": self.clock,
            "start_watchdog": False,
        }
        kwargs.update(overrides)
        return run_canary(**kwargs)


@pytest.fixture
def campaign(paths: CampaignPaths, entry: ModelPlanEntry) -> Campaign:
    samples = tuple(make_sample(index) for index in range(1, 5))
    write_source_manifest(paths.source_manifest, samples)
    paths.canary_selection.write_text(
        json.dumps({"case_keys": [sample.case_key for sample in samples]}),
        encoding="utf-8",
    )
    write_model_registry(paths.model_registry, entry)
    write_prompt_registry(paths, text="")
    write_bundle_receipt(paths, bundle_sha256=BUNDLE_SHA)
    for sample in samples:
        page = paths.root / "staged-public-core" / sample.image_path
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_bytes(sample_bytes(sample))
    return Campaign(
        paths=paths,
        provider=FakeProvider(),
        transport=FakeWorkerTransport(
            run_override=lambda job_id: worker_response_body(
                job_id,
                runtime_mode="bootstrap",
                runtime_image_digest=BOOTSTRAP_DIGEST,
            )
        ),
        samples=samples,
    )


# ------------------------------------------------------------- happy path


def test_the_whole_phase_runs_and_the_pod_comes_back(campaign: Campaign) -> None:
    result = campaign.run()

    assert result.status == "PASS"
    assert result.pages_attempted == 4
    assert result.pages_succeeded == 4
    # D20's ordering, proved by the artefacts each step leaves behind.
    assert result.canary_receipt_path is not None and result.canary_receipt_path.is_file()
    assert result.registry_update_path is not None
    assert result.ledger_path is not None and result.ledger_path.is_file()
    assert result.driver_receipt_path is not None
    assert campaign.transport.drained is True
    assert campaign.provider.stopped == [POD_ID]
    assert campaign.provider.deleted == [POD_ID]
    assert result.pod_return.returned is True

    receipt = json.loads(result.canary_receipt_path.read_text(encoding="utf-8"))
    # D15: the receipt names the bundle, not the base image.
    assert receipt["runtime_image_digest"] == BOOTSTRAP_DIGEST
    assert receipt["base_image"].startswith("vllm/vllm-openai")
    # D26: the authorization and the ledger are cited, not summarised.
    assert receipt["authorization_receipt_path"].endswith("phase1-canary.json")
    assert receipt["authorization_receipt_sha256"] == "d" * 64
    assert receipt["pod_ledger_path"] == "cost/pod_ledger.jsonl"
    assert receipt["pod_id"] == POD_ID
    assert receipt["gpu_type"] == "NVIDIA GeForce RTX 4090"
    assert receipt["gpu_hours_projected"] is not None


def test_the_pod_ledger_row_is_written_when_the_pod_is_given_back(
    campaign: Campaign,
) -> None:
    """D28: the billed life of the pod, written on stop/delete."""

    result = campaign.run()
    assert result.ledger_path is not None
    rows = [
        json.loads(line)
        for line in result.ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["pod_id"] == POD_ID
    assert rows[0]["runtime_mode"] == "bootstrap"
    # D28 / section 3.3: the data centre comes off the provider record, read
    # while the pod still exists. The live 2026-09-03 row had it as null.
    assert rows[0]["data_center_id"] == "EU-RO-1"


def test_the_ledger_is_written_and_priced_even_when_readiness_failed(
    campaign: Campaign,
) -> None:
    """The 2026-09-03 shape: a pod that rented a GPU and produced no page."""

    campaign.transport.ready_answers = [404]
    result = campaign.run(bootstrap_deadline_seconds=180.0, ready_poll_seconds=60.0)

    assert result.status == "ERROR"
    assert result.ledger_path is not None
    row = json.loads(result.ledger_path.read_text(encoding="utf-8").splitlines()[-1])
    assert row["pod_id"] == POD_ID
    assert row["data_center_id"] == "EU-RO-1"
    assert row["estimated_provider_cost_usd"] is not None
    assert row["useful_inference_seconds"] == 0.0

    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    teardown = driver["pod_teardown"]
    assert teardown["stopped_at"] is not None
    assert teardown["deleted_at"] is not None
    assert teardown["data_center_id"] == "EU-RO-1"
    assert teardown["provider_rate_usd_per_hour"] == 0.74


def test_the_internal_ledger_view_carries_the_teardown_times_and_wasted_seconds(
    paths: CampaignPaths,
) -> None:
    """Section 3.3's schema is closed and A1's, so these four fields live in
    ``PodLedgerRow.to_dict`` -- the view ``cost`` writes -- not in the JSONL."""

    from arena.controller.cost import build_ledger_row, pod_ledger_record
    from arena.controller.queue import PodRecord

    pod = PodRecord(
        pod_id=POD_ID,
        model_key=MODEL_KEY,
        name="arena-paddleocr-vl-1-6-w0-20260903v1",
        state="TERMINATED",
        gpu_type="NVIDIA GeForce RTX 4090",
        data_center_id="EU-RO-1",
        runtime_mode="bootstrap",
        listed_rate_usd_per_hour=0.74,
        price_snapshot_sha256="sha256:" + "a" * 64,
        provider_api_version="v1",
        provisioned_at="2026-09-03T12:02:40Z",
        terminated_at="2026-09-03T12:02:48Z",
    )
    row = build_ledger_row(
        pod,
        useful_inference_seconds=0.0,
        stopped_at="2026-09-03T12:02:46Z",
        deleted_at="2026-09-03T12:02:48Z",
    )
    view = row.to_dict()
    assert view["stopped_at"] == "2026-09-03T12:02:46Z"
    assert view["deleted_at"] == "2026-09-03T12:02:48Z"
    assert view["provider_api_version"] == "v1"
    # A canary that produced nothing wasted every second it was billed.
    assert view["wasted_gpu_seconds"] == 8.0
    assert view["billed_seconds"] == 8.0

    # The section 3.3 projection stays exactly what the closed schema names.
    assert set(pod_ledger_record(row)) == {
        "schema", "campaign_id", "model_key", "runtime_mode", "pod_id", "gpu_type",
        "data_center_id", "listed_rate_usd_per_hour", "gpu_count", "price_snapshot_sha256",
        "provisioned_at", "model_ready_at", "last_job_finished_at", "terminated_at",
        "billed_seconds", "model_loading_seconds", "useful_inference_seconds",
        "retry_seconds", "idle_seconds", "estimated_provider_cost_usd",
        "useful_cost_usd", "wasted_cost_usd",
    }


def test_a_pod_with_no_price_quote_is_priced_from_the_provider_record(
    campaign: Campaign,
) -> None:
    """D28: costPerHr is what keeps the row priced when the quote never came."""

    result = campaign.run(hourly_rate_usd=None)

    assert result.ledger_path is not None
    row = json.loads(result.ledger_path.read_text(encoding="utf-8").splitlines()[-1])
    assert row["listed_rate_usd_per_hour"] == 0.74  # the pod's own costPerHr
    assert row["estimated_provider_cost_usd"] is not None
    assert any("provider's own costPerHr" in note for note in result.notes)


# ------------------------------------------------------ bootstrap patience
#
# The 2026-09-03 live run against pod uskidtgack3e3z died here: seconds after
# creation the driver asked once, the RunPod proxy answered 404 because
# nothing was listening on 8000 yet, and the canary aborted 0/0 pages while a
# 4.7 GB image was still pulling. Every test below is that failure, fixed.


def test_a_proxy_that_404s_then_503s_is_waited_out_not_given_up_on(
    campaign: Campaign,
) -> None:
    """404, a dropped connection, 503, then the worker answers. That is a
    bootstrap pod coming up, not a broken one."""

    import httpx

    campaign.transport.ready_answers = [
        404,
        httpx.ConnectError("no listener on 8000 yet"),
        503,
        200,
    ]
    campaign.transport.stages = ["MODEL_LOADING", "WARMING", "READY"]
    result = campaign.run()

    assert result.status == "PASS"
    assert result.pages_succeeded == 4
    assert campaign.transport.ready_calls == 6  # 3 proxy answers + 3 stages
    # Each distinct answer is named once, not once per poll.
    assert any("HTTP 404" in note for note in result.notes)
    assert any("HTTP 503" in note for note in result.notes)
    assert any("no answer (WorkerTransportError)" in note for note in result.notes)
    assert campaign.provider.deleted == [POD_ID]


def test_the_readiness_poll_addresses_v1_ready_on_the_pod_proxy(
    campaign: Campaign,
) -> None:
    """The log line that said ``GET /ready`` left the prefix in doubt."""

    campaign.run()

    assert campaign.transport.ready_urls
    assert campaign.transport.ready_urls[0] == (
        f"https://{POD_ID}-8000.proxy.runpod.net/v1/ready"
    )


def test_a_rejected_bearer_fails_at_once_and_does_not_burn_the_deadline(
    campaign: Campaign,
) -> None:
    """401 will still be 401 in forty-five minutes. Give the pod back now."""

    campaign.transport.ready_answers = [401]
    result = campaign.run(bootstrap_deadline_seconds=2700.0)

    assert result.status == "ERROR"
    assert "refused the campaign bearer" in str(result.error)
    assert campaign.transport.ready_calls == 1
    assert campaign.provider.deleted == [POD_ID]
    assert result.pod_return.returned is True


def test_the_bootstrap_deadline_gives_up_and_names_the_last_status_seen(
    campaign: Campaign,
) -> None:
    campaign.transport.ready_answers = [404]
    result = campaign.run(bootstrap_deadline_seconds=2700.0, ready_poll_seconds=20.0)

    assert result.status == "ERROR"
    assert "never reached READY within 45 min" in str(result.error)
    assert "HTTP 404" in str(result.error)  # the last status seen, in the reason
    assert campaign.transport.ready_calls == 136  # 45 min at one poll per 20 s
    assert campaign.provider.deleted == [POD_ID]
    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    assert driver["readiness"]["last_status"] == "HTTP 404"
    assert driver["readiness"]["polls"] == 136


def test_a_pod_the_provider_reports_exited_fails_before_the_deadline(
    campaign: Campaign,
) -> None:
    """D20: the provider's own verdict outranks waiting for a dead pod."""

    campaign.transport.ready_answers = [502]
    campaign.provider.desired_status = "EXITED"
    campaign.provider.log_lines = [
        {"source": "stderr", "ts": "2026-09-03T12:03:00Z", "line": "no space left on device"}
    ]
    result = campaign.run(bootstrap_deadline_seconds=2700.0)

    assert result.status == "ERROR"
    assert "reports the pod as EXITED" in str(result.error)
    assert campaign.transport.ready_calls == 0  # asked the provider first
    assert campaign.provider.deleted == [POD_ID]
    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    assert driver["readiness"]["provider_status"] == "EXITED"
    tail = driver["readiness"]["container_log_tail"]
    assert tail and tail[0]["line"] == "no space left on device"


def test_a_provider_that_cannot_be_read_is_not_evidence_the_pod_died(
    campaign: Campaign,
) -> None:
    """An unreadable provider must not condemn a pod that is merely slow."""

    campaign.provider.get_pod_raises = RunPodClientError("HTTP 502 from the provider")
    campaign.transport.ready_answers = [404, 200]
    campaign.transport.stages = ["READY"]
    result = campaign.run()

    assert result.status == "PASS"
    assert result.pages_succeeded == 4


def test_a_log_tail_that_trips_the_secret_guard_is_dropped_not_written(
    campaign: Campaign,
) -> None:
    """Losing the whole receipt to a SecretLeak would cost more than the log."""

    campaign.transport.ready_answers = [502]
    campaign.provider.desired_status = "EXITED"
    campaign.provider.log_lines = [
        {
            "source": "stderr",
            "ts": "2026-09-03T12:03:00Z",
            "line": (
                "curl: (22) https://acct.r2.cloudflarestorage.com/b/o"
                "?X-Amz-Signature=deadbeefdeadbeefdeadbeef"
            ),
        }
    ]
    result = campaign.run()

    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    assert driver["readiness"]["container_log_tail"] is None
    assert "withheld" in driver["readiness"]["container_log_note"]
    assert "X-Amz-Signature" not in result.driver_receipt_path.read_text(encoding="utf-8")


# ---------------------------------------------- readiness diagnostics (D19)


def _log(*lines: str) -> list[dict[str, object]]:
    return [
        {"source": "stdout", "ts": f"2026-09-03T12:00:00Z#{index}", "line": text}
        for index, text in enumerate(lines)
    ]


def test_a_crashing_model_server_ends_the_wait_instead_of_burning_45_minutes(
    campaign: Campaign,
) -> None:
    """The 2026-09-03 GLM-OCR pod, exactly: RUNNING, 404, dying, forever."""

    campaign.transport.ready_answers = [404]
    campaign.provider.desired_status = "RUNNING"
    campaign.provider.log_lines = _log(
        "start container for vllm/vllm-openai:v0.11.0: begin",
        "[arena] bootstrap: weights cache hit",
        "[arena] model server exited with status 70",
    )
    result = campaign.run(bootstrap_deadline_seconds=2700.0, ready_poll_seconds=20.0)

    assert result.status == "ERROR"
    assert "will not come up" in str(result.error)
    # One poll, not the 136 the deadline would have allowed.
    assert campaign.transport.ready_calls <= 1
    assert campaign.provider.deleted == [POD_ID]
    assert result.pod_return.returned is True

    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    readiness = driver["readiness"]
    assert readiness["error_class"] == "MODEL_LOAD"
    assert readiness["signature"] == "[arena] model server exited"
    tail = readiness["container_log_tail"]
    assert tail and tail[-1]["line"] == "[arena] model server exited with status 70"


def test_a_restart_loop_ends_the_wait(campaign: Campaign) -> None:
    campaign.transport.ready_answers = [404]
    campaign.provider.log_lines = _log(
        "start container for vllm/vllm-openai:v0.11.0: begin",
        "[arena] bootstrap: extracting bundle",
        "start container for vllm/vllm-openai:v0.11.0: begin",
    )
    result = campaign.run(bootstrap_deadline_seconds=2700.0)

    assert result.status == "ERROR"
    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    assert driver["readiness"]["error_class"] == "MODEL_LOAD"
    assert "start container for" in driver["readiness"]["signature"]
    assert campaign.provider.deleted == [POD_ID]


def test_a_pod_deleted_by_hand_mid_wait_fails_fast_and_still_ledgers(
    campaign: Campaign,
) -> None:
    """Item 5: the operator killed the pod. Do not poll the proxy to the end."""

    campaign.transport.ready_answers = [404]
    campaign.provider.delete_after_reads = 1
    result = campaign.run(bootstrap_deadline_seconds=2700.0, ready_poll_seconds=20.0)

    assert result.status == "ERROR"
    assert "pod gone" in str(result.error)
    assert campaign.transport.ready_calls <= 2  # not 136
    # The `finally` still writes the ledger row, from the provisioning line
    # plus the last provider record read while the pod still existed.
    assert result.ledger_path is not None and result.ledger_path.is_file()
    row = json.loads(result.ledger_path.read_text(encoding="utf-8").splitlines()[-1])
    assert row["pod_id"] == POD_ID
    assert row["data_center_id"] == "EU-RO-1"
    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    assert driver["readiness"]["provider_status"] == "MISSING"


def test_the_provider_read_receipts_are_thinned_and_counted(
    campaign: Campaign,
) -> None:
    """Item 3: 136 identical get_pod receipts per bootstrap was the noise."""

    campaign.transport.ready_answers = [404]
    result = campaign.run(bootstrap_deadline_seconds=2700.0, ready_poll_seconds=20.0)

    reads = len(campaign.provider.get_pod_calls)
    assert reads > 100  # the poll really did run to the deadline
    # Kept: the first, plus every tenth. Nothing that changed is dropped --
    # the status never changed here, so there is nothing else to keep.
    assert len(campaign.provider.receipts_kept) < reads // 5
    assert campaign.provider.receipts_suppressed > 100

    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    tally = driver["readiness"]["provider_reads"]
    assert tally["receipts_kept"] + tally["receipts_suppressed"] == tally["reads"]
    assert tally["receipts_suppressed"] > 100


def test_a_status_change_is_never_a_suppressed_receipt(campaign: Campaign) -> None:
    campaign.transport.ready_answers = [404]
    campaign.provider.delete_after_reads = 3
    result = campaign.run(bootstrap_deadline_seconds=2700.0)

    # Read 1 kept (first), reads 2-3 suppressed, read 4 kept (RUNNING ->
    # MISSING is a change), read 5 kept because the poll gives up on it.
    assert len(campaign.provider.receipts_kept) >= 2
    assert any("provider status: RUNNING -> MISSING" in note for note in result.notes)


def test_readiness_progress_reaches_stdout(
    campaign: Campaign, capsys: pytest.CaptureFixture[str]
) -> None:
    """Item 4: a 45-minute wait that prints nothing looks like a hung driver."""

    campaign.transport.ready_answers = [404]
    campaign.provider.log_lines = _log("[arena] bootstrap: downloading weights")
    campaign.run(bootstrap_deadline_seconds=2700.0, ready_poll_seconds=20.0)

    out = capsys.readouterr().out
    assert "waiting for pod" in out
    assert "HTTP 404" in out
    beats = [line for line in out.splitlines() if "still waiting" in line]
    assert len(beats) >= 8  # 45 minutes, one every five
    assert "[arena] bootstrap: downloading weights" in beats[0]


def test_the_ready_pod_receipt_still_records_the_read_tally(
    campaign: Campaign,
) -> None:
    """The tally is not a failure-only field; a PASS carries it too."""

    result = campaign.run()

    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    assert driver["readiness"]["ready_at"] is not None
    assert driver["readiness"]["provider_reads"]["reads"] >= 1


# --------------------------------------------------------- failure paths


def test_a_pod_that_never_warms_still_comes_back(campaign: Campaign) -> None:
    """The readiness deadline is a deadline, not a hope."""

    campaign.transport.stages = ["WARMING"]
    result = campaign.run(bootstrap_deadline_seconds=180.0, ready_poll_seconds=60.0)

    assert result.status == "ERROR"
    assert result.error is not None and "never reached READY" in result.error
    assert result.pages_attempted == 0
    assert campaign.provider.deleted == [POD_ID]
    assert result.pod_return.returned is True
    # No canary receipt: nothing was measured, so nothing is claimed.
    assert result.canary_receipt_path is None


def test_a_worker_that_crashes_while_loading_still_comes_back(
    campaign: Campaign,
) -> None:
    campaign.transport.stages = ["MODEL_LOADING", "CRASHED"]
    result = campaign.run()

    assert result.status == "ERROR"
    assert "CRASHED" in str(result.error)
    assert campaign.provider.deleted == [POD_ID]


def _fail_second_page(error_class: str):
    """A worker that fails exactly the second page with ``error_class``."""

    seen = {"n": 0}

    def override(job_id: str) -> dict[str, object]:
        seen["n"] += 1
        if seen["n"] == 2:
            return worker_response_body(
                job_id,
                status="FAILED",
                error_class=error_class,
                error_message=f"the adapter reported {error_class}",
                runtime_mode="bootstrap",
                runtime_image_digest=BOOTSTRAP_DIGEST,
            )
        return worker_response_body(
            job_id, runtime_mode="bootstrap", runtime_image_digest=BOOTSTRAP_DIGEST
        )

    return override


def test_a_broken_runtime_fails_the_canary_and_the_loop_still_finishes(
    campaign: Campaign,
) -> None:
    """A GPU_KERNEL fault is section 15.9's "quarantine the runtime" row."""

    campaign.transport.run_override = _fail_second_page("GPU_KERNEL")
    result = campaign.run()

    # The loop does not stop at the first failure: a canary judged only on the
    # pages that worked is not a canary.
    assert result.pages_attempted == 4
    assert result.pages_succeeded == 3
    assert result.status == "FAIL"
    assert result.canary_receipt_path is not None
    receipt = json.loads(result.canary_receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"
    assert receipt["failed_count"] == 1
    assert receipt["fail_reasons"]  # a FAIL always names why
    crashed = next(
        item for item in receipt["criteria"] if item["criterion"] == "zero_hard_crash"
    )
    assert crashed["passed"] is False
    assert campaign.provider.deleted == [POD_ID]


def test_a_capacity_event_is_recorded_but_does_not_condemn_the_runtime(
    campaign: Campaign,
) -> None:
    """D40: the Opus canary's INFRA_CAPACITY page stayed a capacity event.

    Section 15.9 gives INFRA_CAPACITY retries, so it is infrastructure, not a
    verdict on the model. The page is still counted as failed and still named
    in the driver notes -- it is visible, just not a condemnation.
    """

    campaign.transport.run_override = _fail_second_page("INFRA_CAPACITY")
    result = campaign.run()

    assert result.pages_succeeded == 3
    assert result.status == "PASS"
    receipt = json.loads(result.canary_receipt_path.read_text(encoding="utf-8"))
    assert receipt["failed_count"] == 1  # never hidden
    assert any("infrastructure event" in note for note in result.notes)


def test_a_failure_outside_the_taxonomy_is_not_assumed_transient(
    campaign: Campaign,
) -> None:
    """No silent fallback: an unnamed failure counts against the canary."""

    crashes, deterministic, notes = classify_page_failures(
        [{"status": "FAILED", "error_class": "SOMETHING_NEW", "case_key": "k"}]
    )
    assert (crashes, deterministic) == (0, 1)
    assert any("outside the section 16 taxonomy" in note for note in notes)


def test_a_wrong_model_revision_fails_the_canary_and_returns_the_pod(
    campaign: Campaign,
) -> None:
    campaign.transport.run_override = lambda job_id: worker_response_body(
        job_id,
        model_revision="b" * 40,
        runtime_mode="bootstrap",
        runtime_image_digest=BOOTSTRAP_DIGEST,
    )
    result = campaign.run()

    assert result.status == "FAIL"
    assert result.canary_receipt_path is not None
    receipt = json.loads(result.canary_receipt_path.read_text(encoding="utf-8"))
    assert any("not the pinned" in reason for reason in receipt["fail_reasons"])
    assert campaign.provider.deleted == [POD_ID]


def test_a_worker_running_another_image_is_refused_page_by_page(
    campaign: Campaign,
) -> None:
    """D15: the worker's digest must be the one the ledger provisioned."""

    campaign.transport.run_override = lambda job_id: worker_response_body(
        job_id,
        runtime_mode="bootstrap",
        runtime_image_digest="bootstrap:sha256:" + "9" * 64,
    )
    result = campaign.run()

    assert result.pages_succeeded == 0
    assert result.status in {"FAIL", "ERROR"}
    assert campaign.provider.deleted == [POD_ID]


def test_an_unexpected_exception_still_returns_the_pod(campaign: Campaign) -> None:
    """The `finally` is the load-bearing line; prove it with a surprise."""

    def explode(pod_id: str) -> Any:
        raise ZeroDivisionError("nobody predicted this")

    result = campaign.run(worker_factory=explode)

    assert result.status == "ERROR"
    assert "ZeroDivisionError" in str(result.error)
    assert campaign.provider.stopped == [POD_ID]
    assert campaign.provider.deleted == [POD_ID]
    assert result.pod_return.returned is True


def test_a_page_missing_from_disk_is_recorded_not_invented(
    campaign: Campaign,
) -> None:
    """A missing page is the corpus's problem, not the runtime's (15.9)."""

    (campaign.paths.root / "staged-public-core" / campaign.samples[1].image_path).unlink()
    result = campaign.run()

    assert result.pages_attempted == 4
    assert result.pages_succeeded == 3
    receipt = json.loads(result.canary_receipt_path.read_text(encoding="utf-8"))
    assert receipt["failed_count"] == 1
    assert any("quarantines the source" in note for note in result.notes)


def test_a_page_whose_bytes_do_not_match_the_manifest_is_never_dispatched(
    campaign: Campaign,
) -> None:
    page = campaign.paths.root / "staged-public-core" / campaign.samples[0].image_path
    page.write_bytes(b"these are not the bytes the manifest hashed")
    result = campaign.run()

    assert result.pages_succeeded == 3
    assert len(campaign.transport.run_calls) == 3  # the bad page never reached the GPU


def test_a_missing_bundle_receipt_refuses_before_a_pod_exists(
    campaign: Campaign,
) -> None:
    campaign.paths.bundle_receipt(MODEL_KEY).unlink()
    result = campaign.run()

    assert result.status == "ERROR"
    assert "BundleError" in str(result.error)
    assert campaign.created == []  # nothing was provisioned
    assert campaign.provider.deleted == []
    assert result.pod_return.returned is True  # nothing to return


def test_a_missing_prompt_registry_refuses_before_a_pod_exists(
    campaign: Campaign,
) -> None:
    (campaign.paths.prompt_registry_dir / "sha256.json").unlink()
    result = campaign.run()

    assert result.status == "ERROR"
    assert "PromptError" in str(result.error)
    assert campaign.created == []


def test_a_selection_the_manifest_does_not_carry_is_refused(
    campaign: Campaign,
) -> None:
    campaign.paths.canary_selection.write_text(
        json.dumps({"case_keys": ["omnidocbench-999999"]}), encoding="utf-8"
    )
    result = campaign.run()

    assert result.status == "ERROR"
    assert "not in the source manifest" in str(result.error)
    assert campaign.created == []


def test_a_provider_that_returns_no_pod_id_is_not_assumed_to_have_one(
    campaign: Campaign,
) -> None:
    result = campaign.run(create_pod=lambda digest, prompt: (None, {}))

    assert result.status == "ERROR"
    assert "did not return a pod id" in str(result.error)
    assert campaign.provider.deleted == []


def test_a_pod_still_listed_after_the_delete_is_not_called_returned(
    campaign: Campaign,
) -> None:
    """A delete request is not a return. Only an empty listing is."""

    campaign.provider.listing_survives = 99
    result = campaign.run()

    assert campaign.provider.deleted == [POD_ID]
    assert result.pod_return.returned is False
    assert result.pod_return.gone_from_v1 is False
    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    assert driver["pod_return"]["returned"] is False


def test_a_delete_that_the_provider_refuses_is_recorded_not_swallowed(
    campaign: Campaign,
) -> None:
    campaign.provider.delete_raises = RunPodClientError("HTTP 500 from the provider")
    result = campaign.run()

    assert any("delete_pod refused" in note for note in result.notes)
    assert result.pod_return.returned is False


# ------------------------------------------------------------- watchdog


def test_the_lifetime_watchdog_stops_and_deletes_without_the_main_thread() -> None:
    """D10/D20: two hours is two hours, whatever the driver is blocked on."""

    fired: list[float] = []
    clock = {"now": _at(0)}
    watchdog = CanaryWatchdog(
        lifetime_seconds=7200.0,
        tick_seconds=0.01,
        on_expire=fired.append,
        now=lambda: clock["now"],
    )
    assert watchdog.tick() is False
    assert fired == []
    clock["now"] = _at(7201)
    assert watchdog.tick() is True
    assert fired and fired[0] >= 7200.0
    # It fires once, not on every subsequent tick.
    assert watchdog.tick() is False
    assert len(fired) == 1


def test_a_watchdog_with_no_lifetime_is_refused() -> None:
    with pytest.raises(DriverError):
        CanaryWatchdog(lifetime_seconds=0.0, on_expire=lambda _: None)


def test_the_watchdog_thread_terminates_a_wedged_driver(campaign: Campaign) -> None:
    """The driver blocks; the timer -- not the `finally` -- returns the pod."""

    blocked = threading.Event()

    def wedge(pod_id: str) -> Any:
        # The pod exists and the main thread is stuck on it, exactly as it
        # would be on a socket read that never answers.
        blocked.wait(timeout=5.0)
        raise DriverError("released")

    result = campaign.run(
        worker_factory=wedge,
        start_watchdog=True,
        lifetime_seconds=0.05,
        watchdog_tick_seconds=0.01,
        now=None,  # the watchdog measures real elapsed time, not the poll clock
    )
    blocked.set()

    # Exactly one delete: the watchdog fired first and the `finally` did not
    # send a second request against a pod the provider had already removed.
    assert campaign.provider.deleted == [POD_ID]
    assert campaign.provider.stopped == [POD_ID]
    assert any("lifetime watchdog" in note for note in result.notes)


# ---------------------------------------------------------------- inputs


def test_load_page_bytes_refuses_a_page_whose_hash_disagrees(
    tmp_path: Path,
) -> None:
    sample = make_sample(1)
    page = tmp_path / sample.image_path
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_bytes(b"wrong bytes")
    with pytest.raises(DriverError, match="hashes to"):
        load_page_bytes(sample, staged_root=tmp_path)


def test_load_page_bytes_refuses_a_page_that_is_not_there(tmp_path: Path) -> None:
    with pytest.raises(DriverError, match="not on disk"):
        load_page_bytes(make_sample(1), staged_root=tmp_path)


def test_the_real_source_manifest_reads_every_row() -> None:
    """D14, against the actual file: 5,132 rows, all three benchmarks."""

    manifest = Path(__file__).resolve().parents[2] / "source_manifest.jsonl"
    samples = load_source_manifest(manifest)
    assert len(samples) == 5132
    assert {sample.benchmark for sample in samples} == {
        "omnidoc",
        "olmocr",
        "parsebench",
    }
    # D14's three mapped names all arrived, on every row.
    assert all(sample.source_sha256.startswith("sha256:") for sample in samples)
    assert all(sample.benchmark_revision for sample in samples)
    assert all(sample.image_path for sample in samples)
    # `original_source_sha256` is provenance and never enters the job id.
    assert not hasattr(samples[0], "original_source_sha256")


def _at(seconds: float):
    from datetime import UTC, datetime, timedelta

    return datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=seconds)


def _system_backfill(count: int) -> list[dict[str, object]]:
    """The chatty block: image pull progress, all of it earlier than the crash."""

    return [
        {
            "source": "system",
            "ts": f"2026-09-03T12:{index // 60:02d}:{index % 60:02d}Z",
            "line": f"pulling layer {index}: 84%",
        }
        for index in range(count)
    ]


def test_a_fatal_after_a_long_system_block_still_condemns_readiness(
    campaign: Campaign,
) -> None:
    """The other half of the GLM-OCR failure: the sources are not interleaved.

    ``receipts/canary-driver-glm_ocr.json`` carried 200 log lines and every one
    of them was source ``system`` -- image pull progress ending at 13:03Z. The
    ``[arena] FATAL`` the runtime printed at 13:14Z was not in it, because the
    endpoint returns container and system as separate sequences and a bounded
    tail over both keeps only whichever block comes last. Reading each source
    with its own tail is what puts the fatal line back in front of the verdict.
    """

    campaign.transport.ready_answers = [404]
    campaign.provider.desired_status = "RUNNING"
    campaign.provider.log_lines = [
        *_system_backfill(250),
        {
            "source": "stdout",
            "ts": "2026-09-03T13:14:19Z",
            "line": "[arena] bootstrap: starting model server",
        },
        {
            "source": "stderr",
            "ts": "2026-09-03T13:14:20Z",
            "line": "[arena] FATAL model server never became healthy",
        },
    ]
    result = campaign.run(bootstrap_deadline_seconds=2700.0, ready_poll_seconds=20.0)

    assert result.status == "ERROR"
    # One log cadence, not the 45-minute deadline.
    assert campaign.transport.ready_calls <= 1
    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    readiness = driver["readiness"]
    assert readiness["error_class"] == "MODEL_LOAD"
    assert readiness["signature"] == "[arena] FATAL"
    # Both sources were asked for by name, each with its own tail.
    assert "container" in campaign.provider.log_sources
    assert "system" in campaign.provider.log_sources
    assert None not in campaign.provider.log_sources
    tail = readiness["container_log_tail"]
    assert tail and tail[-1]["line"] == "[arena] FATAL model server never became healthy"


def test_a_failed_container_read_is_not_reported_as_a_silent_runtime(
    campaign: Campaign,
) -> None:
    """System lines alone would look like a runtime that printed nothing."""

    campaign.transport.ready_answers = [404]
    campaign.provider.log_lines = _system_backfill(10)
    campaign.provider.log_raises = RunPodClientError(
        "RunPod log stream failed for pod abc: ReadTimeout"
    )
    result = campaign.run(bootstrap_deadline_seconds=600.0, ready_poll_seconds=20.0)

    assert result.status == "ERROR"
    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    note = driver["readiness"]["container_log_note"]
    assert "failed" in note
    assert "no log lines" not in note


# ------------------------------ the ready body, and what the log read did


def test_a_crashed_worker_puts_its_last_error_in_the_receipt_and_the_failure(
    campaign: Campaign,
) -> None:
    """The 2026-09-03 18:39:20Z answer, with the half that was thrown away.

    ``readiness.last_status`` said "HTTP 200 stage=CRASHED" and nothing on disk
    said why. The body behind that status carries ``last_error``.
    """

    campaign.transport.stages = ["CRASHED"]
    campaign.transport.ready_extra = {
        "last_error": "RuntimeError: vLLM engine died during warm-up"
    }
    result = campaign.run(bootstrap_deadline_seconds=600.0, ready_poll_seconds=20.0)

    assert result.status == "ERROR"
    assert result.error is not None
    assert "vLLM engine died during warm-up" in result.error

    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    readiness = driver["readiness"]
    assert readiness["last_status"] == "HTTP 200 stage=CRASHED"
    body = readiness["last_ready_response"]
    assert body["stage"] == "CRASHED"
    assert body["last_error"] == "RuntimeError: vLLM engine died during warm-up"


def test_a_readiness_failure_with_no_parsed_body_records_none(
    campaign: Campaign,
) -> None:
    campaign.transport.ready_answers = [404]
    result = campaign.run(bootstrap_deadline_seconds=180.0, ready_poll_seconds=60.0)

    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    assert driver["readiness"]["last_ready_response"] is None


class _LoggingClient:
    """A provider that answers log reads and receipts what each read did."""

    def __init__(self, *, container: int, system: int, stopped: str = "quiet") -> None:
        self.execute = True
        self.asked: list[tuple[str | None, int]] = []
        self.receipts: list[Any] = []
        self._counts = {"container": container, "system": system}
        self._stopped = stopped

    def get_logs(
        self,
        pod_id: str,
        *,
        tail: int = 200,
        max_lines: int = 2000,
        source: str | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        self.asked.append((source, tail))
        count = self._counts.get(source or "container", 0)
        lines = tuple(
            {"source": source, "ts": f"2026-09-03T18:3{i // 60}:{i % 60:02d}Z",
             "line": f"{source} {i}"}
            for i in range(count)
        )
        self.receipts.append(
            _FakeReceipt(
                summary={
                    "source": source,
                    "tail_requested": tail,
                    "line_count": len(lines),
                    "stopped_because": self._stopped,
                }
            )
        )
        return lines


def test_the_diagnostic_read_asks_the_container_source_for_a_longer_tail() -> None:
    """194 lines that stop a minute short of the crash are not a diagnosis."""

    from arena.controller.driver import (
        DIAGNOSTIC_CONTAINER_TAIL_LINES,
        _readiness_diagnostics,
    )
    from arena.controller.run import LOG_TAIL_LINES, ReadinessError

    client = _LoggingClient(container=194, system=12)
    notes: list[str] = []
    record = _readiness_diagnostics(
        ReadinessError("worker never became READY", last_status="HTTP 404"),
        pod_id="pod_fake",
        clients=(client,),
        notes=notes,
    )

    assert client.asked == [
        ("container", DIAGNOSTIC_CONTAINER_TAIL_LINES),
        ("system", LOG_TAIL_LINES),
    ]
    note = record["container_log_note"]
    assert "container: 400 requested, 194 received, stopped_because=quiet" in note
    assert "system: 200 requested, 12 received, stopped_because=quiet" in note
    assert "206 line(s) from the provider log endpoint" in note
    reads = record["container_log_reads"]
    assert [entry["source"] for entry in reads] == ["container", "system"]


def test_the_reused_verdict_tail_still_says_what_the_read_asked_for(
    campaign: Campaign,
) -> None:
    """The 2026-09-03 note said "198 line(s)" and nothing about the drain.

    The verdict's own tail is reused rather than re-read -- the pod is about to
    be deleted -- so the read's accounting has to travel with it, or a tail cut
    short by the drain is indistinguishable from a runtime that stopped
    printing.
    """

    campaign.transport.ready_answers = [404]
    campaign.provider.log_lines = [
        {
            "source": "stderr",
            "ts": "2026-09-03T18:38:25Z",
            "line": "[arena] FATAL model server never became healthy",
        },
    ]
    result = campaign.run(bootstrap_deadline_seconds=2700.0, ready_poll_seconds=20.0)

    assert result.status == "ERROR"
    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    readiness = driver["readiness"]
    note = readiness["container_log_note"]
    assert "container: 200 requested, 1 received, stopped_because=quiet" in note
    assert [entry["source"] for entry in readiness["container_log_reads"]] == [
        "container",
        "system",
    ]
    # The periodic watch keeps the 200-line tail; only the diagnostic read
    # asks for more.
    assert campaign.provider.log_tails[0] == ("container", 200)


def test_a_pass_keeps_what_the_runtime_printed_while_serving_pages(
    campaign: Campaign,
) -> None:
    """D62: the readiness tail ends where the worker came up; the page-time log
    is the only account of a page that returned SUCCESS with nothing in it
    (mineru_vlm, pod r0yal3hocpipsm)."""

    campaign.provider.log_lines = [
        {
            "source": "stdout",
            "ts": "2026-09-03T21:40:35Z",
            "line": "layout returned 0 blocks for page 0",
        }
    ]
    result = campaign.run()

    assert result.status == "PASS"
    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    postrun = driver["postrun"]
    assert postrun["captured_at"] is not None
    assert postrun["container_log_tail"] is not None
    assert any("0 blocks" in str(entry.get("line")) for entry in postrun["container_log_tail"])
    assert postrun["container_log_reads"]
    # The pod was still there to be read: the capture ran before the delete.
    assert campaign.provider.log_sources.count("container") >= 1


def test_the_post_run_log_goes_through_the_same_secret_guard(
    campaign: Campaign,
) -> None:
    campaign.provider.log_lines = [
        {
            "source": "stdout",
            "ts": "2026-09-03T21:40:35Z",
            "line": (
                "GET https://acct.r2.cloudflarestorage.com/b/o"
                "?X-Amz-Signature=deadbeefdeadbeefdeadbeef 200"
            ),
        }
    ]
    result = campaign.run()

    assert result.status == "PASS"
    text = result.driver_receipt_path.read_text(encoding="utf-8")
    driver = json.loads(text)
    assert driver["postrun"]["container_log_tail"] is None
    assert "withheld" in driver["postrun"]["container_log_note"]
    assert "X-Amz-Signature" not in text


def test_a_pass_keeps_what_the_runtime_printed_while_coming_up(
    campaign: Campaign,
) -> None:
    """D71: on a pass there is no readiness tail, and the page-time tail (D62)
    starts after the bootstrap lines have scrolled away. The self-test verdict
    and the model server's weight-loading warnings live only in a read taken
    at READY (mineru_vlm, pod t0e8yz3oobso7i)."""

    campaign.provider.log_lines = [
        {
            "source": "stdout",
            "ts": "2026-09-04T00:05:35Z",
            "line": "[arena] selftest: mineru CLI exit=0 markdown_bytes=0",
        }
    ]
    result = campaign.run()

    assert result.status == "PASS"
    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    bootstrap = driver["bootstrap_log"]
    assert bootstrap["captured_at"] is not None
    assert bootstrap["container_log_tail"] is not None
    assert any("selftest" in str(entry.get("line")) for entry in bootstrap["container_log_tail"])
    assert bootstrap["container_log_reads"]
    # Two reads of the container log on a pass: at READY and after the pages.
    assert campaign.provider.log_sources.count("container") >= 2
    assert bootstrap["captured_at"] <= driver["postrun"]["captured_at"]


def test_the_ready_time_log_read_failure_is_recorded_not_fatal(
    campaign: Campaign,
) -> None:
    """D71: a provider that cannot answer the READY-time read leaves a note and
    the canary still runs its pages; a missing tail is recorded as missing."""

    campaign.provider.log_raises = RunPodClientError("HTTP 502 from the provider")
    result = campaign.run()

    assert result.status == "PASS"
    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    assert driver["bootstrap_log"]["container_log_tail"] is None
    assert "log read failed" in driver["bootstrap_log"]["container_log_note"]
    assert any("ready-time container log not captured" in note for note in driver["notes"])
