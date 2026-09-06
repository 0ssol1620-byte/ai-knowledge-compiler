"""The Phase 1 canary driver — ARENA_CONTRACT 11.5 D20.

Two adversarial critics returned NO-GO on the first pass with one finding:
``canary --execute`` provisioned a pod and returned. Nothing dispatched a page,
nothing evaluated, nothing receipted, and nothing gave the pod back. This
module is the answer, and its shape is dictated by that failure:

    bundle receipt (D21) -> gate -> provision (v1) -> poll readiness
      -> dispatch each page -> page receipts -> evaluate -> canary receipt
      -> registry update -> drain -> **stop and delete in a finally**
      -> re-list on v1 AND v2 until the pod is gone

The ``finally`` is the load-bearing line. Every failure above it -- a readiness
timeout, a page timeout, an evaluation that FAILs, an exception nobody
predicted -- still returns the pod. On top of that a watchdog thread stops and
deletes at the two-hour D10 lifetime no matter what the main thread is doing,
because a driver wedged on a socket read is exactly the case a `finally` does
not cover.

Everything external is injected -- both provider clients, the worker factory,
the page-bytes loader, the clock and the sleep -- so every one of those failure
paths is a test rather than a hope.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from arena.constants import (
    BUDGET_HARD_CAP_USD,
    BUDGET_SOFT_CAP_USD,
    CAMPAIGN_ID,
    STAGED_PUBLIC_CORE_ROOT,
)
from arena.controller import cost as cost_module
from arena.controller.bundle import BundleError, resolve_bundle_sha256
from arena.controller.canary import (
    CanaryError,
    CanaryReport,
    evaluate_canary,
    load_canary_selection,
    results_from_receipts,
    write_canary_receipt,
    write_registry_update,
)
from arena.controller.cleanup import clean_up_campaign
from arena.controller.events import EventLog
from arena.controller.paths import CampaignPaths
from arena.controller.plan import (
    ModelPlanEntry,
    PlanError,
    SourceSample,
    build_plan,
    load_model_registry,
    load_source_manifest,
)
from arena.controller.prompts import PromptError, PromptRef, resolve_prompt
from arena.controller.queue import CampaignQueue, PodRecord
from arena.controller.run import (
    LOG_TAIL_LINES,
    POD_MISSING,
    ReadinessError,
    RunError,
    dispatch_page,
    poll_until_ready,
    scrub_log_lines,
)
from arena.controller.runtime_spec import RuntimeSpecView
from arena.controller.watchdogs import BudgetWatchdog
from arena.core.ids import bootstrap_image_digest
from arena.provider.runpod_pods import PriceSnapshot, RunPodClientError, RunPodPodsClient
from arena.provider.runpod_v1 import RunPodV1Client
from arena.provider.safety import (
    sha256_bytes,
    utc_now_iso,
    write_json_atomic,
    write_jsonl_append,
)
from arena.provider.worker_client import RunRequest, RunResponse

__all__ = [
    "DEFAULT_BOOTSTRAP_DEADLINE_SECONDS",
    "CanaryDriverResult",
    "CanaryWatchdog",
    "DriverError",
    "PodReturn",
    "classify_page_failures",
    "load_page_bytes",
    "run_canary",
]

# ARENA_CONTRACT 11.5 D20: a bootstrap pod installs a runtime and pulls
# weights before it can answer /v1/ready. Forty-five minutes is the default
# budget for that, and it is a flag because the 7B-class models may need more
# (D19 puts the model-server load alone at >= 20 minutes).
DEFAULT_BOOTSTRAP_DEADLINE_SECONDS: Final = 45 * 60
DEFAULT_READY_POLL_SECONDS: Final = 20.0
# D10: a canary pod lives at most two hours, watchdog or no watchdog.
CANARY_LIFETIME_SECONDS: Final = 2 * 3600
WATCHDOG_TICK_SECONDS: Final = 30.0


# Item 3 of the 2026-09-03 operator report: ``provider_status()`` wrote one
# ``v1-get_pod`` receipt per poll, about 136 per bootstrap, and 130 of them
# said the same word. Keep the first, every change, and every tenth otherwise.
PROVIDER_RECEIPT_EVERY: Final = 10

# Read in this order and merged by timestamp. ``container`` first because it is
# the source the readiness verdict is made from; ``system`` carries the
# ``start container for`` restart marker and nothing else the verdict needs.
LOG_SOURCES_READ: Final = ("container", "system")

# The periodic watch keeps its 200-line tail; the read taken *because*
# readiness failed asks the container source for twice that. Pod
# jdwdnvg8a2rzx6 gave back 194 lines that stopped a minute before the crash
# they were read to explain, and a tail that short leaves nothing to see.
DIAGNOSTIC_CONTAINER_TAIL_LINES: Final = 400


class DriverError(RuntimeError):
    """The canary could not be driven. The pod is still returned."""


@dataclass
class _ReadTally:
    """How many provider reads happened, and how many left a receipt."""

    count: int = 0
    kept: int = 0
    suppressed: int = 0
    last: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "reads": self.count,
            "receipts_kept": self.kept,
            "receipts_suppressed": self.suppressed,
            "policy": (
                "first read, every status change, every "
                f"{PROVIDER_RECEIPT_EVERY}th unchanged read"
            ),
        }


# ------------------------------------------------------------------ inputs


def load_page_bytes(sample: SourceSample, *, staged_root: Path = STAGED_PUBLIC_CORE_ROOT) -> bytes:
    """Read one page PNG and prove it is the page the manifest names.

    D14 makes ``input_png_sha256`` the bytes the model sees, so the check here
    is against exactly that. A mismatch is refused rather than dispatched: an
    output attributed to the wrong page is worse than a missing output.
    """

    path = staged_root / sample.image_path
    if not path.is_file():
        raise DriverError(
            f"page {sample.case_key} is not on disk at {path}; the inference plane reads "
            "the staged public-core PNGs, never ground truth"
        )
    data = path.read_bytes()
    observed = sha256_bytes(data)
    if observed != sample.source_sha256:
        raise DriverError(
            f"page {sample.case_key} at {path} hashes to {observed}, but the manifest says "
            f"{sample.source_sha256}"
        )
    return data


# --------------------------------------------------------------- watchdog


class CanaryWatchdog:
    """One timer for the two things that must happen without the main thread.

    D20 puts the lifetime kill and ``BudgetWatchdog`` on the same timer. A
    driver blocked on a socket cannot notice either, which is the whole reason
    they do not live in the dispatch loop.
    """

    def __init__(
        self,
        *,
        lifetime_seconds: float = CANARY_LIFETIME_SECONDS,
        tick_seconds: float = WATCHDOG_TICK_SECONDS,
        on_expire: Callable[[float], None],
        on_budget: Callable[[Any], None] | None = None,
        budget: BudgetWatchdog | None = None,
        budget_inputs: Callable[[], tuple[float, Sequence[float], float]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if lifetime_seconds <= 0:
            raise DriverError("a canary pod lifetime must be positive")
        self.lifetime_seconds = lifetime_seconds
        self.tick_seconds = max(0.01, min(tick_seconds, lifetime_seconds))
        self._on_expire = on_expire
        self._on_budget = on_budget
        self._budget = budget
        self._budget_inputs = budget_inputs
        self._now = now or (lambda: datetime.now(tz=UTC))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at = self._now()
        self.fired = False
        self.budget_state = "NORMAL"

    def start(self) -> None:
        self._started_at = self._now()
        self._thread = threading.Thread(
            target=self._loop, name="arena-canary-watchdog", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.tick_seconds * 2 + 1.0)
            self._thread = None

    @property
    def elapsed_seconds(self) -> float:
        return (self._now() - self._started_at).total_seconds()

    def tick(self) -> bool:
        """One evaluation. Returns True when the lifetime has expired.

        Public so a test can drive the watchdog without a thread and without
        waiting two hours.
        """

        if self._budget is not None and self._budget_inputs is not None:
            spent, rates, horizon = self._budget_inputs()
            assessment = self._budget.evaluate(
                spent_usd=spent,
                running_worker_rates_usd_per_hour=list(rates),
                seconds_to_next_checkpoint=horizon,
            )
            if assessment.state != self.budget_state:
                self.budget_state = assessment.state
                if self._on_budget is not None:
                    self._on_budget(assessment)
        if self.elapsed_seconds >= self.lifetime_seconds and not self.fired:
            self.fired = True
            self._on_expire(self.elapsed_seconds)
            return True
        return False

    def _loop(self) -> None:
        while not self._stop.wait(self.tick_seconds):
            try:
                if self.tick():
                    return
            except Exception:  # pragma: no cover - a watchdog never kills the run
                # The watchdog exists to return a pod. If its own bookkeeping
                # throws, the `finally` in run_canary is still the backstop,
                # and a traceback here must not take the driver down with it.
                traceback.print_exc()
                return


# --------------------------------------------------------- failure counts

# Masterplan section 15.9's own table decides this, so nothing here is a new
# judgement about which failures are the runtime's fault:
#
#   * a rule whose action drains the worker or quarantines the *runtime* means
#     the runtime itself is broken -- section 17's ``zero_hard_crash``;
#   * a rule the table refuses to retry at all (``max_retries == 0``), or one
#     that quarantines the job, is a deterministic failure -- section 17's
#     ``zero_deterministic_runtime_bug``;
#   * a rule with retries left (INFRA_CAPACITY, INFRA_NETWORK, RATE_LIMIT,
#     WORKER_LOST) is an infrastructure event, not a runtime verdict. D40
#     settles this: the Opus canary's one INFRA_CAPACITY page stayed in the
#     receipt as a capacity event and did not condemn the model.
_RUNTIME_BROKEN_ACTIONS: Final = (
    "drain_worker",
    "quarantine_runtime",
    "drain the worker",
    "quarantine the runtime",
)
# A corrupt or undecodable page is the *source's* problem. Section 15.9 sends
# it to source quarantine, and condemning a runtime for a page it was handed
# would be the campaign blaming the model for the corpus.
_SOURCE_ACTIONS: Final = ("quarantine_source", "quarantine the source")


def classify_page_failures(
    records: Sequence[Mapping[str, Any]],
) -> tuple[int, int, tuple[str, ...]]:
    """Count section 17's hard crashes and deterministic runtime bugs."""

    from arena.controller.retry import rule_for

    crashes = 0
    deterministic = 0
    notes: list[str] = []
    for record in records:
        if str(record.get("status", "")) == "SUCCESS":
            continue
        error_class = str(record.get("error_class") or "UNKNOWN")
        try:
            rule = rule_for(error_class)
        except ValueError:
            # A failure the section 15.9 taxonomy does not name is not
            # assumed to be transient. Fail closed: it counts against the
            # canary and says so.
            deterministic += 1
            notes.append(
                f"page {record.get('case_key')} failed {error_class}, which is outside the "
                "section 16 taxonomy; counted as a deterministic failure rather than "
                "assumed transient"
            )
            continue
        action = rule.action.casefold()
        if any(marker in action for marker in _SOURCE_ACTIONS):
            notes.append(
                f"page {record.get('case_key')} failed {error_class}: section 15.9 "
                f"({rule.mp_row}) quarantines the source, so it is not a verdict on the "
                "runtime"
            )
        elif any(marker in action for marker in _RUNTIME_BROKEN_ACTIONS):
            crashes += 1
            notes.append(
                f"page {record.get('case_key')} failed {error_class}: section 15.9 "
                f"({rule.mp_row}) treats it as the runtime being broken"
            )
        elif rule.max_retries == 0 or rule.quarantines:
            deterministic += 1
            notes.append(
                f"page {record.get('case_key')} failed {error_class}: section 15.9 "
                f"({rule.mp_row}) does not retry it, so it is deterministic"
            )
        else:
            notes.append(
                f"page {record.get('case_key')} failed {error_class}: section 15.9 "
                f"({rule.mp_row}) allows {rule.max_retries} retry(ies), so it is an "
                "infrastructure event and not a verdict on the runtime (D40)"
            )
    return crashes, deterministic, tuple(notes)


