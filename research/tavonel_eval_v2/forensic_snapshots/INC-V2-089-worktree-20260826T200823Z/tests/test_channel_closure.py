"""INC-V2-038 closed, per channel, on both layers it lives on.

The defect had two halves and the second hides the first. Half one: a LOCATOR,
TEMPORAL or METADATA change is detected and correctly typed by the diff
(`EVIDENCE_MOVED`, `TEMPORAL_CHANGED`, `METADATA_CHANGED`) and then reaches
nothing -- `changed_logical_ids` admits only SEMANTIC and GRAPH, and
`selective_build.graph_for` emitted no edge carrying any of the three, so the
artifact that reads the moved unit was labelled `CURRENT, "no change reached
it"`. Half two: `build_all`'s `section:` spec was `{"logical_id",
"semantic_text"}`, so even with the edge restored a clean rebuild and a
selective rebuild emit identical bytes for those channels, and an equivalence
check reports agreement while the defect stands.

So each channel below is proven twice, and the two proofs are independent:

    EDGE          a typed change on the channel reaches the artifact that
                  declared itself sensitive to that facet, and reaches only
                  that artifact
    REPRESENTATION
                  two revisions differing in that facet alone produce
                  different `section:` digests -- the rebuilt bytes actually
                  move, so the edge fix is observable

Plus the two properties that keep the fix from being a widening:

    REFUSAL       a graph that declared no facet does not silently propagate
                  and does not silently drop either: the change resolves to
                  `FacetVerdict.UNRESOLVED` and is recorded on the plan
    CONTAINMENT   a facet change does not drag document-level aggregates in,
                  and a semantic edit's rebuild set is byte-identical to what
                  it was before the fix

`compiler/channel_cases.py` and `compiler/e9_oracle.py` are the measurement
this file's fix answers to; neither is modified and neither is re-implemented
here. What this file adds is the representation half, which E9 cannot see:
E9 compares seed sets, and a seed set is equal whether or not the artifact it
names can express the change.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "compiler"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import pytest  # noqa: E402

from akc_cir.dependency import (  # noqa: E402
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)
from akc_cir.recompilation import (  # noqa: E402
    ArtifactState,
    FacetPolicy,
    FacetVerdict,
    StructuralPolicy,
    plan_recompilation,
)
from akc_cir.semantic_diff import (  # noqa: E402
    ChangeChannel,
    ChangeKind,
    DiffLevel,
    SemanticChange,
    diff_documents,
)
from compiler import channel_cases as cc  # noqa: E402
from compiler import e9_oracle  # noqa: E402
from compiler import selective_build as engine  # noqa: E402

#: (facet key on the canonical document's unit, the value to move it to, the
#: ChangeChannel the diff types that move as, the DependencyChannel an edge
#: must carry for it). One row per channel INC-V2-038 names.
FACETS: tuple[tuple[str, str, ChangeChannel, DependencyChannel], ...] = (
    ("evidence_id", "e:moved-anchor", ChangeChannel.LOCATOR, DependencyChannel.LOCATOR),
    (
        "temporal_fingerprint",
        "effective_time:2027-01-01",
        ChangeChannel.TEMPORAL,
        DependencyChannel.TEMPORAL,
    ),
    (
        "metadata_fingerprint",
        "language:fr-CA",
        ChangeChannel.METADATA,
        DependencyChannel.METADATA,
    ),
)

IDS = [facet[2].value for facet in FACETS]


def _pair(facet_key: str, value: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Two real canonical documents whose text is byte-identical and whose
    second unit differs in exactly one declared facet.

    `channel_cases`' cases inject the facet into the `UnitSnapshot` list after
    `snapshots()` has run, which is right for what they measure (the diff) but
    leaves `build_all` -- which reads the *document* -- looking at two
    identical revisions. The representation half cannot be seen from there at
    all. Here the facet is declared on the document, which is where a real
    source carries it, so the same value flows into both the diff and the
    artifact.

    The AFTER revision carries a distinct `source_digest`. That is not a
    convenience: `diff_documents` computes `content_changed` as
    `before_sha256 != after_sha256` and returns an empty diff when it is False
    (`semantic_diff.py:607`), so a facet re-derived over a byte-identical
    payload -- a re-OCR that moves an anchor, a re-resolved effective time --
    is invisible to the diff before any of this lane's machinery is reached.
    `channel_cases` sidesteps the same gate by forcing a distinct
    `after_sha256`. That gate is upstream of INC-V2-038 and is NOT closed
    here; `test_a_byte_identical_payload_is_invisible_upstream_of_this_fix`
    below pins it as a known open finding rather than leaving it implied.
    """
    before = cc.document(cc.markdown(cc.BODY_ALPHA, cc.BODY_BETA), "v1")
    after = copy.deepcopy(before)
    after["version_id"] = "v2"
    after["source_digest"] = "sha256:" + "9" * 64
    after["units"][1][facet_key] = value
    return before, after


