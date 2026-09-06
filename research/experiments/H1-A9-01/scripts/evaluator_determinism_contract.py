#!/usr/bin/env python3
"""Prove the corrected evaluator returns the same score for the same bytes.

The defect this exists to prevent: the frozen evaluator decided *which matching
algorithm* to run from a wall-clock timeout, so identical predictions could be
scored two different ways depending on machine load. Measured on the A9 holdout,
15 byte-identical pages scored differently across two evaluations and 5 flipped
the severe label.

That alone would be a limitation. What made it a defect in the endpoint is that
the fallback was **not independent of the thing being measured**: pages the gate
abstained on fell back at 12.9% against 3.7% for accepted pages, Fisher exact
p = 0.0005. Noise correlated with the comparison does not merely attenuate an
association, so the usual reassurance did not apply and the evidence had to be
re-measured with a corrected instrument.

This runs the same predictions through the corrected evaluator several times
under conditions that previously changed the answer -- different worker counts,
different page order, and repetition under whatever load the machine happens to
be under -- and requires that the per-page scores and the derived severe labels
are **bit-identical every time**, compared by hash rather than by tolerance.

A tolerance would defeat the purpose. The claim is not "close enough", it is
"the same function of the same input".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SEVERE = 0.10
ARTIFACTS = (
    "text_block_per_page_edit.json",
    "display_formula_per_page_edit.json",
    "reading_order_per_page_edit.json",
)


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def page_scores(artifact_dir: Path) -> dict[str, dict[str, float]]:
    """Every per-page metric the evaluator emitted, keyed by page."""
    merged: dict[str, dict[str, float]] = {}
    for name in ARTIFACTS:
        path = artifact_dir / name
        if not path.is_file():
            continue
        metric = name.removesuffix("_per_page_edit.json")
        for page, value in json.loads(path.read_text(encoding="utf-8")).items():
            merged.setdefault(page, {})[metric] = float(value)
    return merged


def severe_labels(scores: dict[str, dict[str, float]]) -> dict[str, bool]:
    """The endpoint's own label, which is what actually has to be stable."""
    return {
        page: metrics["text_block"] > SEVERE
        for page, metrics in scores.items()
        if "text_block" in metrics
    }



def structural_fallback_evidence(artifact_dir: Path) -> dict[str, Any]:
    """What the evaluator itself recorded about the wall-clock paths.

    Counting `[match-timeout]` lines in captured stdout was the original check.
    It is weaker than it looks: it depends on a capture stream staying healthy
    for the whole run, and on this repository's log format not changing. The
    evaluator also writes `stage_execution.json`, which states the timeout
    values actually in force and the fallback counts it actually took.

    Both are kept. The log count catches a fallback that fired without being
    counted; this catches a log that went missing.
    """
    path = artifact_dir / "stage_execution.json"
    if not path.is_file():
        return {"available": False}
    page_match = json.loads(path.read_text(encoding="utf-8")).get("page_match", {})
    fallbacks = page_match.get("fallbacks", {})
    return {
        "available": True,
        "workers": page_match.get("workers"),
        "page_count": page_match.get("page_count"),
        "match_timeout_sec": page_match.get("match_timeout_sec"),
        "quick_match_truncated_timeout_sec": page_match.get(
            "quick_match_truncated_timeout_sec"
        ),
        "quick_match_timeout_fallbacks": fallbacks.get("quick_match_timeout", {}).get(
            "count"
        ),
        "page_timeout_fallbacks": fallbacks.get("page_timeout", {}).get("count"),
    }

