"""The V2R4 grading core: all eight invariants, V2R3's corrected INVARIANT_6.

WHY THIS IS A COMPOSITION AND NOT A REWRITE. The founder's ruling of 2026-08-26,
paragraph 6: do not reinvent the full-8 scorer. V1's `grade()` already aggregates
every invariant and already produces PASS / FAIL / UNPROVEN / VACUOUS_FAIL from
the frozen pass rule. What V1 does NOT have is V2R3's corrected INVARIANT_6, and
what V2R3R1 does not have is the other seven. Neither is missing anything the
other has, so V2R4 is the join -- not a third implementation of either half.

    INVARIANT_1, 2, 3, 4, 5, 7, 8   V1's aggregation, over V2R3's frozen
                                    scientific definitions (unchanged since V1
                                    for 1-5 and 7; V2R3 widened 8's
                                    disjointness set and V2R4 widens it again,
                                    because more material has been spent).

    INVARIANT_6                     V1's clauses (a) and (b), PLUS V2R3's (c),
                                    (d) and (e) over one `EffectiveSurface`.

A SECOND IMPLEMENTATION OF A PASSING CHECK IS A SECOND THING THAT CAN DRIFT.
That sentence is V2R3's, and it is why `measure_pair` and `measure_extra_clauses`
are imported rather than retyped.

WHAT THIS MODULE CHANGES ABOUT HOW A VERDICT IS REACHED. Nothing, except that it
is reached. V2R3R1's instrument rendered one invariant and no `overall`, so its
frozen pass rule -- eight MET, none UNPROVEN -- could not be evaluated from its
own output. INC-V2-067. Here the scorer produces the frozen-rule verdict itself,
and `invariant_domain.require_receipt_domain` refuses a result that does not
carry all eight blocks with a legal verdict apiece. There is no interpretation
step after execution.

THE INVARIANT_6 RECOMPUTATION IS EXPLICIT, NOT A PATCH. `v1.grade` computes
INVARIANT_6 from clauses (a) and (b) alone, because that is all V1 had. This
module re-derives that one verdict from the union of (a),(b) and (c),(d),(e) and
records BOTH denominators separately, so a reader can see which clauses carried
the power. Every other invariant's verdict is V1's, untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    _path = str(NS / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
if str(NS) not in sys.path:
    sys.path.insert(0, str(NS))

import identity_change_migration_closure as v1  # noqa: E402
import invariant_domain as dom  # noqa: E402

SCHEMA = "tavonel.v2.identity_change_migration_closure.v2r4_result.v1"
PROTOCOL_ID = "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4"
STEM = "identity-change-migration-closure-v2r4"

#: The result schema's required invariant keys. Named here so the third leg of
#: `require_domain_equality` is a real declaration rather than the same tuple the
#: scorer already uses -- a schema that just points at the implementation cannot
#: disagree with it, and a leg that cannot disagree is not a check.
RESULT_INVARIANT_KEYS: tuple[str, ...] = dom.CANONICAL_INVARIANTS

INVARIANT_6 = "INVARIANT_6_ambiguous_identity_stays_unresolved"
INVARIANT_8 = "INVARIANT_8_sfi2_cases_cannot_certify"

#: Every cohort whose material is ALREADY spent, burned or otherwise forbidden
#: at the moment V2R4 acquires. The founder's ruling paragraph 9 lists these; the
#: V2R3/V2R3R1 300 is the newest entry, and it is here because that run GRADED.
#: Adjudicating an instrument incomplete does not un-spend the pairs it read.
#:
#: This is a DECLARED SET, and `require_disjointness_domain` compares it to the
#: keys the frozen universe actually proved -- the same acceptance-domain
#: equality that INC-V2-067 was the absence of, applied to exclusions.
REQUIRED_DISJOINTNESS: tuple[str, ...] = (
    "from_the_538_pair_retrospective_cohort",
    "from_the_14_sfi2_forensic_cases",
    "from_v1_universe",
    "from_v2r1_universe",
    "from_v2r2_universe",
    "from_v2r3r1_universe",
    "from_vbc1_burned_material",
)

#: SFI3 IS DELIBERATELY NOT ABOVE, and its absence is the repair rather than a
#: weakening.
#:
#: An earlier draft of this tuple carried `from_sfi3_material`, defined as every
#: lineage id in SFI3's FROZEN ACQUISITION. That receipt does not exist and must
#: not: the serial order is V2R4 PASS -> SFI3 freeze/acquisition -> SFI3 PASS ->
#: four-link -> GPU. Requiring it here made a circular gate --
#:
#:      V2R4 waits for SFI3's acquisition
#:      SFI3 waits for V2R4's PASS
#:
#: -- in which neither study could ever start. INVARIANT_8 is a disjointness
#: invariant against material that is ALREADY spent; a held-out cohort that has
#: not been acquired is not spent material and cannot be one of its populations.
#:
#: Separation from SFI3 is real and is still enforced, one layer up: SFI3's
#: source CONTAINERS are reserved in advance by `SFI3_ROOT_RESERVATION_V1`, from
#: root identity metadata only, and V2R4's rung 0 binds that reservation and
#: chooses its own containers outside it. Nothing about a future measurement is
#: read to prove a present separation. See `tools/sfi3_root_reservation.py`.
SFI3_SEPARATION_IS_A_RESERVATION_NOT_AN_INVARIANT = (
    "SFI3 separation is enforced by SFI3_ROOT_RESERVATION_V1 at rung 0, on "
    "container identity, and never by INVARIANT_8 over a cohort that does not "
    "exist yet"
)


class GradingRefused(RuntimeError):
    """The grading inputs cannot produce a readable verdict."""


# ---------------------------------------------------------------------------
# INVARIANT_8's exclusion domain


def require_disjointness_domain(proved: dict[str, Any]) -> dict[str, Any]:
    """The universe proved disjointness against exactly the declared cohorts.

    A universe that proves five of eight and reports `holds: true` for each is
    not disjoint from the other three -- it is silent about them, and silence
    reads as clean. That is INC-V2-067's shape pointed at exclusions rather than
    invariants, so it is checked the same way: set equality on identifiers, not
    a count and not a conjunction of whatever happens to be present.
    """
    declared = set(REQUIRED_DISJOINTNESS)
    present = set(proved)
    missing = sorted(declared - present)
    extra = sorted(present - declared)
    if missing or extra:
        raise GradingRefused(
            "the frozen universe's disjointness proofs and V2R4's declared "
            "exclusion set are not the same domain:\n"
            f"  never proved: {missing}\n"
            f"  proved but not declared: {extra}\n"
            "A cohort nobody subtracted is not a cohort that was absent."
        )
    return {"required": sorted(declared), "proved": sorted(present), "equal": True}


#: Where the protocol writes the same list in prose. Read back and compared, so
#: the declaration a reader sees and the set the code enforces cannot drift.
PROTOCOL_POPULATIONS_PATH: tuple[str, ...] = (
    "invariants",
    INVARIANT_8,
    "the_declared_populations",
)


def declared_populations(protocol: Path | None = None) -> tuple[str, ...]:
    """The populations the PROTOCOL names, read from its INVARIANT_8 block."""
    import yaml

    path = protocol or (NS / "protocols" / f"{PROTOCOL_ID}.yaml")
    if not path.is_file():
        raise GradingRefused(f"{path} does not exist; nothing declares an exclusion set")
    body: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for key in PROTOCOL_POPULATIONS_PATH:
        if not isinstance(body, dict) or key not in body:
            raise GradingRefused(
                f"{path.name} has no {'/'.join(PROTOCOL_POPULATIONS_PATH)} block. A "
                "pass rule that says 'disjoint from every spent cohort' over a "
                "protocol that names none is a sentence, not a rule."
            )
        body = body[key]
    if not isinstance(body, dict) or not body:
        raise GradingRefused(f"{path.name}'s declared populations are not a non-empty mapping")
    return tuple(sorted(body))


def require_exclusion_domain(protocol: Path | None = None) -> dict[str, Any]:
    """The protocol's declared populations are the ones this module enforces.

    The third leg, and the one INC-V2-067's shape would otherwise leave open: a
    protocol can name a population the code never subtracts, and a reader
    checking the protocol would find the rule stated and never learn it was not
    executed. Compared as SET EQUALITY on full identifiers, never a count.
    """
    declared = set(declared_populations(protocol))
    enforced = set(REQUIRED_DISJOINTNESS)
    if declared != enforced:
        raise GradingRefused(
            "the protocol's declared exclusion set and this scorer's are not the "
            "same domain:\n"
            f"  declared but never enforced: {sorted(declared - enforced)}\n"
            f"  enforced but not declared:   {sorted(enforced - declared)}\n"
            "A population named in prose and absent from the code is a rule "
            "nobody runs."
        )
    return {
        "declared": sorted(declared),
        "enforced": sorted(enforced),
        "equal": True,
        "compared": "set equality on full identifiers, never a count",
    }


def disjointness_from(universe_disjointness: dict[str, Any]) -> dict[str, Any]:
    """V1's `disjointness` input shape, over V2R4's wider exclusion set."""
    domain = require_disjointness_domain(universe_disjointness)
    violations = []
    for key in sorted(REQUIRED_DISJOINTNESS):
        block = universe_disjointness[key] or {}
        overlap = block.get("overlap") or []
        if overlap or not block.get("holds"):
            violations.append({"why": f"{key} does not hold", "overlap": overlap})
    return {
        "domain": domain,
        "violations": violations,
        **{
            key: bool((universe_disjointness[key] or {}).get("holds"))
            for key in sorted(REQUIRED_DISJOINTNESS)
        },
    }


# ---------------------------------------------------------------------------
# the grading


def _clause_violations(extra: list[dict[str, Any]], clause: str) -> list[dict[str, Any]]:
    return [
        {**violation, "lineage_id": entry["lineage_id"], "clause": clause}
        for entry in extra
        for violation in entry[clause]["violations"]
    ]


def grade(
    *,
    pairs: list[dict[str, Any]],
    extra: list[dict[str, Any]],
    fold: dict[str, Any],
    independence: dict[str, Any],
    mapping: dict[str, Any],
    fixtures: dict[str, Any],
    disjointness: dict[str, Any],
) -> dict[str, Any]:
    """All eight invariants, with INVARIANT_6 re-derived over five clauses.

    `extra` carries V2R3's (c),(d),(e) per pair, one entry per entry in `pairs`
    and in the same order. Passing `pairs=[]` and `extra=[]` yields the full
    eight-block skeleton with every verdict UNPROVEN and an overall of
    VACUOUS_FAIL -- which is how `invariant_domain.graded_invariants` observes
    this function's grading domain without a universe.
    """
    if len(extra) != len(pairs):
        raise GradingRefused(
            f"{len(pairs)} pairs were measured and {len(extra)} carry the effective "
            "surface clauses. INVARIANT_6 would be graded over a different "
            "population than the other seven."
        )
    for index, (pair, entry) in enumerate(zip(pairs, extra, strict=True)):
        if pair.get("lineage_id") != entry.get("lineage_id"):
            raise GradingRefused(
                f"row {index}: pair {pair.get('lineage_id')!r} was measured against "
                f"effective-surface clauses for {entry.get('lineage_id')!r}"
            )

    graded = v1.grade(
        pairs=pairs,
        fold=fold,
        independence=independence,
        mapping=mapping,
        fixtures=fixtures,
        disjointness=disjointness,
    )

    #: INVARIANT_6, re-derived. V1's block already holds clauses (a) and (b);
    #: what it cannot know about is the effective surface, which did not exist
    #: when it was written.
    block = dict(graded["invariants"][INVARIANT_6])
    ab_violations = list(block.get("violations") or [])
    cde_violations = (
        _clause_violations(extra, "c")
        + _clause_violations(extra, "d")
        + _clause_violations(extra, "e")
    )
    clause_observations = {
        "a_b": int(block.get("cohort_observations", 0)) + int(block.get("fixture_observations", 0)),
        "c": sum(entry["c"]["observations"] for entry in extra),
        "d": sum(entry["d"]["observations"] for entry in extra),
        "e": sum(entry["e"]["observations"] for entry in extra),
    }
    all_violations = ab_violations + cde_violations
    block.update(
        {
            "verdict": v1._verdict(all_violations, sum(clause_observations.values())),
            "population": (
                "identity_unresolved records (a, b) and the effective identity "
                "surface (c, d, e); each clause's denominator reported apart"
            ),
            "clause_observations": clause_observations,
            "exercising_observations": sum(clause_observations.values()),
            "clauses_graded": ["a", "b", "c", "d", "e"],
            "violations": all_violations,
            "why_five_clauses": (
                "V1 implemented (a) and (b). V2R3 added (c), (d) and (e) over one "
                "EffectiveSurface after V2R2 died on two separately computed "
                "surfaces that required and forbade the same record. All five are "
                "graded here; none is reimplemented."
            ),
        }
    )
    invariants = dict(graded["invariants"])
    invariants[INVARIANT_6] = block

    #: Recomputed, because INVARIANT_6's verdict may have moved and the overall
    #: is a function of all eight. Taken from `invariant_domain` rather than
    #: restated so the pass rule has exactly one implementation.
    overall = dom.overall_from(invariants, pairs_resolved=graded["pairs_resolved"])

    return {
        **graded,
        "overall": overall,
        "invariants": invariants,
        "invariant_6_clause_sources": {
            "a_b": "identity_change_migration_closure.measure_pair",
            "c_d_e": "identity_change_migration_closure_v2r3r1.measure_extra_clauses",
        },
    }


def measure_pair(
    before_document: dict[str, Any],
    after_document: dict[str, Any],
    *,
    channels: Any,
    records: Any,
    unresolved_records: Any,
    scopes: Any,
    ignored: Any,
    declared_record: str,
    level: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One pair, measured both ways: V1's seven-plus-(a,b), and V2R3's (c,d,e).

    Returned as a pair rather than merged, so `grade` can check that the two
    populations line up row for row instead of assuming it.
    """
    import identity_change_migration_closure_v2r3r1 as v2r3r1

    result = v1.measure_pair(
        before_document,
        after_document,
        channels=channels,
        records=records,
        unresolved_records=unresolved_records,
        scopes=scopes,
        ignored=ignored,
    )
    clauses = v2r3r1.measure_extra_clauses(
        before_document,
        after_document,
        declared_record=declared_record,
        level=level,
    )
    return result, clauses