# --------------------------------------------------------------- results


@dataclass(frozen=True, slots=True)
class PodReturn:
    """What actually happened to the pod. Never inferred, only observed."""

    pod_id: str | None
    stop_called: bool
    delete_called: bool
    gone_from_v1: bool
    gone_from_v2: bool
    attempts: int
    notes: tuple[str, ...] = ()

    @property
    def returned(self) -> bool:
        return self.pod_id is None or (self.gone_from_v1 and self.gone_from_v2)

    def to_dict(self) -> dict[str, object]:
        return {
            "pod_id": self.pod_id,
            "stop_called": self.stop_called,
            "delete_called": self.delete_called,
            "gone_from_v1": self.gone_from_v1,
            "gone_from_v2": self.gone_from_v2,
            "relist_attempts": self.attempts,
            "returned": self.returned,
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class CanaryDriverResult:
    model_key: str
    status: str  # "PASS" | "FAIL" | "ERROR"
    started_at: str
    finished_at: str
    pages_attempted: int
    pages_succeeded: int
    pod_return: PodReturn
    report: CanaryReport | None = None
    canary_receipt_path: Path | None = None
    registry_update_path: Path | None = None
    driver_receipt_path: Path | None = None
    ledger_path: Path | None = None
    error: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.arena.canary_driver.v1",
            "campaign_id": CAMPAIGN_ID,
            "model_key": self.model_key,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pages_attempted": self.pages_attempted,
            "pages_succeeded": self.pages_succeeded,
            "pod_return": self.pod_return.to_dict(),
            "canary_receipt": (
                None if self.canary_receipt_path is None else self.canary_receipt_path.name
            ),
            "registry_update": (
                None if self.registry_update_path is None else self.registry_update_path.name
            ),
            "pod_ledger": None if self.ledger_path is None else self.ledger_path.name,
            "error": self.error,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------- driver


def run_canary(
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
    lifetime_seconds: float = CANARY_LIFETIME_SECONDS,
    watchdog_tick_seconds: float = WATCHDOG_TICK_SECONDS,
    staged_root: Path = STAGED_PUBLIC_CORE_ROOT,
    sleep: Callable[[float], None] | None = None,
    now: Callable[[], datetime] | None = None,
    start_watchdog: bool = True,
) -> CanaryDriverResult:
    """Run the whole of Phase 1 for one model, in this process (D20).

    ``create_pod`` is a callback rather than a client call so the gate, the
    price quote and the provisional ledger line stay in the CLI where the
    operator can see them, while the driver keeps the one thing it must own:
    whatever happens next, the pod comes back.
    """

    clock = now or (lambda: datetime.now(tz=UTC))
    pause = sleep or _default_sleep
    # ``staged_root`` has to reach the reader, not just sit in the signature:
    # binding it here is what makes the flag that names a different staging
    # directory mean anything at all.
    read_page = page_bytes or (
        lambda sample: load_page_bytes(sample, staged_root=staged_root)
    )
    started_at = utc_now_iso()
    notes: list[str] = []
    pod_id: str | None = None
    report: CanaryReport | None = None
    receipt_path: Path | None = None
    update_path: Path | None = None
    ledger_path: Path | None = None
    attempted = 0
    succeeded = 0
    error: str | None = None
    pod_summary: Mapping[str, object] = {}
    ready_at: str | None = None
    watchdog: CanaryWatchdog | None = None
    terminate_lock = threading.Lock()
    terminated: set[str] = set()
    # D28: the data centre and the pod's own hourly rate exist only in the
    # provider record, and only while the pod does. Read once, at teardown.
    pod_facts: dict[str, object] = {}
    teardown: dict[str, str | None] = {"stopped_at": None, "deleted_at": None}
    diagnostics: dict[str, object] = {}
    postrun: dict[str, object] = {}
    bootstrap_log: dict[str, object] = {}
    reads = _ReadTally()
    watch_reads: list[Mapping[str, object]] = []

    def say(line: str) -> None:
        """Say it on stdout as it happens.

        A 45-minute readiness wait that prints nothing until it ends looks
        identical to a hung driver. The receipt still gets ``notes``; this is
        for the operator watching a billed GPU.
        """

        print(f"  {line}", flush=True)

    def terminate(reason: str) -> None:
        """Stop then delete. Safe to call twice; safe to call from the timer.

        "Safe to call twice" has to mean *sends nothing twice*, not merely
        "does not raise": the watchdog and the ``finally`` both call this, and
        a second delete against a pod the provider already removed is a
        request that can only produce a spurious error in the receipt.
        """

        with terminate_lock:
            if pod_id is None or pod_id in terminated:
                return
            terminated.add(pod_id)
            pod_facts.update(_pod_facts(v1_client, pod_id, notes))
            try:
                v1_client.stop_pod(pod_id)
                teardown["stopped_at"] = utc_now_iso()
            except RunPodClientError as exc:
                notes.append(f"stop_pod refused: {exc}")
            try:
                v1_client.delete_pod(pod_id)
                teardown["deleted_at"] = utc_now_iso()
            except RunPodClientError as exc:
                notes.append(f"delete_pod refused: {exc}")
            notes.append(f"pod {pod_id} stop+delete sent ({reason})")

    def provider_status() -> str | None:
        """What the provider says about this pod, or ``None`` when unreadable.

        An unreadable provider is not evidence that a pod died: the bootstrap
        deadline is what bounds the wait, so a failed read keeps the poll going
        rather than condemning a pod that is merely pulling an image. A provider
        that answers "no such pod" is a different thing entirely and is reported
        as :data:`POD_MISSING`; the poll counts those.

        This also owns the receipt policy for the poll. One ``v1-get_pod``
        receipt per poll is 136 files for a single 45-minute bootstrap, and 130
        of them say the same word. Kept: the first read, every read whose
        status differs from the last, and every tenth otherwise. Nothing that
        changed is ever dropped, and the count of what was is receipted.
        """

        if pod_id is None:
            return None
        reads.count += 1
        index = reads.count

        def keep(pod: Any) -> bool:
            answer = _status_of(pod)
            if index == 1 or answer != reads.last or index % PROVIDER_RECEIPT_EVERY == 0:
                reads.kept += 1
                return True
            reads.suppressed += 1
            return False

        present, facts = _pod_probe(
            v1_client, pod_id, notes, quiet=True, persist_receipt=keep
        )
        if facts:
            # Keep the last record the provider gave us. If the pod is deleted
            # out from under the driver, this is all the ledger will ever have
            # for its data centre and rate -- and a ledger row written from the
            # provisioning line plus the last known record beats no row at all.
            pod_facts.update(facts)
        status = facts.get("desired_status")
        answer = (
            POD_MISSING
            if present is False
            else (status if isinstance(status, str) else None)
        )
        if index > 1 and answer != reads.last:
            line = f"pod {pod_id} provider status: {reads.last} -> {answer}"
            notes.append(line)
            say(line)
        reads.last = answer
        return answer

    def container_log() -> tuple[Mapping[str, object], ...]:
        """The bounded log tail, from whichever client offers one (v2)."""

        if pod_id is None:
            return ()
        read = _read_log_tail(
            pod_id, clients=(v2_client, v1_client), max_lines=LOG_TAIL_LINES
        )
        # The verdict reuses this tail rather than re-reading a pod that is
        # about to be deleted, so what the read did has to survive with it.
        watch_reads[:] = read.reads
        return read.lines

    try:
        # 1. D21: the bundle the start command will pin must already be in the
        #    bucket, proven by its publish receipt.
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

        # 2. D15/D17: the prompt is the runtime's, and its hash is the
        #    registry's. Resolve both before a GPU is rented.
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
        selection = load_canary_selection(paths.canary_selection, model_key)
        samples = _selected_samples(paths, selection)
        notes.append(f"{len(samples)} of {len(selection)} selected page(s) resolved")

        # 3. Provision. From here the `finally` owns the pod.
        pod_id, pod_summary = create_pod(digest, prompt)
        if pod_id is None:
            raise DriverError(
                "the provider did not return a pod id; nothing can be dispatched and "
                "nothing is assumed to be running"
            )
        # D48: the estimate names the most expensive pool entry -- a ceiling to
        # authorize against, not a prediction. The walk rents whichever entry
        # had capacity, and from here on the pod record, the receipt and the
        # ledger must say that one, priced from its own snapshot row. These are
        # rebound rather than shadowed so no later use can keep the ceiling.
        gpu_type, hourly_rate_usd, price_row_sha256 = _price_created_gpu(
            pod_summary,
            snapshot=snapshot,
            cloud=cloud,
            quoted_gpu_type=gpu_type,
            quoted_rate_usd=hourly_rate_usd,
            quoted_row_sha256=price_row_sha256,
            notes=notes,
            say=say,
        )
        _record_pod(
            paths,
            pod_id=pod_id,
            model_key=model_key,
            runtime=runtime,
            gpu_type=gpu_type,
            hourly_rate_usd=hourly_rate_usd,
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
                on_budget=lambda assessment: notes.append(
                    f"budget watchdog: {assessment.reason}"
                ),
                budget=BudgetWatchdog(
                    soft_cap_usd=BUDGET_SOFT_CAP_USD, hard_cap_usd=BUDGET_HARD_CAP_USD
                ),
                budget_inputs=lambda: (
                    _spent_usd(paths),
                    [hourly_rate_usd] if hourly_rate_usd else [],
                    lifetime_seconds,
                ),
                now=clock,
            )
            watchdog.start()

        worker = worker_factory(pod_id)

        # 4. Readiness. The deadline gives up, never the first error: a
        #    bootstrap pod answers 404/502/503 from the proxy for as long as it
        #    takes to pull the image, fetch the bundle, install and load.
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
            note=notes.append,
            log_tail=container_log,
            progress=say,
        )
        ready_at = utc_now_iso()
        notes.append(
            f"worker READY after {' -> '.join(observed)} "
            f"(deadline {bootstrap_deadline_seconds / 60:.0f} min)"
        )
        say(f"pod {pod_id} READY after {' -> '.join(observed)}")
        _mark_ready(paths, pod_id=pod_id, ready_at=ready_at)

        # 4b. D71: what the pod printed while coming up. The readiness
        #     tail exists only when readiness *failed*; when it succeeded,
        #     the bootstrap's own record -- the vendor resolution, the
        #     runtime self-test verdict, the model server's weight-loading
        #     warnings -- was printed before READY and is gone with the pod.
        #     mineru_vlm pod t0e8yz3oobso7i came up, answered every page
        #     with a malformed layout string, and no receipt could say
        #     whether the vendor CLI self-test had answered the same. Read
        #     now, before the pages push those lines out of the tail.
        bootstrap_log = _postrun_diagnostics(
            pod_id=pod_id,
            clients=(v2_client, v1_client),
            notes=notes,
            label="ready-time",
        )

        # 5. Dispatch, one page at a time, at the runtime's own timeout.
        records, attempted, succeeded = _dispatch_pages(
            paths=paths,
            model_key=model_key,
            entry=entry,
            samples=samples,
            worker=worker,
            worker_id=f"{model_key}-canary-{pod_id}",
            pod_id=pod_id,
            gpu_type=gpu_type,
            ready_at=ready_at,
            timeout_seconds=runtime.per_page_timeout_seconds,
            page_bytes=read_page,
        )

        # 6. Evaluate and receipt. Section 17's crash and deterministic-bug
        #    criteria are counted from the pages that actually failed -- an
        #    evaluation that only looked at the pages which worked would call
        #    a canary with a dead page a PASS.
        # blank_source is measured from the page the model was actually sent
        # (canary.dark_pixel_fraction); without this resolver every page counts
        # as non-blank and the section 17 non-empty check has no blank notion.
        canary_pages = {sample.case_key: sample for sample in samples}
        results = results_from_receipts(
            records,
            page_bytes=lambda case_key: read_page(canary_pages[case_key]),
        )
        crashes, deterministic, failure_notes = classify_page_failures(records)
        notes.extend(failure_notes)
        report = evaluate_canary(
            model_key,
            results,
            expected_model_revision=runtime.model_revision,
            hard_crashes=crashes,
            deterministic_runtime_bugs=deterministic,
            hourly_rate_usd=hourly_rate_usd,
            price_row_sha256=price_row_sha256,
            gpu_vram_mb=(
                None
                if runtime.gpu_min_vram_gb is None
                else runtime.gpu_min_vram_gb * 1024 * runtime.gpu_count_min
            ),
        )
        receipt_path = write_canary_receipt(
            report,
            paths,
            model_revision=runtime.model_revision,
            runtime_image_digest=digest,
            runtime_mode="bootstrap",
            gpu_type=gpu_type,
            started_at=started_at,
            finished_at=utc_now_iso(),
            base_image=runtime.base_image,
            pod_id=pod_id,
            authorization_receipt_path=authorization_receipt_path,
            authorization_receipt_sha256=authorization_receipt_sha256,
            pod_ledger_path="cost/pod_ledger.jsonl",
            gpu_total_vram_mb=(
                None
                if runtime.gpu_min_vram_gb is None
                else runtime.gpu_min_vram_gb * 1024 * runtime.gpu_count_min
            ),
        )
        update_path = write_registry_update(report, paths)

        # 7. Drain before the pod is taken away, so an in-flight page is not
        #    killed mid-inference (section 15.13's rule, applied here too).
        try:
            worker.drain()
            notes.append("worker drained")
        except Exception as exc:
            notes.append(f"drain failed ({type(exc).__name__}); terminating anyway")

        # 8. D62: the pod is deleted moments from now and its container log
        #    goes with it. The readiness tail (step 5) ends where the worker
        #    came up; what the runtime printed *while serving pages* -- the
        #    only account there is of a page that returned SUCCESS with
        #    nothing in it (mineru_vlm, pod r0yal3hocpipsm) -- lives only here.
        postrun = _postrun_diagnostics(
            pod_id=pod_id, clients=(v2_client, v1_client), notes=notes
        )

    except ReadinessError as exc:
        error = f"{type(exc).__name__}: {exc}"
        # The worker's own account of its death travels in the ready body's
        # ``last_error``. Without it the failure line says only that the stage
        # was terminal, which is the one thing the stage already said.
        worker_error = _worker_last_error(exc.last_ready_response)
        if worker_error is not None:
            error = f"{error}; worker last_error: {worker_error}"
        notes.append(f"driver refused: {error}")
        say(f"driver refused: {error}")
        # The pod is about to be deleted and its container log goes with it.
        # Whatever it printed while failing to come up is the only evidence
        # the next attempt has, so it is captured before the `finally` runs.
        diagnostics = _readiness_diagnostics(
            exc,
            pod_id=pod_id,
            clients=(v2_client, v1_client),
            notes=notes,
            watch_reads=watch_reads,
        )
    except (
        BundleError,
        CanaryError,
        DriverError,
        PlanError,
        PromptError,
        RunError,
        RunPodClientError,
    ) as exc:
        error = f"{type(exc).__name__}: {exc}"
        notes.append(f"driver refused: {error}")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        notes.append(f"driver raised: {error}")
    finally:
        if watchdog is not None:
            watchdog.stop()
            if watchdog.fired:
                notes.append("the lifetime watchdog had already terminated this pod")
        terminate("driver finished")
        pod_return = _confirm_gone(
            pod_id=pod_id,
            v1_client=v1_client,
            v2_client=v2_client,
            sleep=pause,
            notes=notes,
        )
        ledger_path = _write_ledger(
            paths,
            pod_id=pod_id,
            model_key=model_key,
            gpu_type=gpu_type,
            notes=notes,
            pod_facts=pod_facts,
            stopped_at=teardown["stopped_at"],
            deleted_at=teardown["deleted_at"],
        )

    if error is not None:
        status = "ERROR"
    elif report is not None and report.passed:
        status = "PASS"
    else:
        status = "FAIL"

    result = CanaryDriverResult(
        model_key=model_key,
        status=status,
        started_at=started_at,
        finished_at=utc_now_iso(),
        pages_attempted=attempted,
        pages_succeeded=succeeded,
        pod_return=pod_return,
        report=report,
        canary_receipt_path=receipt_path,
        registry_update_path=update_path,
        ledger_path=ledger_path,
        error=error,
        notes=tuple(notes),
    )
    driver_receipt = paths.canary_driver_receipt(model_key)
    write_json_atomic(
        driver_receipt,
        {
            **result.to_dict(),
            "pod_summary": dict(pod_summary),
            "pod_teardown": {
                "stopped_at": teardown["stopped_at"],
                "deleted_at": teardown["deleted_at"],
                **{str(key): value for key, value in pod_facts.items()},
            },
            "readiness": {
                "ready_at": ready_at,
                "provider_reads": reads.to_dict(),
                **diagnostics,
            },
            "postrun": postrun,
            "bootstrap_log": bootstrap_log,
        },
        context="canary driver receipt",
    )
    return CanaryDriverResult(
        model_key=result.model_key,
        status=result.status,
        started_at=result.started_at,
        finished_at=result.finished_at,
        pages_attempted=result.pages_attempted,
        pages_succeeded=result.pages_succeeded,
        pod_return=result.pod_return,
        report=result.report,
        canary_receipt_path=result.canary_receipt_path,
        registry_update_path=result.registry_update_path,
        driver_receipt_path=driver_receipt,
        ledger_path=result.ledger_path,
        error=result.error,
        notes=result.notes,
    )


