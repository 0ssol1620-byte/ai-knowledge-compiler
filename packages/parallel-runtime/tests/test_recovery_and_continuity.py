from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from akc_parallel_runtime import (
    BlockKind,
    ContinuityEdge,
    ContinuityEdgeKind,
    ContinuityMergeConflict,
    ContinuityMerger,
    EventJournal,
    MarginalRole,
    ParsedBlock,
    PreprocessingVariant,
    RecoveryCandidate,
    RecoveryConflictError,
    RecoveryPlanner,
    RecoveryScope,
    RegionLevel,
    ShardOutput,
    TableIdentity,
    ValidationLevel,
    ValidationResult,
    VerificationState,
    canonical_sha256,
)
from helpers import HASH_A, HASH_B, HASH_C, NOW, receipt


def scope(level: RegionLevel, name: str) -> RecoveryScope:
    return RecoveryScope(level=level, scope_id=name, source_refs=(f"source://{name}",))


def validation(passed: bool = True) -> ValidationResult:
    return ValidationResult(
        passed=passed,
        hard_failure_count=0 if passed else 1,
        results=(),
        findings=(),
        digest=canonical_sha256({"passed": passed}),
    )


def block(
    block_id: str,
    page: int,
    order: int,
    kind: BlockKind,
    text: str,
    **overrides: object,
) -> ParsedBlock:
    values: dict[str, object] = {
        "block_id": block_id,
        "page_id": f"p{page + 1}",
        "page_index0": page,
        "order": order,
        "kind": kind,
        "text": text,
        "source_refs": (f"source://p{page + 1}/{block_id}",),
    }
    values.update(overrides)
    return ParsedBlock(**values)  # type: ignore[arg-type]


def edge(
    source: str, target: str, kind: ContinuityEdgeKind
) -> ContinuityEdge:
    return ContinuityEdge(
        from_block_id=source,
        to_block_id=target,
        kind=kind,
        evidence=(receipt(ValidationLevel.TRANSPORT),),
    )


def test_recovery_chooses_smallest_source_localized_scope() -> None:
    scopes = (
        scope(RegionLevel.PAGE, "page-1"),
        scope(RegionLevel.CELL, "cell-A1"),
        scope(RegionLevel.ROW, "row-1"),
    )
    assert RecoveryPlanner.smallest_scope(scopes).level is RegionLevel.CELL


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            "authority_numeric_mismatch",
            PreprocessingVariant.NATIVE_AUTHORITY_RECONSTRUCTION,
        ),
        ("numeric_character_ambiguity", PreprocessingVariant.OCR_EXACT),
        ("cropped_region", PreprocessingVariant.CROP_MARGIN),
        ("rotation_detected", PreprocessingVariant.ROTATE),
        ("photographed_low_quality", PreprocessingVariant.DEWARP),
        ("page_coverage_mismatch", PreprocessingVariant.PAGE_RERENDER_ALT_PARSER),
        ("table_cut_detected", PreprocessingVariant.OVERLAPPING_TILE),
        ("repetition_detected", PreprocessingVariant.CANDIDATE_REJECT),
        ("reading_order_invalid", PreprocessingVariant.LAYOUT_SPECIALIST),
        ("bbox_invalid", PreprocessingVariant.SOURCE_REMAP),
    ],
)
def test_recovery_variant_is_failure_specific(
    failure: str, expected: PreprocessingVariant
) -> None:
    selected = RecoveryPlanner.choose_variant(
        frozenset({failure}), scope(RegionLevel.REGION, "region-1")
    )
    assert selected is expected


def test_row_omission_uses_overlap_recovery() -> None:
    selected = RecoveryPlanner.choose_variant(
        frozenset({"row_omission"}), scope(RegionLevel.TABLE, "table-1")
    )
    assert selected is PreprocessingVariant.OVERLAPPING_TILE


def test_recovery_task_is_deterministic_idempotent_and_conflict_safe() -> None:
    planner = RecoveryPlanner()
    arguments = {
        "base_attempt_id": "attempt-1",
        "base_prediction_sha256": HASH_A,
        "scopes": (scope(RegionLevel.CELL, "cell-1"),),
        "failure_codes": frozenset({"numeric_character_ambiguity"}),
        "parser_recipe": "numeric-specialist-v1",
        "created_at": NOW,
        "idempotency_key": "recovery-1",
    }
    first = planner.plan(**arguments)
    assert planner.plan(**arguments) is first
    with pytest.raises(RecoveryConflictError):
        planner.plan(
            **{
                **arguments,
                "parser_recipe": "different-v2",
            }
        )


