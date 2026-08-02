"""Bounded, explainable retry policy for provider and worker failures."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

RetryCategory = Literal[
    "provider_429",
    "provider_5xx",
    "download_timeout",
    "gpu_oom",
    "invalid_output",
    "unsupported_file",
    "default",
]
RetryStrategy = Literal[
    "retry",
    "reduce_or_escalate",
    "fallback",
    "close",
]


@dataclass(frozen=True, slots=True)
class RetryRule:
    max_retries: int
    base_seconds: float
    cap_seconds: float
    strategy: RetryStrategy


@dataclass(frozen=True, slots=True)
class RetryDecision:
    category: RetryCategory
    strategy: RetryStrategy
    should_retry: bool
    delay_seconds: float
    rule_exhausted: bool
    job_budget_exhausted: bool
    transition_allowed: bool

    @property
    def next_action(self) -> str:
        if self.should_retry:
            return self.strategy
        if self.strategy == "retry":
            return "unresolved"
        return self.strategy


RETRY_POLICY: dict[RetryCategory, RetryRule] = {
    "provider_429": RetryRule(5, 2, 60, "retry"),
    "provider_5xx": RetryRule(3, 5, 120, "retry"),
    "download_timeout": RetryRule(2, 3, 30, "retry"),
    "gpu_oom": RetryRule(2, 2, 30, "reduce_or_escalate"),
    "invalid_output": RetryRule(1, 0, 0, "fallback"),
    "unsupported_file": RetryRule(0, 0, 0, "close"),
    # Unknown retryable failures retain the invocation's bounded legacy policy.
    "default": RetryRule(100, 0, 0, "retry"),
}


def classify_retry_error(code: str) -> RetryCategory:
    normalized = code.strip().upper()
    if normalized == "GPU_PROVIDER_RATE_LIMITED":
        return "provider_429"
    if normalized == "GPU_PROVIDER_5XX":
        return "provider_5xx"
    if "UNSUPPORTED" in normalized:
        return "unsupported_file"
    if "OUT_OF_MEMORY" in normalized or normalized.endswith("_OOM") or "_OOM_" in normalized:
        return "gpu_oom"
    if "DOWNLOAD" in normalized and (
        "TIMEOUT" in normalized or normalized == "GPU_WORKER_INPUT_DOWNLOAD_FAILED"
    ):
        return "download_timeout"
    if any(
        marker in normalized
        for marker in (
            "INVALID_RESULT",
            "INVALID_OUTPUT",
            "RESULT_INVALID",
            "CHECKSUM_MISMATCH",
            "RESULT_SCOPE_MISMATCH",
        )
    ):
        return "invalid_output"
    return "default"


def decide_retry(
    *,
    code: str,
    retryable: bool,
    attempt_number: int,
    category_attempt_number: int | None = None,
    job_max_attempts: int,
    legacy_base_seconds: float,
    legacy_cap_seconds: float,
    jitter_ratio: float,
    random_value: float,
) -> RetryDecision:
    """Return one bounded decision; ``attempt_number`` is one-based."""

    if attempt_number < 1 or job_max_attempts < 1:
        raise ValueError("attempt counts must be positive")
    if attempt_number > job_max_attempts:
        raise ValueError("attempt exceeds the job retry budget")
    if (
        not math.isfinite(legacy_base_seconds)
        or not math.isfinite(legacy_cap_seconds)
        or legacy_base_seconds <= 0
        or legacy_cap_seconds < legacy_base_seconds
    ):
        raise ValueError("invalid legacy retry backoff")
    if not 0 <= jitter_ratio <= 1 or not 0 <= random_value <= 1:
        raise ValueError("invalid retry jitter")

    category_number = attempt_number if category_attempt_number is None else category_attempt_number
    if category_number < 1:
        raise ValueError("category attempt count must be positive")
    category = classify_retry_error(code)
    rule = RETRY_POLICY[category]
    job_budget_exhausted = attempt_number >= job_max_attempts
    rule_exhausted = category_number > rule.max_retries
    policy_retryable = retryable
    if category == "gpu_oom":
        policy_retryable = True
    elif category in {"invalid_output", "unsupported_file"}:
        policy_retryable = False
    transition_allowed = (
        rule.strategy in {"reduce_or_escalate", "fallback"}
        and not rule_exhausted
        and not job_budget_exhausted
    )
    should_retry = policy_retryable and not rule_exhausted and not job_budget_exhausted

    if not should_retry:
        delay = 0.0
    else:
        base_seconds = legacy_base_seconds if category == "default" else rule.base_seconds
        cap_seconds = legacy_cap_seconds if category == "default" else rule.cap_seconds
        base = min(cap_seconds, base_seconds * (2 ** max(0, category_number - 1)))
        jittered = base * (1 + ((random_value * 2) - 1) * jitter_ratio)
        delay = float(max(0.0, jittered))

    return RetryDecision(
        category=category,
        strategy=rule.strategy,
        should_retry=should_retry,
        delay_seconds=delay,
        rule_exhausted=rule_exhausted,
        job_budget_exhausted=job_budget_exhausted,
        transition_allowed=transition_allowed,
    )


__all__ = [
    "RETRY_POLICY",
    "RetryCategory",
    "RetryDecision",
    "RetryRule",
    "RetryStrategy",
    "classify_retry_error",
    "decide_retry",
]
