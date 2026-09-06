#!/usr/bin/env python3
"""Measured Family-B compute/latency benchmark.

See PERFORMANCE_PROTOCOL_2026-08-19.md. Real-revision results and deterministic
1k/10k controlled scaling are emitted as separate strata and are never pooled.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
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
PROTOCOL = HERE.parent / "PERFORMANCE_PROTOCOL_2026-08-19.md"
PRECISE = HERE / "precise_structural_benchmark.py"

from akc_cir.dependency import (  # noqa: E402
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)
from akc_cir.identity import normalize_text_for_identity  # noqa: E402
from akc_cir.recompilation import (  # noqa: E402
    StructuralPolicy,
    content_hash,
    plan_recompilation,
    verify_equivalence,
)
from akc_cir.semantic_diff import (  # noqa: E402
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    diff_documents,
)

SEED = 2026081906
SCALES = (1000, 10000)
CHANGE_FRACTION = 0.01
WARMUPS = 3
TRIALS = 30
SEM = frozenset({DependencyChannel.SEMANTIC})


def sha256_bytes(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_bytes(body.encode("utf-8"))


def load_precise() -> Any:
    spec = importlib.util.spec_from_file_location("family_b_precise_for_perf", PRECISE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load precise benchmark module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def artifact_hashes_subset(
    dependencies: dict[str, tuple[str, ...]],
    units: list[UnitSnapshot],
    selected: set[str] | None = None,
) -> dict[str, str]:
    by_id = {unit.logical_id: unit.text for unit in units}
    result: dict[str, str] = {}
    for artifact, logical_ids in dependencies.items():
        if selected is not None and artifact not in selected:
            continue
        payload = [
            {
                "logical_id": logical_id,
                "semantic_text": normalize_text_for_identity(by_id.get(logical_id, "<ABSENT>")),
            }
            for logical_id in logical_ids
        ]
        result[artifact] = content_hash(payload)
    return result


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


def timed(call: Callable[[], tuple[Any, int]]) -> tuple[Any, int, float]:
    start = time.perf_counter_ns()
    result, bytes_written = call()
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    return result, bytes_written, elapsed_ms


def memory_probe(call: Callable[[], Any]) -> int:
    tracemalloc.start()
    try:
        call()
        _current, peak = tracemalloc.get_traced_memory()
        return peak
    finally:
        tracemalloc.stop()


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    times = [float(row["elapsed_ms"]) for row in samples]
    return {
        "n": len(samples),
        "p50_ms": round(statistics.median(times), 6),
        "p95_ms": round(percentile(times, 0.95), 6),
        "mean_ms": round(statistics.fmean(times), 6),
        "bytes_written_median": int(statistics.median(row["bytes_written"] for row in samples)),
        "samples": samples,
    }


def declared_semantic_graph(dependencies: dict[str, tuple[str, ...]]) -> DependencyGraph:
    return DependencyGraph(
        DependencyEdge(artifact, unit, EdgeType.DEPENDS_ON, channels=SEM)
        for artifact, units in dependencies.items()
        for unit in units
    )


def real_pair_context(
    precise: Any,
    adapter: Any,
    corpus: Path,
    record: dict[str, Any],
) -> dict[str, Any] | None:
    before = precise.read_side(adapter, corpus, record, "before")
    after = precise.read_side(adapter, corpus, record, "after")
    before_units, before_shape = adapter.section_units(before)
    after_units, after_shape = adapter.section_units(after)
    if not before_units or not after_units:
        return None
    _default, inventory, dependencies = adapter.make_graph_and_inventory(
        record["title"], before_units, after_units
    )
    graph = declared_semantic_graph(dependencies)
    before_hashes = artifact_hashes_subset(dependencies, before_units)
    full_oracle = artifact_hashes_subset(dependencies, after_units)
    return {
        "title": record["title"],
        "before": before,
        "after": after,
        "before_units": before_units,
        "after_units": after_units,
        "before_shape": before_shape,
        "after_shape": after_shape,
        "inventory": inventory,
        "dependencies": dependencies,
        "graph": graph,
        "before_hashes": before_hashes,
        "full_oracle": full_oracle,
    }


def build_plan(context: dict[str, Any]) -> Any:
    diff = diff_documents(
        before_sha256=context["before_sha256"],
        after_sha256=context["after_sha256"],
        level=DiffLevel.SEMANTIC,
        before_shape=context["before_shape"],
        after_shape=context["after_shape"],
        before_units=context["before_units"],
        after_units=context["after_units"],
        source=context["source"],
    )
    return plan_recompilation(
        diff=diff,
        graph=context["graph"],
        artifacts=context["inventory"],
        structural_policy=StructuralPolicy.PRECISE,
    )


def arm_calls(
    context: dict[str, Any],
    temp: Path,
) -> tuple[Callable[[], tuple[Any, int]], Callable[[], tuple[Any, int]]]:
    full_path = temp / "full.jsonl"
    selective_path = temp / "selective.jsonl"

    def full() -> tuple[dict[str, str], int]:
        hashes = artifact_hashes_subset(context["dependencies"], context["after_units"])
        return hashes, write_jsonl(full_path, hashes)

    def selective() -> tuple[dict[str, str], int]:
        plan = build_plan(context)
        planned = set(plan.to_rebuild)
        rebuilt = artifact_hashes_subset(context["dependencies"], context["after_units"], planned)
        carried = {
            artifact: context["before_hashes"][artifact]
            for artifact in context["inventory"]
            if artifact not in planned
        }
        equivalence = verify_equivalence(
            full_rebuild=context["full_oracle"],
            selective_rebuild=rebuilt,
            carried_over=carried,
            plan=plan,
        )
        if not equivalence.equivalent:
            raise RuntimeError(
                f"selective result diverged: stale={equivalence.stale_left_behind}, "
                f"diverged={equivalence.diverged}"
            )
        return {**carried, **rebuilt}, write_jsonl(selective_path, rebuilt)

    return full, selective


def build_only_calls(
    context: dict[str, Any],
    temp: Path,
) -> tuple[Callable[[], tuple[Any, int]], Callable[[], tuple[Any, int]]]:
    """Calls that exclude diff/planning/verification overhead.

    The selective plan is prepared before the timer, exactly as frozen in the
    performance protocol. This isolates the artifact-build cost from the
    end-to-end change-handling cost measured by :func:`arm_calls`.
    """
    plan = build_plan(context)
    planned = set(plan.to_rebuild)
    full_path = temp / "full-build-only.jsonl"
    selective_path = temp / "selective-build-only.jsonl"

    def full() -> tuple[dict[str, str], int]:
        hashes = artifact_hashes_subset(context["dependencies"], context["after_units"])
        return hashes, write_jsonl(full_path, hashes)

    def selective() -> tuple[dict[str, str], int]:
        hashes = artifact_hashes_subset(
            context["dependencies"],
            context["after_units"],
            planned,
        )
        return hashes, write_jsonl(selective_path, hashes)

    return full, selective


def paired_samples(
    full: Callable[[], tuple[Any, int]],
    selective: Callable[[], tuple[Any, int]],
    *,
    warmups: int,
    trials: int,
) -> dict[str, Any]:
    for i in range(warmups):
        (full if i % 2 == 0 else selective)()
        (selective if i % 2 == 0 else full)()

    samples: dict[str, list[dict[str, Any]]] = {"full": [], "selective": []}
    for trial in range(trials):
        order = ("full", "selective") if trial % 2 == 0 else ("selective", "full")
        calls = {"full": full, "selective": selective}
        for name in order:
            _result, bytes_written, elapsed_ms = timed(calls[name])
            samples[name].append(
                {
                    "trial": trial,
                    "elapsed_ms": round(elapsed_ms, 6),
                    "bytes_written": bytes_written,
                }
            )

    full_summary = summarize(samples["full"])
    selective_summary = summarize(samples["selective"])
    ratio = (
        full_summary["p50_ms"] / selective_summary["p50_ms"]
        if selective_summary["p50_ms"]
        else None
    )
    return {
        "full": full_summary,
        "selective": selective_summary,
        "p50_full_over_selective_ratio": round(ratio, 6) if ratio is not None else None,
    }


def run_trials(context: dict[str, Any], *, warmups: int, trials: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="tavonel-family-b-perf-") as raw_temp:
        temp = Path(raw_temp)
        full_e2e, selective_e2e = arm_calls(context, temp)
        full_build, selective_build = build_only_calls(context, temp)
        end_to_end = paired_samples(
            full_e2e,
            selective_e2e,
            warmups=warmups,
            trials=trials,
        )
        build_only = paired_samples(
            full_build,
            selective_build,
            warmups=warmups,
            trials=trials,
        )
        peak = {
            "full_e2e_python_tracemalloc_peak_bytes": memory_probe(lambda: full_e2e()),
            "selective_e2e_python_tracemalloc_peak_bytes": memory_probe(
                lambda: selective_e2e()
            ),
        }
        plan = build_plan(context)
        return {
            "artifact_count": len(context["inventory"]),
            "planned_rebuild_count": len(plan.to_rebuild),
            "planned_rebuild_fraction": len(plan.to_rebuild) / len(context["inventory"]),
            "all_equivalent": True,
            "end_to_end": end_to_end,
            "build_only": build_only,
            **peak,
        }


def controlled_context(scale: int) -> dict[str, Any]:
    rng = random.Random(SEED + scale)  # noqa: S311 -- deterministic benchmark generation
    ids = [f"unit:{i:06d}" for i in range(scale)]
    before_units = [
        UnitSnapshot(
            logical_id=unit,
            text=f"stable knowledge token {i} seed {rng.randrange(10**9)}",
        )
        for i, unit in enumerate(ids)
    ]
    after_units = list(before_units)
    changed_count = max(1, round(scale * CHANGE_FRACTION))
    changed = set(random.Random(SEED ^ scale).sample(range(scale), changed_count))  # noqa: S311
    for i in changed:
        after_units[i] = UnitSnapshot(
            logical_id=ids[i],
            text=before_units[i].text + " revised-semantic-value",
        )

    dependencies = {f"artifact:section:{unit}": (unit,) for unit in ids}
    dependencies["artifact:document-index:controlled"] = tuple(ids)
    inventory = sorted(dependencies)
    graph = declared_semantic_graph(dependencies)
    before_hashes = artifact_hashes_subset(dependencies, before_units)
    full_oracle = artifact_hashes_subset(dependencies, after_units)
    shape = DocumentShape(
        heading_path_set=frozenset((unit,) for unit in ids),
        block_count=scale,
        unit_order=tuple(ids),
    )
    return {
        "source": f"controlled-scale:{scale}",
        "before_sha256": canonical_sha256([u.text for u in before_units]),
        "after_sha256": canonical_sha256([u.text for u in after_units]),
        "before_units": before_units,
        "after_units": after_units,
        "before_shape": shape,
        "after_shape": shape,
        "inventory": inventory,
        "dependencies": dependencies,
        "graph": graph,
        "before_hashes": before_hashes,
        "full_oracle": full_oracle,
        "changed_unit_count": changed_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=TRIALS)
    parser.add_argument("--warmups", type=int, default=WARMUPS)
    args = parser.parse_args()
    precise = load_precise()
    adapter = precise.load_adapter()

    real_rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="tavonel-family-b-real-") as raw_temp:
        temp = Path(raw_temp)
        for corpus_name, receipt_path, corpus in precise.CORPORA:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            for record in receipt.get("records", []):
                context = real_pair_context(precise, adapter, corpus, record)
                if context is None:
                    continue
                context.update(
                    {
                        "source": f"wikipedia:{record['title']}",
                        "before_sha256": adapter.sha_text(context["before"].text),
                        "after_sha256": adapter.sha_text(context["after"].text),
                    }
                )
                full_e2e, selective_e2e = arm_calls(context, temp)
                full_build, selective_build = build_only_calls(context, temp)
                _full_result, full_bytes, full_ms = timed(full_e2e)
                _sel_result, sel_bytes, sel_ms = timed(selective_e2e)
                _full_build_result, full_build_bytes, full_build_ms = timed(full_build)
                _sel_build_result, sel_build_bytes, sel_build_ms = timed(selective_build)
                plan = build_plan(context)
                real_rows.append(
                    {
                        "corpus": corpus_name,
                        "title": record["title"],
                        "artifacts": len(context["inventory"]),
                        "planned_rebuild": len(plan.to_rebuild),
                        "rebuild_fraction": len(plan.to_rebuild) / len(context["inventory"]),
                        "end_to_end": {
                            "full_ms": round(full_ms, 6),
                            "selective_ms": round(sel_ms, 6),
                            "full_bytes_written": full_bytes,
                            "selective_bytes_written": sel_bytes,
                        },
                        "build_only": {
                            "full_ms": round(full_build_ms, 6),
                            "selective_ms": round(sel_build_ms, 6),
                            "full_bytes_written": full_build_bytes,
                            "selective_bytes_written": sel_build_bytes,
                        },
                        "equivalent": True,
                    }
                )

    real_ratios = [
        row["end_to_end"]["full_ms"] / row["end_to_end"]["selective_ms"]
        for row in real_rows
        if row["end_to_end"]["selective_ms"]
    ]
    real_build_ratios = [
        row["build_only"]["full_ms"] / row["build_only"]["selective_ms"]
        for row in real_rows
        if row["build_only"]["selective_ms"]
    ]
    real_summary = {
        "pairs": len(real_rows),
        "all_equivalent": all(row["equivalent"] for row in real_rows),
        "end_to_end_median_full_over_selective_wall_ratio": round(
            statistics.median(real_ratios), 6
        )
        if real_ratios
        else None,
        "build_only_median_full_over_selective_wall_ratio": round(
            statistics.median(real_build_ratios), 6
        )
        if real_build_ratios
        else None,
        "end_to_end_p50_full_ms": round(
            statistics.median(row["end_to_end"]["full_ms"] for row in real_rows), 6
        )
        if real_rows
        else None,
        "end_to_end_p50_selective_ms": round(
            statistics.median(row["end_to_end"]["selective_ms"] for row in real_rows),
            6,
        )
        if real_rows
        else None,
        "end_to_end_p95_full_ms": round(
            percentile([row["end_to_end"]["full_ms"] for row in real_rows], 0.95), 6
        ),
        "end_to_end_p95_selective_ms": round(
            percentile(
                [row["end_to_end"]["selective_ms"] for row in real_rows], 0.95
            ),
            6,
        ),
        "rows": real_rows,
    }

    controlled: dict[str, Any] = {}
    for scale in SCALES:
        print(f"controlled scale {scale}: preparing")
        context = controlled_context(scale)
        controlled[str(scale)] = {
            "changed_unit_count": context["changed_unit_count"],
            **run_trials(context, warmups=args.warmups, trials=args.trials),
        }
        print(
            f"controlled scale {scale}: e2e p50 full/selective ratio "
            f"{controlled[str(scale)]['end_to_end']['p50_full_over_selective_ratio']}; "
            f"build-only ratio "
            f"{controlled[str(scale)]['build_only']['p50_full_over_selective_ratio']}"
        )

    receipt: dict[str, Any] = {
        "schema": "tavonel.family-b-measured-performance.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol_sha256": file_sha256(PROTOCOL),
        "script_sha256": file_sha256(Path(__file__)),
        "python": sys.version,
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "seed": SEED,
        "warmups": args.warmups,
        "trials": args.trials,
        "controlled_change_fraction": CHANGE_FRACTION,
        "real_revision": real_summary,
        "controlled_scaling": controlled,
        "measurement_scope": {
            "real_revision": "frozen Wikipedia pairs; one recorded timing per pair",
            "controlled_scaling": "deterministic generated semantic graph; not production traffic",
            "memory": "Python tracemalloc peak, not process RSS",
            "io": "actual temporary JSONL bytes written by the harness",
            "gpu": "not applicable to graph/hash operations",
        },
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"real pairs: {len(real_rows)}, all equivalent={real_summary['all_equivalent']}")
    print(f"receipt: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
