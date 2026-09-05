"""The D72 full-run driver, one stop rule at a time.

Same doubles as the canary driver tests: a fake provider, a fake worker
transport, a virtual clock. Every test ends the same way the canary tests do --
**every pod came back** -- and most of them also check that the queue and the
frozen manifest say what the driver said.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import pytest
from arena.controller.driver import DriverError
from arena.controller.freeze import FreezeError
from arena.controller.full_run import (
    MAX_CONSECUTIVE_FAILURES,
    OPERATOR_STOP,
    run_full,
    stop_file,
)
from arena.controller.paths import CampaignPaths
from arena.controller.plan import ModelPlanEntry
from arena.controller.prompts import PromptRef
from arena.controller.queue import CampaignQueue
from tests.controller.conftest import (
    MODEL_KEY,
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
from tests.controller.test_canary_driver import (
    BOOTSTRAP_DIGEST,
    BUNDLE_SHA,
    FakeProvider,
    VirtualClock,
    _runtime,
    _snapshot,
)

PAGE_COUNT = 4


@dataclass
class FullCampaign:
    paths: CampaignPaths
    provider: FakeProvider
    transport: FakeWorkerTransport
    samples: tuple
    clock: VirtualClock = field(default_factory=VirtualClock)
    created: list = field(default_factory=list)
    seconds_per_page: float = 0.0
    after_page: Any = None

    def create_pod(
        self, image_digest: str, prompt: PromptRef
    ) -> tuple[str | None, Mapping[str, object]]:
        pod_id = f"podfakefull{len(self.created)}"
        self.created.append((pod_id, image_digest, prompt))
        self.provider.add(pod_id)
        return pod_id, {"name": f"arena-paddleocr-vl-1-6-w{len(self.created) - 1}", "env": {}}

    def page_bytes(self, sample: Any) -> bytes:
        # The virtual clock only moves when something sleeps; a page that "takes"
        # time moves it here so the lifetime rule has something to measure.
        if self.seconds_per_page:
            self.clock.sleep(self.seconds_per_page)
        if self.after_page is not None:
            self.after_page(sample)
        return sample_bytes(sample)

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
            "worker_factory": lambda pod_id: fake_worker_client(self.transport, pod_id=pod_id),
            "page_bytes": self.page_bytes,
            "authorization_receipt_path": "receipts/authorizations/phase2-full-run.json",
            "authorization_receipt_sha256": "d" * 64,
            "bootstrap_deadline_seconds": 2700.0,
            "ready_poll_seconds": 20.0,
            "sleep": self.clock.sleep,
            "now": self.clock,
            "start_watchdog": False,
        }
        kwargs.update(overrides)
        return run_full(**kwargs)

    def counts(self) -> dict[str, int]:
        with CampaignQueue(self.paths.queue_db) as queue:
            return dict(queue.counts_by_state(model_key=MODEL_KEY))


@pytest.fixture
def full(paths: CampaignPaths, entry: ModelPlanEntry) -> FullCampaign:
    samples = tuple(make_sample(index) for index in range(1, PAGE_COUNT + 1))
    write_source_manifest(paths.source_manifest, samples)
    # The conftest entry allows baked only; a Full Run on a bootstrap pod
    # needs the runtime to allow bootstrap as well (D25), which is what the
    # real runtime.json files of the bootstrap canaries say.
    write_model_registry(
        paths.model_registry, replace(entry, runtime_mode_allowed=("baked", "bootstrap"))
    )
    write_prompt_registry(paths, text="")
    write_bundle_receipt(paths, bundle_sha256=BUNDLE_SHA)
    # D74: run_full is the bootstrap path, so section 15.1 wants a founder
    # waiver on disk; the fixture carries one and one test takes it away.
    _write_waiver(paths)
    provider = FakeProvider()
    provider.log_lines = [
        {"source": "stdout", "ts": "2026-09-04T01:00:00Z", "line": "[arena] selftest: ok"}
    ]
    # The worker answers with the bootstrap digest the pod was provisioned
    # with (D15); a body naming another runtime is refused by dispatch_page.
    transport = FakeWorkerTransport(
        model_key=MODEL_KEY,
        run_override=lambda job_id: worker_response_body(
            job_id, runtime_mode="bootstrap", runtime_image_digest=BOOTSTRAP_DIGEST
        ),
    )
    return FullCampaign(paths=paths, provider=provider, transport=transport, samples=samples)


def _write_waiver(paths: CampaignPaths) -> None:
    waiver = paths.bootstrap_waiver(MODEL_KEY)
    waiver.parent.mkdir(parents=True, exist_ok=True)
    waiver.write_text(
        json.dumps({"model_key": MODEL_KEY, "authorized_by": "founder"}), encoding="utf-8"
    )


def _all_returned(full: FullCampaign, result: Any) -> None:
    assert result.all_pods_returned
    for pod_id, _digest, _prompt in full.created:
        assert pod_id in full.provider.stopped
        assert pod_id in full.provider.deleted


def test_a_full_run_dispatches_every_page_and_freezes(full: FullCampaign) -> None:
    result = full.run()

    assert result.status == "COMPLETE", result.notes
    assert result.stop_reason == "nothing_left"
    assert result.pages_attempted == PAGE_COUNT
    assert result.pages_succeeded == PAGE_COUNT
    assert len(result.pods) == 1
    assert result.pods[0].stop_reason == "pod_exhausted"
    assert full.counts()["SUCCESS"] == PAGE_COUNT
    assert result.freeze is not None and result.freeze["frozen"] is True
    assert full.paths.frozen_manifest(MODEL_KEY).is_file()
    assert full.paths.frozen_marker(MODEL_KEY).is_file()
    assert result.run_summary_path is not None and result.run_summary_path.is_file()
    driver = json.loads(result.driver_receipt_path.read_text(encoding="utf-8"))
    assert driver["schema"] == "tavonel.arena.full_run_driver.v1"
    pod = driver["pods"][0]
    # D71 at READY and D62 after the pages, both on the full run too.
    assert pod["bootstrap_log"]["container_log_tail"] is not None
    assert pod["postrun"]["container_log_tail"] is not None
    _all_returned(full, result)


def test_a_second_invocation_finds_nothing_left_and_rents_no_pod(full: FullCampaign) -> None:
    first = full.run()
    assert first.status == "COMPLETE"
    rented = len(full.created)

    second = full.run()

    assert second.stop_reason == "nothing_left"
    assert second.pages_attempted == 0
    assert len(full.created) == rented
    # Everything is settled, so the freeze is rebuilt from the same receipts.
    assert second.status == "COMPLETE"


def test_the_lifetime_margin_ends_the_pod_and_the_next_pod_resumes(full: FullCampaign) -> None:
    """D10: six hours less the margin. Here 100 s less 30 s, at 40 s a page, so
    the second page crosses the line and the third page waits for pod two."""

    full.seconds_per_page = 40.0
    result = full.run(lifetime_seconds=100.0, lifetime_margin_seconds=30.0, max_pods=3)

    assert result.status == "COMPLETE", result.notes
    assert [pod.stop_reason for pod in result.pods][:1] == ["lifetime_margin"]
    assert len(result.pods) == 2
    assert result.pages_attempted == PAGE_COUNT
    assert full.counts()["SUCCESS"] == PAGE_COUNT
    assert [pod.pod_id for pod in result.pods] == ["podfakefull0", "podfakefull1"]
    _all_returned(full, result)


def test_max_pods_stops_the_invocation_with_pages_pending(full: FullCampaign) -> None:
    full.seconds_per_page = 40.0
    result = full.run(lifetime_seconds=100.0, lifetime_margin_seconds=30.0, max_pods=1)

    assert result.status == "PARTIAL"
    assert result.stop_reason == "max_pods"
    assert len(result.pods) == 1
    assert full.counts()["PENDING"] == PAGE_COUNT - 2
    assert result.freeze is None
    _all_returned(full, result)


def test_a_refused_next_pod_authorization_is_recorded_and_rents_nothing(
    full: FullCampaign,
) -> None:
    full.seconds_per_page = 40.0
    result = full.run(
        lifetime_seconds=100.0,
        lifetime_margin_seconds=30.0,
        max_pods=3,
        next_pod_allowed=lambda index: (index == 0, f"pod {index}: receipt covers one pod"),
    )

    assert result.status == "STOPPED"
    assert result.stop_reason == "authorization"
    assert len(result.pods) == 1
    assert len(full.created) == 1
    assert any("BLOCKED" in note for note in result.notes)
    _all_returned(full, result)


def test_the_operator_stop_file_ends_the_run_and_is_consumed(full: FullCampaign) -> None:
    def after_first_page(sample: Any) -> None:
        marker = stop_file(full.paths, MODEL_KEY)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("stop\n", encoding="utf-8")

    full.after_page = after_first_page
    result = full.run(max_pods=3)

    assert result.status == "PARTIAL"
    assert result.stop_reason == OPERATOR_STOP
    assert result.pods[0].stop_reason == OPERATOR_STOP
    assert result.pages_attempted == 1
    assert not stop_file(full.paths, MODEL_KEY).exists()
    assert full.counts()["PENDING"] == PAGE_COUNT - 1
    _all_returned(full, result)


def test_a_page_limit_is_a_rehearsal_not_a_run(full: FullCampaign) -> None:
    result = full.run(page_limit=2, max_pods=3)

    assert result.status == "PARTIAL"
    assert result.stop_reason == "page_limit"
    assert result.pages_attempted == 2
    assert len(result.pods) == 1
    assert full.counts()["PENDING"] == PAGE_COUNT - 2
    _all_returned(full, result)


def test_a_bootstrap_runtime_without_a_waiver_rents_nothing(
    full: FullCampaign, entry: ModelPlanEntry
) -> None:
    """Section 15.1 via ``eligibility``: bootstrap is a canary path unless the
    founder waived it on disk. The refusal happens before ``create_pod``, and
    it fires even for a runtime that also allows baked (D74)."""

    write_model_registry(
        full.paths.model_registry, replace(entry, runtime_mode_allowed=("baked", "bootstrap"))
    )
    full.paths.bootstrap_waiver(MODEL_KEY).unlink()

    result = full.run()

    assert result.status == "ERROR"
    assert "waiver" in (result.error or "")
    assert full.created == []
    assert result.pods == ()


def test_a_founder_waiver_lets_a_bootstrap_runtime_run(
    full: FullCampaign, entry: ModelPlanEntry
) -> None:
    bootstrap_entry = replace(entry, runtime_mode_allowed=("bootstrap",))
    write_model_registry(full.paths.model_registry, bootstrap_entry)

    result = full.run()

    assert result.status == "COMPLETE", result.notes
    assert any("waiver" in note for note in result.notes)
    _all_returned(full, result)


def test_consecutive_failures_stop_the_run_instead_of_renting_the_next_pod(
    full: FullCampaign,
) -> None:
    """A runtime that answers nothing usable twenty times in a row is broken,
    not unlucky; the next pod is not rented to prove it again."""

    samples = tuple(make_sample(index) for index in range(1, MAX_CONSECUTIVE_FAILURES + 6))
    write_source_manifest(full.paths.source_manifest, samples)
    full.transport.run_status = 500
    result = full.run(max_pods=3)

    assert result.status == "STOPPED"
    assert result.stop_reason == "consecutive_failures"
    assert len(result.pods) == 1
    assert result.pods[0].pages_succeeded == 0
    assert result.pods[0].pages_attempted >= MAX_CONSECUTIVE_FAILURES
    _all_returned(full, result)


def test_a_pod_that_never_comes_up_is_an_error_and_is_returned(full: FullCampaign) -> None:
    full.transport.ready_answers = [404]
    result = full.run(bootstrap_deadline_seconds=120.0, max_pods=3)

    assert result.status == "ERROR"
    assert result.stop_reason == "pod_error"
    assert len(result.pods) == 1
    assert result.pods[0].error is not None and "Readiness" in result.pods[0].error
    assert result.pods[0].readiness.get("container_log_tail") is not None
    assert full.counts()["PENDING"] == PAGE_COUNT
    _all_returned(full, result)


def test_freeze_refusal_is_a_note_not_a_crash(full: FullCampaign, monkeypatch: Any) -> None:
    import arena.controller.full_run as module

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise FreezeError("a receipt is missing its raw file")

    monkeypatch.setattr(module, "freeze_model", refuse)
    result = full.run()

    assert result.status == "PARTIAL"
    assert result.freeze is None
    assert any("freeze refused" in note for note in result.notes)
    _all_returned(full, result)


def _verdict_receipt(full: FullCampaign, status: str, eligible: bool) -> None:
    update = full.paths.registry_update(MODEL_KEY)
    update.parent.mkdir(parents=True, exist_ok=True)
    update.write_text(
        json.dumps(
            {
                "schema": "tavonel.arena.registry_update.v1",
                "campaign_id": "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1",
                "model_key": MODEL_KEY,
                "fields": {"canary_status": status, "full_run_eligible": eligible},
                "source": f"receipts/canary-{MODEL_KEY}.json",
                "proposed_at": "2026-09-04T00:17:25Z",
            }
        ),
        encoding="utf-8",
    )


def test_a_receipted_canary_pass_makes_a_pending_registry_entry_eligible(
    full: FullCampaign, entry: ModelPlanEntry
) -> None:
    """D74: model_registry.json stays PENDING by design; the canary driver's
    registry-update receipt carries the verdict, and the gate reads it."""

    write_model_registry(
        full.paths.model_registry,
        replace(
            entry,
            canary_status="PENDING",
            full_run_eligible=False,
            runtime_mode_allowed=("baked", "bootstrap"),
        ),
    )
    _verdict_receipt(full, "PASS", True)

    result = full.run()

    assert result.status == "COMPLETE", result.notes
    assert any("canary verdict PASS" in note for note in result.notes)
    _all_returned(full, result)


def test_without_a_receipted_verdict_a_pending_entry_is_refused(
    full: FullCampaign, entry: ModelPlanEntry
) -> None:
    write_model_registry(
        full.paths.model_registry,
        replace(
            entry,
            canary_status="PENDING",
            full_run_eligible=False,
            runtime_mode_allowed=("baked", "bootstrap"),
        ),
    )

    result = full.run()

    assert result.status == "ERROR"
    assert "canary_status is PENDING" in (result.error or "")
    assert full.created == []


def test_a_receipted_canary_fail_is_refused_even_if_the_registry_said_pass(
    full: FullCampaign,
) -> None:
    _verdict_receipt(full, "FAIL", False)

    result = full.run()

    assert result.status == "ERROR"
    assert "canary_status is FAIL" in (result.error or "")
    assert full.created == []


def test_a_malformed_verdict_receipt_is_refused_not_ignored(full: FullCampaign) -> None:
    update = full.paths.registry_update(MODEL_KEY)
    update.parent.mkdir(parents=True, exist_ok=True)
    update.write_text(
        json.dumps({"schema": "something-else", "model_key": MODEL_KEY}), encoding="utf-8"
    )

    result = full.run()

    assert result.status == "ERROR"
    assert "registry_update.v1" in (result.error or "")
    assert full.created == []


def test_a_runtime_that_forbids_bootstrap_is_refused_before_a_pod(
    full: FullCampaign,
) -> None:
    """D25/D36 through the gate: run_full is the bootstrap path, and a runtime
    whose runtime.json allows only baked does not get a bootstrap Full Run."""

    baked_only = replace(_runtime(full.paths), runtime_mode_allowed=("baked",))

    result = full.run(runtime=baked_only)

    assert result.status == "ERROR"
    assert "not allowed" in (result.error or "")
    assert full.created == []


def test_the_runtimes_own_file_decides_the_modes_not_a_stale_registry(
    full: FullCampaign, entry: ModelPlanEntry
) -> None:
    """D77: hpd_parsing's runtime.json was corrected to keep both modes and
    its canary then passed on a bootstrap pod, while model_registry.json --
    written once by ``registry resolve`` -- still said baked only. The refusal
    named runtime.json and quoted a list that had not come from it."""

    write_model_registry(
        full.paths.model_registry, replace(entry, runtime_mode_allowed=("baked",))
    )

    result = full.run()

    assert result.status == "COMPLETE", result.notes
    assert any("D77" in note for note in result.notes)


# ------------------------------------------------------------- D76 slices

SLICE_PAGES = 20
SLICE_SHARD_SIZE = 10


def _widen(full: FullCampaign, entry: ModelPlanEntry) -> None:
    """Twenty pages in shards of ten, so the plan has two shards to split.

    The masterplan 15.6 band puts the smallest legal shard at ten pages, so a
    four-page manifest can only ever be one shard, and one shard cannot show
    that two drivers stay out of each other's way.
    """

    samples = tuple(make_sample(index) for index in range(1, SLICE_PAGES + 1))
    write_source_manifest(full.paths.source_manifest, samples)
    write_model_registry(
        full.paths.model_registry,
        replace(
            entry,
            runtime_mode_allowed=("baked", "bootstrap"),
            shard_size=SLICE_SHARD_SIZE,
        ),
    )


def test_a_shard_slice_runs_only_its_own_pages(
    full: FullCampaign, entry: ModelPlanEntry
) -> None:
    """D76: one driver, one slice. It stops when *its* shards are empty, not
    when the model's are."""

    _widen(full, entry)

    result = full.run(shard_index=0, shard_count=2)

    assert result.stop_reason == "nothing_left", result.notes
    assert any("shard slice 1/2" in note for note in result.notes)
    assert result.pages_succeeded == SLICE_SHARD_SIZE
    assert result.status == "PARTIAL"


