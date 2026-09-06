#!/usr/bin/env python3
"""INC-V2-003 impact analysis: what the wrong identity rule cost P0 v1.

P0 v1 is not modified, re-run or re-labelled. This builds a counterfactual and
compares it with the figures P0 v1 already recorded.

Single variable. The counterfactual keeps everything P0 v1 did -- artifact
specification v1, the same dependency graph, the same channel declarations, the
same `plan_recompilation` call with `StructuralPolicy.PRECISE`, the same
structural comparison over `DocumentShape`, the same
`normalize_text_for_identity` basis for deciding that a unit's content moved --
and replaces exactly one thing: how a unit in the after revision is matched to a
unit in the before revision.

    P0 v1 as executed   `diff_documents` -> LogicalIdentityResolver ->
                        assign_one_to_one, weighted signals, MERGE_THRESHOLD
                        0.92, NEW_IDENTITY_THRESHOLD 0.75, tie band 0.05
    counterfactual      explicit-path identifier equality, which is what
                        P0_master_protocol section 3 specified

The oracle outputs P0 v1 already produced are reused as the full-rebuild side.
They are rebuilds of the after revision from the after revision alone, so no
identity rule can have influenced them.

A direct P0 v1 vs P0b comparison is NOT what this computes. P0b changed the
artifact specification and the invalidation model as well as the identity rule,
so differences between those two runs are confounded and are reported as such.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "compiler"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "cir-python" / "src"))

from common import NS, ROOT, canonical_sha, now, rel, sha_file, write_hashed  # noqa: E402

import selective_build as v1  # noqa: E402
from akc_cir.identity import normalize_text_for_identity  # noqa: E402
from akc_cir.recompilation import StructuralPolicy, plan_recompilation  # noqa: E402
from akc_cir.semantic_diff import (  # noqa: E402
    ChangeKind,
    DiffLevel,
    SemanticChange,
    SemanticDiff,
    _change_id,
    _structural_changes,
)


def deterministic_diff(before: dict[str, Any], after: dict[str, Any]) -> SemanticDiff:
    """The diff P0 v1's protocol specified, built without any resolver."""
    before_units, before_shape = v1.snapshots(before)
    after_units, after_shape = v1.snapshots(after)
    prior = {unit.logical_id: unit for unit in before_units}
    incoming = {unit.logical_id: unit for unit in after_units}

    changes: list[SemanticChange] = list(_structural_changes(before_shape, after_shape))
    for identifier, unit in incoming.items():
        if identifier not in prior:
            changes.append(
                SemanticChange(kind=ChangeKind.UNIT_ADDED, logical_id=identifier, after=unit.anchor)
            )
        elif normalize_text_for_identity(prior[identifier].text) != normalize_text_for_identity(
            unit.text
        ):
            changes.append(
                SemanticChange(
                    kind=ChangeKind.MODIFIED_CLAIM,
                    logical_id=identifier,
                    detail="identity-normalised text differs",
                )
            )
    for identifier, unit in prior.items():
        if identifier not in incoming:
            changes.append(
                SemanticChange(
                    kind=ChangeKind.UNIT_REMOVED, logical_id=identifier, before=unit.anchor
                )
            )

    scope: tuple[str, ...] = ()
    if any(change.kind is ChangeKind.STRUCTURE_CHANGED for change in changes):
        ordered: list[str] = []
        for unit in (*before_units, *after_units):
            if unit.logical_id not in ordered:
                ordered.append(unit.logical_id)
        scope = tuple(ordered)

    return SemanticDiff(
        level=DiffLevel.SEMANTIC,
        content_changed=before["source_digest"] != after["source_digest"],
        changes=tuple(changes),
        change_id=_change_id([change.as_record() for change in changes]),
        structural_scope=scope,
    )