def run_once(
    *,
    evaluator_dir: Path,
    ground_truth: Path,
    predictions_root: Path,
    source_manifest: Path,
    output_dir: Path,
    workers: int,
    python: Path,
    harness: Path,
    reuse_existing: bool = False,
) -> tuple[dict[str, Any], float]:
    started = time.time()
    artifacts = output_dir / "repeat-1" / "official-artifacts"
    if reuse_existing and (artifacts / "text_block_per_page_edit.json").is_file():
        # Regenerating the receipt from runs that already completed. This never
        # skips work that has not been done -- it requires the scored artifacts
        # to be present -- and exists so the receipt can be improved without
        # spending hours recomputing identical scores.
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    else:
        completed = subprocess.run(  # noqa: S603
            [
                str(python), str(harness),
                "--evaluator-dir", str(evaluator_dir),
                "--ground-truth", str(ground_truth),
                "--predictions-root", str(predictions_root),
                "--source-manifest", str(source_manifest),
                "--output-dir", str(output_dir),
                "--repeats", "1",
                "--workers", str(workers),
                "--deterministic-matching",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    if completed.returncode != 0:
        raise SystemExit(
            f"evaluation failed (workers={workers}):\n{completed.stdout[-3000:]}\n"
            f"{completed.stderr[-3000:]}"
        )
    scores = page_scores(artifacts)
    labels = severe_labels(scores)
    stdout_log = output_dir / "repeat-1" / "stdout.log"
    log_text = (
        stdout_log.read_text(encoding="utf-8", errors="replace")
        if stdout_log.is_file()
        else ""
    )
    return (
        {
            "workers": workers,
            "pages_scored": len(scores),
            "severe_pages": sum(1 for flag in labels.values() if flag),
            "per_page_score_hash": canonical_sha256(scores),
            "severe_label_hash": canonical_sha256(labels),
            # If either of these is non-zero the correction did not take effect.
            "timeout_fallback_lines_in_log": log_text.count("[match-timeout]")
            + log_text.count("[quick-match-timeout]"),
            "evaluator_recorded": structural_fallback_evidence(artifacts),
            "scores": scores,
            "labels": labels,
        },
        time.time() - started,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluator-dir", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--predictions-root", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument(
        "--harness",
        type=Path,
        default=Path("benchmark/runpod_eval/evaluate_omnidoc_repeats.py"),
    )
    parser.add_argument(
        "--workers",
        type=int,
        nargs="+",
        default=[4, 1, 8],
        help="one evaluation per value; varying this varies the parallelism",
    )
    parser.add_argument(
        "--also-reversed-order",
        action="store_true",
        help=(
            "add one more evaluation with the ground-truth page order reversed. "
            "Page order changes which pages share a worker and in what sequence, "
            "which is a different axis from the worker count."
        ),
    )
    parser.add_argument(
        "--orders",
        nargs="+",
        choices=["forward", "reversed"],
        help=(
            "page order per worker count, zipped with --workers. Pairing the two "
            "axes covers repetition, parallelism and ordering in one evaluation "
            "each instead of the cross product, which matters when a single "
            "evaluation of the full corpus takes hours."
        ),
    )
    parser.add_argument(
        "--reuse-existing-runs",
        action="store_true",
        help=(
            "regenerate the receipt from evaluations whose scored artifacts are "
            "already on disk instead of recomputing them. Refuses to skip any "
            "run whose artifacts are absent, so it cannot turn missing work into "
            "a pass."
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def reversed_ground_truth() -> Path:
        target = args.work_dir.resolve() / "ground-truth-reversed.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            pages = json.loads(args.ground_truth.resolve().read_text(encoding="utf-8"))
            target.write_text(
                json.dumps(list(reversed(pages)), ensure_ascii=False), encoding="utf-8"
            )
        return target

    if args.orders:
        if len(args.orders) != len(args.workers):
            raise SystemExit("--orders must have one entry per --workers entry")
        plan = [
            (
                workers,
                reversed_ground_truth() if order == "reversed" else args.ground_truth.resolve(),
                order,
            )
            for workers, order in zip(args.workers, args.orders, strict=True)
        ]
    else:
        plan = [
            (workers, args.ground_truth.resolve(), "forward") for workers in args.workers
        ]
    if args.also_reversed_order:
        plan.append((args.workers[0], reversed_ground_truth(), "reversed"))

    runs: list[dict[str, Any]] = []
    for index, (workers, ground_truth, order) in enumerate(plan):
        output_dir = args.work_dir.resolve() / f"run-{index}-w{workers}-{order}"
        result, elapsed = run_once(
            evaluator_dir=args.evaluator_dir.resolve(),
            ground_truth=ground_truth,
            predictions_root=args.predictions_root.resolve(),
            source_manifest=args.source_manifest.resolve(),
            output_dir=output_dir,
            workers=workers,
            python=args.python.resolve(),
            harness=args.harness.resolve(),
            reuse_existing=args.reuse_existing_runs,
        )
        result["elapsed_seconds"] = elapsed
        result["page_order"] = order
        runs.append(result)
        print(
            f"run {index}: workers={workers} order={order} "
            f"pages={result['pages_scored']} "
            f"severe={result['severe_pages']} "
            f"fallbacks={result['timeout_fallback_lines_in_log']} "
            f"{elapsed:.0f}s"
        )

    reference = runs[0]
    score_hashes = {run["per_page_score_hash"] for run in runs}
    label_hashes = {run["severe_label_hash"] for run in runs}

    disagreements: list[dict[str, Any]] = []
    for run in runs[1:]:
        for page, metrics in reference["scores"].items():
            other = run["scores"].get(page)
            if other != metrics:
                disagreements.append(
                    {
                        "page": page,
                        "reference_workers": reference["workers"],
                        "other_workers": run["workers"],
                        "reference": metrics,
                        "other": other,
                    }
                )

    fallbacks = sum(run["timeout_fallback_lines_in_log"] for run in runs)
    recorded = [run["evaluator_recorded"] for run in runs]
    structural_fallbacks = sum(
        (row.get("quick_match_timeout_fallbacks") or 0)
        + (row.get("page_timeout_fallbacks") or 0)
        for row in recorded
        if row.get("available")
    )
    # If a run cannot show its own record, its silence is not evidence.
    unverified = [
        run["workers"] for run in runs if not run["evaluator_recorded"].get("available")
    ]
    timeouts_still_set = [
        {
            "workers": row.get("workers"),
            "match_timeout_sec": row.get("match_timeout_sec"),
            "quick_match_truncated_timeout_sec": row.get(
                "quick_match_truncated_timeout_sec"
            ),
        }
        for row in recorded
        if row.get("available")
        and (
            row.get("match_timeout_sec") is not None
            or row.get("quick_match_truncated_timeout_sec") is not None
        )
    ]
    deterministic = (
        len(score_hashes) == 1 and len(label_hashes) == 1 and not disagreements
    )

    receipt = {
        "schema": "tavonel.a9-evaluator-determinism-contract.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "evaluator_dir": str(args.evaluator_dir.resolve()),
        "predictions_root": str(args.predictions_root.resolve()),
        "evaluations": len(runs),
        "worker_counts": args.workers,
        "page_order_variants": sorted({run["page_order"] for run in runs}),
        "pages_scored": reference["pages_scored"],
        "distinct_per_page_score_hashes": len(score_hashes),
        "distinct_severe_label_hashes": len(label_hashes),
        "per_page_score_hash": reference["per_page_score_hash"],
        "severe_label_hash": reference["severe_label_hash"],
        "page_level_disagreements": disagreements,
        "timeout_fallback_lines_across_all_runs": fallbacks,
        "evaluator_recorded_fallbacks_across_all_runs": structural_fallbacks,
        "runs_that_could_not_show_their_own_record": unverified,
        "runs_with_a_wall_clock_timeout_still_set": timeouts_still_set,
        "deterministic": deterministic,
        "runs": [
            {k: v for k, v in run.items() if k not in {"scores", "labels"}}
            for run in runs
        ],
        "what_is_being_asserted": (
            "identical prediction bytes produce identical per-page scores and "
            "identical severe labels under every parallelism tested, compared by "
            "hash rather than by tolerance. A tolerance would defeat the point: "
            "the claim is not that the answers are close but that scoring is a "
            "function of its input."
        ),
        "why_two_sources_for_the_same_count": (
            "the log count depends on a capture stream staying healthy for the "
            "whole run and on the log format not changing; the evaluator's own "
            "stage_execution.json states the timeout values in force and the "
            "fallbacks it took. Each covers the other's blind spot, and a run "
            "that cannot produce its own record is treated as unverified rather "
            "than as clean."
        ),
        "why_zero_fallbacks_is_part_of_the_contract": (
            "a single fallback line means a wall-clock path is still live, and "
            "the run could have gone the other way on a busier machine. The "
            "hashes agreeing while a fallback fired would be luck, not "
            "determinism."
        ),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)

    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"\ndistinct score hashes: {len(score_hashes)}  "
          f"distinct label hashes: {len(label_hashes)}  "
          f"fallback lines: {fallbacks}")
    print(f"deterministic: {deterministic}")
    print(f"receipt: {args.output.resolve()}")

    if not deterministic:
        for row in disagreements[:20]:
            print(f"  DISAGREE {row['page']}: {row['reference']} vs {row['other']}")
        raise SystemExit(
            "the corrected evaluator is not deterministic; it must not be used "
            "to re-score the holdout until it is"
        )
    if fallbacks or structural_fallbacks:
        raise SystemExit(
            f"{fallbacks} timeout-fallback log lines and {structural_fallbacks} "
            "evaluator-recorded fallbacks: a wall-clock path is still live even "
            "though the hashes happened to agree"
        )
    if unverified:
        raise SystemExit(
            f"{len(unverified)} run(s) produced no stage_execution.json, so their "
            "zero-fallback claim rests on log parsing alone"
        )
    if timeouts_still_set:
        raise SystemExit(
            "a run reported a wall-clock timeout still in force: "
            f"{timeouts_still_set}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