def test_two_shard_slices_together_run_every_page_exactly_once(
    full: FullCampaign, entry: ModelPlanEntry
) -> None:
    """The slices are disjoint and cover the model, so the pages add up, each
    slice rents its own pod, and the last one out freezes the model."""

    _widen(full, entry)

    first = full.run(shard_index=0, shard_count=2)
    second = full.run(shard_index=1, shard_count=2)

    assert first.pages_attempted + second.pages_attempted == SLICE_PAGES
    assert first.pages_succeeded + second.pages_succeeded == SLICE_PAGES
    assert len(full.created) == 2
    assert second.status == "COMPLETE", second.notes


def test_a_slice_leaves_another_slices_in_flight_job_alone(
    full: FullCampaign, entry: ModelPlanEntry
) -> None:
    """A driver returns stale RUNNING jobs to PENDING when it starts. It must
    do that only inside its own slice: a page another driver is running right
    now would otherwise be handed to a second pod and paid for twice."""

    _widen(full, entry)
    # Plan the queue without running anything, then put one page of the first
    # slice's shard in flight, as a driver that is still working would.
    full.run(shard_index=0, shard_count=2, page_limit=1)
    with CampaignQueue(full.paths.queue_db) as queue:
        pending = queue.pending_jobs(model_key=MODEL_KEY, limit=1000)
        first_slice_shard = sorted({job.shard_id for job in pending})[0]
        victim = next(job for job in pending if job.shard_id == first_slice_shard)
        queue.mark_running(victim.inference_job_id, "another-drivers-worker")

    second = full.run(shard_index=1, shard_count=2)

    with CampaignQueue(full.paths.queue_db) as queue:
        running = {
            job.inference_job_id
            for job in queue.jobs_for_model(MODEL_KEY, state="RUNNING")
        }
    assert victim.inference_job_id in running, second.notes


