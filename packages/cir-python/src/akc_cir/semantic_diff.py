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

The second rule, added by INC-V2-037: **identity equivalence is not change
equivalence.** `identity.normalize_text_for_identity` is documented in its own
docstring as a lossy fold built for one job -- deciding whether a unit in a new
revision is the same logical thing as a unit in an old one. This module used
that fold's output as the entire gate for `MODIFIED_CLAIM`, so `Apache` ->
`Apache(R)`, `Github` -> `GitHub`, a spacing edit or a hyphen replaced by an em
dash folded equal and vanished from change detection while remaining, correctly,
the same unit. `MODIFIED_CLAIM` is now decided on the CONTENT facet instead
(`content_facet_verdict` below), which is derived independently of identity.

The facet partition the change decision is declared over is
`tavonel.v2.source_fact_ir.change_facets.v1`. This module does not import that
research-tree module -- a package depending on `research/` would be the wrong
dependency direction -- so CONTENT is ported here, and the remaining eight
facets map onto change kinds this module already emitted:

    CONTENT                        MODIFIED_CLAIM          (ported below)
    STRUCTURAL                     STRUCTURE_CHANGED       (`_structural_changes`)
    REFERENCE_LOCATOR              EVIDENCE_MOVED          (L2 branch)
    TEMPORAL                       TEMPORAL_CHANGED        `_nonsemantic_dimension_changes`
    METADATA                       METADATA_CHANGED        `_nonsemantic_dimension_changes`
    VISUAL                         VISUAL_CHANGED          `_nonsemantic_dimension_changes`
    AUTHORITY_APPLICABILITY        AUTHORITY_CHANGED       (`_graph_changes`, L4)
    ACCESSIBILITY                  -- no data source in `UnitSnapshot`
    EXTERNAL_DEPENDENCY_EXECUTION  -- no data source in `UnitSnapshot`

The last two are declared rather than dropped: compiled-relevant state exists
that no field here can see, and saying so is the honest alternative to a
partition that looks complete because the gaps were deleted from it.
`research/tavonel_eval_v2/tests/test_identity_change_migration.py` binds the
ported CONTENT verdict to `change_facets.change_facets()[CONTENT]` so the two
implementations cannot drift apart silently.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
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
from .identity_quarantine import build_quarantine

#: INC-V2-047's repair, and the switch the Protected Core ladder's last rung
#: flips. It starts False on purpose.
#:
#: INC-V2-042 is what happens when a Protected Core switch ships ahead of the
#: benchmark and canary that were supposed to authorise it: the evidence gets
#: produced afterwards, by someone who already knows which answer is
#: convenient, and no amount of favourable measurement afterwards restores the
#: prospective independence that was skipped. That mistake was made once here
#: already -- the quarantine was written straight into the default path before
#: any rung had run. This constant is the correction.
#:
#: While False, `diff_documents` behaves exactly as it did before the repair:
#: only the candidates a decision NAMES are withheld, and a same-logical-id
#: counterpart escapes as UNIT_REMOVED (INC-V2-047). Callers on the ladder pass
#: `quarantine_unsettled_identity=True` explicitly. Flipping this default is a
#: separate, receipted act.
#: RUNG 5, executed 2026-08-25 after rungs 1-4 completed and PASSED, and
#: recorded as its own act rather than as a side effect of the repair. The
#: constant starts its life `False` above precisely so that this line is a
#: decision someone made on evidence and not a default nobody chose.
#:
#: Discharged, each against a row written in
#: `docs/COMPAT_IDENTITY_UNCERTAINTY_QUARANTINE.md` BEFORE any of it was
#: measured: units gaining a definite outcome 0; units vanishing from the diff
#: 0; `tests/unit` 993 passed / 68 skipped identically under both pins; pin OFF
#: reproduces V1's finding exactly (9 cases, 8 lineages); the nine close under
#: pin ON as development regressions only.
#:
#: What this flip does NOT claim. It is not prospective certification -- the
#: 514-pair universe is V1's and the nine cases were seen before the repair was
#: written; that is V2's job, and V2 can only do it against production, which
#: is why this cannot wait until after V2. Two of the contract's four clauses
#: have no members anywhere and `selected_candidate` is unreachable as wired
#: (INC-V2-052); they ship inert, contributing no behaviour, and stay declared
#: rather than being quietly deleted.
QUARANTINE_UNSETTLED_IDENTITY_DEFAULT = True

