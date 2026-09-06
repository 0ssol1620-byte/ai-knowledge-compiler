"""Tests for `compiler/dependency_contract.py`, INC-V2-038's declarative
dependency/sensitivity contract.

Structure, per the task's four requirements:

    Task 1  every detected typed change resolves to exactly one of SEED_SET /
            NO_DEPENDENT / UNRESOLVED, and NO_DEPENDENT is checked, not
            inferred from silence
    Task 3  gate power: the negative control (unrecognized reader) actually
            produces UNRESOLVED with no guessed edge, and the traversal this
            contract reuses (`DependencyGraph.impact_of`) is proven to do real
            multi-hop propagation on LOCATOR/TEMPORAL/METADATA, not just a
            depth-1 lookup, using the same synthetic-chain technique
            `channel_cases.multi_hop_case` uses for SEMANTIC
    Task 4  the adversarial artifact-representation check: `section:`'s real
            digest formula (`selective_build.build_all`) is facet-blind for
            LOCATOR/TEMPORAL/METADATA while `faceted_section_digest` (this
            contract's reference representation) is not, per channel, with a
            SEMANTIC positive control proving the check has power to detect a
            representation that *does* react
"""

from __future__ import annotations

import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "compiler")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import compiler.channel_cases as cc  # noqa: E402
import compiler.dependency_contract as dc  # noqa: E402
from akc_cir.dependency import DependencyChannel  # noqa: E402
from akc_cir.semantic_diff import ChangeKind, SemanticChange, UnitSnapshot  # noqa: E402

# ---------------------------------------------------------------------------
# Task 1 -- three-way verdict, run against the real channel_cases fixtures.


def _reads_for_identical_text_pair() -> dict[str, tuple[str, ...]]:
    before_doc = cc.document(cc.markdown(cc.BODY_ALPHA, cc.BODY_BETA), "v1")
    after_doc = cc.document(cc.markdown(cc.BODY_ALPHA, cc.BODY_BETA), "v2")
    import compiler.selective_build as engine

    before_deps, _ = engine.inventory_and_dependencies(before_doc)
    after_deps, _ = engine.inventory_and_dependencies(after_doc)
    return dc.merged_reads(before_deps, after_deps)


def test_locator_change_yields_seed_set_naming_the_section_artifact() -> None:
    case = cc.referential_case()
    reads = _reads_for_identical_text_pair()
    change = next(c for c in case.diff.changes if c.channel.value == "locator")
    decision = dc.decide_unit_change(change, graph_reads=reads)
    assert decision.verdict is dc.Verdict.SEED_SET
    assert decision.dependents == frozenset({case.target_artifact})


def test_temporal_change_yields_seed_set_naming_the_section_artifact() -> None:
    case = cc.temporal_case()
    reads = _reads_for_identical_text_pair()
    change = next(c for c in case.diff.changes if c.channel.value == "temporal")
    decision = dc.decide_unit_change(change, graph_reads=reads)
    assert decision.verdict is dc.Verdict.SEED_SET
    assert decision.dependents == frozenset({case.target_artifact})


def test_metadata_change_yields_seed_set_naming_the_section_artifact() -> None:
    case = cc.descriptive_case()
    reads = _reads_for_identical_text_pair()
    change = next(c for c in case.diff.changes if c.channel.value == "metadata")
    decision = dc.decide_unit_change(change, graph_reads=reads)
    assert decision.verdict is dc.Verdict.SEED_SET
    assert decision.dependents == frozenset({case.target_artifact})


def test_no_dependent_is_proven_against_actual_readers_not_assumed() -> None:
    """A change whose only reader is declared insensitive to this facet must
    report NO_DEPENDENT, and the decision must record which reader(s) it
    actually checked -- proof, not silence standing in for a verdict."""
    change = SemanticChange(kind=ChangeKind.EVIDENCE_MOVED, logical_id="u:1")
    decision = dc.decide_unit_change(
        change, graph_reads={"topic-bucket:doc:1": ("u:1",)}
    )
    assert decision.verdict is dc.Verdict.NO_DEPENDENT
    assert decision.readers == frozenset({"topic-bucket:doc:1"})
    assert "topic-bucket:doc:1" in decision.reason


