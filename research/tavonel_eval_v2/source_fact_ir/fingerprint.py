"""SOURCE_FACT_IR_V1 links 3 and 4 — fingerprint, dependency path, and the
alignment invariant that makes INC-V2-028 impossible by construction.

What went wrong, stated as a property rather than as four anecdotes:

    the semantic diff's notion of "changed" and the artifact fingerprint's
    notion of "changed" are two different functions, and nothing required them
    to agree.

Three of the four confirmed stale escapes were cases where the diff was *right*
— typographic_punctuation x1, alphanumeric x2 — and the artifact digest moved
anyway. The fourth was artifact_membership_or_order: an artifact whose value is
derived from *which units exist and in what order*, invalidated (or not) from a
structural verdict about the document rather than from membership itself. Not
one was a missed substantive edit. The damage is therefore not a lost edit; it
is that the selective state is not reproducible by a clean rebuild, and a state
that a clean rebuild does not reproduce cannot be called CURRENT.

This module does not try to make the two functions agree. It makes the
disagreement *detectable and fail-closed*:

    for every artifact key whose value differs between a clean rebuild of the
    BEFORE facts and a clean rebuild of the AFTER facts, the typed delta must
    have named that key. An artifact that moved without being named is an
    alignment violation and `assert_aligned` raises.

Two design commitments, both deliberate, both limitations rather than cleverness.

**Declared conservative always-rebuild.** The derived-membership artifact
classes — `document-index:`, `structure-map:` and `topic-bucket:` — are
invalidated on *every* non-empty delta for every document the delta touches.
Their values are functions of the whole unit set (membership, order, paths), so
no per-fact channel judgement can decide them correctly without reconstructing
the whole set; that reconstruction is exactly the structural judgement whose
gap produced the fourth escape. So they are declared always-rebuilt. This costs
rebuild work on every change and it is the honest price of alignment for that
class. A heuristic that usually agreed is the bug being fixed here, not an
alternative to this.

**Fingerprint is a pure function of (kind, representation).** Never of witness
byte offsets, never of surrounding text, never of dict insertion order — it
goes through `ir.canonical_json` so the system has exactly one serialization.
A fact that moved in the file without changing value has the same fingerprint
and a different `fact_id`; a fact whose value changed has the same `fact_id`
and a different fingerprint. That is what lets `delta` report a *change* rather
than a disappearance plus an arrival.

**What the invariant cannot guarantee.** It compares the delta against the
artifact maps it is handed. It is therefore only as complete as fact
extraction: an artifact that moves because of a source construct no extractor
produced a fact for is invisible to the delta *and* to this check, and will be
reported as an alignment violation only if the caller supplies a clean-rebuild
artifact map that actually contains it. It closes the gap between the diff and
the fingerprint. It does not close the gap between the source and the facts —
that is what `ir.unclaimed_kinds()` and the fail-closed states are for.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from source_fact_ir import ir

SCHEMA = "tavonel.v2.source_fact_ir.fingerprint.v1"


# ---------------------------------------------------------------------------
# artifact key shapes
#
# Mirrored from compiler/selective_build.py rather than imported: that module
# pulls in akc_cir and rewrites sys.path at import time, and link 4 of the chain
# must be resolvable without standing up the production recompiler. The
# duplication is a real risk and is named as one — `test_sfi_fingerprint.py`
# pins the shapes, and a change to the artifact spec must move both files.

#: selective_build.bucket_of hashes into `range(4)`. Declared, not inferred.
BUCKET_COUNT = 4

UNIT = "UNIT"
MEMBERSHIP = "MEMBERSHIP"

ARTIFACT_CLASSES: tuple[str, ...] = (UNIT, MEMBERSHIP)

SECTION_PREFIX = "section:"
DOCUMENT_INDEX_PREFIX = "document-index:"
STRUCTURE_MAP_PREFIX = "structure-map:"
TOPIC_BUCKET_PREFIX = "topic-bucket:"

#: The classes whose value is a function of the whole unit set. These are the
#: always-rebuilt classes; see the module docstring.
MEMBERSHIP_PREFIXES: tuple[str, ...] = (
    DOCUMENT_INDEX_PREFIX,
    STRUCTURE_MAP_PREFIX,
    TOPIC_BUCKET_PREFIX,
)


class UnanchoredFact(ValueError):
    """A fact with no `witness.unit_path`, so link 4 cannot be resolved.

    Raised rather than returning an empty edge set: an empty invalidation path
    and an unresolvable one are different conditions, and collapsing them is
    how an unanchored fact would quietly invalidate nothing.
    """


def unit_key(source_id: str, explicit_path: Iterable[str]) -> str:
    joined = source_id + "\n" + "/".join(explicit_path)
    return "u:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]


def document_key(source_id: str) -> str:
    return hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:16]


def bucket_of(unit_identifier: str) -> int:
    return (
        int(hashlib.sha256(unit_identifier.encode("utf-8")).hexdigest()[:8], 16) % BUCKET_COUNT
    )


def anchor(fact: ir.SourceFact) -> tuple[str, str | None]:
    """(document key, unit key or None) for one fact.

    `witness.unit_path` is `(source_id, *explicit_path)` — the same shape
    `selective_build.snapshots` puts in `UnitSnapshot.document_path`. A path of
    length 1 anchors the fact to the document but to no unit, which is a real
    case (a document-level LANGUAGE or AUTHORITY fact) and not an error.
    """
    path = fact.witness.unit_path
    if not path:
        raise UnanchoredFact(
            f"{fact.kind} fact at byte {fact.witness.byte_start} has no witness.unit_path, so "
            "no artifact key can be derived for it and nothing downstream can be told to rebuild"
        )
    source_id = path[0]
    explicit = path[1:]
    return document_key(source_id), unit_key(source_id, explicit) if explicit else None


def membership_keys(doc: str) -> tuple[str, ...]:
    """Every derived-membership artifact of one document.

    All `BUCKET_COUNT` topic buckets are emitted even though a revision may not
    populate them all. Naming a key that does not exist is over-invalidation and
    is safe; discovering which buckets exist would require the unit set, which
    is the reconstruction this class is declared always-rebuilt to avoid.
    """
    return (
        DOCUMENT_INDEX_PREFIX + doc,
        STRUCTURE_MAP_PREFIX + doc,
        *(f"{TOPIC_BUCKET_PREFIX}{doc}:{index}" for index in range(BUCKET_COUNT)),
    )


# ---------------------------------------------------------------------------
# link 3 — fingerprint


def fingerprint(fact: ir.SourceFact) -> str:
    """A stable digest of the fact's canonical representation.

    Deliberately excludes the witness. Two facts with the same kind and the same
    representation seen at different byte offsets are the same value, and a
    fingerprint that moved because the file grew a paragraph above would
    re-introduce exactly the false-positive half of the alignment failure.
    """
    return ir.digest({"kind": fact.kind, "representation": fact.representation})


# ---------------------------------------------------------------------------
# link 4 — the typed invalidation path
#
# The channel decides which artifact classes a change to the fact reaches. Every
# channel reaches UNIT: each declared kind's representation participates in what
# the unit compiles to, and REFERENTIAL is listed here explicitly rather than by
# accident — a reference whose target moved leaves the unit's text byte-identical
# and must still invalidate the unit's artifact. That case is INC-V2-006 and
# three of the four confirmed escapes.
#
# Every channel also reaches MEMBERSHIP, by the declared conservative rebuild.

CHANNEL_ARTIFACT_CLASSES: dict[str, frozenset[str]] = {
    ir.SEMANTIC: frozenset({UNIT, MEMBERSHIP}),
    ir.STRUCTURAL: frozenset({UNIT, MEMBERSHIP}),
    ir.REFERENTIAL: frozenset({UNIT, MEMBERSHIP}),
    ir.TEMPORAL: frozenset({UNIT, MEMBERSHIP}),
    ir.DESCRIPTIVE: frozenset({UNIT, MEMBERSHIP}),
}


@dataclass(frozen=True)
class DependencyEdge:
    """One typed edge: this fact, on this channel, reaches this artifact key."""

    fact_id: str
    kind: str
    channel: str
    artifact_class: str
    artifact_key: str


def dependency_edges(fact: ir.SourceFact) -> tuple[DependencyEdge, ...]:
    doc, unit = anchor(fact)
    channel = fact.channel
    classes = CHANNEL_ARTIFACT_CLASSES.get(channel)
    if classes is None:
        raise ValueError(
            f"channel {channel!r} has no declared artifact classes; a channel that reaches "
            "nothing cannot be distinguished from a fact nobody typed"
        )
    edges: list[DependencyEdge] = []
    if UNIT in classes and unit is not None:
        edges.append(
            DependencyEdge(fact.fact_id, fact.kind, channel, UNIT, SECTION_PREFIX + unit)
        )
    if MEMBERSHIP in classes:
        edges.extend(
            DependencyEdge(fact.fact_id, fact.kind, channel, MEMBERSHIP, key)
            for key in membership_keys(doc)
        )
    return tuple(edges)


def dependency_keys(fact: ir.SourceFact) -> tuple[str, ...]:
    """The downstream artifact keys a change to this fact must invalidate."""
    return tuple(sorted({edge.artifact_key for edge in dependency_edges(fact)}))


# ---------------------------------------------------------------------------
# the typed delta


@dataclass(frozen=True)
class FactChange:
    """One fact's movement between two revisions, with its invalidation path."""

    fact_id: str
    kind: str
    channel: str
    state_before: str | None
    state_after: str | None
    fingerprint_before: str | None
    fingerprint_after: str | None
    dependency_keys: tuple[str, ...]


