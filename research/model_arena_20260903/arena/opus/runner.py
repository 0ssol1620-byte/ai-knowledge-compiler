"""One fresh ``claude -p`` process per page, with a bounded worker pool.

Masterplan sections 21.6 (fresh context per page), 21.7 (2 -> 4 -> 6 ramp),
21.8 (limit handling), 21.10 (image-handling caveat) and 22 (receipt).

Shape of a run:

    for each page:  fresh process -> JSON payload -> raw files -> page receipt

Nothing is retried inside this module. A limit stops the pool, writes a
checkpoint and makes the CLI exit 75; an unexpected model stops the pool as a
scientific-integrity stop (section 43).
"""

from __future__ import annotations

import contextlib
import json
import re
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from arena.constants import CAMPAIGN_ID
from arena.core import ids as core_ids
from arena.core import receipts as core_receipts
from arena.opus.command import (
    OPUS_DECLARED_MODEL,
    OPUS_MODEL_REPO,
    OpusCommandConfig,
    assert_no_fallback,
    attribute_models,
    build_command,
    build_prompt,
)
from arena.opus.env import scrub_env, subscription_image_digest
from arena.opus.limits import AUTH_EXPIRED, SIGTERM_EXIT_CODE, LimitDetection, classify
from arena.opus.paths import (
    CANARY_DIR,
    CANONICAL_DIR,
    CHECKPOINT_PATH,
    MODEL_KEY,
    RAW_DIR,
    RECEIPT_DIR,
    RUN_ROOT,
    RUN_SUMMARY_PATH,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    canonical_json,
    read_json,
    sha256_tagged,
)
from arena.opus.pricing import PriceSnapshot, auxiliary_usage, estimate_price, extract_usage
from arena.opus.prompt import ResolvedPrompt
from arena.opus.selection import PageSpec, SelectionError, read_image_facts

WORKERS_DEFAULT: Final = 2
WORKERS_HARD_MAX: Final = 6
# D63: an operator stops a running pool by creating this file under RUN_ROOT.
# Every page already dispatched finishes and writes its receipt; nothing new is
# started; the pool checkpoints the rest exactly as a limit would, so
# `resume` (with any --workers) picks up where it stopped. The file is removed
# when acknowledged, so the resume does not stop again on the same request.
STOP_FILE_NAME: Final = "STOP"
OPERATOR_STOP_REASON: Final = "operator_stop"
RAMP_INITIAL_WORKERS: Final = 2
RAMP_SUCCESS_THRESHOLD: Final = 50
PER_PAGE_TIMEOUT_SECONDS_DEFAULT: Final = 600
LIMIT_EXIT_CODE: Final = 75
RECEIPT_SCHEMA: Final = "tavonel.arena.page-receipt.v1"
MAX_ERROR_MESSAGE_CHARS: Final = 2000

