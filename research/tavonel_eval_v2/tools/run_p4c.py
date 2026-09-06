#!/usr/bin/env python3
"""P4c: two endpoints over an independent cohort. CPU only, no spend.

The scorer and the unit-level, non-tie-breaking ranking function are imported
from ``run_p4b`` rather than re-implemented. INC-V2-007 happened because that
ranking was written twice and the second copy broke the frozen tie policy;
writing it a third time is the same risk taken again.

P4c-Core and P4c-Global are separate experiments with separate verdicts and are
never combined into one number.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "facets"))

from common import NS, ROOT, canonical_sha, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from facet_coverage import SEMANTIC, project  # noqa: E402
from run_p4b import FIELD_WEIGHTS, TOP_K, FieldedBm25, rank, tokenise  # noqa: E402

PROTOCOL = NS / "protocols" / "P4c_retrieval_validity.yaml"
SCORER = NS / "tools" / "run_p4b.py"
PER_DOCUMENT_CAP = 12


def frame_question(document: dict[str, Any], heading: str, parent: str | None) -> str:
    """Natural identity only. No machine identifier, no revision signal."""
    where = "in the " + document["spoken_type"] + " for " + document["identity"]
    if parent:
        return "what does the section on " + heading + " under " + parent + " say " + where + "?"
    return "what does the section on " + heading + " say " + where + "?"


def build_cohort(
    manifest: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    cohort = json.loads(manifest.read_text(encoding="utf-8"))
    documents: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    ineligible: list[dict[str, Any]] = []

    for record in cohort["documents"]:
        slug = record["document_slug"]
        before = json.loads((ROOT / record["before"]["canonical_path"]).read_text(encoding="utf-8"))
        after = json.loads((ROOT / record["after"]["canonical_path"]).read_text(encoding="utf-8"))
        before_by_path = {"/".join(u["explicit_path"]): u for u in before["units"]}
        after_by_path = {"/".join(u["explicit_path"]): u for u in after["units"]}

        for revision, by_path in (("superseded", before_by_path), ("current", after_by_path)):
            for key, unit in by_path.items():
                documents.append(
                    {
                        "doc_id": slug + "|" + revision + "|" + key,
                        "pair_id": slug,
                        "source_id": record["document_id"],
                        "source_family": record["family"],
                        "path": key,
                        "revision": revision,
                        "fields": {
                            "title": record["title_field"],
                            "doc_type": record["doc_type"],
                            "heading_path": key.replace("/", " "),
                            "heading": unit["heading"],
                            "body": unit["text"],
                        },
                    }
                )

        revised = 0
        unchanged = 0
        for key, unit in after_by_path.items():
            prior = before_by_path.get(key)
            if prior is None:
                continue
            heading = str(unit.get("heading") or "").strip()
            if not heading:
                ineligible.append(
                    {"document": slug, "path": key, "reason": "INELIGIBLE_HEADING_ABSENT"}
                )
                continue
            moved = project(SEMANTIC, prior) != project(SEMANTIC, unit)
            kind = "Q1_REVISED_VALUE" if moved else "C1_UNCHANGED_CONTROL"
            if moved and revised >= PER_DOCUMENT_CAP:
                continue
            if not moved and unchanged >= PER_DOCUMENT_CAP:
                continue
            parts = unit["explicit_path"]
            parent = parts[-2] if len(parts) >= 2 else None
            query = frame_question(record, heading, parent)
            if not tokenise(query):
                ineligible.append(
                    {"document": slug, "path": key, "reason": "INELIGIBLE_EMPTY_QUERY"}
                )
                continue
            questions.append(
                {
                    "question_id": slug + "|" + kind + "|" + key,
                    "kind": kind,
                    "pair_id": slug,
                    "source_id": record["document_id"],
                    "source_family": record["family"],
                    "path": key,
                    "query": query,
                    "oracle_current_doc": slug + "|current|" + key,
                    "superseded_doc": slug + "|superseded|" + key,
                }
            )
            if moved:
                revised += 1
            else:
                unchanged += 1

    return documents, questions, ineligible


def evaluate(
    index: FieldedBm25,
    questions: list[dict[str, Any]],
    scopes: dict[str, set[str]] | None,
    doc_unit: dict[str, str],
    unit_lineage: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for question in questions:
        scope = scopes[question["pair_id"]] if scopes is not None else None
        scores = index.score_all(question["query"], scope)
        if question["oracle_current_doc"] not in scores:
            rows.append({**question, "state": "INELIGIBLE_NO_ORACLE_UNIT"})
            continue
        result = rank(scores, question["oracle_current_doc"], doc_unit)
        current = scores[question["oracle_current_doc"]]
        superseded = scores.get(question["superseded_doc"])
        rows.append(
            {
                **question,
                **result,
                "lineage_at_1": all(
                    unit_lineage.get(unit) == question["pair_id"] for unit in result["top_units"]
                ),
                "current_score": current,
                "superseded_score": superseded,
                "revision_scores_differ": superseded is not None and current != superseded,
                "lexical_only_picks_current": superseded is not None and current > superseded,
                "lexical_only_picks_superseded": superseded is not None and superseded > current,
                "lexical_only_cannot_choose": superseded is None or current == superseded,
                "compiled_currency_picks_current": True,
            }
        )
    return rows


def share(rows: list[dict[str, Any]], field: str) -> float:
    return (sum(1 for row in rows if row.get(field)) / len(rows)) if rows else 0.0


def by_family(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for family in sorted({row["source_family"] for row in rows}):
        subset = [row for row in rows if row["source_family"] == family]
        out[family] = {"questions": len(subset)}
        out[family].update({field: share(subset, field) for field in fields})
    return out


def run(manifest: Path) -> int:
    started = now()
    documents, questions, ineligible = build_cohort(manifest)
    doc_unit = {item["doc_id"]: item["pair_id"] + "|" + item["path"] for item in documents}
    unit_lineage = {unit: unit.split("|", 1)[0] for unit in doc_unit.values()}
    scopes: dict[str, set[str]] = {}
    for item in documents:
        scopes.setdefault(item["pair_id"], set()).add(item["doc_id"])

    index = FieldedBm25(documents)
    reversed_index = FieldedBm25(list(reversed(documents)))

    core = evaluate(index, questions, scopes, doc_unit, unit_lineage)
    glob = evaluate(index, questions, None, doc_unit, unit_lineage)
    core_check = evaluate(reversed_index, questions, scopes, doc_unit, unit_lineage)
    glob_check = evaluate(reversed_index, questions, None, doc_unit, unit_lineage)

    deterministic = all(
        left.get("top_score") == right.get("top_score")
        and left.get("tied_set") == right.get("tied_set")
        and left.get("current_score") == right.get("current_score")
        for pair in ((core, core_check), (glob, glob_check))
        for left, right in zip(pair[0], pair[1], strict=True)
    )

    scored_core = [row for row in core if row["state"] == "SCORED"]
    scored_global = [row for row in glob if row["state"] == "SCORED"]
    q1_core = [row for row in scored_core if row["kind"] == "Q1_REVISED_VALUE"]
    c1_core = [row for row in scored_core if row["kind"] == "C1_UNCHANGED_CONTROL"]
    docs = len({row["pair_id"] for row in scored_core})
    families = sorted({row["source_family"] for row in scored_core})

    core_measures = {
        "tie_rate": share(scored_core, "exact_top_score_tie"),
        "unit_retrievable_at_10": share(scored_core, "target_in_top_10"),
        "unit_top_1": share(scored_core, "target_unique_top_1"),
        "unchanged_control_retrievable_at_10": share(c1_core, "target_in_top_10"),
    }
    global_measures = {
        "tie_rate": share(scored_global, "exact_top_score_tie"),
        "lineage_at_1": share(scored_global, "lineage_at_1"),
        "unit_retrievable_at_10": share(scored_global, "target_in_top_10"),
    }
    revision = {
        "scope": "P4c-Core, correct unit secured by construction",
        "q1_question_count": len(q1_core),
        "LEXICAL_ONLY": {
            "picks_current": share(q1_core, "lexical_only_picks_current"),
            "picks_superseded": share(q1_core, "lexical_only_picks_superseded"),
            "cannot_choose": share(q1_core, "lexical_only_cannot_choose"),
            "gated": False,
            "note": "the finding. Not gated, because gating it would decide it.",
        },
        "COMPILED_CURRENCY": {
            "picks_current": share(scored_core, "compiled_currency_picks_current"),
            "gated": True,
            "status": (
                "positive control on the harness, NOT a TAVONEL performance "
                "result. Near 1.0 by construction and never to be quoted as an "
                "outcome."
            ),
        },
        "failure_mode_removed_by_compiled_currency": share(
            q1_core, "lexical_only_picks_superseded"
        ),
        "no_model_executed": True,
    }

    shared_scale = len(scored_core) >= 250 and docs >= 40 and len(families) >= 4
    core_gates = {
        "G_P4C_SCALE": {
            "passed": shared_scale,
            "questions": len(scored_core),
            "documents": docs,
            "families": families,
        },
        "G_P4C_DETERMINISM": {"passed": deterministic},
        "G_P4C_CORE_TIE": {
            "passed": core_measures["tie_rate"] <= 0.10,
            "value": core_measures["tie_rate"],
            "threshold": 0.10,
        },
        "G_P4C_CORE_RETRIEVABLE": {
            "passed": core_measures["unit_retrievable_at_10"] >= 0.90,
            "value": core_measures["unit_retrievable_at_10"],
            "threshold": 0.90,
        },
        "G_P4C_CORE_TOP1": {
            "passed": core_measures["unit_top_1"] >= 0.60,
            "value": core_measures["unit_top_1"],
            "threshold": 0.60,
        },
        "G_P4C_CORE_Q1_SCALE": {
            "passed": len(q1_core) >= 100,
            "value": len(q1_core),
            "threshold": 100,
        },
        "G_P4C_CORE_HARNESS": {
            "passed": revision["COMPILED_CURRENCY"]["picks_current"] >= 0.99,
            "value": revision["COMPILED_CURRENCY"]["picks_current"],
            "threshold": 0.99,
        },
        "G_P4C_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }
    global_gates = {
        "G_P4C_SCALE": core_gates["G_P4C_SCALE"],
        "G_P4C_DETERMINISM": {"passed": deterministic},
        "G_P4C_GLOBAL_LINEAGE": {
            "passed": global_measures["lineage_at_1"] >= 0.80,
            "value": global_measures["lineage_at_1"],
            "threshold": 0.80,
        },
        "G_P4C_GLOBAL_UNIT": {
            "passed": global_measures["unit_retrievable_at_10"] >= 0.75,
            "value": global_measures["unit_retrievable_at_10"],
            "threshold": 0.75,
        },
        "G_P4C_COST": core_gates["G_P4C_COST"],
    }

    core_verdict = "PASS" if all(gate["passed"] for gate in core_gates.values()) else "FAIL"
    global_verdict = "PASS" if all(gate["passed"] for gate in global_gates.values()) else "FAIL"

    body: dict[str, Any] = {
        "schema": "tavonel.v2.p4c_retrieval_validity.v1",
        "protocol": "P4c_retrieval_validity",
        "split": "development",
        "started_at": started,
        "ended_at": now(),
        "cohort_manifest": rel(manifest),
        "cohort_manifest_file_sha256": sha_file(manifest),
        "scorer_source": rel(SCORER),
        "scorer_sha256": sha_file(SCORER),
        "scorer_reused_because": (
            "INC-V2-007 was caused by writing the unit-level ranking twice. "
            "Importing the corrected implementation is the fix for that class."
        ),
        "field_weights": FIELD_WEIGHTS,
        "index_size": len(documents),
        "question_count": len(questions),
        "ineligible": ineligible,
        "endpoints_are_separate": (
            "P4c-Core and P4c-Global carry separate verdicts and are never "
            "summed, averaged or reported as one number."
        ),
        "P4c_Core": {
            "design": "the correct source document lineage is given as a condition",
            "scored_question_count": len(scored_core),
            "q1_count": len(q1_core),
            "c1_count": len(c1_core),
            "measures": core_measures,
            "by_source_family": by_family(
                scored_core, ("target_in_top_10", "target_unique_top_1", "exact_top_score_tie")
            ),
            "revision_selection": revision,
            "gates": core_gates,
            "verdict": core_verdict,
            "gpu_eligibility": (
                "a PASS here, together with the source-coverage gates, makes a "
                "controlled model experiment eligible to be proposed. It is not "
                "an authorisation and it is not a spend approval."
            ),
        },
        "P4c_Global": {
            "design": "the whole corpus, nothing given",
            "scored_question_count": len(scored_global),
            "measures": global_measures,
            "by_source_family": by_family(
                scored_global, ("lineage_at_1", "target_in_top_10", "exact_top_score_tie")
            ),
            "gates": global_gates,
            "verdict": global_verdict,
            "failure_does_not_invalidate_core": True,
            "consequence_of_failure": (
                "the global end-to-end GPU endpoint stays closed. Core eligibility is unaffected."
            ),
        },
        "determinism_check": {"reversed_insertion_order_reproduces_every_score": deterministic},
        "gpu_authorised_by_this_result": False,
        "core_rows": core,
        "global_rows": glob,
        "rows_sha256": canonical_sha([core, glob]),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    written = write_immutable(
        "p4c-retrieval-validity", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(
        json.dumps(
            {
                "core_verdict": core_verdict,
                "global_verdict": global_verdict,
                "questions": len(scored_core),
                "documents": docs,
                "families": families,
                "core": {k: round(v, 4) for k, v in core_measures.items()},
                "global": {k: round(v, 4) for k, v in global_measures.items()},
                "lexical_only_q1": {
                    k: round(v, 4)
                    for k, v in revision["LEXICAL_ONLY"].items()
                    if isinstance(v, float)
                },
                "core_gates": {name: gate["passed"] for name, gate in core_gates.items()},
                "global_gates": {name: gate["passed"] for name, gate in global_gates.items()},
                **written,
            },
            sort_keys=True,
        )
    )
    return 0 if core_verdict == "PASS" and global_verdict == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()
    manifest = args.manifest
    if manifest is None:
        pointer = json.loads(
            (NS / "receipts" / "latest" / "p4c-cohort-manifest.json").read_text(encoding="utf-8")
        )
        manifest = ROOT / pointer["points_to"]
    return run(manifest)


if __name__ == "__main__":
    raise SystemExit(main())
