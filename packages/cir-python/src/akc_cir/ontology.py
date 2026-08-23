"""Ontology induction, quality gates, and the approval-gate state machine.

Implements the blueprint sections the engine gap audit flagged as missing:

- §16.3-16.5 (ontology induction + quality gates): deterministic induction of
  candidate entity/relation kinds from corpus statistics (frequency +
  co-occurrence), followed by itemized quality-gate evaluation
  (coverage / distinctiveness / stability) producing a ``GateReport``.
- §8.4 (approval gate): the six-state lifecycle
  ``DRAFT → PROPOSED → UNDER_REVIEW → APPROVED → ACTIVE → RETIRED`` with an
  explicit allowed-transition map, rejection of every transition outside the
  map, and a mandatory reviewer note guarding the APPROVED transition.

Persistence is one world-scoped JSON manifest following the local-mcp
``LocalWorldStore`` path convention (``<root>/<world_id>/ontology.json``
alongside the published ``manifest.json``/``state.json``). No database
migration is involved.

Determinism contract: every function here is a pure function of its inputs.
Wall-clock time is never read inside the module; callers supply timestamps.
The same corpus statistics, configuration, and timestamps therefore always
produce byte-identical proposals and reports.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from itertools import combinations
from math import sqrt
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator

from .base import (
    ContractModel,
    NonEmptyStr,
    Sha256,
    StableId,
    canonical_json,
    sha256_digest,
)

ONTOLOGY_MANIFEST_FILENAME = "ontology.json"
ONTOLOGY_MANIFEST_SCHEMA_VERSION = "akc.ontology-manifest-1"

INDUCTION_METHOD = "frequency_cooccurrence_v1"
RELATES_TO_KIND = "relates_to"

_FLOAT_TOLERANCE = 1e-9


class OntologyError(ValueError):
    """Base class for ontology domain errors."""


class IllegalTransitionError(OntologyError):
    """A lifecycle transition outside the §8.4 allowed-transition map."""


class MissingReviewerNoteError(OntologyError):
    """An APPROVED transition attempted without the mandatory reviewer note."""


class OntologyManifestError(OntologyError):
    """A persisted ontology manifest is missing, unreadable, or untrusted."""


class OntologyKindScope(StrEnum):
    """Which layer of the schema a kind definition belongs to."""

    ENTITY = "entity"
    RELATION = "relation"
    ATTRIBUTE = "attribute"


class GateName(StrEnum):
    """§16.5 ontology quality gates evaluated before approval."""

    COVERAGE = "coverage"
    DISTINCTIVENESS = "distinctiveness"
    STABILITY = "stability"


class OntologyState(StrEnum):
    """§8.4 approval-gate states."""

    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


#: Every legal §8.4 transition. Anything outside these sets is rejected;
#: RETIRED is terminal.
ALLOWED_ONTOLOGY_TRANSITIONS: dict[OntologyState, frozenset[OntologyState]] = {
    OntologyState.DRAFT: frozenset({OntologyState.PROPOSED}),
    OntologyState.PROPOSED: frozenset({OntologyState.UNDER_REVIEW}),
    OntologyState.UNDER_REVIEW: frozenset({OntologyState.APPROVED}),
    OntologyState.APPROVED: frozenset({OntologyState.ACTIVE}),
    OntologyState.ACTIVE: frozenset({OntologyState.RETIRED}),
    OntologyState.RETIRED: frozenset(),
}

#: Targets whose incoming transition carries the mandatory reviewer-note guard.
REVIEWER_NOTE_REQUIRED: frozenset[OntologyState] = frozenset({OntologyState.APPROVED})


def ontology_transition_allowed(previous: OntologyState, current: OntologyState) -> bool:
    """Mirror the page-state helper style: pure lookup into the allowed map."""
    return current in ALLOWED_ONTOLOGY_TRANSITIONS[previous]


def _require_timezone(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


def _normalize_reviewer_note(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class KindDefinition(ContractModel):
    """One named kind in the ontology schema."""

    name: StableId
    scope: OntologyKindScope
    label: NonEmptyStr
    description: str = ""


class OntologySchema(ContractModel):
    """Entity/relation/attribute kind definitions (the static side of §16.3)."""

    schema_version: str = "ontology-schema-1"
    entity_kinds: tuple[KindDefinition, ...] = ()
    relation_kinds: tuple[KindDefinition, ...] = ()
    attribute_kinds: tuple[KindDefinition, ...] = ()

    @property
    def scopes(self) -> Mapping[OntologyKindScope, tuple[KindDefinition, ...]]:
        return {
            OntologyKindScope.ENTITY: self.entity_kinds,
            OntologyKindScope.RELATION: self.relation_kinds,
            OntologyKindScope.ATTRIBUTE: self.attribute_kinds,
        }

    def has_kind(self, scope: OntologyKindScope, name: str) -> bool:
        return any(kind.name == name for kind in self.scopes[scope])

    @model_validator(mode="after")
    def unique_names_per_scope(self) -> OntologySchema:
        for scope, kinds in self.scopes.items():
            seen: set[str] = set()
            for kind in kinds:
                if kind.scope != scope:
                    raise ValueError(
                        f"kind {kind.name!r} declared under {scope.value} "
                        f"but scoped {kind.scope.value}"
                    )
                if kind.name in seen:
                    raise ValueError(f"duplicate {scope.value} kind name: {kind.name!r}")
                seen.add(kind.name)
        return self

    @classmethod
    def universal_core(cls) -> OntologySchema:
        """Seed schema with the Universal Core entity kinds (audit §16-b axis)."""
        names = (
            "person",
            "organization",
            "project",
            "document",
            "event",
            "location",
            "product",
            "concept",
            "metric",
            "policy",
            "asset",
        )
        return cls(
            entity_kinds=tuple(
                KindDefinition(
                    name=name, scope=OntologyKindScope.ENTITY, label=name.replace("_", " ")
                )
                for name in names
            ),
            relation_kinds=(
                KindDefinition(
                    name=RELATES_TO_KIND,
                    scope=OntologyKindScope.RELATION,
                    label="relates to",
                ),
            ),
        )


class CoOccurrence(ContractModel):
    """One undirected co-occurrence count, stored in canonical (a < b) order."""

    entity_a: NonEmptyStr
    entity_b: NonEmptyStr
    count: int = Field(ge=1)

    @model_validator(mode="after")
    def canonical_order(self) -> CoOccurrence:
        if self.entity_a == self.entity_b:
            raise ValueError("co-occurrence endpoints must differ")
        if self.entity_a > self.entity_b:
            raise ValueError(
                "co-occurrence endpoints must be given in lexicographic order "
                f"({self.entity_b!r}, {self.entity_a!r})"
            )
        return self


class CorpusStats(ContractModel):
    """Observations fed to induction (§16.3 step 1: observations)."""

    corpus_id: StableId
    document_count: int = Field(ge=0)
    entity_mentions: Mapping[str, int]
    co_occurrences: tuple[CoOccurrence, ...] = ()

    @field_validator("entity_mentions")
    @classmethod
    def positive_counts(cls, value: Mapping[str, int]) -> Mapping[str, int]:
        for name, count in value.items():
            if not name.strip():
                raise ValueError("entity mention names must be non-empty")
            if count <= 0:
                raise ValueError(f"mention count for {name!r} must be positive")
        return value

    @model_validator(mode="after")
    def co_occurrence_endpoints_observed(self) -> CorpusStats:
        for pair in self.co_occurrences:
            for endpoint in (pair.entity_a, pair.entity_b):
                if endpoint not in self.entity_mentions:
                    raise ValueError(f"co-occurrence references unobserved entity {endpoint!r}")
        return self

    @property
    def total_mentions(self) -> int:
        return sum(self.entity_mentions.values())


class InductionConfig(ContractModel):
    """Deterministic thresholds for ``propose``."""

    min_mention_frequency: int = Field(default=3, ge=1)
    max_entity_kinds: int = Field(default=12, ge=1)
    min_co_occurrence: int = Field(default=2, ge=1)
    min_pair_affinity: float = Field(default=0.05, ge=0.0, le=1.0)
    max_relation_candidates: int = Field(default=16, ge=0)


def _kind_slug(surface: str) -> str:
    lowered = surface.lower()
    slug = "".join(ch if ch.isalnum() else "_" for ch in lowered)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


class EntityCandidate(ContractModel):
    """One induced entity-kind candidate with its supporting statistics."""

    name: NonEmptyStr
    suggested_kind: NonEmptyStr
    mention_frequency: int = Field(ge=1)
    mention_share: float = Field(ge=0.0, le=1.0)


class RelationCandidate(ContractModel):
    """One induced relation candidate between two frequent entities."""

    source: NonEmptyStr
    target: NonEmptyStr
    suggested_kind: NonEmptyStr
    support: int = Field(ge=1)
    affinity: float = Field(ge=0.0, le=1.0)


class OntologyProposal(ContractModel):
    """§16.3 output: the deterministic proposal awaiting gates and approval."""

    proposal_id: StableId
    corpus_id: StableId
    method: NonEmptyStr
    observed_document_count: int = Field(ge=0)
    entity_candidates: tuple[EntityCandidate, ...] = ()
    relation_candidates: tuple[RelationCandidate, ...] = ()
    # TimestampedModel-style field kept explicit so the module owns its own
    # timezone rule; see the determinism contract in the module docstring.
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        return _require_timezone(value)


def _ranked_entities(stats: CorpusStats, config: InductionConfig) -> list[tuple[str, int]]:
    qualified = [
        (name, count)
        for name, count in stats.entity_mentions.items()
        if count >= config.min_mention_frequency
    ]
    qualified.sort(key=lambda item: (-item[1], item[0]))
    return qualified[: config.max_entity_kinds]


def _induce_entity_candidates(
    stats: CorpusStats, config: InductionConfig
) -> tuple[EntityCandidate, ...]:
    total = stats.total_mentions
    candidates: list[EntityCandidate] = []
    slug_counts: dict[str, int] = {}
    for name, count in _ranked_entities(stats, config):
        slug = _kind_slug(name) or "entity"
        # Conflict policy (§16.3 frequency/conflict step): two surfaces that
        # normalize onto one slug get deterministic ordinal suffixes by rank.
        occurrences = slug_counts.get(slug, 0)
        slug_counts[slug] = occurrences + 1
        kind_name = slug if occurrences == 0 else f"{slug}_{occurrences + 1}"
        candidates.append(
            EntityCandidate(
                name=name,
                suggested_kind=kind_name,
                mention_frequency=count,
                mention_share=(count / total) if total else 0.0,
            )
        )
    return tuple(candidates)


def _induce_relation_candidates(
    stats: CorpusStats, config: InductionConfig
) -> tuple[RelationCandidate, ...]:
    pairs: list[tuple[int, str, str, float]] = []
    for pair in stats.co_occurrences:
        if pair.count < config.min_co_occurrence:
            continue
        floor = min(
            stats.entity_mentions[pair.entity_a],
            stats.entity_mentions[pair.entity_b],
        )
        affinity = pair.count / floor if floor else 0.0
        if affinity < config.min_pair_affinity:
            continue
        pairs.append((pair.count, pair.entity_a, pair.entity_b, affinity))
    pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
    return tuple(
        RelationCandidate(
            source=entity_a,
            target=entity_b,
            suggested_kind=RELATES_TO_KIND,
            support=count,
            affinity=affinity,
        )
        for count, entity_a, entity_b, affinity in pairs[: config.max_relation_candidates]
    )


def _compute_proposal_id(body: Mapping[str, Any]) -> str:
    digest = sha256_digest(canonical_json(dict(body)))
    return f"prop_{digest.removeprefix('sha256:')[:16]}"


def propose(
    corpus_stats: CorpusStats,
    *,
    config: InductionConfig | None = None,
    now: datetime,
) -> OntologyProposal:
    """Deterministically induce an :class:`OntologyProposal` from observations.

    Frequency selects candidate entity kinds (top-N by descending mention
    count, ties broken lexicographically); co-occurrence support and the
    overlap coefficient select candidate relations. Directionality is not
    asserted: endpoints are stored in canonical lexicographic order and the
    semantic direction is assigned at approval time.
    """
    _require_timezone(now)
    active_config = config if config is not None else InductionConfig()
    entity_candidates = _induce_entity_candidates(corpus_stats, active_config)
    relation_candidates = _induce_relation_candidates(corpus_stats, active_config)
    body = {
        "corpus_id": corpus_stats.corpus_id,
        "method": INDUCTION_METHOD,
        "observed_document_count": corpus_stats.document_count,
        "entity_candidates": [c.model_dump(mode="json", by_alias=True) for c in entity_candidates],
        "relation_candidates": [
            r.model_dump(mode="json", by_alias=True) for r in relation_candidates
        ],
    }
    return OntologyProposal(
        proposal_id=_compute_proposal_id(body),
        created_at=now,
        **body,
    )


class GateThresholds(ContractModel):
    """§16.5 thresholds; a gate passes when observed ≥ threshold."""

    min_coverage: float = Field(default=0.60, ge=0.0, le=1.0)
    min_distinctiveness: float = Field(default=0.50, ge=0.0, le=1.0)
    min_stability: float = Field(default=0.80, ge=0.0, le=1.0)

    def threshold_for(self, gate: GateName) -> float:
        if gate is GateName.COVERAGE:
            return self.min_coverage
        if gate is GateName.DISTINCTIVENESS:
            return self.min_distinctiveness
        return self.min_stability


class GateResult(ContractModel):
    """One gate's itemized verdict inside a :class:`GateReport`."""

    gate: GateName
    passed: bool
    observed: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)
    detail: NonEmptyStr


