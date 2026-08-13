"""What changed between two versions of a document, at five levels.

Masterplan §12. This is the layer that turns "the bytes are different" into "the
warranty clause went from two years to three", and everything downstream depends
on it being right: dependency traversal (§15) walks out from the changed units,
impact (§16.1) marks artifacts stale from that set, and selective recompile
rebuilds exactly it. A diff that reports the wrong unit as changed sends all
three after the wrong thing.

The five levels answer progressively harder questions:

    L0 binary       did the bytes change at all
    L1 structural   did the shape change -- headings, block counts, table shape
    L2 evidence     which anchored regions were added, removed, moved
    L3 semantic     which knowledge units changed, and how
    L4 graph        did entities, relations or authority change

L0 is cheap and answers most calls; the expensive levels only run when a caller
asks for them. Two runs over the same pair of versions always produce the same
change set, because impact analysis that is not reproducible cannot be audited.

The rule this module exists to hold: **an identity the resolver could not settle
is never reported as a modification.** Calling it modified asserts continuity
that was not established, and calling it removed-plus-added destroys a history
that may be real. It is reported as unresolved, which is what it is.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from .identity import (
    LogicalIdentityResolver,
    LogicalMatch,
    LogicalUnitFingerprint,
    assign_one_to_one,
    normalize_text_for_identity,
)

__all__ = [
    "ChangeKind",
    "DiffLevel",
    "DocumentShape",
    "SemanticChange",
    "SemanticDiff",
    "UnitSnapshot",
    "diff_documents",
]

#: Stands in for the source id when a caller diffs two versions without naming
#: the source. Both sides get the same value, so §N15.2's continuity signal is
#: available and reads "these are two versions of one document" -- which is what
#: calling `diff_documents` asserts. It is not a measured value dressed up as
#: one: a real source id should be passed whenever the caller has it.
_DIFF_SCOPE_LINEAGE = "<diff-scope>"


class DiffLevel(StrEnum):
    """§12's five levels. Ordered, and each implies the ones below it."""

    BINARY = "L0"
    STRUCTURAL = "L1"
    EVIDENCE = "L2"
    SEMANTIC = "L3"
    GRAPH = "L4"


_LEVEL_ORDER = {
    DiffLevel.BINARY: 0,
    DiffLevel.STRUCTURAL: 1,
    DiffLevel.EVIDENCE: 2,
    DiffLevel.SEMANTIC: 3,
    DiffLevel.GRAPH: 4,
}


class ChangeKind(StrEnum):
    CONTENT_UNCHANGED = "content_unchanged"
    STRUCTURE_CHANGED = "structure_changed"
    EVIDENCE_ADDED = "evidence_added"
    EVIDENCE_REMOVED = "evidence_removed"
    EVIDENCE_MOVED = "evidence_moved"
    UNIT_ADDED = "unit_added"
    UNIT_REMOVED = "unit_removed"
    MODIFIED_CLAIM = "modified_claim"
    ENTITY_CHANGED = "entity_changed"
    RELATIONSHIP_ADDED = "relationship_added"
    RELATIONSHIP_REMOVED = "relationship_removed"
    AUTHORITY_CHANGED = "authority_changed"
    # Not a change. A statement that identity could not be established, which is
    # deliberately not spelled as one of the changes above.
    IDENTITY_UNRESOLVED = "identity_unresolved"


@dataclass(frozen=True, slots=True)
class UnitSnapshot:
    """One knowledge unit as it stood in one version.

    `logical_id` is what the identity layer assigned. `evidence_id` anchors it to
    a region of the document, and it is allowed to change while the logical id
    stays the same -- that is a unit that moved, not a different unit.
    """

    logical_id: str
    text: str
    document_path: tuple[str, ...] = ()
    anchor: str = ""
    neighbour_anchors: tuple[str, ...] = ()
    evidence_id: str | None = None
    page_number1: int | None = None
    entities: frozenset[str] = frozenset()
    relationships: frozenset[tuple[str, str, str]] = frozenset()
    authority: str | None = None
    #: §N15.2 signal inputs. Empty means the document did not provide one, which
    #: the resolver treats as an absent signal rather than a mismatched value.
    explicit_identifier: str = ""
    geometry_style: str = ""

    def fingerprint(self, *, source_lineage: str = "") -> LogicalUnitFingerprint:
        return LogicalUnitFingerprint.of(
            logical_id=self.logical_id,
            document_path=self.document_path,
            anchor=self.anchor,
            text=self.text,
            source_lineage=source_lineage,
            explicit_identifier=self.explicit_identifier,
            geometry_style=self.geometry_style,
            neighbour_anchors=self.neighbour_anchors,
        )

    @property
    def identity_text(self) -> str:
        return normalize_text_for_identity(self.text)