# --------------------------------------------------------------- internals


def _selected_samples(
    paths: CampaignPaths, selection: Sequence[str]
) -> tuple[SourceSample, ...]:
    """The manifest rows the canary selection names, in selection order."""

    by_case = {sample.case_key: sample for sample in load_source_manifest(paths.source_manifest)}
    missing = [case_key for case_key in selection if case_key not in by_case]
    if missing:
        raise DriverError(
            f"{len(missing)} canary page(s) are not in the source manifest, first: "
            f"{missing[0]!r}. The selection and the manifest disagree; refusing to run a "
            "canary over a different set of pages than the one that was selected."
        )
    return tuple(by_case[case_key] for case_key in selection)


def _dispatch_pages(
    *,
    paths: CampaignPaths,
    model_key: str,
    entry: ModelPlanEntry,
    samples: Sequence[SourceSample],
    worker: Any,
    worker_id: str,
    pod_id: str,
    gpu_type: str,
    ready_at: str,
    timeout_seconds: int,
    page_bytes: Callable[[SourceSample], bytes],
) -> tuple[tuple[Mapping[str, Any], ...], int, int]:
    """One page at a time through ``run.dispatch_page`` (D20).

    A page whose bytes cannot be read, or whose dispatch failed, still
    produces a canary page record. ``evaluate_canary`` must see the failures
    -- a canary judged only on the pages that worked is not a canary.
    """

    plan = build_plan(
        model_key=model_key, samples=samples, entry=entry, job_kind="canary"
    )
    by_case = {job.case_key: job for job in plan.jobs}
    records: list[Mapping[str, Any]] = []
    attempted = 0
    succeeded = 0

    pages_path = paths.canary_pages(model_key)
    pages_path.parent.mkdir(parents=True, exist_ok=True)

    with CampaignQueue(paths.queue_db) as queue:
        queue.upsert_shards(plan.shards)
        queue.enqueue(plan.jobs)
        events = EventLog(paths.events_log)
        for sample in samples:
            job = by_case[sample.case_key]
            attempted += 1
            try:
                data = page_bytes(sample)
            except DriverError as exc:
                record = _failed_record(sample, "INPUT_DECODE", str(exc))
                records.append(record)
                write_jsonl_append(pages_path, record, context="canary page record")
                continue
            outcome = dispatch_page(
                worker=worker,
                worker_id=worker_id,
                pod_id=pod_id,
                gpu_type=gpu_type,
                job=job,
                sample=sample,
                entry=entry,
                paths=paths,
                queue=queue,
                events=events,
                image_bytes=data,
                worker_ready_at=ready_at,
                timeout_seconds=timeout_seconds,
            )
            if outcome.succeeded and outcome.receipt_path is not None:
                from arena.provider.safety import read_json

                document = read_json(outcome.receipt_path)
                if isinstance(document, Mapping):
                    records.append(document)
                    write_jsonl_append(pages_path, dict(document), context="canary page record")
                    succeeded += 1
                    continue
            record = _failed_record(
                sample, outcome.error_class or "UNKNOWN", outcome.error_message
            )
            records.append(record)
            write_jsonl_append(pages_path, record, context="canary page record")
    return tuple(records), attempted, succeeded


