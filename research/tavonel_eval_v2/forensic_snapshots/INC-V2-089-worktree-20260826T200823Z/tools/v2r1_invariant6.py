"""INVARIANT_6 for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R1, all five clauses.

Split into its own module because (d) and (e) are the load-bearing NEW claims of
V2R1 and they deserve to be readable, mutation-tested and cited on their own
rather than buried inside a thousand-line runner.

    (a) an unsettled identity may not also carry a continuity assertion
    (b) a candidate of an unsettled identity may not be reported removed
    (c) an AMBIGUOUS decision may not enter matched-facet reproduction
    (d) TOTAL UNIT ACCOUNTING
    (e) every quarantined identity stays visible on the declared channel

(a) and (b) are V1's, reused from `identity_change_migration_closure` rather
than reimplemented -- a second implementation of a check that already passed a
frozen closure is a second thing that can drift.

WHY (d) NEEDS A PARAGRAPH. `SemanticDiff` publishes `changes`, `unresolved`,
`changed_logical_ids` and `structural_change_present`. It has NO matched
surface. A matched, unchanged unit therefore emits no record at all, which means
SILENCE IS A FIFTH EXIT rather than an omission. A (d) computed from the change
list alone would mark every unchanged unit unaccounted and fail every pair for a
reason that has nothing to do with the migration. That is not a hypothetical: it
is INC-V2-053, found by writing exactly that classifier and watching it report
`unaccounted` on a pair where nothing was wrong. MATCHED is therefore INFERRED
as {present on both id sets} AND {carrying no record}.

WHY (e) IS NOT SATISFIED BY WITHHOLDING. Suppressing a false `unit_removed` and
saying nothing replaces a false statement with no statement, and a fail-closed
endpoint cannot score an absence. An empty candidate string does not count as
NAMED: a record saying a unit is implicated by something it declines to identify
names nothing, and a criterion that accepted one could be satisfied by silence
wearing the shape of a statement.
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

#: The record kind production emits for an unresolved identity. Read from the
#: enum rather than written as a string, so a rename cannot leave this module
#: quietly checking for a literal nothing emits any more.
UNRESOLVED_KIND = ChangeKind.IDENTITY_UNRESOLVED

#: The concrete, identity-sensitive outcomes. A quarantined unit may carry none
#: of them.
DEFINITE_KINDS: tuple[ChangeKind, ...] = (
    ChangeKind.UNIT_ADDED,
    ChangeKind.UNIT_REMOVED,
    ChangeKind.MODIFIED_CLAIM,
)


def _named_ids(diff: Any) -> set[str]:
    """Every id made visible by an unresolved record, as subject or candidate.

    Empty strings are dropped. NAMED means a non-empty logical id: an empty
    candidate entry names nothing.
    """
    named: set[str] = set()
    for change in diff.changes:
        if change.kind is not UNRESOLVED_KIND:
            continue
        if change.logical_id:
            named.add(change.logical_id)
        named.update(c for c in (change.candidates or ()) if c)
    return named


def _definite_ids(diff: Any) -> set[str]:
    return {
        change.logical_id
        for change in diff.changes
        if change.kind in DEFINITE_KINDS and change.logical_id
    }


def check_total_accounting(
    diff: Any,
    *,
    before_ids: frozenset[str] | set[str],
    after_ids: frozenset[str] | set[str],
) -> tuple[list[dict[str, Any]], int]:
    """INVARIANT_6(d). Every id accounted exactly once, silence included.

    Returns (violations, observations). `observations` is the size of the
    population actually examined, so a caller can tell a clean pair from a pair
    that had nothing in it -- an endpoint nothing could have violated has not
    been met, it has been avoided.
    """
    before = frozenset(before_ids)
    after = frozenset(after_ids)
    population = before | after

    named = _named_ids(diff)
    definite = _definite_ids(diff)

    #: The fifth exit. Inferred, because production does not publish it.
    silent = population - named - definite
    matched = silent & before & after

    violations: list[dict[str, Any]] = []

    #: Present on one side only, and carrying no statement whatsoever. This is
    #: silent disappearance (before-side) or silent appearance (after-side).
    for logical_id in sorted((silent - matched) & before):
        violations.append(
            {
                "logical_id": logical_id,
                "clause": "d",
                "why": (
                    "a before-side unit left the diff with no record of any kind: "
                    "not matched, not definitely classified, not named as unresolved"
                ),
            }
        )
    for logical_id in sorted((silent - matched) & after):
        violations.append(
            {
                "logical_id": logical_id,
                "clause": "d",
                "why": (
                    "an after-side unit appeared with no record of any kind: not "
                    "matched, not definitely classified, not named as unresolved"
                ),
            }
        )

    #: Accounted TWICE, which is not accounting. A unit whose identity was
    #: declined cannot simultaneously carry a definite outcome.
    for logical_id in sorted(named & definite):
        violations.append(
            {
                "logical_id": logical_id,
                "clause": "d",
                "why": (
                    "a unit is both named by an unresolved record and definitely "
                    "classified; the accounting is not a partition"
                ),
            }
        )

    return violations, len(population)


def check_quarantine_channel(
    diff: Any,
    *,
    unsettled_ids: frozenset[str] | set[str],
    declared_record: str,
) -> tuple[list[dict[str, Any]], int]:
    """INVARIANT_6(e). Every unsettled identity is VISIBLE, not merely withheld.

    `declared_record` is `quarantine_channel.production_record` from the frozen
    protocol. It is checked against the live enum here rather than trusted as a
    string: a declared kind production never emits would make this clause
    vacuous, which is this study's most-repeated defect.
    """
    violations: list[dict[str, Any]] = []

    valid = {kind.value for kind in ChangeKind}
    if declared_record not in valid:
        violations.append(
            {
                "clause": "e",
                "why": (
                    f"the protocol declares record kind {declared_record!r}, which is "
                    "not a member of production's ChangeKind. A clause written over a "
                    "record nothing emits cannot be violated, and a criterion that "
                    "cannot be violated has not been met"
                ),
            }
        )
        return violations, 0

    named = _named_ids(diff)
    unsettled = frozenset(unsettled_ids)

    for logical_id in sorted(unsettled - named):
        violations.append(
            {
                "logical_id": logical_id,
                "clause": "e",
                "why": (
                    "an unsettled identity is not named by any "
                    f"{declared_record} record. Withholding the definite outcome "
                    "without stating the uncertainty is SILENT SUPPRESSION: a false "
                    "statement replaced by no statement, which a fail-closed "
                    "endpoint cannot score"
                ),
            }
        )

    #: Reported so a reader can tell a clause that held from a clause that had
    #: no members to hold over.
    return violations, len(unsettled)


def check_ambiguous_not_reproduced(
    ambiguous_ids: frozenset[str] | set[str],
    reproduced_ids: frozenset[str] | set[str],
) -> tuple[list[dict[str, Any]], int]:
    """INVARIANT_6(c). An AMBIGUOUS decision may not enter matched-facet reproduction.

    Reproducing facets across a pairing the resolver declined to settle asserts
    the very correspondence that was declined.
    """
    ambiguous = frozenset(ambiguous_ids)
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