@dataclass(frozen=True, slots=True)
class DocumentShape:
    """The structural skeleton §12's L1 compares.

    Deliberately not the content: two versions with identical shape and totally
    different words differ at L3, not L1, and a caller who only asked for L1
    should not be told the shape changed.
    """

    heading_path_set: frozenset[tuple[str, ...]] = frozenset()
    block_count: int = 0
    table_shapes: tuple[tuple[int, int], ...] = ()
    figure_refs: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class SemanticChange:
    kind: ChangeKind
    logical_id: str | None = None
    before: str | None = None
    after: str | None = None
    detail: str = ""
    candidates: tuple[str, ...] = ()

    def as_record(self) -> dict[str, object]:
        record: dict[str, object] = {"kind": self.kind.value}
        for name, value in (
            ("logical_id", self.logical_id),
            ("before", self.before),
            ("after", self.after),
            ("detail", self.detail or None),
        ):
            if value is not None:
                record[name] = value
        if self.candidates:
            record["candidates"] = list(self.candidates)
        return record


@dataclass(frozen=True, slots=True)
class SemanticDiff:
    level: DiffLevel
    content_changed: bool
    changes: tuple[SemanticChange, ...] = ()
    change_id: str = ""

    @property
    def unresolved(self) -> tuple[SemanticChange, ...]:
        return tuple(
            change
            for change in self.changes
            if change.kind is ChangeKind.IDENTITY_UNRESOLVED
        )

    @property
    def changed_logical_ids(self) -> tuple[str, ...]:
        """The set a dependency traversal starts from.

        Unresolved identities are not in it. Marking artifacts stale from an
        identity nobody established would spread a guess across the graph.
        """
        seen: list[str] = []
        for change in self.changes:
            if change.kind is ChangeKind.IDENTITY_UNRESOLVED:
                continue
            if change.logical_id and change.logical_id not in seen:
                seen.append(change.logical_id)
        return tuple(seen)

    def as_record(self) -> dict[str, object]:
        return {
            "change_id": self.change_id,
            "level": self.level.value,
            "content_changed": self.content_changed,
            "changes": [change.as_record() for change in self.changes],
        }


def _change_id(records: Sequence[dict[str, object]]) -> str:
    """A digest over the change set, so two runs can be compared by one value."""
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "chg_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _structural_changes(before: DocumentShape, after: DocumentShape) -> list[SemanticChange]:
    changes: list[SemanticChange] = []
    if before.heading_path_set != after.heading_path_set:
        added = len(after.heading_path_set - before.heading_path_set)
        removed = len(before.heading_path_set - after.heading_path_set)
        changes.append(
            SemanticChange(
                kind=ChangeKind.STRUCTURE_CHANGED,
                detail=f"heading tree changed: {added} added, {removed} removed",
            )
        )
    if before.block_count != after.block_count:
        changes.append(
            SemanticChange(
                kind=ChangeKind.STRUCTURE_CHANGED,
                before=str(before.block_count),
                after=str(after.block_count),
                detail="block count changed",
            )
        )
    if before.table_shapes != after.table_shapes:
        changes.append(
            SemanticChange(
                kind=ChangeKind.STRUCTURE_CHANGED,
                before=str(before.table_shapes),
                after=str(after.table_shapes),
                detail="table shape changed",
            )
        )
    if before.figure_refs != after.figure_refs:
        changes.append(
            SemanticChange(
                kind=ChangeKind.STRUCTURE_CHANGED,
                detail=(
                    f"figure references changed: "
                    f"{len(after.figure_refs - before.figure_refs)} added, "
                    f"{len(before.figure_refs - after.figure_refs)} removed"
                ),
            )
        )
    return changes