_FENCE_RE: Final = re.compile(
    r"\A```[ \t]*([A-Za-z0-9_+\-]*)[ \t]*\r?\n(.*?)\r?\n?```[ \t]*\Z", re.DOTALL
)


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def timestamp_slug() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def clamp_message(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= MAX_ERROR_MESSAGE_CHARS:
        return collapsed
    return collapsed[: MAX_ERROR_MESSAGE_CHARS - 3] + "..."


def canonicalize_raw_text(raw_text: str) -> tuple[str, list[str]]:
    """Whitespace-normalise and unwrap a single wrapping code fence.

    This is the *only* transformation applied. It never adds, reorders or repairs
    content; every change it makes is reported in ``conversion_notes``
    (adapter_api.py: canonicalization may never fill a gap).
    """
    notes: list[str] = []
    text = raw_text
    stripped = text.strip()
    if stripped != text:
        notes.append("stripped leading/trailing whitespace")
    text = stripped
    match = _FENCE_RE.match(text)
    if match is not None:
        inner = match.group(2)
        # Only unwrap when the fence spans the entire result; a document that
        # merely contains a code block is left alone by the regex anchors.
        if "```" not in inner:
            language = match.group(1) or "none"
            text = inner.strip()
            notes.append(
                f"unwrapped a single wrapping markdown code fence (info string: {language})"
            )
        else:
            notes.append(
                "result begins and ends with a fence but contains nested fences; left as is"
            )
    return text, notes


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    command: OpusCommandConfig
    prompt: ResolvedPrompt
    price_snapshot: PriceSnapshot
    claude_version: str | None
    workers: int = WORKERS_DEFAULT
    timeout_seconds: int = PER_PAGE_TIMEOUT_SECONDS_DEFAULT
    job_kind: str = "inference"
    ramp_threshold: int = RAMP_SUCCESS_THRESHOLD
    ramp_initial: int = RAMP_INITIAL_WORKERS
    env: Mapping[str, str] | None = None
    child_cwd: Path | None = None
    extra_receipt_fields: Mapping[str, Any] = field(default_factory=dict)
    selection_source: str | None = None
    selection_detail: str | None = None

    @property
    def runtime_image_digest(self) -> str:
        """``subscription:claude-code-<cli version>-<model id>`` (D27).

        There is no container in this lane, so the pair that decides what the
        model sees is the Claude Code build and the model id it resolves to.
        """
        return subscription_image_digest(self.claude_version, OPUS_DECLARED_MODEL)


@dataclass(frozen=True, slots=True)
class PageOutcome:
    case_key: str
    sample_id: str
    status: str
    error_class: str | None
    error_message: str | None
    wall_seconds: float
    receipt: dict[str, Any]
    limit: LimitDetection | None
    stop_reason: str | None


class _RampGate:
    """Concurrency permit holder implementing the 2 -> N ramp of section 21.7."""

    def __init__(self, initial: int, target: int, threshold: int) -> None:
        self._target = max(1, target)
        self._initial = max(1, min(initial, self._target))
        self._threshold = max(0, threshold)
        self._semaphore = threading.Semaphore(self._initial)
        self._lock = threading.Lock()
        self._successes = 0
        self._raised = self._initial >= self._target or self._threshold == 0
        if self._threshold == 0 and self._initial < self._target:
            for _ in range(self._target - self._initial):
                self._semaphore.release()

    @property
    def current_limit(self) -> int:
        return self._target if self._raised else self._initial

    def acquire(self) -> None:
        self._semaphore.acquire()

    def release(self) -> None:
        self._semaphore.release()

    def note_success(self) -> None:
        with self._lock:
            self._successes += 1
            if not self._raised and self._successes >= self._threshold:
                self._raised = True
                for _ in range(self._target - self._initial):
                    self._semaphore.release()


def schema_error(receipt: Mapping[str, Any]) -> str | None:
    """``None`` when the receipt satisfies page-receipt.schema.json, else why not.

    The check runs through ``arena.core.receipts.validate`` so this lane and the
    GPU lanes are judged by one contract. The two keys recording the outcome are
    added *after* the check and are not part of the schema's required set, so
    recording the result cannot change it.
    """
    try:
        core_receipts.validate(dict(receipt))
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _stamp_schema_check(receipt: dict[str, Any]) -> str | None:
    error = schema_error(receipt)
    receipt["receipt_schema"] = "page-receipt.schema.json"
    receipt["receipt_schema_valid"] = error is None
    receipt["receipt_schema_error"] = error
    return error


def _output_dirs(job_kind: str) -> tuple[Path, Path, Path]:
    """(raw_dir, canonical_dir, receipt_dir) for this job kind."""
    if job_kind == "canary":
        base = CANARY_DIR
        return base / "raw", base / "canonical", base / "receipts"
    return RAW_DIR, CANONICAL_DIR, RECEIPT_DIR


def run_page(spec: PageSpec, cfg: RunnerConfig, *, worker_index: int) -> PageOutcome:
    """Run exactly one page in a fresh process and persist everything it produced."""
    raw_dir, canonical_dir, receipt_dir = _output_dirs(cfg.job_kind)
    # Both ids come from arena.core.ids (shard width 4, D27); this lane keeps no
    # private id implementation. There is no pod, so the worker's host slot is
    # named "local".
    worker_id = core_ids.worker_id(MODEL_KEY, worker_index, "local")
    shard_id = core_ids.shard_id(MODEL_KEY, spec.benchmark, 0)
    queued_at = utcnow()
    prompt_sha = cfg.prompt.sha256
    config_sha = cfg.command.inference_config_sha256()

    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "benchmark": spec.benchmark,
        "benchmark_revision": spec.benchmark_revision,
        "sample_id": spec.sample_id,
        "case_key": spec.case_key,
        "model_key": MODEL_KEY,
        "model_repo": OPUS_MODEL_REPO,
        "model_revision": OPUS_DECLARED_MODEL,
        "runtime_mode": "subscription",
        "runtime_image_digest": cfg.runtime_image_digest,
        "surface": "claude-code-read-tool",
        "prompt_id": cfg.prompt.prompt_id,
        "prompt_sha256": prompt_sha,
        "prompt_source": cfg.prompt.source,
        "inference_config_sha256": config_sha,
        "job_kind": cfg.job_kind,
        "worker_id": worker_id,
        "shard_id": shard_id,
        "gpu_type": None,
        "gpu_id": None,
        "pod_id": None,
        "peak_vram_mb": None,
        "wasted_gpu_seconds": 0.0,
        "attempt": 1,
        "retry_count": 0,
        "retry_reason": None,
        "queued_at": queued_at,
        "worker_ready_at": queued_at,
        "first_token_at": None,
        "actual_marginal_api_cost": "N/A",
        "subscription_included_usage": True,
        "price_snapshot_sha256": cfg.price_snapshot.snapshot_sha256,
        "price_snapshot_captured_at": cfg.price_snapshot.captured_at,
        "image_handling_caveat": (
            "Claude Code's Read tool may resize or recompress a large page image before the "
            "model sees it (masterplan 21.10). Original dimensions, bytes and sha256 are "
            "recorded here; this is not an API raw-image benchmark."
        ),
    }
    receipt.update(dict(cfg.extra_receipt_fields))

    def fail(
        error_class: str,
        message: str,
        *,
        started_at: str,
        limit: LimitDetection | None = None,
        stop_reason: str | None = None,
        extra: Mapping[str, Any] | None = None,
        wall_seconds: float = 0.0,
    ) -> PageOutcome:
        receipt.update(
            {
                "started_at": started_at,
                "finished_at": utcnow(),
                "status": "FAILED",
                "error_class": error_class,
                "error_message": clamp_message(message),
                "queue_ms": 0,
                "load_ms": 0,
                "preprocess_ms": 0,
                "inference_ms": int(wall_seconds * 1000),
                "postprocess_ms": 0,
                "total_ms": int(wall_seconds * 1000),
                "output_bytes": 0,
                "output_chars": 0,
                "raw_output_path": None,
                "raw_output_sha256": None,
                "canonical_output_path": None,
                "canonical_output_sha256": None,
            }
        )
        receipt.setdefault("input_tokens", None)
        receipt.setdefault("output_tokens", None)
        receipt.setdefault("cache_creation_input_tokens", None)
        receipt.setdefault("cache_read_input_tokens", None)
        receipt.setdefault("api_equivalent_list_price_usd", None)
        receipt.setdefault("input_bytes", None)
        receipt.setdefault("image_width", None)
        receipt.setdefault("image_height", None)
        receipt.setdefault("source_sha256", spec.manifest_input_sha256)
        receipt.setdefault("reported_model", None)
        if extra:
            receipt.update(dict(extra))
        _stamp_schema_check(receipt)
        atomic_write_json(
            receipt_dir / f"{spec.case_key}.json", receipt, where=f"receipt:{spec.case_key}"
        )
        return PageOutcome(
            case_key=spec.case_key,
            sample_id=spec.sample_id,
            status="FAILED",
            error_class=error_class,
            error_message=clamp_message(message),
            wall_seconds=wall_seconds,
            receipt=receipt,
            limit=limit,
            stop_reason=stop_reason,
        )

    started_at = utcnow()

    try:
        image_bytes, image_sha, width, height = read_image_facts(spec)
    except SelectionError as exc:
        return fail("CHECKSUM", str(exc), started_at=started_at)

    receipt.update(
        {
            "source_sha256": image_sha,
            "staged_input_sha256": spec.manifest_input_sha256,
            "staged_source_sha256": spec.staged_source_sha256,
            "input_bytes": len(image_bytes),
            "image_width": width,
            "image_height": height,
            "image_path": str(spec.image_path),
        }
    )
    try:
        receipt["inference_job_id"] = core_ids.inference_job_id(
            campaign_id=CAMPAIGN_ID,
            benchmark_revision=spec.benchmark_revision,
            sample_id=spec.sample_id,
            source_sha256=image_sha,
            model_repo=OPUS_MODEL_REPO,
            model_revision=OPUS_DECLARED_MODEL,
            runtime_image_digest=cfg.runtime_image_digest,
            prompt_sha256=prompt_sha,
            inference_config_sha256=config_sha,
        )
    except core_ids.IdError as exc:
        return fail("UNKNOWN", f"inference_job_id refused by arena.core.ids: {exc}",
                    started_at=started_at)

    argv = build_command(cfg.command, spec.image_path)
    assert_no_fallback(argv)
    prompt_text = build_prompt(cfg.prompt.text, spec.image_path)
    child_env = dict(cfg.env) if cfg.env is not None else scrub_env()
    cwd = str(cfg.child_cwd) if cfg.child_cwd else None

    started_at = utcnow()
    monotonic = time.perf_counter()
    try:
        completed = subprocess.run(
            argv,
            input=prompt_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=cfg.timeout_seconds,
            env=child_env,
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired:
        wall = time.perf_counter() - monotonic
        return fail(
            "INFERENCE_TIMEOUT",
            f"claude -p exceeded the {cfg.timeout_seconds}s per-page wall clock and was killed",
            started_at=started_at,
            wall_seconds=wall,
        )
    except OSError as exc:
        wall = time.perf_counter() - monotonic
        return fail(
            "DEPENDENCY",
            f"could not start the claude executable: {type(exc).__name__}",
            started_at=started_at,
            wall_seconds=wall,
        )
    wall = time.perf_counter() - monotonic

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    exit_code = completed.returncode
    receipt["cli_exit_code"] = exit_code
    receipt["cli_stderr_excerpt"] = clamp_message(stderr) if stderr else None

    payload: dict[str, Any] | None = None
    parse_error: str | None = None
    if stdout.strip():
        try:
            decoded = json.loads(stdout)
        except json.JSONDecodeError as exc:
            parse_error = f"stdout is not JSON: {exc.msg}"
        else:
            if isinstance(decoded, dict):
                payload = decoded
            else:
                parse_error = f"stdout JSON is a {type(decoded).__name__}, expected an object"

    detection = classify(
        exit_code=exit_code, stderr=stderr, payload=payload, raw_stdout=stdout
    )
    if detection is not None:
        if detection.kind == AUTH_EXPIRED:
            # An expired/unrefreshable subscription OAuth session is an
            # infrastructure condition, not a page result: it says nothing
            # about this page, so no page receipt is written for it (unlike
            # every other limit kind, which does write a FAILED receipt).
            # The pool still pauses and the case_key stays pending for a
            # later `resume` once the founder has re-authenticated.
            return PageOutcome(
                case_key=spec.case_key,
                sample_id=spec.sample_id,
                status="AUTH_EXPIRED",
                error_class=detection.error_class,
                error_message=(
                    f"{detection.kind}: matched {detection.matched_pattern!r} in "
                    f"{detection.matched_in} ({detection.matched_source}); "
                    f"reset hint: {detection.reset_hint}"
                ),
                wall_seconds=wall,
                receipt={},
                limit=detection,
                stop_reason=f"limit:{detection.kind}",
            )
        if payload is not None:
            atomic_write_bytes(
                raw_dir / f"{spec.case_key}.claude.json",
                json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8"),
            )
        return fail(
            detection.error_class,
            f"{detection.kind}: matched {detection.matched_pattern!r} in {detection.matched_in} "
            f"({detection.matched_source})"
            + (f"; reset hint: {detection.reset_hint}" if detection.reset_hint else ""),
            started_at=started_at,
            limit=detection,
            stop_reason=f"limit:{detection.kind}",
            extra={"limit_detection": detection.to_json()},
            wall_seconds=wall,
        )

    if exit_code == SIGTERM_EXIT_CODE:
        return fail(
            "INFERENCE_TIMEOUT",
            "claude -p exited 143 (SIGTERM); the run was terminated before it produced a result",
            started_at=started_at,
            wall_seconds=wall,
        )
    if payload is None:
        return fail(
            "OUTPUT_MALFORMED",
            f"exit {exit_code}: {parse_error or 'no stdout'}",
            started_at=started_at,
            wall_seconds=wall,
        )

    payload_path = raw_dir / f"{spec.case_key}.claude.json"
    payload_bytes = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False).encode(
        "utf-8"
    )
    payload_sha = atomic_write_bytes(payload_path, payload_bytes)
    receipt["claude_payload_path"] = str(payload_path)
    receipt["claude_payload_sha256"] = payload_sha
    session_id = payload.get("session_id")
    receipt["claude_session_id"] = session_id if isinstance(session_id, str) else None
    num_turns = payload.get("num_turns")
    receipt["claude_num_turns"] = num_turns if isinstance(num_turns, int) else None
    duration_ms = payload.get("duration_ms")
    receipt["claude_duration_ms"] = duration_ms if isinstance(duration_ms, int) else None
    cost = payload.get("total_cost_usd")
    receipt["claude_client_cost_estimate_usd"] = (
        float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None
    )
    receipt["claude_client_cost_estimate_note"] = (
        "Client-side estimate emitted by Claude Code; not an invoice amount and not the "
        "api_equivalent_list_price_usd column."
    )

    attribution = attribute_models(payload)
    receipt.update(attribution.to_json())
    receipt["reported_model"] = attribution.primary
    usage = extract_usage(payload, model=attribution.primary)
    receipt.update(usage.to_json())
    receipt["auxiliary_model_usage"] = auxiliary_usage(payload, attribution.auxiliary)
    receipt["auxiliary_model_note"] = (
        "Claude Code spends a small amount of an auxiliary model on its own housekeeping "
        "inside a -p run. Those tokens are recorded here and excluded from the benchmark's "
        "token and price columns; they are not a model fallback."
    )
    price = estimate_price(usage, cfg.price_snapshot)
    receipt.update(price.to_json())

    reason = attribution.failure_reason()
    if reason is not None:
        return fail(
            "UNKNOWN",
            reason,
            started_at=started_at,
            stop_reason="unexpected_model",
            wall_seconds=wall,
        )

    if bool(payload.get("is_error")):
        message = payload.get("result")
        return fail(
            "OUTPUT_MALFORMED",
            "claude reported is_error=true: "
            + (message if isinstance(message, str) else "no result text"),
            started_at=started_at,
            wall_seconds=wall,
        )

    raw_text = payload.get("result")
    if not isinstance(raw_text, str):
        return fail(
            "OUTPUT_MALFORMED",
            f"payload 'result' is {type(raw_text).__name__}, expected a string",
            started_at=started_at,
            wall_seconds=wall,
        )
    if not raw_text.strip():
        return fail(
            "OUTPUT_EMPTY",
            "claude returned an empty result for a page that was supposed to be transcribed",
            started_at=started_at,
            wall_seconds=wall,
        )

    raw_path = raw_dir / f"{spec.case_key}.raw.txt"
    raw_sha = atomic_write_text(raw_path, raw_text)
    canonical_text, conversion_notes = canonicalize_raw_text(raw_text)
    canonical_path = canonical_dir / f"{spec.case_key}.md"
    canonical_sha = atomic_write_text(canonical_path, canonical_text)

    finished_at = utcnow()
    receipt.update(
        {
            "started_at": started_at,
            "finished_at": finished_at,
            "status": "SUCCESS",
            "error_class": None,
            "error_message": None,
            "queue_ms": 0,
            "load_ms": 0,
            "preprocess_ms": 0,
            "inference_ms": int(wall * 1000),
            "postprocess_ms": 0,
            "total_ms": int(wall * 1000),
            "wall_seconds": round(wall, 3),
            "output_bytes": len(raw_text.encode("utf-8")),
            "output_chars": len(raw_text),
            "raw_output_path": str(raw_path),
            "raw_output_sha256": raw_sha,
            "canonical_output_path": str(canonical_path),
            "canonical_output_sha256": canonical_sha,
            "conversion_notes": conversion_notes,
            "canonical_lossy": False,
        }
    )
    invalid = _stamp_schema_check(receipt)
    if invalid is not None:
        # The page produced bytes, but a receipt the shared validator rejects is
        # not evidence. The outputs above are already on disk; the page is
        # reported FAILED rather than counted as a success (no silent pass).
        return fail(
            "UNKNOWN",
            f"page receipt does not satisfy page-receipt.schema.json: {invalid}",
            started_at=started_at,
            wall_seconds=wall,
            extra={
                "raw_output_path": str(raw_path),
                "raw_output_sha256": raw_sha,
                "canonical_output_path": str(canonical_path),
                "canonical_output_sha256": canonical_sha,
            },
        )
    atomic_write_json(
        receipt_dir / f"{spec.case_key}.json", receipt, where=f"receipt:{spec.case_key}"
    )
    return PageOutcome(
        case_key=spec.case_key,
        sample_id=spec.sample_id,
        status="SUCCESS",
        error_class=None,
        error_message=None,
        wall_seconds=wall,
        receipt=receipt,
        limit=None,
        stop_reason=None,
    )


