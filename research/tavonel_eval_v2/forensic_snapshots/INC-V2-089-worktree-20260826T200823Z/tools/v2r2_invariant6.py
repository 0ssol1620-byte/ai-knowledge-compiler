"""INVARIANT_6 for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2.

Every clause here reads the SAME frozen `ResolverSurface`. That is the whole
correction. In V2R1 each clause built its own partial view of identity, and (d)
built the wrong one -- it treated `before_ids & after_ids`, raw revision-local
snapshot ids, as the set of cross-revision identity matches. It is not, and the
run was adjudicated INVALID_INSTRUMENT_CONTRACT for it.

    (a) an unsettled identity may not also carry a continuity assertion
    (b) a candidate of an unsettled identity may not be reported removed
    (c) an AMBIGUOUS decision may not enter matched-facet reproduction
    (d) TOTAL UNIT ACCOUNTING over the resolver decision graph
    (e) every quarantined identity stays visible on the declared channel

(a) and (b) remain V1's, reused rather than reimplemented.

CLAUSE (d), REBUILT. The population is not two id sets; it is the resolver's
decision graph, and each disposition carries a different obligation:

    A  MATCHED (b, a)          the two ids MAY DIFFER. Silence is LEGITIMATE
                               (an unchanged unit emits nothing). Facet events
                               keyed on `b` are legitimate. What is forbidden is
                               contradiction: UNIT_ADDED for either id, or
                               UNIT_REMOVED for `b`.
    B  NEW (a)                 UNIT_ADDED naming `a` is REQUIRED. Silence is a
                               violation.
    C  AMBIGUOUS (a)           IDENTITY_UNRESOLVED naming `a` is REQUIRED, and
                               `a` may carry no definite outcome. Never also
                               NEW, REMOVED or matched.
    D  before-side unconsumed  UNIT_REMOVED naming `b`, or visibly unresolved.
                               Silence is a violation.

MATCHED COMES FROM THE RESOLVER, NEVER FROM DIFF SILENCE. V2R1 inferred it as
"present on both sides and carrying no record", which is how a path rename
became a fabricated pair of a silent appearance and a silent disappearance.
Silence is now *permitted* under disposition A and *forbidden* under B and D --
its meaning is decided by the resolver, never by its own absence.

A FACET EVENT IS NOT AN IDENTITY DISPOSITION. `EVIDENCE_MOVED`,
`TEMPORAL_CHANGED`, `METADATA_CHANGED` are emitted only after a correspondence
exists. None of them may satisfy an accounting obligation, and none appears in
`DEFINITE_KINDS`. Adding `EVIDENCE_MOVED` there was explicitly ruled out: it
would have made a change event stand in for identity accounting, which is the
original defect wearing a new hat.

CONSERVATION IS PROVED, NOT ASSUMED. `check_conservation` re-derives both
one-to-one identities from the surface. `verify_exhaustive` already refuses to
build a non-total surface; this scores it again inside the measurement, because
a proof that lives only in a constructor is a proof no receipt cites.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(ROOT / "packages" / "cir-python" / "src"), str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from akc_cir.semantic_diff import ChangeKind  # noqa: E402
from v2r2_resolver_surface import ResolverSurface  # noqa: E402

#: The record kind production emits for an unresolved identity. Read from the
#: enum, never written as a literal: a clause spelled against a string nothing
#: emits cannot be violated, and a criterion that cannot be violated has not
#: been met (INC-V2-044).
UNRESOLVED_KIND = ChangeKind.IDENTITY_UNRESOLVED

#: The identity-sensitive outcomes -- the ones that ASSERT something about
#: whether a unit began, ended or continued. Facet events are deliberately
#: absent; see the module docstring.
DEFINITE_KINDS: tuple[ChangeKind, ...] = (
    ChangeKind.UNIT_ADDED,
    ChangeKind.UNIT_REMOVED,
    ChangeKind.MODIFIED_CLAIM,
)


def named_ids(diff: Any) -> set[str]:
    """Every id an unresolved record makes visible, as subject or as candidate.

    Empty strings are dropped. NAMED means a non-empty logical id: a record
    saying a unit is implicated by something it declines to identify names
    nothing, and a clause that accepted one could be satisfied by silence
    wearing the shape of a statement.
    """
    named: set[str] = set()
    for change in diff.changes:
        if change.kind is not UNRESOLVED_KIND:
            continue
        if change.logical_id:
            named.add(change.logical_id)
        named.update(c for c in (change.candidates or ()) if c)
    return named


def _ids_of_kind(diff: Any, kind: ChangeKind) -> set[str]:
    return {c.logical_id for c in diff.changes if c.kind is kind and c.logical_id}


def definite_ids(diff: Any) -> set[str]:
    return {c.logical_id for c in diff.changes if c.kind in DEFINITE_KINDS and c.logical_id}


def check_conservation(surface: ResolverSurface) -> list[dict[str, Any]]:
    """One-to-one conservation, scored rather than assumed.

    before = MATCHED + unmatched_before, and after = MATCHED + NEW + AMBIGUOUS,
    with no unit appearing twice on either side.
    """
    violations: list[dict[str, Any]] = []
    matched = len(surface.matched)

    before_total = matched + len(surface.unmatched_before_ids)
    if before_total != len(surface.before_ids):
        violations.append(
            {
                "clause": "d",
                "why": (
                    f"before-side conservation failed: {matched} matched + "
                    f"{len(surface.unmatched_before_ids)} unmatched != "
                    f"{len(surface.before_ids)} present"
                ),
            }
        )

    after_total = matched + len(surface.new_after_ids) + len(surface.ambiguous_after_ids)
    if after_total != len(surface.after_ids):
        violations.append(
            {
                "clause": "d",
                "why": (
                    f"after-side conservation failed: {matched} matched + "
                    f"{len(surface.new_after_ids)} new + "
                    f"{len(surface.ambiguous_after_ids)} ambiguous != "
                    f"{len(surface.after_ids)} present"
                ),
            }
        )

    if len(surface.matched_before_ids) != matched:
        violations.append(
            {
                "clause": "d",
                "why": "a before-side unit was consumed by more than one correspondence",
            }
        )
    if len(surface.matched_after_ids) != matched:
        violations.append(
            {
                "clause": "d",
                "why": "an after-side unit holds more than one correspondence",
            }
        )
    return violations


def check_total_accounting(diff: Any, surface: ResolverSurface) -> tuple[list[dict[str, Any]], int]:
    """INVARIANT_6(d) over the resolver decision graph.

    Returns (violations, observations). `observations` is the number of resolver
    decisions actually examined, so a reader can tell a clause that held from a
    clause that had nothing to hold over.
    """
    violations: list[dict[str, Any]] = list(check_conservation(surface))

    added = _ids_of_kind(diff, ChangeKind.UNIT_ADDED)
    removed = _ids_of_kind(diff, ChangeKind.UNIT_REMOVED)
    named = named_ids(diff)
    definite = definite_ids(diff)

    # --- A: MATCHED -------------------------------------------------------
    #: Silence is legitimate here and ONLY here on the after side. What is
    #: forbidden is a record that contradicts the correspondence.
    for corr in surface.matched:
        b, a = corr.before_logical_id, corr.after_snapshot_logical_id
        if a in added or b in added:
            violations.append(
                {
                    "logical_id": a,
                    "clause": "d",
                    "disposition": "A_MATCHED",
                    "why": (
                        f"the resolver MATCHED after-side {a!r} to before-side {b!r}, "
                        "but the diff reports it added. A matched unit did not begin "
                        "at this revision"
                    ),
                }
            )
        if b in removed:
            violations.append(
                {
                    "logical_id": b,
                    "clause": "d",
                    "disposition": "A_MATCHED",
                    "why": (
                        f"before-side {b!r} was consumed by a MATCHED correspondence "
                        f"with {a!r}, but the diff reports it removed. A matched unit "
                        "did not end at this revision"
                    ),
                }
            )

    # --- B: NEW -----------------------------------------------------------
    for a in sorted(surface.new_after_ids):
        if a not in added:
            violations.append(
                {
                    "logical_id": a,
                    "clause": "d",
                    "disposition": "B_NEW",
                    "why": (
                        "the resolver settled this after-side unit as NEW and the "
                        "diff says nothing. Silence is a violation here: a unit that "
                        "genuinely begins must be visible as added"
                    ),
                }
            )

    # --- C: AMBIGUOUS -----------------------------------------------------
    for a in sorted(surface.ambiguous_after_ids):
        if a not in named:
            violations.append(
                {
                    "logical_id": a,
                    "clause": "d",
                    "disposition": "C_AMBIGUOUS",
                    "why": (
                        "the resolver declined to settle this identity and the diff "
                        "names it nowhere. Withholding the outcome without stating "
                        "the uncertainty is silent suppression"
                    ),
                }
            )
        if a in definite:
            violations.append(
                {
                    "logical_id": a,
                    "clause": "d",
                    "disposition": "C_AMBIGUOUS",
                    "why": (
                        "an identity the resolver declined to settle also carries a "
                        "definite outcome. An unsettled decision may never be "
                        "simultaneously reported as new, removed or modified"
                    ),
                }
            )

    # --- D: before-side not consumed --------------------------------------
    for b in sorted(surface.unmatched_before_ids):
        if b in removed or b in named:
            continue
        violations.append(
            {
                "logical_id": b,
                "clause": "d",
                "disposition": "D_UNCONSUMED_BEFORE",
                "why": (
                    "no correspondence consumed this before-side unit, and the diff "
                    "neither reports it removed nor names it unresolved. It left the "
                    "revision silently"
                ),
            }
        )

    # --- partition integrity ---------------------------------------------
    #: Accounted twice is not accounting. Kept from V2R1 because this half was
    #: never the defect.
    for logical_id in sorted(named & definite):
        violations.append(
            {
                "logical_id": logical_id,
                "clause": "d",
                "disposition": "PARTITION",
                "why": (
                    "a unit is both named by an unresolved record and definitely "
                    "classified; the accounting is not a partition"
                ),
            }
        )

    observations = (
        len(surface.matched)
        + len(surface.new_after_ids)
        + len(surface.ambiguous_after_ids)
        + len(surface.unmatched_before_ids)
    )
    return violations, observations


def check_quarantine_channel(
    diff: Any, surface: ResolverSurface, *, declared_record: str
) -> tuple[list[dict[str, Any]], int]:
    """INVARIANT_6(e). Every unsettled identity is VISIBLE, not merely withheld.

    The unsettled population now comes from the same frozen surface (c) and (d)
    read, rather than from a second independent resolver pass. `declared_record`
    is checked against the live enum, so a protocol that declared a kind
    production never emits fails here instead of passing vacuously.
    """
    violations: list[dict[str, Any]] = []

    if declared_record not in {kind.value for kind in ChangeKind}:
        violations.append(
            {
                "clause": "e",
                "why": (
                    f"the protocol declares record kind {declared_record!r}, which is "
                    "not a member of production's ChangeKind. A clause written over a "
                    "record nothing emits cannot be violated"
                ),
            }
        )
        return violations, 0

    unsettled = surface.quarantine_members | surface.ambiguous_after_ids
    named = named_ids(diff)

    for logical_id in sorted(unsettled - named):
        violations.append(
            {
                "logical_id": logical_id,
                "clause": "e",
                "why": (
                    "an unsettled identity is not named by any "
                    f"{declared_record} record. Withholding the definite outcome "
                    "without stating the uncertainty is SILENT SUPPRESSION: a false "
                    "statement replaced by no statement, which a fail-closed endpoint "
                    "cannot score"
                ),
            }
        )
    return violations, len(unsettled)


def check_ambiguous_not_reproduced(
    surface: ResolverSurface, reproduced_ids: frozenset[str] | set[str]
) -> tuple[list[dict[str, Any]], int]:
    """INVARIANT_6(c). An AMBIGUOUS decision may not enter matched-facet reproduction.

    Reproducing facets across a pairing the resolver declined to settle asserts
    the very correspondence that was declined. The ambiguous population is the
    surface's, so (c) and (d) can never disagree about who was ambiguous.
    """
    ambiguous = surface.ambiguous_after_ids | surface.ambiguous_candidate_before_ids
    overlap = sorted(ambiguous & frozenset(reproduced_ids))
    return (
        [
            {
                "logical_id": logical_id,
                "clause": "c",
                "why": (
                    "an AMBIGUOUS identity entered matched-facet reproduction, which "
                    "asserts the correspondence the resolver declined to settle"
                ),
            }
            for logical_id in overlap
        ],
        len(ambiguous),
    )
