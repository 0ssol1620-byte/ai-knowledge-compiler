"""P0-A Personal E2E spine -- acceptance scenarios over real source files.

미션 §5의 스파인 수용 조건을 실제 디스크 파일로 검증한다:

(a) 최초 컴파일 -> WS-1 활성, 'current launch date' 질문에 October 15 CURRENT,
    evidence가 원본 파일 해시/위치를 참조한다.
(b) 파일 직접 수정(October 15 -> November 3) -> recompile -> WS-2 활성,
    답변 November 3 CURRENT, WS-1 시점 초안은 STALE로 재판정된다.
(c) rename -> identity continuity (logical_id 유지).
(d) 삭제 -> 의존 지식 무효화 (dependency chain 영향 전파).
(e) 동격 충돌 삽입 -> CONFLICT outcome (임의 선택 금지).
(f) 모호한 identity -> 리뷰 큐로 fail-closed 격리, 세계 나머지는 건강.
(g) 선택 재컴파일 == full rebuild (oracle), 변경 없으면 no-op world 유지.

Each scenario runs against its own temporary workspace compiled from
``make_demo_workspace``'s corpus, so they are order-independent.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_cir.answer_compiler import AnswerOutcome, compile_answer
from akc_cir.authority import ClaimContext
from akc_compiler_runtime import Pipeline, write_demo_workspace
from akc_compiler_runtime.demo import (
    GOVERNANCE_POLICY,
    LAUNCH_DELAY_MEMO,
    LAUNCH_PLAN,
    MEMO_CONTENT,
    ROADMAP_HINTS,
)

AS_OF = datetime(2026, 10, 1, tzinfo=UTC)
LAUNCH_QUESTION = "What is the current launch date?"
READINESS_QUESTION = "What does the readiness gate require?"
CONTEXT = ClaimContext(subject="workspace", as_of=AS_OF)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    write_demo_workspace(root)
    return root


@pytest.fixture()
def pipeline(tmp_path: Path) -> Pipeline:
    return Pipeline(tmp_path / "world-store")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# (a) first compile
# ---------------------------------------------------------------------------


def test_first_compile_answers_current_with_file_evidence(
    workspace: Path, pipeline: Pipeline
) -> None:
    result = pipeline.compile_workspace(workspace)

    # WS-1 is the active state, published atomically with a manifest.
    assert result.world_state_id == "WS-1"
    assert result.published and not result.no_op
    assert result.manifest_hash.startswith("sha256:")
    assert result.review_queue == ()

    answer = result.answer(LAUNCH_QUESTION)
    assert answer.outcome is AnswerOutcome.CURRENT
    assert len(answer.claim_ids) == 1
    winning_row = result.claims[answer.claim_ids[0]]
    assert "October 15" in str(winning_row["value"])
    # The informal kickoff note lost on authority, not on silence.
    assert "authority_rank" in answer.reason

    # Evidence cites the original file's location AND its bytes.
    occurrence = answer.evidence_occurrences[0]
    evidence = result.evidence_for(occurrence.evidence_id)
    assert evidence is not None
    assert evidence["rel_path"] == LAUNCH_PLAN
    assert evidence["sha256"] == _sha256(workspace / LAUNCH_PLAN)
    assert int(evidence["line_number"]) >= 1
    assert evidence["span"] == winning_row["value"]

    # Demo corpus structure the mission asked for: one future effective date
    # and one superseded fact, both visible in the compiled world.
    effective = [
        row
        for row in result.claims.values()
        if str(row.get("valid_from")) == "2027-01-01T00:00:00+00:00"
    ]
    assert effective and effective[0]["temporal_source"] == "explicit"
    assert any(
        "superseded" in str(row["value"]).casefold()
        and int(row["source_status"]) == 1  # SourceStatus.SUPERSEDED
        for row in result.claims.values()
    )


def test_effective_date_stays_dormant_until_it_takes_effect(
    workspace: Path, pipeline: Pipeline
) -> None:
    pipeline.compile_workspace(workspace)
    answer = pipeline.answer("What is the current support coverage?", as_of=AS_OF)
    assert answer.outcome is AnswerOutcome.CURRENT
    value = str(pipeline.store.load_world().claims[answer.claim_ids[0]]["value"])
    assert "Monday through Friday" in value
    assert "weekends" not in value

    future = pipeline.answer(
        "What is the current support coverage?",
        as_of=datetime(2027, 2, 1, tzinfo=UTC),
    )
    assert future.outcome is AnswerOutcome.CURRENT
    future_value = str(pipeline.store.load_world().claims[future.claim_ids[0]]["value"])
    assert "weekends" in future_value


# ---------------------------------------------------------------------------
# (b) direct file edit -> WS-2, flip, STALE re-judgement
# ---------------------------------------------------------------------------


def test_edit_flips_answer_and_rejudges_old_drafts_stale(
    workspace: Path, pipeline: Pipeline
) -> None:
    first = pipeline.compile_workspace(workspace)
    first_answer = first.answer(LAUNCH_QUESTION)
    assert first_answer.outcome is AnswerOutcome.CURRENT
    logical_id = first_answer.claim_ids[0]
    ws1_drafts = first.draft_claims(LAUNCH_QUESTION)
    assert all(draft.world_state_id == "WS-1" for draft in ws1_drafts)

    plan_file = workspace / LAUNCH_PLAN
    plan_file.write_text(
        plan_file.read_text(encoding="utf-8").replace("October 15", "November 3"),
        encoding="utf-8",
    )

    second = pipeline.recompile(workspace)
    assert second.published and not second.no_op
    assert second.world_state_id == "WS-2"
    assert second.previous_world_state_id == "WS-1"

    # Same logical identity continued, carrying the new value.
    updated = second.claims[logical_id]
    assert "November 3, 2026" in str(updated["value"])
    assert "October" not in str(updated["value"])

    new_answer = pipeline.answer(LAUNCH_QUESTION)
    assert new_answer.outcome is AnswerOutcome.CURRENT
    assert new_answer.claim_ids == (logical_id,)

    # The WS-1 drafts are re-judged against the ACTIVE WS-2: stale, honestly.
    stale_answer = compile_answer(LAUNCH_QUESTION, ws1_drafts, pipeline.registry, CONTEXT)
    assert stale_answer.outcome is AnswerOutcome.STALE
    assert "WS-1" in stale_answer.reason

    # A brand-new process sees WS-2 through the persisted pointer alone.
    reopened = Pipeline(pipeline.store.base.parent)
    assert reopened.answer(LAUNCH_QUESTION).claim_ids == (logical_id,)


# ---------------------------------------------------------------------------
# (c) rename -> identity continuity
# ---------------------------------------------------------------------------


def test_rename_keeps_logical_identity(
    workspace: Path, pipeline: Pipeline
) -> None:
    first = pipeline.compile_workspace(workspace)
    ids_before = set(first.claims)

    renamed_path = "projects/launch-plan-v2.md"
    (workspace / LAUNCH_PLAN).rename(workspace / renamed_path)

    result = pipeline.recompile(workspace)
    assert result.published
    assert result.renames == ((LAUNCH_PLAN, renamed_path),)
    # Every logical id survived the move -- nothing split, nothing forked.
    assert set(result.claims) == ids_before
    moved_rows = [
        row for row in result.claims.values() if str(row["rel_path"]) == renamed_path
    ]
    assert moved_rows and all(row.get("moved_from") == LAUNCH_PLAN for row in moved_rows)

    answer = result.answer(LAUNCH_QUESTION)
    assert answer.outcome is AnswerOutcome.CURRENT
    evidence = result.evidence_for(answer.evidence_occurrences[0].evidence_id)
    assert evidence is not None
    assert evidence["rel_path"] == renamed_path


# ---------------------------------------------------------------------------
# (d) deletion -> dependent knowledge invalidated
# ---------------------------------------------------------------------------


def test_deletion_invalidates_dependent_knowledge(
    workspace: Path, pipeline: Pipeline
) -> None:
    first = pipeline.compile_workspace(workspace)
    pre = pipeline.answer(READINESS_QUESTION)
    assert pre.outcome is AnswerOutcome.CURRENT
    governance_ids = {
        logical_id
        for logical_id, row in first.claims.items()
        if str(row["rel_path"]) == GOVERNANCE_POLICY
    }
    assert governance_ids

    (workspace / GOVERNANCE_POLICY).unlink()

    result = pipeline.recompile(workspace)
    assert result.published
    # The deleted document's claims are gone...
    assert not governance_ids & set(result.claims)
    # ...and everything downstream of them is stamped invalid, transitively
    # (plan depends on governance; spec depends on plan).
    invalidated = set(result.invalidated)
    dependent_ids = {
        logical_id
        for logical_id, row in result.claims.items()
        if str(row["rel_path"]) in {LAUNCH_PLAN, "specs/launch-spec.md"}
    }
    assert dependent_ids <= invalidated
    stamps = {
        logical_id: list(result.claims[logical_id]["invalidated_by"])
        for logical_id in dependent_ids
    }
    assert all(stamps[logical_id] for logical_id in dependent_ids)
    flat_causes = {cause for causes in stamps.values() for cause in causes}
    assert flat_causes & governance_ids

    # Fail-closed answering: the invalidated launch claim is not nominated
    # even though its text would match, and the deleted topic answers
    # UNRESOLVED rather than serving a ghost.
    launch_drafts = result.draft_claims(LAUNCH_QUESTION)
    assert dependent_ids.isdisjoint({d.claim.claim_id for d in launch_drafts})
    post = pipeline.answer(READINESS_QUESTION)
    assert post.outcome is AnswerOutcome.UNRESOLVED


# ---------------------------------------------------------------------------
# (e) equal-standing disagreement -> CONFLICT
# ---------------------------------------------------------------------------


def test_equal_authority_disagreement_compiles_to_conflict(
    workspace: Path, pipeline: Pipeline
) -> None:
    pipeline.compile_workspace(workspace)
    memo = workspace / LAUNCH_DELAY_MEMO
    memo.write_text(MEMO_CONTENT, encoding="utf-8")

    result = pipeline.recompile(workspace)
    assert result.published

    answer = pipeline.answer(LAUNCH_QUESTION)
    assert answer.outcome is AnswerOutcome.CONFLICT
    assert len(answer.claim_ids) == 2
    values = [str(result.claims[cid]["value"]) for cid in answer.claim_ids]
    assert any("October 15" in value for value in values)
    assert any("November 3" in value for value in values)
    assert answer.evidence_occurrences


# ---------------------------------------------------------------------------
# (f) ambiguous identity -> review queue, fail-closed
# ---------------------------------------------------------------------------


def test_ambiguous_identity_is_quarantined_for_review(
    workspace: Path, pipeline: Pipeline
) -> None:
    first = pipeline.compile_workspace(workspace)
    roadmap_old = [
        logical_id
        for logical_id, row in first.claims.items()
        if str(row["rel_path"]) == ROADMAP_HINTS
    ]
    assert roadmap_old

    hints = workspace / ROADMAP_HINTS
    hints.write_text(
        hints.read_text(encoding="utf-8").replace(
            "The companion mobile app is planned for next quarter.",
            "Companion mobile application work is worth exploring during the upcoming cycle.",
        ),
        encoding="utf-8",
    )

    result = pipeline.recompile(workspace)
    assert result.published

    # The resolver abstained: neither merged into the old identity nor split
    # into a confident new one -- quarantined for human review instead.
    assert len(result.review_queue) == 1
    item = result.review_queue[0]
    assert item.candidates
    assert any(candidate in roadmap_old for candidate in item.candidates)
    assert "review band" in item.reason or "critical signal" in item.reason
    assert roadmap_old[0] not in result.claims
    assert not any(
        "upcoming cycle" in str(row["value"]) for row in result.claims.values()
    )

    # Fail-closed locality: the touched topic refuses to answer while the
    # rest of the world stays healthy.
    assert pipeline.answer("Is the companion mobile app planned?").outcome is (
        AnswerOutcome.UNRESOLVED
    )
    launch = pipeline.answer(LAUNCH_QUESTION)
    assert launch.outcome is AnswerOutcome.CURRENT
    assert "October 15" in str(result.claims[launch.claim_ids[0]]["value"])

    # An unchanged tree is a no-op that carries the held review item forward
    # as the same typed ReviewItem, not its stored record.
    noop = pipeline.recompile(workspace)
    assert noop.no_op
    assert noop.review_queue == result.review_queue


# ---------------------------------------------------------------------------
# (g) selective == full oracle; unchanged tree is a no-op
# ---------------------------------------------------------------------------


def test_selective_recompile_equals_full_rebuild_and_noop_retains_world(
    workspace: Path, pipeline: Pipeline, tmp_path: Path
) -> None:
    pipeline.compile_workspace(workspace)

    hints = workspace / ROADMAP_HINTS
    hints.write_text(
        hints.read_text(encoding="utf-8")
        + "\nQuarterly pricing review is scheduled before the next quarter begins.\n",
        encoding="utf-8",
    )

    selective = pipeline.recompile(workspace)
    assert selective.published
    plan = selective.plan
    assert plan is not None
    assert plan.work_avoided > 0
    assert selective.equivalence is not None
    assert selective.equivalence.equivalent

    # The §44 exit criterion, stated as hashes: rebuilding *everything* from
    # the same tree produces the very same artifact set, hence the same
    # manifest hash the selective publish carries.
    scratch = Pipeline(tmp_path / "scratch-store")
    full = scratch.compile_workspace(workspace)
    assert full.manifest_hash == selective.manifest_hash

    # Recompiling an unchanged tree publishes nothing at all.
    noop = pipeline.recompile(workspace)
    assert noop.no_op and not noop.published
    assert noop.world_state_id == selective.world_state_id
    assert noop.manifest_hash == selective.manifest_hash


# ---------------------------------------------------------------------------
# answer machinery details the outcomes above rest on
# ---------------------------------------------------------------------------


def test_unrelated_question_refuses_to_guess(workspace: Path, pipeline: Pipeline) -> None:
    pipeline.compile_workspace(workspace)
    answer = pipeline.answer("What is the quarterly revenue forecast?")
    assert answer.outcome is AnswerOutcome.UNRESOLVED
    assert answer.claim_ids == ()


def test_superseded_fact_loses_to_its_successor(
    workspace: Path, pipeline: Pipeline
) -> None:
    pipeline.compile_workspace(workspace)
    # Both warranty statements are nominated; the superseded informal note
    # must lose to the active official policy on the §N17 tuple.
    answer = pipeline.answer("What is the warranty?")
    assert answer.outcome is AnswerOutcome.CURRENT
    world = pipeline.store.load_world()
    winner = world.claims[answer.claim_ids[0]]
    assert "two-year limited warranty" in str(winner["value"])
    superseded_rows = [
        row
        for row in world.claims.values()
        if int(row["source_status"]) == 1
    ]
    assert superseded_rows
    assert all(row["logical_id"] != winner["logical_id"] for row in superseded_rows)