def _diff_for(before: dict[str, Any], after: dict[str, Any]):
    before_units, before_shape = engine.snapshots(before)
    after_units, after_shape = engine.snapshots(after)
    return diff_documents(
        before_sha256=before["source_digest"],
        after_sha256=after["source_digest"],
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=after_units,
        source=after["source_id"],
    )


def _moved_id(document: dict[str, Any]) -> str:
    return engine.logical_id(document["source_id"], document["units"][1]["explicit_path"])


# ---------------------------------------------------------------------------
# EDGE -- the change reaches the artifact, and reaches only it.


@pytest.mark.parametrize(("facet_key", "value", "change_channel", "dep_channel"), FACETS, ids=IDS)
def test_facet_change_reaches_the_artifact_that_declared_it(
    facet_key: str, value: str, change_channel: ChangeChannel, dep_channel: DependencyChannel
) -> None:
    before, after = _pair(facet_key, value)
    diff = _diff_for(before, after)
    assert diff.changed_logical_ids_for(change_channel), (
        f"fixture did not produce a {change_channel.value} change"
    )
    assert not diff.changed_logical_ids, (
        "fixture leaked a semantic seed; the channel is no longer isolated and a "
        "pass would prove nothing about this facet"
    )

    before_deps, _ = engine.inventory_and_dependencies(before)
    after_deps, _ = engine.inventory_and_dependencies(after)
    plan = plan_recompilation(
        diff=diff,
        graph=engine.graph_for(before_deps, after_deps),
        artifacts=sorted({*before_deps, *after_deps}),
        structural_policy=StructuralPolicy.PRECISE,
    )

    target = "section:" + _moved_id(after)
    assert target in plan.to_rebuild, (
        "INC-V2-038: the change was detected and typed and then reached nothing"
    )
    assert plan.explain(target) != "no change reached it"


@pytest.mark.parametrize(("facet_key", "value", "change_channel", "dep_channel"), FACETS, ids=IDS)
def test_facet_change_does_not_invalidate_the_document_aggregates(
    facet_key: str, value: str, change_channel: ChangeChannel, dep_channel: DependencyChannel
) -> None:
    """Containment. A system that rebuilds everything on every change is a
    different failure from one that rebuilds nothing, not a fix for it."""
    before, after = _pair(facet_key, value)
    diff = _diff_for(before, after)
    before_deps, _ = engine.inventory_and_dependencies(before)
    after_deps, _ = engine.inventory_and_dependencies(after)
    plan = plan_recompilation(
        diff=diff,
        graph=engine.graph_for(before_deps, after_deps),
        artifacts=sorted({*before_deps, *after_deps}),
        structural_policy=StructuralPolicy.PRECISE,
    )

    assert set(plan.to_rebuild) == {"section:" + _moved_id(after)}, (
        "a one-unit facet move must invalidate one section artifact; "
        f"got {sorted(plan.to_rebuild)}"
    )


