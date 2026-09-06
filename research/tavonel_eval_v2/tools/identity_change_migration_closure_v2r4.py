"""The scorer of record for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4.

ALL EIGHT INVARIANTS, ONE VERDICT, WRITTEN BY THE INSTRUMENT. V2R3R1's scorer
rendered INVARIANT_6 and no `overall`, so its frozen pass rule -- eight MET, none
UNPROVEN -- could not be evaluated from its own output, and 300 pairs were spent
establishing one answer. INC-V2-067. Here `v2r4_grading.grade` produces the
frozen-rule verdict itself and `invariant_domain.require_receipt_domain` refuses
a result that does not carry all eight blocks with a legal verdict apiece. There
is no interpretation step after execution.

NOTHING ABOUT GRADING IS IMPLEMENTED HERE. The five-clause INVARIANT_6, the other
seven invariants and the pass rule all live in `v2r4_grading`, which rung 4 pinned
by digest. This module is the TRAVERSAL: it opens the frozen universe, reads each
pair, hands the measurements to the pinned grader and writes the receipt. A second
implementation of a check that already passed a frozen closure is a second thing
that can drift, so `measure_pair` and `measure_extra_clauses` are imported rather
than retyped.

WHERE INVARIANT_8's DISJOINTNESS PROOFS ACTUALLY LIVE, and why this module has to
say so out loud. `v2r4_grading.disjointness_from` maps a universe receipt's
`disjointness` block onto V1's input shape, and it assumes that block is keyed by
`REQUIRED_DISJOINTNESS`. For this chain that assumption is false. The universe
rung is frozen by V1's `build_universe`, which computes THREE proofs under V1's
own names; the enumerator proves TWELVE, under its own, and writes them to the
candidates artifact the universe receipt pins by sha256.

Calling `disjointness_from` on the frozen block would therefore have refused --
correctly, and only after 223 pairs had been diffed. So the mapping is made
EXPLICIT here, one declared `REQUIRED_DISJOINTNESS` name to one or more named
enumerator proofs, and `require_disjointness_domain` is still what decides: set
equality on full identifiers, never a count. What moved is where the seven proofs
are read from, not whether all seven must be present.

THE SOURCE IS PINNED, NOT A SIDE CHANNEL. The candidates artifact is re-hashed
and compared to `manifest.sha256` in the frozen universe receipt before a single
proof is read. An artifact whose digest does not match the rung that pinned it is
not evidence, and reading a proof out of an unpinned file to satisfy a frozen rung
is the false-provenance seam this study keeps recording.

AND THE THREE THE UNIVERSE COMPUTED ITSELF ARE STILL REQUIRED TO AGREE. Two
independent computations of the same disjointness, both of which must hold. A
mapping that quietly replaced the universe's own proofs with the enumerator's
would have removed a check rather than repaired one.

THE REAL-COHORT PATH IS NOT REACHABLE FROM A TEST, and that is structural. The
V2R1 chain died because a stale test called `run()` directly, traversed all 300
pairs and crashed in census aggregation; no outcome escaped, but only because of
where the exception happened to land. So `run()` takes an authorisation that ONLY
the declared one-shot entry point can mint, the mint refuses while a test runner
is loaded, and the authorisation check is the FIRST statement in `run()` -- before
the workspace, the protocol or the universe is touched.

THERE IS NO BYPASS AND THERE IS NO `--limit`. No token file, no environment
variable, no force flag; a permission reconstructible from outside the process
would be the force flag this protocol says does not exist. A limited run reads
real outcomes from part of the cohort and is therefore a PREVIEW whatever it does
with them afterwards, and the execution contract is "exactly once, no preview". A
flag whose only use is to look first does not exist here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
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

import freeze_migration_closure_v2r4 as fz  # noqa: E402

#: The V2R4 freezer is an ADAPTER, so the ladder helpers live on `fz.base` while
#: the overridden entry points and this chain's gate live on `fz`. Reaching for a
#: helper on the adapter raises immediately -- which is how the equivalent line
#: came to be written in V2R2: the derived scorer called `fz.Workspace()` and blew
#: up before it could seal anything against the wrong protocol.
base_fz = fz.base
import identity_change_migration_closure as v1  # noqa: E402
import identity_change_migration_closure_v2r3r1 as parent  # noqa: E402
import invariant_domain as dom  # noqa: E402
import v2r4_grading as grading  # noqa: E402
from akc_cir.semantic_diff import DiffLevel  # noqa: E402
from evidence import write_immutable  # noqa: E402

STEM = grading.STEM
SCHEMA = grading.SCHEMA


class ClosureRefused(RuntimeError):
    """A precondition of measuring is not met."""


# ---------------------------------------------------------------------------
# INVARIANT_8's disjointness, read from where it was actually proved
#
# Each declared population is bound to the enumerator proof ids that establish
# it. Written as a MAP rather than resolved by string similarity: a name-matching
# rule would silently bind `v2_aborted_16` to `from_v2r1_universe` and nothing
# downstream could tell.

#: Declared population -> the enumerator proof ids that must ALL hold for it.
#:
#: `from_the_538_pair_retrospective_cohort` takes three. The enumerator's
#: `retrospective_538` proof carries only 14 comparable ids and says so in its own
#: `coverage` field: full coverage for that material comes from `sfi1_spent` and
#: `sfi2_spent`, enumerated separately. Binding the declared population to the
#: weak proof alone would have satisfied the domain check with a fraction of the
#: cohort actually compared.
PROOF_SOURCES: dict[str, tuple[str, ...]] = {
    "from_the_538_pair_retrospective_cohort": (
        "retrospective_538",
        "sfi1_spent",
        "sfi2_spent",
    ),
    "from_the_14_sfi2_forensic_cases": ("sfi2_forensic_14",),
    "from_v1_universe": ("v1_closure_514",),
    "from_v2r1_universe": ("v2r1_spent",),
    "from_v2r2_universe": ("v2r2_spent",),
    "from_v2r3r1_universe": ("v2r3_and_v2r3r1_spent_300",),
    "from_vbc1_burned_material": ("vbc1_probe",),
}

#: Proofs the enumerator computes that no declared population consumes. Named so
#: they are RECORDED rather than silently dropped: an unmapped proof is either a
#: population nobody declared or a proof nobody needed, and the two are worth
#: telling apart when the next chain reads this receipt.
UNMAPPED_PROOFS: tuple[str, ...] = (
    "earlier_identity_measurements",
    "sfi3_all",
    "v2_aborted_16",
)

#: The universe rung computes three of these itself, under V1's names. Both
#: computations must hold. Dropping the universe's own proofs in favour of the
#: enumerator's would have removed a check while appearing to repair one.
UNIVERSE_CORROBORATION: dict[str, str] = {
    "from_the_538_pair_retrospective_cohort": "from_the_538_pair_retrospective_cohort",
    "from_the_14_sfi2_forensic_cases": "from_the_14_confirmed_sfi2_lineages",
    "from_v1_universe": "from_the_v1_frozen_universe",
}


def _sha_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def pinned_candidates(universe_receipt: dict[str, Any]) -> dict[str, Any]:
    """The enumerator's output, verified against the digest rung 3 pinned.

    An artifact whose digest does not match the rung that pinned it is not
    evidence. This runs BEFORE any proof is read, so a drifted candidates file
    refuses rather than contributing a disjointness claim nobody sealed.
    """
    manifest = universe_receipt.get("manifest") or {}
    declared = manifest.get("sha256")
    relative = manifest.get("path")
    if not declared or not relative:
        raise ClosureRefused(
            "the frozen universe receipt does not pin the enumerator's candidates "
            "artifact by path and digest, so INVARIANT_8's proofs cannot be read "
            "from a source this chain sealed."
        )
    path = ROOT / relative
    if not path.is_file():
        raise ClosureRefused(f"the pinned candidates artifact is missing: {relative}")
    current = _sha_file(path)
    if current != declared:
        raise ClosureRefused(
            "the enumerator's candidates artifact has changed since rung 3 pinned "
            f"it.\n  frozen:  {declared}\n  current: {current}\n"
            "A disjointness proof read out of a drifted artifact is not the proof "
            "the universe was frozen against."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def disjointness_input(universe_receipt: dict[str, Any]) -> dict[str, Any]:
    """V1's `disjointness` shape over V2R4's seven declared populations.

    `require_disjointness_domain` still decides. What this supplies is the source:
    the enumerator's twelve proofs from the pinned candidates artifact, bound to
    the declared names by `PROOF_SOURCES`, corroborated where the universe rung
    proved the same thing independently.
    """
    candidates = pinned_candidates(universe_receipt)
    proofs = candidates.get("disjointness") or {}
    if not proofs:
        raise ClosureRefused(
            "the pinned candidates artifact carries no disjointness proofs. An "
            "empty proof set is not a clean one."
        )

    universe_proofs = universe_receipt.get("disjointness") or {}
    built: dict[str, Any] = {}
    detail: dict[str, Any] = {}
    violations: list[dict[str, Any]] = []

    for population, sources in sorted(PROOF_SOURCES.items()):
        missing = [name for name in sources if name not in proofs]
        if missing:
            raise ClosureRefused(
                f"{population} is bound to enumerator proofs {list(sources)} and "
                f"{missing} are absent from the pinned artifact. A population "
                "nobody proved is not a population that was absent."
            )
        rows = []
        holds = True
        for name in sources:
            block = proofs[name] or {}
            overlap = list(block.get("overlap") or [])
            ok = bool(block.get("holds")) and not overlap
            holds = holds and ok
            rows.append(
                {
                    "proof": name,
                    "holds": bool(block.get("holds")),
                    "overlap": overlap[:6],
                    "comparable_ids": block.get("comparable_ids"),
                    "lineage_count": block.get("lineage_count"),
                }
            )
            if not ok:
                violations.append(
                    {
                        "why": f"{population} does not hold: enumerator proof {name}",
                        "overlap": overlap,
                    }
                )

        #: The universe rung's independent computation, where it made one.
        corroborating = UNIVERSE_CORROBORATION.get(population)
        corroboration: dict[str, Any] | None = None
        if corroborating is not None:
            block = universe_proofs.get(corroborating)
            if block is None:
                raise ClosureRefused(
                    f"the frozen universe declares no {corroborating!r} proof, but "
                    f"{population} is recorded as independently corroborated by it. "
                    "A corroboration that is not there is not a corroboration."
                )
            overlap = list(block.get("overlap") or [])
            ok = bool(block.get("holds")) and not overlap
            corroboration = {
                "universe_key": corroborating,
                "holds": bool(block.get("holds")),
                "overlap": overlap[:6],
            }
            holds = holds and ok
            if not ok:
                violations.append(
                    {
                        "why": (
                            f"{population} does not hold: the universe rung's own "
                            f"{corroborating} proof"
                        ),
                        "overlap": overlap,
                    }
                )

        built[population] = holds
        detail[population] = {
            "enumerator_proofs": rows,
            "universe_corroboration": corroboration,
            "holds": holds,
        }

    #: Set equality on full identifiers, against the DECLARED set. The check that
    #: refused the naive path is the same check that passes this one.
    domain = grading.require_disjointness_domain(built)

    unmapped = sorted(set(proofs) - {name for names in PROOF_SOURCES.values() for name in names})
    if set(unmapped) != set(UNMAPPED_PROOFS):
        raise ClosureRefused(
            "the enumerator's proof set has moved.\n"
            f"  unconsumed now:      {unmapped}\n"
            f"  unconsumed declared: {sorted(UNMAPPED_PROOFS)}\n"
            "A new proof nobody bound to a population is a population nobody "
            "declared, and a vanished one is a proof somebody stopped computing."
        )

    return {
        **built,
        "violations": violations,
        "domain": domain,
        "read_from": {
            "candidates_artifact": (universe_receipt["manifest"])["path"],
            "candidates_sha256": (universe_receipt["manifest"])["sha256"],
            "pinned_by": "rung 3, the universe freeze",
        },
        "proof_sources": {name: list(rows) for name, rows in sorted(PROOF_SOURCES.items())},
        "per_population": detail,
        "unconsumed_enumerator_proofs": unmapped,
        "why_not_the_universe_block_alone": (
            "the universe rung is frozen by V1's `build_universe`, which computes "
            "three proofs under V1's own names. This chain declares seven. Calling "
            "`disjointness_from` on that block refuses on a domain mismatch -- "
            "correctly, and only after the whole cohort has been diffed."
        ),
        "compared": "set equality on full identifiers, never a count",
    }


# ---------------------------------------------------------------------------
# the execution boundary


@dataclass(frozen=True)
class ExecutionAuthorisation:
    """Permission to read the real cohort, valid only inside the process that
    minted it.

    Deliberately NOT serialisable in any useful way: no `from_token`, no file, no
    environment variable. A permission reconstructible from outside the process is
    the force flag this protocol says does not exist.
    """

    gate: dict[str, Any]
    minted_by: str


_ONE_SHOT_ENTRY_POINT_ACTIVE = False
_MINTED: ExecutionAuthorisation | None = None

#: Checked at mint time. A test that deliberately removed one of these from
#: `sys.modules` would be circumventing rather than tripping over the boundary,
#: and the boundary is here to stop the accident that actually happened.
_TEST_RUNNERS = ("pytest", "_pytest", "unittest", "nose")


@contextmanager
def _one_shot_entry_point() -> Iterator[None]:
    global _ONE_SHOT_ENTRY_POINT_ACTIVE
    previous = _ONE_SHOT_ENTRY_POINT_ACTIVE
    _ONE_SHOT_ENTRY_POINT_ACTIVE = True
    try:
        yield
    finally:
        _ONE_SHOT_ENTRY_POINT_ACTIVE = previous


def authorise_one_shot(ws: Any) -> ExecutionAuthorisation:
    """Mint permission for exactly one real-cohort execution.

    Refuses unless the declared entry point is running AND no test runner is
    loaded AND this chain's gate reports READY. The gate call binds the
    authorisation to a chain: one minted against a chain that is not READY does
    not exist.
    """
    global _MINTED
    if not _ONE_SHOT_ENTRY_POINT_ACTIVE:
        raise ClosureRefused(
            "the real-cohort closure may only be authorised from the declared "
            "one-shot measurement entry point. Nothing else may mint permission, "
            "and there is no token, environment variable or force flag that "
            "substitutes for it."
        )
    loaded = [name for name in _TEST_RUNNERS if name in sys.modules]
    if loaded:
        raise ClosureRefused(
            f"a test runner is loaded in this process ({loaded}). The real cohort is "
            "never scored from a test. Unit tests may call pure helpers, synthetic "
            "fixtures and spent regression material; the measurement path is not "
            "among them."
        )
    gate = fz.require_v2r4_execution_preconditions(ws)
    _MINTED = ExecutionAuthorisation(gate=gate, minted_by="one_shot_entry_point")
    return _MINTED


def _require_authorisation(authorisation: ExecutionAuthorisation | None) -> None:
    """The first thing `run()` does. Nothing is read before this returns.

    Ordered deliberately: the V2R1 chain's crash traversed all 300 pairs before it
    failed, and the only reason no outcome escaped is where the exception happened
    to land. A boundary that refused AFTER loading the universe would preserve
    that same dependence on luck.
    """
    if authorisation is None:
        raise ClosureRefused(
            "run() requires an ExecutionAuthorisation and was called without one. "
            "The real-cohort closure is reachable only through the declared "
            "one-shot entry point. If this came from a test: call the pure helpers "
            "or build a synthetic surface -- the measurement path is not test "
            "material, and this refusal happened before the universe was opened."
        )
    if authorisation is not _MINTED:
        raise ClosureRefused(
            "the authorisation was not minted by this process's one-shot entry "
            "point. It is compared by identity precisely so that a well-shaped "
            "object built by hand is not accepted."
        )
    if not authorisation.gate.get("gate", "").endswith("v2r4_execution_preconditions"):
        raise ClosureRefused(
            "the authorisation does not carry this chain's gate result. A "
            "permission granted against another chain is not a permission."
        )


def _chain_run_ids(preconditions: dict[str, Any]) -> dict[str, Any]:
    """The run ids of the rungs that authorised this execution.

    Recorded so the run is attributable to the chain that authorised it and to no
    other -- including not to a predecessor chain, whose receipts this one may
    reference as provenance but never as an active predecessor.
    """
    chain = preconditions.get("chain")
    companions = preconditions.get("companion_attestations")
    if not chain or not companions:
        raise ClosureRefused(
            "the gate result carries no chain links or no companion attestations, so "
            "this measurement could not be attributed to the chain that authorised "
            "it. A receipt that cannot name its chain is not a receipt."
        )
    return {
        "rungs": chain,
        "companion_attestations": {name: entry["receipt"] for name, entry in companions.items()},
        "universe_sha256": preconditions["universe_sha256"],
        "acceptance_semantics_sha256": preconditions["acceptance_semantics_sha256"],
        "exclusion_policy_sha256": preconditions["exclusion_policy_sha256"],
    }


def run(authorisation: ExecutionAuthorisation | None = None) -> dict[str, Any]:
    #: FIRST. Before the workspace, the protocol, the universe or one pair.
    _require_authorisation(authorisation)

    started = time.time()
    ws = fz.workspace()

    #: Every rung, digest, link AND companion attestation recomputed -- again,
    #: now, rather than trusting the copy the authorisation carries. A closure
    #: that measures before its chain is verified is INC-V2-042 with a different
    #: subject; one that measures on a chain whose chain-specific proofs were
    #: never sealed is INC-V2-065.
    preconditions = fz.require_v2r4_execution_preconditions(ws)
    protocol = base_fz.load_protocol(ws.protocol)

    universe_receipt = base_fz.latest_receipt(base_fz.stem_for(protocol, "universe"), ws.receipts)
    if universe_receipt is None:
        raise ClosureRefused("the universe is not frozen")

    #: The gate already refuses on a prior measurement. Checked again here because
    #: this is the file that would write the second one, and a guard that lives
    #: only in the caller is a guard the next caller can skip.
    existing = sorted((NS / "receipts").glob(f"{STEM}--*.json"))
    if existing:
        raise ClosureRefused(
            "V2R4 has already been measured and it runs EXACTLY ONCE. Re-running a "
            "spent closure on the same corpus is what the founder ruling's execution "
            f"contract forbids.\n  {existing[-1].name}"
        )

    #: BEFORE the traversal, not after it. Assembling INVARIANT_8's proofs costs
    #: nothing and refuses on a domain mismatch; discovering that mismatch after
    #: 223 pairs have been diffed is the failure shape this chain exists to end.
    disjointness = disjointness_input(universe_receipt)

    declared_record = protocol["quarantine_channel"]["production_record"]
    channels, records, unresolved_records, scopes = v1._channel_tables(protocol)
    ignore_declaration = protocol["predeclared_ignored_facets"]["by_family"]
    forbidden_imports = tuple(protocol["expectation_oracle"]["forbidden_imports"])
    forbidden_attrs = tuple(protocol["expectation_oracle"]["forbidden_attribute_reads"])

    rows = universe_receipt["pairs"]
    if not rows:
        raise ClosureRefused(
            "the frozen universe declares no pairs. A closure over zero pairs is "
            "vacuous and this protocol fails it rather than passing it."
        )

    pair_results: list[dict[str, Any]] = []
    extra: list[dict[str, Any]] = []
    texts: list[str] = []
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
        #: ONE call, returning both halves. The pinned grader's `measure_pair`
        #: already composes V1's measurement with V2R3's (c),(d),(e) clauses and
        #: hands back the two populations separately, so `grade` can check they
        #: line up row for row instead of assuming it. Calling V1's measurement
        #: here and `measure_extra_clauses` beside it would diff every pair
        #: TWICE and re-derive, in this unpinned module, a composition rung 4
        #: already sealed. INC-V2-082.
        result, clauses = grading.measure_pair(
            before_document,
            after_document,
            channels=channels,
            records=records,
            unresolved_records=unresolved_records,
            scopes=scopes,
            ignored=frozenset(declared_ignores),
            declared_record=declared_record,
            level=DiffLevel.GRAPH,
        )
        result["lineage_id"] = row["lineage_id"]
        result["family"] = row["family"]
        pair_results.append(result)

        clauses["lineage_id"] = row["lineage_id"]
        clauses["family"] = row["family"]
        extra.append(clauses)

        texts.extend(v1._sample_texts(before_document))

    fold = v1.measure_identity_fold(texts, classes=tuple(v1.FOLD_CLASSES))
    independence = v1.audit_oracle_independence(
        forbidden_imports=forbidden_imports, forbidden_attributes=forbidden_attrs
    )
    mapping = v1.audit_obligation_mapping()
    fixtures = v1.run_fixture_battery(protocol["fixture_battery"]["classes"])

    graded = grading.grade(
        pairs=pair_results,
        extra=extra,
        fold=fold,
        independence=independence,
        mapping=mapping,
        fixtures=fixtures,
        disjointness=disjointness,
    )

    by_family: dict[str, int] = {}
    for row in rows:
        by_family[row["family"]] = by_family.get(row["family"], 0) + 1

    #: The census exists so a reader can see the instrument had something to
    #: measure. Two counts carry that weight specifically:
    #: `matched_with_differing_raw_ids` -- a PASS over a cohort containing zero
    #: renamed correspondences is a pass V2R1's defect could also have produced;
    #: and `quarantine_overrides` -- a PASS over a cohort with zero of them never
    #: exercised the rows V2R2 died on. Saying so afterwards is not the same as
    #: recording it.
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
    parent._require_census_keys(extra, scalar_keys + map_keys)
    census: dict[str, Any] = {
        key: sum(entry["census"][key] for entry in extra) for key in scalar_keys
    }
    for key in map_keys:
        census[key] = parent._sum_maps(entry["census"][key] for entry in extra)

    body = {
        "schema": SCHEMA,
        "protocol_id": protocol["protocol_id"],
        "pair_count": len(rows),
        "by_family": dict(sorted(by_family.items())),
        "preconditions": preconditions,
        "authorisation": {
            "entry_point": authorisation.minted_by,
            "gate": preconditions["gate"],
            "chain_run_ids": _chain_run_ids(preconditions),
        },
        "universe_sha256": universe_receipt.get("universe_sha256"),
        "overall": graded["overall"],
        "invariants": graded["invariants"],
        "pairs_resolved": graded.get("pairs_resolved"),
        "invariant_6_clause_sources": graded.get("invariant_6_clause_sources"),
        "disjointness": disjointness,
        "unsettled_identities_total": sum(entry["unsettled_identities"] for entry in extra),
        "effective_census": census,
        "wall_seconds": round(time.time() - started, 2),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    #: DECLARED == GRADED == RECEIPT, enforced on the receipt itself. Rung 4a
    #: attested the first two before execution; this is the third, and it is what
    #: INC-V2-067's absence cost -- a result that carried one invariant block
    #: under a pass rule naming eight, with nothing between them to object.
    dom.require_receipt_domain(body)
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-receipt", action="store_true")
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "perform the one authorised real-cohort execution. Without it this "
            "command does nothing: there is no preview, no limit and no sample, so "
            "a run with no flag would be the whole measurement by accident."
        ),
    )
    args = parser.parse_args(argv)

    if not args.execute:
        print(
            json.dumps(
                {
                    "state": "NOT_EXECUTED",
                    "why": (
                        "the real-cohort closure runs exactly once and is not the "
                        "default action of this command. Pass --execute to perform "
                        "it. There is no preview, no --limit and no sample."
                    ),
                },
                indent=1,
            )
        )
        return 0

    try:
        with _one_shot_entry_point():
            body = run(authorise_one_shot(fz.workspace()))
    except (ClosureRefused, grading.GradingRefused, fz.FreezeRefused) as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        return 4

    if args.write_receipt:
        body.update(write_immutable(STEM, body, tool=Path(__file__).resolve()))

    print(f"pairs        : {body['pair_count']}  {json.dumps(body['by_family'], sort_keys=True)}")
    print(f"OVERALL      : {body['overall']}")
    for name in sorted(body["invariants"]):
        block = body["invariants"][name]
        print(f"  {block['verdict']:<10} {name}  violations={len(block.get('violations') or [])}")
    print(f"census       : {json.dumps(body['effective_census'], sort_keys=True)}")
    if body.get("receipt"):
        print(f"receipt      : {body['receipt']}")
    return 0 if body["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
