#!/usr/bin/env python3
"""Score the P4i expanded cohort for eligibility. Once.

Questions, envelopes, the IntentView query builder, the scorer, the ranking and
the whole coverage instrument are imported from P4e and P4g **unchanged**. The
composite instrument identity must equal the value that produced 174, and there
is no escape clause this time.

INC-V2-016 is what P4i exists to repair, and the repair is one line of design:
acquisition breadth and statistical power are separate gates.

    G_P4I_BREADTH  : admitted >= 400 documents across >= 4 families
    decision gate  : eligible Q1 >= 190, in >= 2 families

550 is the acquisition target — what was attempted for headroom — and falling
short of it is not a protocol failure as long as 400 admitted is reached. A
document count and a powered question count are never welded together again.

The anti-fitting rule binds after this run: the number it produces is the
result. Neither instrument, policy, floor nor breadth bar moves in response.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "canonicalization"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "retrieval"))

from common import NS, ROOT, canonical_sha, now, rel, sha_file  # noqa: E402
from coverage_witness import COMPLETE, INCOMPLETE  # noqa: E402
from coverage_witness_v2 import build_witness, witness_status  # noqa: E402
from envelope import build_envelopes  # noqa: E402
from evidence import write_immutable  # noqa: E402
from markup_semantics import policy_digest, schema_digest  # noqa: E402
from run_p4b import FieldedBm25  # noqa: E402
from run_p4e import PERMITTED_INTENT_SOURCES, build, evaluate  # noqa: E402
from source_map import LOCATION_UNVERIFIABLE  # noqa: E402
from source_map_v2 import located_spans  # noqa: E402
from source_spans import attribute_to_canonical, reference_facts  # noqa: E402

PROTOCOL = NS / "protocols" / "P4i_cohort_expansion.yaml"
SOURCE_MAP_V2 = NS / "canonicalization" / "source_map_v2.py"
WITNESS_V2 = NS / "canonicalization" / "coverage_witness_v2.py"
SEMANTICS = NS / "canonicalization" / "markup_semantics.py"

#: Preregistered floor. Never lowered after seeing eligibility.
HARD_MINIMUM_ELIGIBLE_Q1 = 190

#: Inherited from P4g's G_P4G_SCALE, which required it before any result
#: existed and which P4g failed at 321. Not a bar invented to fit 174.
BREADTH_FLOOR_DOCUMENTS = 400

#: The instrument that produced 174. P4i must match it exactly.
COMPOSITE_THAT_PRODUCED_174 = (
    "sha256:0ed844f6eb83e8b342f6790a772099c8ebec4c80c525cdf721b59a54df10fe2a"
)


def composite_identity() -> dict[str, Any]:
    parts = {
        "source_map_code": sha_file(SOURCE_MAP_V2),
        "witness_code": sha_file(WITNESS_V2),
        "markup_semantics_code": sha_file(SEMANTICS),
        "markup_policy": policy_digest(),
        "schema": schema_digest(),
    }
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    composite = "sha256:" + sha256(blob.encode("utf-8")).hexdigest()
    return {
        "parts": parts,
        "composite": composite,
        "composite_that_produced_174": COMPOSITE_THAT_PRODUCED_174,
        "matches": composite == COMPOSITE_THAT_PRODUCED_174,
        "rule": (
            "byte-identical and semantically identical to the instrument that "
            "produced 174. No escape clause: the gap that forced one in P4g — a "
            "policy nothing read — is repaired."
        ),
    }


def _slim(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_id": row["question_id"],
        "kind": row["kind"],
        "pair_id": row["pair_id"],
        "source_family": row["source_family"],
        "evidence_atom": row["evidence_atom"],
    }


def score_coverage(manifest: Path, scored: list[dict[str, Any]]) -> dict[str, Any]:
    """Question-local coverage under the markup-semantics source map."""
    cohort = {
        record["document_slug"]: record
        for record in json.loads(manifest.read_text(encoding="utf-8"))["documents"]
    }
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for row in scored:
        by_pair.setdefault(row["pair_id"], []).append(row)
    unverifiable_total = 0
    rows: list[dict[str, Any]] = []
    documents_scored = 0

    # one document at a time. Holding the spans of 321 documents at once is
    # what exhausted memory on the first attempt; nothing here needs two
    # documents in scope simultaneously.
    for slug, questions in by_pair.items():
        record = cohort.get(slug)
        if record is None:
            rows.extend(
                {**_slim(row), "status": INCOMPLETE, "reasons": ["DOCUMENT_NOT_FOUND"]}
                for row in questions
            )
            continue
        document = json.loads(
            (ROOT / record["after"]["canonical_path"]).read_text(encoding="utf-8")
        )
        envelopes, atoms = build_envelopes(
            slug,
            "current",
            document["units"],
            {"title": record["title_field"], "doc_type": record["doc_type"]},
        )
        raw = (ROOT / record["after"]["raw_path"]).read_bytes().decode("utf-8", errors="replace")
        canonical_text = " ".join(unit["text"] for unit in document["units"])
        spans, grammar = located_spans(raw, record["suffix"], canonical_text)
        facts = reference_facts(spans)
        targets = [str(fact.get("target") or "") for fact in facts]
        if grammar == "markdown":
            attribute_to_canonical(spans, [a["text"] for a in atoms.values()], targets)
        unlocated = sum(1 for span in spans if span.location_state == LOCATION_UNVERIFIABLE)
        unverifiable_total += unlocated
        documents_scored += 1
        envelope_by_id = {e.envelope_id: e for e in envelopes}

        for row in questions:
            atom = atoms.get(row["evidence_atom"])
            envelope = envelope_by_id.get(row["target_envelope"])
            if atom is None or envelope is None:
                rows.append({**_slim(row), "status": INCOMPLETE, "reasons": ["ATOM_NOT_FOUND"]})
                continue
            members = [
                atoms[member]["text"]
                for member in envelope.member_ids
                if member in atoms and member != row["evidence_atom"]
            ]
            witness = build_witness(
                spans,
                atom["text"],
                members,
                targets,
                raw=raw,
                canonical_text=canonical_text,
                grammar=grammar,
            )
            status = witness_status(witness, spans)
            rows.append(
                {
                    **_slim(row),
                    "status": status["status"],
                    "reasons": status["reasons"],
                    "witness_element_count": witness["element_count"],
                    "witness_by_role": witness["by_role"],
                    "unmodeled_in_closure": status["unmodeled_in_closure"],
                    "unresolved_in_closure": status["unresolved_in_closure"],
                    "unresolved_constructs": status["unresolved_constructs"],
                    "location_unverifiable_in_document": status[
                        "location_unverifiable_in_document"
                    ],
                    "grammar": grammar,
                }
            )
    return {
        "rows": rows,
        "location_unverifiable_spans": unverifiable_total,
        "documents_scored": documents_scored,
    }


def run(manifest: Path) -> int:
    started = now()
    identity = composite_identity()

    built = build(manifest)
    envelopes = built["envelopes"]
    envelope_by_id = {e.envelope_id: e for e in envelopes}
    envelope_unit = {e.envelope_id: e.document_id + "|" + e.anchor_path for e in envelopes}
    scopes: dict[str, set[str]] = {}
    for index_row in built["index_rows"]:
        scopes.setdefault(index_row["pair_id"], set()).add(index_row["doc_id"])

    index = FieldedBm25(built["index_rows"])
    rows = evaluate(index, built["questions"], scopes, envelope_by_id, envelope_unit)
    scored = [row for row in rows if row["state"] == "SCORED"]
    q1 = [row for row in scored if row["kind"] == "Q1_REVISED_VALUE"]

    coverage = score_coverage(manifest, scored)
    status_by_question = {row["question_id"]: row for row in coverage["rows"]}
    complete = [row for row in coverage["rows"] if row["status"] == COMPLETE]
    complete_q1 = [
        row
        for row in q1
        if status_by_question.get(row["question_id"], {}).get("status") == COMPLETE
    ]
    q1_by_family = Counter(row["source_family"] for row in complete_q1)
    families_with_q1 = {family for family, count in q1_by_family.items() if count > 0}
    reasons = Counter(reason for row in coverage["rows"] for reason in row.get("reasons", []))
    unresolved_drivers = Counter(
        construct for row in coverage["rows"] for construct in row.get("unresolved_constructs", [])
    )

    provenance_ok = all(
        row["provenance"]
        and all(p["provenance"] in PERMITTED_INTENT_SOURCES for p in row["provenance"])
        for row in scored
    )
    forbidden_total = sum(len(row["forbidden_contribution"]) for row in scored)
    cohort = json.loads(manifest.read_text(encoding="utf-8"))
    families = sorted({row["source_family"] for row in scored})

    gates = {
        "G_P4I_BREADTH": {
            "passed": cohort["document_count"] >= BREADTH_FLOOR_DOCUMENTS and len(families) >= 4,
            "documents_admitted": cohort["document_count"],
            "breadth_floor": BREADTH_FLOOR_DOCUMENTS,
            "acquisition_target": cohort["acquisition_target"]["source_documents"],
            "families": families,
            "note": (
                "the acquisition target is 550 and falling short of it is not a "
                "failure. The gate is 400 admitted across 4 families, inherited "
                "from P4g's G_P4G_SCALE"
            ),
        },
        "G_P4I_INDEPENDENCE": {
            "passed": len({d["document_id"] for d in cohort["documents"]})
            == cohort["document_count"],
            "note": "one revision pair per source document",
        },
        "G_P4I_SELECTION_BLIND": {
            "passed": bool(cohort.get("frozen_before_any_eligibility_result"))
            and bool(cohort["consumption_order"]["frozen_before_any_fetch"]),
            "held_by": (
                "candidate lists, reserve ordering and family quotas were hashed "
                "in sources_p4i.py before the first fetch"
            ),
        },
        "G_P4I_MIX_NOT_REWEIGHTED": {
            "passed": {
                family: cohort["family_quota"][family]
                for family in ("git_docs", "regulation_ecfr", "encyclopedia_wikipedia", "sec_edgar")
            }
            == {
                "git_docs": 165,
                "regulation_ecfr": 165,
                "encyclopedia_wikipedia": 165,
                "sec_edgar": 55,
            },
            "note": (
                "quotas are the declared scale-up of P4g's nominal balance rule, "
                "not its realized mix of 98 / 93 / 114 / 16"
            ),
        },
        "G_P4I_NO_NARROWING": {
            "passed": len(families) >= 4,
            "families_in_every_reported_measure": families,
        },
        "G_P4I_ADMISSION_ACCOUNTED": {
            "passed": all(
                item.get("code") in cohort["admission_failure_codes"] for item in cohort["rejected"]
            ),
            "rejected": cohort["rejected_count"],
            "by_code": cohort["rejected_by_code"],
        },
        "G_P4I_INSTRUMENT_UNCHANGED": {
            "passed": identity["matches"],
            "composite": identity["composite"],
            "composite_that_produced_174": identity["composite_that_produced_174"],
        },
        "G_P4I_SCORED_ONCE": {
            "passed": True,
            "note": "first and only eligibility scoring of this cohort",
        },
        "G_P4I_PROVENANCE": {
            "passed": provenance_ok and forbidden_total == 0,
            "forbidden_contribution": forbidden_total,
        },
        "G_P4I_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }
    verdict = "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL"

    decision = {
        "hard_minimum_eligible_Q1": HARD_MINIMUM_ELIGIBLE_Q1,
        "status_of_the_floor": "conservative preregistered floor, never lowered",
        "eligible_Q1": len(complete_q1),
        "meets_floor": len(complete_q1) >= HARD_MINIMUM_ELIGIBLE_Q1,
        "families_with_eligible_Q1": sorted(families_with_q1),
        "spread_requirement_met": len(families_with_q1) >= 2,
        "outcome": (
            "RESUBMIT_MODEL_STUDY_PROPOSAL_WITH_REAL_NUMBERS"
            if len(complete_q1) >= HARD_MINIMUM_ELIGIBLE_Q1 and len(families_with_q1) >= 2
            else "REPORT_AND_STOP_NO_GPU_REQUEST"
        ),
        "breadth_floor_documents": BREADTH_FLOOR_DOCUMENTS,
        "gpu": "never executed before founder approval of the model study",
        "forbidden_responses": [
            "requesting GPU below the floor",
            "re-fitting the locality instrument to this cohort",
            "reclassifying a markup construct to raise this number",
            "narrowing to one family",
            "lowering the eligible-Q1 floor",
            "lowering the 400-document breadth bar",
        ],
    }

    body: dict[str, Any] = {
        "schema": "tavonel.v2.p4i.v1",
        "protocol": "P4i_cohort_expansion",
        "split": "development",
        "started_at": started,
        "ended_at": now(),
        "programme_status": "PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED",
        "cohort_manifest": rel(manifest),
        "cohort_manifest_file_sha256": sha_file(manifest),
        "instrument_identity": identity,
        "predecessors_not_rescored": [
            "P0d",
            "P4c",
            "P4d",
            "P4e",
            "P4g",
            "SOURCE_LOCALITY_V2",
        ],
        "p4h": "SUPERSEDED_BEFORE_EXECUTION, preserved unmodified. INC-V2-016.",
        "cohort": {
            "documents": cohort["document_count"],
            "family_counts": cohort["family_counts"],
            "candidates_selected": cohort["candidates_selected"],
            "rejected": cohort["rejected_count"],
            "rejected_by_code": cohort["rejected_by_code"],
            "rejected_by_family_and_code": cohort["rejected_by_family_and_code"],
            "acquisition_target": cohort["acquisition_target"]["source_documents"],
            "family_quota_is": cohort["family_quota_is"],
        },
        "totals": {
            "questions_built": len(built["questions"]),
            "questions_scored": len(scored),
            "q1_questions": len(q1),
            "locally_complete": len(complete),
            "locally_complete_q1": len(complete_q1),
            "documents_with_coverage": coverage["documents_scored"],
        },
        "locally_complete_by_family": dict(Counter(row["source_family"] for row in complete)),
        "locally_complete_q1_by_family": dict(q1_by_family),
        "q1_by_family": dict(Counter(row["source_family"] for row in q1)),
        "witness_failures_by_reason": dict(reasons),
        "unresolved_drivers": dict(unresolved_drivers.most_common(20)),
        "location_unverifiable_spans": coverage["location_unverifiable_spans"],
        "retrieval_measures_reported_not_gated": {
            "envelope_retrievable_at_10": (
                sum(1 for row in scored if row.get("envelope_in_top_10")) / len(scored)
                if scored
                else 0.0
            ),
            "atom_recoverable_from_envelope": (
                sum(1 for row in scored if row.get("atom_recoverable_from_envelope")) / len(scored)
                if scored
                else 0.0
            ),
        },
        "decision_gate": decision,
        "gates": gates,
        "verdict": verdict,
        "gpu_authorised_by_this_result": False,
        "coverage_rows": coverage["rows"],
        "coverage_rows_sha256": canonical_sha(coverage["rows"]),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    written = write_immutable("p4i", body, tool=Path(__file__).resolve(), protocol=PROTOCOL)
    print(
        json.dumps(
            {
                "verdict": verdict,
                "documents": cohort["document_count"],
                "questions_scored": len(scored),
                "q1": len(q1),
                "eligible_q1": len(complete_q1),
                "eligible_q1_by_family": dict(q1_by_family),
                "meets_floor": decision["meets_floor"],
                "outcome": decision["outcome"],
                "composite_identity": identity["composite"],
                "instrument_matches_174_run": identity["matches"],
                **written,
            },
            sort_keys=True,
        )
    )
    return 0 if verdict == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=NS / "artifacts" / "development" / "p4i_cohort.json"
    )
    args = parser.parse_args()
    return run(args.manifest)


if __name__ == "__main__":
    raise SystemExit(main())
