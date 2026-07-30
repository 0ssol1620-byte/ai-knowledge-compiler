from __future__ import annotations

import pytest
from akc_scheduler.retry_policy import (
    RETRY_POLICY,
    classify_retry_error,
    decide_retry,
)


@pytest.mark.parametrize(
    ("code", "category"),
    [
        ("GPU_PROVIDER_RATE_LIMITED", "provider_429"),
        ("GPU_PROVIDER_5XX", "provider_5xx"),
        ("GPU_WORKER_INPUT_DOWNLOAD_FAILED", "download_timeout"),
        ("GPU_WORKER_CUDA_OOM", "gpu_oom"),
        ("GPU_PROVIDER_INVALID_RESULT", "invalid_output"),
        ("GPU_WORKER_UNSUPPORTED_FILE", "unsupported_file"),
        ("GPU_PROVIDER_UNAVAILABLE", "default"),
    ],
)
def test_retry_error_classification_is_explicit(code: str, category: str) -> None:
    assert classify_retry_error(code) == category


@pytest.mark.parametrize(
    ("code", "expected_delays", "max_retries"),
    [
        ("GPU_PROVIDER_RATE_LIMITED", [2.0, 4.0, 8.0, 16.0, 32.0], 5),
        ("GPU_PROVIDER_5XX", [5.0, 10.0, 20.0], 3),
        ("GPU_WORKER_INPUT_DOWNLOAD_FAILED", [3.0, 6.0], 2),
    ],
)
def test_frozen_retry_schedules_and_caps(
    code: str,
    expected_delays: list[float],
    max_retries: int,
) -> None:
    decisions = [
        decide_retry(
            code=code,
            retryable=True,
            attempt_number=attempt,
            job_max_attempts=10,
            legacy_base_seconds=1,
            legacy_cap_seconds=120,
            jitter_ratio=0,
            random_value=0.5,
        )
        for attempt in range(1, max_retries + 2)
    ]
    assert [item.delay_seconds for item in decisions[:-1]] == expected_delays
    assert all(item.should_retry for item in decisions[:-1])
    assert decisions[-1].should_retry is False
    assert decisions[-1].rule_exhausted is True


def test_job_budget_preempts_error_specific_retry_limit() -> None:
    decision = decide_retry(
        code="GPU_PROVIDER_RATE_LIMITED",
        retryable=True,
        attempt_number=2,
        job_max_attempts=2,
        legacy_base_seconds=1,
        legacy_cap_seconds=120,
        jitter_ratio=0,
        random_value=0.5,
    )
    assert decision.should_retry is False
    assert decision.job_budget_exhausted is True
    assert decision.rule_exhausted is False


def test_oom_escalates_and_terminal_content_errors_never_loop() -> None:
    oom = decide_retry(
        code="GPU_WORKER_CUDA_OUT_OF_MEMORY",
        retryable=False,
        attempt_number=1,
        job_max_attempts=3,
        legacy_base_seconds=1,
        legacy_cap_seconds=120,
        jitter_ratio=0,
        random_value=0.5,
    )
    assert oom.should_retry is True
    assert oom.strategy == "reduce_or_escalate"

    invalid = decide_retry(
        code="GPU_PROVIDER_INVALID_RESULT",
        retryable=True,
        attempt_number=1,
        job_max_attempts=3,
        legacy_base_seconds=1,
        legacy_cap_seconds=120,
        jitter_ratio=0,
        random_value=0.5,
    )
    unsupported = decide_retry(
        code="GPU_WORKER_UNSUPPORTED_FILE",
        retryable=True,
        attempt_number=1,
        job_max_attempts=3,
        legacy_base_seconds=1,
        legacy_cap_seconds=120,
        jitter_ratio=0,
        random_value=0.5,
    )
    assert invalid.should_retry is False
    assert invalid.next_action == "fallback"
    assert unsupported.should_retry is False
    assert unsupported.next_action == "close"
    assert RETRY_POLICY["unsupported_file"].max_retries == 0


def test_jitter_is_bounded_around_exponential_delay() -> None:
    low = decide_retry(
        code="GPU_PROVIDER_5XX",
        retryable=True,
        attempt_number=2,
        job_max_attempts=10,
        legacy_base_seconds=1,
        legacy_cap_seconds=120,
        jitter_ratio=0.2,
        random_value=0,
    )
    high = decide_retry(
        code="GPU_PROVIDER_5XX",
        retryable=True,
        attempt_number=2,
        job_max_attempts=10,
        legacy_base_seconds=1,
        legacy_cap_seconds=120,
        jitter_ratio=0.2,
        random_value=1,
    )
    assert low.delay_seconds == pytest.approx(8)
    assert high.delay_seconds == pytest.approx(12)