def _failed_record(
    sample: SourceSample, error_class: str, message: str | None
) -> dict[str, Any]:
    """A canary page that produced no receipt. Zeros are absences, not metrics."""

    return {
        "schema": "tavonel.arena.canary_page.v1",
        "campaign_id": CAMPAIGN_ID,
        "case_key": sample.case_key,
        "sample_id": sample.sample_id,
        "benchmark": sample.benchmark,
        "status": "FAILED",
        "error_class": error_class,
        "error_message": None if message is None else message[:2000],
        "started_at": utc_now_iso(),
        "model_revision": "",
        "output_chars": 0,
        "peak_vram_mb": None,
    }


def _price_created_gpu(
    pod_summary: Mapping[str, object],
    *,
    snapshot: PriceSnapshot,
    cloud: str,
    quoted_gpu_type: str,
    quoted_rate_usd: float | None,
    quoted_row_sha256: str | None,
    notes: list[str],
    say: Callable[[str], None],
) -> tuple[str, float | None, str | None]:
    """``(gpu_type, hourly_rate, price_row_sha256)`` for the GPU actually created.

    D48's pool walk means the created GPU need not be the quoted one: pod
    jdwdnvg8a2rzx6's ledger row said ``NVIDIA L40S`` while the pod that ran was
    a GeForce RTX 4090 at $0.74/h. When the walk fell to another entry the row
    is re-read from the snapshot for *that* GPU; when the snapshot does not
    price it, the rate is left empty so the ledger falls back to the provider's
    own ``costPerHr`` rather than carrying a price nobody was charged.
    """

    created = pod_summary.get("gpu_type_id_created")
    if not isinstance(created, str) or not created or created == quoted_gpu_type:
        return quoted_gpu_type, quoted_rate_usd, quoted_row_sha256
    try:
        row = snapshot.row(created)
    except RunPodClientError:
        line = (
            f"the pool walk created a {created}, which the price snapshot does not "
            f"carry; the ledger is priced from the provider's own rate instead of the "
            f"quoted {quoted_gpu_type}"
        )
        notes.append(line)
        say(line)
        return created, None, None
    rate = row.rate_for(cloud)
    line = (
        f"the pool walk created a {created}, not the quoted {quoted_gpu_type}; "
        f"repriced from its own {cloud} snapshot row "
        f"({'no rate' if rate is None else f'{rate:.4f} USD/h'})"
    )
    notes.append(line)
    say(line)
    return created, rate, row.row_sha256()


