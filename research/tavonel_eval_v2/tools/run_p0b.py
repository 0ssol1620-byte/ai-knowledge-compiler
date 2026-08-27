#!/usr/bin/env python3
"""P0b driver: deterministic identity, facet-typed invalidation, independent oracle.

Three processes per pair, none importing either of the others, and a driver that
imports none of the three. Static independence and identity-scope evidence are
collected before the first pair runs.

The P0 v1 files are not read for results and are not written to. The only P0 v1
artifacts this touches are the canonical documents, as input.
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

SELECTIVE = NS / "compiler" / "selective_build_p0b.py"
FACETS_MODULE = NS / "facets" / "facets.py"
ORACLE = NS / "oracle" / "independent_full_build_p0b.py"
COMPARATOR = NS / "comparator" / "compare_states_p0b.py"

#: P0b protocol section 2. Importing any of these is running the mechanism the
#: protocol excludes, which is the defect INC-V2-003 records.
FUZZY_IDENTITY_SYMBOLS = frozenset(
    {
        "diff_documents",
        "assign_one_to_one",
        "LogicalIdentityResolver",
        "LogicalMatch",
        "LogicalUnitFingerprint",
    }
)

#: P0b protocol section 5, the pre-registered prediction. Not supplied to the
#: implementation; compared against what the recorder observed.
PREDICTED_SENSITIVITY = {
    "section": ["LEXICAL"],
    "semantic-summary": ["SEMANTIC"],
    "document-index": ["STRUCTURAL"],
    "structure-map": ["STRUCTURAL"],
    "topic-bucket": ["STRUCTURAL"],
}


def imports_of(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    symbols: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
            symbols.setdefault(node.module, []).extend(alias.name for alias in node.names)
    return {
        "modules": sorted(modules),
        "symbols": {module: sorted(names) for module, names in sorted(symbols.items())},
        "non_stdlib_modules": sorted(
            name for name in modules if name not in sys.stdlib_module_names
        ),
    }


def identity_scope_evidence() -> dict[str, Any]:
    engine = imports_of(SELECTIVE)
    helper = imports_of(FACETS_MODULE)
    akc_symbols = sorted(
        {
            name
            for source in (engine["symbols"], helper["symbols"])
            for module, names in source.items()
            if module.startswith("akc_cir")
            for name in names
        }
    )
    return {
        "selective_engine": rel(SELECTIVE),
        "selective_engine_sha256": sha_file(SELECTIVE),
        "facets_module": rel(FACETS_MODULE),
        "facets_module_sha256": sha_file(FACETS_MODULE),
        "akc_cir_symbols_imported": akc_symbols,
        "forbidden_symbols": sorted(FUZZY_IDENTITY_SYMBOLS),
        "forbidden_symbols_present": sorted(set(akc_symbols) & FUZZY_IDENTITY_SYMBOLS),
        "identity_rule": "deterministic explicit-path equality",
    }


def static_independence() -> dict[str, Any]:
    oracle = imports_of(ORACLE)
    comparator = imports_of(COMPARATOR)
    return {
        "oracle": {
            "path": rel(ORACLE),
            "sha256": sha_file(ORACLE),
            "modules": oracle["modules"],
            "non_stdlib_modules": oracle["non_stdlib_modules"],
            "imports_akc_cir": "akc_cir" in oracle["modules"],
            "imports_facets": "facets" in oracle["modules"],
        },
        "comparator": {
            "path": rel(COMPARATOR),
            "sha256": sha_file(COMPARATOR),
            "modules": comparator["modules"],
            "non_stdlib_modules": comparator["non_stdlib_modules"],
            "imports_either_engine": any(
                name in {"akc_cir", "facets", "selective_build_p0b", "independent_full_build_p0b"}
                for name in comparator["modules"]
            ),
        },
    }


def guard_probe(work: Path) -> dict[str, Any]:
    probe = (
        "import runpy, sys, json\n"
        "sys.argv = ['oracle', '--after', 'x', '--output', 'y']\n"
        "runpy.run_path(r'''" + str(ORACLE) + "''')\n"
        "for name in ('akc_cir', 'facets'):\n"
        "    try:\n"
        "        __import__(name)\n"
        "        print(json.dumps({'module': name, 'blocked': False}))\n"
        "    except ImportError:\n"
        "        print(json.dumps({'module': name, 'blocked': True}))\n"
    )
    work.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=False,
    )
    rows = [json.loads(line) for line in completed.stdout.splitlines() if line.startswith("{")]
    return {
        "exit_code": completed.returncode,
        "results": rows,
        "all_blocked": bool(rows) and all(row["blocked"] for row in rows),
        "stderr_tail": completed.stderr.strip().splitlines()[-3:],
    }


def launch(argv: list[str], *, isolated: bool) -> tuple[int, str, str, float]:
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


def run(manifest: Path, output: Path) -> int:
    corpus = json.loads(manifest.read_text(encoding="utf-8"))
    out_root = NS / "artifacts" / "development" / "p0b"
    selective_root = out_root / "selective"
    oracle_root = out_root / "oracle"
    compare_root = out_root / "comparison"
    forensic_root = out_root / "forensic"

    identity_scope = identity_scope_evidence()
    static = static_independence()
    probe = guard_probe(out_root / "work")

    rows: list[dict[str, Any]] = []
    started_at = now()

    for pair in corpus["pairs"]:
        pair_id = pair["pair_id"]
        selective_out = selective_root / (pair_id + ".json")
        oracle_out = oracle_root / (pair_id + ".json")
        compare_out = compare_root / (pair_id + ".json")

        s_code, s_out, s_err, s_wall = launch(
            [
                str(SELECTIVE),
                "--before",
                str(ROOT / pair["before"]["path"]),
                "--after",
                str(ROOT / pair["after"]["path"]),
                "--output",
                str(selective_out),
            ],
            isolated=False,
        )
        o_code, o_out, o_err, o_wall = launch(
            [
                str(ORACLE),
                "--after",
                str(ROOT / pair["after"]["path"]),
                "--output",
                str(oracle_out),
            ],
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
                    "selective_stderr": s_err.strip().splitlines()[-5:],
                    "oracle_stderr": o_err.strip().splitlines()[-5:],
                }
            )
            continue

        c_code, c_out, c_err, _ = launch(
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
            for name, source in (
                ("selective.json", selective_out),
                ("oracle.json", oracle_out),
                ("comparison.json", compare_out),
            ):
                (keep / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            (keep / "streams.json").write_text(
                json.dumps(
                    {
                        "selective_stdout": s_out,
                        "selective_stderr": s_err,
                        "oracle_stdout": o_out,
                        "oracle_stderr": o_err,
                        "comparator_stdout": c_out,
                        "comparator_stderr": c_err,
                        "comparator_exit": c_code,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        by_kind: dict[str, dict[str, list[str]]] = {}
        for artifact, info in selective["artifact_detail"].items():
            by_kind.setdefault(artifact.split(":")[0], {}).setdefault(info["state"], []).append(
                artifact
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
                "before_canonical_digest": pair["before_canonical_digest"],
                "after_canonical_digest": pair["after_canonical_digest"],
                "identity_outcomes": selective["identity_outcomes"],
                "changed_units": selective["changed_units"],
                "changed_facets": selective["changed_facets"],
                "observed_sensitivity_by_kind": selective["observed_sensitivity_by_kind"],
                "artifact_inventory_size": len(selective["artifact_inventory"]),
                "selective_rebuild_set": selective["selective_rebuild_set"],
                "carried_forward_set": selective["carried_forward_set"],
                "unverifiable_set": selective["unverifiable_set"],
                "retired_set": selective["retired_set"],
                "unnecessary_rebuild_set": selective["unnecessary_rebuild_set"],
                "traversal_fingerprint_disagreements": selective[
                    "traversal_fingerprint_disagreements"
                ],
                "state_by_kind": by_kind,
                "full_rebuild_artifact_set_size": len(oracle["artifact_inventory"]),
                "selective_final_state_hash": selective["state_hash"],
                "full_rebuild_final_state_hash": oracle["state_hash"],
                "equivalence_verdict": "EQUIVALENT" if comparison["equivalent"] else "DIVERGED",
                "stale_left_behind": comparison["stale_left_behind"],
                "diverged": comparison["diverged"],
                "missing_from_selective": comparison["missing_from_selective"],
                "extra_in_selective": comparison["extra_in_selective"],
                "rebuilt_fraction": selective["rebuilt_fraction"],
                "work_avoided_fraction": selective["work_avoided_fraction"],
                "selective_duration_ms": selective["duration_ms"],
                "oracle_duration_ms": oracle["duration_ms"],
                "selective_wall_ms": s_wall,
                "oracle_wall_ms": o_wall,
                "selective_pid": selective["pid"],
                "oracle_pid": oracle["independence"]["pid"],
                "distinct_processes": selective["pid"] != oracle["independence"]["pid"],
                "oracle_akc_cir_imported": oracle["independence"]["akc_cir_imported"],
                "oracle_facets_imported": oracle["independence"]["facets_imported"],
                "oracle_cir_python_on_path": oracle["independence"]["cir_python_on_path"],
                "oracle_non_stdlib_modules": oracle["independence"]["non_stdlib_modules_loaded"],
            }
        )

    scored = [row for row in rows if "equivalence_verdict" in row]
    failed = [row for row in rows if row.get("state") == "ENGINE_FAILED"]
    natural = [row for row in scored if row["group"] == "natural"]
    lexical = [row for row in scored if row["group"] == "lexical_positive_control"]
    structural = [row for row in scored if row["group"] == "structural_positive_control"]
    equivalent = [row for row in scored if row["equivalence_verdict"] == "EQUIVALENT"]
    stale_total = sum(len(row["stale_left_behind"]) for row in scored)

    observed: dict[str, set[str]] = {}
    for row in scored:
        for kind, facets in row["observed_sensitivity_by_kind"].items():
            observed.setdefault(kind, set()).update(facets)
    observed_sorted = {kind: sorted(values) for kind, values in sorted(observed.items())}
    sensitivity_mismatch = {
        kind: {"predicted": PREDICTED_SENSITIVITY.get(kind), "observed": values}
        for kind, values in observed_sorted.items()
        if PREDICTED_SENSITIVITY.get(kind) != values
    }

    def kind_states(row: dict[str, Any], kind: str) -> dict[str, list[str]]:
        return row["state_by_kind"].get(kind, {})

    lexical_ok = [
        row
        for row in lexical
        if not kind_states(row, "section").get("CARRIED")
        and kind_states(row, "section").get("REBUILT")
        and not kind_states(row, "semantic-summary").get("REBUILT")
        and kind_states(row, "semantic-summary").get("CARRIED")
    ]
    structural_ok = [
        row
        for row in structural
        if not kind_states(row, "section").get("REBUILT")
        and not kind_states(row, "semantic-summary").get("REBUILT")
        and kind_states(row, "document-index").get("REBUILT")
        and kind_states(row, "structure-map").get("REBUILT")
    ]

    carried_with_moved_fingerprint = [
        item
        for row in scored
        for item in row["traversal_fingerprint_disagreements"]
        if item["fingerprint_says_stale"] and not item["traversal_says_stale"]
    ]

    gates = {
        "G_P0B_IDENTITY_SCOPE": {
            "passed": not identity_scope["forbidden_symbols_present"]
            and all(row["identity_outcomes"]["unresolved"] == 0 for row in scored),
            "forbidden_symbols_present": identity_scope["forbidden_symbols_present"],
            "unresolved_total": sum(row["identity_outcomes"]["unresolved"] for row in scored),
        },
        "G_P0B_ISOLATION": {
            "passed": not static["oracle"]["non_stdlib_modules"]
            and not static["oracle"]["imports_akc_cir"]
            and not static["oracle"]["imports_facets"]
            and not static["comparator"]["imports_either_engine"]
            and probe["all_blocked"]
            and all(row["distinct_processes"] for row in scored)
            and not any(row["oracle_akc_cir_imported"] for row in scored)
            and not any(row["oracle_facets_imported"] for row in scored)
            and not any(row["oracle_cir_python_on_path"] for row in scored)
        },
        "G_P0B_SCALE": {
            "passed": len(natural) >= 20 and len({row["source_family"] for row in natural}) >= 2,
            "natural_pairs": len(natural),
            "families": sorted({row["source_family"] for row in natural}),
        },
        "G_P0B_SENSITIVITY_OBSERVED": {
            "passed": not sensitivity_mismatch
            and not any(row["unverifiable_set"] for row in scored),
            "observed": observed_sorted,
            "predicted": PREDICTED_SENSITIVITY,
            "mismatch": sensitivity_mismatch,
            "unverifiable_artifacts": sum(len(row["unverifiable_set"]) for row in scored),
        },
        "G_P0B_LEXICAL_DISCRIMINATION": {
            "passed": bool(lexical) and len(lexical_ok) == len(lexical),
            "controls": len(lexical),
            "discriminating": len(lexical_ok),
        },
        "G_P0B_STRUCTURAL_DISCRIMINATION": {
            "passed": bool(structural) and len(structural_ok) == len(structural),
            "controls": len(structural),
            "discriminating": len(structural_ok),
        },
        "G_P0B_FINGERPRINT_AGREEMENT": {
            "passed": not carried_with_moved_fingerprint,
            "carried_with_moved_fingerprint": carried_with_moved_fingerprint,
            "disagreements_recorded": sum(
                len(row["traversal_fingerprint_disagreements"]) for row in scored
            ),
        },
        "G_P0B_EQUIVALENCE": {
            "passed": bool(scored)
            and len(equivalent) == len(scored)
            and stale_total == 0
            and not failed,
            "scored_pairs": len(scored),
            "equivalent_pairs": len(equivalent),
            "stale_left_behind_total": stale_total,
            "engine_failures": len(failed),
        },
        "G_P0B_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }

    body: dict[str, Any] = {
        "schema": "tavonel.v2.p0b_mechanics.v1",
        "protocol": "P0b_recompilation_mechanics",
        "split": "development",
        "started_at": started_at,
        "ended_at": now(),
        "protocol_sha256": json.loads(
            (NS / "receipts" / "p0b-protocol-freeze.json").read_text(encoding="utf-8")
        )["protocol_sha256"],
        "corpus_manifest": rel(manifest),
        "corpus_manifest_file_sha256": sha_file(manifest),
        "driver_sha256": sha_file(Path(__file__).resolve()),
        "identity_scope": identity_scope,
        "static_independence": static,
        "runtime_guard_probe": probe,
        "output_roots_disjoint": len({str(selective_root), str(oracle_root), str(compare_root)})
        == 3,
        "pair_count": len(rows),
        "natural_pair_count": len(natural),
        "lexical_control_count": len(lexical),
        "structural_control_count": len(structural),
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
    parser.add_argument(
        "--manifest", type=Path, default=NS / "receipts" / "p0b-corpus-manifest.json"
    )
    parser.add_argument("--output", type=Path, default=NS / "receipts" / "p0b-mechanics.json")
    args = parser.parse_args()
    return run(args.manifest, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
