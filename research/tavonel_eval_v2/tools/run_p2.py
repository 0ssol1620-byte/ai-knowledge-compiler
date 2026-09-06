#!/usr/bin/env python3
"""P2 driver: three identity policies over multi-revision chains.

Artifact identifiers, the artifact specification, the dependency structure and
the independent full rebuild are the same in all three arms. Only the set of
units an arm treats as changed differs, so any difference downstream is
attributable to the identity policy.

The oracle runs as a separate isolated process, as in P0b.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "compiler"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "facets"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "cir-python" / "src"))

from common import NS, ROOT, canonical_sha, now, rel, sha_file, write_hashed  # noqa: E402

import selective_build_p0b as engine  # noqa: E402
from akc_cir.identity import (  # noqa: E402
    LogicalMatch,
    assign_one_to_one,
)
from facets import FACETS, change_facets  # noqa: E402

ORACLE = NS / "oracle" / "independent_full_build_p0b.py"
ARMS = ("A_DETERMINISTIC", "B_GLOBAL_ONE_TO_ONE", "C_FORCED_CONTINUATION")
HORIZONS = (1, 2, 3, 5, 10)


def snapshots(document: dict[str, Any]) -> list[Any]:
    """UnitSnapshot-shaped fingerprint inputs, ordered as the document reads."""
    from akc_cir.semantic_diff import UnitSnapshot

    source_id = document["source_id"]
    headings = [unit["heading"] for unit in document["units"]]
    units = []
    for index, unit in enumerate(document["units"]):
        identifier = engine.logical_id(source_id, unit["explicit_path"])
        units.append(
            UnitSnapshot(
                logical_id=identifier,
                text=unit["text"],
                document_path=(source_id, *unit["explicit_path"]),
                anchor=unit["heading"],
                neighbour_anchors=(
                    headings[index - 1] if index else "",
                    headings[index + 1] if index + 1 < len(headings) else "",
                ),
                evidence_id="e:" + identifier,
                explicit_identifier="/".join(unit["explicit_path"]),
            )
        )
    return units


def decide(arm: str, before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """For each after-unit key, what this arm says it continues.

    The returned mapping is keyed by explicit path, which is arm-independent, so
    the three arms can be compared unit for unit.
    """
    source_id = after["source_id"]
    prior_by_id = {
        engine.logical_id(source_id, unit["explicit_path"]): unit for unit in before["units"]
    }
    result: dict[str, dict[str, Any]] = {}

    if arm == "A_DETERMINISTIC":
        for unit in after["units"]:
            key = "/".join(unit["explicit_path"])
            identifier = engine.logical_id(source_id, unit["explicit_path"])
            if identifier in prior_by_id:
                result[key] = {"outcome": "CONTINUATION", "continues": identifier}
            else:
                result[key] = {"outcome": "NEW", "continues": None}
        return result

    before_units = snapshots(before)
    after_units = snapshots(after)
    lineage = source_id
    decisions = assign_one_to_one(
        [unit.fingerprint(source_lineage=lineage) for unit in after_units],
        [unit.fingerprint(source_lineage=lineage) for unit in before_units],
    )
    for unit, decision in zip(after_units, decisions, strict=True):
        key = "/".join(unit.document_path[1:])
        if decision.match is LogicalMatch.MATCHED and decision.logical_id in prior_by_id:
            result[key] = {"outcome": "CONTINUATION", "continues": decision.logical_id}
        elif decision.match is LogicalMatch.AMBIGUOUS:
            top = next((item for item in decision.candidates if item in prior_by_id), None)
            if arm == "C_FORCED_CONTINUATION" and top is not None:
                result[key] = {
                    "outcome": "CONTINUATION",
                    "continues": top,
                    "forced": True,
                    "candidates": list(decision.candidates),
                }
            else:
                result[key] = {
                    "outcome": "UNRESOLVED",
                    "continues": None,
                    "candidates": list(decision.candidates),
                }
        else:
            result[key] = {"outcome": "NEW", "continues": None}
    return result


def changed_units_for(
    arm_decisions: dict[str, dict[str, Any]],
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, tuple[str, ...]]:
    """Facet change facts, seeded by what this arm believes continues what."""
    source_id = after["source_id"]
    prior_by_id = {
        engine.logical_id(source_id, unit["explicit_path"]): unit for unit in before["units"]
    }
    facts: dict[str, tuple[str, ...]] = {}
    for unit in after["units"]:
        key = "/".join(unit["explicit_path"])
        identifier = engine.logical_id(source_id, unit["explicit_path"])
        decision = arm_decisions[key]
        if decision["outcome"] == "CONTINUATION":
            prior = prior_by_id.get(decision["continues"])
            moved = change_facets(prior, unit) if prior is not None else FACETS
            if moved:
                facts[identifier] = moved
        else:
            # NEW and UNRESOLVED both fail closed: nothing has been shown to
            # continue, so everything derived from this unit is rebuilt.
            facts[identifier] = FACETS
    return facts


def selective_state(
    before: dict[str, Any], after: dict[str, Any], facts: dict[str, tuple[str, ...]]
) -> dict[str, Any]:
    """P0b's carry rule, with the arm's change facts substituted for its own."""
    key = engine.doc_key(after["source_id"])
    prior = engine.build_revision(before)
    jobs = {job["artifact"]: job for job in engine.plan_of(after)}
    final: dict[str, str] = {}
    rebuilt: list[str] = []
    carried: list[str] = []
    for artifact in sorted(jobs):
        job = jobs[artifact]
        previous = prior.get(artifact)
        input_ids = [identifier for identifier, _ in job["inputs"]]
        if previous is None or previous["state"] == "UNVERIFIABLE":
            value, _ = engine.execute(job, key)
            final[artifact] = value
            rebuilt.append(artifact)
            continue
        edge_facets = set(previous["sensitivity"])
        touched = {
            facet for identifier in input_ids for facet in facts.get(identifier, ())
        } & edge_facets
        moved = engine.fingerprint(job, tuple(previous["sensitivity"])) != previous["fingerprint"]
        if touched or moved:
            value, _ = engine.execute(job, key)
            final[artifact] = value
            rebuilt.append(artifact)
        else:
            final[artifact] = previous["digest"]
            carried.append(artifact)
    return {
        "state": final,
        "rebuilt": rebuilt,
        "carried": carried,
        "inventory": sorted(jobs),
        "state_hash": engine.digest(final),
    }


def oracle_state(canonical_path: Path, out_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ORACLE),
            "--after",
            str(canonical_path),
            "--output",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit("oracle failed: " + completed.stderr[-400:])
    return json.loads(out_path.read_text(encoding="utf-8"))


def jaccard_divergence(left: list[str], right: list[str]) -> float:
    a, b = set(left), set(right)
    union = a | b
    if not union:
        return 0.0
    return 1.0 - len(a & b) / len(union)


def first_divergence_cause(arm_decision: dict[str, Any], reference: dict[str, Any]) -> str:
    if reference["outcome"] == "NEW" and arm_decision["outcome"] == "CONTINUATION":
        return "NEW_VS_CONTINUATION"
    if reference["outcome"] == "CONTINUATION" and arm_decision["outcome"] == "NEW":
        return "CONTINUATION_VS_NEW"
    if arm_decision["outcome"] == "UNRESOLVED":
        return "UNRESOLVED_VS_DECIDED"
    if (
        reference["outcome"] == "CONTINUATION"
        and arm_decision["outcome"] == "CONTINUATION"
        and arm_decision.get("forced")
    ):
        return "RUNNER_UP_LOSS"
    return "CONTINUATION_SWAP"


def run(manifest: Path, output: Path) -> int:
    chains = json.loads(manifest.read_text(encoding="utf-8"))
    oracle_root = NS / "artifacts" / "development" / "p2" / "oracle"
    started = now()

    chain_rows: list[dict[str, Any]] = []
    for chain in chains["chains"]:
        revisions = [
            json.loads((ROOT / item["canonical_path"]).read_text(encoding="utf-8"))
            for item in chain["revisions"]
        ]
        origins: dict[str, dict[str, tuple[int, str]]] = {arm: {} for arm in ARMS}
        for arm in ARMS:
            for unit in revisions[0]["units"]:
                key = "/".join(unit["explicit_path"])
                origins[arm][key] = (0, key)

        steps: list[dict[str, Any]] = []
        horizon_rows: list[dict[str, Any]] = []
        first_divergence: dict[str, dict[str, Any] | None] = {arm: None for arm in ARMS}
        arm_states: dict[str, dict[str, Any]] = {}

        for position in range(len(revisions) - 1):
            before, after = revisions[position], revisions[position + 1]
            decisions = {arm: decide(arm, before, after) for arm in ARMS}
            facts = {arm: changed_units_for(decisions[arm], before, after) for arm in ARMS}
            builds = {arm: selective_state(before, after, facts[arm]) for arm in ARMS}
            arm_states = builds

            inventories = {arm: builds[arm]["inventory"] for arm in ARMS}
            inventory_identical = len({tuple(value) for value in inventories.values()}) == 1

            new_origins: dict[str, dict[str, tuple[int, str]]] = {arm: {} for arm in ARMS}
            prior_key_by_id = {
                engine.logical_id(after["source_id"], unit["explicit_path"]): "/".join(
                    unit["explicit_path"]
                )
                for unit in before["units"]
            }
            for arm in ARMS:
                for unit in after["units"]:
                    key = "/".join(unit["explicit_path"])
                    decision = decisions[arm][key]
                    if decision["outcome"] == "CONTINUATION":
                        prior_key = prior_key_by_id.get(decision["continues"])
                        inherited = origins[arm].get(prior_key) if prior_key else None
                        new_origins[arm][key] = inherited or (position + 1, key)
                    else:
                        new_origins[arm][key] = (position + 1, key)
            origins = new_origins

            step: dict[str, Any] = {
                "step": position,
                "from_version": chain["revisions"][position]["version_id"][:12],
                "to_version": chain["revisions"][position + 1]["version_id"][:12],
                "unit_count_after": len(after["units"]),
                "inventory_identical_across_arms": inventory_identical,
                "arms": {},
            }
            for arm in ARMS:
                mismatched = [
                    key
                    for key in decisions[arm]
                    if decisions[arm][key]["outcome"]
                    != decisions["A_DETERMINISTIC"][key]["outcome"]
                    or decisions[arm][key]["continues"]
                    != decisions["A_DETERMINISTIC"][key]["continues"]
                ]
                origin_mismatch = [
                    key
                    for key in origins[arm]
                    if origins[arm][key] != origins["A_DETERMINISTIC"][key]
                ]
                step["arms"][arm] = {
                    "unresolved": sum(
                        1 for item in decisions[arm].values() if item["outcome"] == "UNRESOLVED"
                    ),
                    "forced": sum(1 for item in decisions[arm].values() if item.get("forced")),
                    "changed_units": len(facts[arm]),
                    "rebuilt": len(builds[arm]["rebuilt"]),
                    "carried": len(builds[arm]["carried"]),
                    "current_decision_divergence": len(mismatched) / len(decisions[arm])
                    if decisions[arm]
                    else 0.0,
                    "origin_divergence": len(origin_mismatch) / len(origins[arm])
                    if origins[arm]
                    else 0.0,
                    "affected_set_jaccard_divergence": jaccard_divergence(
                        builds[arm]["rebuilt"], builds["A_DETERMINISTIC"]["rebuilt"]
                    ),
                }
                if arm != "A_DETERMINISTIC" and first_divergence[arm] is None and mismatched:
                    key = sorted(mismatched)[0]
                    first_divergence[arm] = {
                        "step": position,
                        "unit": key,
                        "cause": first_divergence_cause(
                            decisions[arm][key], decisions["A_DETERMINISTIC"][key]
                        ),
                    }
            steps.append(step)

            horizon = position + 1
            if horizon in HORIZONS:
                horizon_rows.append(
                    {
                        "horizon": horizon,
                        "units": len(origins["A_DETERMINISTIC"]),
                        "path_divergence": {
                            arm: step["arms"][arm]["origin_divergence"] for arm in ARMS
                        },
                    }
                )

        final_index = len(revisions) - 1
        oracle_out = oracle_root / (chain["chain_id"] + ".json")
        oracle = oracle_state(ROOT / chain["revisions"][final_index]["canonical_path"], oracle_out)
        downstream: dict[str, Any] = {}
        for arm in ARMS:
            state = arm_states[arm]["state"]
            diverged = sorted(
                key
                for key in set(state) & set(oracle["state"])
                if state[key] != oracle["state"][key]
            )
            carried = set(arm_states[arm]["carried"])
            downstream[arm] = {
                "state_hash_equal": arm_states[arm]["state_hash"] == oracle["state_hash"],
                "diverged": diverged,
                "stale_left_behind": sorted(key for key in diverged if key in carried),
                "missing_from_selective": sorted(set(oracle["state"]) - set(state)),
                "extra_in_selective": sorted(set(state) - set(oracle["state"])),
            }

        chain_rows.append(
            {
                "chain_id": chain["chain_id"],
                "source_family": chain["source_family"],
                "source_id": chain["source_id"],
                "length": chain["length"],
                "steps": steps,
                "horizons": horizon_rows,
                "first_divergence": first_divergence,
                "downstream": downstream,
                "oracle_pid": oracle["independence"]["pid"],
                "oracle_akc_cir_imported": oracle["independence"]["akc_cir_imported"],
                "oracle_cir_python_on_path": oracle["independence"]["cir_python_on_path"],
            }
        )

    # --- aggregation --------------------------------------------------------
    horizon_summary: dict[str, dict[str, Any]] = {}
    for horizon in HORIZONS:
        contributing = [
            row for chain in chain_rows for row in chain["horizons"] if row["horizon"] == horizon
        ]
        if not contributing:
            continue
        horizon_summary[str(horizon)] = {
            "chains_reaching_this_horizon": len(contributing),
            "mean_path_divergence": {
                arm: statistics.fmean(row["path_divergence"][arm] for row in contributing)
                for arm in ARMS
            },
            "max_path_divergence": {
                arm: max(row["path_divergence"][arm] for row in contributing) for arm in ARMS
            },
        }

    ordered = sorted(int(key) for key in horizon_summary)
    monotone = {
        arm: all(
            horizon_summary[str(ordered[index])]["mean_path_divergence"][arm]
            <= horizon_summary[str(ordered[index + 1])]["mean_path_divergence"][arm] + 1e-12
            for index in range(len(ordered) - 1)
        )
        for arm in ARMS
    }
    forced_at_least_as_divergent = all(
        horizon_summary[key]["mean_path_divergence"]["C_FORCED_CONTINUATION"]
        >= horizon_summary[key]["mean_path_divergence"]["B_GLOBAL_ONE_TO_ONE"] - 1e-12
        for key in horizon_summary
    )

    all_steps = [step for chain in chain_rows for step in chain["steps"]]
    stale_total = {
        arm: sum(len(chain["downstream"][arm]["stale_left_behind"]) for chain in chain_rows)
        for arm in ARMS
    }
    equivalence = {
        arm: all(
            not chain["downstream"][arm]["diverged"]
            and not chain["downstream"][arm]["missing_from_selective"]
            and not chain["downstream"][arm]["extra_in_selective"]
            for chain in chain_rows
        )
        for arm in ARMS
    }

    gates = {
        "G_P2_SCALE": {
            "passed": len(chain_rows) >= 5 and all(chain["length"] >= 3 for chain in chain_rows),
            "chains": len(chain_rows),
            "shortest": min((chain["length"] for chain in chain_rows), default=0),
        },
        "G_P2_ARM_INVARIANCE": {
            "passed": all(step["inventory_identical_across_arms"] for step in all_steps),
            "steps": len(all_steps),
        },
        "G_P2_EQUIVALENCE": {
            "passed": all(equivalence.values()) and not any(stale_total.values()),
            "per_arm_equivalent": equivalence,
            "stale_left_behind_total": stale_total,
        },
        "G_P2_HORIZON_COVERAGE": {
            "passed": "10" in horizon_summary,
            "horizons_reached": sorted(horizon_summary),
        },
        "G_P2_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }

    body: dict[str, Any] = {
        "schema": "tavonel.v2.p2_lineage.v1",
        "protocol": "P2_multi_revision_lineage",
        "split": "development",
        "started_at": started,
        "ended_at": now(),
        "protocol_sha256": json.loads(
            (NS / "receipts" / "p2-protocol-freeze.json").read_text(encoding="utf-8")
        )["protocol_sha256"],
        "chain_manifest": rel(manifest),
        "chain_manifest_file_sha256": sha_file(manifest),
        "driver_sha256": sha_file(Path(__file__).resolve()),
        "arms": list(ARMS),
        "reference_arm": "A_DETERMINISTIC",
        "reference_arm_note": (
            "the lineage the document's own heading paths declare, not an oracle of "
            "true authorship lineage. Divergence from it is not an error rate."
        ),
        "chain_count": len(chain_rows),
        "step_count": len(all_steps),
        "unresolved_decisions": {
            arm: sum(step["arms"][arm]["unresolved"] for step in all_steps) for arm in ARMS
        },
        "forced_continuations": {
            arm: sum(step["arms"][arm]["forced"] for step in all_steps) for arm in ARMS
        },
        "mean_current_decision_divergence": {
            arm: statistics.fmean(
                step["arms"][arm]["current_decision_divergence"] for step in all_steps
            )
            for arm in ARMS
        },
        "mean_affected_set_jaccard_divergence": {
            arm: statistics.fmean(
                step["arms"][arm]["affected_set_jaccard_divergence"] for step in all_steps
            )
            for arm in ARMS
        },
        "mean_rebuilt_per_step": {
            arm: statistics.fmean(step["arms"][arm]["rebuilt"] for step in all_steps)
            for arm in ARMS
        },
        "path_divergence_by_horizon": horizon_summary,
        "H4a_divergence_non_decreasing_in_horizon": monotone,
        "H4b_forced_at_least_as_divergent_as_preserving": forced_at_least_as_divergent,
        "H4c_downstream_equivalence_in_every_arm": all(equivalence.values()),
        "first_divergence_causes": {
            chain["chain_id"]: chain["first_divergence"] for chain in chain_rows
        },
        "gates": gates,
        "verdict": "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL",
        "chains": chain_rows,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    body["chains_sha256"] = canonical_sha(chain_rows)
    write_hashed(output, body, "receipt_sha256")

    frontier = NS / "artifacts" / "development" / "p2" / "path_divergence_by_horizon.csv"
    frontier.parent.mkdir(parents=True, exist_ok=True)
    lines = ["horizon,chains," + ",".join(ARMS)]
    for key in sorted(horizon_summary, key=int):
        row = horizon_summary[key]
        lines.append(
            key
            + ","
            + str(row["chains_reaching_this_horizon"])
            + ","
            + ",".join("%.6f" % row["mean_path_divergence"][arm] for arm in ARMS)
        )
    frontier.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "verdict": body["verdict"],
                "chains": len(chain_rows),
                "steps": len(all_steps),
                "gates": {name: gate["passed"] for name, gate in gates.items()},
                "receipt": rel(output),
            },
            sort_keys=True,
        )
    )
    return 0 if body["verdict"] == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=NS / "receipts" / "p2-chain-manifest.json")
    parser.add_argument("--output", type=Path, default=NS / "receipts" / "p2-lineage.json")
    args = parser.parse_args()
    return run(args.manifest, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