class GateReport(ContractModel):
    """Itemized §16.5 gate outcome for one proposal."""

    proposal_id: StableId
    results: tuple[GateResult, ...]

    @model_validator(mode="after")
    def covers_every_gate_once(self) -> GateReport:
        seen = [result.gate for result in self.results]
        expected = list(GateName)
        if sorted(seen, key=lambda g: g.value) != sorted(expected, key=lambda g: g.value):
            raise ValueError(
                f"gate report must contain each gate exactly once, got {[g.value for g in seen]}"
            )
        return self

    def result_for(self, gate: GateName) -> GateResult:
        for result in self.results:
            if result.gate is gate:
                return result
        raise KeyError(gate)  # pragma: no cover - guarded by covers_every_gate_once

    @property
    def all_passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def failed_gates(self) -> tuple[GateName, ...]:
        return tuple(result.gate for result in self.results if not result.passed)


def _coverage_value(proposal: OntologyProposal, stats: CorpusStats) -> tuple[float, str]:
    total = stats.total_mentions
    captured = sum(
        stats.entity_mentions.get(candidate.name, 0) for candidate in proposal.entity_candidates
    )
    value = (captured / total) if total else 0.0
    detail = f"captured {captured}/{total} mentions across {len(proposal.entity_candidates)} kinds"
    return value, detail


