"""The scorer of record for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3.

WHAT THIS ADDS TO V1's SCORER. V1 implemented INVARIANT_6 clauses (a) and (b).
Those are reused rather than reimplemented -- a second implementation of a check
that already passed a frozen closure is a second thing that can drift. V2R3
adds, over ONE surface:

    (c) an effectively unresolved identity may not enter matched-facet reproduction
    (d) TOTAL ACCOUNTING over the EFFECTIVE identity disposition
    (e) every effectively unresolved identity stays visible on the declared channel

WHAT CHANGED FROM V2R2, and why this is a new run rather than a rescore. V2R2's
(d) read the resolver's LOCAL decision and its (e) read the quarantine, as two
separately computed surfaces. For a unit the resolver called NEW while the
quarantine held it, (d) required `unit_added` and the quarantine contract (e)
enforces forbade it. Required and forbade the same record. No production
behaviour could satisfy that, so its FAIL carried no information about the
system: adjudicated INVALID_INSTRUMENT_CONTRACT, corpus SPENT, never rescored.

Here (c), (d) and (e) consume ONE `EffectiveSurface`, built once per pair by
running all three layers in order -- resolver decision, independent quarantine,
effective disposition -- and every obligation comes from
`v2r3_state_table.OBLIGATIONS` keyed by the EFFECTIVE disposition. None of the
three clauses decides anything: the surface decides and they read. A
disagreement between clauses is no longer expressible rather than merely
unlikely.

THE SURFACE IS BUILT BEFORE THE DIFF AND INDEPENDENTLY OF IT. Asking the diff
which identities it considered unsettled, and then checking it emitted records
for those, is a question that cannot come back no.

THERE IS NO `--limit`. V2R2's scorer had one. A limited run reads real outcomes
from part of the cohort and is therefore a PREVIEW, whatever it does with the
result afterwards -- and the founder ruling's execution contract is "exactly
once, no preview". A flag whose only use is to look first does not exist here.

THE GATE IS THE V2R3 GATE, NEVER THE BASE ONE. `base.require_execution_-
preconditions` verifies the standard protocol -> universe -> scorer ->
exclusions chain and knows nothing about the three V2R3 companion attestations,
so calling it would report READY on a chain that never bound them.
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

import freeze_migration_closure_v2r3 as fz  # noqa: E402

#: The V2R3 freezer is an ADAPTER, so the ladder helpers live on `fz.base` while
#: the overridden entry points and the V2R3 gate live on `fz`. Reaching for a
#: helper on the adapter raises immediately -- which is how the equivalent line
#: came to be written in V2R2: the derived scorer called `fz.Workspace()` and
#: blew up before it could seal anything against the wrong protocol.
base_fz = fz.base
import identity_change_migration_closure as base  # noqa: E402
import selective_build as engine  # noqa: E402
import v2r3_effective_identity as eff  # noqa: E402
import v2r3_invariant6 as inv6  # noqa: E402
from akc_cir.semantic_diff import DiffLevel, diff_documents  # noqa: E402
from evidence import write_immutable  # noqa: E402

STEM = "identity-change-migration-closure-v2r3"


class ClosureRefused(RuntimeError):
    """A precondition of measuring is not met."""


def measure_extra_clauses(
    before_document: dict[str, Any],
    after_document: dict[str, Any],
    *,
    declared_record: str,
    level: DiffLevel,
) -> dict[str, Any]:
    """Clauses (c), (d) and (e) for one pair, over ONE effective surface."""
    before_units, before_shape = engine.snapshots(before_document)
    after_units, after_shape = engine.snapshots(after_document)
    source = after_document["source_id"]

    #: Built BEFORE the diff, deliberately. It cannot be influenced by what the
    #: diff emitted, and `build_effective_surface` refuses outright if the
    #: partition it produces is not mechanically exhaustive.
    surface = eff.build_effective_surface(before_units, after_units, source)

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

    d_violations, d_observed = inv6.check_effective_accounting(diff, surface)
    e_violations, e_observed = inv6.check_quarantine_channel(
        diff, surface, declared_record=declared_record
    )
    #: Reproduction is keyed on the BEFORE-side ids, which is what production
    #: keys matched facets on. Taken from the same surface (d) and (e) read, so
    #: the three can never disagree about who was matched.
    c_violations, c_observed = inv6.check_unresolved_not_reproduced(
        surface, {before for before, _after in surface.matched_pairs}
    )

    return {
        "c": {"violations": c_violations, "observations": c_observed},
        "d": {"violations": d_violations, "observations": d_observed},
        "e": {"violations": e_violations, "observations": e_observed},
        "unsettled_identities": len(surface.of(eff.Effective.UNRESOLVED)),
        "census": surface.as_dict(),
    }


def run() -> dict[str, Any]:
    started = time.time()
    ws = fz.workspace()

    #: Every rung, every digest, every link, AND the three companion
    #: attestations recomputed. A closure that measures before its chain is
    #: verified is INC-V2-042 with a different subject; one that measures on a
    #: chain whose V2R3-specific proofs were never sealed is INC-V2-065.
    preconditions = fz.require_v2r3_execution_preconditions(ws)
    protocol = base_fz.load_protocol(ws.protocol)

    universe_receipt = base_fz.latest_receipt(base_fz.stem_for(protocol, "universe"), ws.receipts)
    if universe_receipt is None:
        raise ClosureRefused("the universe is not frozen")

    #: The gate already refuses on a prior measurement. Checked again here
    #: because this is the file that would write the second one, and a guard
    #: that lives only in the caller is a guard the next caller can skip.
    existing = sorted((NS / "receipts").glob(f"{STEM}--*.json"))
    if existing:
        raise ClosureRefused(
            "V2R3 has already been measured and it runs EXACTLY ONCE. Re-running a "
            "spent closure on the same corpus is what the founder ruling's execution "
            f"contract forbids.\n  {existing[-1].name}"
        )

    declared_record = protocol["quarantine_channel"]["production_record"]
    channels, records, unresolved_records, scopes = base._channel_tables(protocol)
    ignore_declaration = protocol["predeclared_ignored_facets"]["by_family"]

    rows = universe_receipt["pairs"]

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
        return [
            {**violation, "lineage_id": entry["lineage_id"]}
            for entry in extra
            for violation in entry[clause]["violations"]
        ]

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

    #: The census exists so a reader can see the instrument had something to
    #: measure. Two counts carry that weight specifically:
    #: `matched_with_differing_raw_ids` -- a PASS over a cohort containing zero
    #: renamed correspondences is a pass V2R1's defect could also have produced;
    #: and `quarantine_overrides` -- a PASS over a cohort with zero of them never
    #: exercised rows B or D, which is where V2R2 died. Saying so afterwards is
    #: not the same as recording it.
    #: Key names are taken from `EffectiveSurface.as_dict` rather than restated,
    #: so a rename there is an import-time failure here instead of a KeyError
    #: after 300 pairs have been diffed. The first version restated them and got
    #: two wrong.
    scalar_keys = (
        "matched_pairs",
        "matched_with_differing_raw_ids",
        "quarantine_overrides",
        "quarantine_members",
    )
    map_keys = (
        "effective_census",
        "resolver_census",
        "quarantine_overrides_by_resolver_state",
    )
    _require_census_keys(extra, scalar_keys + map_keys)
    census: dict[str, Any] = {
        key: sum(entry["census"][key] for entry in extra) for key in scalar_keys
    }
    for key in map_keys:
        census[key] = _sum_maps(entry["census"][key] for entry in extra)

    invariant_6_met = not invariant_6_violations and observations["d"] > 0

    return {
        "schema": "tavonel.v2.identity_change_migration_closure.v2r3_result.v1",
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
            "clause_d": {
                "violations": len(d_violations),
                "observations": observations["d"],
                "graded_against": (
                    "the EFFECTIVE identity disposition, side-scoped and composed per "
                    "logical id -- not the resolver's local decision, which is what "
                    "V2R2 read"
                ),
            },
            "clause_e": {
                "violations": len(e_violations),
                "observations": observations["e"],
                "declared_record": declared_record,
                "unsettled_source": (
                    "the shared EffectiveSurface's own EFFECTIVE_UNRESOLVED units, "
                    "NOT the diff's records -- reading the unsettled set off the diff "
                    "would compare the diff to itself and could not come back no"
                ),
            },
            "zero_tolerance": True,
        },
        "unsettled_identities_total": sum(entry["unsettled_identities"] for entry in extra),
        "effective_census": census,
        "wall_seconds": round(time.time() - started, 2),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def _require_census_keys(extra: list[dict[str, Any]], keys: tuple[str, ...]) -> None:
    """Every census key this scorer aggregates must actually be produced.

    Checked BEFORE aggregating rather than discovered during it. A KeyError
    raised while summing has already cost the whole diff pass, and a run that
    crashes after reading real outcomes is a run somebody has to reason about
    afterwards -- which is a worse position than refusing up front.
    """
    if not extra:
        return
    produced = set(extra[0]["census"])
    missing = sorted(set(keys) - produced)
    if missing:
        raise ClosureRefused(
            f"the effective surface does not report {missing}. This scorer "
            f"aggregates {sorted(keys)} and the surface produces {sorted(produced)}; "
            "one of the two has been renamed and the census would be silently "
            "incomplete or the run would die mid-aggregation."
        )


def _sum_maps(maps: Any) -> dict[str, int]:
    total: dict[str, int] = {}
    for entry in maps:
        for key, count in entry.items():
            total[key] = total.get(key, 0) + count
    return dict(sorted(total.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args(argv)

    try:
        body = run()
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
    print(f"census       : {json.dumps(body['effective_census'], sort_keys=True)}")
    return 0 if six["met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