@dataclass(frozen=True)
class TypedDelta:
    added: tuple[FactChange, ...]
    removed: tuple[FactChange, ...]
    changed: tuple[FactChange, ...]
    unchanged: tuple[FactChange, ...]
    invalidate: tuple[str, ...]

    @property
    def moved(self) -> tuple[FactChange, ...]:
        return (*self.added, *self.removed, *self.changed)

    @property
    def is_empty(self) -> bool:
        return not self.moved


def _signature(fact: ir.SourceFact) -> tuple[str, str]:
    """What "the same fact, unchanged" means.

    State is part of it: a fact that fell from REPRESENTED to
    RECOGNIZED_BUT_UNREPRESENTED changed, even though its (absent)
    representation fingerprints identically both times.
    """
    return fact.state, fingerprint(fact)


def _by_id(facts: Iterable[ir.SourceFact]) -> dict[str, ir.SourceFact]:
    indexed: dict[str, ir.SourceFact] = {}
    for fact in facts:
        existing = indexed.get(fact.fact_id)
        if existing is not None and _signature(existing) != _signature(fact):
            raise ValueError(
                f"two different {fact.kind} facts share fact_id {fact.fact_id[:19]}; identity is "
                "witness+kind derived, so this means one witness produced two representations"
            )
        indexed[fact.fact_id] = fact
    return indexed