def test_recovery_escalates_one_scope_at_a_time() -> None:
    cell = scope(RegionLevel.CELL, "cell")
    row = scope(RegionLevel.ROW, "row")
    page = scope(RegionLevel.PAGE, "page")
    assert RecoveryPlanner.next_broader_scope(cell, (page, row)) == row
    assert RecoveryPlanner.next_broader_scope(page, (cell, row)) is None


def test_recovery_acceptance_preserves_base_diff_evidence_and_lineage() -> None:
    events = EventJournal()
    planner = RecoveryPlanner(events=events)
    task = planner.plan(
        base_attempt_id="attempt-base",
        base_prediction_sha256=HASH_A,
        scopes=(scope(RegionLevel.CELL, "cell-1"),),
        failure_codes=frozenset({"numeric_character_ambiguity"}),
        parser_recipe="numeric-specialist-v1",
        created_at=NOW,
        idempotency_key="recovery-1",
    )
    candidate = RecoveryCandidate(
        task=task,
        repair_attempt_id="attempt-repair",
        prediction_sha256=HASH_B,
        diff_sha256=HASH_C,
        validation=validation(),
        source_evidence=(receipt(ValidationLevel.TRANSPORT),),
        base_independent_family="primary-model",
        repair_independent_family="independent-repair-model",
    )
    decision = planner.accept(
        candidate,
        completed_at=NOW + timedelta(seconds=1),
    )
    assert planner.accept(candidate, completed_at=NOW + timedelta(seconds=2)) is decision
    assert decision.accepted is True
    assert decision.state is VerificationState.AUTO_REPAIRED
    assert decision.base_prediction_sha256 == HASH_A
    assert decision.repaired_prediction_sha256 == HASH_B
    assert [event.event_type for event in events.events()] == [
        "recovery.region.requested.v1",
        "recovery.planned.v1",
        "recovery.started.v1",
        "recovery.validated.v1",
        "region.verified.v1",
        "recovery.completed.v1",
    ]
    with pytest.raises(RecoveryConflictError, match="already completed"):
        planner.accept(
            replace(candidate, prediction_sha256=HASH_C, diff_sha256=HASH_B),
            completed_at=NOW + timedelta(seconds=3),
        )


@pytest.mark.parametrize(
    "failure_mode", ["invalid", "no_change", "no_evidence", "same_family"]
)
def test_recovery_rejects_weak_acceptance_evidence(failure_mode: str) -> None:
    planner = RecoveryPlanner()
    task = planner.plan(
        base_attempt_id="attempt-base",
        base_prediction_sha256=HASH_A,
        scopes=(scope(RegionLevel.CELL, "cell-1"),),
        failure_codes=frozenset({"numeric_character_ambiguity"}),
        parser_recipe="numeric-specialist-v1",
        created_at=NOW,
        idempotency_key="recovery-1",
    )
    candidate = RecoveryCandidate(
        task=task,
        repair_attempt_id="attempt-repair",
        prediction_sha256=HASH_A if failure_mode == "no_change" else HASH_B,
        diff_sha256=HASH_C,
        validation=validation(failure_mode != "invalid"),
        source_evidence=(
            ()
            if failure_mode == "no_evidence"
            else (receipt(ValidationLevel.TRANSPORT),)
        ),
        base_independent_family="primary-model",
        repair_independent_family=(
            "primary-model" if failure_mode == "same_family" else "repair-model"
        ),
    )
    decision = planner.accept(candidate, completed_at=NOW)
    assert decision.accepted is False
    assert decision.state is VerificationState.UNRESOLVED
    if failure_mode == "same_family":
        assert "recovery_independent_family_missing" in decision.reason_codes


def test_context_blocks_are_not_promoted_as_owned_output() -> None:
    output = ShardOutput(
        shard_id="s1",
        primary_page_ids=("p1",),
        context_page_ids=("p2",),
        blocks=(
            block("owned", 0, 0, BlockKind.PARAGRAPH, "Owned"),
            block("context", 1, 0, BlockKind.PARAGRAPH, "Context only"),
        ),
    )
    result = ContinuityMerger().merge(
        document_version_id="docv-1",
        outputs=(
            output,
            ShardOutput(
                shard_id="s2",
                primary_page_ids=("p2",),
                context_page_ids=("p1",),
                blocks=(block("owned-2", 1, 0, BlockKind.PARAGRAPH, "Page two"),),
            ),
        ),
        edges=(),
        expected_page_ids=("p1", "p2"),
        occurred_at=NOW,
        idempotency_key="merge-1",
    )
    provenance = {item for merged in result.blocks for item in merged.provenance_block_ids}
    assert result.accepted is True
    assert "context" not in provenance
    assert provenance == {"owned", "owned-2"}