def counterfactual(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_deps, _ = v1.inventory_and_dependencies(before)
    after_deps, _ = v1.inventory_and_dependencies(after)
    diff = deterministic_diff(before, after)
    graph = v1.graph_for(before_deps, after_deps)
    plan = plan_recompilation(
        diff=diff,
        graph=graph,
        artifacts=sorted({*before_deps, *after_deps}),
        structural_policy=StructuralPolicy.PRECISE,
    )

    prior_state = v1.build_all(before)
    after_full = v1.build_all(after)
    planned = set(plan.to_rebuild)

    final: dict[str, str] = {}
    rebuilt: list[str] = []
    carried: list[str] = []
    for artifact in sorted(after_deps):
        if artifact in planned:
            final[artifact] = after_full[artifact]
            rebuilt.append(artifact)
        elif artifact in prior_state:
            final[artifact] = prior_state[artifact]
            carried.append(artifact)
        else:
            final[artifact] = v1.MISSING

    unnecessary = [
        artifact
        for artifact in rebuilt
        if artifact in prior_state and prior_state[artifact] == after_full[artifact]
    ]
    before_ids = {
        unit["explicit_path"] and v1.logical_id(before["source_id"], unit["explicit_path"])
        for unit in before["units"]
    }
    after_ids = {
        v1.logical_id(after["source_id"], unit["explicit_path"]) for unit in after["units"]
    }
    return {
        "identity_outcomes": {
            "continuation": len(before_ids & after_ids),
            "new": len(after_ids - before_ids),
            "retired": len(before_ids - after_ids),
            "unresolved": 0,
        },
        "changed_logical_ids": len(diff.changed_logical_ids),
        "detected_change_kinds": sorted({change.kind.value for change in diff.changes}),
        "structural_change_present": diff.structural_change_present,
        "selective_rebuild_set": rebuilt,
        "carried_forward_set": carried,
        "unnecessary_rebuild_set": unnecessary,
        "rebuilt_fraction": len(rebuilt) / len(after_deps) if after_deps else 0.0,
        "work_avoided_fraction": len(carried) / len(after_deps) if after_deps else 0.0,
        "state": final,
        "state_hash": v1._digest(final),
    }


def run(v1_receipt: Path, corpus: Path, output: Path) -> int:
    executed = json.loads(v1_receipt.read_text(encoding="utf-8"))
    manifest = json.loads(corpus.read_text(encoding="utf-8"))
    by_id = {pair["pair_id"]: pair for pair in manifest["pairs"]}
    oracle_root = NS / "artifacts" / "development" / "oracle"

    rows: list[dict[str, Any]] = []
    for record in executed["records"]:
        if "equivalence_verdict" not in record:
            continue
        pair = by_id[record["pair_id"]]
        before = json.loads((ROOT / pair["before"]["path"]).read_text(encoding="utf-8"))
        after = json.loads((ROOT / pair["after"]["path"]).read_text(encoding="utf-8"))
        alternative = counterfactual(before, after)

        oracle_path = oracle_root / (record["pair_id"] + ".json")
        oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
        oracle_state = oracle["state"]
        diverged = sorted(
            key
            for key in set(alternative["state"]) & set(oracle_state)
            if alternative["state"][key] != oracle_state[key]
        )
        carried = set(alternative["carried_forward_set"])
        stale = sorted(key for key in diverged if key in carried)

        rows.append(
            {
                "pair_id": record["pair_id"],
                "group": record["group"],
                "source_family": record["source_family"],
                "executed": {
                    "identity_outcomes": record["identity_outcomes"],
                    "unresolved_present": record["unresolved_present"],
                    "rebuilt": len(record["selective_rebuild_set"]),
                    "carried": len(record["carried_forward_set"]),
                    "unnecessary": len(record["unnecessary_rebuild_set"]),
                    "rebuilt_fraction": record["rebuilt_fraction"],
                    "work_avoided_fraction": record["work_avoided_fraction"],
                    "equivalence_verdict": record["equivalence_verdict"],
                    "stale_left_behind": len(record["stale_left_behind"]),
                },
                "counterfactual": {
                    "identity_outcomes": alternative["identity_outcomes"],
                    "changed_logical_ids": alternative["changed_logical_ids"],
                    "rebuilt": len(alternative["selective_rebuild_set"]),
                    "carried": len(alternative["carried_forward_set"]),
                    "unnecessary": len(alternative["unnecessary_rebuild_set"]),
                    "rebuilt_fraction": alternative["rebuilt_fraction"],
                    "work_avoided_fraction": alternative["work_avoided_fraction"],
                    "equivalence_verdict": "EQUIVALENT" if not diverged else "DIVERGED",
                    "stale_left_behind": len(stale),
                    "diverged": diverged,
                },
                "rebuild_set_identical": sorted(record["selective_rebuild_set"])
                == sorted(alternative["selective_rebuild_set"]),
                "verdict_identical": record["equivalence_verdict"]
                == ("EQUIVALENT" if not diverged else "DIVERGED"),
            }
        )

    natural = [row for row in rows if row["group"] == "natural"]

    def mean(rows_in: list[dict[str, Any]], side: str, field: str) -> float:
        values = [row[side][field] for row in rows_in]
        return statistics.fmean(values) if values else 0.0

    summary = {
        "pairs_analysed": len(rows),
        "natural_pairs": len(natural),
        "unresolved_pairs_executed": sum(
            1 for row in rows if row["executed"]["unresolved_present"]
        ),
        "unresolved_pairs_counterfactual": 0,
        "identity_outcome_totals": {
            "executed": {
                key: sum(row["executed"]["identity_outcomes"].get(key, 0) for row in rows)
                for key in ("continuation", "new", "removed", "modified", "unresolved")
            },
            "counterfactual": {
                key: sum(row["counterfactual"]["identity_outcomes"].get(key, 0) for row in rows)
                for key in ("continuation", "new", "retired", "unresolved")
            },
        },
        "rebuild_set_identical_pairs": sum(1 for row in rows if row["rebuild_set_identical"]),
        "rebuild_set_differs_pairs": sum(1 for row in rows if not row["rebuild_set_identical"]),
        "verdict_identical_pairs": sum(1 for row in rows if row["verdict_identical"]),
        "verdict_differs_pairs": sum(1 for row in rows if not row["verdict_identical"]),
        "mean_rebuilt_fraction_natural": {
            "executed": mean(natural, "executed", "rebuilt_fraction"),
            "counterfactual": mean(natural, "counterfactual", "rebuilt_fraction"),
        },
        "mean_work_avoided_natural": {
            "executed": mean(natural, "executed", "work_avoided_fraction"),
            "counterfactual": mean(natural, "counterfactual", "work_avoided_fraction"),
        },
        "unnecessary_rebuilds_total": {
            "executed": sum(row["executed"]["unnecessary"] for row in rows),
            "counterfactual": sum(row["counterfactual"]["unnecessary"] for row in rows),
        },
        "stale_escapes_total": {
            "executed": sum(row["executed"]["stale_left_behind"] for row in rows),
            "counterfactual": sum(row["counterfactual"]["stale_left_behind"] for row in rows),
        },
    }

    body: dict[str, Any] = {
        "schema": "tavonel.v2.inc_v2_003_impact.v1",
        "incident": "INC-V2-003",
        "generated_at": now(),
        "question": (
            "Which P0 v1 figures were changed by running production fuzzy global "
            "identity where the protocol specified deterministic explicit-path identity?"
        ),
        "method": (
            "Single-variable counterfactual. Artifact specification v1, the same "
            "dependency graph and channels, the same plan_recompilation call and "
            "structural policy, the same identity-normalised basis for deciding a unit "
            "moved. Only the matching rule differs. The full-rebuild side is the P0 v1 "
            "oracle output, which no identity rule can have influenced."
        ),
        "not_this": (
            "Not a P0 v1 versus P0b comparison. P0b also changed the artifact "
            "specification and the invalidation model, so that difference is confounded."
        ),
        "p0_v1_receipt": rel(v1_receipt),
        "p0_v1_receipt_sha256": sha_file(v1_receipt),
        "p0_v1_modified": False,
        "analyser_sha256": sha_file(Path(__file__).resolve()),
        "summary": summary,
        "records": rows,
        "gpu_seconds": 0,
        "external_gpu_cost_usd": 0.0,
    }
    body["records_sha256"] = canonical_sha(rows)
    write_hashed(output, body, "receipt_sha256")
    print(json.dumps({"summary": summary, "receipt": rel(output)}, sort_keys=True, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v1-receipt", type=Path, default=NS / "receipts" / "p0-oracle-independence.json"
    )
    parser.add_argument(
        "--corpus", type=Path, default=NS / "receipts" / "p0-canonicalisation-manifest.json"
    )
    parser.add_argument(
        "--output", type=Path, default=NS / "receipts" / "inc-v2-003-impact-analysis.json"
    )
    args = parser.parse_args()
    return run(args.v1_receipt, args.corpus, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
