"""The scorer of record for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2.

WHAT THIS ADDS TO V1's SCORER. V1 implemented INVARIANT_6 clauses (a) and (b).
Those are reused here rather than reimplemented -- a second implementation of a
check that already passed a frozen closure is a second thing that can drift.
V2R2 adds:

    (c) an AMBIGUOUS decision may not enter matched-facet reproduction
    (d) TOTAL ACCOUNTING over the resolver decision graph
    (e) every quarantined identity stays visible on the declared channel

WHAT CHANGED FROM V2R1, and why the run is a new one rather than a rescore.
V2R1's scorer built a separate view of identity inside each clause, and (d)
built the wrong one: it took `before_ids & after_ids` -- raw revision-local
snapshot ids -- as the set of cross-revision identity matches. It is not.
`selective_build.snapshots` derives a snapshot logical id from
`source_id + explicit_path`, so an incoming unit's id moves when its path moves,
and `LogicalIdentityResolver` exists to bridge exactly that gap. Every one of
V2R1's thirty clause-(d) violations was an instrument false violation. The run
was adjudicated INVALID_INSTRUMENT_CONTRACT, its corpus is SPENT, and it is
never rescored.

So here (c), (d) and (e) consume ONE `ResolverSurface`, built once per pair by
invoking the production resolver directly. Not read off the diff: asking the
diff which identities it considered unsettled, and then checking it emitted
records for those, is a question that cannot come back no.
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

import freeze_migration_closure_v2r2 as fz  # noqa: E402

#: The V2R2 freezer is an ADAPTER over V2R1's, so the ladder helpers live on
#: `fz.base` while the overridden entry points live on `fz`. Reaching for a
#: helper on the adapter raises immediately -- which is how this line came to
#: be written: the derived scorer called `fz.Workspace()` and blew up before
#: it could seal anything against the wrong protocol.
base_fz = fz.base
import identity_change_migration_closure as base  # noqa: E402
import selective_build as engine  # noqa: E402
import v2r2_invariant6 as inv6  # noqa: E402
import v2r2_resolver_surface as surfaces  # noqa: E402
from akc_cir.semantic_diff import DiffLevel, diff_documents  # noqa: E402
from evidence import write_immutable  # noqa: E402

STEM = "identity-change-migration-closure-v2r2"


class ClosureRefused(RuntimeError):
    """A precondition of measuring is not met."""


def measure_extra_clauses(
    before_document: dict[str, Any],
    after_document: dict[str, Any],
    *,
    declared_record: str,
    level: DiffLevel,
) -> dict[str, Any]:
    """Clauses (c), (d) and (e) for one pair, over ONE resolver surface.

    The surface is built first and the diff second, and the two are independent:
    the surface comes from `assign_one_to_one` + `LogicalIdentityResolver`, the
    diff from `diff_documents`. Clause (d) then asks whether the diff discharged
    the obligation each resolver disposition implies. That is the whole
    correction over V2R1 -- identity is decided by the resolver, and the diff is
    graded against it, rather than the diff being graded against a
    reconstruction of itself.
    """
    before_units, before_shape = engine.snapshots(before_document)
    after_units, after_shape = engine.snapshots(after_document)
    source = after_document["source_id"]

    #: Built BEFORE the diff, deliberately. It cannot be influenced by what the
    #: diff emitted, and `build_surface` refuses outright if the partition it
    #: produces is not mechanically exhaustive.
    surface = surfaces.build_surface(before_units, after_units, source)

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

    d_violations, d_observed = inv6.check_total_accounting(diff, surface)
    e_violations, e_observed = inv6.check_quarantine_channel(
        diff, surface, declared_record=declared_record
    )
    #: Reproduction is keyed on the BEFORE-side ids, which is what production
    #: keys matched facets on. Taken from the same surface (c) and (d) read, so
    #: the two can never disagree about who was matched.
    c_violations, c_observed = inv6.check_ambiguous_not_reproduced(
        surface, surface.matched_before_ids
    )

    return {
        "c": {"violations": c_violations, "observations": c_observed},
        "d": {"violations": d_violations, "observations": d_observed},
        "e": {"violations": e_violations, "observations": e_observed},
        "unsettled_identities": len(surface.quarantine_members | surface.ambiguous_after_ids),
        "dispositions": {
            "matched": len(surface.matched),
            "matched_with_differing_raw_ids": sum(
                1
                for correspondence in surface.matched
                if correspondence.before_logical_id != correspondence.after_snapshot_logical_id
            ),
            "new": len(surface.new_after_ids),
            "ambiguous": len(surface.ambiguous_after_ids),
            "unmatched_before": len(surface.unmatched_before_ids),
        },
    }


def run(limit: int | None = None) -> dict[str, Any]:
    started = time.time()
    ws = fz.workspace()

    #: Every rung, every digest, every link. A closure that measures before its
    #: chain is verified is INC-V2-042 with a different subject.
    preconditions = base_fz.require_execution_preconditions(ws)
    protocol = base_fz.load_protocol(ws.protocol)

    universe_receipt = base_fz.latest_receipt(base_fz.stem_for(protocol, "universe"), ws.receipts)
    if universe_receipt is None:
        raise ClosureRefused("the universe is not frozen")

    existing = sorted((NS / "receipts").glob(f"{STEM}--*.json"))
    if existing:
        raise ClosureRefused(
            "V2R2 has already been measured and it runs EXACTLY ONCE. Re-running a "
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
        "schema": "tavonel.v2.identity_change_migration_closure.v2r2_result.v1",
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
                    "the shared ResolverSurface's own AMBIGUOUS decisions and "
                    "quarantine members, NOT the diff's records -- reading the "
                    "unsettled set off the diff would compare the diff to itself and "
                    "could not come back no"
                ),
            },
            "zero_tolerance": True,
        },
        "unsettled_identities_total": sum(entry["unsettled_identities"] for entry in extra),
        #: The census exists so a reader can see the instrument had something to
        #: measure, and specifically that renamed correspondences were PRESENT.
        #: A V2R2 PASS over a cohort containing zero of them would be a pass the
        #: V2R1 defect could also have produced, and saying so afterwards is not
        #: the same as recording it.
        "resolver_dispositions": {
            key: sum(entry["dispositions"][key] for entry in extra)
            for key in (
                "matched",
                "matched_with_differing_raw_ids",
                "new",
                "ambiguous",
                "unmatched_before",
            )
        },
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
    print(f"dispositions : {json.dumps(body['resolver_dispositions'], sort_keys=True)}")
    return 0 if six["met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
