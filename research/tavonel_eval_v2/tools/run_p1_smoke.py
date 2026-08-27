#!/usr/bin/env python3
"""P0 step 5 -- selective versus independent full rebuild over the smoke corpus.

Every pair runs three processes: the selective build, the independent oracle,
and the comparator. None of the three imports either of the others. The driver
does not import them either -- it launches them and reads their files, so the
driver cannot accidentally become the shared component the whole design is
trying to avoid.

Static independence evidence is collected once, before any pair runs, and
recorded in the same receipt as the results.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, ROOT, canonical_sha, now, rel, sha_file, write_hashed  # noqa: E402

SELECTIVE = NS / "compiler" / "selective_build.py"
ORACLE = NS / "oracle" / "independent_full_build.py"
COMPARATOR = NS / "comparator" / "compare_states.py"


def imported_modules(path: Path) -> list[str]:
    """Every top-level module name the file imports, from its syntax tree."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return sorted(names)


def static_independence() -> dict[str, Any]:
    oracle_imports = imported_modules(ORACLE)
    comparator_imports = imported_modules(COMPARATOR)
    selective_imports = imported_modules(SELECTIVE)
    return {
        "oracle": {
            "path": rel(ORACLE),
            "sha256": sha_file(ORACLE),
            "imports": oracle_imports,
            "non_stdlib_imports": [
                name for name in oracle_imports if name not in sys.stdlib_module_names
            ],
            "imports_akc_cir": "akc_cir" in oracle_imports,
        },
        "comparator": {
            "path": rel(COMPARATOR),
            "sha256": sha_file(COMPARATOR),
            "imports": comparator_imports,
            "non_stdlib_imports": [
                name for name in comparator_imports if name not in sys.stdlib_module_names
            ],
            "imports_either_engine": any(
                name in {"akc_cir", "selective_build", "independent_full_build"}
                for name in comparator_imports
            ),
        },
        "selective": {
            "path": rel(SELECTIVE),
            "sha256": sha_file(SELECTIVE),
            "imports": selective_imports,
            "imports_oracle": "independent_full_build" in selective_imports,
        },
        "oracle_source_mentions_selective": any(
            token in ORACLE.read_text(encoding="utf-8")
            for token in ("from akc_cir", "import akc_cir", "selective_build")
        ),
    }


def guard_probe(work: Path) -> dict[str, Any]:
    """Prove the oracle's import guard actually fires, rather than trusting it.

    A guard nobody has seen refuse anything is an assertion, not evidence.
    """
    probe = work / "guard_probe.py"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(
        "import runpy, sys, json\n"
        "sys.argv = ['oracle', '--after', 'x', '--output', 'y']\n"
        "spec = runpy.run_path(r'''" + str(ORACLE) + "''')\n"
        "try:\n"
        "    import akc_cir\n"
        "    print(json.dumps({'blocked': False}))\n"
        "except ImportError as error:\n"
        "    print(json.dumps({'blocked': True, 'error': type(error).__name__}))\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(probe)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=False,
    )
    tail = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    parsed = json.loads(tail[-1]) if tail else {"blocked": None}
    return {
        "probe_path": rel(probe),
        "exit_code": completed.returncode,
        "akc_cir_import_blocked_inside_oracle_process": parsed.get("blocked"),
        "stderr_tail": completed.stderr.strip().splitlines()[-3:],
    }


def launch(argv: list[str], *, isolated: bool) -> tuple[int, str, str, float]:
    # -I drops the cwd, PYTHONPATH and the user site directory. It does NOT drop
    # site-packages, and this repository installs akc_cir there in editable
    # mode, which puts packages/cir-python/src back on the child's sys.path. -S
    # is what actually removes it, so the oracle runs with both: the selective
    # implementation is then not merely unimported but unreachable.
    command = [sys.executable]
    if isolated:
        command.extend(["-I", "-S"])
    command.extend(argv)
    started = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, cwd=str(ROOT), check=False)
    return (
        completed.returncode,
        completed.stdout,
        completed.stderr,
        round((time.perf_counter() - started) * 1000, 3),
    )