def _graph_changes(before: UnitSnapshot, after: UnitSnapshot) -> list[SemanticChange]:
    changes: list[SemanticChange] = []
    if before.entities != after.entities:
        changes.append(
            SemanticChange(
                kind=ChangeKind.ENTITY_CHANGED,
                logical_id=after.logical_id,
                detail=(
                    f"entities changed: +{sorted(after.entities - before.entities)} "
                    f"-{sorted(before.entities - after.entities)}"
                ),
            )
        )
    for relation in sorted(after.relationships - before.relationships):
        changes.append(
            SemanticChange(
                kind=ChangeKind.RELATIONSHIP_ADDED,
                logical_id=after.logical_id,
                after=" ".join(relation),
            )
        )
    for relation in sorted(before.relationships - after.relationships):
        changes.append(
            SemanticChange(
                kind=ChangeKind.RELATIONSHIP_REMOVED,
                logical_id=after.logical_id,
                before=" ".join(relation),
            )
        )
    if before.authority != after.authority:
        changes.append(
            SemanticChange(
                kind=ChangeKind.AUTHORITY_CHANGED,
                logical_id=after.logical_id,
                before=before.authority,
                after=after.authority,
                detail="a claim's authority changed, which changes how much it should be trusted",
            )
        )
    return changes


