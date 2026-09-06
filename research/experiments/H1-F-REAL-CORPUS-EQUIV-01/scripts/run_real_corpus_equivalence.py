#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
EXP = Path(__file__).resolve().parents[1]
PROTOCOL = EXP / "PROTOCOL_2026-08-19.md"
SCRIPT = Path(__file__).resolve()
BASE = ROOT / "research" / "experiments" / "H1-B-REAL-REVISION-01"
ADAPTER = BASE / "scripts" / "run_public_real_revision_holdout_v3.py"
CORPUS_ROOTS = (
    BASE / "corpus",
    BASE / "corpus-confirmatory-v1",
    BASE / "corpus-extension-v1",
)
PINNED_MODULES = (
    ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "identity.py",
    ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "semantic_diff.py",
    ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "dependency.py",
    ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "recompilation.py",
)
EXPECTED_PAIRS = 28
EXPECTED_FILES = 56


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def load_adapter() -> Any:
    spec = importlib.util.spec_from_file_location("h1b_real_adapter_v3", ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load H1-B real-revision adapter")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def inventory() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root in CORPUS_ROOTS:
        if not root.is_dir():
            raise RuntimeError(f"missing corpus root: {root}")
        for directory in sorted(path for path in root.iterdir() if path.is_dir()):
            files = sorted(directory.glob("*.wikitext"), key=lambda path: int(path.stem))
            if len(files) != 2:
                raise RuntimeError(
                    f"expected exactly two revisions in {directory}, got {len(files)}"
                )
            before, after = files
            if int(before.stem) >= int(after.stem):
                raise RuntimeError(f"revision ordering is not increasing in {directory}")
            rows.append(
                {
                    "corpus": root.name,
                    "title_slug": directory.name,
                    "before_path": rel(before),
                    "before_revision_id": int(before.stem),
                    "before_sha256": sha(before),
                    "after_path": rel(after),
                    "after_revision_id": int(after.stem),
                    "after_sha256": sha(after),
                }
            )
    if len(rows) != EXPECTED_PAIRS:
        raise RuntimeError(f"expected {EXPECTED_PAIRS} pairs, got {len(rows)}")
    if len(rows) * 2 != EXPECTED_FILES:
        raise RuntimeError("source-file count drifted")
    return rows


def write_hashed(path: Path, body: dict[str, Any], field: str) -> None:
    body[field] = canonical_sha(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def freeze(output: Path) -> int:
    rows = inventory()
    seal: dict[str, Any] = {
        "schema": "tavonel.h1f-real-corpus-equivalence-seal.v1",
        "frozen_at": datetime.now(UTC).isoformat(),
        "classification": "REAL_CORPUS_EMPIRICAL / retrospective all-stored regression",
        "protocol_path": rel(PROTOCOL),
        "protocol_sha256": sha(PROTOCOL),
        "runner_path": rel(SCRIPT),
        "runner_sha256": sha(SCRIPT),
        "adapter_path": rel(ADAPTER),
        "adapter_sha256": sha(ADAPTER),
        "module_hashes": {rel(path): sha(path) for path in PINNED_MODULES},
        "corpus_roots": [rel(path) for path in CORPUS_ROOTS],
        "pair_count": len(rows),
        "source_file_count": len(rows) * 2,
        "pairs": rows,
        "selection_rule": (
            "all leaf directories with exactly two .wikitext files in all three "
            "pre-existing corpus roots"
        ),
        "network_permitted_during_run": False,
        "fresh_holdout": False,
        "confirmatory": False,
    }
    write_hashed(output, seal, "seal_sha256")
    print(json.dumps({"pair_count": len(rows), "source_files": len(rows) * 2, "seal": rel(output)}))
    return 0


def verify_seal(path: Path) -> dict[str, Any]:
    seal = json.loads(path.read_text(encoding="utf-8"))
    recorded = seal.get("seal_sha256")
    bare = {key: value for key, value in seal.items() if key != "seal_sha256"}
    if canonical_sha(bare) != recorded:
        raise RuntimeError("seal self-hash mismatch")
    live = {
        "protocol_sha256": sha(PROTOCOL),
        "runner_sha256": sha(SCRIPT),
        "adapter_sha256": sha(ADAPTER),
    }
    for key, value in live.items():
        if seal.get(key) != value:
            raise RuntimeError(f"sealed {key} drifted")
    module_hashes = {rel(module): sha(module) for module in PINNED_MODULES}
    if seal.get("module_hashes") != module_hashes:
        raise RuntimeError("pinned live module bytes drifted")
    current = inventory()
    if seal.get("pairs") != current:
        raise RuntimeError("sealed corpus membership or bytes drifted")
    return seal


def revision(adapter: Any, path: Path, title: str) -> Any:
    revid = int(path.stem)
    text = path.read_text(encoding="utf-8")
    return adapter.Revision(
        title=title,
        revid=revid,
        parentid=0,
        timestamp="stored-retrospective",
        mw_sha1="",
        text=text,
    )


def run(seal_path: Path, output: Path) -> int:
    seal = verify_seal(seal_path.resolve())
    adapter = load_adapter()
    records: list[dict[str, Any]] = []
    for row in seal["pairs"]:
        before_path = ROOT / row["before_path"]
        after_path = ROOT / row["after_path"]
        title = f"{row['corpus']}::{row['title_slug']}"
        before = revision(adapter, before_path, title)
        after = revision(adapter, after_path, title)
        result = adapter.run_pair(before, after)
        records.append(
            {
                "corpus": row["corpus"],
                "title_slug": row["title_slug"],
                "before_revision_id": row["before_revision_id"],
                "after_revision_id": row["after_revision_id"],
                "before_sha256": row["before_sha256"],
                "after_sha256": row["after_sha256"],
                "before_units": result["before_units"],
                "after_units": result["after_units"],
                "changed_logical_ids": result["changed_logical_ids"],
                "unresolved_identity_count": result["unresolved_identity_count"],
                "change_kinds": result["change_kinds"],
                "artifact_count": result["artifact_count"],
                "rebuild_count": result["rebuild_count"],
                "rebuild_fraction": result["rebuild_fraction"],
                "equivalent": result["equivalent"],
                "stale_left_behind": result["stale_left_behind"],
                "diverged": result["diverged"],
                "missing_from_selective": result["missing_from_selective"],
            }
        )

    rebuild_fractions = [float(record["rebuild_fraction"]) for record in records]
    changed = [record for record in records if record["changed_logical_ids"] > 0]
    equivalent = [record for record in records if record["equivalent"]]
    stale_total = sum(int(record["stale_left_behind"]) for record in records)
    receipt: dict[str, Any] = {
        "schema": "tavonel.h1f-real-corpus-equivalence.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "classification": "REAL_CORPUS_EMPIRICAL / retrospective all-stored regression",
        "fresh_holdout": False,
        "confirmatory": False,
        "seal_path": rel(seal_path),
        "seal_file_sha256": sha(seal_path),
        "seal_sha256": seal["seal_sha256"],
        "protocol_sha256": seal["protocol_sha256"],
        "runner_sha256": seal["runner_sha256"],
        "adapter_sha256": seal["adapter_sha256"],
        "module_hashes": seal["module_hashes"],
        "pair_count": len(records),
        "changed_pair_count": len(changed),
        "equivalent_pair_count": len(equivalent),
        "all_pairs_equivalent": len(equivalent) == len(records),
        "stale_left_behind_total": stale_total,
        "total_artifacts": sum(int(record["artifact_count"]) for record in records),
        "total_rebuilt": sum(int(record["rebuild_count"]) for record in records),
        "mean_rebuild_fraction": statistics.fmean(rebuild_fractions),
        "median_rebuild_fraction": statistics.median(rebuild_fractions),
        "min_rebuild_fraction": min(rebuild_fractions),
        "max_rebuild_fraction": max(rebuild_fractions),
        "records": records,
        "success_for_retrospective_regression_statement": (
            len(records) == EXPECTED_PAIRS
            and len(equivalent) == len(records)
            and stale_total == 0
        ),
        "external_gpu_cost_usd": 0.0,
        "claim_boundary": (
            "All-stored natural English-Wikipedia revision regression under a sealed local "
            "corpus and live-code pins. Retrospective, not a fresh holdout, and not evidence "
            "of general equivalence."
        ),
    }
    write_hashed(output, receipt, "receipt_sha256")
    print(
        json.dumps(
            {
                "pairs": receipt["pair_count"],
                "changed_pairs": receipt["changed_pair_count"],
                "equivalent_pairs": receipt["equivalent_pair_count"],
                "stale_total": stale_total,
                "mean_rebuild_fraction": receipt["mean_rebuild_fraction"],
                "success": receipt["success_for_retrospective_regression_statement"],
                "receipt": rel(output),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["success_for_retrospective_regression_statement"] else 2


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
