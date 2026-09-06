#!/usr/bin/env python3
"""Emit the reproducibility package: every experiment, its inputs, and its hashes.

Closes the gap the reproducibility red-team recorded as X8 -- the scripts were
runnable but nothing pinned, per experiment, *which* command produced *which*
receipt under *which* environment.

Deliberately descriptive, not prescriptive: it walks what is actually on disk
rather than a hand-maintained list, so an experiment cannot fall out of the
manifest by being forgotten. Where a receipt records its own protocol or code
hashes, those are re-verified against the live files and any drift is reported
as `DRIFTED` rather than quietly re-hashed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENTS = ROOT / "research" / "experiments"
DRIFT_REGISTER = ROOT / "docs" / "repro" / "HISTORICAL_DRIFT_REGISTER.yaml"

# Receipt fields that name a file elsewhere in the tree, so drift can be caught.
HASH_FIELD_TARGETS = {
    "dependency_core_sha256": "packages/cir-python/src/akc_cir/dependency.py",
    "recompilation_core_sha256": "packages/cir-python/src/akc_cir/recompilation.py",
    "semantic_diff_core_sha256": "packages/cir-python/src/akc_cir/semantic_diff.py",
    "identity_module_sha256": "packages/cir-python/src/akc_cir/identity.py",
}


def load_drift_register() -> dict[tuple[str, str], dict[str, Any]]:
    """Declared drift, keyed by (receipt path, pinned field).

    An absent register is not an error -- it means nothing has been declared,
    so every drift is undeclared, which is the strict reading.
    """
    if not DRIFT_REGISTER.exists():
        return {}
    document = yaml.safe_load(DRIFT_REGISTER.read_text(encoding="utf-8")) or {}
    return {
        (entry["path"], entry["field"]): entry
        for entry in document.get("drifted_receipts", []) or []
    }


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 -- git from PATH is intended
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unavailable"


def dependency_fingerprint() -> dict[str, Any]:
    """Record the installed package set so a timing can be re-sited.

    The red-team's X5 finding is that no lockfile hash existed. `pip freeze` is
    not a lockfile, and it is not claimed to be one -- it is a record of what was
    installed when the numbers were produced, which is strictly more than
    nothing and is labelled as such.
    """
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        frozen = out.stdout
    except (subprocess.SubprocessError, OSError) as exc:
        return {"available": False, "reason": str(exc)}
    return {
        "available": True,
        "method": "pip freeze at manifest time; not a lockfile",
        "package_count": len([ln for ln in frozen.splitlines() if ln.strip()]),
        "sha256": "sha256:" + hashlib.sha256(frozen.encode("utf-8")).hexdigest(),
    }


def describe_receipt(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }
    if path.suffix != ".json":
        return record
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        record["parse"] = f"UNPARSEABLE: {exc}"
        return record
    if not isinstance(document, dict):
        return record

    for field in ("schema", "generated_at", "seed", "primary_success", "evidence_class"):
        if field in document:
            record[field] = document[field]

    # Self-hash: does the receipt's own recorded digest still describe it?
    if "receipt_sha256" in document:
        without = {k: v for k, v in document.items() if k != "receipt_sha256"}
        record["self_hash_recomputes"] = canonical_sha256(without) == document["receipt_sha256"]

    drift: list[dict[str, Any]] = []
    for field, target in HASH_FIELD_TARGETS.items():
        if field not in document:
            continue
        source = ROOT / target
        if not source.exists():
            drift.append({"field": field, "target": target, "state": "MISSING"})
            continue
        live = sha256_file(source)
        drift.append(
            {
                "field": field,
                "target": target,
                "recorded": document[field],
                "live": live,
                "state": "UNCHANGED" if live == document[field] else "DRIFTED",
            }
        )
    if drift:
        record["code_pins"] = drift
    return record


def describe_experiment(directory: Path) -> dict[str, Any]:
    protocols = sorted(p for p in directory.glob("*.md"))
    script_dir = directory / "scripts"
    receipt_dir = directory / "receipts"
    scripts = sorted(script_dir.glob("*.py")) if script_dir.is_dir() else []
    receipts = sorted(receipt_dir.glob("*")) if receipt_dir.is_dir() else []

    commands = [
        {
            "script": str(s.relative_to(ROOT)).replace("\\", "/"),
            "command": (
                f"python {str(s.relative_to(ROOT)).replace(chr(92), '/')} "
                f"--output <receipt path>"
            ),
            "note": (
                "argument list is the script's own argparse; see --help. Scripts "
                "that take a frozen manifest or seal require those paths too."
            ),
        }
        for s in scripts
        if not s.name.startswith("__")
    ]

    return {
        "experiment": directory.name,
        "protocols": [
            {"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(p)}
            for p in protocols
        ],
        "scripts": [
            {"path": str(s.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(s)}
            for s in scripts
            if not s.name.startswith("__")
        ],
        "receipts": [describe_receipt(r) for r in receipts if r.is_file()],
        "commands": commands,
        "counts": {
            "protocols": len(protocols),
            "scripts": len(commands),
            "receipts": len([r for r in receipts if r.is_file()]),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "repro" / "EXPERIMENT_MANIFEST.json",
    )
    parser.add_argument("--fail-on-drift", action="store_true")
    args = parser.parse_args()

    experiments = [
        describe_experiment(d)
        for d in sorted(EXPERIMENTS.iterdir())
        if d.is_dir() and not d.name.startswith(".")
    ]

    # A drifted pin is a fact about history, never repaired by editing the
    # receipt. What matters is whether it was *declared*: an undeclared drift may
    # mean a live claim is citing stale code, and that is the failure condition.
    declared = load_drift_register()
    drifted_declared: list[dict[str, Any]] = []
    drifted_undeclared: list[str] = []
    unverified_self_hash: list[str] = []
    for experiment in experiments:
        for receipt in experiment["receipts"]:
            for pin in receipt.get("code_pins", []):
                if pin["state"] == "UNCHANGED":
                    continue
                key = (receipt["path"], pin["field"])
                entry = declared.get(key)
                if entry is None:
                    drifted_undeclared.append(
                        f"{receipt['path']}::{pin['field']} -> {pin['state']}"
                    )
                    continue
                drifted_declared.append(
                    {
                        "receipt": receipt["path"],
                        "field": pin["field"],
                        "state": pin["state"],
                        "claim_carrying": bool(entry.get("claim_carrying")),
                        "superseded_by": entry.get("superseded_by"),
                        "claim_states_the_drift": entry.get("claim_states_the_drift"),
                        "reason": " ".join(str(entry.get("reason", "")).split()),
                    }
                )
            if receipt.get("self_hash_recomputes") is False:
                unverified_self_hash.append(receipt["path"])

    manifest = {
        "schema": "tavonel.experiment-manifest.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "note": (
                "Single uninstrumented desktop host under unknown background load. "
                "Wall-clock figures are order-of-magnitude, not benchmarks."
            ),
            "dependencies": dependency_fingerprint(),
        },
        "experiments": experiments,
        "experiment_count": len(experiments),
        "receipt_count": sum(e["counts"]["receipts"] for e in experiments),
        "code_pin_drift_undeclared": drifted_undeclared,
        "code_pin_drift_declared_historical": drifted_declared,
        "drift_register_path": "docs/repro/HISTORICAL_DRIFT_REGISTER.yaml",
        "drift_register_sha256": (
            sha256_file(DRIFT_REGISTER) if DRIFT_REGISTER.exists() else None
        ),
        "receipts_whose_self_hash_does_not_recompute": unverified_self_hash,
        "external_gpu_cost_usd": 0.0,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"experiments: {manifest['experiment_count']}")
    print(f"receipts:    {manifest['receipt_count']}")
    print(f"code pin drift, declared historical: {len(drifted_declared)}")
    for entry in drifted_declared:
        carrying = "CLAIM-CARRYING" if entry["claim_carrying"] else "superseded"
        print(f"  declared  {entry['receipt']}::{entry['field']} ({carrying})")
    print(f"code pin drift, UNDECLARED: {len(drifted_undeclared)}")
    for entry in drifted_undeclared:
        print(f"  UNDECLARED {entry}")
    print(f"receipts whose self-hash does not recompute: {len(unverified_self_hash)}")
    print(f"wrote {args.output}")
    # Only undeclared drift fails. Declared historical drift is the repository
    # behaving correctly: the measurement happened, the code moved, and both
    # facts are on the record.
    if args.fail_on_drift and drifted_undeclared:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