def test_paragraph_continuation_merges_with_complete_provenance() -> None:
    outputs = (
        ShardOutput(
            "s1",
            ("p1",),
            ("p2",),
            (block("a", 0, 0, BlockKind.PARAGRAPH, "A sentence"),),
        ),
        ShardOutput(
            "s2",
            ("p2",),
            ("p1",),
            (block("b", 1, 0, BlockKind.PARAGRAPH, "continues here."),),
        ),
    )
    result = ContinuityMerger().merge(
        document_version_id="docv-1",
        outputs=outputs,
        edges=(edge("a", "b", ContinuityEdgeKind.CONTINUES),),
        expected_page_ids=("p1", "p2"),
        occurred_at=NOW,
        idempotency_key="merge-1",
    )
    assert result.accepted is True
    assert len(result.blocks) == 1
    assert result.blocks[0].text == "A sentence continues here."
    assert result.blocks[0].provenance_block_ids == ("a", "b")


def test_cross_page_table_merges_only_with_identical_table_identity() -> None:
    identity = TableIdentity(("Amount",), (100,), "Revenue", "USD")
    table_a = block(
        "a",
        0,
        0,
        BlockKind.TABLE,
        "| Amount |\n|---|\n| 1 |",
        table_identity=identity,
        table_row_count=1,
    )
    table_b = block(
        "b",
        1,
        0,
        BlockKind.TABLE,
        "| 2 |",
        table_identity=identity,
        table_row_count=1,
    )
    result = ContinuityMerger().merge(
        document_version_id="docv-1",
        outputs=(
            ShardOutput("s1", ("p1",), (), (table_a,)),
            ShardOutput("s2", ("p2",), (), (table_b,)),
        ),
        edges=(edge("a", "b", ContinuityEdgeKind.SAME_TABLE),),
        expected_page_ids=("p1", "p2"),
        occurred_at=NOW,
        idempotency_key="merge-table",
    )
    assert result.accepted is True
    assert result.blocks[0].table_row_count == 2
    mismatched = replace(
        table_b,
        table_identity=TableIdentity(("Different",), (100,), "Revenue", "USD"),
    )
    with pytest.raises(ContinuityMergeConflict, match="identity mismatch"):
        ContinuityMerger().merge(
            document_version_id="docv-2",
            outputs=(
                ShardOutput("s1", ("p1",), (), (table_a,)),
                ShardOutput("s2", ("p2",), (), (mismatched,)),
            ),
            edges=(edge("a", "b", ContinuityEdgeKind.SAME_TABLE),),
            expected_page_ids=("p1", "p2"),
            occurred_at=NOW,
            idempotency_key="merge-table-bad",
        )


def test_cross_page_table_identity_uses_normalized_header() -> None:
    upper = TableIdentity(("AMOUNT",), (100,), "Revenue", "USD")
    lower = TableIdentity((" amount ",), (100,), " revenue ", "usd")
    result = ContinuityMerger().merge(
        document_version_id="docv-normalized-table",
        outputs=(
            ShardOutput(
                "s1",
                ("p1",),
                (),
                (
                    block(
                        "a",
                        0,
                        0,
                        BlockKind.TABLE,
                        "| AMOUNT |",
                        table_identity=upper,
                        table_row_count=1,
                    ),
                ),
            ),
            ShardOutput(
                "s2",
                ("p2",),
                (),
                (
                    block(
                        "b",
                        1,
                        0,
                        BlockKind.TABLE,
                        "| 100 |",
                        table_identity=lower,
                        table_row_count=1,
                    ),
                ),
            ),
        ),
        edges=(edge("a", "b", ContinuityEdgeKind.SAME_TABLE),),
        expected_page_ids=("p1", "p2"),
        occurred_at=NOW,
        idempotency_key="normalized-table",
    )
    assert result.accepted is True


def test_repeated_headers_and_footers_are_removed_by_stable_fingerprint() -> None:
    outputs = (
        ShardOutput(
            "s1",
            ("p1",),
            (),
            (
                block(
                    "header-1",
                    0,
                    0,
                    BlockKind.PARAGRAPH,
                    "CONFIDENTIAL",
                    marginal_role=MarginalRole.HEADER,
                ),
                block("body-1", 0, 1, BlockKind.PARAGRAPH, "First"),
            ),
        ),
        ShardOutput(
            "s2",
            ("p2",),
            (),
            (
                block(
                    "header-2",
                    1,
                    0,
                    BlockKind.PARAGRAPH,
                    "CONFIDENTIAL",
                    marginal_role=MarginalRole.HEADER,
                ),
                block("body-2", 1, 1, BlockKind.PARAGRAPH, "Second"),
            ),
        ),
    )
    result = ContinuityMerger().merge(
        document_version_id="docv-1",
        outputs=outputs,
        edges=(),
        expected_page_ids=("p1", "p2"),
        occurred_at=NOW,
        idempotency_key="marginals",
    )
    assert result.accepted is True
    assert result.dropped_marginal_block_ids == ("header-1", "header-2")
    assert result.markdown is not None and "CONFIDENTIAL" not in result.markdown