def _record_pod(
    paths: CampaignPaths,
    *,
    pod_id: str,
    model_key: str,
    runtime: RuntimeSpecView,
    gpu_type: str,
    hourly_rate_usd: float | None,
    snapshot: PriceSnapshot,
    authorization_receipt_path: str | None,
    authorization_receipt_sha256: str | None,
) -> None:
    from arena.provider.runpod_pods import pod_name

    with CampaignQueue(paths.queue_db) as queue:
        queue.upsert_pod(
            PodRecord(
                pod_id=pod_id,
                model_key=model_key,
                name=pod_name(model_key, 0),
                state="PROVISIONING",
                gpu_type=gpu_type,
                cloud_type="SECURE",
                runtime_mode="bootstrap",
                listed_rate_usd_per_hour=hourly_rate_usd,
                # D57: the pool walk (D48) may rebind gpu_type but never the
                # count the runtime asked for -- that stays runtime.gpu_count_min.
                gpu_count=runtime.gpu_count_min,
                price_snapshot_sha256=_sha256_ref(snapshot.snapshot_sha256()),
                provider_api_version="v1",
                authorization_receipt_path=authorization_receipt_path,
                authorization_receipt_sha256=authorization_receipt_sha256,
                provisioned_at=utc_now_iso(),
            )
        )


