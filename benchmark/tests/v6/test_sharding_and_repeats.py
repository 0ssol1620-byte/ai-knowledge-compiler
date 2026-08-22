from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from benchmark.v6.contracts import ContractError, EnvironmentIdentity
from benchmark.v6.repeats import (
    RepeatObservation,
    RepeatScope,
    build_adaptive_repeat_plan,
    build_exact_repeat_plan,
    evaluate_adaptive_repeats,
    materialize_adaptive_repeat_plan,
    materialize_repeat_plan,
    validate_adaptive_repeat_plan,
    validate_repeat_plan,
)
from benchmark.v6.sharding import (
    PageManifestEntry,
    plan_document_shards,
    validate_shard_plan,
)


def _pages() -> list[PageManifestEntry]:
    return [
        PageManifestEntry("doc-b", 2, "b-2", "sha256:" + "2" * 64, 8.0, "cross_page_table"),
        PageManifestEntry("doc-a", 1, "a-1", "sha256:" + "3" * 64, 1.0, "native_pdf"),
        PageManifestEntry("doc-b", 1, "b-1", "sha256:" + "4" * 64, 7.0, "cross_page_table"),
        PageManifestEntry("doc-c", 1, "c-1", "sha256:" + "5" * 64, 2.0, "scan"),
        PageManifestEntry("doc-b", 3, "b-3", "sha256:" + "6" * 64, 9.0, "cross_page_table"),
    ]


def test_deterministic_shards_are_order_independent_and_preserve_documents() -> None:
    pages = _pages()
    first = plan_document_shards(pages, shard_count=4, namespace="parsebench@revision")
    second = plan_document_shards(reversed(pages), shard_count=4, namespace="parsebench@revision")

    assert [shard.to_dict() for shard in first] == [shard.to_dict() for shard in second]
    owners = {page.document_id: shard.shard_index for shard in first for page in shard.pages}
    assert len({owners["doc-b"]}) == 1
    assert [
        page.page_number for shard in first for page in shard.pages if page.document_id == "doc-b"
    ] == [1, 2, 3]
    receipt = validate_shard_plan(pages, first, namespace="parsebench@revision")
    assert receipt["no_page_loss"] is True
    assert receipt["document_context_preserved"] is True


def test_shard_validation_rejects_page_loss_and_manifest_tampering() -> None:
    pages = _pages()
    shards = list(plan_document_shards(pages, shard_count=2, namespace="suite@sha"))
    occupied_index = next(index for index, shard in enumerate(shards) if shard.pages)
    occupied = shards[occupied_index]
    shards[occupied_index] = replace(occupied, pages=occupied.pages[:-1])

    with pytest.raises(ContractError, match="coverage mismatch"):
        validate_shard_plan(pages, shards, namespace="suite@sha")


def test_exact_three_repeat_plan_has_same_identity_and_isolated_roots(
    tmp_path: Path,
    environment: EnvironmentIdentity,
) -> None:
    runs = build_exact_repeat_plan(
        base_root=tmp_path,
        benchmark_id="parsebench",
        environment=environment,
        expansion_reason="finalist",
    )
    receipt = validate_repeat_plan(runs)

    assert [run.repeat_index for run in runs] == [1, 2, 3]
    assert len({run.environment_sha256 for run in runs}) == 1
    assert len({run.prediction_root for run in runs}) == 3
    assert len({run.log_root for run in runs}) == 3
    assert receipt["passed"] is True

    materialize_repeat_plan(runs)
    for run in runs:
        assert (run.repeat_root / "repeat-contract.json").is_file()
        assert run.prediction_root.is_dir()
        assert run.log_root.is_dir()


def test_repeat_validation_rejects_incomplete_or_mixed_environment(
    tmp_path: Path,
    environment: EnvironmentIdentity,
) -> None:
    runs = list(
        build_exact_repeat_plan(
            base_root=tmp_path,
            benchmark_id="omnidocbench",
            environment=environment,
            expansion_reason="prediction_drift",
        )
    )
    with pytest.raises(ContractError, match="exactly three"):
        validate_repeat_plan(runs[:2])
    runs[2] = replace(runs[2], environment_sha256="sha256:" + "9" * 64)
    with pytest.raises(ContractError, match="environment_sha256"):
        validate_repeat_plan(runs)


def test_adaptive_initial_plan_is_one_full_plus_three_isolated_audits(
    tmp_path: Path,
    environment: EnvironmentIdentity,
) -> None:
    runs = build_adaptive_repeat_plan(
        base_root=tmp_path,
        benchmark_id="parsebench",
        environment=environment,
    )
    receipt = validate_adaptive_repeat_plan(runs, required_full_runs=1)

    assert len(runs) == 4
    assert [(run.scope, run.repeat_index) for run in runs] == [
        (RepeatScope.FULL, 1),
        (RepeatScope.STRATIFIED_AUDIT, 1),
        (RepeatScope.STRATIFIED_AUDIT, 2),
        (RepeatScope.STRATIFIED_AUDIT, 3),
    ]
    assert receipt["full_run_count"] == 1
    assert receipt["audit_run_count"] == 3
    materialize_adaptive_repeat_plan(runs, required_full_runs=1)
    assert all((run.repeat_root / "repeat-contract.json").is_file() for run in runs)


