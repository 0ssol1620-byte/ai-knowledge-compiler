"""Compose one revision compile: an active world, a revised source, a candidate.

Every part this needs already exists and is tested. `identity` decides whether a
unit in the new version continues one from the old. `semantic_diff` types what
changed. `dependency` says what reads what. `recompilation` turns that into a
plan and can check a rebuild against a full one. `world_state` owns the
candidate/active lifecycle. What did not exist is the **composition**: one entry
point that runs them in the order a production revision actually needs, refuses
to activate on anything it cannot account for, and emits a receipt a product
boundary can verify without re-deriving any of it.

`revision_resolution` is the narrow sibling of this module and stays as it is.
It recomputes authority/applicability/valid-time for one governed subject. This
module compiles a whole revision.

Three rules shape the code, and they are the ones that are easy to get wrong.

**Identity continuity is not change equivalence.** `I(x_t, x_t+1)` asks whether
this is the same logical unit as before. `E(x_t, x_t+1)` asks whether what it
says has materially changed. They are different questions, they take different
inputs, and folding them onto one fingerprint is how a real edit disappears: the
normalisation that lets a clause keep its identity through a re-typeset will
also, if reused, report a re-typeset clause whose numbers changed as unchanged.
So this module computes two fingerprints from **disjoint** projections and says
so in `FINGERPRINT_INPUTS`; `assert_fingerprints_separated` is the check, and
`identity_fingerprint`/`change_fingerprint` are the two functions. A unit may be
`CONTINUED` and `SEMANTIC` at the same time. That pair is the normal case for an
amended clause, not a contradiction.

**An unaccounted change channel is a defect, not a silence.** Every typed change
the diff produced is assigned to a channel and every channel resolves to a
disposition. A channel this module does not know how to route does not fall
through to "nothing reached it" -- it lands in `unresolved_channels` and the
candidate cannot be `PROMOTABLE`.

**Only a predeclared IGNORE fails open.** A source fact that the compiled state
recognised but does not represent, and one that could not be resolved at all,
both block source-faithful CURRENT. That is `FAIL_CLOSED_SOURCE_FACT_STATES`,
and it is the whole reason `43 pairs selective == full` was not the result it
looked like: two builds agreeing tells you nothing about whether either of them
carried the source.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .dependency import DependencyGraph
from .identity import (
    LogicalIdentityResolver,
    LogicalMatch,
    LogicalRelation,
    normalize_text_for_identity,
)
from .recompilation import (
    ArtifactState,
    RecompilationPlan,
    StructuralPolicy,
    plan_recompilation,
)
from .semantic_diff import (
    ChangeChannel,
    ChangeKind,
    DiffLevel,
    DocumentShape,
    SemanticDiff,
    UnitSnapshot,
    diff_documents,
)

__all__ = [
    "CANDIDATE_BLOCKING_CHANGE_STATES",
    "FAIL_CLOSED_SOURCE_FACT_STATES",
    "FINGERPRINT_INPUTS",
    "SCHEMA",
    "ChangeState",
    "IdentityContinuity",
    "PriorWorld",
    "RevisionCompileResult",
    "RevisionDisposition",
    "SourceFact",
    "SourceFactAudit",
    "SourceFactState",
    "UnitRevisionRecord",
    "assert_fingerprints_separated",
    "change_fingerprint",
    "compile_revision",
    "identity_fingerprint",
]

SCHEMA = "tavonel.core.revision_compile.v1"


# ---------------------------------------------------------------------------
# identity continuity -- I(x_t, x_t+1)


class IdentityContinuity(StrEnum):
    """What the identity layer concluded about one unit's lineage.

    Four values, not three: `AMBIGUOUS` and `UNRESOLVED` are different findings.
    Ambiguous means the resolver scored candidates and none cleared the bar --
    there is a shortlist. Unresolved means it could not score at all, because a
    critical signal had no value. Collapsing them loses the shortlist, which is
    the only thing that makes an ambiguous decision reviewable.
    """

    CONTINUED = "continued"
    NEW = "new"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


#: Continuity states that cannot silently carry a prior artifact forward. A unit
#: whose lineage is undecided has no prior value that is known to be its own.
UNSETTLED_CONTINUITY = frozenset(
    {IdentityContinuity.AMBIGUOUS, IdentityContinuity.UNRESOLVED}
)


# ---------------------------------------------------------------------------
# change equivalence -- E(x_t, x_t+1)


class ChangeState(StrEnum):
    """What materially changed about a unit, independently of its lineage.

    One value per `ChangeChannel` the diff can emit, plus `UNCHANGED`. The
    mapping is total by construction (`_CHANNEL_STATE` is checked against the
    enum at import), so a channel added to `semantic_diff` later cannot arrive
    here as a silent `UNCHANGED`.
    """

    UNCHANGED = "unchanged"
    SEMANTIC = "semantic"
    STRUCTURAL = "structural"
    GRAPH = "graph"
    TEMPORAL = "temporal"
    AUTHORITY = "authority"
    LOCATOR = "locator"
    METADATA = "metadata"
    VISUAL = "visual"
    UNRESOLVED = "unresolved"


_CHANNEL_STATE: dict[ChangeChannel, ChangeState] = {
    ChangeChannel.UNCHANGED: ChangeState.UNCHANGED,
    ChangeChannel.SEMANTIC: ChangeState.SEMANTIC,
    ChangeChannel.STRUCTURAL: ChangeState.STRUCTURAL,
    ChangeChannel.GRAPH: ChangeState.GRAPH,
    ChangeChannel.TEMPORAL: ChangeState.TEMPORAL,
    ChangeChannel.LOCATOR: ChangeState.LOCATOR,
    ChangeChannel.METADATA: ChangeState.METADATA,
    ChangeChannel.VISUAL: ChangeState.VISUAL,
    ChangeChannel.UNRESOLVED: ChangeState.UNRESOLVED,
}

# `AUTHORITY_CHANGED` is a ChangeKind on the GRAPH channel in `semantic_diff`;
# the product contract needs it named separately because an authority change and
# a relationship change have different review consequences. The kind, not the
# channel, decides -- so this is a kind-level override rather than a second
# channel that would have to be kept in step with the diff module.
_KIND_STATE_OVERRIDE: dict[ChangeKind, ChangeState] = {
    ChangeKind.AUTHORITY_CHANGED: ChangeState.AUTHORITY,
}

if set(_CHANNEL_STATE) != set(ChangeChannel):  # pragma: no cover - import guard
    missing = sorted(set(ChangeChannel) - set(_CHANNEL_STATE))
    raise RuntimeError(f"revision_compile does not route change channels: {missing}")


#: Ordering used when one unit carries changes on several channels. The most
#: consequential wins, so a clause that both moved and was reworded is reported
#: SEMANTIC rather than LOCATOR. Recording only the strongest is a summary, not a
#: loss: `UnitRevisionRecord.change_states` keeps every channel that fired.
_STATE_RANK: tuple[ChangeState, ...] = (
    ChangeState.UNRESOLVED,
    ChangeState.SEMANTIC,
    ChangeState.AUTHORITY,
    ChangeState.GRAPH,
    ChangeState.STRUCTURAL,
    ChangeState.TEMPORAL,
    ChangeState.METADATA,
    ChangeState.LOCATOR,
    ChangeState.VISUAL,
    ChangeState.UNCHANGED,
)


#: Change states that block an automatic promotable disposition on their own.
#: An unresolved change is a change nobody typed; activating a world over one
#: asserts a completeness that was never established.
CANDIDATE_BLOCKING_CHANGE_STATES = frozenset({ChangeState.UNRESOLVED})


# ---------------------------------------------------------------------------
# the two fingerprints, and the proof that they are not the same fingerprint


#: What each fingerprint is allowed to read. Disjoint by construction, and
#: asserted at import. This is the machine-readable form of "identity continuity
#: is not change equivalence": if the two ever share an input, the assertion
#: below fails and the module refuses to load.
FINGERPRINT_INPUTS: dict[str, tuple[str, ...]] = {
    "identity": (
        "normalized_text",
        "document_path",
        "anchor",
        "explicit_identifier",
        "geometry_style",
    ),
    "change": (
        "raw_text",
        "entities",
        "relationships",
        "authority",
        "temporal_fingerprint",
        "metadata_fingerprint",
        "visual_fingerprint",
        "evidence_id",
        "page_number1",
    ),
}

_shared_inputs = set(FINGERPRINT_INPUTS["identity"]) & set(FINGERPRINT_INPUTS["change"])
if _shared_inputs:  # pragma: no cover - import guard
    raise RuntimeError(
        "identity and change fingerprints must read disjoint inputs; shared: "
        f"{sorted(_shared_inputs)}"
    )


def _digest(prefix: str, payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return f"{prefix}_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def identity_fingerprint(unit: UnitSnapshot) -> str:
    """`I` -- what makes this the same logical unit as before.

    Reads the identity-normalised text, because a clause that was re-typeset,
    re-cased or re-punctuated is still that clause. Deliberately excludes page
    number, evidence occurrence and every facet fingerprint: those move freely
    between versions and a unit that moved down a page is not a new unit.
    """
    return _digest(
        "idf",
        {
            "normalized_text": normalize_text_for_identity(unit.text),
            "document_path": list(unit.document_path),
            "anchor": normalize_text_for_identity(unit.anchor),
            "explicit_identifier": normalize_text_for_identity(
                unit.explicit_identifier
            ),
            "geometry_style": unit.geometry_style,
        },
    )


def change_fingerprint(unit: UnitSnapshot) -> str:
    """`E` -- what makes this materially different from before.

    Reads the **raw** text. Not the identity fold. This is the entire point: a
    fold that treats `30 days` and `30 Days` as the same unit is correct for
    identity and catastrophic for change detection the moment the fold reaches
    anything that carries meaning. Nothing here is normalised, and the facet
    fingerprints the document declared are included so a change that lives in a
    facet rather than in prose is still a change.
    """
    return _digest(
        "chf",
        {
            "raw_text": unit.text,
            "entities": sorted(unit.entities),
            "relationships": sorted(
                [list(item) for item in unit.relationships], key=repr
            ),
            "authority": unit.authority,
            "temporal_fingerprint": unit.temporal_fingerprint,
            "metadata_fingerprint": unit.metadata_fingerprint,
            "visual_fingerprint": unit.visual_fingerprint,
            "evidence_id": unit.evidence_id,
            "page_number1": unit.page_number1,
        },
    )


def assert_fingerprints_separated(before: UnitSnapshot, after: UnitSnapshot) -> None:
    """Refuse the one pairing that would mean the separation collapsed.

    If two versions of a unit are identity-identical, that is normal and says
    nothing. If they are change-identical, that is normal too. The failure this
    guards is a *change* fingerprint that agreed only because it was computed
    from the identity fold: raw texts differ, and the change fingerprint does
    not. That combination cannot occur while `change_fingerprint` reads
    `raw_text`, and asserting it here turns a future refactor that reintroduces
    the fold into a failure at the seam rather than a stale answer in a world.
    """
    if before.text == after.text:
        return
    if change_fingerprint(before) == change_fingerprint(after):
        raise AssertionError(
            "change fingerprint collapsed a raw-text difference; identity "
            "normalisation has leaked into change equivalence "
            f"(logical_id={after.logical_id!r})"
        )


# ---------------------------------------------------------------------------
# source facts


class SourceFactState(StrEnum):
    """The four states, with the strings SOURCE_FACT_IR_V1 already uses.

    Kept here rather than imported so `akc_cir` does not depend on the research
    harness -- the dependency runs the other way. The values are pinned to the
    research vocabulary on purpose: a record produced by
    `research/tavonel_eval_v2/source_fact_ir/ir.py` is readable here without a
    translation table, and a translation table is where two vocabularies drift.
    """

    REPRESENTED = "REPRESENTED_IN_COMPILED_STATE"
    UNREPRESENTED = "RECOGNIZED_BUT_UNREPRESENTED"
    IGNORED = "IGNORED_BY_PREDECLARED_POLICY"
    UNRESOLVED = "UNRESOLVED_SOURCE_FACT"


#: The states that forbid "source-faithful CURRENT". `IGNORED` is absent because
#: a loss declined in advance, by a policy that existed before the run, is a
#: declared limitation rather than a silent drop. It is the only fail-open state.
FAIL_CLOSED_SOURCE_FACT_STATES = frozenset(
    {SourceFactState.UNREPRESENTED, SourceFactState.UNRESOLVED}
)


@dataclass(frozen=True, slots=True)
class SourceFact:
    """One fact the source carried, and what the compiled state did with it."""

    fact_id: str
    kind: str
    state: SourceFactState
    #: Required when the state is IGNORED. A policy named after the fact is not
    #: a predeclared policy, so the caller supplies the identifier it declared.
    policy_id: str = ""
    #: Required when the state is fail-closed. A bare "unresolved" is
    #: indistinguishable from a bug.
    reason: str = ""
    logical_id: str | None = None

    def validate(self) -> None:
        if self.state is SourceFactState.IGNORED and not self.policy_id:
            raise ValueError(
                f"{self.fact_id}: IGNORED_BY_PREDECLARED_POLICY needs a policy id"
            )
        if self.state in FAIL_CLOSED_SOURCE_FACT_STATES and not self.reason:
            raise ValueError(f"{self.fact_id}: {self.state.value} needs a reason")


@dataclass(frozen=True, slots=True)
class SourceFactAudit:
    """The tally, and whether it permits a source-faithful CURRENT."""

    tally: dict[str, int]
    fail_closed: tuple[str, ...]
    ignored_policies: tuple[str, ...]

    @property
    def total(self) -> int:
        return sum(self.tally.values())

    @property
    def source_faithful(self) -> bool:
        return not self.fail_closed

    @property
    def coverage(self) -> float:
        """Represented share of everything that was not declined in advance.

        Facts declined by a predeclared policy leave the denominator: including
        them would let a broad IGNORE policy raise coverage, which is exactly
        backwards.
        """
        considered = self.total - self.tally.get(SourceFactState.IGNORED.value, 0)
        if considered <= 0:
            return 1.0
        return self.tally.get(SourceFactState.REPRESENTED.value, 0) / considered

    def as_record(self) -> dict[str, object]:
        return {
            "tally": dict(sorted(self.tally.items())),
            "total": self.total,
            "coverage": round(self.coverage, 6),
            "source_faithful": self.source_faithful,
            "fail_closed": list(self.fail_closed),
            "ignored_policies": list(self.ignored_policies),
        }


def audit_source_facts(facts: Iterable[SourceFact]) -> SourceFactAudit:
    tally: dict[str, int] = {state.value: 0 for state in SourceFactState}
    blocking: list[str] = []
    policies: set[str] = set()
    for fact in facts:
        fact.validate()
        tally[fact.state.value] += 1
        if fact.state in FAIL_CLOSED_SOURCE_FACT_STATES:
            blocking.append(fact.fact_id)
        elif fact.state is SourceFactState.IGNORED:
            policies.add(fact.policy_id)
    return SourceFactAudit(
        tally=tally,
        fail_closed=tuple(sorted(blocking)),
        ignored_policies=tuple(sorted(policies)),
    )


# ---------------------------------------------------------------------------
# per-unit record


@dataclass(frozen=True, slots=True)
class UnitRevisionRecord:
    """One unit, its lineage and its material change -- kept apart on purpose."""

    logical_unit_id: str
    continuity: IdentityContinuity
    previous_logical_unit_id: str | None
    relation: LogicalRelation | None
    identity_fingerprint: str
    change_fingerprint: str
    change_state: ChangeState
    change_states: tuple[ChangeState, ...]
    identity_candidates: tuple[str, ...] = ()
    reason: str = ""

    @property
    def continued_and_changed(self) -> bool:
        """The case the whole separation exists for.

        Same clause, different obligation. Any implementation that reports this
        as `unchanged` has folded `E` into `I`.
        """
        return (
            self.continuity is IdentityContinuity.CONTINUED
            and self.change_state is not ChangeState.UNCHANGED
        )

    def as_record(self) -> dict[str, object]:
        record: dict[str, object] = {
            "logicalUnitId": self.logical_unit_id,
            "identityContinuity": self.continuity.value,
            "changeState": self.change_state.value,
            "changeStates": [state.value for state in self.change_states],
            "identityFingerprint": self.identity_fingerprint,
            "changeFingerprint": self.change_fingerprint,
        }
        if self.previous_logical_unit_id:
            record["previousLogicalUnitId"] = self.previous_logical_unit_id
        if self.relation is not None:
            record["identityRelation"] = self.relation.value
        if self.identity_candidates:
            record["identityCandidates"] = list(self.identity_candidates)
        if self.reason:
            record["identityReason"] = self.reason
        return record


# ---------------------------------------------------------------------------
# prior world


@dataclass(frozen=True, slots=True)
class PriorWorld:
    """The v1 side of the revision, bound by digest rather than by name.

    A revision that names its predecessor by id alone can be replayed against a
    world that has since been superseded. The manifest digest is what makes the
    binding checkable, and `artifact_digests` is what makes a carried-forward
    value verifiable rather than assumed.
    """

    world_state_id: str
    manifest_digest: str
    artifact_digests: Mapping[str, str]
    source_sha256: str
    units: Sequence[UnitSnapshot] = ()
    shape: DocumentShape | None = None


class RevisionDisposition(StrEnum):
    """What this revision may become.

    `PROMOTABLE` is the only value that permits a human to be offered an
    activation. It is never reached by default: every gate below has to have
    been checked and passed.
    """

    PROMOTABLE = "promotable"
    REVIEW_REQUIRED = "review_required"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class RevisionCompileResult:
    schema: str
    change_id: str
    previous_world_state_id: str
    previous_manifest_digest: str
    diff: SemanticDiff
    plan: RecompilationPlan
    units: tuple[UnitRevisionRecord, ...]
    source_facts: SourceFactAudit
    rebuilt_artifact_ids: tuple[str, ...]
    carried_forward_artifact_ids: tuple[str, ...]
    quarantined_artifact_ids: tuple[str, ...]
    unnecessary_rebuild_artifact_ids: tuple[str, ...]
    unresolved_channels: tuple[ChangeState, ...]
    equivalence: str
    equivalence_divergent_artifact_ids: tuple[str, ...]
    disposition: RevisionDisposition
    review_reasons: tuple[str, ...]
    state: Mapping[str, str]
    state_digest: str

    @property
    def total_artifacts(self) -> int:
        return (
            len(self.rebuilt_artifact_ids)
            + len(self.carried_forward_artifact_ids)
            + len(self.quarantined_artifact_ids)
        )

    @property
    def work_avoided_artifacts(self) -> int:
        """Kept as `total - rebuilt`, which is the product's stored invariant.

        Quarantined artifacts are not rebuilt and are not avoided work either --
        they were withheld. They stay inside `total` so the arithmetic the
        product already verifies keeps holding, and they are listed separately so
        a withheld artifact is never read as a saving.
        """
        return self.total_artifacts - len(self.rebuilt_artifact_ids)

    def as_record(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "changeId": self.change_id,
            "previousWorldStateId": self.previous_world_state_id,
            "previousManifestDigest": self.previous_manifest_digest,
            "identity": {
                "continued": sum(
                    1
                    for unit in self.units
                    if unit.continuity is IdentityContinuity.CONTINUED
                ),
                "new": sum(
                    1 for unit in self.units if unit.continuity is IdentityContinuity.NEW
                ),
                "ambiguous": sum(
                    1
                    for unit in self.units
                    if unit.continuity is IdentityContinuity.AMBIGUOUS
                ),
                "unresolved": sum(
                    1
                    for unit in self.units
                    if unit.continuity is IdentityContinuity.UNRESOLVED
                ),
                "units": [unit.as_record() for unit in self.units],
            },
            "typedChanges": _typed_change_record(self.diff),
            "impact": {
                "affectedArtifactIds": list(self.plan.stale),
                "unresolvedArtifactIds": list(self.plan.unresolved),
                "facetResolutions": [
                    item.as_record() for item in self.plan.facet_resolutions
                ],
            },
            "recompilation": {
                "totalArtifacts": self.total_artifacts,
                "rebuiltArtifacts": len(self.rebuilt_artifact_ids),
                "workAvoidedArtifacts": self.work_avoided_artifacts,
                "rebuiltArtifactIds": list(self.rebuilt_artifact_ids),
                "carriedForwardArtifactIds": list(self.carried_forward_artifact_ids),
                "quarantinedArtifactIds": list(self.quarantined_artifact_ids),
                "unnecessaryRebuildArtifactIds": list(
                    self.unnecessary_rebuild_artifact_ids
                ),
            },
            "sourceFacts": self.source_facts.as_record(),
            "unresolvedChannels": [state.value for state in self.unresolved_channels],
            "equivalence": self.equivalence,
            "equivalenceDivergentArtifactIds": list(
                self.equivalence_divergent_artifact_ids
            ),
            "disposition": self.disposition.value,
            "reviewReasons": list(self.review_reasons),
            "stateDigest": self.state_digest,
        }


def _typed_change_record(diff: SemanticDiff) -> dict[str, list[dict[str, object]]]:
    """Group the diff's changes by the state the product contract names.

    Every change lands in exactly one bucket and no bucket is synthesised, so a
    caller can add the counts and get the change count back.
    """
    grouped: dict[str, list[dict[str, object]]] = {}
    for change in diff.changes:
        state = _KIND_STATE_OVERRIDE.get(change.kind) or _CHANNEL_STATE[change.channel]
        grouped.setdefault(state.value, []).append(change.as_record())
    return grouped


def _strongest(states: Iterable[ChangeState]) -> ChangeState:
    present = set(states)
    for candidate in _STATE_RANK:
        if candidate in present:
            return candidate
    return ChangeState.UNCHANGED


def _continuity_of(match: LogicalMatch, has_candidates: bool) -> IdentityContinuity:
    if match is LogicalMatch.MATCHED:
        return IdentityContinuity.CONTINUED
    if match is LogicalMatch.NEW:
        return IdentityContinuity.NEW
    return (
        IdentityContinuity.AMBIGUOUS if has_candidates else IdentityContinuity.UNRESOLVED
    )


def compile_revision(
    *,
    source_id: str,
    previous: PriorWorld,
    after_units: Sequence[UnitSnapshot],
    after_shape: DocumentShape,
    after_sha256: str,
    graph: DependencyGraph,
    artifacts: Sequence[str],
    build: Callable[[str], str],
    source_facts: Sequence[SourceFact] = (),
    full_rebuild: Callable[[], Mapping[str, str]] | None = None,
    resolver: LogicalIdentityResolver | None = None,
    structural_policy: StructuralPolicy = StructuralPolicy.PRECISE,
    quarantine_unsettled_identity: bool = True,
) -> RevisionCompileResult:
    """Compile `previous` forward onto the revised source and stop before ACTIVE.

    `build(artifact_id)` produces the artifact's content digest from the AFTER
    revision. It is the caller's compiler; this module decides *which* artifacts
    it is called for and checks what comes back. `full_rebuild()` is the
    independent oracle, called only when supplied -- it must not share code with
    `build`, or the equivalence it reports is a function comparing itself.

    Nothing here activates a world. The result carries a disposition and the
    reasons behind it; promotion stays an explicit human decision on the product
    side, which is where it has always been.
    """
    if previous.shape is None:
        raise ValueError("a revision needs the prior version's DocumentShape")

    diff = diff_documents(
        before_sha256=previous.source_sha256,
        after_sha256=after_sha256,
        level=DiffLevel.SEMANTIC,
        before_shape=previous.shape,
        after_shape=after_shape,
        before_units=previous.units,
        after_units=after_units,
        resolver=resolver,
        source=source_id,
        quarantine_unsettled_identity=quarantine_unsettled_identity,
    )

    # The separation, checked on every pair the identity layer matched. This is
    # cheap and it is the invariant the paper turns on, so it runs in production
    # rather than only in a test.
    before_by_id = {unit.logical_id: unit for unit in previous.units}
    for unit in after_units:
        prior = before_by_id.get(unit.logical_id)
        if prior is not None:
            assert_fingerprints_separated(prior, unit)

    unit_records = _unit_records(diff, after_units, before_by_id, resolver)

    plan = plan_recompilation(
        diff=diff,
        graph=graph,
        artifacts=list(artifacts),
        structural_policy=structural_policy,
    )

    # Any facet the planner saw and could not route. `plan.unresolved_facet_changes`
    # is the planner's own finding; it is surfaced rather than summarised so the
    # product boundary can refuse on it.
    unresolved_channels = tuple(
        sorted(
            {
                _CHANNEL_STATE[item.change_channel]
                for item in plan.unresolved_facet_changes
            },
            key=lambda state: state.value,
        )
    )

    quarantined = tuple(
        sorted(
            {
                target.artifact_id
                for target in plan.targets
                if target.state is ArtifactState.UNRESOLVED
            }
        )
    )
    to_rebuild = list(plan.to_rebuild)

    compiled: dict[str, str] = {}
    rebuilt: list[str] = []
    carried: list[str] = []
    for artifact in sorted(artifacts):
        if artifact in to_rebuild:
            compiled[artifact] = build(artifact)
            rebuilt.append(artifact)
        elif artifact in previous.artifact_digests:
            compiled[artifact] = previous.artifact_digests[artifact]
            carried.append(artifact)
        else:
            # Planned for nothing and with no prior value. Left visibly missing
            # rather than filled in, and it blocks promotion below.
            compiled[artifact] = _MISSING
            quarantined = tuple(sorted({*quarantined, artifact}))

    equivalence = "not_run"
    divergent: tuple[str, ...] = ()
    unnecessary: tuple[str, ...] = ()
    if full_rebuild is not None:
        oracle = full_rebuild()
        mismatched = sorted(
            artifact
            for artifact in sorted(artifacts)
            if compiled.get(artifact) != oracle.get(artifact)
        )
        divergent = tuple(mismatched)
        equivalence = "passed" if not mismatched else "failed"
        # False invalidation: rebuilt, and the rebuild produced what was already
        # there. Correct but wasted, and a selective compiler that reports zero
        # stale by rebuilding everything is measured here rather than praised.
        unnecessary = tuple(
            artifact
            for artifact in rebuilt
            if artifact in previous.artifact_digests
            and previous.artifact_digests[artifact] == oracle.get(artifact)
        )

    audit = audit_source_facts(source_facts)

    review_reasons: list[str] = []
    if unresolved_channels:
        review_reasons.append(
            "unresolved change channels: "
            + ", ".join(channel.value for channel in unresolved_channels)
        )
    if quarantined:
        review_reasons.append(f"{len(quarantined)} artifact(s) quarantined")
    if not audit.source_faithful:
        review_reasons.append(
            f"{len(audit.fail_closed)} source fact(s) fail closed: "
            + ", ".join(audit.fail_closed[:5])
        )
    unsettled = [
        record.logical_unit_id
        for record in unit_records
        if record.continuity in UNSETTLED_CONTINUITY
    ]
    if unsettled:
        review_reasons.append(f"{len(unsettled)} unit identity(ies) unsettled")
    blocking_changes = sorted(
        {
            record.change_state.value
            for record in unit_records
            if record.change_state in CANDIDATE_BLOCKING_CHANGE_STATES
        }
    )
    if blocking_changes:
        review_reasons.append("untyped unit change: " + ", ".join(blocking_changes))
    if equivalence == "failed":
        review_reasons.append(
            f"full-rebuild equivalence failed on {len(divergent)} artifact(s)"
        )

    disposition = (
        RevisionDisposition.PROMOTABLE
        if not review_reasons
        else RevisionDisposition.REVIEW_REQUIRED
    )

    return RevisionCompileResult(
        schema=SCHEMA,
        change_id=diff.change_id,
        previous_world_state_id=previous.world_state_id,
        previous_manifest_digest=previous.manifest_digest,
        diff=diff,
        plan=plan,
        units=unit_records,
        source_facts=audit,
        rebuilt_artifact_ids=tuple(rebuilt),
        carried_forward_artifact_ids=tuple(carried),
        quarantined_artifact_ids=quarantined,
        unnecessary_rebuild_artifact_ids=unnecessary,
        unresolved_channels=unresolved_channels,
        equivalence=equivalence,
        equivalence_divergent_artifact_ids=divergent,
        disposition=disposition,
        review_reasons=tuple(review_reasons),
        state=compiled,
        state_digest=_digest("st", compiled),
    )


#: What a slot holds when the plan named it for nothing and no prior value
#: existed. A visible sentinel, never an empty string: an empty artifact is a
#: value and this is the absence of one.
_MISSING = "MISSING_NOT_PLANNED_AND_NO_PRIOR_VALUE"


def _unit_records(
    diff: SemanticDiff,
    after_units: Sequence[UnitSnapshot],
    before_by_id: Mapping[str, UnitSnapshot],
    resolver: LogicalIdentityResolver | None,
) -> tuple[UnitRevisionRecord, ...]:
    """Turn the diff back into one record per unit in the new version.

    The diff is authoritative for *what changed*; it is read here rather than
    recomputed, because recomputing it would be a second implementation of the
    detection step and the two would eventually disagree about the thing the
    receipt claims they agree on.
    """
    states_by_unit: dict[str, set[ChangeState]] = {}
    candidates_by_unit: dict[str, tuple[str, ...]] = {}
    reason_by_unit: dict[str, str] = {}
    for change in diff.changes:
        if not change.logical_id:
            continue
        state = _KIND_STATE_OVERRIDE.get(change.kind) or _CHANNEL_STATE[change.channel]
        states_by_unit.setdefault(change.logical_id, set()).add(state)
        if change.candidates:
            candidates_by_unit[change.logical_id] = tuple(change.candidates)
        if change.detail:
            reason_by_unit[change.logical_id] = change.detail

    added = {
        change.logical_id
        for change in diff.changes
        if change.kind is ChangeKind.UNIT_ADDED and change.logical_id
    }
    unresolved_ids = {
        change.logical_id for change in diff.unresolved if change.logical_id
    }

    records: list[UnitRevisionRecord] = []
    for unit in after_units:
        logical_id = unit.logical_id
        states = states_by_unit.get(logical_id, {ChangeState.UNCHANGED})
        candidates = candidates_by_unit.get(logical_id, ())
        if logical_id in unresolved_ids:
            match = LogicalMatch.AMBIGUOUS
        elif logical_id in added:
            match = LogicalMatch.NEW
        else:
            match = LogicalMatch.MATCHED
        continuity = _continuity_of(match, bool(candidates))
        prior = before_by_id.get(logical_id)
        records.append(
            UnitRevisionRecord(
                logical_unit_id=logical_id,
                continuity=continuity,
                previous_logical_unit_id=(
                    prior.logical_id
                    if prior is not None and continuity is IdentityContinuity.CONTINUED
                    else None
                ),
                relation=(
                    LogicalRelation.SAME_AS_VERSION
                    if continuity is IdentityContinuity.CONTINUED and prior is not None
                    else None
                ),
                identity_fingerprint=identity_fingerprint(unit),
                change_fingerprint=change_fingerprint(unit),
                change_state=_strongest(states),
                change_states=tuple(
                    sorted(states, key=lambda state: _STATE_RANK.index(state))
                ),
                identity_candidates=candidates,
                reason=reason_by_unit.get(logical_id, ""),
            )
        )
    return tuple(records)