def _mark_ready(paths: CampaignPaths, *, pod_id: str, ready_at: str) -> None:
    with CampaignQueue(paths.queue_db) as queue:
        for pod in queue.pods():
            if pod.pod_id != pod_id:
                continue
            queue.upsert_pod(
                PodRecord(
                    pod_id=pod.pod_id,
                    model_key=pod.model_key,
                    name=pod.name,
                    state="READY",
                    worker_id=pod.worker_id,
                    gpu_type=pod.gpu_type,
                    cloud_type=pod.cloud_type,
                    data_center_id=pod.data_center_id,
                    runtime_mode=pod.runtime_mode,
                    listed_rate_usd_per_hour=pod.listed_rate_usd_per_hour,
                    gpu_count=pod.gpu_count,
                    price_snapshot_sha256=pod.price_snapshot_sha256,
                    provider_api_version=pod.provider_api_version,
                    authorization_receipt_path=pod.authorization_receipt_path,
                    authorization_receipt_sha256=pod.authorization_receipt_sha256,
                    provisioned_at=pod.provisioned_at,
                    model_ready_at=ready_at,
                    last_job_finished_at=pod.last_job_finished_at,
                    terminated_at=pod.terminated_at,
                )
            )
            return


def _confirm_gone(
    *,
    pod_id: str | None,
    v1_client: RunPodV1Client,
    v2_client: RunPodPodsClient,
    sleep: Callable[[float], None],
    notes: list[str],
    attempts: int = 6,
    poll_seconds: float = 10.0,
) -> PodReturn:
    """Re-list on **both** APIs until the pod is gone from both (D20).

    A stop is not a return and a delete request is not a return. Only a
    listing that no longer carries the id is, and only when both API versions
    agree -- a pod created on v1 can outlive its absence from v2.
    """

    if pod_id is None:
        return PodReturn(
            pod_id=None,
            stop_called=False,
            delete_called=False,
            gone_from_v1=True,
            gone_from_v2=True,
            attempts=0,
            notes=("no pod was created, so there is nothing to return",),
        )
    gone_v1 = False
    gone_v2 = False
    used = 0
    for index in range(attempts):
        used = index + 1
        if not gone_v1:
            gone_v1 = _absent(v1_client, pod_id, notes, "v1")
        if not gone_v2:
            gone_v2 = _absent(v2_client, pod_id, notes, "v2")
        if gone_v1 and gone_v2:
            break
        if index + 1 < attempts:
            sleep(poll_seconds)
    if not (gone_v1 and gone_v2):
        notes.append(
            f"pod {pod_id} is still listed after {used} re-list attempt(s) "
            f"(gone from v1={gone_v1}, v2={gone_v2}); run "
            "`python -m arena.controller cleanup-verify --execute`"
        )
    return PodReturn(
        pod_id=pod_id,
        stop_called=True,
        delete_called=True,
        gone_from_v1=gone_v1,
        gone_from_v2=gone_v2,
        attempts=used,
        notes=(),
    )


def _absent(client: Any, pod_id: str, notes: list[str], label: str) -> bool:
    """True only when a live listing came back without this pod id.

    An API that could not be read is *not* evidence of absence, and neither is
    a dry-run client: both return ``False`` so the caller keeps trying and the
    receipt records that cleanup was not confirmed.
    """

    if not getattr(client, "execute", False):
        return False
    try:
        listed = client.list_pods()
    except RunPodClientError as exc:
        notes.append(f"REST {label} listing failed while confirming teardown: {exc}")
        return False
    from arena.provider.runpod_pods import ProviderReceipt

    if isinstance(listed, ProviderReceipt):
        return False
    return all(pod.pod_id != pod_id for pod in listed)


def _pod_probe(
    v1_client: Any,
    pod_id: str,
    notes: list[str],
    *,
    quiet: bool = False,
    persist_receipt: bool | Callable[[Any], bool] = True,
) -> tuple[bool | None, dict[str, object]]:
    """``(present, facts)`` for one pod. ``present`` is ``None`` when unread.

    The three answers are genuinely different and the readiness poll acts on
    each differently: ``True`` with a status, ``False`` for a provider that
    answered "no such pod" (deleted out from under us), ``None`` for a read
    that failed (which is not evidence of anything).
    """

    reader = getattr(v1_client, "get_pod", None)
    if reader is None or not getattr(v1_client, "execute", False):
        return None, {}
    try:
        pod = _read_pod(reader, pod_id, persist_receipt=persist_receipt)
    except RunPodClientError as exc:
        if not quiet:
            notes.append(f"provider record for {pod_id} could not be read: {exc}")
        return None, {}
    if pod is None:
        # A 404 right after a create is the provider being eventually
        # consistent, not the pod being dead. Say nothing rather than the
        # wrong thing; the bootstrap deadline is what bounds the wait, and the
        # caller is the one that counts consecutive absences.
        return False, {}
    facts: dict[str, object] = {}
    for field_name, attribute in (
        ("desired_status", "desired_status"),
        ("data_center_id", "data_center_id"),
        ("provider_rate_usd_per_hour", "cost_usd_per_hour"),
        ("machine_id", "machine_id"),
    ):
        value = getattr(pod, attribute, None)
        if value is not None:
            facts[field_name] = value
    return True, facts


def _read_pod(
    reader: Any, pod_id: str, *, persist_receipt: bool | Callable[[Any], bool]
) -> Any:
    """Call ``get_pod``, asking it not to receipt when the caller said so.

    A client double that predates the keyword is still a valid client; it just
    keeps every receipt.
    """

    try:
        return reader(pod_id, persist_receipt=persist_receipt)
    except TypeError as exc:
        if "persist_receipt" not in str(exc):
            raise
        return reader(pod_id)


