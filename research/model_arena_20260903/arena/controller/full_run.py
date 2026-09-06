"""The Phase 2 full-run driver -- ARENA_CONTRACT 11.7 D72.

``run --execute`` used to provision one pod and return: nothing dispatched a
page, nothing froze, and the pod's return depended on the operator. The canary
driver (D20) already owns the shape that fixes this -- gate, provision, poll
readiness, dispatch, drain, **stop and delete in a finally**, confirm gone,
ledger -- and this module runs that shape over every page the queue still
holds, pod after pod, instead of over fifteen selected pages once:

    bundle receipt (D21) -> eligibility (canary PASS, baked or waiver)
      -> plan every manifest page into the queue (idempotent, section 9.3)
      -> [ provision -> readiness -> READY-time log (D71)
           -> dispatch every PENDING page in shard order, one at a time,
              checkpointed by run.dispatch_page
           -> stop rule -> drain -> post-run log (D62)
           -> stop+delete in a finally -> confirm gone -> ledger ]  x pods
      -> run summary -> freeze when nothing is left undecided

Stop rules, checked after every page: the operator's STOP file, a page limit
for rehearsals, the pod's D10 lifetime less a margin (the next pod resumes),
the section 15.13 budget caps, and a run of consecutive failures long enough
to say the runtime is broken rather than the page. A pod that ends on the
lifetime margin is followed by another only when the caller's
``next_pod_allowed`` says the authorization still covers it -- a receipt
written for one pod's ceiling never pays for six by accident.

Everything external is injected, exactly as in the canary driver, so every one
of those paths is a test rather than a hope. Nothing here touches the model
registry's canary verdict; a Full Run is judged by its receipts and its frozen
manifest.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from arena.constants import (
    BUDGET_HARD_CAP_USD,
    BUDGET_SOFT_CAP_USD,
    CAMPAIGN_ID,
    STAGED_PUBLIC_CORE_ROOT,
)
from arena.controller.bundle import BundleError, resolve_bundle_sha256
from arena.controller.driver import (
    DEFAULT_BOOTSTRAP_DEADLINE_SECONDS,
    DEFAULT_READY_POLL_SECONDS,
    PROVIDER_RECEIPT_EVERY,
    WATCHDOG_TICK_SECONDS,
    CanaryWatchdog,
    DriverError,
    PodReturn,
    _confirm_gone,
    _mark_ready,
    _pod_facts,
    _pod_probe,
    _postrun_diagnostics,
    _price_created_gpu,
    _read_log_tail,
    _readiness_diagnostics,
    _ReadTally,
    _record_pod,
    _spent_usd,
    _status_of,
    _worker_last_error,
    _write_ledger,
    load_page_bytes,
)
from arena.controller.events import EventLog
from arena.controller.freeze import FreezeError, freeze_model
from arena.controller.paths import CampaignPaths
from arena.controller.plan import (
    ModelPlanEntry,
    PlanError,
    SourceSample,
    build_plan,
    dispatch_order,
    load_model_registry,
    load_source_manifest,
)
from arena.controller.prompts import PromptError, PromptRef, resolve_prompt
from arena.controller.queue import CampaignQueue, JobRecord, QueueError
from arena.controller.retry import decide
from arena.controller.run import (
    LOG_TAIL_LINES,
    POD_MISSING,
    Eligibility,
    PageOutcome,
    ReadinessError,
    RunError,
    dispatch_page,
    eligibility,
    entry_with_canary_verdict,
    poll_until_ready,
    write_run_summary,
)
from arena.controller.runtime_spec import RuntimeSpecView
from arena.controller.watchdogs import BudgetAssessment, BudgetWatchdog
from arena.core.ids import bootstrap_image_digest
from arena.provider.runpod_pods import PriceSnapshot, RunPodClientError, RunPodPodsClient
from arena.provider.runpod_v1 import RunPodV1Client
from arena.provider.safety import utc_now_iso, write_json_atomic

__all__ = [
    "FULL_RUN_LIFETIME_MARGIN_SECONDS",
    "FULL_RUN_LIFETIME_SECONDS",
    "MAX_CONSECUTIVE_FAILURES",
    "OPERATOR_STOP",
    "STOP_FILE_NAME",
    "FullRunDriverResult",
    "PodAttempt",
    "run_full",
    "stop_file",
]

# D10: a full-run pod lives at most six hours. The margin is how long before
# that the driver stops taking new pages, so the page in flight and the
# teardown both finish inside the lifetime rather than under the watchdog.
FULL_RUN_LIFETIME_SECONDS: Final = 6 * 3600
FULL_RUN_LIFETIME_MARGIN_SECONDS: Final = 15 * 60
# Twenty pages failing in a row is not twenty hard pages; it is a runtime that
# stopped answering. The next pod is not rented to find out again.
MAX_CONSECUTIVE_FAILURES: Final = 20
STOP_FILE_NAME: Final = "STOP"
OPERATOR_STOP: Final = "operator_stop"
UNSETTLED_STATES: Final = ("PENDING", "ASSIGNED", "RUNNING", "PAUSED")
# Stop reasons after which the run does not rent another pod.
_TERMINAL_STOPS: Final = frozenset(
    {"budget_hard_cap", "consecutive_failures", OPERATOR_STOP, "page_limit", "authorization"}
)


def stop_file(paths: CampaignPaths, model_key: str) -> Path:
    """``runs/<model_key>/STOP``: touch it and the driver finishes the page it
    is on, drains, returns the pod and writes its receipts (D63's rule, applied
    to the GPU lane)."""

    return paths.model_run_dir(model_key) / STOP_FILE_NAME


@dataclass(frozen=True, slots=True)
class PodAttempt:
    """One pod's share of the run, receipted whatever happened to it."""

    index: int
    pod_id: str | None
    gpu_type: str
    hourly_rate_usd: float | None
    provisioned_at: str
    ready_at: str | None
    finished_at: str
    pages_attempted: int
    pages_succeeded: int
    pages_failed: int
    stop_reason: str | None
    error: str | None
    pod_return: PodReturn | None
    ledger_path: Path | None
    notes: tuple[str, ...]
    pod_summary: Mapping[str, object] = field(default_factory=dict)
    teardown: Mapping[str, object] = field(default_factory=dict)
    readiness: Mapping[str, object] = field(default_factory=dict)
    bootstrap_log: Mapping[str, object] = field(default_factory=dict)
    postrun: Mapping[str, object] = field(default_factory=dict)
    budget: Mapping[str, object] | None = None

    @property
    def returned(self) -> bool:
        return self.pod_id is None or (self.pod_return is not None and self.pod_return.returned)

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "pod_id": self.pod_id,
            "gpu_type": self.gpu_type,
            "hourly_rate_usd": self.hourly_rate_usd,
            "provisioned_at": self.provisioned_at,
            "ready_at": self.ready_at,
            "finished_at": self.finished_at,
            "pages_attempted": self.pages_attempted,
            "pages_succeeded": self.pages_succeeded,
            "pages_failed": self.pages_failed,
            "stop_reason": self.stop_reason,
            "error": self.error,
            "pod_return": None if self.pod_return is None else _pod_return_dict(self.pod_return),
            "ledger_path": None if self.ledger_path is None else str(self.ledger_path),
            "notes": list(self.notes),
            "pod_summary": dict(self.pod_summary),
            "pod_teardown": dict(self.teardown),
            "readiness": dict(self.readiness),
            "bootstrap_log": dict(self.bootstrap_log),
            "postrun": dict(self.postrun),
            "budget": None if self.budget is None else dict(self.budget),
        }