def test_a_slice_outside_its_count_is_refused(full: FullCampaign) -> None:
    with pytest.raises(DriverError, match="shard_index"):
        full.run(shard_index=2, shard_count=2)

    assert full.created == []


def test_a_shard_index_without_a_count_is_refused(full: FullCampaign) -> None:
    with pytest.raises(DriverError, match="together"):
        full.run(shard_index=0)

    assert full.created == []


# --------------------------------------------------------------- D81 retry


def test_an_operational_failure_goes_back_to_pending_and_is_run_again(
    full: FullCampaign,
) -> None:
    """D81: a pod that dies mid-dispatch fails its page with INFRA_NETWORK.
    That is the pod's failure, not the model's answer, and the masterplan's
    retry table allows three attempts, so the page must come back.

    The transport reads ``run_status`` before it calls the override, so the
    override sets the status the *next* call will answer with: the first
    dispatch gets the 500 this test starts with, and everything after it
    succeeds.
    """

    calls = {"n": 0}

    def one_bad_answer(job_id: str) -> dict[str, object]:
        calls["n"] += 1
        full.transport.run_status = 200
        return worker_response_body(
            job_id, runtime_mode="bootstrap", runtime_image_digest=BOOTSTRAP_DIGEST
        )

    full.transport.run_status = 500
    full.transport.run_override = one_bad_answer

    result = full.run()

    assert result.status == "COMPLETE", result.notes
    assert result.pages_succeeded == PAGE_COUNT
    assert full.counts().get("FAILED", 0) == 0
    # ``mark_failed`` has already spent one of the three, so the note the
    # driver records for the first requeue reads 2/3.
    assert any(
        "INFRA_NETWORK" in note and "allows retry" in note
        for pod in result.pods
        for note in pod.notes
    )
    assert calls["n"] == PAGE_COUNT + 1


def test_a_page_that_keeps_failing_settles_after_its_allowance(
    full: FullCampaign,
) -> None:
    """The other half: the retry table bounds the attempts, so a page that
    always fails is decided rather than dispatched forever."""

    calls = {"n": 0}

    def always_bad(job_id: str) -> dict[str, object]:
        calls["n"] += 1
        full.transport.run_status = 500
        return {"error": "worker died"}

    full.transport.run_status = 500
    full.transport.run_override = always_bad

    result = full.run()

    counts = full.counts()
    assert counts.get("PENDING", 0) == 0
    assert counts.get("FAILED", 0) == PAGE_COUNT
    assert result.status in ("COMPLETE", "PARTIAL", "STOPPED"), result.notes
    # One dispatch plus the three retries INFRA_NETWORK is allowed, per page.
    assert calls["n"] == PAGE_COUNT * 4
