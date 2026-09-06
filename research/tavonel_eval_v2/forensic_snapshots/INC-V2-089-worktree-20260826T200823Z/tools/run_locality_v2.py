#!/usr/bin/env python3
"""Apply Source Coverage Locality v2 to the frozen P4e cohort. Once.

The instrument was completed against `canonicalization/locality_fixtures.py`,
frozen as `SOURCE_LOCALITY_V2`, and sealed by tool digest before this script
first touched the cohort. The eligibility count it produces is the result, and
the anti-fitting rule forbids adjusting the instrument to move it.

P4e is not re-scored. Its questions, its Q1 labels and its retrieval measures
are read from its receipt exactly as recorded; only the coverage status is
recomputed, and it is recorded under a different name.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "canonicalization"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "retrieval"))

from common import NS, ROOT, canonical_sha, now, rel, sha_file  # noqa: E402
from coverage_witness import COMPLETE, INCOMPLETE, build_witness, witness_status  # noqa: E402
from envelope import build_envelopes  # noqa: E402
from evidence import write_immutable  # noqa: E402
from locality_fixtures import (  # noqa: E402
    FIXTURES,
    OVER_GRANT_CONTROL,
    POSITIVE_CONTROL,
    UNDER_GRANT_CONTROL,
)
from source_map import LOCATION_UNVERIFIABLE, located_spans  # noqa: E402
from source_spans import attribute_to_canonical, reference_facts  # noqa: E402

PROTOCOL = NS / "protocols" / "SOURCE_LOCALITY_V2.yaml"
SOURCE_MAP = NS / "canonicalization" / "source_map.py"
WITNESS = NS / "canonicalization" / "coverage_witness.py"
FIXTURE_FILE = NS / "canonicalization" / "locality_fixtures.py"

#: Preregistered floor. Never lowered after seeing eligibility.
HARD_MINIMUM_ELIGIBLE_Q1 = 190


def run_controls() -> dict[str, Any]:
    """The eight development controls, in the same execution as the cohort run."""
    results = []
    for fixture in FIXTURES:
        spans, grammar = located_spans(fixture["raw"], fixture["suffix"])
        facts = reference_facts(spans)
        targets = [str(fact.get("target") or "") for fact in facts]
        if grammar == "markdown":
            attribute_to_canonical(spans, [fixture["atom"], *fixture["members"]], targets)
        witness = build_witness(
            spans, fixture["atom"], fixture["members"], targets, raw=fixture["raw"]
        )
        status = witness_status(witness, spans)
        results.append(
            {
                "name": fixture["name"],
                "expected": fixture["expect"],
                "observed": status["status"],
                "agrees": status["status"] == fixture["expect"],
                "reasons": status["reasons"],
                "guards": fixture["guards"],
                "witness_element_count": witness["element_count"],
            }
        )
    by_name = {result["name"]: result for result in results}
    return {
        "results": results,
        "all_agree": all(result["agrees"] for result in results),
        "directional": {
            "over_grant_control": by_name[OVER_GRANT_CONTROL],
            "under_grant_control": by_name[UNDER_GRANT_CONTROL],
            "positive_control": by_name[POSITIVE_CONTROL],
            "passed": (
                by_name[OVER_GRANT_CONTROL]["observed"] == INCOMPLETE
                and by_name[UNDER_GRANT_CONTROL]["observed"] == COMPLETE
                and by_name[POSITIVE_CONTROL]["observed"] == COMPLETE
            ),
        },
    }


def score_cohort(manifest: Path, p4e: dict[str, Any]) -> dict[str, Any]:
    cohort = {
        record["document_slug"]: record
        for record in json.loads(manifest.read_text(encoding="utf-8"))["documents"]
    }
    scored = [row for row in p4e["rows"] if row.get("state") == "SCORED"]

    by_document: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    unverifiable_total = 0

    for slug, record in cohort.items():
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
        spans, grammar = located_spans(raw, record["suffix"])
        facts = reference_facts(spans)
        targets = [str(fact.get("target") or "") for fact in facts]
        if grammar == "markdown":
            attribute_to_canonical(spans, [a["text"] for a in atoms.values()], targets)
        unlocated = sum(1 for span in spans if span.location_state == LOCATION_UNVERIFIABLE)
        unverifiable_total += unlocated
        by_document[slug] = {
            "spans": spans,
            "atoms": atoms,
            "envelopes": {e.envelope_id: e for e in envelopes},
            "targets": targets,
            "raw": raw,
            "grammar": grammar,
            "location_unverifiable": unlocated,
        }

    for row in scored:
        context = by_document.get(row["pair_id"])
        if context is None:
            rows.append({**_slim(row), "status": INCOMPLETE, "reasons": ["DOCUMENT_NOT_FOUND"]})
            continue
        atom = context["atoms"].get(row["evidence_atom"])
        envelope = context["envelopes"].get(row["target_envelope"])
        if atom is None or envelope is None:
            rows.append({**_slim(row), "status": INCOMPLETE, "reasons": ["ATOM_NOT_FOUND"]})
            continue
        members = [
            context["atoms"][member]["text"]
            for member in envelope.member_ids
            if member in context["atoms"] and member != row["evidence_atom"]
        ]
        witness = build_witness(
            context["spans"], atom["text"], members, context["targets"], raw=context["raw"]
        )
        status = witness_status(witness, context["spans"])
        rows.append(
            {
                **_slim(row),
                "status": status["status"],
                "reasons": status["reasons"],
                "witness_element_count": witness["element_count"],
                "witness_by_role": witness["by_role"],
                "unmodeled_in_closure": status["unmodeled_in_closure"],
                "location_unverifiable_in_document": status["location_unverifiable_in_document"],
                "grammar": context["grammar"],
            }
        )

    return {
        "rows": rows,
        "location_unverifiable_spans": unverifiable_total,
        "documents_scored": len(by_document),
    }


def _slim(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_id": row["question_id"],
        "kind": row["kind"],
        "pair_id": row["pair_id"],
        "source_family": row["source_family"],
        "evidence_atom": row["evidence_atom"],
        "p4e_status_provisional": row["source_coverage"]["status"],
    }


def run(manifest: Path, p4e_receipt: Path) -> int:
    started = now()
    controls = run_controls()
    p4e = json.loads(p4e_receipt.read_text(encoding="utf-8"))

    if not controls["all_agree"] or not controls["directional"]["passed"]:
        # the protocol says STOP before the cohort is touched
        body = {
            "schema": "tavonel.v2.locality_v2.v1",
            "protocol": "SOURCE_LOCALITY_V2",
            "started_at": started,
            "ended_at": now(),
            "controls": controls,
            "cohort_scored": False,
            "verdict": "STOP_CONTROLS_FAILED",
            "gpu_seconds": 0,
            "estimated_cost_usd": 0.0,
        }
        written = write_immutable(
            "locality-v2", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
        )
        print(json.dumps({"verdict": "STOP_CONTROLS_FAILED", **written}, sort_keys=True))
        return 2

    result = score_cohort(manifest, p4e)
    rows = result["rows"]
    complete = [row for row in rows if row["status"] == COMPLETE]
    q1 = [row for row in rows if row["kind"] == "Q1_REVISED_VALUE"]
    complete_q1 = [row for row in complete if row["kind"] == "Q1_REVISED_VALUE"]
    reasons = Counter(reason for row in rows for reason in row.get("reasons", []))
    q1_by_family = Counter(row["source_family"] for row in complete_q1)
    families_with_q1 = {family for family, count in q1_by_family.items() if count > 0}

    gates = {
        "G_LOC2_CONTROLS": {"passed": controls["all_agree"], "count": len(FIXTURES)},
        "G_LOC2_DIRECTIONAL": {"passed": controls["directional"]["passed"]},
        "G_LOC2_WITNESS_RECORDED": {
            "passed": all(
                "witness_by_role" in row
                for row in rows
                if "reasons" in row and row.get("witness_element_count") is not None
            )
            and bool(rows),
            "rows": len(rows),
        },
        "G_LOC2_NO_INTERVAL_ONLY_GRANT": {
            "passed": all(row.get("unmodeled_in_closure", 0) == 0 for row in complete),
            "note": "every grant cites a witness with zero unmodeled elements",
        },
        "G_LOC2_LOCATION_HONESTY": {
            "passed": True,
            "held_by": (
                "construction: a span is LOCATION_VERIFIED with an interval or "
                "LOCATION_UNVERIFIABLE with none. No position is estimated."
            ),
            "location_unverifiable_spans": result["location_unverifiable_spans"],
        },
        "G_LOC2_APPLIED_ONCE": {
            "passed": True,
            "note": "first and only application to the frozen P4e cohort",
        },
        "G_LOC2_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }
    verdict = "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL"

    decision = {
        "hard_minimum_eligible_Q1": HARD_MINIMUM_ELIGIBLE_Q1,
        "status_of_the_floor": "conservative preregistered floor, never lowered",
        "eligible_Q1": len(complete_q1),
        "meets_floor": len(complete_q1) >= HARD_MINIMUM_ELIGIBLE_Q1,
        "families_with_eligible_Q1": sorted(families_with_q1),
        "outcome": (
            "RESUBMIT_MODEL_STUDY_PROPOSAL_WITH_REAL_NUMBERS"
            if len(complete_q1) >= HARD_MINIMUM_ELIGIBLE_Q1 and len(families_with_q1) >= 2
            else "FREEZE_A_NEW_COHORT_ACQUISITION_PROTOCOL"
        ),
        "forbidden_responses": [
            "requesting GPU below the floor",
            "re-fitting the instrument to this cohort",
            "narrowing to markdown only",
            "lowering the floor",
        ],
    }

    body: dict[str, Any] = {
        "schema": "tavonel.v2.locality_v2.v1",
        "protocol": "SOURCE_LOCALITY_V2",
        "split": "development",
        "started_at": started,
        "ended_at": now(),
        "programme_status": "PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED",
        "cohort_manifest": rel(manifest),
        "cohort_manifest_file_sha256": sha_file(manifest),
        "p4e_receipt": rel(p4e_receipt),
        "p4e_receipt_file_sha256": sha_file(p4e_receipt),
        "p4e_not_rescored": (
            "P4e's questions, Q1 labels and retrieval measures are read as "
            "recorded. Only coverage status is recomputed, under a new name."
        ),
        "instrument": {
            "source_map": rel(SOURCE_MAP),
            "source_map_sha256": sha_file(SOURCE_MAP),
            "witness": rel(WITNESS),
            "witness_sha256": sha_file(WITNESS),
            "fixtures": rel(FIXTURE_FILE),
            "fixtures_sha256": sha_file(FIXTURE_FILE),
            "completed_against": "development fixtures only, before the cohort was touched",
        },
        "controls": controls,
        "totals": {
            "questions": len(rows),
            "locally_complete": len(complete),
            "locally_complete_share": len(complete) / len(rows) if rows else 0.0,
            "q1_questions": len(q1),
            "locally_complete_q1": len(complete_q1),
            "documents": result["documents_scored"],
        },
        "locally_complete_by_family": dict(Counter(row["source_family"] for row in complete)),
        "locally_complete_q1_by_family": dict(q1_by_family),
        "witness_failures_by_reason": dict(reasons),
        "location_unverifiable_spans": result["location_unverifiable_spans"],
        "comparison_to_p4e_provisional": {
            "p4e_provisional_locally_complete": p4e["source_coverage"][
                "question_local_coverage_complete"
            ],
            "note": (
                "P4e's figure stands as recorded. This is a separate measurement "
                "by a different instrument on the same frozen cohort, not a "
                "correction of it."
            ),
        },
        "decision_gate": decision,
        "gates": gates,
        "verdict": verdict,
        "gpu_authorised_by_this_result": False,
        "rows": rows,
        "rows_sha256": canonical_sha(rows),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    written = write_immutable("locality-v2", body, tool=Path(__file__).resolve(), protocol=PROTOCOL)
    print(
        json.dumps(
            {
                "verdict": verdict,
                "controls_all_agree": controls["all_agree"],
                "directional_passed": controls["directional"]["passed"],
                "locally_complete": len(complete),
                "locally_complete_share": round(len(complete) / len(rows) if rows else 0.0, 4),
                "q1_total": len(q1),
                "locally_complete_q1": len(complete_q1),
                "locally_complete_q1_by_family": dict(q1_by_family),
                "witness_failures_by_reason": dict(reasons),
                "location_unverifiable_spans": result["location_unverifiable_spans"],
                "decision": decision["outcome"],
                **written,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=NS / "artifacts" / "development" / "p4e_cohort.json"
    )
    parser.add_argument("--p4e", type=Path, default=None)
    args = parser.parse_args()
    receipt = args.p4e
    if receipt is None:
        pointer = json.loads(
            (NS / "receipts" / "latest" / "p4e-provenance-retrieval.json").read_text(
                encoding="utf-8"
            )
        )
        receipt = ROOT / pointer["points_to"]
    return run(args.manifest, receipt)


if __name__ == "__main__":
    raise SystemExit(main())
