"""Benchmark identity resolution at 1k / 10k synthetic units.

What this measures
------------------
For each size N, a synthetic previous-version corpus of N units is generated,
a mutated incoming version is derived from it, and every incoming unit is
resolved against the corpus through the §N15.1 sparse blocking index
(`resolve_units`). Reported per unit: wall-clock p50/p95/mean, totals,
decision counts and peak memory. The pre-blocking brute-force scan is timed
on a small sample of the same work to quantify the speedup without paying
its quadratic cost end-to-end.

A MemoryError anywhere surfaces as a crash: a clean run at N=10000 is the
no-MemoryError evidence this benchmark exists to produce.

Usage::

    python scripts/bench_identity.py --sizes 1000 10000 [--seed S]
        [--brute-sample K] [--no-brute]

Standard library on top of akc_cir.identity only; no new dependencies.
"""

from __future__ import annotations

import argparse
import platform
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "cir-python" / "src"))

from akc_cir.identity import (
    BlockingCandidateIndex,
    LogicalIdentityResolver,
    LogicalUnitFingerprint,
)

_WORDS = [
    "warranty", "coverage", "shipping", "carrier", "parts", "labour",
    "delivery", "scope", "claims", "remedies", "rates", "overview",
    "consumables", "cosmetic", "damage", "tendered", "earliest", "pickup",
    "window", "retention", "notice", "disposal", "sections", "schedules",
    "premium",
]
_SECTIONS = [
    "Warranty", "Coverage", "Shipping", "Claims", "Definitions", "Remedies",
    "Privacy", "Security", "Billing", "Support",
]
_STYLES = ("body 10pt indent-0", "body 10pt indent-1", "heading 14pt indent-0")


def _corpus(rng: random.Random, size: int) -> list[LogicalUnitFingerprint]:
    """N synthetic units spread over documents, sections and wording."""
    documents = max(1, size // 50)
    units: list[LogicalUnitFingerprint] = []
    for index in range(size):
        document = index % documents
        section = _SECTIONS[rng.randrange(len(_SECTIONS))]
        major, minor = rng.randrange(1, 12), rng.randrange(1, 10)
        number = f"{major}.{minor}"
        title = " ".join(rng.choices(_WORDS, k=3))
        body = " ".join(rng.choices(_WORDS, k=rng.randrange(10, 45)))
        units.append(
            LogicalUnitFingerprint.of(
                logical_id=f"ku_prev_{index:07d}",
                document_path=(f"document-{document}", section, f"{number} {title}"),
                anchor=f"{number} {title}",
                text=body,
                source_lineage=f"src_document_{document}",
                version_distance=1,
                explicit_identifier=number,
                previous_anchor=f"{major}.{max(1, minor - 1)} prev",
                next_anchor=f"{major}.{minor + 1} {title}",
                geometry_style=rng.choice(_STYLES),
            )
        )
    return units


def _mutate(text: str, rng: random.Random) -> str:
    words = text.split()
    if not words:
        return text
    position = rng.randrange(len(words))
    words[position] = rng.choice(_WORDS)
    if len(words) > 3 and rng.random() < 0.25:
        words.pop(rng.randrange(len(words)))
    return " ".join(words)


def _incoming_version(
    rng: random.Random, corpus: list[LogicalUnitFingerprint]
) -> list[LogicalUnitFingerprint]:
    """The next version: mostly continuations, some moves, some brand-new."""
    incoming: list[LogicalUnitFingerprint] = []
    for index, unit in enumerate(corpus):
        roll = rng.random()
        parts = list(unit.document_path)
        number, _, title = unit.anchor.partition(" ")
        if roll < 0.70:
            pass  # stayed put
        elif roll < 0.90:
            parts[1] = _SECTIONS[rng.randrange(len(_SECTIONS))]  # moved section
        else:
            title = " ".join(rng.choices(_WORDS, k=3))  # retitled
        anchor = f"{number} {title}"
        text = unit.normalized_text if roll < 0.30 else _mutate(unit.normalized_text, rng)
        incoming.append(
            LogicalUnitFingerprint.of(
                logical_id=f"ku_in_{index:07d}",
                document_path=tuple(parts),
                anchor=anchor,
                text=text,
                source_lineage=unit.source_lineage,
                version_distance=1,
                explicit_identifier=unit.explicit_identifier,
                previous_anchor=unit.previous_anchor,
                next_anchor=unit.next_anchor,
                geometry_style=unit.geometry_style,
            )
        )
        if rng.random() < 0.05:
            fresh_number = f"{rng.randrange(20, 29)}.{rng.randrange(1, 9)}"
            fresh_title = " ".join(rng.choices(_WORDS, k=3))
            incoming.append(
                LogicalUnitFingerprint.of(
                    logical_id=f"ku_in_new_{index:07d}",
                    document_path=(
                        parts[0], _SECTIONS[0], f"{fresh_number} {fresh_title}"
                    ),
                    anchor=f"{fresh_number} {fresh_title}",
                    text=" ".join(rng.choices(_WORDS, k=rng.randrange(10, 45))),
                    source_lineage=unit.source_lineage,
                    explicit_identifier=fresh_number,
                    geometry_style=rng.choice(_STYLES),
                )
            )
    return incoming


def _legacy_resolve(
    resolver: LogicalIdentityResolver,
    unit: LogicalUnitFingerprint,
    previous: list[LogicalUnitFingerprint],
) -> float:
    """Pre-blocking resolve(): one full score_pair scan per unit."""
    start = time.perf_counter()
    scored = sorted(
        ((resolver.score_pair(candidate, unit), candidate) for candidate in previous),
        key=lambda item: (-item[0][0], item[1].logical_id),
    )
    elapsed = time.perf_counter() - start
    # Sanity inside the benchmark itself: brute force must agree with blocking.
    blocked = resolver.resolve(unit, previous)
    assert blocked.score == scored[0][0][0] and blocked.match == (
        resolver.decide_pair(
            incoming=unit,
            partner=scored[0][1],
            score=scored[0][0][0],
            signals=scored[0][0][1],
            missing=scored[0][0][2],
            runner_up=scored[1][0][0] if len(scored) > 1 else 0.0,
            runner_up_id=scored[1][1].logical_id if len(scored) > 1 else None,
            seed_logical_id=None,
        ).match
    ), "blocked result diverged from brute force"
    return elapsed


def _peak_rss_mb() -> float | None:
    try:  # Windows: GetProcessMemoryInfo needs explicit argtypes/restype.
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_PMC),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = _PMC()
        counters.cb = ctypes.sizeof(_PMC)
        handle = kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            peak = counters.PeakWorkingSetSize
            return float(peak) / 1048576
    except Exception:  # noqa: S110 - platform probe; POSIX fallback follows.
        pass
    try:  # POSIX fallback
        import resource

        return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - not a POSIX platform
        return None


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    position = min(len(sorted_values) - 1, round(fraction * (len(sorted_values) - 1)))
    return sorted_values[position]