@dataclass(frozen=True, slots=True)
class FullRunDriverResult:
    model_key: str
    status: str
    stop_reason: str | None
    started_at: str
    finished_at: str
    pages_attempted: int
    pages_succeeded: int
    pods: tuple[PodAttempt, ...]
    job_counts: Mapping[str, int]
    run_summary_path: Path | None
    freeze: Mapping[str, object] | None
    driver_receipt_path: Path | None
    error: str | None
    notes: tuple[str, ...]

    @property
    def all_pods_returned(self) -> bool:
        return all(attempt.returned for attempt in self.pods)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.arena.full_run_driver.v1",
            "campaign_id": CAMPAIGN_ID,
            "model_key": self.model_key,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pages_attempted": self.pages_attempted,
            "pages_succeeded": self.pages_succeeded,
            "pods": [attempt.to_dict() for attempt in self.pods],
            "all_pods_returned": self.all_pods_returned,
            "job_counts": dict(self.job_counts),
            "run_summary_path": (
                None if self.run_summary_path is None else str(self.run_summary_path)
            ),
            "freeze": None if self.freeze is None else dict(self.freeze),
            "driver_receipt_path": (
                None if self.driver_receipt_path is None else str(self.driver_receipt_path)
            ),
            "error": self.error,
            "notes": list(self.notes),
        }


def _pod_return_dict(pod_return: PodReturn) -> dict[str, object]:
    return {
        "returned": pod_return.returned,
        "gone_from_v1": pod_return.gone_from_v1,
        "gone_from_v2": pod_return.gone_from_v2,
    }


