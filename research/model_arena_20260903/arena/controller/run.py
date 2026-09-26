"""The dispatch loop: provision, poll, run one page, checkpoint, repeat.

Masterplan section 15.7 is the shape of the loop, and the order inside a page
is not negotiable:

    raw write -> fsync -> hash -> canonical write -> receipt write -> SUCCESS

The SUCCESS marker is last. A pod that dies on page 99 costs page 99, never
pages 1-98.

Everything external is injected: the provider client, the worker-client factory
and the clock. That is what lets the failure paths -- checksum mismatch, budget
hard cap, circuit breaker, idle killer -- be exercised without a GPU.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Protocol

from arena.constants import CAMPAIGN_ID
from arena.controller import retry as retry_policy
from arena.controller.events import EventLog
from arena.controller.paths import CampaignPaths
from arena.controller.plan import ModelPlanEntry, SourceSample
from arena.controller.queue import CampaignQueue, JobRecord
from arena.controller.watchdogs import BudgetAssessment, CircuitBreaker
from arena.provider.safety import (
    SecretLeak,
    assert_secret_free,
    atomic_write_bytes,
    read_json,
    sha256_bytes,
    utc_now_iso,
    write_json_atomic,
    write_jsonl_append,
)
from arena.provider.worker_client import (
    RunRequest,
    RunResponse,
    WorkerChecksumError,
    WorkerError,
    WorkerHTTPError,
    WorkerProtocolError,
)

__all__ = [
    "DEAD_POD_STATUSES",
    "DEFAULT_LOG_INTERVAL_SECONDS",
    "FATAL_LOG_SIGNATURES",
    "LOG_TAIL_LINES",
    "POD_MISSING",
    "RESTART_MARKER",
    "Eligibility",
    "PageOutcome",
    "ReadinessError",
    "RunError",
    "WorkerPort",
    "build_page_receipt",
    "checkpoint_page",
    "dispatch_page",
    "eligibility",
    "poll_until_ready",
    "record_error",
    "scrub_log_lines",
    "scrub_ready_body",
]

READY_STAGES: Final = ("IMAGE_READY", "MODEL_LOADING", "WARMING", "READY")
TERMINAL_WORKER_STAGES: Final = frozenset({"CRASHED", "OOM", "QUARANTINED", "TERMINATED"})
# A bearer the worker refuses is refused on every later poll too. Everything
# else the RunPod proxy answers with -- 404, 502, 503, a dropped connection --
# is what "nothing is listening on 8000 yet" looks like from outside.
FATAL_READY_STATUSES: Final = frozenset({401, 403})
# The provider's own verdict that the pod will never answer. Anything else it
# reports (or fails to report) while a 4.7 GB image is pulling is "still coming".
DEAD_POD_STATUSES: Final = frozenset({"EXITED", "FAILED", "TERMINATED"})
# A sentinel ``pod_status`` may return for "the provider answered, and it said
# this pod does not exist". Distinct from ``None``, which means "the provider
# could not be read" -- a 404 twice running is a deleted pod, an unreadable
# provider is a pod that may still be pulling an image.
POD_MISSING: Final = "MISSING"
MISSING_POLLS_BEFORE_GIVING_UP: Final = 2

# What a failing bootstrap prints. The 2026-09-03 GLM-OCR pod is the shape
# these come from: the model server died ten seconds after start because
# Transformers did not know the architecture, `entrypoint.sh` exited 70, and
# RunPod restarted the container every two minutes -- forever, on a billed GPU,
# while the v1 pod record still said RUNNING. None of that is visible to the
# readiness poll; all of it is in the container log.
#
# Each signature carries the section 15.9 error class the driver receipts it
# under. DEPENDENCY and MODEL_LOAD both retry zero times (arena.controller.
# retry: "dependency/import error", "model load failure"), which is the point:
# a model server that cannot load is not going to load on the next poll.
FATAL_LOG_SIGNATURES: Final = (
    ("[arena] FATAL", "MODEL_LOAD"),
    ("[arena] model server exited", "MODEL_LOAD"),
    ("[arena] model server did not answer", "MODEL_LOAD"),
    ("Traceback (most recent call last)", "DEPENDENCY"),
)
# RunPod prints this once per container start. Twice means it restarted, and a
# bootstrap that restarts is a crash loop -- the weights cache makes each cycle
# cheap enough that it can run out the whole 45-minute deadline.
RESTART_MARKER: Final = "start container for"
RESTARTS_BEFORE_CRASH_LOOP: Final = 2
# Roughly one log read every two minutes. Expressed as seconds and divided by
# the poll interval so the cadence does not silently change with the interval.
DEFAULT_LOG_INTERVAL_SECONDS: Final = 120.0
LOG_TAIL_LINES: Final = 200
DEFAULT_HEARTBEAT_SECONDS: Final = 300.0
# Milestone lines the runtime prints for the operator to follow.
ARENA_LOG_PREFIX: Final = "[arena]"
# Substrings that make a log line unfit to persist. ``assert_secret_free``
# catches the campaign's own loaded credentials and the SigV4 query shape; these
# cover the rest of what a bootstrap log can echo -- a presigned bundle URL, an
# Authorization header, a worker bearer written out by a curl trace.
LOG_SCRUB_MARKERS: Final = ("X-Amz", "Signature=", "Bearer")


class RunError(RuntimeError):
    """The full run refused to start or continue."""


class ReadinessError(RunError):
    """The worker will not become READY, or did not in the time allowed.

    Carries what was actually observed rather than only a sentence about it:
    the driver decides whether to pull container logs from the provider by
    asking ``provider_status``, and the receipt records the last status seen.
    """

    def __init__(
        self,
        message: str,
        *,
        observed: Sequence[str] = (),
        last_status: str | None = None,
        provider_status: str | None = None,
        elapsed_seconds: float = 0.0,
        polls: int = 0,
        error_class: str | None = None,
        signature: str | None = None,
        log_tail: Sequence[Mapping[str, object]] = (),
        log_note: str | None = None,
        last_ready_response: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.observed = tuple(observed)
        self.last_status = last_status
        self.provider_status = provider_status
        self.elapsed_seconds = elapsed_seconds
        self.polls = polls
        # The section 15.9 class this failure is receipted under, when the
        # container log named one. ``None`` means the wait ended for a reason
        # the taxonomy does not cover (a deadline, a rejected bearer).
        self.error_class = error_class
        # The exact text that ended the wait, so the receipt says *what* was
        # seen and not only that something was.
        self.signature = signature
        self.log_tail = tuple(log_tail)
        self.log_note = log_note
        # The last body ``/v1/ready`` actually parsed, secret-scrubbed. A
        # terminal stage says the worker gave up; ``last_error`` inside this
        # body says what killed it, and the 2026-09-03 GLM-OCR receipt kept
        # only "HTTP 200 stage=CRASHED" because nothing held on to it.
        self.last_ready_response = (
            None if last_ready_response is None else dict(last_ready_response)
        )


class WorkerPort(Protocol):
    """What the run loop needs from a worker. ``WorkerClient`` satisfies it."""

    def ready(self) -> Mapping[str, object]: ...

    def heartbeat(self) -> Mapping[str, object]: ...

    def run(self, request: RunRequest) -> RunResponse: ...

    def drain(self) -> Mapping[str, object]: ...


# ------------------------------------------------------------- eligibility


@dataclass(frozen=True, slots=True)
class Eligibility:
    allowed: bool
    reason: str
    runtime_mode: str
    waiver_path: Path | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "runtime_mode": self.runtime_mode,
            "waiver": None if self.waiver_path is None else self.waiver_path.name,
        }


CANARY_VERDICTS: Final = frozenset({"PASS", "FAIL"})


def entry_with_canary_verdict(
    entry: ModelPlanEntry, paths: CampaignPaths
) -> tuple[ModelPlanEntry, str | None]:
    """The registry entry with the canary's verdict applied (D74).

    ``model_registry.json`` is a resolve-time artifact: ``arena.registry
    resolve`` writes ``canary_status: PENDING`` and ``validate`` insists on it.
    The canary driver does not rewrite that file; it writes
    ``receipts/registry-updates/<model>.json`` (``tavonel.arena.registry_update.v1``,
    sourced from the canary receipt) with the verdict. That receipt is the
    evidence, so it is what the Full Run gate reads. Returns the entry and a
    note naming the receipt, or the entry unchanged and ``None`` when no
    verdict has been receipted. A malformed receipt is refused, not ignored.
    """

    path = paths.registry_update(entry.model_key)
    if not path.is_file():
        return entry, None
    document = read_json(path)
    if not isinstance(document, Mapping):
        raise RunError(f"{path} is not a JSON object")
    if document.get("schema") != "tavonel.arena.registry_update.v1":
        raise RunError(f"{path} is not a tavonel.arena.registry_update.v1 receipt")
    if document.get("model_key") != entry.model_key:
        raise RunError(
            f"{path} names model_key {document.get('model_key')!r}, not {entry.model_key!r}"
        )
    fields = document.get("fields")
    if not isinstance(fields, Mapping):
        raise RunError(f"{path} carries no fields")
    status = fields.get("canary_status")
    if status not in CANARY_VERDICTS:
        raise RunError(f"{path} carries canary_status {status!r}; expected PASS or FAIL")
    eligible = bool(fields.get("full_run_eligible", False))
    updated = replace(entry, canary_status=str(status), full_run_eligible=eligible)
    note = (
        f"canary verdict {status} from {path.name} (source "
        f"{document.get('source')}, proposed {document.get('proposed_at')})"
    )
    return updated, note


def eligibility(
    entry: ModelPlanEntry, paths: CampaignPaths, *, runtime_mode: str | None = None
) -> Eligibility:
    """May this model start a Full Run? (ARENA_CONTRACT section 5.)

    Two independent gates. The canary must have passed -- masterplan section 17
    exists precisely so a broken runtime is discovered on 15 pages instead of
    5,132. And the runtime must be a baked image, unless a founder waiver
    receipt exists on disk saying otherwise; bootstrap is a canary path
    (section 15.1: do not install a runtime during a Full Run).

    ``runtime_mode`` is the mode the run will actually use. D74: without it
    the gate judged the most permissive mode the runtime *allows*, so a
    model allowed ``["baked", "bootstrap"]`` with no baked image at all was
    called eligible as "baked" and the waiver rule never fired. The callers
    that know the mode pass it; a mode the runtime forbids is refused.
    """

    if runtime_mode is None:
        runtime_mode = "baked" if "baked" in entry.runtime_mode_allowed else "bootstrap"
    elif runtime_mode not in entry.runtime_mode_allowed:
        return Eligibility(
            allowed=False,
            reason=(
                f"runtime_mode {runtime_mode!r} is not allowed by runtimes/"
                f"{entry.model_key}/runtime.json ({list(entry.runtime_mode_allowed)}; D25)"
            ),
            runtime_mode=runtime_mode,
        )
    if entry.canary_status != "PASS":
        return Eligibility(
            allowed=False,
            reason=(
                f"canary_status is {entry.canary_status}; a Full Run requires PASS "
                "(masterplan section 17)"
            ),
            runtime_mode=runtime_mode,
        )
    if not entry.full_run_eligible:
        return Eligibility(
            allowed=False,
            reason="registry says full_run_eligible is false",
            runtime_mode=runtime_mode,
        )
    if runtime_mode == "baked":
        return Eligibility(
            allowed=True,
            reason="canary PASS and a baked runtime image",
            runtime_mode="baked",
        )
    waiver = paths.bootstrap_waiver(entry.model_key)
    if waiver.is_file():
        document = read_json(waiver)
        if isinstance(document, Mapping) and document.get("model_key") == entry.model_key:
            return Eligibility(
                allowed=True,
                reason=f"founder waiver on file permits a bootstrap Full Run ({waiver.name})",
                runtime_mode="bootstrap",
                waiver_path=waiver,
            )
        return Eligibility(
            allowed=False,
            reason=f"{waiver.name} does not name model_key {entry.model_key!r}",
            runtime_mode="bootstrap",
            waiver_path=waiver,
        )
    return Eligibility(
        allowed=False,
        reason=(
            "runtime_mode is bootstrap and no founder waiver receipt exists at "
            f"receipts/waivers/{waiver.name} (masterplan section 15.1)"
        ),
        runtime_mode="bootstrap",
    )


# --------------------------------------------------------------- readiness


def _line_text(entry: Mapping[str, object]) -> str:
    value = entry.get("line")
    return value if isinstance(value, str) else ""


def _safe_error_text(exc: BaseException) -> str:
    """An exception rendered for an operator line, or its type alone.

    The provider's own errors are written to withhold bodies, but this text
    reaches the console and the receipt, so anything the secret guard objects
    to is reduced to the exception class rather than trusted.
    """

    text = f"{type(exc).__name__}: {exc}"
    try:
        assert_secret_free(text, context="log fetch error")
    except SecretLeak:
        return type(exc).__name__
    return text


def scrub_log_lines(
    lines: Sequence[Mapping[str, object]],
) -> tuple[tuple[dict[str, object], ...], int]:
    """Drop the log lines that must not be persisted; keep the rest.

    Returns the kept lines and how many were dropped. Dropping the offending
    *lines* rather than the whole tail is deliberate: a bootstrap log is the
    only evidence the next attempt has, and losing two hundred lines because
    one of them echoed a presigned URL costs more than it protects.
    """

    kept: list[dict[str, object]] = []
    dropped = 0
    for entry in lines:
        record = {str(key): value for key, value in entry.items()}
        text = _line_text(record)
        if any(marker in text for marker in LOG_SCRUB_MARKERS):
            dropped += 1
            continue
        try:
            assert_secret_free(record, context="container log line")
        except SecretLeak:
            dropped += 1
            continue
        kept.append(record)
    return tuple(kept), dropped


def scrub_ready_body(
    payload: Mapping[str, object],
) -> tuple[dict[str, object], int]:
    """The ready body reduced to what is safe to persist, and what was dropped.

    ``/v1/ready`` carries ``last_error``, and a worker that died while warming
    puts the reason for its death there. That text is the runtime's own, so it
    goes through the guard the container log tail uses rather than being
    trusted: an offending *field* is dropped, the rest of the body kept.
    """

    kept: dict[str, object] = {}
    dropped = 0
    for key, value in payload.items():
        name = str(key)
        if isinstance(value, str) and any(
            marker in value for marker in LOG_SCRUB_MARKERS
        ):
            dropped += 1
            continue
        try:
            assert_secret_free({name: value}, context="ready response field")
        except SecretLeak:
            dropped += 1
            continue
        kept[name] = value
    return kept, dropped


class _LogWatch:
    """Reads the container log tail on a cadence and judges what it says.

    Three things come out of it: a verdict (crash loop or fatal marker), the
    scrubbed tail to attach to the receipt, and the last ``[arena]`` milestone
    so a 45-minute wait can report progress instead of silence.
    """

    __slots__ = (
        "_seen",
        "fetch_error",
        "milestone",
        "note",
        "restarts",
        "signature",
        "tail",
        "verdict_class",
    )

    def __init__(self) -> None:
        self.tail: tuple[dict[str, object], ...] = ()
        self.note: str | None = None
        self.milestone: str | None = None
        self.signature: str | None = None
        self.verdict_class: str | None = None
        # Why the last read produced nothing, when it produced nothing. A read
        # that failed and a runtime that has printed nothing look identical
        # from the heartbeat unless this is kept apart -- and the GLM-OCR pod
        # spent 45 min reporting the second while doing the first.
        self.fetch_error: str | None = None
        self.restarts = 0
        # Restart markers are counted across reads, deduplicated by their own
        # timestamp and text: a 200-line tail can scroll past the first
        # ``start container for`` long before the second one appears.
        self._seen: set[tuple[str, str]] = set()

    def refresh(self, reader: Callable[[], Sequence[Mapping[str, object]]]) -> None:
        try:
            lines = reader()
        except Exception as exc:  # the provider is diagnostics, never the verdict
            self.fetch_error = _safe_error_text(exc)
            self.note = f"log fetch failed: {self.fetch_error}"
            return
        self.fetch_error = None
        if not isinstance(lines, (tuple, list)) or not lines:
            self.note = "the provider returned no log lines"
            return
        raw = [entry for entry in lines if isinstance(entry, Mapping)]
        # The signatures are matched on the raw text and the *scrubbed* tail is
        # what gets written: a fatal line that also carried a token would
        # otherwise be dropped before it could be recognised.
        for entry in raw:
            text = _line_text(entry)
            if RESTART_MARKER in text:
                key = (str(entry.get("ts") or ""), text)
                if key not in self._seen:
                    self._seen.add(key)
                    self.restarts += 1
            if text.lstrip().startswith(ARENA_LOG_PREFIX):
                self.milestone = text.strip()
        kept, dropped = scrub_log_lines(raw[-LOG_TAIL_LINES:])
        self.tail = kept
        self.note = f"{len(kept)} line(s) from the provider log endpoint"
        if dropped:
            self.note += f"; {dropped} line(s) withheld by the secret guard"
        for entry in raw:
            text = _line_text(entry)
            for marker, error_class in FATAL_LOG_SIGNATURES:
                if marker in text:
                    self.signature = marker
                    self.verdict_class = error_class
                    return
        if self.restarts >= RESTARTS_BEFORE_CRASH_LOOP:
            self.signature = (
                f"{self.restarts} x {RESTART_MARKER!r} (the container restarted)"
            )
            self.verdict_class = "MODEL_LOAD"

    @property
    def condemned(self) -> bool:
        return self.verdict_class is not None

    @property
    def status_note(self) -> str:
        """One phrase for the heartbeat: progress, silence, or a failed read."""

        if self.fetch_error is not None:
            return f"log fetch failed: {self.fetch_error}"
        if self.milestone is not None:
            return self.milestone
        return "no [arena] milestone in the container log yet"


def poll_until_ready(
    worker: WorkerPort,
    *,
    max_attempts: int | None = 120,
    poll_seconds: float = 10.0,
    deadline_seconds: float | None = None,
    sleep: Callable[[float], None] | None = None,
    now: Callable[[], datetime] | None = None,
    pod_status: Callable[[], str | None] | None = None,
    note: Callable[[str], None] | None = None,
    log_tail: Callable[[], Sequence[Mapping[str, object]]] | None = None,
    log_every_polls: int | None = None,
    progress: Callable[[str], None] | None = None,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
) -> tuple[str, tuple[str, ...]]:
    """Two-stage readiness (masterplan section 15.3, contract section 4).

    Returns the final stage and the stage sequence observed. The controller
    sends ``/v1/run`` only after ``READY`` -- a pod reporting RUNNING is not a
    worker that can do work.

    **This is a poll, not a single probe.** A bootstrap pod pulls a multi-GB
    image, fetches a bundle, installs a runtime and downloads weights before
    anything binds port 8000, and for that whole window the RunPod proxy
    answers 404, 502, 503 or nothing at all. The first live run aborted seconds
    after creation on exactly that 404. So every non-200 and every transport
    failure is "not ready yet" and the deadline -- not the first error -- is
    what gives up. Four answers end the wait early instead:

    * a 200 whose ``stage`` is ``READY`` (the only success);
    * a 200 whose ``stage`` is terminal (CRASHED / OOM / QUARANTINED /
      TERMINATED) -- the worker itself says it is finished;
    * HTTP 401 or 403 -- the bearer is wrong and waiting cannot fix it;
    * the provider reporting the pod EXITED / FAILED / TERMINATED.

    Two more end it when the caller supplies the means to see them, because
    the 2026-09-03 GLM-OCR pod showed that ``/v1/ready`` answering 404 and the
    provider saying RUNNING is exactly what a crash loop looks like from
    outside:

    * ``log_tail`` -- read every ``log_every_polls`` polls (by default about
      once every two minutes) and matched against
      :data:`FATAL_LOG_SIGNATURES` and the container-restart marker. A model
      server that exited, a traceback, or two container starts ends the wait
      with the section 15.9 class on the error rather than at the deadline;
    * ``pod_status`` returning :data:`POD_MISSING` twice running -- the pod was
      deleted out from under the driver, and the proxy will answer 404 until
      the deadline if nobody says otherwise.

    ``progress`` is the operator's view of a wait that can last 45 minutes: one
    line per distinct answer, plus a heartbeat every ``heartbeat_seconds``
    carrying the elapsed time and the last ``[arena]`` milestone from the log.
    """

    if max_attempts is None and deadline_seconds is None:
        raise RunError(
            "a readiness poll needs a bound: pass max_attempts, deadline_seconds or both. "
            "Waiting forever on a GPU that is billing is not an option this loop offers."
        )
    pause = sleep or _default_sleep
    clock = now or (lambda: datetime.now(tz=UTC))
    started = clock()
    observed: list[str] = []
    last_status: str | None = None
    last_ready_body: dict[str, object] | None = None
    noted_status: str | None = None
    polls = 0
    missing_polls = 0
    watch = _LogWatch()
    # A cadence in polls, derived from the interval so the two-minute target
    # holds whether the caller polls every 10 s or every 60 s.
    every = (
        max(1, round(DEFAULT_LOG_INTERVAL_SECONDS / poll_seconds))
        if log_every_polls is None and poll_seconds > 0
        else max(1, log_every_polls or 1)
    )
    last_heartbeat = 0.0

    def elapsed() -> float:
        return max(0.0, (clock() - started).total_seconds())

    def fail(message: str, **extra: object) -> ReadinessError:
        return ReadinessError(
            message,
            observed=observed,
            last_status=last_status,
            elapsed_seconds=elapsed(),
            polls=polls,
            log_tail=watch.tail,
            log_note=watch.note,
            last_ready_response=last_ready_body,
            **extra,  # type: ignore[arg-type]
        )

    while True:
        polls += 1
        provider = None if pod_status is None else pod_status()
        if provider == POD_MISSING:
            missing_polls += 1
            if missing_polls >= MISSING_POLLS_BEFORE_GIVING_UP:
                raise fail(
                    f"pod gone: the provider reports no such pod on {missing_polls} "
                    f"consecutive reads after {elapsed() / 60:.1f} min. It was deleted "
                    "outside this driver; waiting for the proxy to answer would burn the "
                    "rest of the deadline for nothing",
                    provider_status=POD_MISSING,
                    signature="pod gone",
                )
        elif provider is not None:
            missing_polls = 0
        if provider is not None and provider.upper() in DEAD_POD_STATUSES:
            raise fail(
                f"the provider reports the pod as {provider} before the worker was ever "
                f"READY; last worker answer was {last_status or 'none'} after "
                f"{elapsed() / 60:.1f} min",
                provider_status=provider,
            )
        if log_tail is not None and (polls == 1 or polls % every == 0):
            watch.refresh(log_tail)
            if watch.condemned:
                raise fail(
                    f"the container log says the runtime will not come up: "
                    f"{watch.signature} (after {elapsed() / 60:.1f} min, {polls} poll(s)). "
                    f"Section 15.9 classes this {watch.verdict_class}, which retries zero "
                    "times; the pod is given back rather than waited out",
                    provider_status=provider,
                    error_class=watch.verdict_class,
                    signature=watch.signature,
                )
        try:
            payload = worker.ready()
        except WorkerHTTPError as exc:
            if exc.status_code in FATAL_READY_STATUSES:
                last_status = f"HTTP {exc.status_code}"
                raise fail(
                    f"the worker refused the campaign bearer (HTTP {exc.status_code}); "
                    "no amount of waiting changes that",
                    provider_status=provider,
                    error_class="AUTH",
                ) from None
            last_status = f"HTTP {exc.status_code}"
        except WorkerProtocolError as exc:
            # A 200 the contract cannot parse. The proxy serves its own error
            # pages with a 200 while the pod is still coming up, so this is
            # treated as "not ready yet" -- and named in the give-up reason so
            # a genuinely malformed worker is not mistaken for a slow one.
            last_status = f"unparseable answer ({type(exc).__name__})"
        except WorkerError as exc:
            last_status = f"no answer ({type(exc).__name__})"
        else:
            stage = str(payload.get("stage", ""))
            last_status = f"HTTP 200 stage={stage}"
            body, withheld = scrub_ready_body(payload)
            if withheld:
                body["_withheld_field_count"] = withheld
            last_ready_body = body
            if not observed or observed[-1] != stage:
                observed.append(stage)
            if stage == "READY":
                return stage, tuple(observed)
            if stage in TERMINAL_WORKER_STAGES:
                raise fail(
                    f"worker reached terminal stage {stage} while warming; "
                    f"observed {' -> '.join(observed) or 'nothing'}",
                    provider_status=provider,
                )
        spent = elapsed()
        if last_status != noted_status:
            # One line per *distinct* answer. A 45-minute bootstrap is well
            # over a hundred polls, and a receipt carrying "HTTP 404" a hundred
            # times says nothing the first one did not.
            noted_status = last_status
            line = f"readiness after {spent / 60:.1f} min (poll {polls}): {last_status}"
            if note is not None:
                note(line)
            if progress is not None:
                progress(line)
        if (
            progress is not None
            and heartbeat_seconds > 0
            and spent - last_heartbeat >= heartbeat_seconds
        ):
            # The operator is watching a billed GPU do nothing visible. Say so
            # on a fixed cadence, with whatever the runtime last printed.
            last_heartbeat = spent
            progress(
                f"readiness still waiting: {spent / 60:.1f} min elapsed, {polls} poll(s), "
                f"last answer {last_status}; {watch.status_note}"
            )
        if deadline_seconds is not None and spent >= deadline_seconds:
            raise fail(
                f"worker never reached READY within {deadline_seconds / 60:.0f} min "
                f"({polls} poll(s), {spent / 60:.1f} min elapsed); last answer was "
                f"{last_status}; observed stages {' -> '.join(observed) or 'none'}",
                provider_status=provider,
            )
        if max_attempts is not None and polls >= max_attempts:
            raise fail(
                f"worker never reached READY in {max_attempts} polls; last answer was "
                f"{last_status}; observed stages {' -> '.join(observed) or 'none'}",
                provider_status=provider,
            )
        pause(poll_seconds)


# -------------------------------------------------------------- checkpoint


@dataclass(frozen=True, slots=True)
class PageOutcome:
    inference_job_id: str
    case_key: str
    status: str
    error_class: str | None
    error_message: str | None
    raw_output_sha256: str | None
    receipt_sha256: str | None
    receipt_path: Path | None
    total_ms: int
    retried: bool = False
    detail: Mapping[str, object] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status == "SUCCESS"


def build_page_receipt(
    *,
    job: JobRecord,
    sample: SourceSample,
    entry: ModelPlanEntry,
    response: RunResponse,
    worker_id: str,
    pod_id: str | None,
    gpu_type: str | None,
    queued_at: str,
    worker_ready_at: str | None,
    canonical_output_path: str | None,
    raw_output_path: str | None,
    wasted_gpu_seconds: float,
    recovery_job_id: str | None = None,
    campaign_id: str = CAMPAIGN_ID,
) -> dict[str, object]:
    """Masterplan section 11 plus ARENA_CONTRACT sections 3.1 and 11 D3.

    ``semantic_error_class`` is copied from the worker response, never derived
    here: the adapter knows whether an output was empty, truncated, repetitive
    or malformed, and the controller inventing that classification from an
    output length would be exactly the fabricated data the constitution bans.
    """

    if job.job_kind == "recovery" and recovery_job_id is None:
        # A recovery page whose receipt cannot name its recovery job is
        # untraceable; refuse rather than write a null into the field.
        raise RunError(
            f"page {job.case_key} is a recovery job but no recovery_job_id was supplied"
        )
    if job.job_kind != "recovery" and recovery_job_id is not None:
        raise RunError(
            f"page {job.case_key} carries a recovery_job_id but its job_kind is {job.job_kind!r}"
        )
    # ARENA_CONTRACT 11.5 D15: the runtime the worker says it is running must
    # be the runtime the ledger says we provisioned. If they differ, every
    # number in this receipt is attributed to a runtime nobody authorized --
    # and a canary that "passed" on the wrong image is worse than no canary.
    if _normalise_digest(response.runtime_image_digest) != _normalise_digest(
        entry.runtime_image_digest
    ):
        raise RunError(
            f"page {job.case_key}: the worker reports runtime_image_digest "
            f"{response.runtime_image_digest!r} but the pod was provisioned with "
            f"{entry.runtime_image_digest!r} (ARENA_CONTRACT 11.5 D15). Refusing to write a "
            "receipt that attributes this output to the wrong runtime."
        )
    timings = dict(response.timings_ms)
    return {
        "schema": "tavonel.arena.page_receipt.v1",
        "campaign_id": campaign_id,
        "inference_job_id": job.inference_job_id,
        "benchmark": job.benchmark,
        "sample_id": job.sample_id,
        "case_key": job.case_key,
        "source_sha256": sample.source_sha256,
        "model_key": job.model_key,
        "model_revision": response.model_revision,
        "runtime_image_digest": response.runtime_image_digest,
        "runtime_mode": response.runtime_mode,
        "gpu_type": gpu_type,
        "gpu_id": None,
        "pod_id": pod_id,
        "worker_id": worker_id,
        "shard_id": job.shard_id,
        "job_kind": job.job_kind,
        "prompt_id": entry.prompt_id,
        "prompt_sha256": entry.prompt_sha256,
        "inference_config_sha256": entry.inference_config_sha256,
        "image_width": sample.width,
        "image_height": sample.height,
        "queued_at": queued_at,
        "worker_ready_at": worker_ready_at,
        "started_at": response.started_at,
        "first_token_at": response.first_token_at,
        "finished_at": response.finished_at,
        "queue_ms": _elapsed_ms(queued_at, response.started_at),
        "load_ms": timings.get("load_ms", 0),
        "preprocess_ms": timings.get("preprocess_ms", 0),
        "inference_ms": timings.get("inference_ms", 0),
        "postprocess_ms": timings.get("postprocess_ms", 0),
        "total_ms": timings.get("total_ms", 0),
        "peak_vram_mb": response.peak_vram_mb,
        "baseline_vram_mb": getattr(response, "baseline_vram_mb", None),
        "vram_total_mb": getattr(response, "vram_total_mb", None),
        "vram_measurement_source": getattr(response, "vram_measurement_source", None),
        "input_bytes": response.input_bytes,
        "output_bytes": response.output_bytes,
        "output_chars": response.output_chars,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "attempt": job.attempt + 1,
        "retry_count": job.retry_count,
        "retry_reason": job.error_class,
        "status": response.status,
        "error_class": response.error_class,
        "semantic_error_class": getattr(response, "semantic_error_class", None),
        "recovery_job_id": recovery_job_id,
        "error_message": (response.error_message or None)
        if response.error_message is None
        else response.error_message[:2000],
        "raw_output_path": raw_output_path,
        "raw_output_sha256": response.raw_output_sha256,
        "canonical_output_path": canonical_output_path,
        "canonical_output_sha256": response.canonical_output_sha256,
        "wasted_gpu_seconds": round(wasted_gpu_seconds, 3),
    }


def checkpoint_page(
    *,
    paths: CampaignPaths,
    model_key: str,
    case_key: str,
    response: RunResponse,
    receipt: Mapping[str, object],
) -> tuple[str, str, Path]:
    """Write raw, canonical and receipt atomically. Returns the three hashes.

    Nothing marks the job SUCCESS here. The caller does that only after this
    returns, so a crash between the two leaves a re-runnable job rather than a
    SUCCESS row pointing at a half-written file.
    """

    raw_path = paths.raw_dir(model_key) / f"{case_key}.raw.txt"
    raw_bytes = response.raw_text.encode("utf-8")
    raw_sha = atomic_write_bytes(raw_path, raw_bytes)
    if raw_sha != response.raw_output_sha256:
        raise RunError(
            f"raw bytes for {case_key} hash to {raw_sha}, not the "
            f"{response.raw_output_sha256} the worker declared"
        )

    if response.native_json is not None:
        import json

        native_path = paths.raw_dir(model_key) / f"{case_key}.native.json"
        atomic_write_bytes(
            native_path,
            json.dumps(dict(response.native_json), sort_keys=True, ensure_ascii=False).encode(
                "utf-8"
            ),
        )

    canonical_path = paths.canonical_dir(model_key) / f"{case_key}.md"
    canonical_sha = atomic_write_bytes(
        canonical_path, response.canonical_markdown.encode("utf-8")
    )
    if canonical_sha != response.canonical_output_sha256:
        raise RunError(
            f"canonical bytes for {case_key} hash to {canonical_sha}, not the "
            f"{response.canonical_output_sha256} the worker declared"
        )

    receipt_path = paths.receipt_dir(model_key) / f"{case_key}.json"
    receipt_sha = write_json_atomic(receipt_path, dict(receipt), context="page receipt")
    return raw_sha, receipt_sha, receipt_path


# ---------------------------------------------------------------- dispatch


def dispatch_page(
    *,
    worker: WorkerPort,
    worker_id: str,
    pod_id: str | None,
    gpu_type: str | None,
    job: JobRecord,
    sample: SourceSample,
    entry: ModelPlanEntry,
    paths: CampaignPaths,
    queue: CampaignQueue,
    events: EventLog,
    image_bytes: bytes,
    worker_ready_at: str | None = None,
    timeout_seconds: int | None = None,
    recovery_job_id: str | None = None,
) -> PageOutcome:
    """Run exactly one page and checkpoint it. Never raises on model failure.

    Provider/worker transport failures and checksum mismatches are classified
    into the section 16 taxonomy and recorded; they do not stop the loop, and
    they never produce a SUCCESS.
    """

    queued_at = job.queued_at or utc_now_iso()
    observed = sha256_bytes(image_bytes)
    if observed != sample.source_sha256:
        # The controller checks too: an inference plane that sends the wrong
        # bytes would produce an output attributed to the wrong page.
        return _fail(
            queue=queue,
            events=events,
            job=job,
            error_class="CHECKSUM",
            message=(
                f"page bytes for {job.case_key} hash to {observed}, "
                f"manifest says {sample.source_sha256}"
            ),
            quarantine=True,
        )

    queue.mark_running(job.inference_job_id, worker_id)
    request = RunRequest(
        campaign_id=CAMPAIGN_ID,
        inference_job_id=job.inference_job_id,
        sample_id=job.sample_id,
        case_key=job.case_key,
        benchmark=job.benchmark,
        source_sha256=sample.source_sha256,
        image_bytes=image_bytes,
        width=sample.width or 0,
        height=sample.height or 0,
        prompt_id=entry.prompt_id,
        prompt_sha256=entry.prompt_sha256,
        inference_config_sha256=entry.inference_config_sha256,
        job_kind=job.job_kind,
        timeout_seconds=timeout_seconds,
        metadata=sample.metadata(),
    )

    try:
        response = worker.run(request)
    except WorkerChecksumError as exc:
        return _fail(
            queue=queue,
            events=events,
            job=job,
            error_class="CHECKSUM",
            message=str(exc),
            quarantine=False,
        )
    except WorkerProtocolError as exc:
        return _fail(
            queue=queue,
            events=events,
            job=job,
            error_class="OUTPUT_MALFORMED",
            message=str(exc),
            quarantine=False,
        )
    except WorkerError as exc:
        # A worker that answered and refused is not a network fault. When the
        # 422 body named the check that failed, the client has already mapped
        # it to a section 16 class (worker_client.REJECTION_ERROR_CLASSES) and
        # a deterministic refusal gets zero retries instead of three. Anything
        # that did not answer -- or answered without a code -- stays
        # INFRA_NETWORK, which is what it is.
        return _fail(
            queue=queue,
            events=events,
            job=job,
            error_class=getattr(exc, "error_class", None) or "INFRA_NETWORK",
            message=str(exc),
            quarantine=False,
        )

    total_ms = int(dict(response.timings_ms).get("total_ms", 0))
    if not response.succeeded:
        return _fail(
            queue=queue,
            events=events,
            job=job,
            error_class=response.error_class or "UNKNOWN",
            message=response.error_message,
            quarantine=False,
            total_ms=total_ms,
        )

    receipt = build_page_receipt(
        job=job,
        sample=sample,
        entry=entry,
        response=response,
        worker_id=worker_id,
        pod_id=pod_id,
        gpu_type=gpu_type,
        queued_at=queued_at,
        worker_ready_at=worker_ready_at,
        raw_output_path=f"runs/{job.model_key}/raw/{job.case_key}.raw.txt",
        canonical_output_path=f"runs/{job.model_key}/canonical/{job.case_key}.md",
        wasted_gpu_seconds=0.0,
        recovery_job_id=recovery_job_id,
    )
    raw_sha, receipt_sha, receipt_path = checkpoint_page(
        paths=paths,
        model_key=job.model_key,
        case_key=job.case_key,
        response=response,
        receipt=receipt,
    )
    queue.mark_success(
        job.inference_job_id,
        raw_output_sha256=raw_sha,
        receipt_sha256=receipt_sha,
        worker_id=worker_id,
    )
    events.append(
        entity_kind="job",
        entity_id=job.inference_job_id,
        from_state="RUNNING",
        to_state="SUCCESS",
        reason="page checkpointed",
        detail={"case_key": job.case_key, "worker_id": worker_id, "total_ms": total_ms},
    )
    return PageOutcome(
        inference_job_id=job.inference_job_id,
        case_key=job.case_key,
        status="SUCCESS",
        error_class=None,
        error_message=None,
        raw_output_sha256=raw_sha,
        receipt_sha256=receipt_sha,
        receipt_path=receipt_path,
        total_ms=total_ms,
    )


def _fail(
    *,
    queue: CampaignQueue,
    events: EventLog,
    job: JobRecord,
    error_class: str,
    message: str | None,
    quarantine: bool,
    total_ms: int = 0,
) -> PageOutcome:
    decision = retry_policy.decide(error_class, retry_count=job.retry_count)
    should_quarantine = quarantine or (not decision.retry and decision.rule.quarantines)
    queue.mark_failed(
        job.inference_job_id,
        error_class=error_class,
        error_message=message,
        quarantine=should_quarantine,
        increment_retry=decision.retry,
    )
    events.append(
        entity_kind="job",
        entity_id=job.inference_job_id,
        from_state="RUNNING",
        to_state="QUARANTINED" if should_quarantine else "FAILED",
        reason=decision.reason,
        detail={
            "case_key": job.case_key,
            "error_class": error_class,
            "retry": decision.retry,
            "action": decision.rule.action,
        },
    )
    if decision.retry:
        queue.requeue(job.inference_job_id, reason=decision.reason)
    return PageOutcome(
        inference_job_id=job.inference_job_id,
        case_key=job.case_key,
        status="QUARANTINED" if should_quarantine else "FAILED",
        error_class=error_class,
        error_message=message,
        raw_output_sha256=None,
        receipt_sha256=None,
        receipt_path=None,
        total_ms=total_ms,
        retried=decision.retry,
        detail={"action": decision.rule.action, "mp_row": decision.rule.mp_row},
    )


# ------------------------------------------------------------- error ledger


def record_error(
    path: Path,
    *,
    model_key: str,
    error_class: str,
    signature: str,
    runtime_image_digest: str | None,
    gpu_type: str | None,
    retryable: bool,
    wasted_gpu_seconds: float,
    root_cause: str | None = None,
    resolution: str | None = None,
    count: int = 1,
    first_seen: str | None = None,
) -> None:
    """Append one masterplan section 16 error record to failures/errors.jsonl."""

    now = utc_now_iso()
    write_jsonl_append(
        path,
        {
            "schema": "tavonel.arena.error_record.v1",
            "campaign_id": CAMPAIGN_ID,
            "first_seen": first_seen or now,
            "last_seen": now,
            "count": count,
            "model_key": model_key,
            "error_class": error_class,
            "error_signature": signature,
            "runtime_image_digest": runtime_image_digest,
            "gpu_type": gpu_type,
            "retryable": retryable,
            "root_cause": root_cause,
            "resolution": resolution,
            "wasted_gpu_seconds": round(wasted_gpu_seconds, 3),
        },
        context="error record",
    )


# ---------------------------------------------------------------- summary


def write_run_summary(
    paths: CampaignPaths,
    *,
    model_key: str,
    queue: CampaignQueue,
    entry: ModelPlanEntry,
    eligibility_result: Eligibility,
    budget: BudgetAssessment | None,
    breaker: CircuitBreaker | None,
    started_at: str,
) -> Path:
    counts = queue.counts_by_state(model_key=model_key)
    trip = None if breaker is None else breaker.tripped
    summary = {
        "schema": "tavonel.arena.run_summary.v1",
        "campaign_id": CAMPAIGN_ID,
        "model_key": model_key,
        "started_at": started_at,
        "finished_at": utc_now_iso(),
        "model_revision": entry.model_revision,
        "runtime_image_digest": entry.runtime_image_digest,
        "runtime_mode": eligibility_result.runtime_mode,
        "eligibility": eligibility_result.to_dict(),
        "job_counts": counts,
        "budget": None if budget is None else budget.to_dict(),
        "circuit_breaker": (
            None
            if trip is None
            else {"rule": trip.rule, "reason": trip.reason, "detail": dict(trip.detail)}
        ),
        "retry_policy_source": retry_policy.policy_source(),
    }
    path = paths.run_summary(model_key)
    write_json_atomic(path, summary, context="run summary")
    return path


def apply_budget(
    assessment: BudgetAssessment,
    *,
    queue: CampaignQueue,
    events: EventLog,
    workers: Sequence[str],
    drain: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Section 15.13: soft cap stops growth, hard cap pauses and drains.

    In-flight RUNNING jobs are never touched. ``pause_pending`` moves only
    dispatchable jobs, so the page a worker is on finishes and checkpoints.
    """

    applied: dict[str, object] = {"state": assessment.state, "paused_jobs": 0, "drained": []}
    if assessment.state == "NORMAL":
        return applied
    queue.set_flag("budget_state", assessment.state)
    if assessment.pause_queue:
        paused = queue.pause_pending()
        applied["paused_jobs"] = paused
        events.append(
            entity_kind="campaign",
            entity_id=CAMPAIGN_ID,
            to_state="BUDGET_PAUSED",
            reason=assessment.reason,
            detail={"paused_jobs": paused, **assessment.to_dict()},
        )
    if assessment.drain_workers and drain is not None:
        drained: list[str] = []
        for worker_id in workers:
            drain(worker_id)
            drained.append(worker_id)
            events.append(
                entity_kind="worker",
                entity_id=worker_id,
                to_state="DRAINING",
                reason="budget hard cap: drain to the next checkpoint, do not kill a page",
            )
        applied["drained"] = drained
    return applied


def _normalise_digest(value: str | None) -> str | None:
    """One spelling for one digest (ARENA_CONTRACT 11.6 D35).

    ``bootstrap:sha256:<hex>`` and ``bootstrap:<hex>`` name the same bundle;
    comparing the two as raw strings would fail a pod that is perfectly
    correct, so the ``sha256:`` marker is dropped before comparing.
    """

    if value is None:
        return None
    return value.replace("sha256:", "").strip().lower()


def _elapsed_ms(start: str | None, end: str | None) -> int:
    first = _parse(start)
    second = _parse(end)
    if first is None or second is None:
        return 0
    return max(0, int((second - first).total_seconds() * 1000))


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _default_sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)
