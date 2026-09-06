#!/usr/bin/env python3
"""P0c driver: coverage attribution over the P0b mechanism.

Three processes per pair, none importing either of the others, and a driver that
imports none of the three. The receipt is written through the immutable plumbing
(INC-V2-005), so a second run of this file cannot destroy the first one's.

P0b is read for its corpus and for nothing else. Its receipt is not touched, its
result is not restated, and nothing here amends it.
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

from common import NS, ROOT, canonical_sha, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

SELECTIVE = NS / "compiler" / "selective_build_p0c.py"
COVERAGE_MODULE = NS / "facets" / "facet_coverage.py"
ORACLE = NS / "oracle" / "independent_full_build_p0c.py"
COMPARATOR = NS / "comparator" / "compare_states_p0c.py"
PROTOCOL = NS / "protocols" / "P0c_coverage_completeness.yaml"

FUZZY_IDENTITY_SYMBOLS = frozenset(
    {
        "diff_documents",
        "assign_one_to_one",
        "LogicalIdentityResolver",
        "LogicalMatch",
        "LogicalUnitFingerprint",
    }
)

#: Protocol section 7. Not supplied to the implementation.
PREDICTED_SENSITIVITY = {
    "section": ["LEXICAL"],
    "semantic-summary": ["SEMANTIC"],
    "document-index": ["STRUCTURAL"],
    "structure-map": ["STRUCTURAL"],
    "topic-bucket": ["STRUCTURAL"],
    "coverage-probe": ["UNCLASSIFIED"],
}

PRODUCTION_KINDS = (
    "section",
    "semantic-summary",
    "document-index",
    "structure-map",
    "topic-bucket",
)
CONTROL_KIND = "coverage-probe"


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
    helper = imports_of(COVERAGE_MODULE)
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
        "coverage_module": rel(COVERAGE_MODULE),
        "coverage_module_sha256": sha_file(COVERAGE_MODULE),
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
            "imports_coverage": "facet_coverage" in oracle["modules"],
        },
        "comparator": {
            "path": rel(COMPARATOR),
            "sha256": sha_file(COMPARATOR),
            "modules": comparator["modules"],
            "non_stdlib_modules": comparator["non_stdlib_modules"],
            "imports_either_engine": any(
                name
                in {
                    "akc_cir",
                    "facet_coverage",
                    "selective_build_p0c",
                    "independent_full_build_p0c",
                }
                for name in comparator["modules"]
            ),
        },
    }


def guard_probe() -> dict[str, Any]:
    probe = (
        "import runpy, sys, json\n"
        "sys.argv = ['oracle', '--after', 'x', '--output', 'y']\n"
        "runpy.run_path(r'''" + str(ORACLE) + "''')\n"
        "for name in ('akc_cir', 'facet_coverage'):\n"
        "    try:\n"
        "        __import__(name)\n"
        "        print(json.dumps({'module': name, 'blocked': False}))\n"
        "    except ImportError:\n"
        "        print(json.dumps({'module': name, 'blocked': True}))\n"
    )
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


def run(manifest: Path) -> int:
    corpus = json.loads(manifest.read_text(encoding="utf-8"))
    out_root = NS / "artifacts" / "development" / "p0c"
    selective_root = out_root / "selective"
    oracle_root = out_root / "oracle"
    compare_root = out_root / "comparison"
    forensic_root = out_root / "forensic"

    identity_scope = identity_scope_evidence()
    static = static_independence()
    probe = guard_probe()

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
                        "selective_stderr": s_err,
                        "oracle_stderr": o_err,
                        "comparator_stdout": c_out,
                        "comparator_stderr": c_err,
                        "comparator_exit": c_code,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        detail = selective["artifact_detail"]
        by_kind: dict[str, dict[str, list[str]]] = {}
        for artifact, info in detail.items():
            by_kind.setdefault(artifact.split(":")[0], {}).setdefault(info["state"], []).append(
                artifact
            )

        unclassified_by_kind: dict[str, list[str]] = {}
        for artifact, info in detail.items():
            if info["unclassified_fields"]:
                unclassified_by_kind.setdefault(artifact.split(":")[0], []).extend(
                    info["unclassified_fields"]
                )
        unclassified_by_kind = {
            kind: sorted(set(values)) for kind, values in sorted(unclassified_by_kind.items())
        }

        unproven = set(selective["coverage_unproven_set"])
        carried = set(selective["carried_forward_set"])
        rebuilt = set(selective["selective_rebuild_set"])
        proven_rebuilt = [artifact for artifact in rebuilt if artifact not in unproven]

        rows.append(
            {
                "pair_id": pair_id,
                "group": pair["group"],
                "corpus": pair.get("corpus", "p0b"),
                "source_family": pair.get("source_family"),
                "source_id": pair.get("source_id"),
                "identity_outcomes": selective["identity_outcomes"],
                "changed_units": selective["changed_units"],
                "changed_facets": selective["changed_facets"],
                "unclassified_source_change": selective["unclassified_source_change"],
                "observed_sensitivity_by_kind": selective["observed_sensitivity_by_kind"],
                "fields_read_by_kind": selective["fields_read_by_kind"],
                "unclassified_fields_by_kind": unclassified_by_kind,
                "artifact_inventory_size": len(selective["artifact_inventory"]),
                "selective_rebuild_set": sorted(rebuilt),
                "proven_coverage_rebuild_set": sorted(proven_rebuilt),
                "carried_forward_set": sorted(carried),
                "unverifiable_set": selective["unverifiable_set"],
                "coverage_unproven_set": sorted(unproven),
                "unproven_but_carried": sorted(unproven & carried),
                "state_by_kind": by_kind,
                "traversal_fingerprint_disagreements": selective[
                    "traversal_fingerprint_disagreements"
                ],
                "selective_final_state_hash": selective["state_hash"],
                "full_rebuild_final_state_hash": oracle["state_hash"],
                "equivalence_verdict": "EQUIVALENT" if comparison["equivalent"] else "DIVERGED",
                "judged_artifact_count": comparison["judged_artifact_count"],
                "refused_artifact_count": comparison["refused_artifact_count"],
                "stale_left_behind": comparison["stale_left_behind"],
                "diverged": comparison["diverged"],
                "missing_from_selective": comparison["missing_from_selective"],
                "extra_in_selective": comparison["extra_in_selective"],
                "rebuilt_fraction": selective["rebuilt_fraction"],
                "work_avoided_fraction": selective["work_avoided_fraction"],
                "selective_wall_ms": s_wall,
                "oracle_wall_ms": o_wall,
                "selective_pid": selective["pid"],
                "oracle_pid": oracle["independence"]["pid"],
                "distinct_processes": selective["pid"] != oracle["independence"]["pid"],
                "oracle_akc_cir_imported": oracle["independence"]["akc_cir_imported"],
                "oracle_cir_python_on_path": oracle["independence"]["cir_python_on_path"],
                "oracle_non_stdlib_modules": oracle["independence"]["non_stdlib_modules_loaded"],
            }
        )

    scored = [row for row in rows if "equivalence_verdict" in row]
    failed = [row for row in rows if row.get("state") == "ENGINE_FAILED"]
    natural = [row for row in scored if row["group"] == "natural"]
    equivalent = [row for row in scored if row["equivalence_verdict"] == "EQUIVALENT"]
    stale_total = sum(len(row["stale_left_behind"]) for row in scored)

    probes = [row for row in scored if row["group"] == "unclassified_access_probe"]
    usc_pos = [row for row in scored if row["group"] == "unclassified_source_change_positive"]
    usc_neg = [row for row in scored if row["group"] == "unclassified_source_change_negative"]

    # --- attribution: production builders must read only mapped fields --------
    production_unclassified = [
        {"pair_id": row["pair_id"], "kind": kind, "fields": fields}
        for row in scored
        for kind, fields in row["unclassified_fields_by_kind"].items()
        if kind in PRODUCTION_KINDS
    ]

    # --- the invariant itself -------------------------------------------------
    carry_violations = [
        {"pair_id": row["pair_id"], "artifacts": row["unproven_but_carried"]}
        for row in scored
        if row["unproven_but_carried"]
    ]

    # --- the probe control has to actually fire ------------------------------
    def probe_fired(row: dict[str, Any]) -> bool:
        states = row["state_by_kind"].get(CONTROL_KIND, {})
        return (
            bool(row["unclassified_fields_by_kind"].get(CONTROL_KIND))
            and not states.get("CARRIED")
            and any(artifact.startswith(CONTROL_KIND + ":") for artifact in row["unverifiable_set"])
        )

    probes_firing = [row for row in probes if probe_fired(row)]

    # --- the diagnostic ------------------------------------------------------
    pos_firing = [row for row in usc_pos if row["unclassified_source_change"]["fires"]]
    neg_firing = [row for row in usc_neg if row["unclassified_source_change"]["fires"]]
    natural_firing = [
        row["pair_id"] for row in natural if row["unclassified_source_change"]["fires"]
    ]

    global_rebuild_on_diagnostic = [
        {"pair_id": row["pair_id"], "rebuilt": row["proven_coverage_rebuild_set"]}
        for row in scored
        if row["unclassified_source_change"]["fires"] and row["proven_coverage_rebuild_set"]
    ]

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

    gates = {
        "G_P0C_ATTRIBUTION": {
            "passed": not production_unclassified,
            "production_kinds": list(PRODUCTION_KINDS),
            "unattributed_accesses_by_production_builders": production_unclassified,
        },
        "G_P0C_CARRY_BAN": {
            "passed": not carry_violations,
            "violations": carry_violations,
        },
        "G_P0C_PROBE_FIRES": {
            "passed": bool(probes) and len(probes_firing) == len(probes),
            "controls": len(probes),
            "firing": len(probes_firing),
        },
        "G_P0C_DIAGNOSTIC": {
            "passed": bool(usc_pos) and len(pos_firing) == len(usc_pos) and not neg_firing,
            "positive_controls": len(usc_pos),
            "positive_firing": len(pos_firing),
            "negative_controls": len(usc_neg),
            "negative_firing": len(neg_firing),
            "natural_pairs_firing": natural_firing,
        },
        "G_P0C_NO_GLOBAL_REBUILD": {
            "passed": not global_rebuild_on_diagnostic,
            "violations": global_rebuild_on_diagnostic,
        },
        "G_P0C_EQUIVALENCE": {
            "passed": bool(scored)
            and len(equivalent) == len(scored)
            and stale_total == 0
            and not failed,
            "scored_pairs": len(scored),
            "equivalent_pairs": len(equivalent),
            "stale_left_behind_total": stale_total,
            "engine_failures": len(failed),
        },
        "G_P0C_ISOLATION": {
            "passed": not static["oracle"]["non_stdlib_modules"]
            and not static["oracle"]["imports_akc_cir"]
            and not static["oracle"]["imports_coverage"]
            and not static["comparator"]["imports_either_engine"]
            and probe["all_blocked"]
            and all(row["distinct_processes"] for row in scored)
            and not any(row["oracle_akc_cir_imported"] for row in scored)
            and not any(row["oracle_cir_python_on_path"] for row in scored)
        },
        "G_P0C_SCALE": {
            "passed": len(natural) >= 20 and bool(probes) and bool(usc_pos) and bool(usc_neg),
            "natural_pairs": len(natural),
            "controls": {
                "unclassified_access_probe": len(probes),
                "unclassified_source_change_positive": len(usc_pos),
                "unclassified_source_change_negative": len(usc_neg),
            },
        },
        "G_P0C_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }

    body: dict[str, Any] = {
        "schema": "tavonel.v2.p0c_coverage_completeness.v1",
        "protocol": "P0c_coverage_completeness",
        "split": "development",
        "started_at": started_at,
        "ended_at": now(),
        "corpus_manifest": rel(manifest),
        "corpus_manifest_file_sha256": sha_file(manifest),
        "identity_scope": identity_scope,
        "static_independence": static,
        "runtime_guard_probe": probe,
        "output_roots_disjoint": len({str(selective_root), str(oracle_root), str(compare_root)})
        == 3,
        "pair_count": len(rows),
        "natural_pair_count": len(natural),
        "equivalent_pair_count": len(equivalent),
        "stale_escape_count": stale_total,
        "observed_sensitivity_by_kind": observed_sorted,
        "predicted_sensitivity_by_kind": PREDICTED_SENSITIVITY,
        "sensitivity_prediction_mismatch": sensitivity_mismatch,
        "heading_projection_change_effect": (
            "recorded by comparing this run's rebuild sets against P0b's in the "
            "report; not asserted here"
        ),
        "gates": gates,
        "verdict": "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL",
        "records": rows,
        "records_sha256": canonical_sha(rows),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    written = write_immutable(
        "p0c-coverage-completeness",
        body,
        tool=Path(__file__).resolve(),
        protocol=PROTOCOL,
    )
    print(
        json.dumps(
            {
                "verdict": body["verdict"],
                "pairs": len(rows),
                "equivalent": len(equivalent),
                "stale": stale_total,
                "gates": {name: gate["passed"] for name, gate in gates.items()},
                **written,
            },
            sort_keys=True,
        )
    )
    return 0 if body["verdict"] == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()
    manifest = args.manifest
    if manifest is None:
        pointer = json.loads(
            (NS / "receipts" / "latest" / "p0c-corpus-manifest.json").read_text(encoding="utf-8")
        )
        manifest = ROOT / pointer["points_to"]
    return run(manifest)


if __name__ == "__main__":
    raise SystemExit(main())