def _cosine_dissimilarity(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    shared = set(left) & set(right)
    dot = sum(left[dim] * right[dim] for dim in shared)
    left_norm = sqrt(sum(v * v for v in left.values()))
    right_norm = sqrt(sum(v * v for v in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 1.0
    return 1.0 - (dot / (left_norm * right_norm))


def _distinctiveness_value(proposal: OntologyProposal, stats: CorpusStats) -> tuple[float, str]:
    names = [candidate.name for candidate in proposal.entity_candidates]
    if len(names) < 2:
        return 1.0, f"vacuously distinctive with {len(names)} candidate kind(s)"
    dimensions = sorted(
        {endpoint for pair in stats.co_occurrences for endpoint in (pair.entity_a, pair.entity_b)}
    )
    profiles: dict[str, dict[str, float]] = {}
    for name in names:
        profiles[name] = {dim: 0.0 for dim in dimensions}
    for pair in stats.co_occurrences:
        for name in (pair.entity_a, pair.entity_b):
            if name in profiles and pair.entity_a != pair.entity_b:
                other = pair.entity_b if name == pair.entity_a else pair.entity_a
                profiles[name][other] += float(pair.count)
    dissimilarities = [
        _cosine_dissimilarity(profiles[a], profiles[b]) for a, b in combinations(names, 2)
    ]
    value = sum(dissimilarities) / len(dissimilarities)
    detail = (
        f"mean pairwise co-occurrence-profile dissimilarity {round(value, 6)} "
        f"across {len(names)} candidate kinds"
    )
    return value, detail


def _stability_value(
    proposal: OntologyProposal, previous: OntologyProposal | None
) -> tuple[float, str]:
    if previous is None:
        return 1.0, "bootstrap: no prior proposal to compare against"
    current_names = {candidate.name for candidate in proposal.entity_candidates}
    previous_names = {candidate.name for candidate in previous.entity_candidates}
    union = current_names | previous_names
    value = (len(current_names & previous_names) / len(union)) if union else 1.0
    detail = (
        f"Jaccard overlap with prior proposal {previous.proposal_id}: {round(value, 6)} "
        f"over {len(current_names)} current / {len(previous_names)} prior kinds"
    )
    return value, detail


def evaluate_quality_gates(
    proposal: OntologyProposal,
    corpus_stats: CorpusStats,
    *,
    thresholds: GateThresholds | None = None,
    previous_proposal: OntologyProposal | None = None,
) -> GateReport:
    """Evaluate the three §16.5 gates and return the itemized report."""
    active_thresholds = thresholds if thresholds is not None else GateThresholds()
    metrics = {
        GateName.COVERAGE: _coverage_value(proposal, corpus_stats),
        GateName.DISTINCTIVENESS: _distinctiveness_value(proposal, corpus_stats),
        GateName.STABILITY: _stability_value(proposal, previous_proposal),
    }
    results = []
    for gate in GateName:
        observed, detail = metrics[gate]
        threshold = active_thresholds.threshold_for(gate)
        results.append(
            GateResult(
                gate=gate,
                passed=observed + _FLOAT_TOLERANCE >= threshold,
                observed=min(max(observed, 0.0), 1.0),
                threshold=threshold,
                detail=detail,
            )
        )
    return GateReport(proposal_id=proposal.proposal_id, results=tuple(results))


class LifecycleEvent(ContractModel):
    """One recorded §8.4 transition."""

    from_state: OntologyState
    to_state: OntologyState
    actor: NonEmptyStr
    at: datetime
    reviewer_note: str | None = None

    @field_validator("at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        return _require_timezone(value)

    @model_validator(mode="after")
    def note_guard(self) -> LifecycleEvent:
        if self.to_state in REVIEWER_NOTE_REQUIRED and not _normalize_reviewer_note(
            self.reviewer_note
        ):
            raise MissingReviewerNoteError(
                f"transition to {self.to_state.value} requires a reviewer note"
            )
        return self


def validate_lifecycle_history(events: Sequence[LifecycleEvent]) -> None:
    """Reject histories that do not replay cleanly from DRAFT through the map."""
    previous_state = OntologyState.DRAFT
    for event in events:
        if event.from_state != previous_state:
            raise IllegalTransitionError(
                f"history discontinuity: expected a transition out of "
                f"{previous_state.value}, got one out of {event.from_state.value}"
            )
        if not ontology_transition_allowed(event.from_state, event.to_state):
            raise IllegalTransitionError(
                f"illegal transition {event.from_state.value} → {event.to_state.value}"
            )
        if event.to_state in REVIEWER_NOTE_REQUIRED and not _normalize_reviewer_note(
            event.reviewer_note
        ):
            raise MissingReviewerNoteError(
                f"transition to {event.to_state.value} requires a reviewer note"
            )
        previous_state = event.to_state


class OntologyApprovalGate:
    """§8.4 six-state approval-gate state machine for one ontology version."""

    def __init__(
        self,
        *,
        state: OntologyState = OntologyState.DRAFT,
        history: Sequence[LifecycleEvent] = (),
    ) -> None:
        if history:
            validate_lifecycle_history(history)
            replayed_end = history[-1].to_state
            if state != replayed_end:
                raise IllegalTransitionError(
                    f"state {state.value} contradicts history ending at {replayed_end.value}"
                )
        elif state != OntologyState.DRAFT:
            raise IllegalTransitionError(f"a fresh gate starts at DRAFT, not {state.value}")
        self._state = state
        self._events: list[LifecycleEvent] = list(history)

    @classmethod
    def from_history(cls, events: Sequence[LifecycleEvent]) -> OntologyApprovalGate:
        return cls(state=events[-1].to_state if events else OntologyState.DRAFT, history=events)

    @property
    def state(self) -> OntologyState:
        return self._state

    @property
    def history(self) -> tuple[LifecycleEvent, ...]:
        return tuple(self._events)

    def can_transition(self, to_state: OntologyState) -> bool:
        return ontology_transition_allowed(self._state, to_state)

    def transition(
        self,
        to_state: OntologyState,
        *,
        actor: str,
        at: datetime,
        reviewer_note: str | None = None,
    ) -> LifecycleEvent:
        """Apply one transition and return the appended event.

        Raises :class:`IllegalTransitionError` outside the allowed map and
        :class:`MissingReviewerNoteError` when entering APPROVED without a
        non-empty reviewer note.
        """
        _require_timezone(at)
        normalized_note = _normalize_reviewer_note(reviewer_note)
        if not ontology_transition_allowed(self._state, to_state):
            allowed = sorted(s.value for s in ALLOWED_ONTOLOGY_TRANSITIONS[self._state])
            raise IllegalTransitionError(
                f"illegal transition {self._state.value} → {to_state.value}; "
                f"allowed from {self._state.value}: {allowed}"
            )
        if to_state in REVIEWER_NOTE_REQUIRED and normalized_note is None:
            raise MissingReviewerNoteError(
                f"transition to {to_state.value} requires a non-empty reviewer note"
            )
        event = LifecycleEvent(
            from_state=self._state,
            to_state=to_state,
            actor=actor,
            at=at,
            reviewer_note=normalized_note,
        )
        self._state = to_state
        self._events.append(event)
        return event


class OntologyManifest(ContractModel):
    """World-scoped ontology manifest (one JSON file per world directory)."""

    schema_version: str = ONTOLOGY_MANIFEST_SCHEMA_VERSION
    world_id: StableId
    workspace_id: str | None = None
    ontology_version: int = Field(ge=1)
    state: OntologyState
    proposal: OntologyProposal | None = None
    gates: GateReport | None = None
    history: tuple[LifecycleEvent, ...] = ()
    manifest_hash: Sha256

    @model_validator(mode="after")
    def consistent_state_and_history(self) -> OntologyManifest:
        validate_lifecycle_history(self.history)
        expected = self.history[-1].to_state if self.history else OntologyState.DRAFT
        if self.state != expected:
            raise IllegalTransitionError(
                f"state {self.state.value} contradicts history ending at {expected.value}"
            )
        if self.gates is not None and self.proposal is None:
            raise ValueError("a gate report requires its proposal")
        return self

    def json_body(self) -> dict[str, Any]:
        """The hash-covered payload: everything except ``manifest_hash``."""
        return {
            "schema_version": self.schema_version,
            "world_id": self.world_id,
            "workspace_id": self.workspace_id,
            "ontology_version": self.ontology_version,
            "state": self.state.value,
            "proposal": (
                self.proposal.model_dump(mode="json", by_alias=False)
                if self.proposal is not None
                else None
            ),
            "gates": (
                self.gates.model_dump(mode="json", by_alias=False)
                if self.gates is not None
                else None
            ),
            "history": [event.model_dump(mode="json", by_alias=False) for event in self.history],
        }

    def verify_hash(self) -> bool:
        return sha256_digest(canonical_json(self.json_body())) == self.manifest_hash


def build_ontology_manifest(
    *,
    world_id: str,
    ontology_version: int,
    state: OntologyState,
    proposal: OntologyProposal | None = None,
    gates: GateReport | None = None,
    history: Sequence[LifecycleEvent] = (),
    workspace_id: str | None = None,
) -> OntologyManifest:
    """Construct a manifest whose ``manifest_hash`` covers the exact body.

    Domain rules are enforced here with typed errors first: pydantic wraps
    validator exceptions in ``ValidationError``, and callers of this factory
    deserve the specific :class:`IllegalTransitionError` /
    :class:`MissingReviewerNoteError` contracts.
    """
    validate_lifecycle_history(history)
    expected_state = history[-1].to_state if history else OntologyState.DRAFT
    if state != expected_state:
        raise IllegalTransitionError(
            f"state {state.value} contradicts history ending at {expected_state.value}"
        )
    if gates is not None and proposal is None:
        raise OntologyManifestError("a gate report requires its proposal")
    draft = OntologyManifest(
        world_id=world_id,
        workspace_id=workspace_id,
        ontology_version=ontology_version,
        state=state,
        proposal=proposal,
        gates=gates,
        history=tuple(history),
        manifest_hash="sha256:" + "0" * 64,
    )
    digest = sha256_digest(canonical_json(draft.json_body()))
    return draft.model_copy(update={"manifest_hash": digest})


class OntologyStore:
    """Persist ontology manifests per world, LocalWorldStore-style.

    Layout: ``<root>/<world_id>/ontology.json`` — the same per-world directory
    the local-mcp ``LocalWorldStore`` reads ``manifest.json``/``state.json``
    from. This store only ever creates/reads the additional ``ontology.json``
    sibling; it never touches the published world documents, so no database
    migration is needed.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def world_dir(self, world_id: str) -> Path:
        if not world_id or "/" in world_id or "\\" in world_id or world_id in {".", ".."}:
            raise OntologyManifestError(f"invalid world id: {world_id!r}")
        return self._root / world_id

    def ontology_path(self, world_id: str) -> Path:
        return self.world_dir(world_id) / ONTOLOGY_MANIFEST_FILENAME

    def has(self, world_id: str) -> bool:
        return self.ontology_path(world_id).is_file()

    def save(self, manifest: OntologyManifest) -> Path:
        if not manifest.verify_hash():
            raise OntologyManifestError(
                f"refusing to persist world {manifest.world_id!r}: "
                "manifest_hash does not cover the body"
            )
        directory = self.world_dir(manifest.world_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / ONTOLOGY_MANIFEST_FILENAME
        serialized = (
            json.dumps(
                # Field-name (snake_case) keys, matching the sibling
                # manifest.json/state.json convention of LocalWorldStore.
                # by_alias=False must be explicit: ContractModel sets
                # serialize_by_alias=True, which would otherwise default us
                # to camelCase on disk.
                manifest.model_dump(mode="json", by_alias=False),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        temp_path = target.with_suffix(".json.tmp")
        temp_path.write_text(serialized, encoding="utf-8")
        os.replace(temp_path, target)
        return target

    def load(self, world_id: str) -> OntologyManifest:
        path = self.ontology_path(world_id)
        if not path.is_file():
            raise OntologyManifestError(f"no ontology manifest for world {world_id!r} at {path}")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OntologyManifestError(f"{path}: unreadable ontology manifest") from exc
        if not isinstance(document, dict):
            raise OntologyManifestError(f"{path}: ontology manifest must be a JSON object")
        recorded_hash = document.pop("manifest_hash", None)
        if not isinstance(recorded_hash, str):
            raise OntologyManifestError(f"{path}: ontology manifest lacks a manifest_hash")
        try:
            manifest = OntologyManifest.model_validate({**document, "manifest_hash": recorded_hash})
        except ValueError as exc:
            raise OntologyManifestError(f"{path}: malformed ontology manifest: {exc}") from exc
        if manifest.schema_version != ONTOLOGY_MANIFEST_SCHEMA_VERSION:
            raise OntologyManifestError(
                f"{path}: unsupported ontology manifest schema {manifest.schema_version!r}"
            )
        if not manifest.verify_hash():
            raise OntologyManifestError(f"{path}: manifest_hash does not cover the body")
        return manifest
