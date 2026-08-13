"""What to do about a failure the inspector found.

Masterplan §N10 and §N11. The inspector says *this output is wrong and here is
which detector says so*; this decides what to spend next, and refuses to spend it
forever.

The escalation ladder is the shape of the whole module. Each rung costs more than
the one below and is tried only when the rung below has failed or does not apply,
so the cheap fixes -- rotate the page, re-render at a higher DPI -- run before a
stronger model is booked. §2.4's ablation is the reason the ladder exists at all:
the same model and corpus scored 80.6 with recovery and 53.7 without it.
Reliability is a system property, not a model property.

Four rules keep it from becoming a retry loop that bills forever.

**A security failure is blocked, never retried.** §N11.2 checks security codes
first. Retrying a poisoned document is running it again, and a policy engine that
treats "prompt injection suspected" as a transient error will keep running it
until the budget is gone.

**The same failure signature twice is not a third attempt.** §17.4 sets
`stop_on_same_failure_signature`. A rung that produced an identical failure is a
rung that does not address this failure, and the answer is to escalate or stop
rather than to try harder at the same thing.

**Correlated failure opens a circuit rather than buying more workers.** §N11.3.
The campaign paid for the absence of this: a provider-wide stop read as several
independent worker failures, and the reaction was to replace workers.

**A silent downgrade is a failure, not a result.** §N43 lists *unbounded retry or
silent downgrade* as the blocker condition for this subsystem. When the ladder
runs out, the outcome is `HUMAN_REVIEW` or `FAIL_CLOSED` with the reason attached
-- never a quietly accepted worse answer.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

from .inspection import SECURITY_CODES, FailureCode

__all__ = [
    "AgreementVector",
    "Arbitration",
    "ArbitrationOutcome",
    "Availability",
    "CircuitState",
    "PolicyRegistry",
    "QualityMode",
    "RecoveryAttempt",
    "RecoveryBudget",
    "RecoveryDecision",
    "RecoveryLevel",
    "RecoveryOutcome",
    "RecoveryPolicy",
    "arbitrate",
    "circuit_state",
    "document_availability",
    "select_recovery",
]


class RecoveryLevel(IntEnum):
    """§N11.1's ladder. Ordered, and the order is the cost order.

    An IntEnum because a quality mode caps the ladder by level, and comparing
    levels is the check that cap performs.
    """

    L0_ACCEPT = 0
    L1_SAFE_RERENDER = 1
    L2_SAME_PARSER_VARIATION = 2
    L3_ALTERNATE_PARSER_FAMILY = 3
    L4_CONDITIONAL_ENSEMBLE = 4
    L5_STRONGER_VERIFIER = 5
    L6_DOCUMENT_JOINT_RECONCILE = 6
    L7_HUMAN_REVIEW = 7
    L8_FAIL_CLOSED = 8


class QualityMode(StrEnum):
    """§38. Not a marketing label -- it caps the ladder and the budget."""

    FAST = "FAST"
    BALANCED = "BALANCED"
    VERIFIED = "VERIFIED"

    @property
    def max_level(self) -> RecoveryLevel:
        return _MODE_CEILING[self]

    @property
    def allows_review(self) -> bool:
        return self is QualityMode.VERIFIED


_MODE_CEILING: dict[QualityMode, RecoveryLevel] = {
    # "recovery L2 정도까지" -- a draft-quality path does not book a second model.
    QualityMode.FAST: RecoveryLevel.L2_SAME_PARSER_VARIATION,
    # "recovery L4 정도" -- ensembles yes, a stronger verifier no.
    QualityMode.BALANCED: RecoveryLevel.L4_CONDITIONAL_ENSEMBLE,
    # "L7 review 가능" -- contracts and compliance can afford a human.
    QualityMode.VERIFIED: RecoveryLevel.L7_HUMAN_REVIEW,
}


class RecoveryOutcome(StrEnum):
    """What `select_recovery` concluded. Every one of them is explicit."""

    APPLY = "APPLY"
    BLOCK_SECURITY = "BLOCK_SECURITY"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    FAIL_CLOSED = "FAIL_CLOSED"
    PAUSED_DEPENDENCY = "PAUSED_DEPENDENCY"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    """One rung, for one failure code."""

    policy_id: str
    code: FailureCode
    level: RecoveryLevel
    action: str
    estimated_gpu_seconds: float = 0.0
    estimated_cost_units: float = 0.0

    @property
    def signature(self) -> str:
        """What "already tried this" means. The rung, not the occurrence."""
        return f"{self.code.value}/{self.level.name}/{self.action}"


@dataclass(frozen=True, slots=True)
class RecoveryAttempt:
    """One rung already walked, and what it produced."""

    policy_signature: str
    failure_signature: str
    succeeded: bool = False
    gpu_seconds: float = 0.0
    cost_units: float = 0.0


@dataclass(frozen=True, slots=True)
class RecoveryBudget:
    """§17.4's `recovery_budget`, and §39.2's stop conditions.

    A budget that is only checked after spending is not a budget. `can_afford`
    is asked before a rung is chosen, using the rung's own estimate.
    """

    max_attempts_per_page: int = 4
    max_gpu_seconds: float = 600.0
    max_wall_clock_seconds: float = 1800.0
    max_cost_units: float = 100.0
    stop_on_same_failure_signature: bool = True

    def spent(self, history: Sequence[RecoveryAttempt]) -> tuple[float, float]:
        return (
            sum(attempt.gpu_seconds for attempt in history),
            sum(attempt.cost_units for attempt in history),
        )

    def can_afford(
        self, policy: RecoveryPolicy, history: Sequence[RecoveryAttempt]
    ) -> bool:
        if len(history) >= self.max_attempts_per_page:
            return False
        gpu, cost = self.spent(history)
        return (
            gpu + policy.estimated_gpu_seconds <= self.max_gpu_seconds
            and cost + policy.estimated_cost_units <= self.max_cost_units
        )


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    outcome: RecoveryOutcome
    policy: RecoveryPolicy | None
    reason: str

    def as_record(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "policy_id": self.policy.policy_id if self.policy else None,
            "level": self.policy.level.name if self.policy else None,
            "reason": self.reason,
        }


class PolicyRegistry:
    """The rungs available for each failure code, cheapest first.

    §N8's subtitle is *Detection·Recovery와 1:1 연결*. A code the inspector can
    raise and the registry has no rung for is a failure that gets found and then
    dropped, so `for_code` returning empty is a real answer the caller must act
    on rather than an empty loop that falls through to success.
    """

    def __init__(self, policies: Iterable[RecoveryPolicy] = ()) -> None:
        self._by_code: dict[FailureCode, list[RecoveryPolicy]] = {}
        for policy in policies:
            self.add(policy)

    def add(self, policy: RecoveryPolicy) -> None:
        bucket = self._by_code.setdefault(policy.code, [])
        bucket.append(policy)
        bucket.sort(key=lambda p: (p.level, p.policy_id))

    def for_code(self, code: FailureCode) -> tuple[RecoveryPolicy, ...]:
        return tuple(self._by_code.get(code, ()))

    def covered_codes(self) -> frozenset[FailureCode]:
        return frozenset(self._by_code)

    def uncovered(self, codes: Iterable[FailureCode]) -> tuple[FailureCode, ...]:
        """Codes the inspector can raise that no rung addresses."""
        return tuple(sorted(set(codes) - self.covered_codes(), key=lambda c: c.value))


def select_recovery(
    *,
    code: FailureCode,
    failure_signature: str,
    registry: PolicyRegistry,
    history: Sequence[RecoveryAttempt] = (),
    mode: QualityMode = QualityMode.BALANCED,
    budget: RecoveryBudget | None = None,
    circuit_open: bool = False,
) -> RecoveryDecision:
    """§N11.2, with each refusal named.

    Order matters and is the masterplan's: security first, then the repeated
    signature guard, then the ladder filtered by mode ceiling and budget, then
    review or fail-closed. Checking the budget before security would let a
    poisoned document be blocked for the wrong reason, and checking the ladder
    before the repeated-signature guard would walk the same rung twice.
    """
    limits = budget or RecoveryBudget()

    if code in SECURITY_CODES:
        return RecoveryDecision(
            outcome=RecoveryOutcome.BLOCK_SECURITY,
            policy=None,
            reason=(
                f"{code.value} is a security failure; retrying a poisoned "
                "document is running it again"
            ),
        )

    if circuit_open:
        return RecoveryDecision(
            outcome=RecoveryOutcome.PAUSED_DEPENDENCY,
            policy=None,
            reason=(
                "a dependency circuit is open; queued work waits rather than "
                "buying capacity against a provider-wide failure"
            ),
        )

    repeats = sum(1 for a in history if a.failure_signature == failure_signature)
    if limits.stop_on_same_failure_signature and repeats >= 2:
        return _exhausted(
            mode,
            f"the same failure signature came back {repeats} times; another "
            "attempt at the same thing is a retry storm, not a recovery",
        )

    tried = {attempt.policy_signature for attempt in history if not attempt.succeeded}
    affordable_exists = False
    for policy in registry.for_code(code):
        if policy.level > mode.max_level:
            continue
        if policy.signature in tried:
            continue
        affordable_exists = True
        if limits.can_afford(policy, history):
            return RecoveryDecision(
                outcome=RecoveryOutcome.APPLY,
                policy=policy,
                reason=(
                    f"{policy.level.name} addresses {code.value} within the "
                    f"{mode.value} ceiling and the remaining budget"
                ),
            )

    if affordable_exists:
        return RecoveryDecision(
            outcome=RecoveryOutcome.BUDGET_EXHAUSTED,
            policy=None,
            reason=(
                f"a rung for {code.value} exists but the page budget is spent; "
                "the result is not downgraded silently"
            ),
        )

    if not registry.for_code(code):
        return _exhausted(
            mode,
            f"no recovery rung is registered for {code.value}; a failure that is "
            "detected and has no remedy must not resolve as success",
        )

    return _exhausted(
        mode,
        f"every rung for {code.value} within the {mode.value} ceiling has been "
        "tried without success",
    )


def _exhausted(mode: QualityMode, reason: str) -> RecoveryDecision:
    """§N43's blocker: never a silent downgrade when the ladder runs out."""
    if mode.allows_review:
        return RecoveryDecision(
            outcome=RecoveryOutcome.HUMAN_REVIEW, policy=None, reason=reason
        )
    return RecoveryDecision(
        outcome=RecoveryOutcome.FAIL_CLOSED, policy=None, reason=reason
    )


