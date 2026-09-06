"""Append the scientific adjudication of V2R1. Additive. Nothing is rewritten.

The V2R1 measurement receipt is immutable and stays exactly as written: its
frozen scorer returned FAIL, and that is a true statement about what happened.
What it is NOT is a statement about production, because the frozen
INVARIANT_6(d) encoded an identity model production does not use.

    raw_execution_verdict            FAIL
    scientific_adjudication          INVALID_INSTRUMENT_CONTRACT
    production_failure_established   false
    corpus_spent                     true
    rescore_permitted                false

This tool recomputes the forensic evidence rather than transcribing it, so the
adjudication binds numbers it has itself observed.
"""

from __future__ import annotations

import collections
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "tools"),
    str(NS / "compiler"),
    str(NS / "acquisition"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import freeze_migration_closure_v2r1 as fz  # noqa: E402
import selective_build as engine  # noqa: E402
from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalMatch,
    assign_one_to_one,
)
from evidence import write_immutable  # noqa: E402

STEM = "identity-change-migration-closure-v2r1-adjudication"
MEASUREMENT_GLOB = "identity-change-migration-closure-v2r1--*.json"

VIOLATING_LINEAGES = (
    "ecfr:40:273:273.3",
    "git:qdrant/landing_page:qdrant-landing/content/documentation/capacity-planning.md",
    "ecfr:47:54:54.101",
)


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def forensics() -> dict[str, Any]:
    """Recompute the resolver dispositions for the three violating lineages."""
    ws = fz.Workspace()
    protocol = fz.load_protocol(ws.protocol)
    universe = fz.latest_receipt(fz.stem_for(protocol, "universe"), ws.receipts)

    rows: dict[str, Any] = {}
    matched_with_different_raw_id = 0
    for lineage_id in VIOLATING_LINEAGES:
        row = next(r for r in universe["pairs"] if r["lineage_id"] == lineage_id)
        before = json.loads((ROOT / row["before"]["canonical_path"]).read_text(encoding="utf-8"))
        after = json.loads((ROOT / row["after"]["canonical_path"]).read_text(encoding="utf-8"))
        before_units, _ = engine.snapshots(before)
        after_units, _ = engine.snapshots(after)
        source = after["source_id"]

        decisions = assign_one_to_one(
            [unit.fingerprint(source_lineage=source) for unit in after_units],
            [unit.fingerprint(source_lineage=source) for unit in before_units],
            resolver=LogicalIdentityResolver(),
        )
        counts: collections.Counter[str] = collections.Counter()
        differing = 0
        for incoming, decision in zip(after_units, decisions, strict=True):
            counts[decision.match.name] += 1
            if (
                decision.match is LogicalMatch.MATCHED
                and decision.logical_id
                and decision.logical_id != incoming.logical_id
            ):
                differing += 1
        matched_with_different_raw_id += differing

        before_ids = {unit.logical_id for unit in before_units}
        after_ids = {unit.logical_id for unit in after_units}
        rows[lineage_id] = {
            "before_units": len(before_units),
            "after_units": len(after_units),
            "raw_logical_id_overlap": len(before_ids & after_ids),
            "resolver_dispositions": dict(counts),
            "matched_with_different_incoming_raw_id": differing,
        }

    return {
        "lineages": rows,
        "matched_with_different_raw_id_total": matched_with_different_raw_id,
        "recomputed_here": True,
    }


