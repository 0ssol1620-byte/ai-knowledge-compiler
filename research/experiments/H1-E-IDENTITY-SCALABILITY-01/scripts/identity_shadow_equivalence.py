#!/usr/bin/env python3
"""H1-E: LEGACY vs BLOCKED identity matching -- decision equivalence and scaling.

Governed by PROTOCOL_2026-08-19.md, frozen before any number below was produced.
Nothing here touches the sealed Family B fresh-seed holdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json

# `random` seeds the controlled corpora and is deliberately reproducible;
# nothing here is cryptographic.
import random
import statistics
import sys
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalUnitFingerprint,
    MatchingPolicy,
    assign_one_to_one,
)

PROTOCOL = Path(__file__).resolve().parents[1] / "PROTOCOL_2026-08-19.md"
IDENTITY_MODULE = ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "identity.py"

WORDS = [
    "obligation", "party", "delivery", "notice", "term", "renewal", "breach",
    "remedy", "payment", "invoice", "schedule", "annex", "consent", "warranty",
    "liability", "indemnity", "assignment", "governing", "dispute", "arbitration",
]


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def sentence(rng: random.Random, length: int = 12) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(length))


def unit(
    *,
    logical_id: str,
    section: str,
    ordinal: int,
    text: str,
    identifier: str = "",
    lineage: str = "controlled",
) -> LogicalUnitFingerprint:
    return LogicalUnitFingerprint.of(
        logical_id=logical_id,
        document_path=(section, f"para-{ordinal}"),
        anchor=f"anchor-{logical_id}",
        text=text,
        source_lineage=lineage,
        version_distance=1,
        explicit_identifier=identifier,
        previous_anchor=f"anchor-{logical_id}-prev",
        next_anchor=f"anchor-{logical_id}-next",
        geometry_style="body",
    )


# -- topologies ------------------------------------------------------------
#
# Each returns (previous, incoming). Sections are the path root, so a unit in a
# different section is exactly what the candidate index prunes.


def topo_stable(rng: random.Random, size: int) -> tuple[list, list]:
    sections = max(1, size // 25)
    prev, inc = [], []
    for i in range(size):
        text = sentence(rng)
        section = f"section-{i % sections}"
        prev.append(unit(logical_id=f"u{i}", section=section, ordinal=i, text=text))
        inc.append(unit(logical_id=f"n{i}", section=section, ordinal=i, text=text))
    return prev, inc


def topo_edited(rng: random.Random, size: int) -> tuple[list, list]:
    prev, inc = topo_stable(rng, size)
    out = []
    for i, u in enumerate(inc):
        if i % 5 == 0:
            out.append(
                unit(
                    logical_id=u.logical_id,
                    section=u.document_path[0],
                    ordinal=i,
                    text=sentence(rng),
                )
            )
        else:
            out.append(u)
    return prev, out


def topo_reordered(rng: random.Random, size: int) -> tuple[list, list]:
    prev, inc = topo_stable(rng, size)
    shuffled = inc[:]
    rng.shuffle(shuffled)
    return prev, shuffled


def topo_duplicate_text_decoy(rng: random.Random, size: int) -> tuple[list, list]:
    """Falsification arm (protocol §5).

    Every unit's text is duplicated verbatim into a *different* path root, so
    the decoy is precisely the candidate the index prunes. If pruning were
    unsafe, this is the cell that would show it.
    """
    prev, inc = topo_stable(rng, size)
    decoys = [
        unit(
            logical_id=f"decoy{i}",
            section="decoy-section",
            ordinal=i,
            text=u.normalized_text,
        )
        for i, u in enumerate(prev)
    ]
    return prev + decoys, inc


def topo_shared_identifier(rng: random.Random, size: int) -> tuple[list, list]:
    """Explicit identifiers repeat across sections -- the index unions them in."""
    prev, inc = [], []
    sections = max(1, size // 25)
    for i in range(size):
        text = sentence(rng)
        section = f"section-{i % sections}"
        ident = f"{i % 7}.{i % 5}"
        prev.append(
            unit(logical_id=f"u{i}", section=section, ordinal=i, text=text, identifier=ident)
        )
        inc.append(
            unit(logical_id=f"n{i}", section=section, ordinal=i, text=text, identifier=ident)
        )
    return prev, inc


def topo_split_and_merge(rng: random.Random, size: int) -> tuple[list, list]:
    prev, _ = topo_stable(rng, size)
    inc = []
    for i, u in enumerate(prev):
        if i % 4 == 0:
            half = u.normalized_text.split()
            inc.append(
                unit(
                    logical_id=f"n{i}a",
                    section=u.document_path[0],
                    ordinal=i,
                    text=" ".join(half[: len(half) // 2]),
                )
            )
            inc.append(
                unit(
                    logical_id=f"n{i}b",
                    section=u.document_path[0],
                    ordinal=i,
                    text=" ".join(half[len(half) // 2 :]),
                )
            )
        else:
            inc.append(
                unit(
                    logical_id=f"n{i}",
                    section=u.document_path[0],
                    ordinal=i,
                    text=u.normalized_text,
                )
            )
    return prev, inc


def topo_near_tie(rng: random.Random, size: int) -> tuple[list, list]:
    """Same section, near-identical siblings -- where the tie guard must fire."""
    prev, inc = [], []
    for i in range(size):
        base = sentence(rng)
        prev.append(unit(logical_id=f"u{i}a", section="section-0", ordinal=i, text=base))
        prev.append(
            unit(logical_id=f"u{i}b", section="section-0", ordinal=i, text=base + " variant")
        )
        inc.append(unit(logical_id=f"n{i}", section="section-0", ordinal=i, text=base))
    return prev, inc


TOPOLOGIES = {
    "stable": topo_stable,
    "edited": topo_edited,
    "reordered": topo_reordered,
    "duplicate_text_decoy": topo_duplicate_text_decoy,
    "shared_identifier": topo_shared_identifier,
    "split_and_merge": topo_split_and_merge,
    "near_tie": topo_near_tie,
}


# -- equivalence -----------------------------------------------------------


def key(decision: Any) -> tuple:
    return (
        str(decision.match),
        decision.logical_id,
        str(decision.relation) if decision.relation is not None else None,
        tuple(sorted(decision.candidates)),
    )


def classify(legacy: Any, blocked: Any) -> str:
    lm, bm = str(legacy.match), str(blocked.match)
    if lm == bm and legacy.logical_id == blocked.logical_id:
        return "OTHER"
    if bm == "matched" and lm in {"ambiguous", "new"}:
        return "FAIL_OPEN"
    if bm == "matched" and lm == "matched" and legacy.logical_id != blocked.logical_id:
        return "FAIL_OPEN"
    if lm == "matched" and bm in {"ambiguous", "new"}:
        return "FAIL_CLOSED"
    return "OTHER"


def run_equivalence(cases_per_cell: int, size: int, seed: int) -> dict[str, Any]:
    engine = LogicalIdentityResolver()
    cells: dict[str, Any] = {}
    totals = {"FAIL_OPEN": 0, "FAIL_CLOSED": 0, "OTHER": 0}
    for name, builder in TOPOLOGIES.items():
        counts = {"FAIL_OPEN": 0, "FAIL_CLOSED": 0, "OTHER": 0}
        examples: list[dict[str, Any]] = []
        compared = 0
        identical_cases = 0
        for case in range(cases_per_cell):
            rng = random.Random(f"{seed}:{name}:{case}")  # noqa: S311
            previous, incoming = builder(rng, size)
            legacy = assign_one_to_one(
                incoming, previous, resolver=engine, policy=MatchingPolicy.LEGACY
            )
            blocked = assign_one_to_one(
                incoming, previous, resolver=engine, policy=MatchingPolicy.BLOCKED
            )
            case_diverged = False
            for position, (lhs, rhs) in enumerate(zip(legacy, blocked, strict=True)):
                compared += 1
                if key(lhs) == key(rhs):
                    continue
                case_diverged = True
                kind = classify(lhs, rhs)
                counts[kind] += 1
                totals[kind] += 1
                if len(examples) < 5:
                    examples.append(
                        {
                            "case": case,
                            "position": position,
                            "kind": kind,
                            "legacy": {
                                "match": str(lhs.match),
                                "logical_id": lhs.logical_id,
                                "score": round(lhs.score, 4),
                            },
                            "blocked": {
                                "match": str(rhs.match),
                                "logical_id": rhs.logical_id,
                                "score": round(rhs.score, 4),
                            },
                        }
                    )
            if not case_diverged:
                identical_cases += 1
        cells[name] = {
            "cases": cases_per_cell,
            "units_per_case": size,
            "decisions_compared": compared,
            "identical_cases": identical_cases,
            "divergences": counts,
            "divergence_examples": examples,
        }
        print(f"equivalence {name}: {counts} over {compared} decisions")
    return {"cells": cells, "totals": totals}


def _weakened_run(
    weakening: str,
    columns_for: Any,
    topology: str,
    size: int,
    seed: int,
) -> dict[str, Any]:
    import akc_cir.identity as identity_module

    engine = LogicalIdentityResolver()
    rng = random.Random(f"{seed}:falsify:{weakening}")  # noqa: S311
    previous, incoming = TOPOLOGIES[topology](rng, size)
    legacy = assign_one_to_one(
        incoming, previous, resolver=engine, policy=MatchingPolicy.LEGACY
    )
    original = identity_module._blocked_candidate_columns
    identity_module._blocked_candidate_columns = columns_for
    try:
        weakened = assign_one_to_one(
            incoming, previous, resolver=engine, policy=MatchingPolicy.BLOCKED
        )
    finally:
        identity_module._blocked_candidate_columns = original
    diverged = sum(
        1 for lhs, rhs in zip(legacy, weakened, strict=True) if key(lhs) != key(rhs)
    )
    print(f"falsification [{weakening}] on {topology}: {diverged} divergent decisions")
    return {
        "weakening": weakening,
        "topology": topology,
        "units": size,
        "divergent_decisions": diverged,
        "separates": diverged > 0,
    }


def run_falsification(size: int, seed: int) -> dict[str, Any]:
    """Protocol §5 as amended -- prove the comparator can see a divergence.

    A zero in §6 is only meaningful if something makes the same comparator
    non-zero. Two weakenings are run, and the amendment records why the first
    one registered is kept but is *not* the arm that carries the claim:

    - `identifier_and_anchor_union_removed` cannot separate by construction, and
      the run that showed that is retained. On `shared_identifier` the correct
      candidate also shares the path root, so dropping the other two unions
      removes only candidates that were never going to win. A weakening that
      cannot change the answer tests nothing.
    - `path_root_bucket_removed` is the arm that carries the claim. On `stable`
      no unit shares an identifier or an anchor with any candidate, so removing
      the path-root bucket empties the candidate set and every decision must
      move. If *this* returns zero the comparator is broken.
    """
    import akc_cir.identity as identity_module

    def only_path_root(incoming, previous, index):
        by_path, _, _ = index
        return sorted(by_path.get(identity_module._path_root(incoming.document_path), ()))

    def without_path_root(incoming, previous, index):
        _, by_identifier, by_anchor = index
        columns: set[int] = set()
        if incoming.explicit_identifier:
            columns.update(
                by_identifier.get(
                    identity_module.normalize_text_for_identity(
                        incoming.explicit_identifier
                    ),
                    (),
                )
            )
        for anchor in (incoming.anchor, incoming.previous_anchor, incoming.next_anchor):
            if anchor:
                columns.update(by_anchor.get(anchor, ()))
        return sorted(columns)

    retained = _weakened_run(
        "identifier_and_anchor_union_removed",
        only_path_root,
        "shared_identifier",
        size,
        seed,
    )
    carrying = _weakened_run(
        "path_root_bucket_removed", without_path_root, "stable", size, seed
    )
    return {
        "arms": [retained, carrying],
        "claim_carrying_arm": "path_root_bucket_removed",
        "harness_can_detect_divergence": carrying["separates"],
        "retained_null_arm_note": (
            "identifier_and_anchor_union_removed cannot separate by construction; "
            "retained as a recorded null, not treated as evidence of safety"
        ),
    }


# -- scaling ---------------------------------------------------------------


def summarise(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "n": len(samples),
        "p50_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 4),
        "mean_ms": round(statistics.fmean(ordered), 4),
    }


def time_policy(policy: Any, previous: list, incoming: list, trials: int) -> dict[str, Any]:
    engine = LogicalIdentityResolver()
    assign_one_to_one(incoming, previous, resolver=engine, policy=policy)  # warm
    samples = []
    for _ in range(trials):
        start = time.perf_counter()
        assign_one_to_one(incoming, previous, resolver=engine, policy=policy)
        samples.append((time.perf_counter() - start) * 1000.0)
    tracemalloc.start()
    assign_one_to_one(incoming, previous, resolver=engine, policy=policy)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    out = summarise(samples)
    out["tracemalloc_peak_bytes"] = peak
    return out


def run_scaling(seed: int) -> dict[str, Any]:
    both = [100, 250, 500, 750, 1000]
    blocked_only = [2500, 5000, 10000]
    results: dict[str, Any] = {}
    for size in both + blocked_only:
        rng = random.Random(f"{seed}:scale:{size}")  # noqa: S311
        previous, incoming = topo_edited(rng, size)
        row: dict[str, Any] = {"units": size, "topology": "edited"}
        row["blocked"] = time_policy(MatchingPolicy.BLOCKED, previous, incoming, 5)
        if size in both:
            # LEGACY is O(N*M) scorings plus an O(max(N,M)**3) pure-Python
            # Hungarian, so repeat count is cut as the scale rises rather than
            # dropping the scale. Amendment 2 records the deviation: the
            # protocol's scale coverage is kept, the repeat count is not.
            trials = 5 if size <= 500 else 1
            try:
                row["legacy"] = time_policy(
                    MatchingPolicy.LEGACY, previous, incoming, trials
                )
                row["legacy_trials"] = trials
                row["legacy_over_blocked_p50"] = round(
                    row["legacy"]["p50_ms"] / row["blocked"]["p50_ms"], 4
                )
            except MemoryError:
                row["legacy"] = "MemoryError"
        else:
            row["legacy"] = "not attempted at this scale; see legacy_10000 probe"
        results[str(size)] = row
        print(f"scale {size}: blocked p50={row['blocked']['p50_ms']} ms")
    return results


def probe_legacy_ceiling(seed: int, budget_s: float = 420.0) -> dict[str, Any]:
    """Walk LEGACY up until it stops being runnable, under a wall-clock budget.

    Protocol §7 expects `LEGACY` at 10,000 to remain unrunnable and its failure
    to be recorded rather than hidden. It is deliberately **not** re-run to
    completion here: `LEGACY` is `O(N*M)` scorings plus an `O(max(N,M)**3)`
    pure-Python Hungarian, so at 10,000 the honest outcomes are `MemoryError`
    or hours of CPU, and burning hours to re-confirm an already-measured
    `MemoryError` buys nothing. Each step is attempted only if the previous one
    finished inside the remaining budget; the first step that is not attempted
    is reported as `not_attempted` with the reason, never as a pass.
    """
    engine = LogicalIdentityResolver()
    steps: list[dict[str, Any]] = []
    remaining = budget_s
    for size in (1500, 2500):
        if remaining <= 0:
            steps.append(
                {
                    "units": size,
                    "outcome": "not_attempted",
                    "reason": "wall-clock budget for this probe was already spent",
                }
            )
            continue
        rng = random.Random(f"{seed}:ceiling:{size}")  # noqa: S311
        previous, incoming = topo_edited(rng, size)
        started = time.perf_counter()
        try:
            assign_one_to_one(
                incoming, previous, resolver=engine, policy=MatchingPolicy.LEGACY
            )
        except MemoryError:
            elapsed = time.perf_counter() - started
            steps.append(
                {"units": size, "outcome": "MemoryError", "elapsed_s": round(elapsed, 2)}
            )
            remaining = 0.0
            continue
        elapsed = time.perf_counter() - started
        remaining -= elapsed
        steps.append(
            {"units": size, "outcome": "completed", "elapsed_s": round(elapsed, 2)}
        )
        print(f"legacy ceiling probe {size}: completed in {elapsed:.1f}s")
    return {
        "budget_s": budget_s,
        "steps": steps,
        "prior_observation": (
            "H1-B measured-performance-v2 recorded MemoryError for the 10,000-unit "
            "full identity matching attempt; that receipt is the citation for the "
            "10,000 ceiling, not a re-run here"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260819)
    parser.add_argument("--cases-per-cell", type=int, default=40)
    parser.add_argument("--equivalence-units", type=int, default=60)
    parser.add_argument("--phase", choices=["all", "equivalence", "scaling"], default="all")
    args = parser.parse_args()

    receipt: dict[str, Any] = {
        "schema": "tavonel.identity-matching-shadow-equivalence.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "evidence_class": "controlled generated corpus; not a real document corpus",
        "protocol_sha256": sha256_file(PROTOCOL),
        "identity_module_sha256": sha256_file(IDENTITY_MODULE),
        "script_sha256": sha256_file(Path(__file__)),
        "external_gpu_cost_usd": 0.0,
        "python": sys.version.split()[0],
    }

    if args.phase in {"all", "equivalence"}:
        equivalence = run_equivalence(args.cases_per_cell, args.equivalence_units, args.seed)
        receipt["equivalence"] = equivalence
        receipt["falsification"] = run_falsification(args.equivalence_units, args.seed)
        totals = equivalence["totals"]
        receipt["primary_criterion"] = "FAIL_OPEN == 0 across every cell"
        receipt["primary_success"] = totals["FAIL_OPEN"] == 0
        receipt["promotion_rule"] = (
            "BLOCKED becomes default only if FAIL_OPEN == 0 and FAIL_CLOSED == 0"
        )
        receipt["promotion_eligible"] = (
            totals["FAIL_OPEN"] == 0 and totals["FAIL_CLOSED"] == 0
        )

    if args.phase in {"all", "scaling"}:
        receipt["scaling"] = run_scaling(args.seed)
        receipt["legacy_ceiling_probe"] = probe_legacy_ceiling(args.seed)

    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"receipt written: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
