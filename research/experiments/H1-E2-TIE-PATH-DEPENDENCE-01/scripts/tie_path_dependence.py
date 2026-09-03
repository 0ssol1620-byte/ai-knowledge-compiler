#!/usr/bin/env python3
"""H1-E2: test whether H1-E's residual row permutations are path-dependent.

The protocol is frozen separately. `freeze` pins the exact H1-E receipt and live
code before `run` is allowed to measure the future-state endpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
EXPERIMENT = Path(__file__).resolve().parents[1]
PROTOCOL = EXPERIMENT / "PROTOCOL_2026-08-19.md"
SCRIPT = Path(__file__).resolve()
H1E = ROOT / "research" / "experiments" / "H1-E-IDENTITY-SCALABILITY-01"
H1E_SCRIPT = H1E / "scripts" / "identity_shadow_equivalence.py"
H1E_RECEIPTS = H1E / "receipts"
IDENTITY_MODULE = ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "identity.py"
SEED = 20260819
CASES = 60
SIZE = 80

sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    MatchingPolicy,
    assign_one_to_one,
)


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def load_h1e() -> Any:
    spec = importlib.util.spec_from_file_location("h1e_identity_shadow", H1E_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load H1-E runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def self_hash_recomputes(document: dict[str, Any]) -> bool:
    recorded = document.get("receipt_sha256")
    if not isinstance(recorded, str):
        return False
    without = {k: v for k, v in document.items() if k != "receipt_sha256"}
    return canonical_sha256(without) == recorded


def select_source_receipt() -> tuple[Path, dict[str, Any]]:
    live_identity = sha256_file(IDENTITY_MODULE)
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in H1E_RECEIPTS.glob("*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(document, dict) or not self_hash_recomputes(document):
            continue
        if document.get("identity_module_sha256") != live_identity:
            continue
        totals = document.get("equivalence", {}).get("totals", {})
        if totals != {"FAIL_OPEN": 0, "FAIL_CLOSED": 0, "OTHER": 8}:
            continue
        split = document.get("equivalence", {}).get("cells", {}).get("split_and_merge", {})
        if split.get("cases") != CASES or split.get("units_per_case") != SIZE:
            continue
        if document.get("seed") != SEED:
            continue
        matches.append((path, document))
    if len(matches) != 1:
        names = [path.name for path, _ in matches]
        raise RuntimeError(f"expected exactly one live-code H1-E source receipt, found {names}")
    return matches[0]


def write_hashed(path: Path, body: dict[str, Any], hash_field: str) -> None:
    body[hash_field] = canonical_sha256(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def freeze(output: Path) -> int:
    source_path, source = select_source_receipt()
    seal: dict[str, Any] = {
        "schema": "tavonel.identity-tie-path-dependence-seal.v1",
        "frozen_at": datetime.now(UTC).isoformat(),
        "protocol_path": str(PROTOCOL.relative_to(ROOT)).replace("\\", "/"),
        "protocol_sha256": sha256_file(PROTOCOL),
        "script_path": str(SCRIPT.relative_to(ROOT)).replace("\\", "/"),
        "script_sha256": sha256_file(SCRIPT),
        "h1e_script_sha256": sha256_file(H1E_SCRIPT),
        "identity_module_sha256": sha256_file(IDENTITY_MODULE),
        "source_receipt_path": str(source_path.relative_to(ROOT)).replace("\\", "/"),
        "source_receipt_file_sha256": sha256_file(source_path),
        "source_receipt_self_sha256": source["receipt_sha256"],
        "source_totals": source["equivalence"]["totals"],
        "seed": SEED,
        "cases": CASES,
        "units_per_case": SIZE,
        "decision_rule": (
            "PROMOTION_VETO_PATH_DEPENDENT if controls are valid and at least one "
            "row-attached future decision differs"
        ),
    }
    write_hashed(output, seal, "seal_sha256")
    print(f"frozen {output}")
    return 0


def verify_seal(path: Path) -> dict[str, Any]:
    seal = json.loads(path.read_text(encoding="utf-8"))
    recorded = seal.get("seal_sha256")
    without = {k: v for k, v in seal.items() if k != "seal_sha256"}
    if canonical_sha256(without) != recorded:
        raise RuntimeError("seal self-hash mismatch")
    expected = {
        "protocol_sha256": sha256_file(PROTOCOL),
        "script_sha256": sha256_file(SCRIPT),
        "h1e_script_sha256": sha256_file(H1E_SCRIPT),
        "identity_module_sha256": sha256_file(IDENTITY_MODULE),
    }
    for field, live in expected.items():
        if seal.get(field) != live:
            raise RuntimeError(f"sealed {field} drifted: {seal.get(field)} != {live}")
    source_path = ROOT / seal["source_receipt_path"]
    if sha256_file(source_path) != seal["source_receipt_file_sha256"]:
        raise RuntimeError("sealed H1-E source receipt bytes drifted")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if not self_hash_recomputes(source):
        raise RuntimeError("sealed H1-E receipt self-hash no longer recomputes")
    if source.get("receipt_sha256") != seal["source_receipt_self_sha256"]:
        raise RuntimeError("sealed H1-E receipt identity changed")
    return seal


def materialize_prior(incoming: list[Any], decisions: list[Any]) -> list[Any]:
    prior = []
    for source, decision in zip(incoming, decisions, strict=True):
        if decision.logical_id is None:
            continue
        prior.append(replace(source, logical_id=decision.logical_id, version_distance=1))
    return prior


def future_probe(source: Any, case: int, row: int) -> Any:
    return replace(source, logical_id=f"future-c{case}-r{row}", version_distance=1)


def decision_record(decision: Any) -> dict[str, Any]:
    return {
        "match": str(decision.match),
        "logical_id": decision.logical_id,
        "relation": str(decision.relation) if decision.relation is not None else None,
        "candidates": sorted(decision.candidates),
        "score": round(decision.score, 6),
    }


def run(seal_path: Path, output: Path) -> int:
    seal = verify_seal(seal_path)
    h1e = load_h1e()
    engine = LogicalIdentityResolver()

    current_divergences = 0
    future_divergences = 0
    negative_control_divergences = 0
    probe_records: list[dict[str, Any]] = []
    per_case_multiset_equal: list[bool] = []
    first_source_for_positive: tuple[Any, int, int] | None = None

    for case in range(CASES):
        rng = random.Random(f"{SEED}:split_and_merge:{case}")  # noqa: S311
        previous, incoming = h1e.topo_split_and_merge(rng, SIZE)
        legacy = assign_one_to_one(
            incoming, previous, resolver=engine, policy=MatchingPolicy.LEGACY
        )
        blocked = assign_one_to_one(
            incoming, previous, resolver=engine, policy=MatchingPolicy.BLOCKED
        )
        rows = [
            row
            for row, (left, right) in enumerate(zip(legacy, blocked, strict=True))
            if h1e.key(left) != h1e.key(right)
        ]
        current_divergences += len(rows)
        if not rows:
            continue

        legacy_multiset = sorted(h1e.key(legacy[row]) for row in rows)
        blocked_multiset = sorted(h1e.key(blocked[row]) for row in rows)
        per_case_multiset_equal.append(legacy_multiset == blocked_multiset)

        legacy_prior = materialize_prior(incoming, legacy)
        blocked_prior = materialize_prior(incoming, blocked)

        for row in rows:
            source = incoming[row]
            probe = future_probe(source, case, row)
            left = assign_one_to_one(
                [probe], legacy_prior, resolver=engine, policy=MatchingPolicy.LEGACY
            )[0]
            right = assign_one_to_one(
                [probe], blocked_prior, resolver=engine, policy=MatchingPolicy.LEGACY
            )[0]
            differs = h1e.key(left) != h1e.key(right)
            future_divergences += int(differs)

            # Same-state negative control: identical inputs must not fabricate a difference.
            control_a = assign_one_to_one(
                [probe], legacy_prior, resolver=engine, policy=MatchingPolicy.LEGACY
            )[0]
            control_b = assign_one_to_one(
                [probe], list(legacy_prior), resolver=engine, policy=MatchingPolicy.LEGACY
            )[0]
            negative_diff = h1e.key(control_a) != h1e.key(control_b)
            negative_control_divergences += int(negative_diff)

            if first_source_for_positive is None:
                first_source_for_positive = (source, case, row)

            probe_records.append(
                {
                    "case": case,
                    "row": row,
                    "current_legacy": decision_record(legacy[row]),
                    "current_blocked": decision_record(blocked[row]),
                    "future_legacy_state": decision_record(left),
                    "future_blocked_state": decision_record(right),
                    "future_differs": differs,
                    "negative_control_differs": negative_diff,
                }
            )

    if current_divergences != 8:
        raise RuntimeError(f"source reconstruction drifted: expected 8, got {current_divergences}")
    if first_source_for_positive is None:
        raise RuntimeError("no divergence row available for positive falsification")

    source, case, row = first_source_for_positive
    probe = future_probe(source, case, row)
    exact_prior = replace(source, logical_id="falsification-prior", version_distance=1)
    positive_present = assign_one_to_one(
        [probe], [exact_prior], resolver=engine, policy=MatchingPolicy.LEGACY
    )[0]
    positive_absent = assign_one_to_one(
        [probe], [], resolver=engine, policy=MatchingPolicy.LEGACY
    )[0]
    positive_separates = h1e.key(positive_present) != h1e.key(positive_absent)

    controls_valid = positive_separates and negative_control_divergences == 0
    if not controls_valid:
        disposition = "HARNESS_INVALID_NO_PROMOTION_STATEMENT"
    elif future_divergences > 0:
        disposition = "PROMOTION_VETO_PATH_DEPENDENT"
    else:
        disposition = "NO_VETO_FROM_H1_E2_ONLY"

    receipt: dict[str, Any] = {
        "schema": "tavonel.identity-tie-path-dependence.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "evidence_class": "controlled generated mechanism evidence; not real corpus",
        "external_gpu_cost_usd": 0.0,
        "seal_path": str(seal_path.resolve().relative_to(ROOT)).replace("\\", "/"),
        "seal_file_sha256": sha256_file(seal_path),
        "seal_sha256": seal["seal_sha256"],
        "protocol_sha256": seal["protocol_sha256"],
        "script_sha256": seal["script_sha256"],
        "h1e_script_sha256": seal["h1e_script_sha256"],
        "identity_module_sha256": seal["identity_module_sha256"],
        "source_receipt_path": seal["source_receipt_path"],
        "source_receipt_file_sha256": seal["source_receipt_file_sha256"],
        "seed": SEED,
        "cases": CASES,
        "units_per_case": SIZE,
        "current_row_divergences": current_divergences,
        "divergent_case_multisets_all_equal": all(per_case_multiset_equal),
        "future_row_divergences": future_divergences,
        "negative_control_divergences": negative_control_divergences,
        "positive_falsification": {
            "case": case,
            "row": row,
            "present": decision_record(positive_present),
            "absent": decision_record(positive_absent),
            "separates": positive_separates,
        },
        "controls_valid": controls_valid,
        "promotion_disposition": disposition,
        "promotion_safe_under_this_protocol": controls_valid and future_divergences == 0,
        "probes": probe_records,
    }
    write_hashed(output, receipt, "receipt_sha256")
    print(f"current divergences: {current_divergences}")
    print(f"future divergences:  {future_divergences}")
    print(f"negative control:    {negative_control_divergences}")
    print(f"positive separates:  {positive_separates}")
    print(f"disposition:          {disposition}")
    print(f"wrote {output}")
    return 0 if controls_valid else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    freeze_parser = sub.add_parser("freeze")
    freeze_parser.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--seal", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        return freeze(args.output)
    return run(args.seal, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
