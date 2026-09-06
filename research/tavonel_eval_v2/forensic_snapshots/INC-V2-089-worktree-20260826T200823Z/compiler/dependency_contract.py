#!/usr/bin/env python3
"""Declarative dependency/sensitivity contract for INC-V2-038's channel gap.

`akc_cir.recompilation.plan_recompilation` seeds its traversal from
`SemanticDiff.changed_logical_ids`, which only carries SEMANTIC- and
GRAPH-channel changes (`akc_cir.semantic_diff._SEMANTIC_RECOMPILATION_CHANNELS`),
and `compiler.selective_build.graph_for` only ever emits edges tagged
`DependencyChannel.SEMANTIC` and/or `.STRUCTURAL`. A LOCATOR (evidence moved),
TEMPORAL (effective time changed) or METADATA (language/accessibility changed)
change is detected by the diff correctly, and then has no traversal that can
carry it and no edge that could carry it if it did -- it disappears between
detection and seeding. See `compiler/channel_cases.py` and
`tests/test_executor_channels.py` for the confirmed cases.

This module does not patch that gap in place -- `akc_cir.recompilation` is
Protected Core and `compiler/selective_build.py` is out of this lane's scope to
modify. Widening `_SEMANTIC_RECOMPILATION_CHANNELS`'s three enums onto the
allow-list would restore *seeding* without establishing what LOCATOR/TEMPORAL/
METADATA changes actually affect, which is indistinguishable from a guess. What
this module builds instead is the thing a fix would need to be correct: a
declarative statement of which artifact *facet* each channel is about, and
which artifact kinds are actually sensitive to that facet -- proven against
`compiler.selective_build.build_all`'s own digest formulas where production
already answers that question (STRUCTURAL: does the digest read unit order?),
and stated as a normative design claim where it does not yet
(LOCATOR/TEMPORAL/METADATA: `section:` is the one artifact kind whose identity
*is* a single knowledge unit's evidence occurrence, so it is declared
sensitive to that occurrence's locator, temporal and metadata fingerprints even
though today's `build_all` does not read them -- see `e9_oracle.py`'s
adversarial digest check for the proof that this declaration and today's
representation currently disagree).

The traversal itself is not reimplemented. `akc_cir.dependency.DependencyGraph
.impact_of` already accepts an arbitrary `DependencyChannel` and already does
correct multi-hop, cycle-safe, explained propagation on it -- `plan_recompilation`
simply never calls it with anything but `DependencyChannel.SEMANTIC`. This
module builds its own `DependencyGraph` from the declared sensitivity table and
calls the same unmodified `impact_of`, so LOCATOR/TEMPORAL/METADATA propagation
gets the identical, already-tested traversal engine SEMANTIC gets.

Every detected typed change resolves to exactly one of three verdicts, never a
silent fourth option:

    SEED_SET      a complete set of dependent artifacts, found by real
                  channel-filtered graph traversal
    NO_DEPENDENT  every artifact that reads the changed unit was checked and
                  none declared itself sensitive to this change's facet --
                  proven by inspecting the readers, not inferred from an empty
                  traversal result with nothing checked
    UNRESOLVED    the channel is outside this contract's declared scope, the
                  change carries no anchor to bind a dependency to, or a
                  reader artifact matches no declared sensitivity prefix at
                  all -- this contract does not know, and refuses to guess an
                  edge for an ambiguous relationship
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(ROOT / "packages" / "cir-python" / "src"), str(NS)):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from akc_cir.dependency import (  # noqa: E402
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)
from akc_cir.semantic_diff import (  # noqa: E402
    ChangeChannel,
    SemanticChange,
    SemanticDiff,
    UnitSnapshot,
)

__all__ = [
    "DEFAULT_SENSITIVITY",
    "ContractDecision",
    "Verdict",
    "build_contract_graph",
    "decide_structural",
    "decide_unit_change",
    "faceted_section_digest",
    "merged_reads",
    "prefix_of",
    "unrecognized_readers",
]


class Verdict(StrEnum):
    SEED_SET = "seed_set"
    NO_DEPENDENT = "no_dependent"
    UNRESOLVED = "unresolved"


#: The channels this contract binds a `SemanticChange.logical_id` to a
#: `DependencyChannel` for. Deliberately not SEMANTIC's sibling GRAPH, and
#: deliberately not VISUAL: neither is named in INC-V2-038 and adding either
#: here would be widening this contract's declared scope past what it was
#: asked to close. STRUCTURAL is handled separately by `decide_structural`
#: because a structural change carries no `logical_id`
#: (`semantic_diff._structural_changes` never sets one) -- its scope is
#: `SemanticDiff.structural_scope`, the whole document's units, not one unit.
_DEPENDENCY_CHANNEL_OF_UNIT_SCOPED: dict[ChangeChannel, DependencyChannel] = {
    ChangeChannel.SEMANTIC: DependencyChannel.SEMANTIC,
    ChangeChannel.LOCATOR: DependencyChannel.LOCATOR,
    ChangeChannel.TEMPORAL: DependencyChannel.TEMPORAL,
    ChangeChannel.METADATA: DependencyChannel.METADATA,
}

#: Declarative artifact-kind -> facet sensitivity, keyed by the same id-prefix
#: convention `selective_build.graph_for` uses for its own (narrower)
#: declaration. Every entry is individually justified below by what that
#: artifact kind's digest in `selective_build.build_all` actually reads, or --
#: for `section:`'s LOCATOR/TEMPORAL/METADATA entries, which `build_all` does
#: not yet read at all -- by what it represents.
#:
#: `section:<unit>` is one knowledge unit's evidence occurrence
#: (`build_all`: `{"logical_id": ..., "semantic_text": unit["text"]}`).
#: Sensitive to SEMANTIC (the digest reads the unit's text directly) and, by
#: declaration, to LOCATOR/TEMPORAL/METADATA: a unit's evidence anchor,
#: effective time and language/accessibility tags are properties of that same
#: occurrence, even though today's digest formula does not read them (see
#: `faceted_section_digest` below and `e9_oracle.py`'s adversarial check).
#:
#: `document-index:<doc>` aggregates by membership and reading order
#: (`build_all`: `{"doc_key": ..., "members": ordered}`, `ordered` in document
#: order). Sensitive to STRUCTURAL (`ordered`'s order is read directly). NOT
#: sensitive to SEMANTIC: no unit's text is read, only its id and position.
#:
#: `structure-map:<doc>` is explicitly the shape artifact
#: (`build_all`: `{"doc_key": ..., "paths": [...]}`, paths in document order).
#: Sensitive to STRUCTURAL only, for the same reason.
#:
#: `topic-bucket:<doc>:<n>` aggregates by membership alone, order-independent
#: (`build_all` sorts: `sorted(set(ordered))`... filtered by bucket). Not
#: sensitive to any of the four facets this contract tracks: it does not read
#: text, order, or any per-unit facet -- only which ids are in its bucket, and
#: unit add/remove is a different change kind than the four this contract
#: decides over.
DEFAULT_SENSITIVITY: Mapping[str, frozenset[DependencyChannel]] = {
    "section:": frozenset(
        {
            DependencyChannel.SEMANTIC,
            DependencyChannel.LOCATOR,
            DependencyChannel.TEMPORAL,
            DependencyChannel.METADATA,
        }
    ),
    "document-index:": frozenset({DependencyChannel.STRUCTURAL}),
    "structure-map:": frozenset({DependencyChannel.STRUCTURAL}),
    "topic-bucket:": frozenset(),
}


def prefix_of(
    artifact_id: str, sensitivity: Mapping[str, frozenset[DependencyChannel]] = DEFAULT_SENSITIVITY
) -> str | None:
    """The declared artifact-kind prefix `artifact_id` matches, or None.

    None means this contract has no sensitivity declaration for that artifact
    kind at all -- not "declared insensitive to everything" (that is an empty
    frozenset, a real answer), but "unknown", which is what forces callers to
    treat it as unresolved rather than silently skipping it.
    """
    for prefix in sensitivity:
        if artifact_id.startswith(prefix):
            return prefix
    return None


def merged_reads(
    before: Mapping[str, tuple[str, ...]], after: Mapping[str, tuple[str, ...]]
) -> dict[str, tuple[str, ...]]:
    """Union each artifact's declared reads across both revisions.

    Same union `compiler.selective_build.graph_for` takes over
    `before`/`after`'s dependency maps -- an artifact retired or newly created
    by this revision still needs its reads represented for one side of the
    diff. This function only reads `inventory_and_dependencies`'s output (which
    artifact reads which logical id); it does not touch channel assignment,
    which is this module's own decision, not production's.
    """
    merged: dict[str, tuple[str, ...]] = {}
    for artifact in {*before, *after}:
        merged[artifact] = tuple(
            dict.fromkeys((*before.get(artifact, ()), *after.get(artifact, ())))
        )
    return merged


def unrecognized_readers(
    readers: frozenset[str],
    sensitivity: Mapping[str, frozenset[DependencyChannel]] = DEFAULT_SENSITIVITY,
) -> frozenset[str]:
    """Readers whose artifact id matches no declared sensitivity prefix.

    A non-empty result is this contract's negative control: it cannot tell
    whether that reader is sensitive to the facet in question, so a caller
    must fail closed (UNRESOLVED) rather than silently treating "unknown" as
    "insensitive".
    """
    return frozenset(a for a in readers if prefix_of(a, sensitivity) is None)


def build_contract_graph(
    graph_reads: Mapping[str, tuple[str, ...]],
    sensitivity: Mapping[str, frozenset[DependencyChannel]] = DEFAULT_SENSITIVITY,
) -> DependencyGraph:
    """A `DependencyGraph` built from this contract's declared sensitivities.

    One edge per (artifact, logical id it reads), same direction convention as
    `selective_build.graph_for` (`DependencyEdge(artifact, member, DEPENDS_ON,
    channels=...)`, so impact travels member -> artifact, i.e. changing a unit
    invalidates the artifacts that read it). `channels` is this contract's
    declared sensitivity for that artifact kind, not production's -- an
    artifact whose prefix is unrecognized is left out of the graph entirely
    (never guessed in with either every channel or no channel), and an
    artifact declared sensitive to nothing produces no edge at all, since
    `DependencyEdge` refuses to be constructed with an empty channel set.

    Reusing `akc_cir.dependency.DependencyGraph.impact_of` unmodified means
    LOCATOR/TEMPORAL/METADATA propagation here gets the same multi-hop,
    cycle-safe, explained traversal SEMANTIC gets in production --
    `plan_recompilation` simply never calls `impact_of` with those channels.
    """
    edges: list[DependencyEdge] = []
    for artifact, members in graph_reads.items():
        prefix = prefix_of(artifact, sensitivity)
        if prefix is None:
            continue
        channels = sensitivity[prefix]
        if not channels:
            continue
        for member in dict.fromkeys(members):
            edges.append(DependencyEdge(artifact, member, EdgeType.DEPENDS_ON, channels=channels))
    return DependencyGraph(edges)


@dataclass(frozen=True, slots=True)
class ContractDecision:
    """What this contract concluded about one detected typed change.

    `dependents` is populated only when `verdict is Verdict.SEED_SET`; it is
    the complete required rebuild seed set, from a real channel-filtered
    traversal over `build_contract_graph`'s output, not a guess. `readers`
    records every artifact this decision actually checked, so a NO_DEPENDENT
    or UNRESOLVED verdict can be audited against what was and was not looked
    at rather than taken on the verdict's word alone.
    """

    subject: str
    channel: ChangeChannel
    dependency_channel: DependencyChannel | None
    verdict: Verdict
    dependents: frozenset[str] = frozenset()
    readers: frozenset[str] = field(default_factory=frozenset)
    unrecognized: frozenset[str] = frozenset()
    reason: str = ""


def decide_unit_change(
    change: SemanticChange,
    *,
    graph_reads: Mapping[str, tuple[str, ...]],
    sensitivity: Mapping[str, frozenset[DependencyChannel]] = DEFAULT_SENSITIVITY,
) -> ContractDecision:
    """Decide one unit-scoped typed change: SEMANTIC, LOCATOR, TEMPORAL or
    METADATA (see `_DEPENDENCY_CHANNEL_OF_UNIT_SCOPED`). Anything else --
    including STRUCTURAL, which belongs to `decide_structural` -- and any
    change without a `logical_id` to anchor on both fail closed as
    UNRESOLVED, since a dependency cannot be declared without something to
    bind it to.
    """
    channel = change.channel
    dep_channel = _DEPENDENCY_CHANNEL_OF_UNIT_SCOPED.get(channel)
    if dep_channel is None:
        return ContractDecision(
            subject=change.logical_id or "<no logical_id>",
            channel=channel,
            dependency_channel=None,
            verdict=Verdict.UNRESOLVED,
            reason=(
                f"channel {channel.value!r} is outside this contract's declared "
                f"scope ({sorted(c.value for c in _DEPENDENCY_CHANNEL_OF_UNIT_SCOPED)}); "
                "refusing to guess a dependency for it"
            ),
        )
    if not change.logical_id:
        return ContractDecision(
            subject="<no logical_id>",
            channel=channel,
            dependency_channel=dep_channel,
            verdict=Verdict.UNRESOLVED,
            reason="typed change carries no logical_id to anchor a dependency to",
        )

    readers = frozenset(
        artifact for artifact, reads in graph_reads.items() if change.logical_id in reads
    )
    unknown = unrecognized_readers(readers, sensitivity)
    if unknown:
        return ContractDecision(
            subject=change.logical_id,
            channel=channel,
            dependency_channel=dep_channel,
            verdict=Verdict.UNRESOLVED,
            readers=readers,
            unrecognized=unknown,
            reason=(
                f"{sorted(unknown)} read logical_id {change.logical_id!r} but match no "
                "declared artifact-kind prefix; this contract does not know whether "
                "they are sensitive to this facet and refuses to guess"
            ),
        )

    graph = build_contract_graph(graph_reads, sensitivity)
    if change.logical_id in graph.nodes:
        report = graph.impact_of([change.logical_id], channel=dep_channel)
        dependents = frozenset(report.affected_ids)
    else:
        # Not a node in the contract graph at all -- no artifact, recognized or
        # not, declared reading this logical id. Equivalent to `readers` being
        # empty, handled explicitly below rather than treated as a traversal
        # that ran and found nothing.
        dependents = frozenset()

    if dependents:
        return ContractDecision(
            subject=change.logical_id,
            channel=channel,
            dependency_channel=dep_channel,
            verdict=Verdict.SEED_SET,
            dependents=dependents,
            readers=readers,
            reason=(
                f"{len(dependents)} artifact(s) declared sensitive to "
                f"{dep_channel.value!r} reached from {change.logical_id!r}"
            ),
        )
    if not readers:
        return ContractDecision(
            subject=change.logical_id,
            channel=channel,
            dependency_channel=dep_channel,
            verdict=Verdict.NO_DEPENDENT,
            reason=f"no artifact in the inventory reads logical_id {change.logical_id!r} at all",
        )
    return ContractDecision(
        subject=change.logical_id,
        channel=channel,
        dependency_channel=dep_channel,
        verdict=Verdict.NO_DEPENDENT,
        readers=readers,
        reason=(
            f"{len(readers)} reader artifact(s) checked ({sorted(readers)}); none "
            f"declared sensitive to {dep_channel.value!r}"
        ),
    )


def decide_structural(
    diff: SemanticDiff,
    *,
    graph_reads: Mapping[str, tuple[str, ...]],
    sensitivity: Mapping[str, frozenset[DependencyChannel]] = DEFAULT_SENSITIVITY,
) -> ContractDecision:
    """Decide the document-scoped STRUCTURAL channel.

    A structural change carries no `logical_id` (a block-count or heading-tree
    change is a property of the document, not of one unit), so its seed is
    `diff.structural_scope` -- every logical id on either side, per
    `SemanticDiff`'s own docstring -- not a single change's `logical_id`.
    """
    if not diff.structural_change_present:
        return ContractDecision(
            subject="structural",
            channel=ChangeChannel.STRUCTURAL,
            dependency_channel=DependencyChannel.STRUCTURAL,
            verdict=Verdict.NO_DEPENDENT,
            reason="no structural change is present in this diff",
        )
    scope = diff.structural_scope
    if not scope:
        return ContractDecision(
            subject="structural",
            channel=ChangeChannel.STRUCTURAL,
            dependency_channel=DependencyChannel.STRUCTURAL,
            verdict=Verdict.UNRESOLVED,
            reason=(
                "a structural change is present but structural_scope is empty; "
                "cannot anchor a dependency without a scope, refusing to guess"
            ),
        )
    scope_set = frozenset(scope)
    readers = frozenset(
        artifact for artifact, reads in graph_reads.items() if scope_set & set(reads)
    )
    unknown = unrecognized_readers(readers, sensitivity)
    if unknown:
        return ContractDecision(
            subject="structural",
            channel=ChangeChannel.STRUCTURAL,
            dependency_channel=DependencyChannel.STRUCTURAL,
            verdict=Verdict.UNRESOLVED,
            readers=readers,
            unrecognized=unknown,
            reason=(
                f"{sorted(unknown)} read a unit in structural_scope but match no "
                "declared artifact-kind prefix; refusing to guess"
            ),
        )

    graph = build_contract_graph(graph_reads, sensitivity)
    seeds = [node for node in scope if node in graph.nodes]
    dependents = frozenset()
    if seeds:
        report = graph.impact_of(seeds, channel=DependencyChannel.STRUCTURAL)
        dependents = frozenset(report.affected_ids)

    if dependents:
        return ContractDecision(
            subject="structural",
            channel=ChangeChannel.STRUCTURAL,
            dependency_channel=DependencyChannel.STRUCTURAL,
            verdict=Verdict.SEED_SET,
            dependents=dependents,
            readers=readers,
            reason=(
                f"{len(dependents)} artifact(s) declared order-sensitive reached "
                "from structural_scope"
            ),
        )
    if not readers:
        return ContractDecision(
            subject="structural",
            channel=ChangeChannel.STRUCTURAL,
            dependency_channel=DependencyChannel.STRUCTURAL,
            verdict=Verdict.NO_DEPENDENT,
            reason="no artifact in the inventory reads any unit in structural_scope",
        )
    return ContractDecision(
        subject="structural",
        channel=ChangeChannel.STRUCTURAL,
        dependency_channel=DependencyChannel.STRUCTURAL,
        verdict=Verdict.NO_DEPENDENT,
        readers=readers,
        reason=(
            f"{len(readers)} reader artifact(s) checked ({sorted(readers)}); "
            "none declared order-sensitive"
        ),
    )


# ---------------------------------------------------------------------------
# Task 4 -- artifact representation, not just edges.
#
# A dependency edge existing (this contract's SEED_SET verdict) says a
# consumer *should* rebuild. It says nothing about whether rebuilding would
# actually change that consumer's bytes -- and `compiler.selective_build
# .build_all`'s `section:` spec is `{"logical_id": ..., "semantic_text": text}`
# only. It does not read `evidence_id`, `temporal_fingerprint` or
# `metadata_fingerprint` at all (confirmed in `channel_cases.py`'s
# `referential_case`/`temporal_case`/`descriptive_case` notes, and
# independently below by `tests/test_dependency_contract.py`'s adversarial
# check). So even a corrected traversal that seeds `section:<unit>` for a
# LOCATOR/TEMPORAL/METADATA change would rebuild it into byte-identical
# output: an equivalence check comparing clean-rebuild bytes to
# selective-rebuild bytes would see no divergence and report the pair
# equivalent, hiding the defect a second time, one layer down.
#
# `faceted_section_digest` is a reference representation, declared exactly to
# match this module's own DEFAULT_SENSITIVITY claim that `section:` is
# sensitive to all four facets. It is not wired into `selective_build
# .build_all` -- that module is out of this lane's scope to modify -- so it
# exists only to measure divergence where production's representation cannot
# show one, never to replace production's artifact spec.


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def faceted_section_digest(unit: UnitSnapshot) -> str:
    """What a `section:` artifact's digest would read if it were actually
    sensitive to every facet `DEFAULT_SENSITIVITY` declares for it. Two
    `UnitSnapshot`s that differ only in `evidence_id`, `temporal_fingerprint`
    or `metadata_fingerprint` (text, logical_id otherwise identical) produce
    different digests here and identical digests under
    `selective_build.build_all`'s real `section:` spec -- that gap is the
    adversarial condition Task 4 asks to be made explicit, per channel.
    """
    return _digest(
        {
            "logical_id": unit.logical_id,
            "semantic_text": unit.text,
            "locator": unit.evidence_id,
            "temporal_fingerprint": unit.temporal_fingerprint,
            "metadata_fingerprint": unit.metadata_fingerprint,
        }
    )
