"""The scorer of record for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R1.

READ THE NAME CAREFULLY. This module scores **V2R1**, not the abandoned V2. It
is called `..._v2.py` because the V2R1 protocol names that exact path in
`scorer.modules`, and by the time the mismatch was noticed the protocol was
frozen and acquisition had happened -- which closes the supersede path by
design. Renaming it would break the frozen digest; amending the protocol after
data exists is precisely what the freeze forbids. So the file keeps the name the
contract gave it and says plainly what it is. INC-V2-058.

The abandoned V2 has no scorer and never will: it was classified
ABORTED_BEFORE_FREEZE and its 16-pair universe may never become a positive
confirmatory denominator.

WHAT THIS ADDS TO V1's SCORER. V1 implemented INVARIANT_6 clauses (a) and (b).
Those are reused here rather than reimplemented -- a second implementation of a
check that already passed a frozen closure is a second thing that can drift.
V2R1 adds:

    (c) an AMBIGUOUS decision may not enter matched-facet reproduction
    (d) TOTAL UNIT ACCOUNTING, including silence as a fifth exit
    (e) every quarantined identity stays visible on the declared channel

Clause (e) needs a source of "which identities were unsettled" that is
INDEPENDENT of what the diff chose to emit. Reading it off the diff's own
`identity_unresolved` records would compare the diff to itself and report clean
by construction. So the resolver is run directly, exactly as `matched_pairs`
does, and the unsettled set comes from ITS decisions.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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
import identity_change_migration_closure as base  # noqa: E402
import selective_build as engine  # noqa: E402
import v2r1_invariant6 as inv6  # noqa: E402
from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalMatch,
    assign_one_to_one,
)
from akc_cir.semantic_diff import DiffLevel, diff_documents  # noqa: E402
from evidence import write_immutable  # noqa: E402

STEM = "identity-change-migration-closure-v2r1"


class ClosureRefused(RuntimeError):
    """A precondition of measuring is not met."""


def unsettled_identities(before_units: list[Any], after_units: list[Any], source: str) -> set[str]:
    """Every logical id an AMBIGUOUS decision implicates, from the RESOLVER.

    Independent of the diff on purpose. Clause (e) asks whether production made
    the unsettled identities visible; asking the diff which identities it
    considered unsettled, and then checking it emitted records for those, is a
    question that cannot come back no.
    """
    decisions = assign_one_to_one(
        [unit.fingerprint(source_lineage=source) for unit in after_units],
        [unit.fingerprint(source_lineage=source) for unit in before_units],
        resolver=LogicalIdentityResolver(),
    )
    before_ids = {unit.logical_id for unit in before_units}
    unsettled: set[str] = set()
    for incoming, decision in zip(after_units, decisions, strict=True):
        if decision.match is not LogicalMatch.AMBIGUOUS:
            continue
        unsettled.update(candidate for candidate in (decision.candidates or ()) if candidate)
        #: The INC-V2-047 member: the before-side unit sharing the incoming's own
        #: logical id, implicated by the same unsettled question and named by
        #: nobody. This is the one the defect let escape as `unit_removed`.
        if incoming.logical_id in before_ids:
            unsettled.add(incoming.logical_id)
    return unsettled


def measure_extra_clauses(
    before_document: dict[str, Any],
    after_document: dict[str, Any],
    *,
    declared_record: str,
    level: DiffLevel,
) -> dict[str, Any]:
    """Clauses (c), (d) and (e) for one pair, over the PRODUCTION diff."""
    before_units, before_shape = engine.snapshots(before_document)
    after_units, after_shape = engine.snapshots(after_document)
    source = after_document["source_id"]

    diff = diff_documents(
        before_sha256=before_document["source_digest"],
        after_sha256=after_document["source_digest"],
        level=level,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=after_units,
        source=source,
    )

    before_ids = {unit.logical_id for unit in before_units}
    after_ids = {unit.logical_id for unit in after_units}

    d_violations, d_observed = inv6.check_total_accounting(
        diff, before_ids=before_ids, after_ids=after_ids
    )
    unsettled = unsettled_identities(before_units, after_units, source)
    e_violations, e_observed = inv6.check_quarantine_channel(
        diff, unsettled_ids=unsettled, declared_record=declared_record
    )
    matched, _ = base.matched_pairs(before_units, after_units, source)
    reproduced = {counterpart.logical_id for counterpart, _ in matched}
    c_violations, c_observed = inv6.check_ambiguous_not_reproduced(unsettled, reproduced)

    return {
        "c": {"violations": c_violations, "observations": c_observed},
        "d": {"violations": d_violations, "observations": d_observed},
        "e": {"violations": e_violations, "observations": e_observed},
        "unsettled_identities": len(unsettled),
    }


def run(limit: int | None = None) -> dict[str, Any]:
    started = time.time()
    ws = fz.Workspace()

    #: Every rung, every digest, every link. A closure that measures before its
    #: chain is verified is INC-V2-042 with a different subject.
    preconditions = fz.require_execution_preconditions(ws)
    protocol = fz.load_protocol(ws.protocol)

    universe_receipt = fz.latest_receipt(fz.stem_for(protocol, "universe"), ws.receipts)
    if universe_receipt is None:
        raise ClosureRefused("the universe is not frozen")

    existing = sorted((NS / "receipts").glob(f"{STEM}--*.json"))
    if existing:
        raise ClosureRefused(
            "V2R1 has already been measured and it runs EXACTLY ONCE. Re-running a "
            "spent closure on the same corpus is what founder ruling section 12 "
            f"forbids.\n  {existing[-1].name}"
        )

    declared_record = protocol["quarantine_channel"]["production_record"]
    channels, records, unresolved_records, scopes = base._channel_tables(protocol)
    ignore_declaration = protocol["predeclared_ignored_facets"]["by_family"]

    rows = universe_receipt["pairs"]
    if limit is not None:
        rows = rows[:limit]

    pair_results: list[dict[str, Any]] = []
    extra: list[dict[str, Any]] = []
    for row in rows:
        before_document = json.loads(
            (ROOT / row["before"]["canonical_path"]).read_text(encoding="utf-8")
        )
        after_document = json.loads(
            (ROOT / row["after"]["canonical_path"]).read_text(encoding="utf-8")
        )
        declared_ignores = ignore_declaration.get(row["family"])
        if declared_ignores is None:
            raise ClosureRefused(
                f"the frozen protocol declares no ignore policy for family {row['family']!r}"
            )
        result = base.measure_pair(
            before_document,
            after_document,
            channels=channels,
            records=records,
            unresolved_records=unresolved_records,
            scopes=scopes,
            ignored=frozenset(declared_ignores),
        )
        result["lineage_id"] = row["lineage_id"]
        result["family"] = row["family"]
        pair_results.append(result)

        clauses = measure_extra_clauses(
            before_document,
            after_document,
            declared_record=declared_record,
            level=DiffLevel.GRAPH,
        )
        clauses["lineage_id"] = row["lineage_id"]
        clauses["family"] = row["family"]
        extra.append(clauses)

    def collected(clause: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for entry in extra:
            for violation in entry[clause]["violations"]:
                out.append({**violation, "lineage_id": entry["lineage_id"]})
        return out

    c_violations = collected("c")
    d_violations = collected("d")
    e_violations = collected("e")
    a_b_violations = [
        {**violation, "lineage_id": result["lineage_id"]}
        for result in pair_results
        for violation in result["violations"].get("INVARIANT_6", [])
    ]

    invariant_6_violations = a_b_violations + c_violations + d_violations + e_violations
    observations = {
        "a_b": sum(result.get("ambiguity_observations", 0) for result in pair_results),
        "c": sum(entry["c"]["observations"] for entry in extra),
        "d": sum(entry["d"]["observations"] for entry in extra),
        "e": sum(entry["e"]["observations"] for entry in extra),
    }

    by_family: dict[str, int] = {}
    for row in rows:
        by_family[row["family"]] = by_family.get(row["family"], 0) + 1

    invariant_6_met = not invariant_6_violations and observations["d"] > 0

    body = {
        "schema": "tavonel.v2.identity_change_migration_closure.v2r1_result.v1",
        "protocol_id": protocol["protocol_id"],
        "pair_count": len(rows),
        "by_family": dict(sorted(by_family.items())),
        "preconditions": preconditions,
        "universe_sha256": universe_receipt.get("universe_sha256"),
        "INVARIANT_6_ambiguous_identity_stays_unresolved": {
            "met": invariant_6_met,
            "violations": invariant_6_violations,
            "violation_count": len(invariant_6_violations),
            "observations": observations,
            "clause_a_b": {
                "violations": len(a_b_violations),
                "source": "V1 check_ambiguity, reused rather than reimplemented",
            },
            "clause_c": {"violations": len(c_violations), "observations": observations["c"]},
            "clause_d": {"violations": len(d_violations), "observations": observations["d"]},
            "clause_e": {
                "violations": len(e_violations),
                "observations": observations["e"],
                "declared_record": declared_record,
                "unsettled_source": (
                    "the resolver's own AMBIGUOUS decisions, NOT the diff's records -- "
                    "reading the unsettled set off the diff would compare the diff to "
                    "itself and could not come back no"
                ),
            },
            "zero_tolerance": True,
        },
        "unsettled_identities_total": sum(entry["unsettled_identities"] for entry in extra),
        "wall_seconds": round(time.time() - started, 2),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args(argv)

    try:
        body = run(limit=args.limit)
    except (ClosureRefused, fz.FreezeRefused) as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        return 4

    if args.write_receipt:
        body.update(write_immutable(STEM, body, tool=Path(__file__).resolve()))

    six = body["INVARIANT_6_ambiguous_identity_stays_unresolved"]
    print(f"pairs        : {body['pair_count']}  {json.dumps(body['by_family'], sort_keys=True)}")
    print(f"INVARIANT_6  : {'MET' if six['met'] else 'VIOLATED'}")
    print(f"  violations : {six['violation_count']}")
    print(f"  observations: {json.dumps(six['observations'], sort_keys=True)}")
    for clause in ("clause_a_b", "clause_c", "clause_d", "clause_e"):
        print(f"  {clause:11}: {json.dumps(six[clause], sort_keys=True)[:120]}")
    return 0 if six["met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
