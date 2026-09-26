"""On-pod worker HTTP server (ARENA_CONTRACT section 4).

One process per pod. It owns the model adapter, the readiness state machine
(masterplan section 34), the per-page checkpoint (15.7), the atomic write
(15.8) and the heartbeat (15.4). It holds no campaign policy: retry, hedging
and scheduling belong to the controller.

Rules this file exists to enforce:

* A page is never accepted before ``READY`` and never after ``STALLED`` or
  ``DRAINING`` — the controller gets 409, not a silently queued job.
* Decoded image bytes must hash to ``source_sha256`` or the page fails
  ``CHECKSUM``. Hostile or corrupted input never reaches the model.
* The result file is durable *before* the HTTP response is written, so a pod
  that dies mid-response has still checkpointed the page.
* A repeated ``inference_job_id`` replays the persisted result. Paid inference
  happens at most once per job id.
* Every error message that leaves this process is redacted and bounded.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import errno
import hmac
import json
import logging
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final, TypeVar
from urllib.parse import urlsplit

from arena.constants import BENCHMARK_KEYS, ERROR_CLASSES, WORKER_STATES
from arena.worker import provenance as provenance_module
from arena.worker.adapter_api import (
    AdapterConfig,
    AdapterError,
    ArenaModelAdapter,
    CanonicalOutput,
    PageInput,
    RawOutput,
)
from arena.worker.compat import UTC
from arena.worker.config import (
    ResolvedPrompt,
    RuntimeConfig,
    WorkerEnv,
    load_runtime_config,
    resolve_prompt,
)
from arena.worker.heartbeat import HeartbeatWriter
from arena.worker.loader import Canonicalize, load_adapter, load_canonicalizer
from arena.worker.synthetic import synthetic_page_png
from arena.worker.util import (
    atomic_write_bytes,
    atomic_write_json,
    jsonable,
    safe_error,
    sha256_label,
    utcnow,
)
from arena.worker.vram import (
    MEASUREMENT_SOURCE_ADAPTER,
    MEASUREMENT_SOURCE_NVIDIA_SMI,
    VramSampler,
    VramWindow,
)

LOG: Final = logging.getLogger("arena.worker")

JOB_ID_RE: Final = re.compile(r"[0-9a-f]{64}")
CASE_KEY_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,119}")
SHA_LABEL_RE: Final = re.compile(r"sha256:[0-9a-f]{64}")
JOB_KINDS: Final = ("inference", "canary", "recovery")

# Integration-pass decision D4 (ARENA_CONTRACT 11.1): the heartbeat ``state``
# takes its values from ``arena.constants.WORKER_STATES`` and nothing else. The
# earlier four-value coarse label (LOADING/READY/BUSY/DRAINING) collapsed
# IMAGE_READY, MODEL_LOADING and WARMING into one bucket and had no value at
# all for CRASHED, STALLED or OOM, so a controller could not tell a pod that is
# still pulling weights from one that died. ``stage`` stays as the same value
# for clients written against ARENA_CONTRACT section 4.
WORKER_STATE_VALUES: Final = frozenset(WORKER_STATES)

# Semantic verdicts an adapter may attach to an otherwise successful page
# (decision D3). These are *not* operational failures: MP section 41 keeps
# ``status`` at SUCCESS when a raw output exists, and an empty output is
# SUCCESS + OUTPUT_EMPTY.
SEMANTIC_ERROR_CLASSES: Final = (
    "OUTPUT_EMPTY",
    "OUTPUT_TRUNCATED",
    "OUTPUT_REPETITION",
    "OUTPUT_MALFORMED",
)
SEMANTIC_WARNING_PREFIX: Final = "arena.semantic_error_class="

ACCEPTING_STAGES: Final = frozenset({"READY", "BUSY"})
TERMINAL_STAGES: Final = frozenset({"CRASHED", "STALLED", "TERMINATED", "QUARANTINED"})
MAX_BODY_BYTES: Final = 64 * 1024 * 1024

# Decision D34 asks a ``toolkit`` adapter to compare the text it built with
# ``AdapterConfig.prompt_sha256``. ``adapter_api.py`` belongs to the
# orchestrator, so whether that field exists is read here rather than assumed:
# when it is present the worker fills it, when it is not the worker says so on
# /v1/ready's companion file instead of pretending the check happened.
ADAPTER_CONFIG_FIELDS: Final = frozenset(field.name for field in fields(AdapterConfig))
ADAPTER_CONFIG_ACCEPTS_PROMPT_SHA256: Final = "prompt_sha256" in ADAPTER_CONFIG_FIELDS

# Decision D20: the process exit code when the pod outlives
# ARENA_MAX_POD_AGE_HOURS. Non-zero on purpose -- a pod that ended because it
# ran out of lifetime did not finish its work, and the controller must be able
# to tell that from a clean drain.
MAX_POD_AGE_EXIT_CODE: Final = 75


def read_fatal_file(path: Path) -> dict[str, Any] | None:
    """The D47 sticky-failure file, or ``None`` when it does not exist.

    ``entrypoint.sh`` writes ``reason`` on its own line followed by the last
    200 lines of the model-server log when the model server dies or never
    becomes ready, then sleeps forever (D19/D47). The worker does not repeat
    that whole log into a schema field: only the first line (the reason) plus
    the file's size and mtime travel further, and the reason is passed through
    ``safe_error`` so nothing that looks like a credential leaks.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    reason = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            reason = handle.readline().rstrip("\r\n")
    except OSError:
        pass
    if not reason:
        reason = "(fatal file is empty)"
    mtime = (
        datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    return {
        "reason": safe_error(reason),
        "size_bytes": stat.st_size,
        "mtime": mtime,
    }


def is_connection_refused(exc: BaseException) -> bool:
    """Does this exception (or anything it wraps) mean "nothing is listening yet"?

    Decision D19: a runtime whose entrypoint starts a local model server answers
    connection-refused for as long as the weights take to load. Three shapes are
    recognised, in order of how much they prove:

    1. :class:`ConnectionRefusedError` -- what the stdlib raises,
    2. an :class:`OSError` carrying ``errno.ECONNREFUSED``,
    3. an exception whose text says "connection refused" -- the shape an HTTP
       client library uses when it wraps the socket error in its own class the
       worker cannot import (the pod is stdlib + pillow).

    Nothing else counts. A model that failed to load for a real reason must not
    be retried for twenty minutes.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ConnectionRefusedError):
            return True
        if isinstance(current, OSError) and current.errno == errno.ECONNREFUSED:
            return True
        if "connection refused" in str(current).lower():
            return True
        current = current.__cause__ or current.__context__
    return False


# PEP 695 ``def f[T]`` needs Python 3.12; the deepseek_ocr2 image runs 3.11
# (real canary 2026-09-03, pod rgbpf4s0oq2e15). Pod-side code stays 3.10-parsable.
_T = TypeVar("_T")


def retry_while_connection_refused(  # noqa: UP047 - pod images run Python 3.11
    call: Callable[[], _T],
    *,
    what: str,
    budget_seconds: float,
    poll_seconds: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> _T:
    """Run ``call``, retrying only while a local model server refuses connections.

    Bounded by ``budget_seconds`` (D19: at least 20 minutes for the 7B-class
    models). Every retry is logged, so a pod that spends its whole budget
    waiting says so in the pod log rather than looking idle. When the budget is
    gone the last refusal is re-raised as ``MODEL_LOAD`` -- the worker goes
    CRASHED, it does not keep the pod alive hoping.
    """
    deadline = clock() + budget_seconds
    attempt = 0
    while True:
        attempt += 1
        try:
            return call()
        except Exception as exc:
            if not is_connection_refused(exc):
                raise
            remaining = deadline - clock()
            if remaining <= 0:
                raise AdapterError(
                    "MODEL_LOAD",
                    f"{what}: the local model server was still refusing connections after "
                    f"{budget_seconds:.0f}s and {attempt} attempts "
                    f"(ARENA_MODEL_SERVER_WAIT_SECONDS)",
                ) from exc
            LOG.warning(
                "%s: model server refused the connection (attempt %d); "
                "retrying in %.1fs, %.0fs of the %.0fs budget left",
                what,
                attempt,
                min(poll_seconds, remaining),
                remaining,
                budget_seconds,
            )
            sleep(min(poll_seconds, remaining))


def _exit_process(code: int) -> None:  # pragma: no cover - exercised by monkeypatch
    """Leave the process now, from a daemon thread.

    ``sys.exit`` in a thread raises in that thread and the HTTP server keeps
    serving, which is the opposite of what D20 asks for. The streams are
    flushed first so the reason reaches the pod log.
    """
    for stream in (sys.stdout, sys.stderr):
        # A closed or broken pipe must not stop the exit; there is nowhere left
        # to log it either, which is exactly why nothing is logged here.
        with contextlib.suppress(Exception):
            stream.flush()
    logging.raiseExceptions = False
    os._exit(code)


class PodAgeWatchdog:
    """Decision D20: the pod's own lifetime fuse, beside the controller watchdog.

    The controller stops and deletes the pod at its deadline. This thread is
    what happens when the controller cannot -- it crashed, the network went, the
    driver was killed. At ``max_age_seconds`` it drains, gives pages already in
    flight ``drain_grace_seconds`` to land on disk, then exits non-zero with a
    message naming the fuse.

    The age is measured from worker start, which in bootstrap mode is *later*
    than pod start (the bundle download and the install came first). The fuse
    therefore errs towards firing late; the controller watchdog is the
    authoritative one.
    """

    def __init__(
        self,
        core: WorkerCore,
        *,
        max_age_seconds: float,
        drain_grace_seconds: float,
        poll_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        exit_code: int = MAX_POD_AGE_EXIT_CODE,
    ) -> None:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        self.core = core
        self.max_age_seconds = max_age_seconds
        self.drain_grace_seconds = drain_grace_seconds
        self.poll_seconds = poll_seconds
        self.exit_code = exit_code
        self._clock = clock
        self._sleep = sleep
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.fired = False

    def start(self) -> None:
        thread = threading.Thread(target=self.run, name="arena-pod-age", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        deadline = self._clock() + self.max_age_seconds
        while not self._stop.is_set():
            remaining = deadline - self._clock()
            if remaining <= 0:
                self.expire()
                return
            self._sleep(min(self.poll_seconds, remaining))

    def expire(self) -> None:
        """Drain, wait for in-flight pages, then leave with a non-zero code."""
        self.fired = True
        LOG.error(
            "pod age fuse: %0.2f h elapsed since worker start "
            "(ARENA_MAX_POD_AGE_HOURS); draining and exiting %d",
            self.max_age_seconds / 3600.0,
            self.exit_code,
        )
        try:
            self.core.drain()
        except Exception as exc:  # pragma: no cover - drain is a state flip
            LOG.warning("pod age fuse: drain failed: %s", safe_error(exc))
        grace_deadline = self._clock() + self.drain_grace_seconds
        while self.core.active_jobs > 0 and self._clock() < grace_deadline:
            self._sleep(min(1.0, self.poll_seconds))
        remaining_jobs = self.core.active_jobs
        if remaining_jobs:
            LOG.error(
                "pod age fuse: %d page(s) still running after a %.0fs drain grace; "
                "exiting anyway",
                remaining_jobs,
                self.drain_grace_seconds,
            )
        try:
            self.core.stop()
        except Exception as exc:  # pragma: no cover - teardown is best effort
            LOG.warning("pod age fuse: worker teardown failed: %s", safe_error(exc))
        _exit_process(self.exit_code)

# Exactly the RunResponse keys ARENA_CONTRACT section 4 names, plus the record
# "schema" tag section 3 requires. arena/core/schemas/worker-run-response.schema.json
# is additionalProperties:false, so this list is closed, not a minimum.
CONTRACT_RESULT_KEYS: Final = (
    "schema",
    "inference_job_id",
    "status",
    "error_class",
    "error_message",
    "worker_id",
    "model_key",
    "model_revision",
    "runtime_mode",
    "runtime_image_digest",
    "gpu_type",
    "pod_id",
    "started_at",
    "first_token_at",
    "finished_at",
    "timings_ms",
    "peak_vram_mb",
    # Whole-GPU VRAM context for peak_vram_mb. Without the source a reader
    # cannot tell an nvidia-smi device total from a per-process footprint, and
    # without baseline/total the controller has no headroom to compute.
    "baseline_vram_mb",
    "vram_total_mb",
    "vram_measurement_source",
    "input_bytes",
    "output_bytes",
    "output_chars",
    "input_tokens",
    "output_tokens",
    "raw_output",
    "canonical",
    "raw_output_sha256",
    "canonical_output_sha256",
    # D3: nullable, filled from RawOutput.semantic_error_class or the
    # "arena.semantic_error_class=" warning prefix.
    "semantic_error_class",
)


class RequestRejected(ValueError):
    """The request is not processable; nothing was run and nothing persisted."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class _InferenceTimeout(RuntimeError):
    """``adapter.infer`` exceeded the per-page timeout."""


@dataclass(frozen=True, slots=True)
class RunRequest:
    campaign_id: str
    inference_job_id: str
    sample_id: str
    case_key: str
    benchmark: str
    source_sha256: str
    image_b64: str
    width: int
    height: int
    prompt_id: str
    prompt_sha256: str
    inference_config_sha256: str
    job_kind: str
    metadata: Mapping[str, Any]
    timeout_seconds: float | None


def _require_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RequestRejected("INVALID_REQUEST", f"{key} must be a non-empty string")
    return value


def _require_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RequestRejected("INVALID_REQUEST", f"{key} must be a positive integer")
    return value


def parse_run_request(payload: object) -> RunRequest:
    """Validate the wire body. Raises :class:`RequestRejected` on anything odd."""
    if not isinstance(payload, dict):
        raise RequestRejected("INVALID_REQUEST", "body must be a JSON object")

    job_id = _require_str(payload, "inference_job_id")
    if not JOB_ID_RE.fullmatch(job_id):
        raise RequestRejected(
            "INVALID_REQUEST", "inference_job_id must be 64 lowercase hex characters"
        )
    case_key = _require_str(payload, "case_key")
    if not CASE_KEY_RE.fullmatch(case_key):
        raise RequestRejected(
            "INVALID_REQUEST",
            "case_key must be filesystem-safe: [A-Za-z0-9._-], 1-120 characters",
        )
    benchmark = _require_str(payload, "benchmark")
    if benchmark not in BENCHMARK_KEYS:
        raise RequestRejected("INVALID_REQUEST", f"benchmark must be one of {BENCHMARK_KEYS}")
    job_kind = str(payload.get("job_kind") or "inference")
    if job_kind not in JOB_KINDS:
        raise RequestRejected("INVALID_REQUEST", f"job_kind must be one of {JOB_KINDS}")

    source_sha256 = _require_str(payload, "source_sha256")
    if not SHA_LABEL_RE.fullmatch(source_sha256):
        raise RequestRejected("INVALID_REQUEST", "source_sha256 must be 'sha256:<64 hex>'")
    prompt_sha256 = _require_str(payload, "prompt_sha256")
    if not SHA_LABEL_RE.fullmatch(prompt_sha256):
        raise RequestRejected("INVALID_REQUEST", "prompt_sha256 must be 'sha256:<64 hex>'")
    config_sha = _require_str(payload, "inference_config_sha256")
    if not SHA_LABEL_RE.fullmatch(config_sha):
        raise RequestRejected(
            "INVALID_REQUEST", "inference_config_sha256 must be 'sha256:<64 hex>'"
        )

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise RequestRejected("INVALID_REQUEST", "metadata must be a JSON object")

    timeout_raw = payload.get("timeout_seconds")
    timeout: float | None
    if timeout_raw is None:
        timeout = None
    elif isinstance(timeout_raw, bool) or not isinstance(timeout_raw, int | float):
        raise RequestRejected("INVALID_REQUEST", "timeout_seconds must be a number")
    elif timeout_raw <= 0:
        raise RequestRejected("INVALID_REQUEST", "timeout_seconds must be > 0")
    else:
        timeout = float(timeout_raw)

    return RunRequest(
        campaign_id=_require_str(payload, "campaign_id"),
        inference_job_id=job_id,
        sample_id=_require_str(payload, "sample_id"),
        case_key=case_key,
        benchmark=benchmark,
        source_sha256=source_sha256,
        image_b64=_require_str(payload, "image_b64"),
        width=_require_int(payload, "width"),
        height=_require_int(payload, "height"),
        prompt_id=_require_str(payload, "prompt_id"),
        prompt_sha256=prompt_sha256,
        inference_config_sha256=config_sha,
        job_kind=job_kind,
        metadata=metadata,
        timeout_seconds=timeout,
    )


class WorkerCore:
    """Worker state, adapter lifecycle and the behaviour behind every endpoint."""

    def __init__(self, env: WorkerEnv) -> None:
        self.env = env
        self.started_at = utcnow()
        self.state_dir = env.state_dir
        self.inputs_dir = self.state_dir / "inputs"
        self.results_dir = self.state_dir / "results"
        self.synthetic_dir = self.state_dir / "synthetic"
        for directory in (self.inputs_dir, self.results_dir, self.synthetic_dir):
            directory.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._stage = "IMAGE_READY"
        self._last_error: str | None = None
        self._ready_at: str | None = None
        self._load_receipt: dict[str, Any] | None = None
        self._warmup_receipt: dict[str, Any] | None = None
        self._load_ms: int | None = None
        self._jobs_done = 0
        self._jobs_failed = 0
        self._current_job_id: str | None = None
        self._last_progress_at = self.started_at
        self._output_progress = 0
        self._active_jobs = 0

        self._runtime: RuntimeConfig | None = None
        self._adapter: ArenaModelAdapter | None = None
        self._canonicalize: Canonicalize | None = None
        self._canonicalizer_source: str | None = None
        self._adapter_model_key: str | None = None
        self._prompt: ResolvedPrompt | None = None
        self._prompt_delivered_sha256_to_adapter = False
        self._semaphore: threading.BoundedSemaphore | None = None
        self._job_locks: dict[str, threading.Lock] = {}

        self._provenance: dict[str, Any] | None = None
        self._provenance_lock = threading.Lock()
        self._readiness_thread: threading.Thread | None = None
        self.pod_age_watchdog: PodAgeWatchdog | None = None
        self.heartbeat = HeartbeatWriter(self.state_dir / "heartbeat.json", self._snapshot)

        # Whole-GPU VRAM (arena/worker/vram.py): the model server is a process
        # this worker does not own, so an in-process measurement reads zero.
        self.vram = VramSampler()
        self._vram_at_load_start_mb: int | None = None
        self._vram_baseline_mb: int | None = None
        self._vram_total_mb: int | None = None
        self._vram_unavailable_reason: str | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start the heartbeat, the readiness thread (MP 15.3) and the D20 fuse."""
        self.heartbeat.start()
        thread = threading.Thread(target=self._run_readiness, name="arena-readiness", daemon=True)
        self._readiness_thread = thread
        thread.start()
        if self.env.max_pod_age_hours is not None:
            watchdog = PodAgeWatchdog(
                self,
                max_age_seconds=self.env.max_pod_age_hours * 3600.0,
                drain_grace_seconds=self.env.pod_age_drain_seconds,
            )
            self.pod_age_watchdog = watchdog
            watchdog.start()
            LOG.info(
                "pod age fuse armed at %.2f h (ARENA_MAX_POD_AGE_HOURS)",
                self.env.max_pod_age_hours,
            )

    def stop(self) -> None:
        watchdog = self.pod_age_watchdog
        if watchdog is not None:
            watchdog.stop()
        self.heartbeat.stop()
        adapter = self._adapter
        if adapter is not None:
            try:
                adapter.close()
            except Exception as exc:  # pragma: no cover - adapter teardown is best effort
                LOG.warning("adapter.close() failed: %s", safe_error(exc))

    def _check_fatal_file(self) -> bool:
        """D47: if the entrypoint's sticky-failure file exists, go CRASHED.

        Returns whether the fatal file was found. Called before ``_prepare``
        loads anything, and on every ``/v1/ready`` -- a runtime the entrypoint
        condemned after this worker announced READY must not keep answering
        healthy.
        """
        fatal = read_fatal_file(self.env.fatal_file)
        if fatal is None:
            return False
        message = safe_error(
            f"ARENA_FATAL_FILE present at {self.env.fatal_file}: {fatal['reason']} "
            f"(size={fatal['size_bytes']}, mtime={fatal['mtime']})"
        )
        with self._lock:
            self._last_error = message
        self._set_stage("CRASHED", force=True)
        return True

    def _run_readiness(self) -> None:
        try:
            if self._check_fatal_file():
                LOG.error(
                    "worker %s: ARENA_FATAL_FILE present at startup; not loading the model",
                    self.env.worker_id,
                )
                return
            self._prepare()
        except Exception as exc:
            message = safe_error(exc)
            with self._lock:
                self._last_error = message
            self._set_stage("CRASHED", force=True)
            LOG.error("worker readiness failed, staying up for diagnosis: %s", message)
        finally:
            try:
                atomic_write_json(self.state_dir / "worker-info.json", self.worker_info())
            except OSError as exc:  # pragma: no cover - unwritable state volume
                LOG.warning("could not write worker-info.json: %s", safe_error(exc))
            if self.env.collect_provenance_at_startup:
                try:
                    self.provenance()
                except Exception as exc:  # pragma: no cover - provenance is never fatal
                    LOG.warning("provenance collection failed: %s", safe_error(exc))

    def _adapter_config(self, runtime: RuntimeConfig, prompt: ResolvedPrompt) -> AdapterConfig:
        """Build the frozen adapter configuration (D17, D34).

        ``prompt_sha256`` is passed when ``adapter_api.AdapterConfig`` declares
        it. That file belongs to the orchestrator, so this is a fact read from
        the dataclass, not an assumption about it; either way a ``toolkit``
        adapter can still verify what it built against ``prompt_text``, which is
        byte-identical to the registry file the hash was taken over.
        """
        extra: dict[str, Any] = {}
        if ADAPTER_CONFIG_ACCEPTS_PROMPT_SHA256:
            extra["prompt_sha256"] = prompt.sha256
        return AdapterConfig(
            model_key=runtime.model_key,
            model_repo=runtime.model_repo,
            model_revision=runtime.model_revision,
            weights_dir=runtime.weights_dir,
            prompt_id=runtime.prompt_id,
            prompt_text=prompt.text,
            inference_config=runtime.inference_config,
            inference_config_sha256=runtime.inference_config_sha256,
            max_concurrency=runtime.max_concurrency_per_worker,
            device=self.env.device,
            **extra,
        )

    def _await_model_server(
        self, what: str, call: Callable[[], _T]
    ) -> _T:
        """D19: a bounded, logged wait for a local model server that is still loading."""
        return retry_while_connection_refused(
            call,
            what=what,
            budget_seconds=self.env.model_server_wait_seconds,
            poll_seconds=self.env.model_server_poll_seconds,
        )

    def _prepare(self) -> None:
        runtime = load_runtime_config(self.env)
        prompt = resolve_prompt(self.env, runtime)
        adapter = load_adapter(self.env.runtime_dir)
        canonicalize, canonical_source = load_canonicalizer(self.env.runtime_dir)
        with self._lock:
            self._runtime = runtime
            self._prompt = prompt
            self._prompt_delivered_sha256_to_adapter = ADAPTER_CONFIG_ACCEPTS_PROMPT_SHA256
            self._adapter = adapter
            self._canonicalize = canonicalize
            self._canonicalizer_source = canonical_source
            self._adapter_model_key = getattr(adapter, "model_key", None)
            self._semaphore = threading.BoundedSemaphore(runtime.max_concurrency_per_worker)

        LOG.info(
            "prompt %s (kind %s) resolved from %s, sha256 %s",
            runtime.prompt_id,
            prompt.prompt_kind,
            prompt.path,
            prompt.sha256,
        )
        config = self._adapter_config(runtime, prompt)

        self._set_stage("MODEL_LOADING")
        at_load_start = self.vram.read()
        with self._lock:
            self._vram_at_load_start_mb = at_load_start.used_mb
        load_receipt = self._await_model_server("model load", lambda: adapter.load(config))
        if load_receipt.model_revision != runtime.model_revision:
            raise AdapterError(
                "MODEL_LOAD",
                f"adapter loaded revision {load_receipt.model_revision!r} but runtime.json "
                f"pins {runtime.model_revision!r}",
            )
        with self._lock:
            self._load_receipt = jsonable(asdict(load_receipt))
            self._load_ms = load_receipt.load_ms

        self._set_stage("WARMING")
        warmup_png = synthetic_page_png(self.synthetic_dir / f"warmup-{runtime.model_key}.png")
        warmup_receipt = self._await_model_server("warm-up", lambda: adapter.warmup(warmup_png))
        if not warmup_receipt.schema_valid:
            raise AdapterError("MODEL_LOAD", "warm-up inference failed the adapter schema check")
        with self._lock:
            self._warmup_receipt = jsonable(asdict(warmup_receipt))
        # The baseline is read *after* warm-up: weights, CUDA context and the
        # first allocator arena are all resident by then, so a page's peak minus
        # this baseline is what that page cost. Before warm-up it would be a
        # half-loaded model's number.
        self._record_vram_baseline()
        # Diagnostics land before the stage flips: a controller that sees READY
        # must already be able to read what this worker will demand.
        atomic_write_json(self.state_dir / "worker-info.json", self.worker_info())
        with self._lock:
            self._ready_at = utcnow()
            # Never flip to READY over a stage something else already moved to.
            # A drain (D20's fuse, or POST /v1/drain) that lands while the model
            # is still loading must survive: announcing READY afterwards would
            # invite the controller to dispatch a page to a pod that is leaving.
            if self._stage == "WARMING":
                self._stage = "READY"
                overridden = None
            else:
                overridden = self._stage
        if overridden is not None:
            LOG.warning(
                "worker %s finished warm-up in stage %s; not announcing READY",
                self.env.worker_id,
                overridden,
            )
            return
        LOG.info("worker %s READY (model %s)", self.env.worker_id, runtime.model_key)

    def _record_vram_baseline(self) -> None:
        """Read the device baseline and total, and hang them off the load receipt.

        ``ready-response.schema.json`` is ``additionalProperties: false`` and has
        no VRAM field, but ``load_receipt`` is a free-form object -- so the
        measurement goes in there, under its own ``vram`` key so nothing
        confuses it with something the adapter reported.
        """

        reading = self.vram.read()
        with self._lock:
            self._vram_baseline_mb = reading.used_mb
            self._vram_total_mb = reading.total_mb
            self._vram_unavailable_reason = reading.unavailable_reason
            if self._load_receipt is not None:
                self._load_receipt["vram"] = {
                    "measurement_source": (
                        MEASUREMENT_SOURCE_NVIDIA_SMI if reading.available else None
                    ),
                    "scope": "whole-gpu",
                    "device_count": reading.device_count,
                    "at_load_start_mb": self._vram_at_load_start_mb,
                    "baseline_vram_mb": reading.used_mb,
                    "vram_total_mb": reading.total_mb,
                    "unavailable_reason": reading.unavailable_reason,
                }
        if not reading.available:
            LOG.warning(
                "VRAM is not measurable on this pod (%s); peak_vram_mb stays null",
                reading.unavailable_reason,
            )

    # -- state -------------------------------------------------------------

    @property
    def stage(self) -> str:
        with self._lock:
            return self._stage

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    @property
    def active_jobs(self) -> int:
        """Pages currently inside ``/v1/run``. The D20 fuse waits on this."""
        with self._lock:
            return self._active_jobs

    def _set_stage(self, stage: str, *, force: bool = False) -> None:
        announce: str | None = None
        with self._lock:
            # DRAINING is one-way, like the terminal stages: once the pod has
            # been told to stop taking work -- by POST /v1/drain or the D20
            # lifetime fuse -- the readiness ladder must not walk back over it.
            if not force and (self._stage in TERMINAL_STAGES or self._stage == "DRAINING"):
                return
            if stage == "CRASHED" and self._stage != "CRASHED":
                announce = self._last_error or "(no error recorded)"
            self._stage = stage
        if announce is not None:
            # The pod is deleted moments after the driver sees CRASHED, and its
            # container log is the only evidence that survives the delete. Put
            # the reason there too, once per transition, on stdout -- stdlib
            # only, because this file ships in every bundle.
            print(f"[arena] worker CRASHED: {announce}", flush=True)

    def _enter_job(self, job_id: str) -> None:
        with self._lock:
            self._active_jobs += 1
            self._current_job_id = job_id
            self._last_progress_at = utcnow()
            self._output_progress = 0
            if self._stage == "READY":
                self._stage = "BUSY"

    def _exit_job(self, *, success: bool, output_chars: int) -> None:
        with self._lock:
            self._active_jobs = max(0, self._active_jobs - 1)
            self._current_job_id = None
            self._last_progress_at = utcnow()
            self._output_progress = output_chars
            if success:
                self._jobs_done += 1
            else:
                self._jobs_failed += 1
            if self._stage == "BUSY" and self._active_jobs == 0:
                self._stage = "READY"

    def _snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema": "tavonel.arena.heartbeat.v1",
                "worker_id": self.env.worker_id,
                # D4: a WORKER_STATES value, never a coarse bucket. The stage
                # this worker is actually in is the only honest answer, and an
                # unknown stage would be a defect here, not a state to report.
                "state": _worker_state(self._stage),
                "stage": self._stage,
                "job_id": self._current_job_id,
                "last_progress_at": self._last_progress_at,
                "output_progress": self._output_progress,
                "jobs_done": self._jobs_done,
                "jobs_failed": self._jobs_failed,
                "pid": os.getpid(),
            }
        # Anything else a controller might want lives on /v1/ready (live) or in
        # worker-info.json (static). heartbeat.schema.json is
        # additionalProperties:false and this object stays inside it, except for
        # the two fields noted in HeartbeatWriter.sample.

    # -- endpoints ---------------------------------------------------------

    def ready_response(self) -> dict[str, Any]:
        """Exactly ``arena/core/schemas/ready-response.schema.json``.

        That schema is ``additionalProperties: false``, so worker-side
        diagnostics (which canonicalizer loaded, the runtime.json hash, the
        config hash the worker will demand) live in ``worker-info.json`` under
        the state directory instead of leaking into this object. The schema
        also has no ``fatal`` field (D47's request for one is BLOCKED on that
        point -- see the config docstring); a fatal file's reason travels in
        ``last_error`` instead, the existing nullable string field the schema
        already carries.
        """
        self._check_fatal_file()
        with self._lock:
            return {
                "schema": "tavonel.arena.ready-response.v1",
                "stage": self._stage,
                "worker_id": self.env.worker_id,
                "model_key": self.env.model_key,
                "model_revision": self.env.model_revision,
                "runtime_mode": self.env.runtime_mode,
                "runtime_image_digest": self.env.image_digest,
                "load_receipt": self._load_receipt,
                "warmup_receipt": self._warmup_receipt,
                "started_at": self.started_at,
                "ready_at": self._ready_at,
                "last_error": self._last_error,
            }

    def worker_info(self) -> dict[str, Any]:
        """Worker-side diagnostics, written to ``<state_dir>/worker-info.json``."""
        with self._lock:
            runtime = self._runtime
            prompt = self._prompt
            return {
                "campaign_id": self.env.campaign_id,
                "worker_id": self.env.worker_id,
                "environment": self.env.public(),
                "prompt_id": runtime.prompt_id if runtime else None,
                "prompt_kind": runtime.prompt_kind if runtime else None,
                "prompt_sha256": prompt.sha256 if prompt else None,
                "prompt_file": str(prompt.path) if prompt else None,
                "prompt_source": prompt.source if prompt else None,
                # D34 asks a toolkit adapter to compare against
                # AdapterConfig.prompt_sha256. Whether the worker could hand it
                # over is recorded, never assumed.
                "adapter_config_prompt_sha256_delivered": (
                    self._prompt_delivered_sha256_to_adapter
                ),
                "inference_config_sha256": runtime.inference_config_sha256 if runtime else None,
                "runtime_json_sha256": runtime.runtime_json_sha256 if runtime else None,
                "max_concurrency_per_worker": (
                    runtime.max_concurrency_per_worker if runtime else None
                ),
                "per_page_timeout_seconds": runtime.per_page_timeout_seconds if runtime else None,
                "weights_dir": str(runtime.weights_dir) if runtime else None,
                "canonicalizer": self._canonicalizer_source,
                "adapter_model_key": self._adapter_model_key,
                "written_at": utcnow(),
            }

    def heartbeat_response(self) -> dict[str, Any]:
        return self.heartbeat.write_once()

    def provenance(self) -> dict[str, Any]:
        with self._provenance_lock:
            if self._provenance is None:
                adapter = self._adapter
                adapter_facts: Mapping[str, Any] | None = None
                if adapter is not None:
                    try:
                        adapter_facts = adapter.runtime_provenance()
                    except Exception as exc:  # pragma: no cover - adapter defect
                        adapter_facts = {"error": safe_error(exc)}
                self._provenance = provenance_module.collect_provenance(
                    image_digest=self.env.image_digest,
                    adapter_provenance=adapter_facts,
                )
                self._provenance["worker_id"] = self.env.worker_id
                self._provenance["runtime_mode"] = self.env.runtime_mode
            return self._provenance

    def drain(self) -> dict[str, Any]:
        self._set_stage("DRAINING")
        return {"stage": self.stage, "worker_id": self.env.worker_id, "at": utcnow()}

    def read_result(self, job_id: str) -> dict[str, Any] | None:
        """Read a persisted result, or ``None``. A corrupt file fails closed."""
        if not JOB_ID_RE.fullmatch(job_id):
            raise RequestRejected(
                "INVALID_REQUEST", "inference_job_id must be 64 lowercase hex characters"
            )
        path = self.results_dir / f"{job_id}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"persisted result {path.name} is unreadable: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"persisted result {path.name} is not a JSON object")
        return data

    def _job_lock(self, job_id: str) -> threading.Lock:
        with self._lock:
            lock = self._job_locks.get(job_id)
            if lock is None:
                lock = threading.Lock()
                self._job_locks[job_id] = lock
            return lock

    def handle_run(self, payload: object) -> tuple[int, dict[str, Any]]:
        """POST /v1/run. Returns ``(http_status, body)``."""
        request = parse_run_request(payload)
        if request.campaign_id != self.env.campaign_id:
            raise RequestRejected(
                "CAMPAIGN_MISMATCH",
                f"worker serves campaign {self.env.campaign_id!r}, "
                f"request carries {request.campaign_id!r}",
            )

        with self._job_lock(request.inference_job_id):
            persisted = self.read_result(request.inference_job_id)
            if persisted is not None:
                LOG.info("replaying persisted result for %s", request.inference_job_id)
                return 200, persisted

            stage = self.stage
            if stage not in ACCEPTING_STAGES:
                return 409, {
                    "error": "NOT_ACCEPTING",
                    "stage": stage,
                    "worker_id": self.env.worker_id,
                    "last_error": self.last_error,
                }

            runtime = self._runtime
            adapter = self._adapter
            canonicalize = self._canonicalize
            semaphore = self._semaphore
            if runtime is None or adapter is None or canonicalize is None or semaphore is None:
                return 409, {"error": "NOT_ACCEPTING", "stage": stage, "detail": "runtime absent"}

            if request.inference_config_sha256 != runtime.inference_config_sha256:
                raise RequestRejected(
                    "CONFIG_MISMATCH",
                    f"worker inference_config_sha256 {runtime.inference_config_sha256} != "
                    f"request {request.inference_config_sha256}",
                )
            # D17: the worker refuses a run whose request prompt_sha256 differs
            # from the hash of the registry file it resolved. There is no
            # "worker has no prompt" branch any more -- readiness fails closed
            # when the file is missing, so a READY worker always has a hash.
            prompt = self._prompt
            if prompt is None:
                return 409, {"error": "NOT_ACCEPTING", "stage": stage, "detail": "prompt absent"}
            if request.prompt_sha256 != prompt.sha256:
                raise RequestRejected(
                    "PROMPT_MISMATCH",
                    f"worker prompt_sha256 {prompt.sha256} (prompt_id {prompt.prompt_id}, "
                    f"kind {prompt.prompt_kind}) != request {request.prompt_sha256}",
                )

            started_at = utcnow()
            started_perf = time.perf_counter()

            try:
                image = base64.b64decode(request.image_b64, validate=True)
            except (binascii.Error, ValueError) as exc:
                return 422, self._build_response(
                    request,
                    status="FAILED",
                    error_class="INPUT_DECODE",
                    error_message=safe_error(f"image_b64 is not valid base64: {exc}"),
                    started_at=started_at,
                    total_ms=_elapsed_ms(started_perf),
                    input_bytes=0,
                    measured_ms={"preprocess_ms": _elapsed_ms(started_perf)},
                )

            digest = sha256_label(image)
            if digest != request.source_sha256:
                return 422, self._build_response(
                    request,
                    status="FAILED",
                    error_class="CHECKSUM",
                    error_message=(
                        f"decoded image hashes to {digest}, "
                        f"request declared {request.source_sha256}"
                    ),
                    started_at=started_at,
                    total_ms=_elapsed_ms(started_perf),
                    input_bytes=len(image),
                    measured_ms={"preprocess_ms": _elapsed_ms(started_perf)},
                )

            response = self._execute(
                request,
                image=image,
                runtime=runtime,
                adapter=adapter,
                canonicalize=canonicalize,
                semaphore=semaphore,
                started_at=started_at,
                started_perf=started_perf,
                decode_perf=started_perf,
            )
            atomic_write_json(self.results_dir / f"{request.inference_job_id}.json", response)
            return 200, response

    def _execute(
        self,
        request: RunRequest,
        *,
        image: bytes,
        runtime: RuntimeConfig,
        adapter: ArenaModelAdapter,
        canonicalize: Canonicalize,
        semaphore: threading.BoundedSemaphore,
        started_at: str,
        started_perf: float,
        decode_perf: float,
    ) -> dict[str, Any]:
        image_path = self.inputs_dir / f"{request.case_key}.png"
        atomic_write_bytes(image_path, image)
        # Worker-side preparation: base64 decode, checksum, page write. Used as
        # preprocess_ms only when the adapter does not report its own.
        preprocess_ms = _elapsed_ms(decode_perf)
        page = PageInput(
            inference_job_id=request.inference_job_id,
            sample_id=request.sample_id,
            case_key=request.case_key,
            benchmark=request.benchmark,
            image_path=image_path,
            source_sha256=request.source_sha256,
            width=request.width,
            height=request.height,
            metadata=request.metadata,
        )
        timeout = request.timeout_seconds or runtime.per_page_timeout_seconds

        raw: RawOutput | None = None
        canonical: CanonicalOutput | None = None
        error_class: str | None = None
        error_message: str | None = None

        with semaphore, self.vram.track() as vram_window:
            self._enter_job(request.inference_job_id)
            infer_perf = time.perf_counter()
            try:
                raw = self._infer_with_timeout(adapter, page, timeout)
            except _InferenceTimeout:
                # A worker that abandoned a page cannot be trusted with the
                # next one: the adapter thread may still hold the GPU.
                self._set_stage("STALLED", force=True)
                error_class = "INFERENCE_TIMEOUT"
                error_message = f"adapter.infer exceeded the {timeout:g}s per-page timeout"
            except AdapterError as exc:
                error_class = exc.error_class if exc.error_class in ERROR_CLASSES else "UNKNOWN"
                error_message = safe_error(exc)
                if error_class != exc.error_class:
                    error_message = (
                        f"adapter reported unknown error_class {exc.error_class!r}: "
                        f"{error_message}"
                    )
            except Exception as exc:
                error_class = "UNKNOWN"
                error_message = safe_error(exc)
            finally:
                inference_ms = _elapsed_ms(infer_perf)
                self._exit_job(
                    success=raw is not None,
                    output_chars=len(raw.raw_text) if raw is not None else 0,
                )

        postprocess_perf = time.perf_counter()
        if raw is not None:
            try:
                canonical = canonicalize(raw)
            except Exception as exc:
                canonical = None
                error_class = "POSTPROCESS"
                error_message = safe_error(exc)
        postprocess_ms = _elapsed_ms(postprocess_perf)

        status = "SUCCESS" if raw is not None and canonical is not None else "FAILED"
        return self._build_response(
            request,
            status=status,
            error_class=error_class,
            error_message=error_message,
            started_at=started_at,
            total_ms=_elapsed_ms(started_perf),
            input_bytes=len(image),
            raw=raw,
            canonical=canonical,
            vram_window=vram_window,
            measured_ms={
                "preprocess_ms": preprocess_ms,
                "inference_ms": inference_ms,
                "postprocess_ms": postprocess_ms,
            },
        )

    def _infer_with_timeout(
        self, adapter: ArenaModelAdapter, page: PageInput, timeout: float
    ) -> RawOutput:
        """Run the adapter on a thread the server can walk away from."""
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="arena-infer")
        try:
            future = pool.submit(adapter.infer, page)
            try:
                return future.result(timeout=timeout)
            except FutureTimeoutError as exc:
                future.cancel()
                raise _InferenceTimeout(f"{timeout:g}s") from exc
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _build_response(
        self,
        request: RunRequest,
        *,
        status: str,
        started_at: str,
        total_ms: int,
        input_bytes: int,
        error_class: str | None = None,
        error_message: str | None = None,
        raw: RawOutput | None = None,
        canonical: CanonicalOutput | None = None,
        vram_window: VramWindow | None = None,
        measured_ms: Mapping[str, int] | None = None,
    ) -> dict[str, Any]:
        # Every phase timing is measured, never assumed: the adapter's own
        # number when it reports one, otherwise the worker's wall-clock for
        # that phase. A failed page still has a real preprocess and inference
        # duration, and that is what the cost model needs.
        adapter_timings: Mapping[str, Any] = raw.timings_ms if raw is not None else {}
        measured: Mapping[str, int] = measured_ms or {}
        timings: dict[str, int] = {"load_ms": self._load_ms or 0, "total_ms": total_ms}
        for phase in ("preprocess_ms", "inference_ms", "postprocess_ms"):
            reported = _optional_int(adapter_timings.get(phase))
            timings[phase] = reported if reported is not None else int(measured.get(phase, 0))
        extra = [key for key in adapter_timings if key not in timings]
        if extra:
            LOG.debug("adapter reported timings outside the contract, dropped: %s", sorted(extra))

        peak_vram_mb, vram_source = self._resolve_peak_vram(raw, vram_window)
        with self._lock:
            baseline_vram_mb = self._vram_baseline_mb
            total_vram_mb = self._vram_total_mb
        if vram_window is not None and vram_window.total_mb is not None:
            total_vram_mb = vram_window.total_mb

        usage: Mapping[str, Any] = raw.usage if raw is not None else {}
        raw_text = raw.raw_text if raw is not None else None
        semantic_error_class, semantic_warnings = resolve_semantic_error_class(raw)
        warnings = list(raw.warnings) + list(semantic_warnings) if raw is not None else []

        return {
            "schema": "tavonel.arena.worker-run-response.v1",
            "inference_job_id": request.inference_job_id,
            "status": status,
            "error_class": error_class,
            "error_message": (
                safe_error(error_message) if isinstance(error_message, str) else None
            ),
            "worker_id": self.env.worker_id,
            "model_key": self.env.model_key,
            "model_revision": self.env.model_revision,
            "runtime_mode": self.env.runtime_mode,
            "runtime_image_digest": self.env.image_digest,
            "gpu_type": self.env.gpu_type,
            "pod_id": self.env.pod_id,
            "started_at": started_at,
            "first_token_at": raw.first_token_at if raw is not None else None,
            "finished_at": utcnow(),
            "timings_ms": timings,
            "peak_vram_mb": peak_vram_mb,
            "baseline_vram_mb": baseline_vram_mb,
            "vram_total_mb": total_vram_mb,
            "vram_measurement_source": vram_source,
            "input_bytes": input_bytes,
            # Zero here is a measurement, not a placeholder: a failed page
            # produced no output bytes at all.
            "output_bytes": len(raw_text.encode("utf-8")) if raw_text is not None else 0,
            "output_chars": len(raw_text) if raw_text is not None else 0,
            "input_tokens": _optional_int(usage.get("input_tokens")),
            "output_tokens": _optional_int(usage.get("output_tokens")),
            "raw_output": (
                None
                if raw is None
                else {
                    "raw_text": raw.raw_text,
                    "output_format": raw.output_format,
                    "native_json": jsonable(raw.native_json)
                    if raw.native_json is not None
                    else None,
                    "usage": jsonable(dict(raw.usage)),
                    "warnings": warnings,
                }
            ),
            "canonical": (
                None
                if canonical is None
                else {
                    "markdown": canonical.markdown,
                    "elements": jsonable(list(canonical.elements))
                    if canonical.elements is not None
                    else None,
                    "lossy": bool(canonical.lossy),
                    "conversion_notes": list(canonical.conversion_notes),
                }
            ),
            "raw_output_sha256": (
                sha256_label(raw_text.encode("utf-8")) if raw_text is not None else None
            ),
            "canonical_output_sha256": (
                sha256_label(canonical.markdown.encode("utf-8")) if canonical is not None else None
            ),
            "semantic_error_class": semantic_error_class,
        }
        # Nothing else goes in this object. arena/core/schemas/
        # worker-run-response.schema.json is additionalProperties:false, and the
        # controller already holds every request-side field it would need for
        # the page receipt because it sent them.

    @staticmethod
    def _resolve_peak_vram(
        raw: RawOutput | None, window: VramWindow | None
    ) -> tuple[int | None, str | None]:
        """The page's peak VRAM and where the number came from.

        The whole-GPU sample wins when there is one: an adapter that can see
        its own allocator is the exception here, and the two numbers measure
        different things, so the receipt must not silently mix them. When
        ``nvidia-smi`` gave nothing, an adapter-reported figure is still better
        than a null -- labelled ``adapter`` so nobody compares it with a
        device total.
        """

        if window is not None and window.peak_used_mb is not None:
            return window.peak_used_mb, MEASUREMENT_SOURCE_NVIDIA_SMI
        if raw is not None and raw.peak_vram_mb is not None:
            return raw.peak_vram_mb, MEASUREMENT_SOURCE_ADAPTER
        return None, None


def _worker_state(stage: str) -> str:
    if stage not in WORKER_STATE_VALUES:  # pragma: no cover - defended, never expected
        raise RuntimeError(
            f"worker stage {stage!r} is not in arena.constants.WORKER_STATES; "
            "the heartbeat refuses to invent a state value"
        )
    return stage


def resolve_semantic_error_class(raw: RawOutput | None) -> tuple[str | None, tuple[str, ...]]:
    """D3: the page's semantic verdict, plus any warning the resolution adds.

    Order: the adapter's own ``semantic_error_class`` field, then a warning
    whose text starts exactly with ``arena.semantic_error_class=`` (the C3
    convention), then ``None``. A value outside
    :data:`SEMANTIC_ERROR_CLASSES` is never passed through: the result is
    ``None`` and a warning says what was rejected, because a made-up class
    would flow into the page receipt and the recovery decision.
    """
    if raw is None:
        return None, ()

    declared = raw.semantic_error_class
    if declared is not None:
        if declared in SEMANTIC_ERROR_CLASSES:
            return declared, ()
        return None, (
            f"arena.worker: adapter reported semantic_error_class "
            f"{safe_error(str(declared))!r}, which is not one of "
            f"{list(SEMANTIC_ERROR_CLASSES)}; dropped",
        )

    for warning in raw.warnings:
        if not isinstance(warning, str) or not warning.startswith(SEMANTIC_WARNING_PREFIX):
            continue
        value = warning[len(SEMANTIC_WARNING_PREFIX) :].strip()
        if value in SEMANTIC_ERROR_CLASSES:
            return value, ()
        return None, (
            f"arena.worker: warning declared semantic_error_class "
            f"{safe_error(value)!r}, which is not one of "
            f"{list(SEMANTIC_ERROR_CLASSES)}; dropped",
        )
    return None, ()


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _elapsed_ms(start_perf: float) -> int:
    return round((time.perf_counter() - start_perf) * 1000)


class ArenaHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        core: WorkerCore,
    ) -> None:
        self.core = core
        super().__init__(address, handler)


class ArenaRequestHandler(BaseHTTPRequestHandler):
    server_version = "arena-worker/1"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    @property
    def core(self) -> WorkerCore:
        server = self.server
        if not isinstance(server, ArenaHTTPServer):
            raise RuntimeError("handler is not bound to an ArenaHTTPServer")
        return server.core

    def log_message(self, format: str, *args: Any) -> None:
        LOG.info("%s %s", self.address_string(), safe_error(format % args))

    def _send(self, status: int, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "") or ""
        prefix = "Bearer "
        supplied = header[len(prefix) :] if header.startswith(prefix) else ""
        return hmac.compare_digest(supplied, self.core.env.token)

    def _read_body(self) -> object:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length else 0
        except ValueError as exc:
            raise RequestRejected("INVALID_REQUEST", "Content-Length is not an integer") from exc
        if length < 0:
            raise RequestRejected("INVALID_REQUEST", "Content-Length must not be negative")
        if length > MAX_BODY_BYTES:
            raise RequestRejected(
                "BODY_TOO_LARGE", f"body of {length} bytes exceeds {MAX_BODY_BYTES}"
            )
        if length == 0:
            return {}
        data = self.rfile.read(length)
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestRejected("INVALID_REQUEST", f"body is not valid JSON: {exc}") from exc

    def _path(self) -> str:
        path = urlsplit(self.path).path
        return path.rstrip("/") or "/"

    def do_GET(self) -> None:
        if not self._authorized():
            self._send(401, {"error": "UNAUTHORIZED"})
            return
        path = self._path()
        try:
            core = self.core
            if path == "/v1/ready":
                self._send(200, core.ready_response())
            elif path == "/v1/heartbeat":
                self._send(200, core.heartbeat_response())
            elif path == "/v1/provenance":
                self._send(200, core.provenance())
            elif path.startswith("/v1/result/"):
                job_id = path[len("/v1/result/") :]
                result = core.read_result(job_id)
                if result is None:
                    self._send(404, {"error": "NOT_FOUND", "inference_job_id": job_id})
                else:
                    self._send(200, result)
            else:
                self._send(404, {"error": "NOT_FOUND", "path": path})
        except RequestRejected as exc:
            self._send(422, {"error": exc.code, "detail": exc.detail})
        except Exception as exc:
            LOG.exception("GET %s failed", path)
            self._send(500, {"error": "INTERNAL", "detail": safe_error(exc)})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send(401, {"error": "UNAUTHORIZED"})
            return
        path = self._path()
        try:
            core = self.core
            if path == "/v1/run":
                status, body = core.handle_run(self._read_body())
                self._send(status, body)
            elif path == "/v1/drain":
                self._read_body()
                self._send(200, core.drain())
            else:
                self._send(404, {"error": "NOT_FOUND", "path": path})
        except RequestRejected as exc:
            self._send(422, {"error": exc.code, "detail": exc.detail})
        except Exception as exc:
            LOG.exception("POST %s failed", path)
            self._send(500, {"error": "INTERNAL", "detail": safe_error(exc)})


def create_server(env: WorkerEnv) -> tuple[ArenaHTTPServer, WorkerCore]:
    core = WorkerCore(env)
    server = ArenaHTTPServer((env.host, env.port), ArenaRequestHandler, core)
    return server, core


def main(argv: Sequence[str] | None = None) -> int:
    del argv  # the worker is configured only through the pod environment
    logging.basicConfig(
        level=os.environ.get("ARENA_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    env = WorkerEnv.from_env()
    server, core = create_server(env)
    core.start()
    LOG.info(
        "arena worker %s listening on %s:%s (model %s, mode %s)",
        env.worker_id,
        env.host,
        env.port,
        env.model_key,
        env.runtime_mode,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - operator interrupt
        LOG.info("interrupted; shutting down")
    finally:
        core.stop()
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())


__all__ = [
    "ACCEPTING_STAGES",
    "ADAPTER_CONFIG_ACCEPTS_PROMPT_SHA256",
    "CONTRACT_RESULT_KEYS",
    "MAX_POD_AGE_EXIT_CODE",
    "SEMANTIC_ERROR_CLASSES",
    "SEMANTIC_WARNING_PREFIX",
    "WORKER_STATE_VALUES",
    "ArenaHTTPServer",
    "ArenaRequestHandler",
    "PodAgeWatchdog",
    "RequestRejected",
    "RunRequest",
    "WorkerCore",
    "create_server",
    "is_connection_refused",
    "main",
    "parse_run_request",
    "read_fatal_file",
    "resolve_semantic_error_class",
    "retry_while_connection_refused",
]