@dataclass
class RunReport:
    outcomes: list[PageOutcome] = field(default_factory=list)
    stopped: bool = False
    stop_reason: str | None = None
    limit: LimitDetection | None = None
    pending: list[str] = field(default_factory=list)
    checkpoint_path: str | None = None

    @property
    def succeeded(self) -> list[str]:
        return [o.case_key for o in self.outcomes if o.status == "SUCCESS"]

    @property
    def failed(self) -> list[str]:
        return [o.case_key for o in self.outcomes if o.status != "SUCCESS"]

    @property
    def exit_code(self) -> int:
        if self.limit is not None:
            return LIMIT_EXIT_CODE
        if self.stopped or self.failed:
            return 1
        return 0


def write_checkpoint(report: RunReport, cfg: RunnerConfig) -> Path:
    payload: dict[str, Any] = {
        "schema": "tavonel.arena.opus-checkpoint.v1",
        "campaign_id": CAMPAIGN_ID,
        "model_key": MODEL_KEY,
        "written_at": utcnow(),
        "job_kind": cfg.job_kind,
        "selection_source": cfg.selection_source,
        "selection_detail": cfg.selection_detail,
        "stop_reason": report.stop_reason,
        "limit": report.limit.to_json() if report.limit else None,
        "reset_hint": report.limit.reset_hint if report.limit else None,
        "done_case_keys": report.succeeded,
        "failed_case_keys": report.failed,
        "pending_case_keys": report.pending,
        "counts": {
            "done": len(report.succeeded),
            "failed": len(report.failed),
            "pending": len(report.pending),
        },
        "no_fallback_assertion": (
            "No fallback, no model downgrade, no API auto-switch was performed "
            "(masterplan section 21.8)."
        ),
        "prompt_sha256": cfg.prompt.sha256,
        "inference_config_sha256": cfg.command.inference_config_sha256(),
        "runtime_image_digest": cfg.runtime_image_digest,
    }
    atomic_write_json(CHECKPOINT_PATH, payload, where="checkpoint")
    return CHECKPOINT_PATH