def null_grading_inputs() -> dict[str, Any]:
    """Empty populations, for observing the grading domain without a universe.

    Used by `invariant_domain.graded_invariants`. The verdicts that come back
    are meaningless and are discarded; only the emitted keys are read.
    """
    return {
        "pairs": [],
        "extra": [],
        "fold": {
            "violations": [],
            "observations": 0,
            "lossiness_witnesses": 0,
            "per_class": {},
        },
        "independence": {
            "violations": [],
            "observations": 0,
            "modules_inspected": [],
            "signature": "",
        },
        "mapping": {"violations": [], "observations": 0, "combinations_evaluated": 0},
        "fixtures": {
            "held": [],
            "failed": [],
            "drift": {"declared_without_a_builder": [], "built_without_a_declaration": []},
            "results": {},
        },
        "disjointness": {"violations": []},
    }


def graded_domain() -> tuple[str, ...]:
    """What this module ACTUALLY grades, obtained by running it."""
    return dom.graded_invariants(grade, **null_grading_inputs())


def require_domain() -> dict[str, Any]:
    """The three-way equality, for the protocol this scorer is bound to.

    Called before a cohort is acquired and again before the receipt is written.
    A study whose acceptance domain and grading domain differ may not be frozen,
    and one whose result omits an invariant may not be reported.
    """
    protocol = NS / "protocols" / f"{PROTOCOL_ID}.yaml"
    return dom.require_domain_equality(
        declared=dom.declared_invariants(protocol),
        graded=graded_domain(),
        schema=dom.schema_invariants(RESULT_INVARIANT_KEYS),
    )