__all__ = [
    "CHANGE_FACET_SCHEMA",
    "ChangeChannel",
    "ChangeFacetVerdict",
    "ChangeKind",
    "DiffLevel",
    "DocumentShape",
    "SemanticChange",
    "SemanticDiff",
    "UnitSnapshot",
    "content_facet_verdict",
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
    VISUAL_CHANGED = "visual_changed"
    TEMPORAL_CHANGED = "temporal_changed"
    METADATA_CHANGED = "metadata_changed"
    # Not a change. A statement that identity could not be established, which is
    # deliberately not spelled as one of the changes above.
    IDENTITY_UNRESOLVED = "identity_unresolved"


class ChangeChannel(StrEnum):
    """Why a change matters, independently of the concrete change vocabulary.

    This is orthogonal to ``DiffLevel``. Locator/visual/structural observations
    remain auditable without being conflated with meaning changes that must seed
    semantic dependency traversal.
    """

    UNCHANGED = "unchanged"
    STRUCTURAL = "structural"
    LOCATOR = "locator"
    SEMANTIC = "semantic"
    GRAPH = "graph"
    TEMPORAL = "temporal"
    VISUAL = "visual"
    METADATA = "metadata"
    UNRESOLVED = "unresolved"


_CHANGE_CHANNEL: dict[ChangeKind, ChangeChannel] = {
    ChangeKind.CONTENT_UNCHANGED: ChangeChannel.UNCHANGED,
    ChangeKind.STRUCTURE_CHANGED: ChangeChannel.STRUCTURAL,
    ChangeKind.EVIDENCE_ADDED: ChangeChannel.LOCATOR,
    ChangeKind.EVIDENCE_REMOVED: ChangeChannel.LOCATOR,
    ChangeKind.EVIDENCE_MOVED: ChangeChannel.LOCATOR,
    ChangeKind.UNIT_ADDED: ChangeChannel.SEMANTIC,
    ChangeKind.UNIT_REMOVED: ChangeChannel.SEMANTIC,
    ChangeKind.MODIFIED_CLAIM: ChangeChannel.SEMANTIC,
    ChangeKind.ENTITY_CHANGED: ChangeChannel.GRAPH,
    ChangeKind.RELATIONSHIP_ADDED: ChangeChannel.GRAPH,
    ChangeKind.RELATIONSHIP_REMOVED: ChangeChannel.GRAPH,
    ChangeKind.AUTHORITY_CHANGED: ChangeChannel.GRAPH,
    ChangeKind.VISUAL_CHANGED: ChangeChannel.VISUAL,
    ChangeKind.TEMPORAL_CHANGED: ChangeChannel.TEMPORAL,
    ChangeKind.METADATA_CHANGED: ChangeChannel.METADATA,
    ChangeKind.IDENTITY_UNRESOLVED: ChangeChannel.UNRESOLVED,
}

_SEMANTIC_RECOMPILATION_CHANNELS = frozenset(
    {ChangeChannel.SEMANTIC, ChangeChannel.GRAPH}
)

#: The facet partition `MODIFIED_CLAIM` is now decided under. Named here so a
#: receipt can record which contract a change set was produced against, and so
#: the binding test has one string to pin rather than a version it inferred.
CHANGE_FACET_SCHEMA = "tavonel.v2.source_fact_ir.change_facets.v1"


class ChangeFacetVerdict(StrEnum):
    """How one facet of an already-matched unit pair resolved.

    Values match `change_facets.VERDICTS` exactly, so the two implementations
    are comparable without a translation table that could itself drift.
    `ignored_by_predeclared_policy` -- the fourth verdict in that vocabulary --
    is deliberately not offered for CONTENT: it exists for a facet a caller can
    declare inapplicable in advance (a source family with no jurisdiction
    concept has no `AUTHORITY_APPLICABILITY`), and there is no source family
    for which "what this unit says" is out of scope.
    """

    CHANGED = "changed"
    UNCHANGED = "unchanged"
    #: No data to compare on. **Never mapped to `unchanged`** -- reading an
    #: absence as agreement is the defect class INC-V2-037 belongs to, one
    #: layer up. Callers fail closed on it; see `diff_documents`.
    UNRESOLVED = "unresolved"


def _content_facet_projection(text: object) -> str | None:
    """NFC only -- canonical-form encoding noise is not a content change.

    Deliberately *not* `normalize_text_for_identity`: that fold is what erased
    the INC-V2-037 cases, because it casefolds, replaces punctuation with
    spaces and collapses whitespace. NFC only undoes an encoder's choice
    between a precomposed codepoint and a base character plus a combining mark
    for the *same* visible text. `Apache` and `Apache(R)` differ under NFC;
    two encodings of one accented letter do not.

    A non-`str` text is no data rather than an empty one, so it projects to
    `None` and the facet resolves `UNRESOLVED`.
    """
    if not isinstance(text, str):
        return None
    return unicodedata.normalize("NFC", text)


def content_facet_verdict(
    before: UnitSnapshot, after: UnitSnapshot
) -> ChangeFacetVerdict:
    """The CONTENT facet for one pair the identity layer already matched.

    Called only after identity has answered "is this the same unit?". It never
    consults identity again: it reads neither `identity_text` nor the resolver's
    decision, which is what keeps its agreement with identity evidence rather
    than a tautology.
    """
    before_projection = _content_facet_projection(before.text)
    after_projection = _content_facet_projection(after.text)
    if before_projection is None or after_projection is None:
        return ChangeFacetVerdict.UNRESOLVED
    if before_projection != after_projection:
        return ChangeFacetVerdict.CHANGED
    return ChangeFacetVerdict.UNCHANGED


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
    visual_fingerprint: str = ""
    temporal_fingerprint: str = ""
    metadata_fingerprint: str = ""

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

    @property
    def logical_unit_id(self) -> str:
        """Stable logical identity, named explicitly for new callers."""
        return self.logical_id

    @property
    def evidence_occurrence_id(self) -> str | None:
        """This version/location's evidence occurrence, not a logical identity."""
        return self.evidence_id


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
    #: Reading order of the units, as a sequence rather than a set.
    #:
    #: Added after the adversarial-graph sweep found that a pure reorder --
    #: same units, same text, same headings, same block count -- produced an
    #: identical shape, no changes at all, and an empty structural scope. Any
    #: artifact whose bytes depend on order was then carried forward stale, in
    #: every topology tested, 0/60 equivalent.
    #:
    #: Defaults to empty so every existing caller is unaffected: an adapter that
    #: does not supply an order is compared exactly as before, and the reorder
    #: blind spot remains for it. That is a real limitation of not declaring
    #: order, not a silent behaviour change for callers who never had it.
    unit_order: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticChange:
    kind: ChangeKind
    logical_id: str | None = None
    before: str | None = None
    after: str | None = None
    detail: str = ""
    candidates: tuple[str, ...] = ()

    @property
    def channel(self) -> ChangeChannel:
        return _CHANGE_CHANNEL[self.kind]

    def as_record(self) -> dict[str, object]:
        record: dict[str, object] = {
            "kind": self.kind.value,
            "channel": self.channel.value,
        }
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
    #: The logical ids in scope when the structural channel fired, empty
    #: otherwise. A block-count or heading-tree change is a property of the
    #: document rather than of any one unit, so it carries no ``logical_id`` and
    #: cannot enter ``changed_logical_ids`` -- which left a structural change
    #: with nothing to seed a dependency traversal with, and let an artifact
    #: aggregated over document position be carried over stale. The scope is the
    #: document's units, which is the honest answer to "what did this structural
    #: change touch": all of them, positionally.
    structural_scope: tuple[str, ...] = ()

    @property
    def structural_change_present(self) -> bool:
        return any(
            change.channel is ChangeChannel.STRUCTURAL for change in self.changes
        )

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

        Only meaning-changing channels enter this set. Locator-only evidence
        movement remains visible in ``changes`` but cannot make semantic
        artifacts stale. Unresolved identities are handled separately and fail
        closed in ``plan_recompilation``.
        """
        return self.changed_logical_ids_for(*_SEMANTIC_RECOMPILATION_CHANNELS)

    def changed_logical_ids_for(self, *channels: ChangeChannel) -> tuple[str, ...]:
        """Return stable logical ids whose changes belong to ``channels``."""
        wanted = frozenset(channels)
        if not wanted:
            return ()
        seen: list[str] = []
        for change in self.changes:
            if change.channel not in wanted:
                continue
            if change.logical_id and change.logical_id not in seen:
                seen.append(change.logical_id)
        return tuple(seen)

    def as_record(self) -> dict[str, object]:
        record: dict[str, object] = {
            "change_id": self.change_id,
            "level": self.level.value,
            "content_changed": self.content_changed,
            "changes": [change.as_record() for change in self.changes],
        }
        # Absent rather than empty, so a diff produced before the structural
        # channel existed and one that genuinely has no structural scope
        # serialise identically. `change_id` digests this record, and a new
        # always-present key would change every stored change id.
        if self.structural_scope:
            record["structural_scope"] = list(self.structural_scope)
        return record


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
    if before.unit_order != after.unit_order and set(before.unit_order) == set(after.unit_order):
        # Membership is unchanged, so nothing else in this comparison can see
        # it: heading set, block count, table shapes and figure refs are all
        # order-insensitive. Insertions and removals are already reported by the
        # unit-level comparison, so the pure-permutation case is the one that
        # would otherwise pass silently.
        changes.append(
            SemanticChange(
                kind=ChangeKind.STRUCTURE_CHANGED,
                before=str(before.unit_order),
                after=str(after.unit_order),
                detail="reading order changed without any change of membership",
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


def _nonsemantic_dimension_changes(
    before: UnitSnapshot, after: UnitSnapshot
) -> list[SemanticChange]:
    """Report replay-relevant dimensions without turning them into semantic edits."""
    changes: list[SemanticChange] = []
    for kind, label, old, new in (
        (
            ChangeKind.VISUAL_CHANGED,
            "visual fingerprint",
            before.visual_fingerprint,
            after.visual_fingerprint,
        ),
        (
            ChangeKind.TEMPORAL_CHANGED,
            "temporal fingerprint",
            before.temporal_fingerprint,
            after.temporal_fingerprint,
        ),
        (
            ChangeKind.METADATA_CHANGED,
            "metadata fingerprint",
            before.metadata_fingerprint,
            after.metadata_fingerprint,
        ),
    ):
        if old == new:
            continue
        changes.append(
            SemanticChange(
                kind=kind,
                logical_id=after.logical_id,
                before=old or None,
                after=new or None,
                detail=f"{label} changed without asserting a semantic text change",
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
    legacy_identity_change_predicate: bool = False,
    quarantine_unsettled_identity: bool | None = None,
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

    `legacy_identity_change_predicate` restores the pre-INC-V2-037 gate, in
    which a matched pair was reported `MODIFIED_CLAIM` only when its
    `normalize_text_for_identity` folds differed. It is off by default and
    exists so the old path stays reachable for canary comparison and rollback,
    not because it is a supported mode: it is the defect, and a caller that
    passes `True` is asking for the escapes back.
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

        # INC-V2-047. The quarantine is computed over ALL decisions before any
        # change is emitted, because membership is not knowable one decision at
        # a time: clause (4) implicates a definite match by the state of a
        # counterpart another decision left unsettled. The previous code decided
        # per unit as it went and could therefore only ever protect what the
        # current decision itself named -- which is exactly the omission that
        # let a same-logical-id counterpart escape as UNIT_REMOVED.
        settled = [
            (incoming, decision)
            for incoming, decision in zip(after_units, decisions, strict=True)
        ]
        quarantine_on = (
            QUARANTINE_UNSETTLED_IDENTITY_DEFAULT
            if quarantine_unsettled_identity is None
            else quarantine_unsettled_identity
        )
        quarantine = build_quarantine(
            unsettled_decisions=[
                (incoming.logical_id, decision.candidates, decision.logical_id)
                for incoming, decision in settled
                if decision.match is LogicalMatch.AMBIGUOUS
            ],
            definite_matches=[
                (incoming.logical_id, decision.logical_id)
                for incoming, decision in settled
                if decision.match is not LogicalMatch.AMBIGUOUS and decision.logical_id
            ],
            before_ids=frozenset(by_logical),
        )
        if not quarantine_on:
            #: The pre-repair path, reachable on purpose and kept reachable. An
            #: empty quarantine makes every guard below a no-op, so the old
            #: behaviour is restored by removing evidence rather than by a
            #: second code path that could drift away from the one it stands in
            #: for.
            quarantine = build_quarantine(
                unsettled_decisions=(), definite_matches=(), before_ids=frozenset()
            )
        # Every logical id this diff has already described as unresolved, so the
        # visibility pass below adds a record for a quarantined unit without
        # duplicating one the incoming loop already emitted for the same id.
        unresolved_ids: set[str] = set()

        for incoming, decision in zip(after_units, decisions, strict=True):
            if decision.match is LogicalMatch.NEW and decision.logical_id is None:
                decision = replace(decision, logical_id=incoming.logical_id)

            if decision.match is LogicalMatch.AMBIGUOUS:
                # The rule this module exists to hold. Not a modification, not a
                # remove-plus-add: a statement that identity is unsettled.
                #
                # `logical_id` is the *incoming* unit whose identity could not be
                # settled; `candidates` are the prior units it might continue.
                # Recording only the candidates named one side of an unsettled
                # correspondence, and the incoming unit then appeared in no
                # change at all -- not here, not as UNIT_ADDED, because this
                # branch returns. Anything derived from it was reached by
                # nothing and was carried over stale while a full rebuild
                # produced different bytes. The channel stays UNRESOLVED, so
                # this does not enter `changed_logical_ids`: an unsettled
                # identity is still not a modification.
                changes.append(
                    SemanticChange(
                        kind=ChangeKind.IDENTITY_UNRESOLVED,
                        logical_id=incoming.logical_id,
                        detail=decision.reason,
                        candidates=decision.candidates,
                    )
                )
                unresolved_ids.add(incoming.logical_id)
                # `unsettled` is retained as the removal loop's fast membership
                # test and is now filled from the quarantine, which is a superset
                # of the candidates this branch used to add on its own.
                unsettled.update(decision.candidates)
                continue

            # The quarantine, applied to EVERY definite outcome and asked
            # before any of them is emitted.
            #
            # It was first written just below the NEW branch, so a quarantined id
            # could still escape as UNIT_ADDED -- one of the exact outcomes the
            # invariant forbids. The development replay caught it: violations
            # went from 0 to 12 against a pre-repair baseline of 0, all of them
            # `unit_added` on a quarantined id. The repair had correctly
            # identified the unit as unsafe and then made a definite statement
            # about it anyway, which is the original defect with a different
            # verb. A guard that covers three of four exits is not a guard.
            #
            # Withheld and STATED, never silently dropped: a fail-closed
            # endpoint cannot score an absence.
            implicated = decision.logical_id or incoming.logical_id
            if implicated in quarantine:
                #: INC-V2-051. This was `reason_for(...) or "identity is
                #: unsettled"` and `implicated_by(...) or ""`. Membership has
                #: just been tested and both fields are non-optional on
                #: `QuarantineMember`, so neither fallback could ever be taken
                #: -- a probe over every quarantine path confirmed it never was.
                #: An empty candidate would in any case have produced a record
                #: that LOOKS well-formed and that a fail-closed consumer
                #: scanning for non-empty ids drops, which is the silent
                #: disappearance this repair exists to prevent.
                member = quarantine.member(implicated)
                changes.append(
                    SemanticChange(
                        kind=ChangeKind.IDENTITY_UNRESOLVED,
                        logical_id=incoming.logical_id,
                        #: `reason_for` is Optional only because the mapping is
                        #: general; membership was just established, so the
                        #: fallback is unreachable rather than a default being
                        #: quietly supplied for a missing reason.
                        detail=member.reason,
                        candidates=(member.implicated_by,),
                    )
                )
                unresolved_ids.add(incoming.logical_id)
                unresolved_ids.add(implicated)
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

            # INC-V2-037. The gate used to be `counterpart.identity_text !=
            # incoming.identity_text`, which asked the identity fold a question
            # it is documented not to answer: whether the content moved. It is
            # now the CONTENT facet, derived from the raw text and NFC alone.
            #
            # UNRESOLVED fails closed as a modification rather than silently
            # passing as unchanged, and says so in `detail`. Reporting it
            # `IDENTITY_UNRESOLVED` instead would be a different lie: identity
            # was settled here -- that is why there is a counterpart at all --
            # and it is the content that could not be compared.
            if legacy_identity_change_predicate:
                content_changed_here = counterpart.identity_text != incoming.identity_text
                content_detail = ""
            else:
                verdict = content_facet_verdict(counterpart, incoming)
                content_changed_here = verdict is not ChangeFacetVerdict.UNCHANGED
                content_detail = (
                    "content facet unresolved: a unit's text was not comparable, "
                    "reported as modified rather than assumed unchanged"
                    if verdict is ChangeFacetVerdict.UNRESOLVED
                    else ""
                )

            if content_changed_here:
                changes.append(
                    SemanticChange(
                        kind=ChangeKind.MODIFIED_CLAIM,
                        logical_id=counterpart.logical_id,
                        before=counterpart.text,
                        after=incoming.text,
                        detail=content_detail,
                    )
                )

            changes.extend(_nonsemantic_dimension_changes(counterpart, incoming))

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

        #: Every id this diff has already made visible as unresolved, either as
        #: the subject of a record or as a candidate named inside one.
        named_in_unresolved: set[str] = set(unresolved_ids)
        for change in changes:
            if change.kind is ChangeKind.IDENTITY_UNRESOLVED:
                if change.logical_id:
                    named_in_unresolved.add(change.logical_id)
                named_in_unresolved.update(c for c in (change.candidates or ()) if c)

        for unit in previous:
            if unit.logical_id in matched_before:
                continue
            if unit.logical_id in quarantine or unit.logical_id in unsettled:
                if not quarantine_on:
                    #: Pre-repair behaviour, restored exactly: a named candidate
                    #: was skipped SILENTLY. Gating this too is what makes the
                    #: pin a real reference path -- an `unsettled` member would
                    #: otherwise still gain a record it never had, and the
                    #: differential below would be measuring the repair against
                    #: something that was never production.
                    continue
                # INC-V2-047's repair, and the half that is easy to get wrong.
                # Suppressing the false UNIT_REMOVED is not enough: a unit that
                # simply disappears from the diff has had a false statement
                # replaced by no statement, and a fail-closed endpoint cannot
                # score an absence. So the uncertainty is STATED. The channel is
                # UNRESOLVED, so this still does not enter
                # `changed_logical_ids` -- an unsettled identity is not a
                # modification -- but it is visible to `SemanticDiff.unresolved`
                # and therefore to SFI3's E7.
                #: Only what is OTHERWISE INVISIBLE gets a record of its own.
                #:
                #: A declared candidate is already named -- it appears in the
                #: `candidates` field of the unresolved record emitted for the
                #: incoming unit whose identity it might continue -- so giving it
                #: a second record of its own says nothing new and breaks the
                #: property that one unsettled decision produces one unresolved
                #: record. The first version of this repair did exactly that and
                #: three Protected Core consumer tests caught it: a two-candidate
                #: ambiguity produced three records where one was correct.
                #:
                #: The unit INC-V2-047 is about is different in the way that
                #: matters: it is named by nobody. It shares the incoming's
                #: logical id, no decision lists it as a candidate, and before
                #: this repair it was reported UNIT_REMOVED. Withholding that
                #: removal without stating anything would move it from a false
                #: statement to no statement, so it -- and only it -- needs a
                #: record here.
                if unit.logical_id in named_in_unresolved:
                    continue
                changes.append(
                    SemanticChange(
                        kind=ChangeKind.IDENTITY_UNRESOLVED,
                        logical_id=unit.logical_id,
                        #: Same correction as above, and here it also makes an
                        #: unstated property load-bearing. This branch is
                        #: entered on `in quarantine OR in unsettled`, so the
                        #: lookup is total only because every `unsettled` member
                        #: is a DECLARED_CANDIDATE of the quarantine whenever
                        #: the pin is on. If that subset relation ever stops
                        #: holding, this raises instead of quietly emitting a
                        #: record with an empty candidate.
                        detail=quarantine.member(unit.logical_id).reason,
                        candidates=(quarantine.member(unit.logical_id).implicated_by,),
                    )
                )
                unresolved_ids.add(unit.logical_id)
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

    # A structural change names no unit, so its scope is the document: every
    # logical id on either side, in a stable order. Recording it here rather
    # than deriving it downstream keeps the diff the single description of what
    # changed, and keeps `plan_recompilation` from needing the unit lists again.
    structural_scope: tuple[str, ...] = ()
    if any(change.channel is ChangeChannel.STRUCTURAL for change in changes):
        ordered: list[str] = []
        for unit in (*before_units, *after_units):
            if unit.logical_id and unit.logical_id not in ordered:
                ordered.append(unit.logical_id)
        structural_scope = tuple(ordered)

    records = [change.as_record() for change in changes]
    return SemanticDiff(
        level=level,
        content_changed=True,
        changes=tuple(changes),
        change_id=_change_id(records),
        structural_scope=structural_scope,
    )