def _pod_facts(
    v1_client: Any, pod_id: str, notes: list[str], *, quiet: bool = False
) -> dict[str, object]:
    """The provider's own record of this pod: status, data centre, rate (D28).

    Best effort by construction. A read that fails leaves the ledger fields
    empty and says so; inventing a data centre or a price to fill a column
    would be worse than an honest gap.
    """

    _present, facts = _pod_probe(v1_client, pod_id, notes, quiet=quiet)
    return facts


def _status_of(pod: Any) -> str | None:
    """The status string a ``get_pod`` answer carries, or the gone sentinel."""

    if pod is None:
        return POD_MISSING
    status = getattr(pod, "desired_status", None)
    return status if isinstance(status, str) else None


@dataclass(frozen=True, slots=True)
class _LogTailRead:
    """The merged tail, and what each source read actually did.

    ``reads`` is what makes a short tail readable after the fact: how many
    lines were asked for, how many came back and why the drain stopped. A
    receipt that says only "194 line(s)" cannot tell a runtime that printed
    194 lines from a backfill that was cut at 194.
    """

    lines: tuple[Mapping[str, object], ...] = ()
    reads: tuple[Mapping[str, object], ...] = ()

    @property
    def note(self) -> str:
        base = f"{len(self.lines)} line(s) from the provider log endpoint"
        detail = _reads_detail(self.reads)
        return base if detail is None else f"{base} ({detail})"


def _reads_detail(reads: Sequence[Mapping[str, object]]) -> str | None:
    """"container: 400 requested, 194 received, stopped_because=quiet"."""

    if not reads:
        return None
    return "; ".join(
        f"{read.get('source')}: {read.get('tail_requested')} requested, "
        f"{read.get('line_count')} received, "
        f"stopped_because={read.get('stopped_because')}"
        for read in reads
    )


def _log_reads_since(client: Any, mark: int) -> tuple[Mapping[str, object], ...]:
    """The ``get_logs`` receipt summaries this client produced after ``mark``."""

    receipts = getattr(client, "receipts", ())
    out: list[Mapping[str, object]] = []
    for receipt in tuple(receipts)[mark:]:
        if getattr(receipt, "action", None) != "get_logs":
            continue
        summary = getattr(receipt, "summary", None)
        if not isinstance(summary, Mapping):
            continue
        out.append(
            {
                "source": summary.get("source"),
                "tail_requested": summary.get("tail_requested"),
                "line_count": summary.get("line_count"),
                "stopped_because": summary.get("stopped_because"),
            }
        )
    return tuple(out)


def _read_log_tail(
    pod_id: str,
    *,
    clients: Sequence[Any],
    max_lines: int,
    container_tail: int | None = None,
) -> _LogTailRead:
    """The container log tail from whichever injected client offers one.

    REST v1 has no logs endpoint, so in practice this is v2 addressing the same
    pod id. Raises :class:`RunPodClientError` so the caller decides what a
    failed read means; returns ``()`` when no client can read logs at all.

    **Each source is fetched on its own.** The endpoint returns the container
    lines and the system lines as two sequences rather than one time-ordered
    stream, so a single bounded tail over both keeps whichever block comes last
    and drops the other. The 2026-09-03 GLM-OCR receipt is 200 system lines of
    image-pull progress ending at 13:03Z, with the ``[arena] FATAL`` the pod
    printed at 13:14Z nowhere in it. The verdict needs ``container`` (the
    runtime's own output) and the restart marker lives in ``system``, so both
    are read with their own tail and merged by timestamp afterwards.
    """

    last_error: RunPodClientError | None = None
    for client in clients:
        reader = getattr(client, "get_logs", None)
        if reader is None or not getattr(client, "execute", False):
            continue
        merged: list[Mapping[str, object]] = []
        read_any = False
        container_error: RunPodClientError | None = None
        mark = len(tuple(getattr(client, "receipts", ())))
        for source in LOG_SOURCES_READ:
            tail = (
                container_tail
                if source == "container" and container_tail is not None
                else max_lines
            )
            try:
                lines = reader(pod_id, tail=tail, max_lines=max(max_lines, tail), source=source)
            except RunPodClientError as exc:
                last_error = exc
                if source == "container":
                    container_error = exc
                continue
            if not isinstance(lines, (tuple, list)):
                # A dry-run client answers with a receipt, not log lines.
                continue
            read_any = True
            merged.extend(entry for entry in lines if isinstance(entry, Mapping))
        if container_error is not None:
            # The container source is the one the readiness verdict is made
            # from. Returning the system lines alone would look like a
            # successful read of a runtime that printed nothing.
            raise container_error
        if not read_any:
            continue
        # Stable by timestamp: the two sequences arrive one after the other,
        # and the tail slice downstream keeps the *end* of this list.
        merged.sort(key=lambda entry: str(entry.get("ts") or ""))
        return _LogTailRead(tuple(merged), _log_reads_since(client, mark))
    if last_error is not None:
        raise last_error
    return _LogTailRead()


def _worker_last_error(body: Mapping[str, object] | None) -> str | None:
    """``last_error`` from a scrubbed ready body, when it carries one."""

    if not body:
        return None
    value = body.get("last_error")
    return value if isinstance(value, str) and value.strip() else None