def build() -> dict[str, Any]:
    receipts = NS / "receipts"
    measurement = sorted(receipts.glob(MEASUREMENT_GLOB))
    if not measurement:
        raise RuntimeError("no V2R1 measurement receipt exists to adjudicate")
    measurement_path = measurement[-1]
    measured = json.loads(measurement_path.read_text(encoding="utf-8"))
    six = measured["INVARIANT_6_ambiguous_identity_stays_unresolved"]

    scorer_freeze = sorted(
        receipts.glob("identity-change-migration-closure-v2r1-scorer-freeze--*.json")
    )[-1]
    protocol_freeze = sorted(
        receipts.glob("identity-change-migration-closure-v2r1-protocol-freeze--*.json")
    )[-1]

    evidence = forensics()

    violations = six["violations"]
    appeared = sum(1 for v in violations if "appeared" in v["why"])
    disappeared = sum(1 for v in violations if "left the diff" in v["why"])

    return {
        "schema": "tavonel.v2.identity_change_migration_closure.adjudication.v1",
        "subject": {
            "protocol_id": "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R1",
            "measurement_receipt": measurement_path.name,
            "measurement_receipt_sha256": _sha(measurement_path),
            "protocol_freeze_receipt": protocol_freeze.name,
            "protocol_freeze_receipt_sha256": _sha(protocol_freeze),
            "protocol_sha256": _sha(
                NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R1.yaml"
            ),
            "scorer_freeze_receipt": scorer_freeze.name,
            "scorer_freeze_receipt_sha256": _sha(scorer_freeze),
            "scorer_module_sha256": _sha(NS / "tools" / "identity_change_migration_closure_v2.py"),
        },
        "raw_execution_verdict": "FAIL",
        "scientific_adjudication": "INVALID_INSTRUMENT_CONTRACT",
        "production_correctness_verdict": "NOT_ESTABLISHED",
        "production_failure_established": False,
        "corpus_status": "SPENT",
        "corpus_spent": True,
        "rescore_permitted": False,
        "why_invalid": (
            "the frozen INVARIANT_6(d) equated raw revision-local logical-id equality "
            "with resolver-established cross-revision identity. "
            "`selective_build.snapshots` derives a snapshot logical id from "
            "source_id + explicit_path, so an incoming unit's revision-local id "
            "changes when its path changes; `LogicalIdentityResolver` exists "
            "precisely to bridge that, and on MATCHED returns the BEFORE-side stable "
            "logical id while the incoming snapshot keeps its own. "
            "`before_ids & after_ids` is therefore not the set of cross-revision "
            "identity matches, and a clause built on it measures the wrong property."
        ),
        "reclassification": {
            "total_clause_d_violations": six["violation_count"],
            "reported_as_silent_appearance": appeared,
            "reported_as_silent_disappearance": disappeared,
            "all_are_instrument_false_violations": True,
            "resolver_matched_with_differing_raw_ids": evidence[
                "matched_with_different_raw_id_total"
            ],
            "arithmetic": "14 + 2 + 1 = 17 alleged silent appearances, all resolver-MATCHED",
            "the_13_disappearances_are": (
                "the before-side counterparts consumed by those same MATCHED "
                "decisions, correctly not reported as removed"
            ),
            "superseded_analysis": (
                "an earlier 13/17 split attributed 13 to a scorer gap around "
                "EVIDENCE_MOVED and 17 to a production representation gap. Both halves "
                "were wrong: the split described a symptom of the wrong ontology rather "
                "than two independent causes."
            ),
        },
        "forensics": evidence,
        "evidence_moved_ruling": {
            "is_a_production_correctness_defect": False,
            "why": (
                "EVIDENCE_MOVED is emitted only AFTER the resolver has already matched "
                "a counterpart, so it is a facet event on an established "
                "correspondence, not an identity disposition. Production keys it to "
                "the stable resolved prior logical identity, which is consistent with "
                "MATCHED semantics; the after-side raw snapshot id is not necessarily "
                "the enduring identity."
            ),
            "recorded_instead_as": "representation / observability debt",
            "debt": (
                "SemanticDiff publishes no first-class matched-correspondence surface, "
                "which forced the external scorer to reconstruct matching and "
                "contributed to the bad inference"
            ),
            "production_must_not_be_altered": (
                "no change to production may be made merely to turn the spent V2R1 receipt green"
            ),
        },
        "must_not_be_described_as": [
            "a successful closure",
            "evidence that production failed INVARIANT_6",
            "a PASS",
        ],
        "successor": "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2",
        "v2r1_lineages_excluded_from_successor": True,
        "the_three_violating_lineages_may_be": (
            "DEVELOPMENT / FORENSIC regression cases only, because they are spent. "
            "They may never certify V2R2."
        ),
        "raw_receipt_untouched": True,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    body = build()
    body.update(write_immutable(STEM, body, tool=Path(__file__).resolve()))
    print(json.dumps({k: v for k, v in body.items() if k != "forensics"}, indent=1)[:1800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