# ---------------------------------------------------------------------------
# §N11.3 — circuit breaker
# ---------------------------------------------------------------------------


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"


def circuit_state(
    *,
    provider_scoped_signatures: int,
    dependency_outage: bool = False,
    queue_delay_seconds: float = 0.0,
    ttl_budget_seconds: float = 0.0,
) -> tuple[CircuitState, str]:
    """§N11.3. Open on evidence that the problem is not this document.

    Any one of the conditions is enough. They are alternatives rather than a
    score because each independently means the next attempt will fail for a
    reason no rung addresses, and requiring two would mean spending through the
    first one to confirm it.
    """
    if dependency_outage:
        return CircuitState.OPEN, "a dependency (R2, API or database) is unavailable"
    if provider_scoped_signatures > 0:
        return (
            CircuitState.OPEN,
            f"{provider_scoped_signatures} failure signature(s) correlated to the "
            "provider rather than to any one document",
        )
    if ttl_budget_seconds > 0 and queue_delay_seconds >= ttl_budget_seconds:
        return (
            CircuitState.OPEN,
            f"queue delay {queue_delay_seconds:.0f}s has consumed the "
            f"{ttl_budget_seconds:.0f}s TTL budget",
        )
    return CircuitState.CLOSED, ""


# ---------------------------------------------------------------------------
# §N11.4 — partial availability
# ---------------------------------------------------------------------------