def _unit_order(facts: Mapping[str, ir.SourceFact]) -> dict[str, tuple[str, ...]]:
    """Per document, the ordered unit keys the fact set witnesses.

    Read in source order — facts are keyed by a witness byte offset, so sorting
    by it recovers document order without consulting the document.
    """
    ordered: dict[str, list[str]] = {}
    for fact in sorted(facts.values(), key=lambda item: item.witness.byte_start):
        doc, unit = anchor(fact)
        seen = ordered.setdefault(doc, [])
        if unit is not None and unit not in seen:
            seen.append(unit)
    return {doc: tuple(units) for doc, units in ordered.items()}


def _change(
    before: ir.SourceFact | None, after: ir.SourceFact | None
) -> FactChange:
    present = after if after is not None else before
    assert present is not None  # one of the two is always given
    return FactChange(
        fact_id=present.fact_id,
        kind=present.kind,
        channel=present.channel,
        state_before=before.state if before is not None else None,
        state_after=after.state if after is not None else None,
        fingerprint_before=fingerprint(before) if before is not None else None,
        fingerprint_after=fingerprint(after) if after is not None else None,
        dependency_keys=dependency_keys(present),
    )


def delta(before: list[ir.SourceFact], after: list[ir.SourceFact]) -> TypedDelta:
    """Match by `fact_id`, classify, and union the invalidation paths.

    Identity is witness+kind derived and deliberately not value derived, so a
    changed value is the same fact with a new fingerprint — reported as
    `changed`, never as a removal plus an addition. Downstream needs to be told
    *which artifact to rebuild*, and a disappearance names no artifact.
    """
    before_by_id = _by_id(before)
    after_by_id = _by_id(after)

    added: list[FactChange] = []
    removed: list[FactChange] = []
    changed: list[FactChange] = []
    unchanged: list[FactChange] = []

    for fact_id in sorted(set(before_by_id) | set(after_by_id)):
        prior = before_by_id.get(fact_id)
        current = after_by_id.get(fact_id)
        if prior is None:
            added.append(_change(None, current))
        elif current is None:
            removed.append(_change(prior, None))
        elif _signature(prior) != _signature(current):
            changed.append(_change(prior, current))
        else:
            unchanged.append(_change(prior, current))

    invalidate: set[str] = set()
    touched_documents: set[str] = set()
    for entry in (*added, *removed, *changed):
        invalidate.update(entry.dependency_keys)
        witness = after_by_id.get(entry.fact_id) or before_by_id[entry.fact_id]
        touched_documents.add(anchor(witness)[0])

    # The declared conservative rebuild. Also fires where the unit set or its
    # order moved without any individual fact being judged structural — the
    # fourth confirmed escape was exactly that: membership decided from a
    # structural verdict instead of from membership.
    before_order = _unit_order(before_by_id)
    after_order = _unit_order(after_by_id)
    for doc in set(before_order) | set(after_order):
        if before_order.get(doc) != after_order.get(doc):
            touched_documents.add(doc)
    for doc in touched_documents:
        invalidate.update(membership_keys(doc))

    return TypedDelta(
        added=tuple(added),
        removed=tuple(removed),
        changed=tuple(changed),
        unchanged=tuple(unchanged),
        invalidate=tuple(sorted(invalidate)),
    )