def test_merge_rejects_multiple_page_owners_and_ambiguous_graph() -> None:
    merger = ContinuityMerger()
    with pytest.raises(ContinuityMergeConflict, match="multiple primary owners"):
        merger.merge(
            document_version_id="docv-1",
            outputs=(
                ShardOutput("s1", ("p1",), (), (block("a", 0, 0, BlockKind.PARAGRAPH, "A"),)),
                ShardOutput("s2", ("p1",), (), (block("b", 0, 1, BlockKind.PARAGRAPH, "B"),)),
            ),
            edges=(),
            expected_page_ids=("p1",),
            occurred_at=NOW,
            idempotency_key="bad-owner",
        )


def test_heading_depth_jump_fails_merge_validator_and_withholds_markdown() -> None:
    result = ContinuityMerger().merge(
        document_version_id="docv-1",
        outputs=(
            ShardOutput(
                "s1",
                ("p1",),
                (),
                (
                    block("h1", 0, 0, BlockKind.HEADING, "One", heading_depth=1),
                    block("h4", 0, 1, BlockKind.HEADING, "Four", heading_depth=4),
                ),
            ),
        ),
        edges=(),
        expected_page_ids=("p1",),
        occurred_at=NOW,
        idempotency_key="heading-jump",
    )
    assert result.accepted is False
    assert result.markdown is None
    assert result.reason_codes == ("heading_depth_jump",)


def test_figure_caption_and_footnote_relationships_control_final_order() -> None:
    output = ShardOutput(
        "s1",
        ("p1",),
        (),
        (
            block("caption", 0, 0, BlockKind.CAPTION, "Figure 1"),
            block("footnote", 0, 1, BlockKind.FOOTNOTE, "Source note"),
            block("figure", 0, 2, BlockKind.FIGURE, "[image]"),
        ),
    )
    result = ContinuityMerger().merge(
        document_version_id="docv-1",
        outputs=(output,),
        edges=(
            edge("caption", "figure", ContinuityEdgeKind.CAPTION_OF),
            edge("footnote", "figure", ContinuityEdgeKind.FOOTNOTE_OF),
        ),
        expected_page_ids=("p1",),
        occurred_at=NOW,
        idempotency_key="relationships",
    )
    assert result.accepted is True
    assert [item.kind for item in result.blocks] == [
        BlockKind.FIGURE,
        BlockKind.CAPTION,
        BlockKind.FOOTNOTE,
    ]


def test_blank_owned_page_fails_page_coverage_validation() -> None:
    result = ContinuityMerger().merge(
        document_version_id="docv-1",
        outputs=(ShardOutput("s1", ("p1",), (), ()),),
        edges=(),
        expected_page_ids=("p1",),
        occurred_at=NOW,
        idempotency_key="blank-page",
    )
    assert result.accepted is False
    assert result.reason_codes == ("page_coverage_failed",)


def test_relationship_edge_cannot_reference_context_only_block() -> None:
    with pytest.raises(ContinuityMergeConflict, match="missing primary block"):
        ContinuityMerger().merge(
            document_version_id="docv-1",
            outputs=(
                ShardOutput(
                    "s1",
                    ("p1",),
                    ("p2",),
                    (
                        block("figure", 0, 0, BlockKind.FIGURE, "[image]"),
                        block("caption", 1, 0, BlockKind.CAPTION, "Context caption"),
                    ),
                ),
                ShardOutput(
                    "s2",
                    ("p2",),
                    ("p1",),
                    (block("actual-caption", 1, 0, BlockKind.CAPTION, "Actual"),),
                ),
            ),
            edges=(edge("caption", "figure", ContinuityEdgeKind.CAPTION_OF),),
            expected_page_ids=("p1", "p2"),
            occurred_at=NOW,
            idempotency_key="context-edge",
        )


def test_merge_idempotency_rejects_changed_input() -> None:
    merger = ContinuityMerger()
    output = ShardOutput(
        "s1", ("p1",), (), (block("a", 0, 0, BlockKind.PARAGRAPH, "A"),)
    )
    arguments = {
        "document_version_id": "docv-1",
        "outputs": (output,),
        "edges": (),
        "expected_page_ids": ("p1",),
        "occurred_at": NOW,
        "idempotency_key": "same",
    }
    first = merger.merge(**arguments)
    assert merger.merge(**arguments) is first
    changed = replace(output, blocks=(block("a", 0, 0, BlockKind.PARAGRAPH, "Changed"),))
    with pytest.raises(ContinuityMergeConflict, match="idempotency"):
        merger.merge(**{**arguments, "outputs": (changed,)})