def run_size(size: int, seed: int, brute_sample: int, do_brute: bool) -> None:
    rng = random.Random(seed + size)  # noqa: S311 - synthetic corpus, not security
    print(f"\n[{size} units] generating synthetic corpus...", flush=True)
    corpus = _corpus(rng, size)
    incoming = _incoming_version(rng, corpus)
    resolver = LogicalIdentityResolver()

    # Timing runs WITHOUT tracemalloc: per-allocation tracing distorts the
    # latencies several-fold. Peak memory comes from the process working set
    # instead, which observes growth without taxing every allocation.
    start = time.perf_counter()
    index = BlockingCandidateIndex(corpus)
    index_build_s = time.perf_counter() - start
    start = time.perf_counter()

    latencies: list[float] = []
    decisions = []
    for unit in incoming:
        unit_start = time.perf_counter()
        decisions.append(resolver.resolve(unit, corpus, index=index))
        latencies.append(time.perf_counter() - unit_start)
    total_s = time.perf_counter() - start

    counts = Counter(decision.match.value for decision in decisions)

    latencies.sort()
    p50_ms = _percentile(latencies, 0.50) * 1000
    p95_ms = _percentile(latencies, 0.95) * 1000
    mean_ms = statistics.mean(latencies) * 1000

    print(f"[{size} units] corpus={len(corpus)} incoming={len(incoming)}")
    print(f"  index build              : {index_build_s:.2f} s")
    print(f"  blocked resolve total    : {total_s:.2f} s")
    print(
        f"  per-unit latency         : p50 {p50_ms:.2f} ms"
        f" | p95 {p95_ms:.2f} ms | mean {mean_ms:.2f} ms"
    )
    print(
        f"  decisions                : matched={counts['matched']}"
        f" new={counts['new']} ambiguous={counts['ambiguous']}"
    )

    if do_brute and brute_sample > 0:
        picks = rng.sample(range(len(incoming)), min(brute_sample, len(incoming)))
        samples_ms = []
        for pick in picks:
            samples_ms.append(_legacy_resolve(resolver, incoming[pick], corpus) * 1000)
        brute_p50_ms = statistics.median(samples_ms)
        projected_s = brute_p50_ms * len(incoming) / 1000
        print(
            f"  brute-force scan (n={len(picks):02d} sample): p50 {brute_p50_ms:.2f} ms/unit"
            f" -> projected total {projected_s:.1f} s   speedup x{brute_p50_ms / p50_ms:.1f}"
        )

    rss_mb = _peak_rss_mb()
    memory = (
        f"peak working set {rss_mb:.1f} MB (whole process, cumulative)"
        if rss_mb is not None
        else "unavailable on this platform"
    )
    print(f"  peak memory              : {memory}")
    print("  MemoryError              : none")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000])
    parser.add_argument("--seed", type=int, default=20260823)
    parser.add_argument("--brute-sample", type=int, default=12)
    parser.add_argument("--no-brute", action="store_true")
    args = parser.parse_args()

    print("== identity resolution benchmark ==")
    print(f"python {platform.python_version()} | seed {args.seed}")
    for size in args.sizes:
        run_size(size, args.seed, args.brute_sample, not args.no_brute)
    print("\nall sizes completed without MemoryError")


if __name__ == "__main__":
    main()