# ---------------------------------------------------------------------------
# the alignment invariant


@dataclass(frozen=True)
class AlignmentReport:
    """What the delta named, what the clean rebuilds actually moved, and the gap.

    `under_invalidated` and `silent_facts` are violations. `over_invalidated` is
    not: naming an artifact that did not move costs a rebuild, and the whole
    finding is that the cheap direction is the unsafe one.
    """

    moved: tuple[str, ...]
    invalidated: tuple[str, ...]
    under_invalidated: tuple[str, ...]
    over_invalidated: tuple[str, ...]
    silent_facts: tuple[str, ...]

    @property
    def is_aligned(self) -> bool:
        return not self.under_invalidated and not self.silent_facts

    def describe(self) -> str:
        parts: list[str] = []
        if self.under_invalidated:
            parts.append(
                f"{len(self.under_invalidated)} artifact(s) moved without being named: "
                + ", ".join(self.under_invalidated[:5])
            )
        if self.silent_facts:
            parts.append(
                f"{len(self.silent_facts)} moved fact(s) invalidate nothing: "
                + ", ".join(item[:19] for item in self.silent_facts[:5])
            )
        return "; ".join(parts) if parts else "aligned"


def moved_artifacts(
    before_artifacts: Mapping[str, str], after_artifacts: Mapping[str, str]
) -> tuple[str, ...]:
    """Keys whose clean-rebuild value differs, appearance and retirement included.

    A key present in only one revision counts as moved: an artifact that came
    into existence is exactly the `MISSING_NOT_PLANNED_AND_NO_PRIOR_VALUE` case
    the selective path records, and it has no prior value to carry forward.
    """
    return tuple(
        sorted(
            key
            for key in set(before_artifacts) | set(after_artifacts)
            if before_artifacts.get(key) != after_artifacts.get(key)
        )
    )


def aligned(
    before_facts: list[ir.SourceFact],
    after_facts: list[ir.SourceFact],
    before_artifacts: Mapping[str, str],
    after_artifacts: Mapping[str, str],
) -> AlignmentReport:
    """Compare the typed delta against two clean rebuilds. Report, do not decide.

    `before_artifacts` and `after_artifacts` must be *clean full rebuilds* of
    the two revisions. Handing this a selectively built map would compare the
    selective path against itself and pass by construction.
    """
    typed = delta(before_facts, after_facts)
    moved = set(moved_artifacts(before_artifacts, after_artifacts))
    named = set(typed.invalidate)
    silent = tuple(
        entry.fact_id for entry in typed.moved if not entry.dependency_keys
    )
    return AlignmentReport(
        moved=tuple(sorted(moved)),
        invalidated=typed.invalidate,
        under_invalidated=tuple(sorted(moved - named)),
        over_invalidated=tuple(sorted(named - moved)),
        silent_facts=tuple(sorted(silent)),
    )


def assert_aligned(
    before_facts: list[ir.SourceFact],
    after_facts: list[ir.SourceFact],
    before_artifacts: Mapping[str, str],
    after_artifacts: Mapping[str, str],
    *,
    scope: str = "the selective state",
) -> AlignmentReport:
    """Fail closed on an alignment violation, naming the artifacts.

    Raises rather than returning False for the reason `ir.NotSourceFaithful`
    exists: an under-invalidated artifact returned as a quiet False into an `if`
    nobody wrote is a stale escape with extra steps.
    """
    report = aligned(before_facts, after_facts, before_artifacts, after_artifacts)
    if not report.is_aligned:
        raise ir.NotSourceFaithful(f"{scope} is not alignment-safe: {report.describe()}")
    return report
