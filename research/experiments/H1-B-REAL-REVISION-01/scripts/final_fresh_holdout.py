#!/usr/bin/env python3
"""One-shot fresh-seed B-EQUIV holdout.

Run only after FINAL_FRESH_HOLDOUT_PROTOCOL and this file are hash-frozen in the
seed preregistration receipt. The seed is supplied from the external sealed temp
file and disclosed only in the final result receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
HERE = Path(__file__).resolve().parent
PROTOCOL = HERE.parent / "FINAL_FRESH_HOLDOUT_PROTOCOL_2026-08-19.md"
CHANGE_SCRIPT = HERE / "change_space_sweep.py"
TOPOLOGY_SCRIPT = HERE / "adversarial_topology_extension.py"

from akc_cir.recompilation import StructuralPolicy  # noqa: E402

CHANGE_CLASSES = ("unchanged", "semantic_only", "structural_only", "mixed", "ambiguous")
CHANGE_CASES = 400
TOPOLOGY_CASES = 200
TOPOLOGY_CELLS = (
    "deep_chain_64",
    "cross_document_dependency",
    "diamond_conflicting_channels_semantic",
    "diamond_conflicting_channels_structural",
)


def sha256_bytes(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    )


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load holdout generator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def derived_rng(seed: int, label: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}|{label}".encode()).digest()
    return random.Random(int.from_bytes(digest[:16], "big"))  # noqa: S311 -- holdout generation


def change_cell(change: Any, seed: int, change_class: str) -> dict[str, Any]:
    rng = derived_rng(seed, f"change:{change_class}")
    counter: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    for _ in range(CHANGE_CASES):
        case = change.build_case(rng, change_class)
        row = change.run_case(case, policy=StructuralPolicy.PRECISE)
        counter["cases"] += 1
        counter["equivalent_cases"] += int(row["equivalent"])
        counter["escape_cases"] += int(bool(row["stale_escaped"]))
        counter["escape_artifacts"] += len(row["stale_escaped"])
        counter["false_invalidations"] += row["falsely_invalidated"]
        counter["rebuilt"] += row["rebuilt"]
        counter["genuinely_changed"] += row["genuinely_changed"]
        counter["gate_missed_escape"] += int(row["gate_missed_an_escape"])
        if row["stale_escaped"] and len(examples) < 5:
            examples.append(row)
    return {"totals": dict(counter), "escape_examples": examples}


def topology_cell(topology: Any, seed: int, name: str) -> dict[str, Any]:
    rng = derived_rng(seed, f"topology:{name}")
    if name == "deep_chain_64":
        rows = [topology.deep_chain_case(rng, i) for i in range(TOPOLOGY_CASES)]
    elif name == "cross_document_dependency":
        rows = [topology.cross_document_case(rng, i) for i in range(TOPOLOGY_CASES)]
    elif name == "diamond_conflicting_channels_semantic":
        rows = [topology.diamond_case(rng, i, "semantic") for i in range(TOPOLOGY_CASES)]
    elif name == "diamond_conflicting_channels_structural":
        rows = [topology.diamond_case(rng, i, "structural") for i in range(TOPOLOGY_CASES)]
    else:
        raise ValueError(name)
    return topology.accumulate(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-file", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    seed_text = args.seed_file.read_text(encoding="utf-8").strip()
    if not seed_text.isdigit():
        raise SystemExit("sealed seed file is not a decimal integer")
    seed = int(seed_text)
    prereg = json.loads(args.preregistration.read_text(encoding="utf-8"))
    observed_seed_hash = sha256_bytes(seed_text.encode("utf-8"))
    if observed_seed_hash != prereg["seed_sha256"]:
        raise SystemExit("seed does not match preregistration")

    current_hashes = {
        "protocol_sha256": file_sha256(PROTOCOL),
        "runner_sha256": file_sha256(Path(__file__)),
        "change_generator_sha256": file_sha256(CHANGE_SCRIPT),
        "topology_generator_sha256": file_sha256(TOPOLOGY_SCRIPT),
        "dependency_core_sha256": file_sha256(
            ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "dependency.py"
        ),
        "recompilation_core_sha256": file_sha256(
            ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "recompilation.py"
        ),
        "semantic_diff_core_sha256": file_sha256(
            ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "semantic_diff.py"
        ),
        "promotion_gate_core_sha256": file_sha256(
            ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "promotion_gate.py"
        ),
    }
    for key, value in current_hashes.items():
        if prereg.get(key) != value:
            raise SystemExit(f"frozen bytes changed before holdout: {key}")

    change = load_module("family_b_holdout_change_generator", CHANGE_SCRIPT)
    topology = load_module("family_b_holdout_topology_generator", TOPOLOGY_SCRIPT)

    change_cells = {
        change_class: change_cell(change, seed, change_class)
        for change_class in CHANGE_CLASSES
    }
    topology_cells = {
        name: topology_cell(topology, seed, name) for name in TOPOLOGY_CELLS
    }
    cells = {**change_cells, **topology_cells}
    failed_cells = [
        name
        for name, cell in cells.items()
        if cell["totals"].get("escape_cases", 0) != 0
        or cell["totals"].get("equivalent_cases", 0) != cell["totals"].get("cases", 0)
    ]
    gate_missed = sum(
        cell["totals"].get("gate_missed_escape", 0) for cell in change_cells.values()
    )
    success = not failed_cells
    receipt: dict[str, Any] = {
        "schema": "tavonel.family-b-final-fresh-holdout.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "seed_sha256": observed_seed_hash,
        "preregistration_file_sha256": file_sha256(args.preregistration),
        **current_hashes,
        "change_cases_per_class": CHANGE_CASES,
        "topology_cases_per_cell": TOPOLOGY_CASES,
        "cells": cells,
        "failed_cells": failed_cells,
        "primary_success": success,
        "gate_missed_escape_total": gate_missed,
        "primary_criterion": (
            "every cell exact-equivalent to independent full rebuild; "
            "zero stale escapes"
        ),
        "evidence_class": "one-shot fresh-seed controlled holdout",
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"holdout cells: {len(cells)}")
    print(f"failed cells: {len(failed_cells)}")
    print(f"gate missed escape total: {gate_missed}")
    print(f"primary success: {success}")
    print(f"receipt: {args.output}")
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