def test_adaptive_expansion_adds_only_two_full_runs_and_preserves_initial_ids(
    tmp_path: Path,
    environment: EnvironmentIdentity,
) -> None:
    initial = build_adaptive_repeat_plan(
        base_root=tmp_path,
        benchmark_id="omnidocbench",
        environment=environment,
    )
    expanded = build_adaptive_repeat_plan(
        base_root=tmp_path,
        benchmark_id="omnidocbench",
        environment=environment,
        required_full_runs=3,
    )

    initial_identity = {
        (run.scope, run.repeat_index): run.run_id for run in initial
    }
    expanded_identity = {
        (run.scope, run.repeat_index): run.run_id for run in expanded
    }
    assert len(expanded) == 6
    assert all(expanded_identity[key] == value for key, value in initial_identity.items())
    assert set(expanded_identity) - set(initial_identity) == {
        (RepeatScope.FULL, 2),
        (RepeatScope.FULL, 3),
    }
    validate_adaptive_repeat_plan(expanded, required_full_runs=3)


def test_adaptive_plan_rejects_unbounded_or_intermediate_full_count(
    tmp_path: Path,
    environment: EnvironmentIdentity,
) -> None:
    with pytest.raises(ContractError, match="one or three"):
        build_adaptive_repeat_plan(
            base_root=tmp_path,
            benchmark_id="parsebench",
            environment=environment,
            required_full_runs=2,
        )


def _observation(
    run_id: str,
    scope: RepeatScope,
    *,
    digest: str = "1",
    failure_count: int = 0,
) -> RepeatObservation:
    return RepeatObservation(
        run_id=run_id,
        candidate_id="paddle",
        benchmark_id="omnidocbench",
        environment_sha256="sha256:" + "a" * 64,
        scope=scope,
        prediction_hashes=(("page-1", "sha256:" + digest * 64),),
        score=0.95 if digest == "1" else 0.94,
        failure_count=failure_count,
    )


def test_adaptive_repeat_gate_skips_redundant_full_runs_for_stable_non_finalist() -> None:
    observations = (
        _observation("full-1", RepeatScope.FULL),
        _observation("audit-1", RepeatScope.STRATIFIED_AUDIT),
        _observation("audit-2", RepeatScope.STRATIFIED_AUDIT),
        _observation("audit-3", RepeatScope.STRATIFIED_AUDIT),
    )

    decision = evaluate_adaptive_repeats(observations, finalist=False)

    assert decision.gate_complete is True
    assert decision.deterministic is True
    assert decision.required_full_runs == 1
    assert decision.additional_full_runs == 0


def test_adaptive_repeat_gate_expands_drift_or_finalist_to_three_full_runs() -> None:
    observations = (
        _observation("full-1", RepeatScope.FULL),
        _observation("audit-1", RepeatScope.STRATIFIED_AUDIT),
        _observation("audit-2", RepeatScope.STRATIFIED_AUDIT, digest="2"),
        _observation("audit-3", RepeatScope.STRATIFIED_AUDIT),
    )

    drift = evaluate_adaptive_repeats(observations, finalist=False)
    finalist = evaluate_adaptive_repeats(observations[:1] + observations[1:], finalist=True)

    assert drift.deterministic is False
    assert drift.additional_full_runs == 2
    assert drift.gate_complete is False
    assert finalist.required_full_runs == 3


def test_adaptive_repeat_records_full_run_variance_after_expansion() -> None:
    observations = (
        _observation("full-1", RepeatScope.FULL),
        _observation("full-2", RepeatScope.FULL, digest="2"),
        _observation("full-3", RepeatScope.FULL),
        _observation("audit-1", RepeatScope.STRATIFIED_AUDIT),
        _observation("audit-2", RepeatScope.STRATIFIED_AUDIT),
        _observation("audit-3", RepeatScope.STRATIFIED_AUDIT),
    )

    decision = evaluate_adaptive_repeats(observations, finalist=True)

    assert decision.gate_complete is False
    assert decision.deterministic is False
    assert "full_repeat_drift_observed" in decision.reason_codes


def test_three_stable_full_runs_clear_audit_drift_after_required_expansion() -> None:
    observations = (
        _observation("full-1", RepeatScope.FULL),
        _observation("full-2", RepeatScope.FULL),
        _observation("full-3", RepeatScope.FULL),
        _observation("audit-1", RepeatScope.STRATIFIED_AUDIT),
        _observation("audit-2", RepeatScope.STRATIFIED_AUDIT, digest="2"),
        _observation("audit-3", RepeatScope.STRATIFIED_AUDIT),
    )

    decision = evaluate_adaptive_repeats(observations, finalist=False)

    assert decision.gate_complete is True
    assert decision.deterministic is True
    assert "determinism_audit_drift" in decision.reason_codes


def test_adaptive_repeat_rejects_extra_or_nonfinite_evidence() -> None:
    observations = tuple(
        _observation(f"audit-{index}", RepeatScope.STRATIFIED_AUDIT)
        for index in range(1, 5)
    )
    with pytest.raises(ContractError, match="at most three successful"):
        evaluate_adaptive_repeats(observations, finalist=False)
    with pytest.raises(ValueError, match="finite"):
        replace(_observation("full-1", RepeatScope.FULL), score=float("nan"))


def test_failed_attempt_does_not_count_as_a_successful_repeat() -> None:
    observations = (
        _observation("full-failed", RepeatScope.FULL, failure_count=1),
        _observation("full-1", RepeatScope.FULL),
        _observation("audit-1", RepeatScope.STRATIFIED_AUDIT),
        _observation("audit-2", RepeatScope.STRATIFIED_AUDIT),
        _observation("audit-3", RepeatScope.STRATIFIED_AUDIT),
    )

    decision = evaluate_adaptive_repeats(observations, finalist=False)

    assert decision.required_full_runs == 3
    assert decision.additional_full_runs == 2
    assert decision.gate_complete is False
    assert "runtime_failure_observed" in decision.reason_codes