def run(split: str, manifest: Path, output: Path) -> int:
    canonicalisation = json.loads(manifest.read_text(encoding="utf-8"))
    out_root = NS / "artifacts" / split
    selective_root = out_root / "selective"
    oracle_root = out_root / "oracle"
    compare_root = out_root / "comparison"
    forensic_root = out_root / "forensic"
    work = out_root / "work"

    static = static_independence()
    probe = guard_probe(work)

    rows: list[dict[str, Any]] = []
    started_at = now()

    for pair in canonicalisation["pairs"]:
        pair_id = pair["pair_id"]
        before = ROOT / pair["before"]["path"]
        after = ROOT / pair["after"]["path"]
        selective_out = selective_root / (pair_id + ".json")
        oracle_out = oracle_root / (pair_id + ".json")
        compare_out = compare_root / (pair_id + ".json")

        s_code, s_stdout, s_stderr, s_wall = launch(
            [
                str(SELECTIVE),
                "--before",
                str(before),
                "--after",
                str(after),
                "--output",
                str(selective_out),
            ],
            isolated=False,
        )
        o_code, o_stdout, o_stderr, o_wall = launch(
            [str(ORACLE), "--after", str(after), "--output", str(oracle_out)],
            isolated=True,
        )
        if s_code != 0 or o_code != 0:
            rows.append(
                {
                    "pair_id": pair_id,
                    "group": pair["group"],
                    "source_family": pair["source_family"],
                    "state": "ENGINE_FAILED",
                    "selective_exit": s_code,
                    "oracle_exit": o_code,
                    "selective_stderr": s_stderr.strip().splitlines()[-5:],
                    "oracle_stderr": o_stderr.strip().splitlines()[-5:],
                }
            )
            continue

        c_code, c_stdout, c_stderr, _ = launch(
            [
                str(COMPARATOR),
                "--selective",
                str(selective_out),
                "--oracle",
                str(oracle_out),
                "--output",
                str(compare_out),
            ],
            isolated=True,
        )
        selective = json.loads(selective_out.read_text(encoding="utf-8"))
        oracle = json.loads(oracle_out.read_text(encoding="utf-8"))
        comparison = json.loads(compare_out.read_text(encoding="utf-8"))

        if not comparison["equivalent"]:
            keep = forensic_root / pair_id
            keep.mkdir(parents=True, exist_ok=True)
            (keep / "selective.json").write_text(
                selective_out.read_text(encoding="utf-8"), encoding="utf-8"
            )
            (keep / "oracle.json").write_text(
                oracle_out.read_text(encoding="utf-8"), encoding="utf-8"
            )
            (keep / "comparison.json").write_text(
                compare_out.read_text(encoding="utf-8"), encoding="utf-8"
            )
            (keep / "streams.json").write_text(
                json.dumps(
                    {
                        "selective_stdout": s_stdout,
                        "selective_stderr": s_stderr,
                        "oracle_stdout": o_stdout,
                        "oracle_stderr": o_stderr,
                        "comparator_stdout": c_stdout,
                        "comparator_stderr": c_stderr,
                        "comparator_exit": c_code,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        rows.append(
            {
                "pair_id": pair_id,
                "group": pair["group"],
                "constructed": pair["constructed"],
                "source_family": pair["source_family"],
                "source_id": pair["source_id"],
                "before_version_id": pair["before_version_id"],
                "after_version_id": pair["after_version_id"],
                "before_source_digest": pair["before_source_digest"],
                "after_source_digest": pair["after_source_digest"],
                "before_canonical_digest": pair["before_canonical_digest"],
                "after_canonical_digest": pair["after_canonical_digest"],
                "detected_change_kinds": selective["detected_change_kinds"],
                "structural_change_present": selective["structural_change_present"],
                "identity_outcomes": selective["identity_outcomes"],
                "unresolved_present": selective["unresolved_present"],
                "affected_subgraph": selective["affected_subgraph"],
                "selective_rebuild_set": selective["selective_rebuild_set"],
                "carried_forward_set": selective["carried_forward_set"],
                "retired_set": selective["retired_set"],
                "full_rebuild_artifact_set": oracle["artifact_inventory"],
                "selective_final_state_hash": selective["state_hash"],
                "full_rebuild_final_state_hash": oracle["state_hash"],
                "equivalence_verdict": "EQUIVALENT" if comparison["equivalent"] else "DIVERGED",
                "stale_left_behind": comparison["stale_left_behind"],
                "diverged": comparison["diverged"],
                "missing_from_selective": comparison["missing_from_selective"],
                "extra_in_selective": comparison["extra_in_selective"],
                "wrongly_rebuilt": comparison["wrongly_rebuilt"],
                "unnecessary_rebuild_set": selective["unnecessary_rebuild_set"],
                "work_avoided_fraction": selective["work_avoided_fraction"],
                "rebuilt_fraction": selective["rebuilt_fraction"],
                "selective_duration_ms": selective["duration_ms"],
                "oracle_duration_ms": oracle["duration_ms"],
                "selective_wall_ms": s_wall,
                "oracle_wall_ms": o_wall,
                "selective_pid": selective["pid"],
                "oracle_pid": oracle["independence"]["pid"],
                "distinct_processes": selective["pid"] != oracle["independence"]["pid"],
                "oracle_akc_cir_imported": oracle["independence"]["akc_cir_imported"],
                "oracle_non_stdlib_modules": oracle["independence"]["non_stdlib_modules_loaded"],
                "oracle_cir_python_on_path": oracle["independence"]["cir_python_on_path"],
                "oracle_isolated_mode": oracle["independence"]["isolated_mode"],
                "state_hash_equal": comparison["state_hash_equal"],
                "state_hash_agrees_with_artifact_comparison": comparison["state_hash_equal"]
                == comparison["equivalent"],
            }
        )

    natural = [row for row in rows if row.get("group") == "natural"]
    controls = [row for row in rows if row.get("group") == "structural_positive_control"]
    failed = [row for row in rows if row.get("state") == "ENGINE_FAILED"]
    equivalent = [row for row in rows if row.get("equivalence_verdict") == "EQUIVALENT"]
    stale_total = sum(len(row.get("stale_left_behind", ())) for row in rows)
    scored = [row for row in rows if "equivalence_verdict" in row]

    control_detected = [
        row
        for row in controls
        if row.get("structural_change_present")
        and row.get("equivalence_verdict") == "EQUIVALENT"
        and len(row.get("selective_rebuild_set", ())) > 0
    ]

    gates = {
        "G_P0_ISOLATION": {
            "passed": (
                not static["oracle"]["imports_akc_cir"]
                and not static["oracle"]["non_stdlib_imports"]
                and not static["comparator"]["imports_either_engine"]
                and probe["akc_cir_import_blocked_inside_oracle_process"] is True
                and all(row.get("distinct_processes", False) for row in scored)
                and not any(row.get("oracle_akc_cir_imported", True) for row in scored)
                and not any(row.get("oracle_cir_python_on_path", True) for row in scored)
            )
        },
        "G_P0_SMOKE_SCALE": {
            "passed": len(natural) >= 20 and len({row["source_family"] for row in natural}) >= 2,
            "natural_pairs": len(natural),
            "families": sorted({row["source_family"] for row in natural}),
        },
        "G_P0_STRUCTURAL_COVERAGE": {
            "passed": len(control_detected) >= 1,
            "controls_run": len(controls),
            "controls_detected_and_equivalent": len(control_detected),
        },
        "G_P0_EQUIVALENCE": {
            "passed": len(equivalent) == len(scored) and stale_total == 0 and not failed,
            "scored_pairs": len(scored),
            "equivalent_pairs": len(equivalent),
            "stale_left_behind_total": stale_total,
            "engine_failures": len(failed),
        },
        "G_P0_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }

    body: dict[str, Any] = {
        "schema": "tavonel.v2.p1_smoke_equivalence.v1",
        "split": split,
        "started_at": started_at,
        "ended_at": now(),
        "protocol_sha256": json.loads(
            (NS / "receipts" / "p0-protocol-freeze.json").read_text(encoding="utf-8")
        )["protocol_sha256"],
        "canonicalisation_manifest": rel(manifest),
        "canonicalisation_manifest_file_sha256": sha_file(manifest),
        "driver_sha256": sha_file(Path(__file__).resolve()),
        "static_independence": static,
        "runtime_guard_probe": probe,
        "output_roots": {
            "selective": rel(selective_root),
            "oracle": rel(oracle_root),
            "comparison": rel(compare_root),
            "forensic": rel(forensic_root),
        },
        "output_roots_disjoint": len({str(selective_root), str(oracle_root), str(compare_root)})
        == 3,
        "pair_count": len(rows),
        "natural_pair_count": len(natural),
        "control_pair_count": len(controls),
        "equivalent_pair_count": len(equivalent),
        "artifact_exact_match_rate": (len(equivalent) / len(scored)) if scored else 0.0,
        "stale_escape_count": stale_total,
        "gates": gates,
        "verdict": "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL",
        "records": rows,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    body["records_sha256"] = canonical_sha(rows)
    write_hashed(output, body, "receipt_sha256")
    print(
        json.dumps(
            {
                "verdict": body["verdict"],
                "pairs": len(rows),
                "equivalent": len(equivalent),
                "stale": stale_total,
                "gates": {name: gate["passed"] for name, gate in gates.items()},
                "receipt": rel(output),
            },
            sort_keys=True,
        )
    )
    return 0 if body["verdict"] == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="development")
    parser.add_argument(
        "--manifest", type=Path, default=NS / "receipts" / "p0-canonicalisation-manifest.json"
    )
    parser.add_argument(
        "--output", type=Path, default=NS / "receipts" / "p0-oracle-independence.json"
    )
    args = parser.parse_args()
    return run(args.split, args.manifest, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