def test_no_dependent_when_nothing_reads_the_changed_unit_at_all() -> None:
    change = SemanticChange(kind=ChangeKind.EVIDENCE_MOVED, logical_id="u:orphan")
    decision = dc.decide_unit_change(change, graph_reads={"section:other": ("u:other",)})
    assert decision.verdict is dc.Verdict.NO_DEPENDENT
    assert decision.readers == frozenset()


def test_structural_seed_set_matches_production_exactly() -> None:
    """Confirmed empirically against real production output: structural_case's
    plan.to_rebuild is exactly {document-index:<key>, structure-map:<key>} --
    this contract's independently-declared order-sensitive set matches it
    exactly (not merely a subset), because both `document-index:` and
    `structure-map:` genuinely read unit order in `build_all`."""
    case = cc.structural_case()
    before_doc = cc.document(cc.markdown(cc.BODY_ALPHA, cc.BODY_BETA, cc.BODY_GAMMA), "v1")
    raw_units = list(before_doc["units"])
    after_doc = {
        **before_doc,
        "units": [raw_units[0], raw_units[2], raw_units[1]],
        "version_id": "v2",
    }
    import compiler.selective_build as engine

    before_deps, _ = engine.inventory_and_dependencies(before_doc)
    after_deps, _ = engine.inventory_and_dependencies(after_doc)
    reads = dc.merged_reads(before_deps, after_deps)

    decision = dc.decide_structural(case.diff, graph_reads=reads)
    assert decision.verdict is dc.Verdict.SEED_SET
    assert decision.dependents == frozenset(case.plan.to_rebuild)


# ---------------------------------------------------------------------------
# Task 3 -- negative control: ambiguous / unsupported relationships fail
# closed with NO guessed edge, and gate power for that refusal (it is not
# merely the code path that never triggers).


def test_unrecognized_reader_prefix_fails_closed_as_unresolved() -> None:
    """An artifact of a kind this contract has never seen reads the changed
    unit. The contract must not guess it is insensitive (silently proceeding
    to NO_DEPENDENT) nor guess it is sensitive (silently proceeding to
    SEED_SET) -- it must say it does not know."""
    change = SemanticChange(kind=ChangeKind.EVIDENCE_MOVED, logical_id="u:1")
    decision = dc.decide_unit_change(
        change, graph_reads={"mystery-cache:Q": ("u:1",), "section:X": ("u:1",)}
    )
    assert decision.verdict is dc.Verdict.UNRESOLVED
    assert decision.unrecognized == frozenset({"mystery-cache:Q"})
    assert decision.dependents == frozenset(), "an UNRESOLVED verdict must name no seeds at all"


def test_unrecognized_reader_control_has_power_recognized_prefix_would_pass() -> None:
    """Gate power for the case above: the same scenario with the unrecognized
    reader removed resolves cleanly to SEED_SET. If it did not, the UNRESOLVED
    result above would prove nothing about the unrecognized-prefix check
    specifically -- it could be failing for an unrelated reason."""
    change = SemanticChange(kind=ChangeKind.EVIDENCE_MOVED, logical_id="u:1")
    decision = dc.decide_unit_change(change, graph_reads={"section:X": ("u:1",)})
    assert decision.verdict is dc.Verdict.SEED_SET


def test_out_of_scope_channel_fails_closed_as_unresolved() -> None:
    change = SemanticChange(kind=ChangeKind.VISUAL_CHANGED, logical_id="u:1")
    decision = dc.decide_unit_change(change, graph_reads={"section:X": ("u:1",)})
    assert decision.verdict is dc.Verdict.UNRESOLVED
    assert decision.dependents == frozenset()


def test_missing_logical_id_fails_closed_as_unresolved() -> None:
    change = SemanticChange(kind=ChangeKind.EVIDENCE_MOVED, logical_id=None)
    decision = dc.decide_unit_change(change, graph_reads={"section:X": ("u:1",)})
    assert decision.verdict is dc.Verdict.UNRESOLVED
    assert decision.dependents == frozenset()


