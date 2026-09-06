"""``python -m arena.opus <preflight|probe|canary|run|status|resume|verify>``.

Exit codes: 0 success, 1 failure, 75 a subscription/rate/capacity limit stopped
the pool (masterplan section 21.8), 2 a usage error.

``probe`` and ``canary`` are the only commands that consume subscription
allowance, and both refuse to run unless explicitly asked for. ``canary`` runs
the frozen ``opus_canary`` block of ``canary_selection.json`` and is capped at
``CANARY_MAX_PAGES``; ``run`` refuses to start without ``--execute`` so a full
5,132-page pass is never begun by accident. ``verify`` spends nothing: it
re-validates receipts already on disk against the shared schema and re-derives
every identifier through ``arena.core.ids``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from arena.constants import CAMPAIGN_ID
from arena.core import ids as core_ids
from arena.core import receipts as core_receipts
from arena.opus import paths as opus_paths
from arena.opus.canary_receipt import CanaryReceiptError, build_canary_receipt
from arena.opus.command import (
    OPUS_DECLARED_MODEL,
    OPUS_MODEL_REPO,
    OpusCommandConfig,
    attribute_models,
    build_probe_command,
)
from arena.opus.env import PreflightError, preflight, scrub_env, subscription_image_digest
from arena.opus.limits import classify
from arena.opus.paths import (
    CAMPAIGN_RECEIPT_DIR,
    CANARY_DIR,
    MODEL_KEY,
    RECEIPT_DIR,
    RUN_ROOT,
    atomic_write_json,
    read_json,
)
from arena.opus.pricing import PriceSnapshot, auxiliary_usage, estimate_price, extract_usage
from arena.opus.prompt import PromptError, resolve_prompt
from arena.opus.runner import (
    LIMIT_EXIT_CODE,
    PER_PAGE_TIMEOUT_SECONDS_DEFAULT,
    RAMP_SUCCESS_THRESHOLD,
    WORKERS_DEFAULT,
    WORKERS_HARD_MAX,
    PageOutcome,
    RunnerConfig,
    run_pages,
    timestamp_slug,
    utcnow,
    write_run_summary,
)
from arena.opus.selection import (
    CANARY_SELECTION_PATH,
    PageSpec,
    SelectionError,
    read_frozen_opus_canary,
    resolve_case_keys,
    select_canary_pages,
    select_source_manifest_pages,
)

# ARENA_CONTRACT D27 replaces the 3-page qualification of section 7: the canary
# is the frozen 50-page ``opus_canary`` block.
CANARY_MAX_PAGES: Final = 50
# ARENA_CONTRACT 11.6 D37: receipts/canary-<model_key>.json, the shared schema
# every other lane's canary receipt uses.
SHARED_CANARY_RECEIPT_PATH: Final = CAMPAIGN_RECEIPT_DIR / f"canary-{MODEL_KEY}.json"
PROBE_PROMPT: Final = "Reply with the single word OK"
EXIT_OK: Final = 0
EXIT_FAIL: Final = 1
EXIT_USAGE: Final = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m arena.opus",
        description="Claude Opus 5 subscription-surface runner (masterplan section 21).",
    )
    parser.add_argument(
        "command",
        choices=(
            "preflight", "probe", "canary", "run", "status", "resume", "verify",
            "canary-receipt",
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=WORKERS_DEFAULT,
        help=f"worker processes (default {WORKERS_DEFAULT}, hard max {WORKERS_HARD_MAX})",
    )
    parser.add_argument("--limit", type=int, default=None, help="maximum pages to run")
    parser.add_argument(
        "--timeout",
        type=int,
        default=PER_PAGE_TIMEOUT_SECONDS_DEFAULT,
        help="per-page wall-clock timeout in seconds",
    )
    parser.add_argument(
        "--effort", default="high", help="Claude Code effort level for every page"
    )
    parser.add_argument(
        "--claude", default=None, help="path to the claude executable (default: PATH)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="required by `run`; without it `run` prints the plan and stops",
    )
    parser.add_argument(
        "--case-key",
        action="append",
        default=None,
        help="explicit case key to run (repeatable); overrides the canary selection",
    )
    return parser


def _clamped_workers(requested: int) -> int:
    return max(1, min(requested, WORKERS_HARD_MAX))


def _resolve_config(
    args: argparse.Namespace,
) -> tuple[OpusCommandConfig, str | None, dict[str, Any] | None]:
    """Preflight, including the subscription-auth check (fails closed inside
    ``preflight``). Returns the command config, the CLI version string, and the
    ``auth`` facts as JSON so callers can carry them into a receipt.
    """
    result = preflight(executable=args.claude)
    if not result.ok:
        for finding in result.findings:
            print(f"PREFLIGHT: {finding}", file=sys.stderr)
        raise PreflightError("preflight failed; refusing to run")
    return (
        OpusCommandConfig(claude_executable=result.claude_executable, effort=args.effort),
        result.claude_version,
        result.auth.to_json() if result.auth is not None else None,
    )


def cmd_preflight(args: argparse.Namespace) -> int:
    result = preflight(executable=args.claude)
    payload: dict[str, Any] = {
        "schema": "tavonel.arena.opus-preflight.v1",
        "campaign_id": CAMPAIGN_ID,
        "model_key": MODEL_KEY,
        "checked_at": utcnow(),
        **result.to_json(),
    }
    try:
        prompt = resolve_prompt()
        payload["prompt"] = prompt.to_json()
    except PromptError as exc:
        payload["prompt"] = None
        payload["prompt_error"] = str(exc)
    try:
        snapshot = PriceSnapshot.load()
        payload["price_snapshot"] = {
            "model_id": snapshot.model_id,
            "captured_at": snapshot.captured_at,
            "source_urls": list(snapshot.source_urls),
            "input_per_mtok_usd": snapshot.input_per_mtok_usd,
            "output_per_mtok_usd": snapshot.output_per_mtok_usd,
            "cache_write_per_mtok_usd": snapshot.cache_write_per_mtok_usd,
            "cache_read_per_mtok_usd": snapshot.cache_read_per_mtok_usd,
            "snapshot_sha256": snapshot.snapshot_sha256,
        }
    except Exception as exc:
        payload["price_snapshot"] = None
        payload["price_snapshot_error"] = f"{type(exc).__name__}: {exc}"
    if result.ok:
        cfg = OpusCommandConfig(
            claude_executable=result.claude_executable, effort=args.effort
        )
        payload["inference_config"] = cfg.inference_config()
        payload["inference_config_sha256"] = cfg.inference_config_sha256()
        payload["probe_command"] = build_probe_command(cfg)

    target = CAMPAIGN_RECEIPT_DIR / f"opus-preflight-{timestamp_slug()}.json"
    atomic_write_json(target, payload, where="preflight")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nwrote {target}", file=sys.stderr)
    return EXIT_OK if result.ok else EXIT_FAIL


def cmd_probe(args: argparse.Namespace) -> int:
    """One trivial JSON call. Proves auth, model id, usage shape and wall time."""
    cfg, version, host_auth = _resolve_config(args)
    argv = build_probe_command(cfg)
    env = scrub_env()
    started = utcnow()
    monotonic = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="arena-opus-probe-") as cwd:
        try:
            completed = subprocess.run(
                argv,
                input=PROBE_PROMPT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=args.timeout,
                env=env,
                cwd=cwd,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(f"probe timed out after {args.timeout}s", file=sys.stderr)
            return EXIT_FAIL
    wall = time.perf_counter() - monotonic

    payload: dict[str, Any] | None = None
    parse_error: str | None = None
    if (completed.stdout or "").strip():
        try:
            decoded = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            parse_error = exc.msg
        else:
            payload = decoded if isinstance(decoded, dict) else None
            if payload is None:
                parse_error = f"stdout JSON is a {type(decoded).__name__}"

    detection = classify(
        exit_code=completed.returncode,
        stderr=completed.stderr or "",
        payload=payload,
        raw_stdout=completed.stdout or "",
    )
    attribution = attribute_models(payload) if payload else None
    usage = (
        extract_usage(payload, model=attribution.primary)
        if payload and attribution
        else None
    )
    price = None
    if usage is not None:
        try:
            price = estimate_price(usage, PriceSnapshot.load()).to_json()
        except Exception as exc:
            price = {"error": f"{type(exc).__name__}: {exc}"}

    record: dict[str, Any] = {
        "schema": "tavonel.arena.opus-probe.v1",
        "campaign_id": CAMPAIGN_ID,
        "model_key": MODEL_KEY,
        "started_at": started,
        "finished_at": utcnow(),
        "wall_seconds": round(wall, 3),
        "claude_version": version,
        "host_auth": host_auth,
        "argv_without_executable": argv[1:],
        "prompt": PROBE_PROMPT,
        "prompt_delivery": "stdin",
        "scrubbed_env_names": sorted(env),
        "exit_code": completed.returncode,
        "stderr_excerpt": (completed.stderr or "").strip()[:2000] or None,
        "stdout_parse_error": parse_error,
        "payload": payload,
        **(attribution.to_json() if attribution else {"reported_models": []}),
        "reported_model": attribution.primary if attribution else None,
        "reported_model_is_opus5": bool(attribution and attribution.ok),
        "model_attribution_failure": attribution.failure_reason() if attribution else None,
        "usage": usage.to_json() if usage else None,
        "auxiliary_model_usage": (
            auxiliary_usage(payload, attribution.auxiliary)
            if payload and attribution
            else {}
        ),
        "api_equivalent_price": price,
        "limit_detected": detection.to_json() if detection else None,
        "nesting_guard_interfered": _nesting_guard_finding(
            completed.returncode, completed.stderr or "", payload
        ),
    }
    target = CAMPAIGN_RECEIPT_DIR / f"opus-probe-{timestamp_slug()}.json"
    atomic_write_json(target, record, where="probe")
    print(json.dumps(record, indent=2, ensure_ascii=False))
    print(f"\nwrote {target}", file=sys.stderr)

    if detection is not None:
        return LIMIT_EXIT_CODE
    if payload is None or not record["reported_model_is_opus5"]:
        return EXIT_FAIL
    return EXIT_OK


def _nesting_guard_finding(
    exit_code: int, stderr: str, payload: dict[str, Any] | None
) -> str | None:
    """Report, verbatim, any refusal to run inside another Claude Code session."""
    haystack = stderr
    if payload is not None and isinstance(payload.get("result"), str):
        haystack = f"{haystack}\n{payload['result']}"
    lowered = haystack.lower()
    for needle in ("nested", "already running inside", "recursive", "claude code session"):
        if needle in lowered:
            return haystack.strip()[:2000]
    if exit_code != 0 and payload is None and stderr.strip():
        return stderr.strip()[:2000]
    return None


def _specs_for(args: argparse.Namespace, *, default_limit: int) -> tuple[list[PageSpec], str, str]:
    if args.case_key:
        specs = resolve_case_keys(list(args.case_key))
        return specs, "explicit_case_keys", "case keys given on the command line"
    limit = args.limit if args.limit is not None else default_limit
    selection = select_canary_pages(limit)
    return list(selection.specs), selection.source, selection.detail


def _run_specs_for(args: argparse.Namespace) -> tuple[list[PageSpec], str, str]:
    """``run``'s selection: the whole ``source_manifest.jsonl`` campaign by
    default (5,132 pages, ARENA_CONTRACT section 7), never the 50-page canary
    block. ``--case-key`` still overrides, and ``--limit`` still trims."""
    if args.case_key:
        specs = resolve_case_keys(list(args.case_key))
        return specs, "explicit_case_keys", "case keys given on the command line"
    selection = select_source_manifest_pages(args.limit)
    specs, skipped = _without_receipted(list(selection.specs))
    detail = selection.detail
    if skipped:
        detail = (
            f"{detail}; {skipped} page(s) already have a receipt under "
            f"{opus_paths.RECEIPT_DIR} and were skipped (D63)"
        )
    return specs, selection.source, detail


def _without_receipted(specs: list[PageSpec]) -> tuple[list[PageSpec], int]:
    """D63: a restarted ``run`` is idempotent over the receipts already on disk.

    A page receipt is written once, atomically, after the page finished (in
    either status), so its presence is the fact that the page was run. A
    killed process leaves no checkpoint; this is what lets ``run`` be started
    again -- with a different ``--workers`` -- without paying for the pages
    the previous process already finished. Looked up through the module so the
    test fixture's redirected run root is honoured.
    """
    receipt_dir = opus_paths.RECEIPT_DIR
    kept = [spec for spec in specs if not (receipt_dir / f"{spec.case_key}.json").is_file()]
    return kept, len(specs) - len(kept)


def _report_progress(outcome: PageOutcome) -> None:
    print(
        f"[{outcome.status}] {outcome.case_key} "
        f"{outcome.wall_seconds:.1f}s "
        f"chars={outcome.receipt.get('output_chars')} "
        f"in={outcome.receipt.get('input_tokens')} out={outcome.receipt.get('output_tokens')}"
        + (f" {outcome.error_class}: {outcome.error_message}" if outcome.error_class else ""),
        file=sys.stderr,
    )


def _run(args: argparse.Namespace, *, job_kind: str, specs: Sequence[PageSpec],
         selection_source: str, selection_detail: str) -> int:
    cfg, version, host_auth = _resolve_config(args)
    prompt = resolve_prompt()
    snapshot = PriceSnapshot.load()
    runner_cfg = RunnerConfig(
        command=cfg,
        prompt=prompt,
        price_snapshot=snapshot,
        claude_version=version,
        workers=_clamped_workers(args.workers),
        timeout_seconds=args.timeout,
        job_kind=job_kind,
        ramp_threshold=RAMP_SUCCESS_THRESHOLD,
        selection_source=selection_source,
        selection_detail=selection_detail,
    )
    report = run_pages(specs, runner_cfg, progress=_report_progress)
    summary_path = write_run_summary(
        report,
        runner_cfg,
        extra={
            "selection_source": selection_source,
            "selection_detail": selection_detail,
            "prompt_notes": list(prompt.notes),
            "host_auth": host_auth,
        },
    )
    print(f"wrote {summary_path}", file=sys.stderr)

    if job_kind == "canary":
        receipt = {
            "schema": "tavonel.arena.opus-canary-receipt.v1",
            "campaign_id": CAMPAIGN_ID,
            "model_key": MODEL_KEY,
            "display_name": "Claude Opus 5 - Claude Code subscription surface",
            "written_at": utcnow(),
            "runtime_mode": "subscription",
            "runtime_image_digest": runner_cfg.runtime_image_digest,
            "claude_version": version,
            "host_auth": host_auth,
            "selection_source": selection_source,
            "selection_detail": selection_detail,
            "selection_frozen_pages": _frozen_page_count(),
            "prompt": prompt.to_json(),
            "inference_config": cfg.inference_config(),
            "inference_config_sha256": cfg.inference_config_sha256(),
            "price_snapshot_sha256": snapshot.snapshot_sha256,
            "actual_marginal_api_cost": "N/A",
            "subscription_included_usage": True,
            "surface": "claude-code-read-tool",
            "image_handling_caveat": (
                "Results include Claude Code's Read-tool image handling (masterplan 21.10); "
                "this is not an API raw-image benchmark."
            ),
            "pages": [
                {
                    "case_key": o.case_key,
                    "sample_id": o.sample_id,
                    "benchmark": o.receipt.get("benchmark"),
                    "status": o.status,
                    "error_class": o.error_class,
                    "error_message": o.error_message,
                    "wall_seconds": round(o.wall_seconds, 3),
                    "image_width": o.receipt.get("image_width"),
                    "image_height": o.receipt.get("image_height"),
                    "input_bytes": o.receipt.get("input_bytes"),
                    "source_sha256": o.receipt.get("source_sha256"),
                    "input_tokens": o.receipt.get("input_tokens"),
                    "output_tokens": o.receipt.get("output_tokens"),
                    "cache_creation_input_tokens": o.receipt.get(
                        "cache_creation_input_tokens"
                    ),
                    "cache_read_input_tokens": o.receipt.get("cache_read_input_tokens"),
                    "output_chars": o.receipt.get("output_chars"),
                    "api_equivalent_list_price_usd": o.receipt.get(
                        "api_equivalent_list_price_usd"
                    ),
                    "reported_model": o.receipt.get("reported_model"),
                    "raw_output_sha256": o.receipt.get("raw_output_sha256"),
                    "canonical_output_sha256": o.receipt.get("canonical_output_sha256"),
                    "conversion_notes": o.receipt.get("conversion_notes"),
                }
                for o in report.outcomes
            ],
            "counts": {
                "attempted": len(report.outcomes),
                "success": len(report.succeeded),
                "failed": len(report.failed),
            },
            "stopped": report.stopped,
            "stop_reason": report.stop_reason,
        }
        target = CAMPAIGN_RECEIPT_DIR / f"opus-canary-{timestamp_slug()}.json"
        atomic_write_json(target, receipt, where="canary-receipt")
        print(f"wrote {target}", file=sys.stderr)

        # ARENA_CONTRACT 11.6 D37: also emit the shared-schema receipt every
        # other lane's canary uses, built from the complete set of page
        # receipts on disk (cumulative across resumes; see
        # _emit_shared_canary_receipt's docstring).
        try:
            shared = _emit_shared_canary_receipt(
                runtime_image_digest=runner_cfg.runtime_image_digest,
                workers=runner_cfg.workers,
            )
        except CanaryReceiptError as exc:
            print(f"WARNING: shared canary receipt not written: {exc}", file=sys.stderr)
        else:
            if shared is not None:
                print(f"wrote {shared[0]}", file=sys.stderr)

    if report.limit is not None:
        print(
            f"STOPPED: {report.stop_reason}; checkpoint at {report.checkpoint_path}. "
            "No fallback, no downgrade, no API switch was performed.",
            file=sys.stderr,
        )
    return report.exit_code


def cmd_canary(args: argparse.Namespace) -> int:
    limit = args.limit if args.limit is not None else CANARY_MAX_PAGES
    if limit > CANARY_MAX_PAGES:
        print(
            f"canary is capped at {CANARY_MAX_PAGES} pages in this build phase "
            f"(--limit {limit} refused)",
            file=sys.stderr,
        )
        return EXIT_USAGE
    args.limit = limit
    specs, source, detail = _specs_for(args, default_limit=CANARY_MAX_PAGES)
    specs = specs[:CANARY_MAX_PAGES]
    return _run(args, job_kind="canary", specs=specs, selection_source=source,
                selection_detail=detail)


def cmd_run(args: argparse.Namespace) -> int:
    if not args.execute:
        print(
            "`run` is the full subscription pass and spends the founder's allowance. "
            "Re-run with --execute once the canary has passed and the founder has "
            "authorised the full run (ARENA_CONTRACT section 7).",
            file=sys.stderr,
        )
        return EXIT_USAGE
    specs, source, detail = _run_specs_for(args)
    if not specs:
        print(f"nothing left to run: {detail}", file=sys.stderr)
        return EXIT_OK
    return _run(args, job_kind="inference", specs=specs, selection_source=source,
                selection_detail=detail)


def cmd_resume(args: argparse.Namespace) -> int:
    checkpoint_path = RUN_ROOT / "checkpoint.json"
    if not checkpoint_path.is_file():
        print(f"no checkpoint at {checkpoint_path}; nothing to resume", file=sys.stderr)
        return EXIT_USAGE
    data = read_json(checkpoint_path)
    pending = data.get("pending_case_keys") if isinstance(data, dict) else None
    if not isinstance(pending, list) or not pending:
        print("checkpoint has no pending case keys; nothing to resume", file=sys.stderr)
        return EXIT_OK
    keys = [str(k) for k in pending]
    if args.limit is not None:
        keys = keys[: args.limit]
    job_kind = str(data.get("job_kind") or "inference") if isinstance(data, dict) else "inference"
    if job_kind != "canary" and not args.execute:
        print(
            f"resume would run {len(keys)} pending pages of the full pass; "
            "re-run with --execute",
            file=sys.stderr,
        )
        return EXIT_USAGE
    specs = resolve_case_keys(keys)
    return _run(
        args,
        job_kind=job_kind,
        specs=specs,
        selection_source="checkpoint",
        selection_detail=str(checkpoint_path),
    )


def _emit_shared_canary_receipt(
    *, runtime_image_digest: str, workers: int
) -> tuple[Path, dict[str, Any]] | None:
    """Build and write the shared-schema canary receipt from every receipt on disk.

    ARENA_CONTRACT 11.6 D37: no new inference. This reads every page receipt
    under ``canary/receipts/`` -- the complete, resume-tolerant population,
    not just the pages this particular invocation ran -- so the receipt it
    writes is cumulative across resumes even though ``canary/run-summary.json``
    (masterplan-required, one file per invocation) is not. Returns ``None``
    when there are no receipts to summarise yet (e.g. every page in this
    invocation failed before a receipt was written).
    """
    receipt_dir = CANARY_DIR / "receipts"
    if not receipt_dir.is_dir():
        return None
    page_receipts = [read_json(p) for p in sorted(receipt_dir.glob("*.json"))]
    if not page_receipts:
        return None
    document = build_canary_receipt(
        page_receipts,
        runtime_image_digest=runtime_image_digest,
        written_at=utcnow(),
        workers=workers,
    )
    atomic_write_json(SHARED_CANARY_RECEIPT_PATH, document, where="shared-canary-receipt")
    return SHARED_CANARY_RECEIPT_PATH, document


def cmd_canary_receipt(args: argparse.Namespace) -> int:
    """Re-emit ``receipts/canary-opus5_subscription.json`` from receipts on disk.

    Spends nothing: no page is run and no process is started. This is the
    command a future canary run should follow (and the one this fix pass
    used to re-emit the existing 50-page canary in the shared schema).
    """
    workers = _clamped_workers(args.workers)
    try:
        _cfg, version, _host_auth = _resolve_config(args)
    except PreflightError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_FAIL
    runtime_image_digest = subscription_image_digest(version, OPUS_DECLARED_MODEL)
    try:
        result = _emit_shared_canary_receipt(
            runtime_image_digest=runtime_image_digest, workers=workers
        )
    except CanaryReceiptError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_FAIL
    if result is None:
        print("no canary page receipts on disk; nothing to summarise", file=sys.stderr)
        return EXIT_USAGE
    target, document = result
    print(json.dumps(document, indent=2, ensure_ascii=False))
    print(f"\nwrote {target}", file=sys.stderr)
    return EXIT_OK if document["status"] == "PASS" else EXIT_FAIL


def _frozen_page_count() -> int | None:
    """How many pages the frozen ``opus_canary`` block holds, or ``None``."""
    if not CANARY_SELECTION_PATH.is_file():
        return None
    try:
        return len(read_frozen_opus_canary(CANARY_SELECTION_PATH))
    except SelectionError:
        return None


def _verify_receipt(data: dict[str, Any]) -> list[str]:
    """Every way one page receipt fails the shared contract. Empty means clean."""
    problems: list[str] = []
    try:
        core_receipts.validate(data)
    except Exception as exc:
        problems.append(f"schema: {type(exc).__name__}: {exc}")

    required = (
        "benchmark_revision",
        "sample_id",
        "source_sha256",
        "runtime_image_digest",
        "prompt_sha256",
        "inference_config_sha256",
        "inference_job_id",
    )
    missing = [name for name in required if not isinstance(data.get(name), str)]
    if missing:
        problems.append(f"ids: cannot recompute, missing {missing}")
        return problems

    try:
        expected = core_ids.inference_job_id(
            campaign_id=str(data.get("campaign_id")),
            benchmark_revision=str(data["benchmark_revision"]),
            sample_id=str(data["sample_id"]),
            source_sha256=str(data["source_sha256"]),
            model_repo=str(data.get("model_repo") or OPUS_MODEL_REPO),
            model_revision=str(data.get("model_revision") or OPUS_DECLARED_MODEL),
            runtime_image_digest=str(data["runtime_image_digest"]),
            prompt_sha256=str(data["prompt_sha256"]),
            inference_config_sha256=str(data["inference_config_sha256"]),
        )
    except core_ids.IdError as exc:
        problems.append(f"ids: arena.core.ids refuses these inputs: {exc}")
        return problems
    if expected != data["inference_job_id"]:
        problems.append(
            f"ids: inference_job_id is {data['inference_job_id']} but arena.core.ids "
            f"derives {expected}"
        )

    benchmark = data.get("benchmark")
    shard = data.get("shard_id")
    if isinstance(benchmark, str) and isinstance(shard, str):
        try:
            expected_shard = core_ids.shard_id(str(data.get("model_key")), benchmark, 0)
        except core_ids.IdError as exc:
            problems.append(f"ids: shard_id inputs rejected: {exc}")
        else:
            if shard != expected_shard:
                problems.append(
                    f"ids: shard_id is {shard!r} but arena.core.ids derives "
                    f"{expected_shard!r} (width {core_ids.SHARD_INDEX_WIDTH})"
                )
    return problems


def cmd_verify(_args: argparse.Namespace) -> int:
    """Re-validate the receipts on disk. Spends nothing, changes nothing."""
    results: list[dict[str, Any]] = []
    for label, directory in (
        ("canary", CANARY_DIR / "receipts"),
        ("inference", RECEIPT_DIR),
    ):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                data = read_json(path)
            except (OSError, ValueError) as exc:
                results.append(
                    {
                        "job_kind": label,
                        "path": str(path),
                        "ok": False,
                        "problems": [f"unreadable: {type(exc).__name__}: {exc}"],
                    }
                )
                continue
            if not isinstance(data, dict):
                results.append(
                    {
                        "job_kind": label,
                        "path": str(path),
                        "ok": False,
                        "problems": ["receipt is not a JSON object"],
                    }
                )
                continue
            problems = _verify_receipt(data)
            results.append(
                {
                    "job_kind": label,
                    "path": str(path),
                    "case_key": data.get("case_key"),
                    "status": data.get("status"),
                    "ok": not problems,
                    "problems": problems,
                }
            )
    bad = [r for r in results if not r["ok"]]
    payload = {
        "schema": "tavonel.arena.opus-verify.v1",
        "campaign_id": CAMPAIGN_ID,
        "model_key": MODEL_KEY,
        "checked_at": utcnow(),
        "validator": "arena.core.receipts.validate + arena.core.ids",
        "counts": {"checked": len(results), "ok": len(results) - len(bad), "failed": len(bad)},
        "receipts": results,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return EXIT_OK if not bad else EXIT_FAIL


def _count_receipts(directory: Path) -> tuple[int, dict[str, int]]:
    statuses: dict[str, int] = {}
    if not directory.is_dir():
        return 0, statuses
    paths = sorted(directory.glob("*.json"))
    for path in paths:
        try:
            data = read_json(path)
        except (OSError, ValueError):
            statuses["UNREADABLE"] = statuses.get("UNREADABLE", 0) + 1
            continue
        key = str(data.get("status", "UNKNOWN")) if isinstance(data, dict) else "UNKNOWN"
        statuses[key] = statuses.get(key, 0) + 1
    return len(paths), statuses


def cmd_status(_args: argparse.Namespace) -> int:
    checkpoint_path = RUN_ROOT / "checkpoint.json"
    run_count, run_statuses = _count_receipts(RECEIPT_DIR)
    canary_count, canary_statuses = _count_receipts(CANARY_DIR / "receipts")
    payload = {
        "campaign_id": CAMPAIGN_ID,
        "model_key": MODEL_KEY,
        "run_root": str(RUN_ROOT),
        "run_root_exists": RUN_ROOT.is_dir(),
        "receipt_count": run_count,
        "status_counts": run_statuses,
        "canary_receipt_count": canary_count,
        "canary_status_counts": canary_statuses,
        "checkpoint": str(checkpoint_path) if checkpoint_path.is_file() else None,
    }
    if checkpoint_path.is_file():
        data = read_json(checkpoint_path)
        if isinstance(data, dict):
            payload["checkpoint_counts"] = data.get("counts")
            payload["checkpoint_stop_reason"] = data.get("stop_reason")
            payload["checkpoint_reset_hint"] = data.get("reset_hint")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    handlers = {
        "preflight": cmd_preflight,
        "probe": cmd_probe,
        "canary": cmd_canary,
        "run": cmd_run,
        "resume": cmd_resume,
        "status": cmd_status,
        "verify": cmd_verify,
        "canary-receipt": cmd_canary_receipt,
    }
    try:
        return handlers[args.command](args)
    except (PreflightError, PromptError, SelectionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["CANARY_MAX_PAGES", "PROBE_PROMPT", "cmd_verify", "main"]