def _stop_requested(paths: CampaignPaths, model_key: str) -> bool:
    """The operator's STOP file, consumed on read (D63)."""

    marker = stop_file(paths, model_key)
    if not marker.is_file():
        return False
    with contextlib.suppress(OSError):
        marker.unlink()
    return True


def _counts(paths: CampaignPaths, model_key: str) -> dict[str, int]:
    with CampaignQueue(paths.queue_db) as queue:
        return dict(queue.counts_by_state(model_key=model_key))


def _unsettled(counts: Mapping[str, int]) -> int:
    return sum(int(counts.get(state, 0)) for state in UNSETTLED_STATES)


def _with_runtime_modes(
    entry: ModelPlanEntry,
    runtime: RuntimeSpecView,
    say: Callable[[str], None],
) -> ModelPlanEntry:
    """The modes this runtime permits, taken from its own file (D77).

    ``model_registry.json`` is written by ``arena.registry resolve`` and is a
    snapshot: hpd_parsing's runtime.json was later corrected to keep both
    modes -- its canary then ran, and passed, on a bootstrap pod -- while the
    registry still carried ``["baked"]``, so the Full Run was refused with a
    D25 message that named runtime.json and quoted a list that did not come
    from it. The runtime's own file is the authority for what its runtime
    permits; this restores that without re-resolving the registry mid-campaign
    and disturbing digests the frozen canaries depend on.
    """

    allowed = tuple(runtime.runtime_mode_allowed)
    if allowed == tuple(entry.runtime_mode_allowed):
        return entry
    say(
        f"runtime_mode_allowed {list(allowed)} from runtime.json "
        f"(model_registry.json says {list(entry.runtime_mode_allowed)}; D77)"
    )
    return replace(entry, runtime_mode_allowed=allowed)


def _retry_if_operational(
    *,
    queue: CampaignQueue,
    job: JobRecord,
    outcome: PageOutcome,
    notes: list[str],
    pause: Callable[[float], None],
) -> bool:
    """Return a page to PENDING when the masterplan's retry table allows it (D81).

    A pod that dies mid-dispatch fails its page with INFRA_NETWORK. That is an
    operational failure, not the model's answer, and leaving it FAILED would
    put a dead pod's page into the score. ``retry.decide`` owns which classes
    are retryable and how many attempts each gets, so a deterministic failure
    still settles after its allowance and is never retried forever.
    """

    error_class = outcome.error_class
    if not error_class:
        return False
    current = queue.get_job(job.inference_job_id)
    retry_count = current.retry_count if current is not None else job.retry_count
    decision = decide(error_class, retry_count=retry_count)
    if not decision.retry:
        return False
    if decision.delay_seconds > 0:
        pause(decision.delay_seconds)
    queue.requeue(job.inference_job_id, reason=decision.reason)
    notes.append(f"{job.case_key}: {decision.reason}")
    return True


def _pending_in(paths: CampaignPaths, model_key: str, shard_ids: Collection[str]) -> int:
    """PENDING pages in this driver's shards (D76).

    The model's own PENDING count is the wrong stop condition once drivers
    are sliced: a driver whose shards are finished would keep renting pods
    for pages another driver already owns.
    """

    with CampaignQueue(paths.queue_db) as queue:
        return sum(
            len(queue.pending_jobs(model_key=model_key, shard_id=shard_id, limit=1000))
            for shard_id in shard_ids
        )