def test_structural_change_present_but_empty_scope_fails_closed() -> None:
    """Constructed directly rather than via a real diff: `diff_documents`
    never actually produces `structural_change_present=True` with an empty
    `structural_scope` (the scope is derived from the same units the
    structural comparison ran over), so this is a synthetic contract on the
    dataclass itself -- proving the guard exists even though production
    cannot currently trigger it, rather than leaving it untested because
    production happens not to reach it."""
    from akc_cir.semantic_diff import ChangeChannel as _CC
    from akc_cir.semantic_diff import DiffLevel, SemanticDiff

    change = SemanticChange(kind=ChangeKind.STRUCTURE_CHANGED)
    assert change.channel is _CC.STRUCTURAL
    diff = SemanticDiff(
        level=DiffLevel.SEMANTIC,
        content_changed=True,
        changes=(change,),
        structural_scope=(),
    )
    decision = dc.decide_structural(diff, graph_reads={"structure-map:doc": ("u:1",)})
    assert decision.verdict is dc.Verdict.UNRESOLVED


# ---------------------------------------------------------------------------
# Task 3 -- multi-hop propagation, proven with a synthetic chain the same way
# `channel_cases.multi_hop_case` proves it for SEMANTIC: production's real
# `inventory_and_dependencies` never builds artifact-on-artifact edges, so a
# depth-1 relationship is all any real fixture can exercise. This proves the
# *traversal this contract reuses* -- `DependencyGraph.impact_of`, unmodified
# from `akc_cir.dependency` -- actually walks more than one hop on channels
# other than SEMANTIC, which production never calls it with at all.


def test_locator_multi_hop_propagation_walks_the_full_chain() -> None:
    sensitivity = {
        "chain:A": frozenset({DependencyChannel.LOCATOR}),
        "chain:B": frozenset({DependencyChannel.LOCATOR}),
        "chain:C": frozenset({DependencyChannel.LOCATOR}),
    }
    deps = {"chain:A": ("leaf",), "chain:B": ("chain:A",), "chain:C": ("chain:B",)}
    change = SemanticChange(kind=ChangeKind.EVIDENCE_MOVED, logical_id="leaf")
    decision = dc.decide_unit_change(change, graph_reads=deps, sensitivity=sensitivity)
    assert decision.verdict is dc.Verdict.SEED_SET
    assert decision.dependents == frozenset({"chain:A", "chain:B", "chain:C"})

    graph = dc.build_contract_graph(deps, sensitivity)
    report = graph.impact_of(["leaf"], channel=DependencyChannel.LOCATOR)
    depth_by_node = {p.node_id: p.depth for p in report.affected}
    assert depth_by_node == {"chain:A": 1, "chain:B": 2, "chain:C": 3}, (
        "not just reached -- reached at increasing depth, proving a real "
        "transitive walk rather than a flattened depth-1 lookup"
    )


def test_temporal_and_metadata_multi_hop_propagation_also_walk_the_chain() -> None:
    for channel in (DependencyChannel.TEMPORAL, DependencyChannel.METADATA):
        sensitivity = {
            "chain:A": frozenset({channel}),
            "chain:B": frozenset({channel}),
        }
        deps = {"chain:A": ("leaf",), "chain:B": ("chain:A",)}
        graph = dc.build_contract_graph(deps, sensitivity)
        report = graph.impact_of(["leaf"], channel=channel)
        assert {p.node_id for p in report.affected} == {"chain:A", "chain:B"}, channel