# ---------------------------------------------------------------------------
# REPRESENTATION -- adversarial, per channel. A rebuild that emits identical
# bytes because the facet is absent from the artifact is not a repair.


@pytest.mark.parametrize(("facet_key", "value", "change_channel", "dep_channel"), FACETS, ids=IDS)
def test_section_digest_moves_when_only_this_facet_moves(
    facet_key: str, value: str, change_channel: ChangeChannel, dep_channel: DependencyChannel
) -> None:
    before, after = _pair(facet_key, value)
    assert before["units"][1]["text"] == after["units"][1]["text"], (
        "the fixture must move the facet and nothing else"
    )

    prior = engine.build_all(before)
    rebuilt = engine.build_all(after)
    target = "section:" + _moved_id(after)

    assert prior[target] != rebuilt[target], (
        "production's section: digest is still blind to this facet, so a "
        "selective rebuild and a clean rebuild emit identical bytes and an "
        "equivalence check would report agreement over an untouched defect"
    )
    unchanged = "section:" + engine.logical_id(
        after["source_id"], after["units"][0]["explicit_path"]
    )
    assert prior[unchanged] == rebuilt[unchanged], (
        "the digest must move for the unit whose facet moved and no other; a "
        "digest that moves for everything proves nothing"
    )


@pytest.mark.parametrize(("facet_key", "value", "change_channel", "dep_channel"), FACETS, ids=IDS)
def test_selective_run_actually_emits_the_moved_bytes(
    facet_key: str, value: str, change_channel: ChangeChannel, dep_channel: DependencyChannel
) -> None:
    """Both halves at once, through the real executor: the artifact is rebuilt
    rather than carried, and what it activates is the AFTER revision's bytes.
    """
    before, after = _pair(facet_key, value)
    result = engine.run_pair(before, after)
    target = "section:" + _moved_id(after)

    assert target in result["selective_rebuild_set"]
    assert target not in result["carried_forward_set"]
    assert result["state"][target] == engine.build_all(after)[target]
    assert result["state"][target] != engine.build_all(before)[target]
    assert target not in result["unnecessary_rebuild_set"], (
        "the rebuild must have been necessary -- prior and rebuilt bytes differ"
    )


def test_a_facet_blind_document_keeps_its_stored_digests() -> None:
    """The representation change is additive. A revision that declares no
    facet produces exactly the digest it produced before INC-V2-038, so no
    stored corpus or receipt is invalidated by this fix."""
    document = cc.document(cc.markdown(cc.BODY_ALPHA, cc.BODY_BETA), "v1")
    identifier = engine.logical_id(
        document["source_id"], document["units"][0]["explicit_path"]
    )
    legacy = engine._digest(
        {"logical_id": identifier, "semantic_text": document["units"][0]["text"]}
    )
    assert engine.build_all(document)["section:" + identifier] == legacy


# ---------------------------------------------------------------------------
# REFUSAL -- an undeclared graph neither guesses an edge nor swallows the
# change.


@pytest.mark.parametrize(("facet_key", "value", "change_channel", "dep_channel"), FACETS, ids=IDS)
def test_an_undeclared_graph_records_the_change_instead_of_dropping_it(
    facet_key: str, value: str, change_channel: ChangeChannel, dep_channel: DependencyChannel
) -> None:
    before, after = _pair(facet_key, value)
    diff = _diff_for(before, after)
    moved = _moved_id(after)
    # `channels` left at the constructor default: this adapter has said
    # nothing about facets.
    undeclared = DependencyGraph([DependencyEdge("chunk:x", moved, EdgeType.DEPENDS_ON)])

    plan = plan_recompilation(diff=diff, graph=undeclared, artifacts=["chunk:x"])

    assert plan.to_rebuild == (), (
        "an undeclared edge must not be read as permission to propagate; that "
        "is StructuralPolicy.ALWAYS's measured failure in a new place"
    )
    resolutions = plan.unresolved_facet_changes
    assert [r.change_channel for r in resolutions] == [change_channel]
    assert resolutions[0].verdict is FacetVerdict.UNRESOLVED
    assert resolutions[0].seeds == (moved,)
    assert plan.explain("chunk:x") == "no change reached it"
    assert "facet_resolutions" in plan.as_record(), (
        "the refusal has to survive serialisation, or a study reading stored "
        "plan records sees the pre-INC-V2-038 silence again"
    )