def settle_checkpoint(report: RunReport, path: Path | None = None) -> Path | None:
    """Strike the pages this run finished off an existing checkpoint.

    A resume that completes leaves the checkpoint behind saying those pages are
    still pending; the next ``resume`` would then run them again and spend the
    founder's allowance on work that already has receipts. This removes what the
    run attempted from ``pending_case_keys`` and records that it did so.

    It never *creates* a checkpoint (only :func:`write_checkpoint` does) and never
    deletes one: a settled checkpoint keeps the stop that produced it, so the
    capacity event that interrupted the run stays legible.
    """
    target = path or CHECKPOINT_PATH
    if not target.is_file():
        return None
    data = read_json(target)
    if not isinstance(data, dict):
        return None
    pending = data.get("pending_case_keys")
    if not isinstance(pending, list):
        return None

    attempted = {o.case_key for o in report.outcomes}
    if not attempted:
        return None
    still_pending = [key for key in pending if str(key) not in attempted]
    if len(still_pending) == len(pending):
        return None

    history = data.get("settled_runs")
    runs = list(history) if isinstance(history, list) else []
    runs.append(
        {
            "settled_at": utcnow(),
            "attempted": sorted(attempted),
            "succeeded": sorted(report.succeeded),
            "failed": sorted(report.failed),
        }
    )
    data["pending_case_keys"] = still_pending
    data["settled_runs"] = runs
    counts = data.get("counts")
    data["counts"] = {
        "done": len(report.succeeded)
        + (int(counts.get("done", 0)) if isinstance(counts, dict) else 0),
        "failed": len(report.failed)
        + (int(counts.get("failed", 0)) if isinstance(counts, dict) else 0),
        "pending": len(still_pending),
    }
    data["settled_note"] = (
        "A later run finished these pages. The stop that created this checkpoint is "
        "unchanged above; only pending_case_keys was reduced, so a further `resume` "
        "cannot re-run pages that already have receipts."
    )
    atomic_write_json(target, data, where="checkpoint-settle")
    return target


