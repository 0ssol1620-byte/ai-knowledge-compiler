"""The executable state table, and the gate that proves it is satisfiable.

Founder ruling section 7. This is the check whose absence let V2R2 through. The
contradiction V2R2 carried -- `NEW ∩ QUARANTINED` simultaneously requiring and
forbidding `unit_added` -- was reachable, statable and provable before a single
pair was fetched. Nothing was looking, so a corpus was burned discovering it.

Two things are proved here, over EVERY reachable state and before any V2R3
outcome exists:

    1. TOTALITY      each reachable state yields exactly ONE effective
                     disposition -- never zero, never two.
    2. SATISFIABILITY  no reachable state both requires and forbids the same
                     record. A contract that cannot be satisfied is not a strict
                     contract; it is a broken one, and no implementation can
                     pass it.

THE ROWS ARE NOT A PARALLEL TABLE. They are produced by calling
`classify_after` / `classify_before` -- the same functions the scorer uses --
against a synthetic quarantine. A hand-written table of expected dispositions
would agree with itself and prove nothing about the code that runs.

OBLIGATIONS ARE DERIVED FROM THE EFFECTIVE DISPOSITION AND NOTHING ELSE. That
is the structural fix: V2R2 derived clause (d)'s obligation from Layer 1 and
clause (e)'s from Layer 2, so the two could disagree about the same unit. Here
one function owns both, so a disagreement is not expressible.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(ROOT / "packages" / "cir-python" / "src"), str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from akc_cir.semantic_diff import ChangeKind  # noqa: E402
from v2r3_effective_identity import (  # noqa: E402
    UNRESOLVED_RECORD,
    Effective,
    classify_after,
    classify_before,
)
from v2r3_quarantine_oracle import (  # noqa: E402
    DECLARED_CANDIDATE,
    OracleMember,
    QuarantineOracle,
)


class ContractBroken(RuntimeError):
    """A reachable state has no disposition, two, or contradictory obligations."""


#: A RECORD KIND IS SIDE-SCOPED, and the obligations have to be too.
#:
#: This was found on the spent V2R2 corpus, by the first version of this table
#: getting it wrong. `unit_added` describes the AFTER-side unit carrying that id;
#: `unit_removed` describes the BEFORE-side unit carrying it. Those can be two
#: different units, because a logical id is unique per side and not across
#: sides: an eCFR section can end at a path while a different one begins there,
#: the resolver declines to match them, and production correctly emits BOTH
#: records under the same id.
#:
#: The first table forbade `unit_removed` on EFFECTIVE_NEW and `unit_added` on
#: EFFECTIVE_REMOVED. On that data every such pair fired twice -- each unit
#: reported as violating an obligation that belonged to the other one. Same
#: family as the two predecessors: an identity model that cannot tell two things
#: apart. Third time, one layer lower.
#:
#: So a disposition may only forbid records that could be assertions ABOUT ITS
#: OWN SIDE:
#:
#:   after-side  unit_added, identity_unresolved
#:   before-side unit_removed, modified_claim, identity_unresolved
#:
#: `modified_claim` is keyed on the before-side counterpart, which is why it is a
#: before-side record here.
AFTER_SIDE_RECORDS: frozenset[ChangeKind] = frozenset({ChangeKind.UNIT_ADDED, UNRESOLVED_RECORD})
BEFORE_SIDE_RECORDS: frozenset[ChangeKind] = frozenset(
    {ChangeKind.UNIT_REMOVED, ChangeKind.MODIFIED_CLAIM, UNRESOLVED_RECORD}
)


#: What each effective disposition REQUIRES production to emit about the unit,
#: and what it FORBIDS, before side-scoping is applied. Every entry is justified
#: from the compatibility contract or from the plain meaning of the disposition;
#: nothing is here to make a previous result come out differently.
#:
#:   EFFECTIVE_UNRESOLVED  contract clause 2 forbids every concrete
#:                         identity-sensitive outcome on a quarantined member;
#:                         clause 3 requires the uncertainty to be STATED, since
#:                         a fail-closed endpoint cannot score an absence.
#:   EFFECTIVE_NEW         the unit began here, and `identity_unresolved` on a
#:                         unit no quarantine covers is over-quarantine, which
#:                         the contract names as its own defect.
#:   EFFECTIVE_MATCHED     silence is legitimate: production publishes no matched
#:                         surface, so an unchanged matched unit emits nothing.
#:                         `modified_claim` and every facet event stay ALLOWED --
#:                         they are events on an established correspondence and
#:                         are graded by their own invariants.
#:   EFFECTIVE_REMOVED     the unit ended here, so nothing may assert it
#:                         continued.
OBLIGATIONS: dict[Effective, dict[str, tuple[ChangeKind, ...]]] = {
    Effective.UNRESOLVED: {
        "required": (UNRESOLVED_RECORD,),
        "forbidden": (
            ChangeKind.UNIT_ADDED,
            ChangeKind.UNIT_REMOVED,
            ChangeKind.MODIFIED_CLAIM,
        ),
    },
    Effective.NEW: {
        "required": (ChangeKind.UNIT_ADDED,),
        "forbidden": (UNRESOLVED_RECORD,),
    },
    Effective.MATCHED: {
        "required": (),
        "forbidden": (
            ChangeKind.UNIT_ADDED,
            ChangeKind.UNIT_REMOVED,
            UNRESOLVED_RECORD,
        ),
    },
    Effective.REMOVED: {
        "required": (ChangeKind.UNIT_REMOVED,),
        "forbidden": (ChangeKind.MODIFIED_CLAIM, UNRESOLVED_RECORD),
    },
}


def obligations_for(effective: Effective, side: str = "after") -> dict[str, tuple[ChangeKind, ...]]:
    """The obligations for one disposition, scoped to the side it speaks about.

    A forbidden record that could not be an assertion about this side is
    dropped, not kept "to be safe": keeping it is what made two correct records
    read as two violations.
    """
    scope = AFTER_SIDE_RECORDS if side == "after" else BEFORE_SIDE_RECORDS
    rules = OBLIGATIONS[effective]
    return {
        "required": rules["required"],
        "forbidden": tuple(k for k in rules["forbidden"] if k in scope),
    }


def compose(
    contributions: list[tuple[frozenset[ChangeKind], frozenset[ChangeKind]]],
) -> tuple[frozenset[ChangeKind], frozenset[ChangeKind]]:
    """Merge every obligation held against ONE logical id into one pair.

    A required record wins over a forbidden one, and forbidding needs unanimity:

        required  = union of every contributor's required
        forbidden = intersection of every contributor's forbidden, minus required

    Union for required, because each contributor speaks about a real unit and
    each of those units must be accounted. Intersection for forbidden, because
    one contributor's silence about a record is not a prohibition -- and the
    subtraction makes the result satisfiable BY CONSTRUCTION, which is the
    property V2R2 lacked.

    The case this exists for: an id carried by an unmatched unit on each side
    is EFFECTIVE_NEW and EFFECTIVE_REMOVED at once, so `unit_added` AND
    `unit_removed` are both required and neither may be forbidden.
    """
    if not contributions:
        return frozenset(), frozenset()
    required: set[ChangeKind] = set()
    forbidden: set[ChangeKind] | None = None
    for req, forb in contributions:
        required |= req
        forbidden = set(forb) if forbidden is None else (forbidden & set(forb))
    return frozenset(required), frozenset((forbidden or set()) - required)


@dataclass(frozen=True)
class Row:
    side: str
    resolver_state: str
    quarantined: bool
    effective: Effective
    rule: str
    required: tuple[str, ...]
    forbidden: tuple[str, ...]
    silence_allowed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "resolver_state": self.resolver_state,
            "quarantined": self.quarantined,
            "effective": self.effective.value,
            "rule": self.rule,
            "required": list(self.required),
            "forbidden": list(self.forbidden),
            "silence_allowed": self.silence_allowed,
        }


def _oracle(*ids: str) -> QuarantineOracle:
    return QuarantineOracle(
        members={
            i: OracleMember(logical_id=i, reason=DECLARED_CANDIDATE, implicated_by="synthetic")
            for i in ids
        }
    )


def reachable_rows() -> list[Row]:
    """Every reachable (side, resolver state, quarantine) combination.

    Eight rows. Six after-side -- three resolver states times quarantined or
    not -- and two before-side. All eight are genuinely reachable:

      * AMBIGUOUS + not quarantined happens whenever the unsettled incoming id
        is absent from the before side, so contract clause 1c does not add it;
      * NEW + quarantined is row B, reached transitively or by sharing an id
        with an unsettled neighbourhood. It is the row V2R2 lacked;
      * MATCHED + quarantined is row D, reached when the selected counterpart is
        already a member.

    Nothing is excluded as "cannot happen". V2R2's contradiction lived in a
    state somebody would have called unlikely.
    """
    rows: list[Row] = []
    unit_id, counterpart_id = "u:after", "u:before"

    for resolver_state in ("MATCHED", "NEW", "AMBIGUOUS"):
        for quarantined in (False, True):
            if resolver_state == "MATCHED":
                oracle = _oracle(counterpart_id) if quarantined else _oracle()
                classified = classify_after(
                    unit_id, resolver_state, counterpart_id, counterpart_id, oracle
                )
            elif resolver_state == "NEW":
                oracle = _oracle(unit_id) if quarantined else _oracle()
                classified = classify_after(unit_id, resolver_state, unit_id, None, oracle)
            else:
                oracle = _oracle(unit_id) if quarantined else _oracle()
                classified = classify_after(unit_id, resolver_state, counterpart_id, None, oracle)
            rules = obligations_for(classified.effective, "after")
            rows.append(
                Row(
                    side="after",
                    resolver_state=resolver_state,
                    quarantined=quarantined,
                    effective=classified.effective,
                    rule=classified.rule,
                    required=tuple(k.value for k in rules["required"]),
                    forbidden=tuple(k.value for k in rules["forbidden"]),
                    silence_allowed=not rules["required"],
                )
            )

    for quarantined in (False, True):
        oracle = _oracle(counterpart_id) if quarantined else _oracle()
        classified = classify_before(counterpart_id, oracle)
        rules = obligations_for(classified.effective, "before")
        rows.append(
            Row(
                side="before_unconsumed",
                resolver_state="UNCONSUMED",
                quarantined=quarantined,
                effective=classified.effective,
                rule=classified.rule,
                required=tuple(k.value for k in rules["required"]),
                forbidden=tuple(k.value for k in rules["forbidden"]),
                silence_allowed=not rules["required"],
            )
        )
    return rows


def check_contract() -> dict[str, Any]:
    """Totality and satisfiability over every reachable row.

    Returns the report. Raises `ContractBroken` on any failure, because a
    freeze that proceeds past a broken contract is the V2R2 sequence again.
    """
    rows = reachable_rows()
    problems: list[str] = []

    #: TOTALITY. `classify_after` raises on an unhandled resolver state and
    #: returns exactly one `EffectiveUnit` otherwise, so zero and two are both
    #: unreachable by construction -- and the property is asserted anyway,
    #: because "unreachable by construction" is what V2R2 believed about its own
    #: contradiction.
    seen: dict[tuple[str, str, bool], list[str]] = {}
    for row in rows:
        key = (row.side, row.resolver_state, row.quarantined)
        seen.setdefault(key, []).append(row.effective.value)
    for key, dispositions in sorted(seen.items()):
        if len(dispositions) != 1:
            problems.append(f"{key} yields {len(dispositions)} dispositions: {dispositions}")

    #: SATISFIABILITY.
    for row in rows:
        clash = set(row.required) & set(row.forbidden)
        if clash:
            problems.append(
                f"CONTRACT_BROKEN: {row.side}/{row.resolver_state}/"
                f"quarantined={row.quarantined} both requires and forbids {sorted(clash)}"
            )

    #: The specific row V2R2 got wrong, asserted by name so a future edit that
    #: reintroduces the contradiction fails here rather than in a spent corpus.
    new_quarantined = next(r for r in rows if r.resolver_state == "NEW" and r.quarantined)
    if new_quarantined.effective is not Effective.UNRESOLVED:
        problems.append(
            "NEW + QUARANTINED must be EFFECTIVE_UNRESOLVED; the compatibility "
            "contract forbids a concrete identity outcome on a quarantined member"
        )
    if ChangeKind.UNIT_ADDED.value in new_quarantined.required:
        problems.append(
            "CONTRACT_BROKEN: NEW + QUARANTINED requires unit_added, which contract "
            "clause 2 forbids. This is exactly the state that invalidated V2R2."
        )
    if UNRESOLVED_RECORD.value not in new_quarantined.required:
        problems.append(
            "NEW + QUARANTINED must REQUIRE a visible identity_unresolved record. "
            "Withholding the definite outcome without stating the uncertainty is "
            "silent suppression, which a fail-closed endpoint cannot score."
        )

    #: And the converse, so the fix cannot be a blanket surrender: a genuine,
    #: unquarantined addition must still be required to be definite.
    new_clean = next(r for r in rows if r.resolver_state == "NEW" and not r.quarantined)
    if ChangeKind.UNIT_ADDED.value not in new_clean.required:
        problems.append(
            "NEW without quarantine must still REQUIRE unit_added; over-quarantine "
            "is its own defect and would destroy the diff's usefulness"
        )
    removed_clean = next(r for r in rows if r.side == "before_unconsumed" and not r.quarantined)
    if ChangeKind.UNIT_REMOVED.value not in removed_clean.required:
        problems.append(
            "an unconsumed, unquarantined before-side unit must still REQUIRE unit_removed"
        )

    #: Contract clause 2 as a standing property over the whole table, rather
    #: than as three separate assertions someone could satisfy one at a time.
    for row in rows:
        if row.effective is not Effective.UNRESOLVED:
            continue
        for kind in (ChangeKind.UNIT_ADDED, ChangeKind.UNIT_REMOVED, ChangeKind.MODIFIED_CLAIM):
            if kind.value in row.required:
                problems.append(
                    f"CONTRACT_BROKEN: a quarantined member is required to emit "
                    f"{kind.value}, which contract clause 2 forbids"
                )
            side_records = AFTER_SIDE_RECORDS if row.side == "after" else BEFORE_SIDE_RECORDS
            if kind in side_records and kind.value not in row.forbidden:
                problems.append(
                    f"contract clause 2 not enforced: {kind.value} is not forbidden "
                    f"for {row.side}/{row.resolver_state}"
                )

    if problems:
        raise ContractBroken("\n  ".join(problems))

    return {
        "state": "SATISFIABLE",
        "reachable_rows": len(rows),
        "rows": [row.as_dict() for row in rows],
        "totality": "every reachable state yields exactly one effective disposition",
        "satisfiability": "no reachable state both requires and forbids a record",
        "contract": "docs/COMPAT_IDENTITY_UNCERTAINTY_QUARANTINE.md",
        "v2r2_contradiction_absent": True,
    }


def main() -> int:
    try:
        report = check_contract()
    except ContractBroken as error:
        print(json.dumps({"state": "CONTRACT_BROKEN", "why": str(error)}, indent=1))
        return 4
    for row in report["rows"]:
        print(
            f"{row['side']:18s} {row['resolver_state']:10s} "
            f"q={row['quarantined']!s:5s} -> {row['effective']:22s} [{row['rule']}] "
            f"require={row['required']} forbid={row['forbidden']}"
        )
    print(f"\n{report['state']}: {report['reachable_rows']} reachable rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
