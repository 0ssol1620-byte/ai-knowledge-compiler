"""Append the scientific adjudication of V2R2. Additive. Nothing is rewritten.

The V2R2 measurement receipt is immutable and stays exactly as written: its
frozen scorer returned FAIL with 13 clause-(d) violations, and that is a true
statement about what happened. What it is NOT is a statement about production,
because the frozen INVARIANT_6 carried CONTRADICTORY OBLIGATIONS.

    raw_execution_verdict            FAIL
    scientific_adjudication          INVALID_INSTRUMENT_CONTRACT
    production_failure_established   false
    corpus_spent                     true
    rescore_permitted                false

THE CONTRADICTION, which is the whole finding. For a unit in

    resolver NEW  ∩  quarantined

V2R2's clause (d) disposition B REQUIRED `unit_added`, while the INC-V2-047
compatibility contract -- written before the ladder rungs and long before V2R2 --
FORBIDS `unit_added` on any quarantined member, and V2R2's own clause (e)
REQUIRED `identity_unresolved` for the same unit. No implementation could satisfy
that state. It is not that disposition B was slightly strict; it is that the
instrument asked for something and its own other half forbade it.

This tool RECOMPUTES the evidence rather than transcribing it, so the
adjudication binds numbers it has itself observed: for each of the 13 it
re-derives the resolver decision, tests quarantine membership, and reads what
production actually emitted.

`build_quarantine` is used here for FORENSICS ONLY. It may not be the expected
side of a measurement -- that would compare production to itself -- and V2R3
builds an independent oracle from the contract instead. Diagnosing what
production did with its own quarantine is a different question from grading it.
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

import freeze_migration_closure_v2r2 as fz  # noqa: E402
import selective_build as engine  # noqa: E402
from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalMatch,
    assign_one_to_one,
)
from akc_cir.identity_quarantine import build_quarantine  # noqa: E402
from akc_cir.semantic_diff import ChangeKind, DiffLevel, diff_documents  # noqa: E402
from evidence import write_immutable  # noqa: E402

STEM = "identity-change-migration-closure-v2r2-adjudication"
MEASUREMENT_GLOB = "identity-change-migration-closure-v2r2--*.json"
CONTRACT = NS / "docs" / "COMPAT_IDENTITY_UNCERTAINTY_QUARANTINE.md"
DIFFERENTIAL_GLOB = "identity-quarantine-differential--*.json"


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def forensics(violations: list[dict[str, Any]]) -> dict[str, Any]:
    """Re-derive, for every violating unit, what the resolver and the diff did."""
    ws = fz.workspace()
    protocol = fz.base.load_protocol(ws.protocol)
    universe = fz.base.latest_receipt(fz.base.stem_for(protocol, "universe"), ws.receipts)
    rows = {row["lineage_id"]: row for row in universe["pairs"]}

    wanted: dict[str, set[str]] = collections.defaultdict(set)
    for violation in violations:
        wanted[violation["lineage_id"]].add(violation["logical_id"])

    per_lineage: dict[str, Any] = {}
    census: collections.Counter[str] = collections.Counter()

    for lineage_id, ids in sorted(wanted.items()):
        row = rows[lineage_id]
        before = json.loads((ROOT / row["before"]["canonical_path"]).read_text(encoding="utf-8"))
        after = json.loads((ROOT / row["after"]["canonical_path"]).read_text(encoding="utf-8"))
        before_units, before_shape = engine.snapshots(before)
        after_units, after_shape = engine.snapshots(after)
        source = after["source_id"]

        decisions = assign_one_to_one(
            [unit.fingerprint(source_lineage=source) for unit in after_units],
            [unit.fingerprint(source_lineage=source) for unit in before_units],
            resolver=LogicalIdentityResolver(),
        )
        before_ids = frozenset(unit.logical_id for unit in before_units)

        unsettled: list[tuple[str, tuple[str, ...], str | None]] = []
        definite: list[tuple[str, str]] = []
        by_incoming: dict[str, Any] = {}
        for incoming, decision in zip(after_units, decisions, strict=True):
            by_incoming[incoming.logical_id] = decision
            if decision.match is LogicalMatch.AMBIGUOUS:
                unsettled.append(
                    (incoming.logical_id, tuple(decision.candidates or ()), decision.logical_id)
                )
            elif decision.logical_id:
                definite.append((incoming.logical_id, decision.logical_id))
        quarantine = build_quarantine(
            unsettled_decisions=unsettled, definite_matches=definite, before_ids=before_ids
        )

        diff = diff_documents(
            before_sha256=before["source_digest"],
            after_sha256=after["source_digest"],
            level=DiffLevel.GRAPH,
            before_shape=before_shape,
            after_shape=after_shape,
            before_units=before_units,
            after_units=after_units,
            source=source,
        )
        as_subject: dict[str, list[str]] = collections.defaultdict(list)
        as_candidate: dict[str, list[str]] = collections.defaultdict(list)
        for change in diff.changes:
            if change.logical_id:
                as_subject[change.logical_id].append(change.kind.value)
            for candidate in change.candidates or ():
                if candidate:
                    as_candidate[candidate].append(change.kind.value)

        units: dict[str, Any] = {}
        for logical_id in sorted(ids):
            decision = by_incoming.get(logical_id)
            implicated = (decision.logical_id or logical_id) if decision else logical_id
            row_out = {
                "resolver_decision": decision.match.name if decision else "ABSENT",
                "implicated_identity": implicated,
                "quarantined": implicated in quarantine,
                "production_emitted_as_subject": as_subject.get(logical_id, []),
                "production_named_as_candidate_in": as_candidate.get(logical_id, []),
            }
            row_out["effective_disposition_should_be"] = (
                "EFFECTIVE_UNRESOLVED" if row_out["quarantined"] else "EFFECTIVE_NEW"
            )
            census[
                f"{row_out['resolver_decision']}+"
                f"{'QUARANTINED' if row_out['quarantined'] else 'CLEAN'}"
            ] += 1
            if ChangeKind.IDENTITY_UNRESOLVED.value in row_out["production_emitted_as_subject"]:
                census["stated_as_identity_unresolved"] += 1
            if ChangeKind.UNIT_ADDED.value in row_out["production_emitted_as_subject"]:
                census["asserted_as_unit_added"] += 1
            units[logical_id] = row_out

        #: The comparison that shows the suppression is SELECTIVE. A diff that
        #: withheld `unit_added` from everything would be a different problem;
        #: this one withholds it exactly from the quarantined units.
        added_here = sum(1 for c in diff.changes if c.kind is ChangeKind.UNIT_ADDED)
        per_lineage[lineage_id] = {
            "before_units": len(before_units),
            "after_units": len(after_units),
            "quarantine_members": len(quarantine.members),
            "unit_added_emitted_for_non_quarantined_new": added_here,
            "violating_units": units,
        }

    return {
        "lineages": per_lineage,
        "census": dict(census),
        "recomputed_here": True,
        "build_quarantine_used_for": (
            "FORENSICS ONLY. Production's own quarantine may never be the expected "
            "side of a measurement -- that compares production to itself. V2R3 "
            "builds an independent oracle from the compatibility contract."
        ),
    }


def build() -> dict[str, Any]:
    receipts = NS / "receipts"
    measurement_path = sorted(receipts.glob(MEASUREMENT_GLOB))[-1]
    measured = json.loads(measurement_path.read_text(encoding="utf-8"))
    six = measured["INVARIANT_6_ambiguous_identity_stays_unresolved"]

    protocol_freeze = sorted(
        receipts.glob("identity-change-migration-closure-v2r2-protocol-freeze--*.json")
    )[-1]
    scorer_freeze = sorted(
        receipts.glob("identity-change-migration-closure-v2r2-scorer-freeze--*.json")
    )[-1]
    differential = sorted(receipts.glob(DIFFERENTIAL_GLOB))[-1]

    evidence = forensics(six["violations"])
    dispositions = collections.Counter(v.get("disposition") for v in six["violations"])

    return {
        "schema": "tavonel.v2.identity_change_migration_closure.adjudication.v1",
        "subject": {
            "protocol_id": "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2",
            "measurement_receipt": measurement_path.name,
            "measurement_receipt_sha256": _sha(measurement_path),
            "protocol_freeze_receipt": protocol_freeze.name,
            "protocol_sha256": _sha(
                NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2.yaml"
            ),
            "scorer_freeze_receipt": scorer_freeze.name,
            "scorer_freeze_receipt_sha256": _sha(scorer_freeze),
            "scorer_module_sha256": _sha(
                NS / "tools" / "identity_change_migration_closure_v2r2.py"
            ),
            "invariant_module_sha256": _sha(NS / "tools" / "v2r2_invariant6.py"),
            "surface_module_sha256": _sha(NS / "tools" / "v2r2_resolver_surface.py"),
        },
        "raw_execution_verdict": "FAIL",
        "raw_invariant_6": "VIOLATED",
        "clause_d_raw_violations": six["violation_count"],
        "raw_violation_dispositions": {k: v for k, v in dispositions.items() if k},
        "scientific_adjudication": "INVALID_INSTRUMENT_CONTRACT",
        "production_correctness_verdict": "NOT_ESTABLISHED",
        "production_failure_established": False,
        "corpus_status": "SPENT",
        "corpus_spent": True,
        "rescore_permitted": False,
        "invalidity": (
            "V2R2 treated a resolver-local NEW decision as a FINAL EFFECTIVE IDENTITY "
            "DISPOSITION even when the same unit was quarantined. The resolver's "
            "decision is one layer; the identity quarantine is an overlay on top of "
            "it; the effective disposition is their composition. V2R2 had no third "
            "layer and read the first as if it were."
        ),
        "contradiction": {
            "state": "resolver NEW INTERSECT quarantined",
            "clause_d_B_required": "unit_added",
            "quarantine_contract_forbade": "unit_added",
            "clause_e_required": "identity_unresolved",
            "satisfiable": False,
            "why": (
                "no implementation can emit and not emit the same record. The "
                "instrument did not measure a property production failed; it "
                "described a state production is forbidden to occupy."
            ),
        },
        "preexisting_semantics": {
            "compatibility_contract": "docs/COMPAT_IDENTITY_UNCERTAINTY_QUARANTINE.md",
            "compatibility_contract_sha256": _sha(CONTRACT),
            "clause_2_verbatim": (
                "No quarantined member receives a concrete identity-sensitive "
                "outcome. Not `UNIT_ADDED`, not `UNIT_REMOVED`, not `MODIFIED_CLAIM`. "
                "The guard is asked before every one of those exits, not before some "
                "of them."
            ),
            "contract_predates_v2r2": True,
            "production_guard_predates_v2r2": True,
            "production_guard_location": (
                "akc_cir.semantic_diff, quarantine tested before every definite exit "
                "and above the NEW branch. Its own comment records that placing it "
                "BELOW the NEW branch produced 12 violations in a development replay, "
                "all `unit_added` on a quarantined id."
            ),
            "differential_receipt": differential.name,
            "differential_receipt_sha256": _sha(differential),
            "why_this_block_matters": (
                "it proves the adjudication is NOT an outcome-conditioned relaxation. "
                "Every semantics cited here was written, implemented and receipted "
                "before V2R2 was drafted. The instrument contradicted a contract that "
                "already existed; nothing is being loosened after seeing a result."
            ),
        },
        "forensics": evidence,
        "production_must_not_be_changed": [
            "do not move the quarantine guard below NEW",
            "do not emit unit_added alongside identity_unresolved",
            "do not weaken the quarantine",
            "do not remove the transitive quarantine clause",
            "do not change identity normalisation",
            "do not change the facet predicate",
        ],
        "must_not_be_described_as": [
            "a successful closure",
            "evidence that production violated identity correctness",
            "a PASS",
            "a corrected V2R2 verdict",
        ],
        "successor": "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3",
        "v2r2_lineages_excluded_from_successor": True,
        "the_13_units_may_be": (
            "DEVELOPMENT / FORENSIC regression cases only, because they are spent. "
            "They must be shown to classify as resolver-local NEW plus quarantine "
            "override yielding EFFECTIVE_UNRESOLVED, and they may never become "
            "positive confirmatory evidence."
        ),
        "raw_receipt_untouched": True,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    body = build()
    body.update(write_immutable(STEM, body, tool=Path(__file__).resolve()))
    printable = {k: v for k, v in body.items() if k != "forensics"}
    printable["forensics_census"] = body["forensics"]["census"]
    print(json.dumps(printable, indent=1)[:2600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