def load_checkpoint(path: Path | None = None) -> dict[str, Any]:
    target = path or CHECKPOINT_PATH
    if not target.is_file():
        raise FileNotFoundError(f"no checkpoint at {target}")
    data = read_json(target)
    if not isinstance(data, dict):
        raise ValueError(f"checkpoint is not an object: {target}")
    return data


def run_pages(
    specs: Sequence[PageSpec],
    cfg: RunnerConfig,
    *,
    progress: Callable[[PageOutcome], None] | None = None,
) -> RunReport:
    """Run the pool. Stops dispatching on the first limit or unexpected model."""
    workers = max(1, min(cfg.workers, WORKERS_HARD_MAX))
    gate = _RampGate(cfg.ramp_initial, workers, cfg.ramp_threshold)
    stop = threading.Event()
    report = RunReport()
    lock = threading.Lock()
    remaining: dict[str, PageSpec] = {s.case_key: s for s in specs}

    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    child_cwd = cfg.child_cwd
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if child_cwd is None:
        # A directory outside any repository, so the child does not auto-discover
        # a project CLAUDE.md or a project settings file. See CLAUDE_CLI_FLAGS.md.
        temp_dir = tempfile.TemporaryDirectory(prefix="arena-opus-")
        child_cwd = Path(temp_dir.name)
        cfg = replace(cfg, child_cwd=child_cwd)

    def operator_stop_requested() -> bool:
        stop_file = RUN_ROOT / STOP_FILE_NAME
        if not stop_file.is_file():
            return False
        with lock:
            if not report.stopped:
                report.stopped = True
                report.stop_reason = OPERATOR_STOP_REASON
            # Acknowledged either way; the checkpoint is the record.
            with contextlib.suppress(OSError):
                stop_file.unlink()
        stop.set()
        return True

    def work(index: int, spec: PageSpec) -> PageOutcome | None:
        if stop.is_set() or operator_stop_requested():
            return None
        gate.acquire()
        try:
            if stop.is_set():
                return None
            return run_page(spec, cfg, worker_index=index % workers)
        finally:
            gate.release()

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures: dict[Future[PageOutcome | None], PageSpec] = {}
            for index, spec in enumerate(specs):
                futures[pool.submit(work, index, spec)] = spec
            for future in as_completed(list(futures)):
                outcome = future.result()
                spec = futures[future]
                if outcome is None:
                    continue
                # AUTH_EXPIRED wrote no receipt (run_page): it is an
                # infrastructure condition, not a page result, so the
                # case_key stays in `remaining` (pending) rather than being
                # recorded as done or failed -- a later `resume` retries it.
                auth_expired = outcome.limit is not None and outcome.limit.kind == AUTH_EXPIRED
                with lock:
                    if not auth_expired:
                        report.outcomes.append(outcome)
                        remaining.pop(spec.case_key, None)
                if progress is not None:
                    progress(outcome)
                if outcome.status == "SUCCESS":
                    gate.note_success()
                elif outcome.stop_reason is not None:
                    with lock:
                        report.stopped = True
                        report.stop_reason = outcome.stop_reason
                        report.limit = outcome.limit
                    stop.set()
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    report.pending = [s.case_key for s in specs if s.case_key in remaining]
    if report.stopped:
        report.checkpoint_path = str(write_checkpoint(report, cfg))
    else:
        settle_checkpoint(report)
    return report