class Availability(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class AvailabilityReport:
    availability: Availability
    verified_pages: tuple[int, ...]
    missing_pages: tuple[int, ...]
    reason: str = ""

    def as_record(self) -> dict[str, object]:
        return {
            "availability": self.availability.value,
            "verified_pages": list(self.verified_pages),
            "missing_pages": list(self.missing_pages),
            "reason": self.reason,
        }


def document_availability(
    *, total_pages: int, verified_pages: Iterable[int]
) -> AvailabilityReport:
    """§N11.4. A document missing pages is PARTIAL and names which ones.

    Exposing the searchable units is allowed; presenting them as the whole
    document is not. A response that omits the missing pages silently is a
    document-level claim the pipeline has not earned.
    """
    verified = tuple(sorted(set(verified_pages)))
    missing = tuple(page for page in range(1, total_pages + 1) if page not in verified)
    if not missing:
        return AvailabilityReport(Availability.COMPLETE, verified, ())
    if not verified:
        return AvailabilityReport(
            Availability.UNAVAILABLE, (), missing, "no page was verified"
        )
    return AvailabilityReport(
        Availability.PARTIAL,
        verified,
        missing,
        f"{len(missing)} of {total_pages} pages are not verified",
    )


# ---------------------------------------------------------------------------
# §N10 — consensus and arbitration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgreementVector:
    """§N10.3. Six dimensions, because parsers disagree in different ways.

    A single similarity number cannot distinguish "the same text in a different
    order" from "different text in the same order", and those two disagreements
    call for different rungs.
    """

    text_similarity: float
    block_sequence_similarity: float
    bbox_alignment: float
    table_grid_similarity: float
    reading_order_similarity: float
    consensus_entropy: float

    def __post_init__(self) -> None:
        for name in (
            "text_similarity",
            "block_sequence_similarity",
            "bbox_alignment",
            "table_grid_similarity",
            "reading_order_similarity",
            "consensus_entropy",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within 0..1")

    @property
    def weakest(self) -> tuple[str, float]:
        pairs = [
            ("text_similarity", self.text_similarity),
            ("block_sequence_similarity", self.block_sequence_similarity),
            ("bbox_alignment", self.bbox_alignment),
            ("table_grid_similarity", self.table_grid_similarity),
            ("reading_order_similarity", self.reading_order_similarity),
        ]
        return min(pairs, key=lambda pair: (pair[1], pair[0]))


class ArbitrationOutcome(StrEnum):
    ACCEPT = "ACCEPT"
    ESCALATE = "ESCALATE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True, slots=True)
class Arbitration:
    outcome: ArbitrationOutcome
    reason: str
    weakest_dimension: str = ""


def arbitrate(
    agreement: AgreementVector,
    *,
    source_aware_checks_passed: bool,
    candidate_count: int = 2,
    accept_threshold: float = 0.90,
    escalate_threshold: float = 0.70,
    parser_self_confidence: float | None = None,
) -> Arbitration:
    """§N10.4. Agreement is a signal about risk, not a source of truth.

    Two rules from the masterplan do most of the work here and both are refusals.

    *majority vote만으로 source truth 확정 금지.* Two parsers agreeing is two
    parsers agreeing; if the source-aware checks did not pass, agreement means
    they made the same mistake, which is what a shared training corpus produces.
    So high agreement alone never returns ACCEPT.

    *parser self-confidence는 calibration 후 보조 신호로만 사용.* It is accepted
    as an argument and used only to escalate, never to accept -- an uncalibrated
    confidence that can promote a result is the blind detector again.
    """
    dimension, weakest = agreement.weakest

    if candidate_count >= 3 and weakest < escalate_threshold:
        return Arbitration(
            outcome=ArbitrationOutcome.HUMAN_REVIEW,
            reason=(
                f"{candidate_count} candidates disagree on {dimension} "
                f"({weakest:.2f}); a three-way conflict has no majority worth "
                "trusting"
            ),
            weakest_dimension=dimension,
        )

    if weakest >= accept_threshold:
        if not source_aware_checks_passed:
            return Arbitration(
                outcome=ArbitrationOutcome.ESCALATE,
                reason=(
                    f"candidates agree ({weakest:.2f} on {dimension}) but the "
                    "source-aware checks did not pass; agreement without them is "
                    "evidence they made the same mistake"
                ),
                weakest_dimension=dimension,
            )
        if parser_self_confidence is not None and parser_self_confidence < 0.5:
            return Arbitration(
                outcome=ArbitrationOutcome.ESCALATE,
                reason=(
                    "the parser's own confidence is low; used here only to "
                    "escalate, never to accept"
                ),
                weakest_dimension=dimension,
            )
        return Arbitration(
            outcome=ArbitrationOutcome.ACCEPT,
            reason=(
                f"candidates agree ({weakest:.2f} on {dimension}) and the "
                "source-aware checks passed"
            ),
            weakest_dimension=dimension,
        )

    if weakest >= escalate_threshold:
        return Arbitration(
            outcome=ArbitrationOutcome.ESCALATE,
            reason=(
                f"candidates disagree on {dimension} ({weakest:.2f}); a third "
                "parser or a stronger verifier decides"
            ),
            weakest_dimension=dimension,
        )

    return Arbitration(
        outcome=ArbitrationOutcome.HUMAN_REVIEW,
        reason=(
            f"candidates disagree badly on {dimension} ({weakest:.2f}); no "
            "automatic choice between them is defensible"
        ),
        weakest_dimension=dimension,
    )


@dataclass(frozen=True, slots=True)
class ConsensusTrigger:
    """§N10.1. A second parser runs only for a stated reason.

    Running one on every document doubles the bill for the majority of pages
    that were right the first time, which is the cost side of §2.4's finding
    that recovery is what makes the system reliable: recovery is worth its price
    precisely because it is targeted.
    """

    inspector_suspicious: bool = False
    verified_mode_high_risk: bool = False
    shadow_benchmark: bool = False
    human_requested: bool = False

    @property
    def should_run(self) -> bool:
        return any(
            (
                self.inspector_suspicious,
                self.verified_mode_high_risk,
                self.shadow_benchmark,
                self.human_requested,
            )
        )

    @property
    def reasons(self) -> tuple[str, ...]:
        named = {
            "inspector_suspicious": self.inspector_suspicious,
            "verified_mode_high_risk": self.verified_mode_high_risk,
            "shadow_benchmark": self.shadow_benchmark,
            "human_requested": self.human_requested,
        }
        return tuple(name for name, flag in named.items() if flag)


@dataclass(frozen=True, slots=True)
class RecoveryLedger:
    """The attempts made against one page, for the receipt and the bill."""

    attempts: tuple[RecoveryAttempt, ...] = field(default_factory=tuple)

    def with_attempt(self, attempt: RecoveryAttempt) -> RecoveryLedger:
        return RecoveryLedger(attempts=(*self.attempts, attempt))

    @property
    def gpu_seconds(self) -> float:
        return sum(attempt.gpu_seconds for attempt in self.attempts)

    @property
    def cost_units(self) -> float:
        return sum(attempt.cost_units for attempt in self.attempts)

    @property
    def succeeded(self) -> bool:
        return any(attempt.succeeded for attempt in self.attempts)