@pytest.mark.parametrize(("facet_key", "value", "change_channel", "dep_channel"), FACETS, ids=IDS)
def test_the_fail_closed_policy_is_reachable_not_decorative(
    facet_key: str, value: str, change_channel: ChangeChannel, dep_channel: DependencyChannel
) -> None:
    """`FacetPolicy.ALL_EDGES` reads the all-channels default as a declaration
    and rebuilds. The default does not, and records why. A policy nobody can
    make fire is not a policy, so both readings are exercised on the same
    graph."""
    before, after = _pair(facet_key, value)
    diff = _diff_for(before, after)
    moved = _moved_id(after)
    undeclared = DependencyGraph([DependencyEdge("chunk:x", moved, EdgeType.DEPENDS_ON)])

    strict = plan_recompilation(
        diff=diff,
        graph=undeclared,
        artifacts=["chunk:x"],
        facet_policy=FacetPolicy.ALL_EDGES,
    )
    assert strict.to_rebuild == ("chunk:x",)
    assert [r.verdict for r in strict.facet_resolutions] == [FacetVerdict.SEED_SET]

    off = plan_recompilation(
        diff=diff, graph=undeclared, artifacts=["chunk:x"], facet_policy=FacetPolicy.OFF
    )
    assert off.to_rebuild == ()
    assert [r.verdict for r in off.facet_resolutions] == [FacetVerdict.UNRESOLVED]


def test_a_narrowed_edge_that_omits_the_facet_does_not_carry_it() -> None:
    """Declaring *a* narrower channel set is not declaring *this* facet. The
    gate is per channel, not a graph-wide "this adapter thought about
    channels" flag."""
    before, after = _pair("evidence_id", "e:moved-anchor")
    diff = _diff_for(before, after)
    moved = _moved_id(after)
    semantic_only = DependencyGraph(
        [
            DependencyEdge(
                "chunk:x",
                moved,
                EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.SEMANTIC}),
            )
        ]
    )
    plan = plan_recompilation(diff=diff, graph=semantic_only, artifacts=["chunk:x"])
    assert plan.to_rebuild == ()
    assert [r.verdict for r in plan.unresolved_facet_changes] == [FacetVerdict.UNRESOLVED]


def test_a_declared_reader_outside_the_inventory_is_no_dependent_not_unresolved() -> None:
    """The middle verdict, proven where it applies: the facet is declared, the
    traversal ran and reached something, and nothing it reached is rebuildable.
    That is an answer, and it must not be reported as a refusal."""
    before, after = _pair("evidence_id", "e:moved-anchor")
    diff = _diff_for(before, after)
    moved = _moved_id(after)
    graph = DependencyGraph(
        [
            DependencyEdge(
                "chunk:x",
                moved,
                EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.LOCATOR}),
            )
        ]
    )
    plan = plan_recompilation(diff=diff, graph=graph, artifacts=["chunk:unrelated"])
    assert [r.verdict for r in plan.facet_resolutions] == [FacetVerdict.NO_DEPENDENT]
    assert plan.to_rebuild == ()


# ---------------------------------------------------------------------------
# CONTAINMENT -- the channels that already worked are untouched.


def test_a_semantic_edit_rebuilds_exactly_what_it_did_before() -> None:
    """The blast-radius control. `graph_for` gained facet channels by union,
    never by replacement, so no SEMANTIC or STRUCTURAL edge lost anything and
    a text-only edit's rebuild set is unchanged."""
    result = cc.semantic_case().result
    assert result is not None
    assert sorted(result["affected_subgraph"]) == sorted(result["selective_rebuild_set"])
    key = engine.doc_key(cc.LINEAGE)
    changed = sorted(a for a in result["selective_rebuild_set"] if a.startswith("section:"))
    assert len(changed) == 1
    assert set(result["selective_rebuild_set"]) == {
        changed[0],
        "document-index:" + key,
        "topic-bucket:" + key + ":3",
    }
    assert "structure-map:" + key in result["carried_forward_set"]


