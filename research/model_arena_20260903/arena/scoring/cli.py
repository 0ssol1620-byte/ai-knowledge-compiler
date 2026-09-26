"""``python -m arena.scoring <qa|prepare|score|parse|provenance>``.

Order is not optional. ``qa`` must be green before ``prepare`` writes an
evaluator input, and ``prepare`` must have run before ``score`` launches an
evaluator. Each command refuses rather than working around a missing
predecessor.

``--dry-run`` prints the exact commands and paths a real run would use and
writes nothing. It is the way to read a run before committing hours of CPU to
it, and the way this lane is exercised in a build phase where no evaluator is
installed.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from arena.constants import BENCHMARK_KEYS, CAMPAIGN_ID
from arena.scoring import evaluators, jsonio, parsers, provenance, qa
from arena.scoring.errors import EvaluatorBlockedError, QaGateError, ScoringError
from arena.scoring.outputs import OutputSet, SourceIndex, load_output_set, load_source_index
from arena.scoring.paths import ScoringPaths

__all__ = ["build_parser", "main"]

SCORES_SCHEMA: Final = "tavonel.arena.model-scores.v1"
PREPARE_RECEIPT_SCHEMA: Final = "tavonel.arena.evaluator-input-receipt.v1"
RUN_LOG_SCHEMA: Final = "tavonel.arena.evaluator-run-log.v1"

_EXIT_OK: Final = 0
_EXIT_REFUSED: Final = 1
_EXIT_BLOCKED: Final = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arena.scoring", description=__doc__)
    parser.add_argument(
        "command", choices=("qa", "prepare", "score", "parse", "provenance")
    )
    parser.add_argument("--model", help="model key whose frozen outputs are scored")
    parser.add_argument("--variant", help="TAVONEL variant whose composite outputs are scored")
    parser.add_argument(
        "--benchmark",
        choices=(*BENCHMARK_KEYS, "all"),
        default="all",
        help="benchmark to act on (default: every benchmark present in the output set)",
    )
    parser.add_argument("--lane", choices=("main", "historical"), default="main")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    parser.add_argument("--root", type=Path, help="campaign root (default: the namespace root)")
    parser.add_argument("--repo-root", type=Path, help="repository root, for gt_paths")
    parser.add_argument("--gt-path", help="override the ground-truth path for this benchmark")
    parser.add_argument("--clone-source", help="override the evaluator clone source")
    parser.add_argument("--timeout", type=int, help="watchdog seconds per evaluator step")
    parser.add_argument("--python", default=sys.executable, help="interpreter for the evaluator")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument(
        "--sample-size", type=int, help="provenance: walk only the first N pages"
    )
    return parser


def _paths(args: argparse.Namespace) -> ScoringPaths:
    default = ScoringPaths.default()
    return ScoringPaths(
        root=args.root or default.root,
        repo_root=args.repo_root or default.repo_root,
    )


def _benchmarks(args: argparse.Namespace, output_set: OutputSet) -> tuple[str, ...]:
    if args.benchmark != "all":
        return (args.benchmark,)
    present = output_set.benchmarks
    if not present:
        raise ScoringError(
            f"the output set {output_set.key!r} carries no rows for any known benchmark"
        )
    return present


# ---------------------------------------------------------------------------
# qa
# ---------------------------------------------------------------------------


def _cmd_qa(args: argparse.Namespace, paths: ScoringPaths) -> int:
    output_set = load_output_set(paths, model=args.model, variant=args.variant)
    source_index = load_source_index(paths)
    exit_code = _EXIT_OK
    for benchmark in _benchmarks(args, output_set):
        if args.dry_run:
            print(
                f"[dry-run] would run the section 44 gate for {output_set.key}/{benchmark} "
                f"over {len(output_set.for_benchmark(benchmark))} rows and write "
                f"{paths.qa_report(output_set.key, benchmark)}"
            )
            continue
        report = qa.run_qa_gate(paths, output_set, benchmark, source_index=source_index)
        path, digest = qa.write_qa_report(paths, report)
        state = "PASS" if report.passed else "FAIL"
        print(f"{output_set.key}/{benchmark}: {state} -> {path} ({digest})")
        for check in report.checks:
            print(f"  [{check.state:<15}] {check.name}: {check.detail}")
        if not report.passed:
            exit_code = _EXIT_REFUSED
    return exit_code


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------


def _resolve_lane(
    args: argparse.Namespace, paths: ScoringPaths, benchmark: str
) -> evaluators.EvaluatorLane:
    return evaluators.resolve_lane(
        paths, benchmark, args.lane, clone_source=args.clone_source
    )


def _gt_path(args: argparse.Namespace, paths: ScoringPaths, benchmark: str) -> Path:
    return evaluators.resolve_gt_path(
        paths,
        benchmark,
        evaluators.registry_gt_paths(paths, benchmark),
        override=args.gt_path,
    )


#: A dry run prints commands; it must not have to resolve ground truth to do
#: so, and it must not quietly substitute a path that does not exist. The
#: placeholder is obviously not a path, and the warning says why it is there.
_GT_PLACEHOLDER: Final = Path("<GT_PATH-unresolved>")


def _gt_path_for_plan(
    args: argparse.Namespace, paths: ScoringPaths, benchmark: str
) -> tuple[Path, str | None]:
    try:
        return _gt_path(args, paths, benchmark), None
    except ScoringError as error:
        return _GT_PLACEHOLDER, str(error)


def _cmd_prepare(args: argparse.Namespace, paths: ScoringPaths) -> int:
    output_set = load_output_set(paths, model=args.model, variant=args.variant)
    source_index = load_source_index(paths)
    for benchmark in _benchmarks(args, output_set):
        rows = output_set.for_benchmark(benchmark)
        input_root = paths.evaluator_input(output_set.key, benchmark)
        if args.dry_run:
            print(
                f"[dry-run] would lay {len(rows)} {benchmark} pages out under {input_root} "
                f"({evaluators.LAYOUT_REVISION})"
            )
            continue
        qa.require_qa_passed(paths, output_set.key, benchmark)
        result = evaluators.prepare_inputs(
            paths,
            key=output_set.key,
            benchmark=benchmark,
            rows=rows,
            source_index=source_index,
            pipeline_name=f"tavonel-arena-{output_set.key}",
        )
        receipt: dict[str, Any] = {
            "schema": PREPARE_RECEIPT_SCHEMA,
            "campaign_id": CAMPAIGN_ID,
            "key": output_set.key,
            "prepared_at": jsonio.utc_now_iso(),
            "files_sha256": dict(result.files_sha256),
            **result.to_record(),
        }
        if benchmark == "omnidoc":
            config = evaluators.omnidoc_config(
                gt_path=_gt_path(args, paths, benchmark),
                prediction_dir=input_root / "markdown",
            )
            config_path = paths.evaluator_raw(output_set.key, benchmark) / "omnidoc-config.yaml"
            receipt["config_path"] = str(config_path)
            receipt["config_sha256"] = jsonio.write_text_atomic(config_path, config)
        if benchmark == "olmocr":
            receipt["bench_root"] = evaluators.stage_olmocr_bench_root(
                input_root, _gt_path(args, paths, benchmark)
            )
        path = input_root / "_prepare-receipt.json"
        digest = jsonio.write_json_atomic(path, receipt)
        print(
            f"{output_set.key}/{benchmark}: wrote {result.written} evaluator inputs "
            f"({len(result.skipped)} skipped) -> {path} ({digest})"
        )
        for note in result.notes:
            print(f"  note: {note}")
    return _EXIT_OK


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------


def _steps_for(
    args: argparse.Namespace,
    paths: ScoringPaths,
    lane: evaluators.EvaluatorLane,
    output_set: OutputSet,
    benchmark: str,
    gt_path: Path,
) -> tuple[evaluators.EvaluatorStep, ...]:
    return evaluators.build_steps(
        lane,
        input_root=paths.evaluator_input(output_set.key, benchmark),
        raw_root=paths.evaluator_raw(output_set.key, benchmark),
        gt_path=gt_path,
        candidate=output_set.key,
        python_executable=args.python,
        timeout_seconds=args.timeout,
        max_workers=args.max_workers,
    )


def _print_plan(
    lane: evaluators.EvaluatorLane, steps: Sequence[evaluators.EvaluatorStep]
) -> None:
    print(f"[dry-run] evaluator lane {lane.benchmark}/{lane.lane} @ {lane.revision}")
    print(f"[dry-run]   revision source: {lane.revision_source}")
    for note in lane.notes:
        print(f"[dry-run]   note: {note}")
    for command in evaluators.checkout_commands(lane):
        print(f"[dry-run]   $ {' '.join(command)}")
    print(f"[dry-run]   setup ({lane.setup_note}):")
    for command in lane.setup_commands:
        print(f"[dry-run]   $ (cd {lane.checkout_dir}) {' '.join(command)}")
    for step in steps:
        print(f"[dry-run]   step {step.name} (watchdog {step.timeout_seconds}s):")
        print(f"[dry-run]   $ (cd {step.cwd}) {' '.join(step.argv)}")


def _ensure_checkout(lane: evaluators.EvaluatorLane) -> list[dict[str, Any]]:
    """Materialise the pinned checkout. ``benchmark/cache`` is only read."""

    if jsonio.io_path(lane.checkout_dir / ".git").exists():
        return [{"skipped": "checkout already exists", "path": str(lane.checkout_dir)}]
    jsonio.io_path(lane.checkout_dir).parent.mkdir(parents=True, exist_ok=True)
    steps = [
        evaluators.EvaluatorStep(
            name=f"checkout-{index}",
            argv=command,
            cwd=lane.checkout_dir.parent,
            timeout_seconds=1800,
        )
        for index, command in enumerate(evaluators.checkout_commands(lane))
    ]
    return evaluators.run_steps(steps, lane.checkout_dir.parent / "_checkout-logs")


def _cmd_score(args: argparse.Namespace, paths: ScoringPaths) -> int:
    output_set = load_output_set(paths, model=args.model, variant=args.variant)
    source_index = load_source_index(paths)
    exit_code = _EXIT_OK
    for benchmark in _benchmarks(args, output_set):
        lane = _resolve_lane(args, paths, benchmark)
        if args.dry_run:
            gt_path, warning = _gt_path_for_plan(args, paths, benchmark)
            if warning is not None:
                print(f"[dry-run]   ground truth unresolved: {warning}")
            _print_plan(lane, _steps_for(args, paths, lane, output_set, benchmark, gt_path))
            continue
        gt_path = _gt_path(args, paths, benchmark)
        steps = _steps_for(args, paths, lane, output_set, benchmark, gt_path)
        qa.require_qa_passed(paths, output_set.key, benchmark)
        raw_root = paths.evaluator_raw(output_set.key, benchmark)
        prov = provenance.build_provenance(paths, output_set, lane)
        try:
            checkout = _ensure_checkout(lane)
            records = evaluators.run_steps(steps, raw_root)
        except EvaluatorBlockedError as error:
            summary = parsers.blocked_from_error(
                error, key=output_set.key, benchmark=benchmark, provenance=prov
            )
            jsonio.write_json_atomic(paths.summary(output_set.key, benchmark), summary)
            print(f"{output_set.key}/{benchmark}: EVALUATOR_BLOCKED - {error}")
            exit_code = _EXIT_BLOCKED
            continue
        jsonio.write_json_atomic(
            raw_root / "run-log.json",
            {
                "schema": RUN_LOG_SCHEMA,
                "campaign_id": CAMPAIGN_ID,
                "key": output_set.key,
                "benchmark": benchmark,
                "lane": lane.to_record(),
                "checkout": checkout,
                "steps": records,
                "finished_at": jsonio.utc_now_iso(),
            },
        )
        exit_code = max(
            exit_code, _parse_and_write(paths, output_set, lane, benchmark, source_index)
        )
    return exit_code


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------


def _parse_and_write(
    paths: ScoringPaths,
    output_set: OutputSet,
    lane: evaluators.EvaluatorLane,
    benchmark: str,
    source_index: SourceIndex,
) -> int:
    qa_document = qa.require_qa_passed(paths, output_set.key, benchmark)
    qa_sha = jsonio.canonical_sha256(qa_document)
    prov = provenance.build_provenance(paths, output_set, lane, qa_report_sha256=qa_sha)
    raw_root = paths.evaluator_raw(output_set.key, benchmark)
    try:
        parsed = parsers.parse_raw(benchmark, raw_root, source_index=source_index)
    except EvaluatorBlockedError as error:
        summary = parsers.blocked_from_error(
            error,
            key=output_set.key,
            benchmark=benchmark,
            provenance=prov,
            qa_report_sha256=qa_sha,
        )
        jsonio.write_json_atomic(paths.summary(output_set.key, benchmark), summary)
        _update_scores_json(paths, output_set.key, benchmark, summary)
        print(f"{output_set.key}/{benchmark}: EVALUATOR_BLOCKED - {error}")
        return _EXIT_BLOCKED
    summary = parsers.build_summary(
        parsed, key=output_set.key, provenance=prov, qa_report_sha256=qa_sha
    )
    summary_path = paths.summary(output_set.key, benchmark)
    digest = jsonio.write_json_atomic(summary_path, summary)
    per_case_path = paths.per_case(output_set.key, benchmark)
    jsonio.write_jsonl_atomic(per_case_path, parsed.per_case)
    _update_scores_json(paths, output_set.key, benchmark, summary)
    print(
        f"{output_set.key}/{benchmark}: SCORED -> {summary_path} ({digest}); "
        f"{len(parsed.per_case)} per-case rows"
    )
    for item in parsed.missing_metrics:
        print(f"  missing metric {item.name}: {item.reason}")
    if parsed.unjoined_locations:
        print(
            f"  {len(parsed.unjoined_locations)} evaluator locations could not be joined "
            "to a case_key and were not turned into rows"
        )
    return _EXIT_OK


def _update_scores_json(
    paths: ScoringPaths, key: str, benchmark: str, summary: Mapping[str, Any]
) -> None:
    path = paths.scores_json(key)
    document: dict[str, Any] = {
        "schema": SCORES_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "key": key,
        "benchmarks": {},
    }
    if jsonio.io_path(path).is_file():
        loaded = jsonio.read_json(path)
        if isinstance(loaded, Mapping):
            existing = loaded.get("benchmarks")
            if isinstance(existing, Mapping):
                document["benchmarks"] = dict(existing)
    document["benchmarks"][benchmark] = {
        "status": summary.get("status"),
        "summary_path": str(paths.summary(key, benchmark)),
        "summary_sha256": jsonio.canonical_sha256(summary),
        "evaluator_revision": (
            summary.get("provenance", {}).get("evaluator_revision")
            if isinstance(summary.get("provenance"), Mapping)
            else None
        ),
        "evaluator_lane": (
            summary.get("provenance", {}).get("evaluator_lane")
            if isinstance(summary.get("provenance"), Mapping)
            else None
        ),
    }
    document["updated_at"] = jsonio.utc_now_iso()
    jsonio.write_json_atomic(path, document)


def _cmd_parse(args: argparse.Namespace, paths: ScoringPaths) -> int:
    output_set = load_output_set(paths, model=args.model, variant=args.variant)
    source_index = load_source_index(paths)
    exit_code = _EXIT_OK
    for benchmark in _benchmarks(args, output_set):
        lane = _resolve_lane(args, paths, benchmark)
        if args.dry_run:
            print(
                f"[dry-run] would parse {paths.evaluator_raw(output_set.key, benchmark)} "
                f"into {paths.summary(output_set.key, benchmark)} and "
                f"{paths.per_case(output_set.key, benchmark)}"
            )
            continue
        exit_code = max(
            exit_code, _parse_and_write(paths, output_set, lane, benchmark, source_index)
        )
    return exit_code


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------


def _cmd_provenance(args: argparse.Namespace, paths: ScoringPaths) -> int:
    output_set = load_output_set(paths, model=args.model, variant=args.variant)
    source_index = load_source_index(paths)
    exit_code = _EXIT_OK
    for benchmark in _benchmarks(args, output_set):
        lane = _resolve_lane(args, paths, benchmark)
        if args.dry_run:
            print(
                f"[dry-run] would walk score -> evaluator {lane.revision} -> normalized "
                f"-> raw -> receipt -> revision -> image -> source sha for "
                f"{output_set.key}/{benchmark}"
            )
            continue
        report = provenance.verify_chain(
            paths,
            output_set,
            lane,
            benchmark,
            source_index=source_index,
            sample_size=args.sample_size,
        )
        path, digest = provenance.write_chain(paths, report)
        state = "PASS" if report.passed else "FAIL"
        print(
            f"{output_set.key}/{benchmark}: chain {state} "
            f"({report.ok}/{report.checked} pages) -> {path} ({digest})"
        )
        if not report.passed:
            exit_code = _EXIT_REFUSED
            for chain in report.failures[:5]:
                broken = [step["step"] for step in chain.steps if not step["ok"]]
                print(f"  {chain.case_key}: broken at {broken}")
    return exit_code


_COMMANDS = {
    "qa": _cmd_qa,
    "prepare": _cmd_prepare,
    "score": _cmd_score,
    "parse": _cmd_parse,
    "provenance": _cmd_provenance,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = _paths(args)
    try:
        return _COMMANDS[args.command](args, paths)
    except QaGateError as error:
        print(f"refused: {error}", file=sys.stderr)
        return _EXIT_REFUSED
    except ScoringError as error:
        print(f"error: {error}", file=sys.stderr)
        return _EXIT_REFUSED
