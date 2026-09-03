#!/usr/bin/env python3
"""Family-B performance v2: identity scaling separated from downstream recompile."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import platform
import random
import statistics
import sys
import tempfile
import time
import tracemalloc
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
HERE = Path(__file__).resolve().parent
PROTOCOL = HERE.parent / "PERFORMANCE_PROTOCOL_V2_2026-08-19.md"
SEED = 2026081909
IDENTITY_SCALES = (100, 250, 500, 750, 1000)
DOWNSTREAM_SCALES = (1000, 10000)
IDENTITY_WARMUPS = 1
IDENTITY_TRIALS = 5
DOWNSTREAM_WARMUPS = 3
DOWNSTREAM_TRIALS = 30
CHANGE_FRACTION = 0.01

from akc_cir.dependency import (  # noqa: E402
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)
from akc_cir.recompilation import (  # noqa: E402
    StructuralPolicy,
    plan_recompilation,
)
from akc_cir.semantic_diff import (  # noqa: E402
    ChangeKind,
    DiffLevel,
    DocumentShape,
    SemanticChange,
    SemanticDiff,
    UnitSnapshot,
    diff_documents,
)

SEM = frozenset({DependencyChannel.SEMANTIC})


def sha256_bytes(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_bytes(body.encode("utf-8"))


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * q
    lo = int(position)
    hi = min(lo + 1, len(ordered) - 1)
    weight = position - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


def summarize_ms(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "p50_ms": round(statistics.median(values), 6),
        "p95_ms": round(percentile(values, 0.95), 6),
        "mean_ms": round(statistics.fmean(values), 6),
        "samples_ms": [round(value, 6) for value in values],
    }


def timed(call: Callable[[], Any]) -> tuple[Any, float]:
    start = time.perf_counter_ns()
    result = call()
    return result, (time.perf_counter_ns() - start) / 1_000_000


def identity_documents(
    scale: int,
) -> tuple[list[UnitSnapshot], list[UnitSnapshot], DocumentShape]:
    rng = random.Random(SEED + scale)  # noqa: S311 -- deterministic benchmark
    changed_count = max(1, round(scale * CHANGE_FRACTION))
    changed = set(random.Random(SEED ^ scale).sample(range(scale), changed_count))  # noqa: S311
    before: list[UnitSnapshot] = []
    after: list[UnitSnapshot] = []
    ids = tuple(f"unit:{index:06d}" for index in range(scale))
    for index, logical_id in enumerate(ids):
        base = f"stable policy clause {index} token {rng.randrange(10**12)}"
        before.append(
            UnitSnapshot(
                logical_id=logical_id,
                text=base,
                document_path=(f"Section {index}",),
                anchor=f"section-{index}",
                explicit_identifier=logical_id,
            )
        )
        after.append(
            UnitSnapshot(
                logical_id=logical_id,
                text=base + (" revised semantic value" if index in changed else ""),
                document_path=(f"Section {index}",),
                anchor=f"section-{index}",
                explicit_identifier=logical_id,
            )
        )
    shape = DocumentShape(
        heading_path_set=frozenset((f"Section {index}",) for index in range(scale)),
        block_count=scale,
        unit_order=ids,
    )
    return before, after, shape


def identity_diff(
    before: list[UnitSnapshot],
    after: list[UnitSnapshot],
    shape: DocumentShape,
    scale: int,
) -> SemanticDiff:
    return diff_documents(
        before_sha256=canonical_sha256([unit.text for unit in before]),
        after_sha256=canonical_sha256([unit.text for unit in after]),
        level=DiffLevel.SEMANTIC,
        before_shape=shape,
        after_shape=shape,
        before_units=before,
        after_units=after,
        source=f"controlled-identity-scale:{scale}",
    )


def run_identity_scaling() -> dict[str, Any]:
    results: dict[str, Any] = {}
    medians: list[tuple[int, float]] = []
    for scale in IDENTITY_SCALES:
        before_units, after_units, document_shape = identity_documents(scale)
        identity_diff(before_units, after_units, document_shape, scale)
        samples: list[float] = []
        observed_changed: set[int] = set()
        for _ in range(IDENTITY_TRIALS):
            start = time.perf_counter_ns()
            diff = identity_diff(before_units, after_units, document_shape, scale)
            elapsed = (time.perf_counter_ns() - start) / 1_000_000
            samples.append(elapsed)
            observed_changed.add(len(diff.changed_logical_ids))
        summary = summarize_ms(samples)
        summary["observed_changed_logical_id_counts"] = sorted(observed_changed)
        summary["unit_count"] = scale
        results[str(scale)] = summary
        medians.append((scale, float(summary["p50_ms"])))
        print(f"identity scale {scale}: p50={summary['p50_ms']} ms")
        del before_units, after_units, document_shape
        gc.collect()

    xs = [math.log(scale) for scale, latency in medians if latency > 0]
    ys = [math.log(latency) for _scale, latency in medians if latency > 0]
    if len(xs) >= 2:
        mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
        denominator = sum((x - mean_x) ** 2 for x in xs)
        slope = numerator / denominator if denominator else None
    else:
        slope = None
    return {
        "scales": results,
        "empirical_loglog_slope": round(slope, 6) if slope is not None else None,
        "attempt1_10000_status": "MEMORY_ERROR_IN_IDENTITY_MATCHING_NOT_RERUN",
    }


def artifact_hash(artifact: str, values: list[str]) -> str:
    return canonical_sha256({"artifact": artifact, "values": values})


def downstream_context(scale: int) -> dict[str, Any]:
    before_values = [f"value-{index:06d}-before" for index in range(scale)]
    after_values = list(before_values)
    changed_count = max(1, round(scale * CHANGE_FRACTION))
    changed_indices = sorted(
        random.Random(SEED ^ (scale << 1)).sample(range(scale), changed_count)  # noqa: S311
    )
    for index in changed_indices:
        after_values[index] = before_values[index] + "-revised"
    unit_ids = [f"unit:{index:06d}" for index in range(scale)]
    section_artifacts = [f"artifact:section:{index:06d}" for index in range(scale)]
    index_artifact = "artifact:document-index"
    artifacts = [*section_artifacts, index_artifact]
    edges = [
        DependencyEdge(artifact, unit, EdgeType.DEPENDS_ON, channels=SEM)
        for artifact, unit in zip(section_artifacts, unit_ids, strict=True)
    ]
    edges.extend(
        DependencyEdge(index_artifact, unit, EdgeType.DEPENDS_ON, channels=SEM)
        for unit in unit_ids
    )
    graph = DependencyGraph(edges)
    changes = tuple(
        SemanticChange(
            kind=ChangeKind.MODIFIED_CLAIM,
            logical_id=unit_ids[index],
            before=before_values[index],
            after=after_values[index],
        )
        for index in changed_indices
    )
    diff = SemanticDiff(
        level=DiffLevel.SEMANTIC,
        content_changed=True,
        changes=changes,
        change_id="chg_perf_"
        + hashlib.sha256(str((scale, changed_indices)).encode()).hexdigest()[:24],
    )

    def build_all(values: list[str]) -> dict[str, str]:
        hashes = {
            artifact: artifact_hash(artifact, [values[index]])
            for index, artifact in enumerate(section_artifacts)
        }
        hashes[index_artifact] = artifact_hash(index_artifact, values)
        return hashes

    before_hashes = build_all(before_values)
    oracle = build_all(after_values)
    return {
        "scale": scale,
        "unit_ids": unit_ids,
        "before_values": before_values,
        "after_values": after_values,
        "section_artifacts": section_artifacts,
        "index_artifact": index_artifact,
        "artifacts": artifacts,
        "graph": graph,
        "diff": diff,
        "before_hashes": before_hashes,
        "oracle": oracle,
        "changed_indices": changed_indices,
        "build_all": build_all,
    }


def write_jsonl(path: Path, values: dict[str, str]) -> int:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for artifact in sorted(values):
            handle.write(
                json.dumps(
                    {"artifact_id": artifact, "sha256": values[artifact]},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
    return path.stat().st_size


def run_downstream_scale(scale: int) -> dict[str, Any]:
    context = downstream_context(scale)
    plan = plan_recompilation(
        diff=context["diff"],
        graph=context["graph"],
        artifacts=context["artifacts"],
        structural_policy=StructuralPolicy.PRECISE,
    )
    planned = set(plan.to_rebuild)
    section_index = {
        artifact: i for i, artifact in enumerate(context["section_artifacts"])
    }

    def selective_hashes() -> dict[str, str]:
        rebuilt: dict[str, str] = {}
        for artifact in planned:
            if artifact == context["index_artifact"]:
                rebuilt[artifact] = artifact_hash(artifact, context["after_values"])
            elif artifact in section_index:
                index = section_index[artifact]
                rebuilt[artifact] = artifact_hash(
                    artifact,
                    [context["after_values"][index]],
                )
        carried = {
            artifact: value
            for artifact, value in context["before_hashes"].items()
            if artifact not in planned
        }
        reconstructed = {**carried, **rebuilt}
        if reconstructed != context["oracle"]:
            missing = sorted(set(context["oracle"]) - set(reconstructed))[:5]
            divergent = sorted(
                key
                for key, value in context["oracle"].items()
                if reconstructed.get(key) != value
            )[:5]
            raise RuntimeError(
                f"selective divergence missing={missing} divergent={divergent}"
            )
        return rebuilt

    with tempfile.TemporaryDirectory(prefix=f"tavonel-perf-v2-{scale}-") as raw_temp:
        temp = Path(raw_temp)
        full_path = temp / "full.jsonl"
        selective_path = temp / "selective.jsonl"

        def full_call() -> tuple[int, int]:
            values = context["build_all"](context["after_values"])
            return len(values), write_jsonl(full_path, values)

        def selective_call() -> tuple[int, int]:
            current_plan = plan_recompilation(
                diff=context["diff"],
                graph=context["graph"],
                artifacts=context["artifacts"],
                structural_policy=StructuralPolicy.PRECISE,
            )
            if set(current_plan.to_rebuild) != planned:
                raise RuntimeError("recompilation plan changed across identical trials")
            rebuilt = selective_hashes()
            return len(rebuilt), write_jsonl(selective_path, rebuilt)

        for i in range(DOWNSTREAM_WARMUPS):
            (full_call if i % 2 == 0 else selective_call)()
            (selective_call if i % 2 == 0 else full_call)()

        samples: dict[str, list[dict[str, Any]]] = {"full": [], "selective": []}
        for trial in range(DOWNSTREAM_TRIALS):
            order = (
                ("full", "selective")
                if trial % 2 == 0
                else ("selective", "full")
            )
            calls = {"full": full_call, "selective": selective_call}
            for arm in order:
                (artifact_count, byte_count), elapsed = timed(calls[arm])
                samples[arm].append(
                    {
                        "trial": trial,
                        "elapsed_ms": round(elapsed, 6),
                        "artifacts_written": artifact_count,
                        "bytes_written": byte_count,
                    }
                )

        tracemalloc.start()
        full_call()
        _current, full_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        tracemalloc.start()
        selective_call()
        _current, selective_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    full_times = [row["elapsed_ms"] for row in samples["full"]]
    selective_times = [row["elapsed_ms"] for row in samples["selective"]]
    full_summary = summarize_ms(full_times)
    selective_summary = summarize_ms(selective_times)
    ratio = full_summary["p50_ms"] / selective_summary["p50_ms"]
    return {
        "scale": scale,
        "changed_units": len(context["changed_indices"]),
        "total_artifacts": len(context["artifacts"]),
        "planned_rebuild_artifacts": len(planned),
        "planned_rebuild_fraction": len(planned) / len(context["artifacts"]),
        "all_equivalent": True,
        "full": {**full_summary, "raw": samples["full"]},
        "selective": {**selective_summary, "raw": samples["selective"]},
        "p50_full_over_selective_ratio": round(ratio, 6),
        "full_python_tracemalloc_peak_bytes": full_peak,
        "selective_python_tracemalloc_peak_bytes": selective_peak,
        "median_full_bytes_written": int(
            statistics.median(row["bytes_written"] for row in samples["full"])
        ),
        "median_selective_bytes_written": int(
            statistics.median(row["bytes_written"] for row in samples["selective"])
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    identity = run_identity_scaling()
    downstream: dict[str, Any] = {}
    for scale in DOWNSTREAM_SCALES:
        result = run_downstream_scale(scale)
        downstream[str(scale)] = result
        print(
            f"downstream {scale}: ratio={result['p50_full_over_selective_ratio']}, "
            f"rebuild={result['planned_rebuild_fraction']:.4f}"
        )

    receipt: dict[str, Any] = {
        "schema": "tavonel.family-b-performance-v2.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol_sha256": file_sha256(PROTOCOL),
        "script_sha256": file_sha256(Path(__file__)),
        "python": sys.version,
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "seed": SEED,
        "identity_change_detection": identity,
        "downstream_selective_recompile": downstream,
        "attempt1_10k_identity_limit": "MemoryError; retained as current scalability limitation",
        "interpretation": (
            "Downstream selective-recompile timings exclude identity/change detection; "
            "they are not end-to-end update speedups."
        ),
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"receipt: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
