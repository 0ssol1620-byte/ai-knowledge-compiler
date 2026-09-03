#!/usr/bin/env python3
"""Freeze the one-shot Family-B holdout seed without disclosing it."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EXP = ROOT / "research" / "experiments" / "H1-B-REAL-REVISION-01"


def sha256_bytes(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    seed_text = str(secrets.randbits(128))
    args.seed_file.parent.mkdir(parents=True, exist_ok=True)
    args.seed_file.write_text(seed_text, encoding="utf-8")

    prereg = {
        "schema": "tavonel.family-b-final-fresh-holdout-preregistration.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "seed_sha256": sha256_bytes(seed_text.encode("utf-8")),
        "protocol_sha256": file_sha256(EXP / "FINAL_FRESH_HOLDOUT_PROTOCOL_2026-08-19.md"),
        "runner_sha256": file_sha256(EXP / "scripts" / "final_fresh_holdout.py"),
        "change_generator_sha256": file_sha256(EXP / "scripts" / "change_space_sweep.py"),
        "topology_generator_sha256": file_sha256(
            EXP / "scripts" / "adversarial_topology_extension.py"
        ),
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
        "change_cases_per_class": 400,
        "topology_cases_per_cell": 200,
        "primary_criterion": (
            "every cell exact-equivalent to independent full rebuild; zero stale escapes"
        ),
        "seed_disclosed_before_run": False,
        "freeze_helper_sha256": file_sha256(Path(__file__)),
        "external_gpu_cost_usd": 0.0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(prereg, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("fresh holdout preregistration frozen; hidden seed stored outside repository")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