def test_multi_hop_chain_breaks_when_an_intermediate_hop_is_not_sensitive() -> None:
    """Gate power for the multi-hop proof above: if `chain:B` were NOT
    declared sensitive to LOCATOR, no edge would carry the channel past it and
    `chain:C` would be unreachable. Confirms the multi-hop result above is
    because of real channel-filtered propagation, not because `impact_of`
    ignores the channel filter."""
    sensitivity = {
        "chain:A": frozenset({DependencyChannel.LOCATOR}),
        "chain:B": frozenset(),  # declared insensitive -- breaks the chain
        "chain:C": frozenset({DependencyChannel.LOCATOR}),
    }
    deps = {"chain:A": ("leaf",), "chain:B": ("chain:A",), "chain:C": ("chain:B",)}
    graph = dc.build_contract_graph(deps, sensitivity)
    report = graph.impact_of(["leaf"], channel=DependencyChannel.LOCATOR)
    assert {p.node_id for p in report.affected} == {"chain:A"}, (
        "chain:B declared no channels produces no edge at all (DependencyEdge "
        "refuses an empty channel set), so the walk must stop there"
    )


# ---------------------------------------------------------------------------
# Task 4 -- artifact representation, not just edges: adversarial per-channel
# check that a dependency edge existing is not sufficient, because
# `selective_build.build_all`'s real `section:` digest does not read the
# facet that changed.


def test_locator_facet_moves_productions_real_digest() -> None:
    """INC-V2-038's representation half, now closed and guarded here.

    This test was written as `..._is_absent_from_productions_real_digest` and
    asserted the opposite: `build_all`'s `section:` spec read only
    `{logical_id, semantic_text}`, so a moved evidence anchor left the digest
    untouched. It said in its own message that if it ever failed, the defect had
    been fixed and the test -- not the contract -- should be revisited. It
    failed, the defect is fixed (`selective_build.SECTION_FACET_KEYS`), and this
    is that revision.

    Direction matters. A rebuild that emits identical bytes because the facet
    that moved is absent from the representation is not a repair, and an
    equivalence check comparing clean bytes to selective bytes would have read
    agreement out of a facet the artifact never held.
    """
    case = cc.referential_case()
    assert case.prior_value is not None and case.rebuilt_value is not None
    assert case.prior_value != case.rebuilt_value


def test_locator_facet_is_present_in_the_reference_faceted_digest() -> None:
    """Same facet, a representation that actually reads it: proves the
    blindness above is a property of `build_all`'s formula, not an artifact of
    digests being insensitive to everything."""
    before = UnitSnapshot(logical_id="u:1", text="same text", evidence_id="e:orig")
    after = UnitSnapshot(logical_id="u:1", text="same text", evidence_id="e:moved")
    assert dc.faceted_section_digest(before) != dc.faceted_section_digest(after)


def test_temporal_facet_moves_productions_real_digest() -> None:
    """See the locator test above: same reversal, same reason."""
    case = cc.temporal_case()
    assert case.prior_value is not None and case.rebuilt_value is not None
    assert case.prior_value != case.rebuilt_value


def test_temporal_facet_is_present_in_the_reference_faceted_digest() -> None:
    before = UnitSnapshot(logical_id="u:1", text="same text", temporal_fingerprint="t1")
    after = UnitSnapshot(logical_id="u:1", text="same text", temporal_fingerprint="t2")
    assert dc.faceted_section_digest(before) != dc.faceted_section_digest(after)


def test_metadata_facet_moves_productions_real_digest() -> None:
    """See the locator test above: same reversal, same reason."""
    case = cc.descriptive_case()
    assert case.prior_value is not None and case.rebuilt_value is not None
    assert case.prior_value != case.rebuilt_value


def test_metadata_facet_is_present_in_the_reference_faceted_digest() -> None:
    before = UnitSnapshot(logical_id="u:1", text="same text", metadata_fingerprint="m1")
    after = UnitSnapshot(logical_id="u:1", text="same text", metadata_fingerprint="m2")
    assert dc.faceted_section_digest(before) != dc.faceted_section_digest(after)


def test_semantic_positive_control_productions_digest_is_not_blind() -> None:
    """Positive control for the three adversarial checks above: SEMANTIC's
    text facet DOES move production's real digest. Without this, "production
    digest is blind" could vacuously describe every facet regardless of
    whether this check has any power to detect a representation that reacts."""
    case = cc.semantic_case()
    assert case.prior_value is not None and case.rebuilt_value is not None
    assert case.prior_value != case.rebuilt_value
