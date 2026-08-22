from __future__ import annotations

import pytest

from benchmark.v6.public_failure_adapter import (
    PUBLIC_FAILURE_RULES,
    EvaluatorFailureRecord,
    adapt_failure,
    adapt_failures,
)

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
REVISION = "d" * 40


def _record(
    *,
    benchmark_id: str,
    evaluator_type: str,
    passed: bool = False,
) -> EvaluatorFailureRecord:
    return EvaluatorFailureRecord(
        benchmark_id=benchmark_id,
        case_id="case-1",
        evaluator_revision=REVISION,
        evaluator_type=evaluator_type,
        location_id="page-1",
        prediction_sha256=SHA_A,
        authority_sha256=SHA_B,
        failure_evidence_sha256=SHA_C,
        passed=passed,
        score=0.5,
    )


@pytest.mark.parametrize(
    ("benchmark_id", "evaluator_type", "code", "scope", "recover"),
    tuple(
        (
            benchmark_id,
            evaluator_type,
            rule.failure_code,
            rule.minimum_scope,
            rule.failure_code not in {"T03", "H01", "H02"},
        )
        for benchmark_id, rules in PUBLIC_FAILURE_RULES.items()
        for evaluator_type, rule in rules.items()
    ),
)
def test_every_registered_evaluator_type_maps_exactly(
    benchmark_id: str,
    evaluator_type: str,
    code: str,
    scope: str,
    recover: bool,
) -> None:
    prediction = adapt_failure(
        _record(benchmark_id=benchmark_id, evaluator_type=evaluator_type)
    )

    assert prediction is not None
    assert prediction.failure_codes == {code}
    assert prediction.scope_level == scope
    assert prediction.scope_id == "case-1:page-1"
    assert prediction.request_recovery is recover
    assert prediction.escalate is False


def test_passing_evaluator_record_emits_no_failure() -> None:
    assert (
        adapt_failure(
            _record(
                benchmark_id="omnidocbench",
                evaluator_type="text_block",
                passed=True,
            )
        )
        is None
    )


def test_unknown_evaluator_type_fails_closed() -> None:
    with pytest.raises(ValueError, match="unmapped evaluator failure type"):
        adapt_failure(
            _record(benchmark_id="parsebench", evaluator_type="future_unknown_rule")
        )


def test_failed_record_rejects_identical_prediction_and_authority() -> None:
    record = _record(benchmark_id="olmocr-bench", evaluator_type="math")
    record = EvaluatorFailureRecord(
        benchmark_id=record.benchmark_id,
        case_id=record.case_id,
        evaluator_revision=record.evaluator_revision,
        evaluator_type=record.evaluator_type,
        location_id=record.location_id,
        prediction_sha256=SHA_A,
        authority_sha256=SHA_A,
        failure_evidence_sha256=record.failure_evidence_sha256,
        passed=False,
    )

    with pytest.raises(ValueError, match="identical artifacts"):
        adapt_failure(record)


def test_duplicate_evaluator_evidence_fails_closed() -> None:
    record = _record(benchmark_id="olmocr-bench", evaluator_type="table")

    with pytest.raises(ValueError, match="duplicate"):
        adapt_failures((record, record))