def run_full(
    *,
    paths: CampaignPaths,
    model_key: str,
    runtime: RuntimeSpecView,
    snapshot: PriceSnapshot,
    gpu_type: str,
    hourly_rate_usd: float | None,
    price_row_sha256: str | None,
    cloud: str = "SECURE",
    v1_client: RunPodV1Client,
    v2_client: RunPodPodsClient,
    create_pod: Callable[[str, PromptRef], tuple[str | None, Mapping[str, object]]],
    worker_factory: Callable[[str], Any],
    page_bytes: Callable[[SourceSample], bytes] | None = None,
    authorization_receipt_path: str | None = None,
    authorization_receipt_sha256: str | None = None,
    bundle_sha256_argv: str | None = None,
    bootstrap_deadline_seconds: float = DEFAULT_BOOTSTRAP_DEADLINE_SECONDS,
    ready_poll_seconds: float = DEFAULT_READY_POLL_SECONDS,
    lifetime_seconds: float = FULL_RUN_LIFETIME_SECONDS,
    lifetime_margin_seconds: float = FULL_RUN_LIFETIME_MARGIN_SECONDS,
    watchdog_tick_seconds: float = WATCHDOG_TICK_SECONDS,
    max_pods: int = 1,
    page_limit: int | None = None,
    shard_index: int | None = None,
    shard_count: int | None = None,
    next_pod_allowed: Callable[[int], tuple[bool, str]] | None = None,
    staged_root: Path = STAGED_PUBLIC_CORE_ROOT,
    sleep: Callable[[float], None] | None = None,
    now: Callable[[], datetime] | None = None,
    start_watchdog: bool = True,
) -> FullRunDriverResult:
    """Run Phase 2 for one model, in this process, until nothing is left or a
    stop rule fires (D72). See the module docstring for the shape."""

    clock = now or (lambda: datetime.now(tz=UTC))
    pause = sleep or (lambda seconds: __import__("time").sleep(max(seconds, 0.0)))
    read_page = page_bytes or (
        lambda sample: load_page_bytes(sample, staged_root=staged_root)
    )
    if max_pods < 1:
        raise DriverError("max_pods must be at least 1")
    if (shard_index is None) != (shard_count is None):
        raise DriverError("shard_index and shard_count are given together or not at all")
    if shard_count is not None:
        if shard_count < 1:
            raise DriverError("shard_count must be at least 1")
        if shard_index is None or not 0 <= shard_index < shard_count:
            raise DriverError(
                f"shard_index must be in [0, {shard_count}); got {shard_index}"
            )
    if page_limit is not None and page_limit < 1:
        raise DriverError("page_limit must be at least 1 when given")

    started_at = utc_now_iso()
    notes: list[str] = []
    pods: list[PodAttempt] = []
    error: str | None = None
    stop_reason: str | None = None
    attempted = 0
    succeeded = 0
    entry: ModelPlanEntry | None = None
    gate: Eligibility | None = None
    digest: str | None = None
    last_budget: BudgetAssessment | None = None

    def say(line: str) -> None:
        print(f"  {line}", flush=True)

    def run_pod(index: int, *, entry: ModelPlanEntry, prompt: PromptRef, order: Sequence[Any],
                by_case: Mapping[str, SourceSample], digest: str) -> PodAttempt:
        """One pod: provision, readiness, pages, stop rule, teardown. Never raises
        past its own ``finally``; whatever happened is in the attempt."""

        nonlocal last_budget
        pod_notes: list[str] = []
        pod_id: str | None = None
        pod_summary: Mapping[str, object] = {}
        ready_at: str | None = None
        watchdog: CanaryWatchdog | None = None
        terminate_lock = threading.Lock()
        terminated: set[str] = set()
        pod_facts: dict[str, object] = {}
        teardown: dict[str, str | None] = {"stopped_at": None, "deleted_at": None}
        diagnostics: dict[str, object] = {}
        postrun: dict[str, object] = {}
        bootstrap_log: dict[str, object] = {}
        reads = _ReadTally()
        watch_reads: list[Mapping[str, object]] = []
        pod_error: str | None = None
        stop: str | None = None
        pod_attempted = 0
        pod_succeeded = 0
        pod_requeued = 0
        pod_failed = 0
        consecutive = 0
        created_gpu = gpu_type
        created_rate = hourly_rate_usd
        provisioned_at = utc_now_iso()
        pod_started = clock()
        budget_seen: BudgetAssessment | None = None

        def terminate(reason: str) -> None:
            with terminate_lock:
                if pod_id is None or pod_id in terminated:
                    return
                terminated.add(pod_id)
                pod_facts.update(_pod_facts(v1_client, pod_id, pod_notes))
                try:
                    v1_client.stop_pod(pod_id)
                    teardown["stopped_at"] = utc_now_iso()
                except RunPodClientError as exc:
                    pod_notes.append(f"stop_pod refused: {exc}")
                try:
                    v1_client.delete_pod(pod_id)
                    teardown["deleted_at"] = utc_now_iso()
                except RunPodClientError as exc:
                    pod_notes.append(f"delete_pod refused: {exc}")
                pod_notes.append(f"pod {pod_id} stop+delete sent ({reason})")

        def provider_status() -> str | None:
            if pod_id is None:
                return None
            reads.count += 1
            index_read = reads.count

            def keep(pod: Any) -> bool:
                answer = _status_of(pod)
                if (
                    index_read == 1
                    or answer != reads.last
                    or index_read % PROVIDER_RECEIPT_EVERY == 0
                ):
                    reads.kept += 1
                    return True
                reads.suppressed += 1
                return False

            present, facts = _pod_probe(
                v1_client, pod_id, pod_notes, quiet=True, persist_receipt=keep
            )
            if facts:
                pod_facts.update(facts)
            status = facts.get("desired_status")
            answer = (
                POD_MISSING
                if present is False
                else (status if isinstance(status, str) else None)
            )
            if index_read > 1 and answer != reads.last:
                line = f"pod {pod_id} provider status: {reads.last} -> {answer}"
                pod_notes.append(line)
                say(line)
            reads.last = answer
            return answer

        def container_log() -> tuple[Mapping[str, object], ...]:
            if pod_id is None:
                return ()
            read = _read_log_tail(
                pod_id, clients=(v2_client, v1_client), max_lines=LOG_TAIL_LINES
            )
            watch_reads[:] = read.reads
            return read.lines

        def elapsed_seconds() -> float:
            return max((clock() - pod_started).total_seconds(), 0.0)

        try:
            pod_id, pod_summary = create_pod(digest, prompt)
            if pod_id is None:
                raise DriverError(
                    "the provider did not return a pod id; nothing can be dispatched and "
                    "nothing is assumed to be running"
                )
            pod_started = clock()
            created_gpu, created_rate, _created_row = _price_created_gpu(
                pod_summary,
                snapshot=snapshot,
                cloud=cloud,
                quoted_gpu_type=gpu_type,
                quoted_rate_usd=hourly_rate_usd,
                quoted_row_sha256=price_row_sha256,
                notes=pod_notes,
                say=say,
            )
            _record_pod(
                paths,
                pod_id=pod_id,
                model_key=model_key,
                runtime=runtime,
                gpu_type=created_gpu,
                hourly_rate_usd=created_rate,
                snapshot=snapshot,
                authorization_receipt_path=authorization_receipt_path,
                authorization_receipt_sha256=authorization_receipt_sha256,
            )
            if start_watchdog:
                watchdog = CanaryWatchdog(
                    lifetime_seconds=lifetime_seconds,
                    tick_seconds=watchdog_tick_seconds,
                    on_expire=lambda elapsed: terminate(
                        f"lifetime watchdog: {elapsed / 3600:.2f} h reached the "
                        f"{lifetime_seconds / 3600:.2f} h cap (D10)"
                    ),
                    on_budget=lambda assessment: pod_notes.append(
                        f"budget watchdog: {assessment.reason}"
                    ),
                    budget=BudgetWatchdog(
                        soft_cap_usd=BUDGET_SOFT_CAP_USD, hard_cap_usd=BUDGET_HARD_CAP_USD
                    ),
                    budget_inputs=lambda: (
                        _spent_usd(paths),
                        [created_rate] if created_rate else [],
                        lifetime_seconds,
                    ),
                    now=clock,
                )
                watchdog.start()

            worker = worker_factory(pod_id)
            say(
                f"waiting for pod {pod_id} to become READY "
                f"(deadline {bootstrap_deadline_seconds / 60:.0f} min, "
                f"poll {ready_poll_seconds:.0f} s)"
            )
            _stage, observed = poll_until_ready(
                worker,
                max_attempts=None,
                poll_seconds=ready_poll_seconds,
                deadline_seconds=bootstrap_deadline_seconds,
                sleep=pause,
                now=clock,
                pod_status=provider_status,
                note=pod_notes.append,
                log_tail=container_log,
                progress=say,
            )
            ready_at = utc_now_iso()
            pod_notes.append(f"worker READY after {' -> '.join(observed)}")
            say(f"pod {pod_id} READY after {' -> '.join(observed)}")
            _mark_ready(paths, pod_id=pod_id, ready_at=ready_at)
            bootstrap_log = _postrun_diagnostics(
                pod_id=pod_id,
                clients=(v2_client, v1_client),
                notes=pod_notes,
                label="ready-time",
            )

            worker_id = f"{model_key}-full-{pod_id}"
            budget_watch = BudgetWatchdog(
                soft_cap_usd=BUDGET_SOFT_CAP_USD, hard_cap_usd=BUDGET_HARD_CAP_USD
            )
            with CampaignQueue(paths.queue_db) as queue:
                events = EventLog(paths.events_log)
                for shard in order:
                    if stop is not None:
                        break
                    while stop is None:
                        pending = queue.pending_jobs(
                            model_key=model_key, shard_id=shard.shard_id, limit=1
                        )
                        if not pending:
                            break
                        job = pending[0]
                        sample = by_case.get(job.case_key)
                        pod_attempted += 1
                        if sample is None:
                            queue.mark_failed(
                                job.inference_job_id,
                                error_class="INPUT_DECODE",
                                error_message="case_key is not in the source manifest",
                            )
                            pod_failed += 1
                            consecutive += 1
                        else:
                            try:
                                data = read_page(sample)
                            except DriverError as exc:
                                queue.mark_failed(
                                    job.inference_job_id,
                                    error_class="INPUT_DECODE",
                                    error_message=str(exc)[:2000],
                                )
                                pod_failed += 1
                                consecutive += 1
                            else:
                                outcome = dispatch_page(
                                    worker=worker,
                                    worker_id=worker_id,
                                    pod_id=pod_id,
                                    gpu_type=created_gpu,
                                    job=job,
                                    sample=sample,
                                    entry=entry,
                                    paths=paths,
                                    queue=queue,
                                    events=events,
                                    image_bytes=data,
                                    worker_ready_at=ready_at,
                                    timeout_seconds=runtime.per_page_timeout_seconds,
                                )
                                if outcome.succeeded:
                                    pod_succeeded += 1
                                    consecutive = 0
                                else:
                                    pod_failed += 1
                                    consecutive += 1
                                    requeued = _retry_if_operational(
                                        queue=queue,
                                        job=job,
                                        outcome=outcome,
                                        notes=pod_notes,
                                        pause=pause,
                                    )
                                    if requeued:
                                        pod_requeued += 1
                        # The stop rules, in the order that matters: the ones a
                        # human or a rehearsal asked for first, then the ones
                        # that say the pod or the money is done.
                        total_so_far = attempted + pod_attempted
                        if page_limit is not None and total_so_far >= page_limit:
                            stop = "page_limit"
                        elif _stop_requested(paths, model_key):
                            stop = OPERATOR_STOP
                        elif consecutive >= MAX_CONSECUTIVE_FAILURES:
                            stop = "consecutive_failures"
                        elif elapsed_seconds() >= lifetime_seconds - lifetime_margin_seconds:
                            stop = "lifetime_margin"
                        else:
                            accrued = (created_rate or 0.0) * elapsed_seconds() / 3600.0
                            assessment = budget_watch.evaluate(
                                spent_usd=_spent_usd(paths) + accrued,
                                running_worker_rates_usd_per_hour=(
                                    [created_rate] if created_rate else []
                                ),
                                seconds_to_next_checkpoint=float(
                                    runtime.per_page_timeout_seconds
                                ),
                            )
                            budget_seen = assessment
                            last_budget = assessment
                            if assessment.pause_queue or assessment.drain_workers:
                                stop = "budget_hard_cap"
                if stop is None:
                    stop = "pod_exhausted"
            pod_notes.append(
                f"pod {pod_id}: {pod_succeeded} SUCCESS / {pod_failed} FAILED of "
                f"{pod_attempted} page(s); stop_reason={stop}"
            )
            say(pod_notes[-1])

            try:
                worker.drain()
                pod_notes.append("worker drained")
            except Exception as exc:
                pod_notes.append(f"drain failed ({type(exc).__name__}); terminating anyway")
            postrun = _postrun_diagnostics(
                pod_id=pod_id, clients=(v2_client, v1_client), notes=pod_notes
            )
        except ReadinessError as exc:
            pod_error = f"{type(exc).__name__}: {exc}"
            worker_error = _worker_last_error(exc.last_ready_response)
            if worker_error is not None:
                pod_error = f"{pod_error}; worker last_error: {worker_error}"
            pod_notes.append(f"driver refused: {pod_error}")
            say(f"driver refused: {pod_error}")
            diagnostics = _readiness_diagnostics(
                exc,
                pod_id=pod_id,
                clients=(v2_client, v1_client),
                notes=pod_notes,
                watch_reads=watch_reads,
            )
        except (DriverError, QueueError, RunError, RunPodClientError) as exc:
            pod_error = f"{type(exc).__name__}: {exc}"
            pod_notes.append(f"driver refused: {pod_error}")
        except Exception as exc:
            pod_error = f"{type(exc).__name__}: {exc}"
            pod_notes.append(f"driver raised: {pod_error}")
        finally:
            if watchdog is not None:
                watchdog.stop()
                if watchdog.fired:
                    pod_notes.append("the lifetime watchdog had already terminated this pod")
            terminate("driver finished")
            pod_return = _confirm_gone(
                pod_id=pod_id,
                v1_client=v1_client,
                v2_client=v2_client,
                sleep=pause,
                notes=pod_notes,
            )
            ledger_path = _write_ledger(
                paths,
                pod_id=pod_id,
                model_key=model_key,
                gpu_type=created_gpu,
                notes=pod_notes,
                pod_facts=pod_facts,
                stopped_at=teardown["stopped_at"],
                deleted_at=teardown["deleted_at"],
            )

        return PodAttempt(
            index=index,
            pod_id=pod_id,
            gpu_type=created_gpu,
            hourly_rate_usd=created_rate,
            provisioned_at=provisioned_at,
            ready_at=ready_at,
            finished_at=utc_now_iso(),
            pages_attempted=pod_attempted,
            pages_succeeded=pod_succeeded,
            pages_failed=pod_failed,
            stop_reason=stop,
            error=pod_error,
            pod_return=pod_return,
            ledger_path=ledger_path,
            notes=tuple(pod_notes),
            pod_summary=dict(pod_summary),
            teardown={
                "stopped_at": teardown["stopped_at"],
                "deleted_at": teardown["deleted_at"],
                **{str(key): value for key, value in pod_facts.items()},
            },
            readiness={
                "ready_at": ready_at,
                "provider_reads": reads.to_dict(),
                **diagnostics,
            },
            bootstrap_log=bootstrap_log,
            postrun=postrun,
            budget=None if budget_seen is None else budget_seen.to_dict(),
        )

    try:
        # 1. D21: the bundle the start command will pin, proven by its receipt.
        bundle_sha256, bundle_receipt = resolve_bundle_sha256(
            paths, model_key, argv_sha256=bundle_sha256_argv
        )
        digest = bootstrap_image_digest(
            bundle_sha256 if bundle_sha256.startswith("sha256:") else f"sha256:{bundle_sha256}"
        )
        notes.append(
            f"bundle {bundle_receipt.get('bundle_reference')} sha256 {bundle_sha256}; "
            f"runtime_image_digest {digest} (D15)"
        )

        # 2. D15/D17: the prompt is the runtime's, its hash the registry's.
        prompt = resolve_prompt(
            paths.root, prompt_id=runtime.prompt_id, prompt_kind=runtime.prompt_kind
        )
        entry = load_model_registry(
            paths.model_registry,
            model_key,
            runtime_image_digest=digest,
            prompt_id=prompt.prompt_id,
            prompt_sha256=prompt.prompt_sha256,
        )

        # 3. Section 5: canary PASS, and a baked image or a founder waiver. The
        #    CLI checked this before asking for money; the driver checks again
        #    so a direct caller cannot skip it.
        entry, verdict_note = entry_with_canary_verdict(entry, paths)
        if verdict_note is not None:
            notes.append(verdict_note)
        entry = _with_runtime_modes(entry, runtime, notes.append)
        gate = eligibility(entry, paths, runtime_mode="bootstrap")
        if not gate.allowed:
            raise DriverError(f"full run refused: {gate.reason}")
        notes.append(f"eligibility: {gate.reason}")

        # 4. Every manifest page into the queue. ``enqueue`` is idempotent and
        #    section 9.3 keeps a settled job settled, so a re-run resumes.
        samples = load_source_manifest(paths.source_manifest)
        by_case = {sample.case_key: sample for sample in samples}
        plan = build_plan(
            model_key=model_key, samples=samples, entry=entry, job_kind="inference"
        )
        # D76: this driver owns a slice of the shards and touches nothing
        # else, so N drivers can run this model's pages at the same time
        # without two of them dispatching one page. The slice is taken from
        # the deterministic dispatch order, so the slices are disjoint and
        # together cover every shard.
        order = dispatch_order(plan.shards)
        if shard_count is not None and shard_index is not None:
            order = tuple(
                shard
                for position, shard in enumerate(order)
                if position % shard_count == shard_index
            )
            notes.append(
                f"shard slice {shard_index + 1}/{shard_count}: "
                f"{len(order)} of {len(plan.shards)} shard(s), "
                f"{sum(shard.job_count for shard in order)} page(s)"
            )
        mine = {shard.shard_id for shard in order}

        with CampaignQueue(paths.queue_db) as queue:
            queue.upsert_shards(plan.shards)
            inserted, skipped = queue.enqueue(plan.jobs)
            stale = 0
            for state in ("RUNNING", "ASSIGNED"):
                for job in queue.jobs_for_model(model_key, state=state):
                    if job.shard_id not in mine:
                        # Another driver's shard. It may have that page in
                        # flight right now; requeueing it here would dispatch
                        # the same page twice.
                        continue
                    # No worker of ours is running: a job left in flight belongs
                    # to a driver that did not get to write its outcome.
                    queue.requeue(
                        job.inference_job_id,
                        reason=f"stale {state} job at full-run start",
                    )
                    stale += 1
            counts = dict(queue.counts_by_state(model_key=model_key))
        notes.append(
            f"{len(plan.jobs)} page(s) in {len(plan.shards)} shard(s): {inserted} enqueued, "
            f"{skipped} already present, {stale} stale job(s) returned to PENDING; "
            f"queue {counts}"
        )
        say(notes[-1])

        # 5. Pods, one after another, until nothing is left or a rule says stop.
        pod_index = 0
        while True:
            counts = _counts(paths, model_key)
            if _pending_in(paths, model_key, mine) == 0:
                stop_reason = "nothing_left"
                break
            if page_limit is not None and attempted >= page_limit:
                stop_reason = "page_limit"
                break
            if _stop_requested(paths, model_key):
                stop_reason = OPERATOR_STOP
                notes.append("operator STOP file found before a pod was rented")
                break
            if pod_index >= max_pods:
                stop_reason = "max_pods"
                notes.append(
                    f"{pod_index} pod(s) is this invocation's --max-pods; "
                    f"{counts.get('PENDING', 0)} page(s) still PENDING"
                )
                break
            if next_pod_allowed is not None:
                allowed, why = next_pod_allowed(pod_index)
                verdict = "GRANTED" if allowed else "BLOCKED"
                notes.append(f"pod {pod_index}: authorization {verdict}: {why}")
                if not allowed:
                    stop_reason = "authorization"
                    break
            if last_budget is not None and not last_budget.allow_new_replicas:
                stop_reason = "budget_soft_cap"
                notes.append(f"no new pod: {last_budget.reason}")
                break
            attempt = run_pod(
                pod_index, entry=entry, prompt=prompt, order=order, by_case=by_case, digest=digest
            )
            pods.append(attempt)
            attempted += attempt.pages_attempted
            succeeded += attempt.pages_succeeded
            pod_index += 1
            if attempt.error is not None:
                # A pod that failed before or while serving is not followed by
                # another on the same recipe: the operator reads why first.
                error = attempt.error
                stop_reason = "pod_error"
                break
            if attempt.stop_reason in _TERMINAL_STOPS:
                stop_reason = attempt.stop_reason
                break
    except (BundleError, DriverError, PlanError, PromptError, QueueError, RunError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        notes.append(f"driver refused: {error}")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        notes.append(f"driver raised: {error}")

    # 6. Summary and, when nothing is undecided, the freeze.
    counts = _counts(paths, model_key)
    summary_path: Path | None = None
    freeze: Mapping[str, object] | None = None
    if entry is not None and gate is not None:
        with CampaignQueue(paths.queue_db) as queue:
            summary_path = write_run_summary(
                paths,
                model_key=model_key,
                queue=queue,
                entry=entry,
                eligibility_result=gate,
                budget=last_budget,
                breaker=None,
                started_at=started_at,
            )
    unsettled = _unsettled(counts)
    decided = int(counts.get("SUCCESS", 0)) + int(counts.get("FAILED", 0))
    if error is None and unsettled == 0 and decided > 0:
        try:
            freeze = freeze_model(
                model_key,
                paths=paths,
                model_revision=runtime.model_revision,
                runtime_image_digest=digest,
            ).to_dict()
            notes.append(
                f"frozen: {freeze.get('success_count')} SUCCESS / "
                f"{freeze.get('failed_count')} FAILED; manifest {freeze.get('manifest_sha256')}"
            )
        except FreezeError as exc:
            notes.append(f"freeze refused: {exc}")

    if error is not None:
        status = "ERROR"
    elif unsettled == 0 and freeze is not None and bool(freeze.get("frozen")):
        status = "COMPLETE"
    elif stop_reason in ("budget_hard_cap", "consecutive_failures", "authorization"):
        status = "STOPPED"
    else:
        status = "PARTIAL"

    # D76: one receipt per slice. Nine drivers of the same model would
    # otherwise write the same file at the same time, and the last one out
    # would be the only run with any record of what it did.
    slice_tag = "" if shard_count is None else f"-s{shard_index}of{shard_count}"
    driver_receipt = (
        paths.receipts_dir / f"full-run-driver-{model_key}{slice_tag}.json"
    )
    result = FullRunDriverResult(
        model_key=model_key,
        status=status,
        stop_reason=stop_reason,
        started_at=started_at,
        finished_at=utc_now_iso(),
        pages_attempted=attempted,
        pages_succeeded=succeeded,
        pods=tuple(pods),
        job_counts=counts,
        run_summary_path=summary_path,
        freeze=freeze,
        driver_receipt_path=driver_receipt,
        error=error,
        notes=tuple(notes),
    )
    write_json_atomic(driver_receipt, result.to_dict(), context="full-run driver receipt")
    return result