def _readiness_diagnostics(
    exc: ReadinessError,
    *,
    pod_id: str | None,
    clients: Sequence[Any],
    notes: list[str],
    max_lines: int = LOG_TAIL_LINES,
    container_tail: int = DIAGNOSTIC_CONTAINER_TAIL_LINES,
    watch_reads: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """What the pod was doing when readiness gave up, kept before the delete.

    The container log is the only evidence the next attempt has: the pod and
    its log are deleted moments after this runs. When the poll already read a
    tail -- which it does whenever a signature ended the wait -- that tail is
    reused rather than re-fetched, because the pod may be gone by now.

    Lines that carry credential material are dropped individually. Withholding
    the whole tail because one line echoed a presigned URL would throw away the
    198 lines that say why the runtime died.
    """

    record: dict[str, object] = {
        "last_status": exc.last_status,
        # The body behind ``last_status``. "HTTP 200 stage=CRASHED" says the
        # worker gave up; ``last_error`` in here says what killed it.
        "last_ready_response": (
            None if exc.last_ready_response is None else dict(exc.last_ready_response)
        ),
        "observed_stages": list(exc.observed),
        "provider_status": exc.provider_status,
        "polls": exc.polls,
        "elapsed_seconds": round(exc.elapsed_seconds, 3),
        "error_class": exc.error_class,
        "signature": exc.signature,
        "container_log_tail": None,
        "container_log_note": "not attempted",
        "container_log_reads": [],
    }
    if exc.log_tail:
        record["container_log_tail"] = [dict(line) for line in exc.log_tail]
        note = exc.log_note or (
            f"{len(exc.log_tail)} line(s) carried by the readiness verdict"
        )
        detail = _reads_detail(watch_reads)
        if detail is not None:
            note = f"{note} ({detail})"
        record["container_log_note"] = note
        record["container_log_reads"] = [dict(entry) for entry in watch_reads]
        return record
    if pod_id is None:
        record["container_log_note"] = "no pod id; nothing to read"
        return record
    try:
        read = _read_log_tail(
            pod_id,
            clients=clients,
            max_lines=max_lines,
            container_tail=container_tail,
        )
    except RunPodClientError as read_error:
        record["container_log_note"] = f"log read failed: {read_error}"
        return record
    record["container_log_reads"] = [dict(entry) for entry in read.reads]
    if not read.lines:
        record["container_log_note"] = (
            f"the provider returned no log lines ({read.note})" if read.reads
            else "the provider returned no log lines"
        )
        return record
    tail, dropped = scrub_log_lines(read.lines)
    note = read.note
    if dropped:
        note += f"; {dropped} line(s) withheld by the secret guard"
        notes.append(f"{dropped} container log line(s) withheld from the receipt")
    record["container_log_tail"] = list(tail) or None
    record["container_log_note"] = note
    return record


def _postrun_diagnostics(
    *,
    pod_id: str | None,
    clients: Sequence[Any],
    notes: list[str],
    max_lines: int = LOG_TAIL_LINES,
    container_tail: int = DIAGNOSTIC_CONTAINER_TAIL_LINES,
    label: str = "post-run",
) -> dict[str, object]:
    """The container log after the pages ran, kept before the delete (D62).

    D71 reuses it at READY (``label="ready-time"``) for the bootstrap lines.

    ``_readiness_diagnostics`` keeps what the pod printed while coming up.
    This keeps what it printed while serving: the runtime's own account of
    every page, which is the only evidence when a page returns SUCCESS with an
    empty body and the worker has nothing to say about it. Same scrub, same
    per-line withholding, same "log read failed" honesty when the provider
    cannot answer -- a missing tail is recorded as missing, never as silence.
    """

    record: dict[str, object] = {
        "captured_at": utc_now_iso(),
        "container_log_tail": None,
        "container_log_note": "not attempted",
        "container_log_reads": [],
    }
    if pod_id is None:
        record["container_log_note"] = "no pod id; nothing to read"
        return record
    try:
        read = _read_log_tail(
            pod_id,
            clients=clients,
            max_lines=max_lines,
            container_tail=container_tail,
        )
    except RunPodClientError as read_error:
        record["container_log_note"] = f"log read failed: {read_error}"
        notes.append(f"{label} container log not captured: {read_error}")
        return record
    record["container_log_reads"] = [dict(entry) for entry in read.reads]
    if not read.lines:
        record["container_log_note"] = (
            f"the provider returned no log lines ({read.note})" if read.reads
            else "the provider returned no log lines"
        )
        return record
    tail, dropped = scrub_log_lines(read.lines)
    note = read.note
    if dropped:
        note += f"; {dropped} line(s) withheld by the secret guard"
        notes.append(f"{dropped} {label} container log line(s) withheld from the receipt")
    record["container_log_tail"] = list(tail) or None
    record["container_log_note"] = note
    return record


def _write_ledger(
    paths: CampaignPaths,
    *,
    pod_id: str | None,
    model_key: str,
    gpu_type: str,
    notes: list[str],
    pod_facts: Mapping[str, object] | None = None,
    stopped_at: str | None = None,
    deleted_at: str | None = None,
) -> Path | None:
    """D28: the pod's billed life, written when the pod is given back."""

    if pod_id is None:
        return None
    facts: Mapping[str, object] = pod_facts or {}
    terminated = utc_now_iso()
    receipts: list[Mapping[str, object]] = []
    receipt_dir = paths.receipt_dir(model_key)
    if receipt_dir.is_dir():
        from arena.provider.safety import read_json

        for path in sorted(receipt_dir.glob("*.json")):
            document = read_json(path)
            if isinstance(document, Mapping) and document.get("pod_id") == pod_id:
                receipts.append(document)
    useful = cost_module.useful_seconds_by_pod(receipts)
    retried = cost_module.retry_seconds_by_pod(receipts)

    with CampaignQueue(paths.queue_db) as queue:
        for pod in queue.pods():
            if pod.pod_id != pod_id:
                continue
            data_center = facts.get("data_center_id")
            provider_rate = facts.get("provider_rate_usd_per_hour")
            # The price snapshot is what we agreed to pay; the pod record is
            # what the provider says it charges. The snapshot wins when both
            # exist -- it is the receipted figure -- and the pod record is what
            # keeps the row priced at all when the quote never arrived.
            rate = pod.listed_rate_usd_per_hour
            if rate is None and isinstance(provider_rate, (int, float)):
                rate = float(provider_rate)
                notes.append(
                    f"no price snapshot row for {pod_id}; the ledger is priced from the "
                    f"provider's own costPerHr ({rate:.4f} USD/h)"
                )
            settled = PodRecord(
                pod_id=pod.pod_id,
                model_key=pod.model_key,
                name=pod.name,
                state="TERMINATED",
                worker_id=pod.worker_id,
                gpu_type=pod.gpu_type or gpu_type,
                cloud_type=pod.cloud_type,
                data_center_id=(
                    data_center if isinstance(data_center, str) else pod.data_center_id
                ),
                runtime_mode=pod.runtime_mode,
                listed_rate_usd_per_hour=rate,
                gpu_count=pod.gpu_count,
                price_snapshot_sha256=pod.price_snapshot_sha256,
                provider_api_version=pod.provider_api_version,
                authorization_receipt_path=pod.authorization_receipt_path,
                authorization_receipt_sha256=pod.authorization_receipt_sha256,
                provisioned_at=pod.provisioned_at,
                model_ready_at=pod.model_ready_at,
                last_job_finished_at=pod.last_job_finished_at,
                terminated_at=terminated,
            )
            queue.upsert_pod(settled)
            row = cost_module.build_ledger_row(
                settled,
                useful_inference_seconds=useful.get(pod_id, 0.0),
                retry_seconds=retried.get(pod_id, 0.0),
                stopped_at=stopped_at,
                deleted_at=deleted_at,
            )
            append = cost_module.append_pod_ledger(paths, row)
            if not append.validated:
                notes.append(
                    f"pod ledger row for {pod_id} did not satisfy pod-ledger.schema.json "
                    f"and was kept in {append.path.name}: {append.problem}"
                )
            return append.path
    notes.append(f"pod {pod_id} has no queue row; no ledger line could be written")
    return None


def _spent_usd(paths: CampaignPaths) -> float:
    from arena.controller.authorization_gate import cumulative_budget

    budget = cumulative_budget(paths, required_usd=0.0)
    return budget.committed_usd + budget.spent_usd


def _sha256_ref(value: str) -> str:
    return value if value.startswith("sha256:") else f"sha256:{value}"


def _default_sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


# Re-exported for the CLI so it does not need three imports to build a request.
__run_request__ = RunRequest
__run_response__ = RunResponse
__clean_up__ = clean_up_campaign