def diff_documents(
    *,
    before_sha256: str,
    after_sha256: str,
    level: DiffLevel = DiffLevel.BINARY,
    before_shape: DocumentShape | None = None,
    after_shape: DocumentShape | None = None,
    before_units: Sequence[UnitSnapshot] = (),
    after_units: Sequence[UnitSnapshot] = (),
    resolver: LogicalIdentityResolver | None = None,
    source: str = "",
) -> SemanticDiff:
    """Compare two document versions up to the requested level.

    Levels are cumulative: asking for L3 runs L0 through L3. Asking for L0 on
    two identical digests is one comparison and returns immediately, which is
    what makes it cheap enough to run on every ingest.

    `source` is the source id both versions belong to. It feeds §N15.2's
    `source_continuity` signal, which is one of the critical signals the resolver
    abstains without. Passing it is not §N4.4 zero-filling: calling this function
    at all asserts that the two digests are versions of one document, so the
    lineage is structural rather than measured. When it is omitted a scope
    sentinel stands in, which keeps the signal available and honest about where
    it came from -- but a caller that diffs two genuinely unrelated documents
    while omitting it will get `SAME_AS_VERSION` relations it has not earned.
    """
    content_changed = before_sha256 != after_sha256
    wanted = _LEVEL_ORDER[level]
    changes: list[SemanticChange] = []

    if not content_changed:
        # Identical bytes cannot have a structural or semantic difference, and
        # reporting one would mean a level below is disagreeing with L0.
        diff = SemanticDiff(
            level=level,
            content_changed=False,
            changes=(SemanticChange(kind=ChangeKind.CONTENT_UNCHANGED),),
        )
        return SemanticDiff(
            level=diff.level,
            content_changed=False,
            changes=diff.changes,
            change_id=_change_id([c.as_record() for c in diff.changes]),
        )

    if wanted >= _LEVEL_ORDER[DiffLevel.STRUCTURAL]:
        if before_shape is None or after_shape is None:
            raise ValueError("L1 and above need a DocumentShape for both versions")
        changes.extend(_structural_changes(before_shape, after_shape))

    if wanted >= _LEVEL_ORDER[DiffLevel.SEMANTIC]:
        engine = resolver or LogicalIdentityResolver()
        previous = list(before_units)
        by_logical = {unit.logical_id: unit for unit in previous}
        matched_before: set[str] = set()
        # Candidates named in an unresolved decision. One of them may well be
        # the continuation, so none of them may be reported as removed: that
        # spelling asserts a deletion the resolver explicitly declined to make.
        unsettled: set[str] = set()

        # §N15.3 -- one old unit to one new unit, decided over the whole window
        # rather than per unit. Resolving each incoming independently lets two
        # new units both claim the same old one; each looks locally reasonable
        # and the result is a history that forked without anyone deciding to.
        lineage = source or _DIFF_SCOPE_LINEAGE
        decisions = assign_one_to_one(
            [unit.fingerprint(source_lineage=lineage) for unit in after_units],
            [unit.fingerprint(source_lineage=lineage) for unit in previous],
            resolver=engine,
        )

        for incoming, decision in zip(after_units, decisions, strict=True):
            if decision.match is LogicalMatch.NEW and decision.logical_id is None:
                decision = replace(decision, logical_id=incoming.logical_id)

            if decision.match is LogicalMatch.AMBIGUOUS:
                # The rule this module exists to hold. Not a modification, not a
                # remove-plus-add: a statement that identity is unsettled.
                changes.append(
                    SemanticChange(
                        kind=ChangeKind.IDENTITY_UNRESOLVED,
                        logical_id=None,
                        detail=decision.reason,
                        candidates=decision.candidates,
                    )
                )
                unsettled.update(decision.candidates)
                continue

            if decision.match is LogicalMatch.NEW:
                changes.append(
                    SemanticChange(
                        kind=ChangeKind.UNIT_ADDED,
                        logical_id=decision.logical_id,
                        after=incoming.text,
                    )
                )
                continue

            counterpart = by_logical.get(decision.logical_id or "")
            if counterpart is None:
                changes.append(
                    SemanticChange(
                        kind=ChangeKind.UNIT_ADDED,
                        logical_id=decision.logical_id,
                        after=incoming.text,
                    )
                )
                continue

            matched_before.add(counterpart.logical_id)

            if counterpart.identity_text != incoming.identity_text:
                changes.append(
                    SemanticChange(
                        kind=ChangeKind.MODIFIED_CLAIM,
                        logical_id=counterpart.logical_id,
                        before=counterpart.text,
                        after=incoming.text,
                    )
                )

            if wanted >= _LEVEL_ORDER[DiffLevel.EVIDENCE] and (
                counterpart.evidence_id != incoming.evidence_id
                or counterpart.page_number1 != incoming.page_number1
            ):
                changes.append(
                    SemanticChange(
                        kind=ChangeKind.EVIDENCE_MOVED,
                        logical_id=counterpart.logical_id,
                        before=counterpart.evidence_id,
                        after=incoming.evidence_id,
                        detail=(
                            f"page {counterpart.page_number1} -> {incoming.page_number1}"
                            if counterpart.page_number1 != incoming.page_number1
                            else "anchor changed within the same page"
                        ),
                    )
                )

            if wanted >= _LEVEL_ORDER[DiffLevel.GRAPH]:
                changes.extend(_graph_changes(counterpart, incoming))

        for unit in previous:
            if unit.logical_id in matched_before or unit.logical_id in unsettled:
                continue
            changes.append(
                SemanticChange(
                    kind=ChangeKind.UNIT_REMOVED,
                    logical_id=unit.logical_id,
                    before=unit.text,
                )
            )

    elif wanted >= _LEVEL_ORDER[DiffLevel.EVIDENCE]:
        before_ids = {unit.evidence_id for unit in before_units if unit.evidence_id}
        after_ids = {unit.evidence_id for unit in after_units if unit.evidence_id}
        for evidence in sorted(after_ids - before_ids):
            changes.append(
                SemanticChange(kind=ChangeKind.EVIDENCE_ADDED, after=evidence)
            )
        for evidence in sorted(before_ids - after_ids):
            changes.append(
                SemanticChange(kind=ChangeKind.EVIDENCE_REMOVED, before=evidence)
            )

    records = [change.as_record() for change in changes]
    return SemanticDiff(
        level=level,
        content_changed=True,
        changes=tuple(changes),
        change_id=_change_id(records),
    )