def write_run_summary(report: RunReport, cfg: RunnerConfig, *, extra: Mapping[str, Any]) -> Path:
    """Write ``run-summary.json`` for exactly this invocation.

    Deliberately **not cumulative**: this is one process's report of the
    pages it just ran, overwritten by the next invocation and by a
    ``resume``. That is why it names only ``report.outcomes``, never the
    receipt files a prior invocation already wrote to disk.

    The cumulative record lives elsewhere: ``canary/receipts/*.json`` never
    loses a page across resumes (each page receipt is its own file, written
    once and never rewritten), and for the canary job kind
    ``canary_receipt.build_canary_receipt`` reads every one of those files
    and derives ``receipts/canary-opus5_subscription.json`` -- the shared
    schema's canary receipt (ARENA_CONTRACT 11.6 D37) -- from the complete
    set. That receipt, not this summary, is the source of truth for "how
    many pages has this canary produced in total" and "what is the p50/p90
    wall time and price floor over all of them". A reader who wants a
    cumulative view should read the canary receipt (or re-derive it with
    ``python -m arena.opus canary-receipt``, which spends nothing), not
    assume this file's counts are anything but the last batch.
    """
    wall_times = [o.wall_seconds for o in report.outcomes if o.status == "SUCCESS"]
    prices = [
        o.receipt.get("api_equivalent_list_price_usd")
        for o in report.outcomes
        if o.status == "SUCCESS"
    ]
    numeric_prices = [p for p in prices if isinstance(p, (int, float))]
    payload: dict[str, Any] = {
        "schema": "tavonel.arena.opus-run-summary.v1",
        "campaign_id": CAMPAIGN_ID,
        "model_key": MODEL_KEY,
        "display_name": "Claude Opus 5 - Claude Code subscription surface",
        "written_at": utcnow(),
        "job_kind": cfg.job_kind,
        "runtime_mode": "subscription",
        "runtime_image_digest": cfg.runtime_image_digest,
        "claude_version": cfg.claude_version,
        "workers_configured": cfg.workers,
        "ramp": {"initial": cfg.ramp_initial, "success_threshold": cfg.ramp_threshold},
        "per_page_timeout_seconds": cfg.timeout_seconds,
        "prompt": cfg.prompt.to_json(),
        "inference_config": cfg.command.inference_config(),
        "inference_config_sha256": cfg.command.inference_config_sha256(),
        "price_snapshot_sha256": cfg.price_snapshot.snapshot_sha256,
        "counts": {
            "attempted": len(report.outcomes),
            "success": len(report.succeeded),
            "failed": len(report.failed),
            "pending": len(report.pending),
        },
        "wall_seconds": {
            "min": round(min(wall_times), 3) if wall_times else None,
            "max": round(max(wall_times), 3) if wall_times else None,
            "mean": round(sum(wall_times) / len(wall_times), 3) if wall_times else None,
        },
        "api_equivalent_list_price_usd_total": (
            round(sum(numeric_prices), 6) if numeric_prices else None
        ),
        "actual_marginal_api_cost": "N/A",
        "subscription_included_usage": True,
        "stopped": report.stopped,
        "stop_reason": report.stop_reason,
        "limit": report.limit.to_json() if report.limit else None,
        "pages": [
            {
                "case_key": o.case_key,
                "sample_id": o.sample_id,
                "status": o.status,
                "error_class": o.error_class,
                "wall_seconds": round(o.wall_seconds, 3),
                "output_chars": o.receipt.get("output_chars"),
                "input_tokens": o.receipt.get("input_tokens"),
                "output_tokens": o.receipt.get("output_tokens"),
                "api_equivalent_list_price_usd": o.receipt.get(
                    "api_equivalent_list_price_usd"
                ),
                "reported_model": o.receipt.get("reported_model"),
            }
            for o in report.outcomes
        ],
    }
    payload.update(dict(extra))
    target = RUN_SUMMARY_PATH if cfg.job_kind != "canary" else CANARY_DIR / "run-summary.json"
    atomic_write_json(target, payload, where="run-summary")
    return target


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return sha256_tagged(canonical_json(dict(payload)).encode("utf-8"))


__all__ = [
    "LIMIT_EXIT_CODE",
    "PER_PAGE_TIMEOUT_SECONDS_DEFAULT",
    "RAMP_SUCCESS_THRESHOLD",
    "WORKERS_DEFAULT",
    "WORKERS_HARD_MAX",
    "PageOutcome",
    "RunReport",
    "RunnerConfig",
    "canonicalize_raw_text",
    "clamp_message",
    "load_checkpoint",
    "payload_sha256",
    "run_page",
    "run_pages",
    "schema_error",
    "settle_checkpoint",
    "timestamp_slug",
    "utcnow",
    "write_checkpoint",
    "write_run_summary",
]
