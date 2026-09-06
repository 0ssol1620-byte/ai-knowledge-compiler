from __future__ import annotations

from akc_cir.cause_conditioned_recovery import (
    FailureClass,
    RecoveryOperatorKind,
    classify_failure,
    operator_kind,
    select_cause_conditioned_recovery,
)
from akc_cir.inspection import FailureCode
from akc_cir.recovery_policy import (
    PolicyRegistry,
    QualityMode,
    RecoveryAttempt,
    RecoveryLevel,
    RecoveryOutcome,
    RecoveryPolicy,
    default_recovery_registry,
)


def _policy(code: FailureCode, level: RecoveryLevel, action: str) -> RecoveryPolicy:
    return RecoveryPolicy(
        policy_id=f"{code.value}-{action}",
        code=code,
        level=level,
        action=action,
    )


def test_failure_class_is_typed_and_conservative() -> None:
    assert classify_failure(FailureCode.F4_WORKER_LOST) is FailureClass.OPERATIONAL_TRANSIENT
    assert classify_failure(FailureCode.F13_TABLE_STRUCTURE) is FailureClass.SEMANTIC_MODEL
    assert (
        classify_failure(FailureCode.F29_PROMPT_INJECTION_SUSPECTED)
        is FailureClass.SECURITY_POLICY
    )
    assert classify_failure(FailureCode.F24_RECOMPILE_DIVERGENCE) is FailureClass.STATE_INTEGRITY


def test_operator_kind_is_independent_of_policy_action_text() -> None:
    code = FailureCode.F13_TABLE_STRUCTURE
    same = _policy(code, RecoveryLevel.L2_SAME_PARSER_VARIATION, "anything")
    alternate = _policy(code, RecoveryLevel.L3_ALTERNATE_PARSER_FAMILY, "anything")

    assert operator_kind(same) is RecoveryOperatorKind.SAME_FAMILY_RETRY
    assert operator_kind(alternate) is RecoveryOperatorKind.INDEPENDENT_FAMILY


def test_semantic_failure_skips_same_family_after_deterministic_repair() -> None:
    code = FailureCode.F13_TABLE_STRUCTURE
    registry = default_recovery_registry()
    first = registry.for_code(code)[0]
    assert first.level is RecoveryLevel.L1_SAFE_RERENDER

    result = select_cause_conditioned_recovery(
        code=code,
        failure_signature="table-semantic-new",
        registry=registry,
        history=[
            RecoveryAttempt(
                policy_signature=first.signature,
                failure_signature="table-semantic-old",
            )
        ],
        mode=QualityMode.VERIFIED,
    )

    assert result.failure_class is FailureClass.SEMANTIC_MODEL
    assert result.decision.outcome is RecoveryOutcome.APPLY
    assert result.decision.policy is not None
    assert result.decision.policy.level is RecoveryLevel.L3_ALTERNATE_PARSER_FAMILY
    assert result.selected_operator_kind is RecoveryOperatorKind.INDEPENDENT_FAMILY


def test_operational_failure_retains_same_family_retry() -> None:
    code = FailureCode.F7_PARSER_EXCEPTION
    registry = default_recovery_registry()
    first = registry.for_code(code)[0]
    assert first.level is RecoveryLevel.L1_SAFE_RERENDER

    result = select_cause_conditioned_recovery(
        code=code,
        failure_signature="parser-op-new",
        registry=registry,
        history=[
            RecoveryAttempt(
                policy_signature=first.signature,
                failure_signature="parser-op-old",
            )
        ],
        mode=QualityMode.VERIFIED,
    )

    assert result.failure_class is FailureClass.OPERATIONAL_TRANSIENT
    assert result.decision.outcome is RecoveryOutcome.APPLY
    assert result.decision.policy is not None
    assert result.decision.policy.level is RecoveryLevel.L2_SAME_PARSER_VARIATION
    assert result.selected_operator_kind is RecoveryOperatorKind.SAME_FAMILY_RETRY


def test_semantic_fast_mode_fails_closed_instead_of_falling_back_to_same_family() -> None:
    code = FailureCode.F13_TABLE_STRUCTURE
    registry = default_recovery_registry()
    first = registry.for_code(code)[0]

    result = select_cause_conditioned_recovery(
        code=code,
        failure_signature="table-fast-new",
        registry=registry,
        history=[
            RecoveryAttempt(
                policy_signature=first.signature,
                failure_signature="table-fast-old",
            )
        ],
        mode=QualityMode.FAST,
    )

    assert result.failure_class is FailureClass.SEMANTIC_MODEL
    assert result.decision.outcome is RecoveryOutcome.FAIL_CLOSED
    assert result.decision.policy is None


def test_security_failure_remains_blocked_before_any_retry() -> None:
    code = FailureCode.F29_PROMPT_INJECTION_SUSPECTED
    registry = PolicyRegistry(
        [_policy(code, RecoveryLevel.L3_ALTERNATE_PARSER_FAMILY, "unsafe-retry")]
    )

    result = select_cause_conditioned_recovery(
        code=code,
        failure_signature="security",
        registry=registry,
        mode=QualityMode.VERIFIED,
    )

    assert result.failure_class is FailureClass.SECURITY_POLICY
    assert result.decision.outcome is RecoveryOutcome.BLOCK_SECURITY
    assert result.decision.policy is None


def test_receipt_record_exposes_causal_branch_and_operator_kind() -> None:
    result = select_cause_conditioned_recovery(
        code=FailureCode.F13_TABLE_STRUCTURE,
        failure_signature="table-record",
        registry=default_recovery_registry(),
        mode=QualityMode.VERIFIED,
    )

    record = result.as_record()
    assert record["failure_class"] == "SEMANTIC_MODEL"
    assert record["operator_kind"] == "DETERMINISTIC_REPAIR"
    assert record["outcome"] == "APPLY"