def test_a_semantic_edit_declares_no_facet_change() -> None:
    """A text edit must not start producing facet resolutions; an empty tuple
    here is what keeps E9's denominator honest."""
    before = cc.document(cc.markdown(cc.BODY_ALPHA, cc.BODY_BETA), "v1")
    after = cc.document(
        cc.markdown(cc.BODY_ALPHA, cc.BODY_BETA.replace("reporting obligation", "disclosure duty")),
        "v2",
    )
    diff = _diff_for(before, after)
    before_deps, _ = engine.inventory_and_dependencies(before)
    after_deps, _ = engine.inventory_and_dependencies(after)
    plan = plan_recompilation(
        diff=diff,
        graph=engine.graph_for(before_deps, after_deps),
        artifacts=sorted({*before_deps, *after_deps}),
        structural_policy=StructuralPolicy.PRECISE,
    )
    assert plan.facet_resolutions == ()
    assert "facet_resolutions" not in plan.as_record()


@pytest.mark.parametrize(("facet_key", "value", "change_channel", "dep_channel"), FACETS, ids=IDS)
def test_a_byte_identical_payload_is_invisible_upstream_of_this_fix(
    facet_key: str, value: str, change_channel: ChangeChannel, dep_channel: DependencyChannel
) -> None:
    """OPEN FINDING, not a closed one, pinned so it cannot be mistaken for
    coverage.

    `diff_documents` sets `content_changed = before_sha256 != after_sha256`
    and returns an empty diff when that is False. So a facet that moves while
    the source payload does not -- a re-OCR that relocates an anchor, an
    effective time re-resolved from an external authority, a language tag
    corrected -- produces no typed change at all, and INC-V2-038's fix never
    runs. Everything this file proves is conditional on the revision carrying
    a new source digest.

    Whether that gate is correct is a separate question from this lane's, and
    closing it would mean changing `semantic_diff`, which this lane does not
    own. This test states the behaviour so a later reader finds it recorded
    rather than discovering it as a second silent disappearance.
    """
    before, after = _pair(facet_key, value)
    after["source_digest"] = before["source_digest"]  # same bytes, facet moved
    diff = _diff_for(before, after)

    assert diff.content_changed is False
    assert [c.channel for c in diff.changes] == [ChangeChannel.UNCHANGED], (
        "the diff reports one CONTENT_UNCHANGED observation and no typed change "
        "of any kind -- the facet move is not merely unrouted, it is unseen"
    )
    result = engine.run_pair(before, after)
    assert result["e9_channel_closure"]["could_have_exhibited"] is False
    assert result["e9_channel_closure"]["no_power_reason"]
    # And the artifact really would have differed, which is what makes this a
    # finding rather than a non-event.
    target = "section:" + _moved_id(after)
    assert engine.build_all(before)[target] != engine.build_all(after)[target]
    assert target in result["carried_forward_set"]


# ---------------------------------------------------------------------------
# The oracle this fix answers to, run unmodified.


def test_e9_passes_on_all_five_channels() -> None:
    results = e9_oracle.run_all()
    assert [r.channel_name for r in results] == [
        "SEMANTIC",
        "STRUCTURAL",
        "LOCATOR",
        "TEMPORAL",
        "METADATA",
    ]
    assert [r.verdict for r in results] == ["PASS"] * 5, {
        r.channel_name: (r.verdict, sorted(r.silent_disappearance)) for r in results
    }
    assert not any(r.silent_disappearance for r in results)


# ---------------------------------------------------------------------------
# The per-pair E9 block a held-out study aggregates.


