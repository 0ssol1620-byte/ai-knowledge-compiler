"""Cause-conditioned recovery selection layered over the protected recovery core.

The protected recovery policy already supplies a bounded, cost-ordered ladder.
This module adds one independent decision that the paper/patent program needs to
measure explicitly: an operational/transient failure and a semantic/model failure
must not be treated as the same kind of retry opportunity.

The rule is intentionally narrow. Semantic/model failures may still receive a
source-preserving deterministic repair (for example a re-render), but a
same-family parser/model variation is not counted as independent recovery. Once
that deterministic repair has been tried, the eligible path skips to an
independent family, source verifier, document reconciliation, review, or
fail-closed outcome. Operational/transient failures retain the same-family retry
path because a fresh worker or bounded variation can legitimately clear them.

This is an adapter over ``recovery_policy`` rather than a rewrite of it. That
keeps the tested cost/budget/security invariants in one place and makes the
cause-conditioned experiment removable and directly ablatable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .inspection import SECURITY_CODES, FailureCode
from .recovery_policy import (
    PolicyRegistry,
    QualityMode,
    RecoveryAttempt,
    RecoveryBudget,
    RecoveryDecision,
    RecoveryLevel,
    RecoveryPolicy,
    select_recovery,
)

__all__ = [
    "CauseConditionedDecision",
    "FailureClass",
    "RecoveryOperatorKind",
    "classify_failure",
    "operator_kind",
    "select_cause_conditioned_recovery",
]


class FailureClass(StrEnum):
    """Cause family used to decide whether same-family retry is defensible."""

    OPERATIONAL_TRANSIENT = "OPERATIONAL_TRANSIENT"
    SEMANTIC_MODEL = "SEMANTIC_MODEL"
    SECURITY_POLICY = "SECURITY_POLICY"
    STATE_INTEGRITY = "STATE_INTEGRITY"


class RecoveryOperatorKind(StrEnum):
    """Mechanism family, deliberately separate from the cost rung."""

    ACCEPT = "ACCEPT"
    DETERMINISTIC_REPAIR = "DETERMINISTIC_REPAIR"
    SAME_FAMILY_RETRY = "SAME_FAMILY_RETRY"
    INDEPENDENT_FAMILY = "INDEPENDENT_FAMILY"
    SOURCE_VERIFIER = "SOURCE_VERIFIER"
    STATE_RECONCILIATION = "STATE_RECONCILIATION"
    HUMAN_OR_FAIL_CLOSED = "HUMAN_OR_FAIL_CLOSED"


def _failure_number(code: FailureCode) -> int:
    return int(code.value.split("_", 1)[0][1:])


def classify_failure(code: FailureCode) -> FailureClass:
    """Classify conservatively; unknown control codes are never guessed transient."""

    if code in SECURITY_CODES:
        return FailureClass.SECURITY_POLICY

    number = _failure_number(code)
    if number in {2, 3, 4, 5, 6, 7, 48}:
        return FailureClass.OPERATIONAL_TRANSIENT
    if 8 <= number <= 21 or number == 42:
        return FailureClass.SEMANTIC_MODEL
    if number in {25, 27, 33}:
        return FailureClass.SECURITY_POLICY
    return FailureClass.STATE_INTEGRITY


def operator_kind(policy: RecoveryPolicy) -> RecoveryOperatorKind:
    """Return the recovery mechanism represented by a policy rung."""

    return {
        RecoveryLevel.L0_ACCEPT: RecoveryOperatorKind.ACCEPT,
        RecoveryLevel.L1_SAFE_RERENDER: RecoveryOperatorKind.DETERMINISTIC_REPAIR,
        RecoveryLevel.L2_SAME_PARSER_VARIATION: RecoveryOperatorKind.SAME_FAMILY_RETRY,
        RecoveryLevel.L3_ALTERNATE_PARSER_FAMILY: RecoveryOperatorKind.INDEPENDENT_FAMILY,
        RecoveryLevel.L4_CONDITIONAL_ENSEMBLE: RecoveryOperatorKind.INDEPENDENT_FAMILY,
        RecoveryLevel.L5_STRONGER_VERIFIER: RecoveryOperatorKind.SOURCE_VERIFIER,
        RecoveryLevel.L6_DOCUMENT_JOINT_RECONCILE: RecoveryOperatorKind.STATE_RECONCILIATION,
        RecoveryLevel.L7_HUMAN_REVIEW: RecoveryOperatorKind.HUMAN_OR_FAIL_CLOSED,
        RecoveryLevel.L8_FAIL_CLOSED: RecoveryOperatorKind.HUMAN_OR_FAIL_CLOSED,
    }[policy.level]


@dataclass(frozen=True, slots=True)
class CauseConditionedDecision:
    """The ordinary recovery decision plus the causal branch that produced it."""

    failure_class: FailureClass
    decision: RecoveryDecision

    @property
    def selected_operator_kind(self) -> RecoveryOperatorKind | None:
        if self.decision.policy is None:
            return None
        return operator_kind(self.decision.policy)

    def as_record(self) -> dict[str, object]:
        return {
            "failure_class": self.failure_class.value,
            "outcome": self.decision.outcome.value,
            "policy_signature": (
                self.decision.policy.signature if self.decision.policy is not None else None
            ),
            "operator_kind": (
                self.selected_operator_kind.value
                if self.selected_operator_kind is not None
                else None
            ),
            "reason": self.decision.reason,
        }


def _eligible_registry(
    code: FailureCode,
    *,
    registry: PolicyRegistry,
    failure_class: FailureClass,
) -> PolicyRegistry:
    policies = list(registry.for_code(code))
    if failure_class is FailureClass.SEMANTIC_MODEL:
        policies = [
            policy
            for policy in policies
            if operator_kind(policy) is not RecoveryOperatorKind.SAME_FAMILY_RETRY
        ]
    return PolicyRegistry(policies)


def select_cause_conditioned_recovery(
    *,
    code: FailureCode,
    failure_signature: str,
    registry: PolicyRegistry,
    history: tuple[RecoveryAttempt, ...] | list[RecoveryAttempt] = (),
    mode: QualityMode = QualityMode.BALANCED,
    budget: RecoveryBudget | None = None,
    circuit_open: bool = False,
) -> CauseConditionedDecision:
    """Select recovery with an explicit operational-vs-semantic branch.

    Security handling, repeated-signature stopping, quality-mode ceilings and
    budget checks remain delegated to ``select_recovery``. The only intervention
    here is which operator kinds are eligible for a semantic/model failure.
    """

    failure_class = classify_failure(code)
    eligible = _eligible_registry(
        code,
        registry=registry,
        failure_class=failure_class,
    )
    decision = select_recovery(
        code=code,
        failure_signature=failure_signature,
        registry=eligible,
        history=history,
        mode=mode,
        budget=budget,
        circuit_open=circuit_open,
    )
    return CauseConditionedDecision(failure_class=failure_class, decision=decision)