@pytest.mark.parametrize(("facet_key", "value", "change_channel", "dep_channel"), FACETS, ids=IDS)
def test_run_pair_reports_power_and_names_nothing_silent(
    facet_key: str, value: str, change_channel: ChangeChannel, dep_channel: DependencyChannel
) -> None:
    before, after = _pair(facet_key, value)
    block = engine.run_pair(before, after)["e9_channel_closure"]

    assert block["schema"] == engine.E9_SCHEMA
    assert block["could_have_exhibited"] is True, block["no_power_reason"]
    assert block["no_power_reason"] == ""
    assert change_channel.value in block["channels_detected"]
    assert block["expected"] == ["section:" + _moved_id(after)]
    assert block["silent"] == []
    assert block["silent_disappearance"] is False
    assert block["unresolved_facet_changes"] == []

    entry = next(e for e in block["per_channel"] if e["change_channel"] == change_channel.value)
    assert entry["supported"] is True
    assert entry["contract_verdict"] == "seed_set"
    assert entry["planner_facet_verdict"] == "seed_set"
    assert entry["counted_in_denominator"] is True


def test_a_pair_with_no_typed_change_has_no_power() -> None:
    """The denominator rule that decides whether E9 can be scored at all: a
    pair that could not have exhibited the failure must not enter it. Counting
    it is how an untested endpoint reports as well-tested."""
    document = cc.document(cc.markdown(cc.BODY_ALPHA, cc.BODY_BETA), "v1")
    block = engine.run_pair(document, copy.deepcopy(document))["e9_channel_closure"]
    assert block["could_have_exhibited"] is False
    assert block["no_power_reason"]
    assert block["silent"] == []


def test_an_unsupported_channel_is_excluded_with_a_reason_not_dropped() -> None:
    """A channel outside the contract's declared scope resolves to UNRESOLVED,
    stays visible in `per_channel`, and stays out of the denominator."""
    from compiler import dependency_contract as dc

    before, after = _pair("evidence_id", "e:moved-anchor")
    visual = SemanticChange(
        kind=ChangeKind.VISUAL_CHANGED, logical_id=_moved_id(after)
    )
    assert visual.channel is ChangeChannel.VISUAL
    before_deps, _ = engine.inventory_and_dependencies(before)
    decision = dc.decide_unit_change(visual, graph_reads=before_deps)
    assert decision.verdict is dc.Verdict.UNRESOLVED
    assert "outside this contract's declared scope" in decision.reason


def test_the_expected_side_is_not_derived_from_the_planner() -> None:
    """`to_rebuild` is `dict.fromkeys(stale + unresolved)`, so an expected side
    read off the plan would compare the planner to itself. This asserts the
    two sides can disagree: with the fix reverted by policy, `actual` empties
    while `expected` -- which comes from the declarative contract -- does not.
    """
    before, after = _pair("evidence_id", "e:moved-anchor")
    diff = _diff_for(before, after)
    before_deps, _ = engine.inventory_and_dependencies(before)
    after_deps, _ = engine.inventory_and_dependencies(after)
    reverted = plan_recompilation(
        diff=diff,
        graph=engine.graph_for(before_deps, after_deps),
        artifacts=sorted({*before_deps, *after_deps}),
        structural_policy=StructuralPolicy.PRECISE,
        facet_policy=FacetPolicy.OFF,
    )
    block = engine.e9_channel_closure(
        diff=diff, before_deps=before_deps, after_deps=after_deps, plan=reverted
    )
    target = "section:" + _moved_id(after)
    assert block["expected"] == [target]
    assert block["actual"] == []
    assert block["silent"] == [target], (
        "with propagation off the block must name the disappeared artifact; if "
        "it cannot, it could never detect the defect it exists to measure"
    )
    assert block["silent_disappearance"] is True
    assert block["could_have_exhibited"] is True
    assert [r["verdict"] for r in block["unresolved_facet_changes"]] == ["unresolved"]
    assert all(
        t.state is ArtifactState.CURRENT for t in reverted.targets if t.artifact_id == target
    )
