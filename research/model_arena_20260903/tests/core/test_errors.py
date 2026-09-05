"""Retry table equals masterplan section 15.9, and classification stays conservative."""

from __future__ import annotations

import pytest
from arena.constants import ERROR_CLASSES
from arena.core.errors import (
    RETRY_POLICY,
    RETRY_POLICY_NOTES,
    ErrorClass,
    classify_failure,
    is_retryable,
    retry_rule,
)

# The masterplan section 15.9 table, transcribed as (max_retries, backoff).
# Ranges take the lower bound; see RETRY_POLICY_NOTES.
EXPECTED_TABLE: dict[str, tuple[int, str]] = {
    # transient network (max 3, exponential backoff + jitter)
    "INFRA_NETWORK": (3, "exponential_jitter"),
    "IMAGE_PULL": (3, "exponential_jitter"),
    "MODEL_DOWNLOAD": (3, "exponential_jitter"),
    "UPLOAD": (3, "exponential_jitter"),
    # 429 / rate limit (bounded, honour Retry-After)
    "RATE_LIMIT": (3, "retry_after"),
    # provider capacity (2~3)
    "INFRA_CAPACITY": (2, "exponential_jitter"),
    # worker lost (1~2, same job id)
    "INFERENCE_TIMEOUT": (1, "none"),
    "INFERENCE_STALL": (1, "none"),
    # OOM (1, after reducing batch/concurrency)
    "CUDA_OOM": (1, "none"),
    # malformed one-off response (1, same config retry)
    "OUTPUT_EMPTY": (1, "none"),
    "OUTPUT_TRUNCATED": (1, "none"),
    "OUTPUT_MALFORMED": (1, "none"),
    "OUTPUT_REPETITION": (1, "none"),
    # deterministic schema failure (0~1, no repeat, quarantine)
    "PREPROCESS": (0, "none"),
    "POSTPROCESS": (0, "none"),
    "UNKNOWN": (0, "none"),
    # dependency/import error (0, worker drain + runtime fix)
    "DEPENDENCY": (0, "none"),
    "AUTH": (0, "none"),
    # model load failure (0, worker drain + runtime fix)
    "MODEL_LOAD": (0, "none"),
    "CUDA_INIT": (0, "none"),
    # repeated tensor-shape error (0, runtime quarantine)
    "TENSOR_SHAPE": (0, "none"),
    "GPU_KERNEL": (0, "none"),
    # corrupt source (0, source quarantine)
    "INPUT_DECODE": (0, "none"),
    "CHECKSUM": (0, "none"),
    # GT/evaluator error (no inference retry)
    "EVALUATOR": (0, "none"),
    "SUBSCRIPTION_LIMIT": (0, "none"),
}


def test_error_class_enum_mirrors_the_constants_exactly() -> None:
    assert tuple(member.value for member in ErrorClass) == ERROR_CLASSES


def test_retry_policy_covers_every_error_class_and_nothing_else() -> None:
    assert {member.value for member in RETRY_POLICY} == set(ERROR_CLASSES)
    assert set(EXPECTED_TABLE) == set(ERROR_CLASSES)


@pytest.mark.parametrize(("name", "expected"), sorted(EXPECTED_TABLE.items()))
def test_retry_policy_matches_masterplan_15_9(name: str, expected: tuple[int, str]) -> None:
    rule = retry_rule(name)
    assert (rule.max_retries, rule.backoff) == expected
    assert rule.action.strip(), f"{name} has no operator action"
    assert rule.mp_row.strip(), f"{name} does not name the masterplan row it implements"
    assert rule.retryable is (rule.max_retries > 0)


def test_the_deterministic_classes_are_never_retried() -> None:
    """The section 15.9 headline: retrying a deterministic error is the costly bug."""

    for name in (
        "DEPENDENCY",
        "MODEL_LOAD",
        "TENSOR_SHAPE",
        "INPUT_DECODE",
        "CHECKSUM",
        "EVALUATOR",
        "SUBSCRIPTION_LIMIT",
        "UNKNOWN",
    ):
        assert not is_retryable(name), f"{name} must not be retried"


def test_retry_policy_notes_record_the_choices_that_are_not_in_the_masterplan() -> None:
    assert set(RETRY_POLICY_NOTES) == {"ranges", "rate_limit_bound", "unlisted_classes"}
    assert all(text.strip() for text in RETRY_POLICY_NOTES.values())


def test_retry_rule_refuses_an_unknown_class() -> None:
    with pytest.raises(ValueError, match="unknown error class"):
        retry_rule("NOT_A_CLASS")


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc_name", "message", "stderr", "http_status", "expected"),
    [
        ("RuntimeError", "CUDA out of memory. Tried to allocate 2.00 GiB", "", None, "CUDA_OOM"),
        ("OutOfMemoryError", "", "", None, "CUDA_OOM"),
        (
            "RuntimeError",
            "The size of tensor a (577) must match; size mismatch at dim 1",
            "",
            None,
            "TENSOR_SHAPE",
        ),
        ("ModuleNotFoundError", "No module named 'paddle'", "", None, "DEPENDENCY"),
        ("ImportError", "cannot import name 'AutoModel'", "", None, "DEPENDENCY"),
        ("TimeoutError", "", "", None, "INFERENCE_TIMEOUT"),
        ("RuntimeError", "inference timed out after 180s", "", None, "INFERENCE_TIMEOUT"),
        ("HTTPStatusError", "", "", 429, "RATE_LIMIT"),
        ("HTTPStatusError", "Too Many Requests", "", None, "RATE_LIMIT"),
        ("HTTPStatusError", "", "", 401, "AUTH"),
        ("HTTPStatusError", "", "", 403, "AUTH"),
        ("RuntimeError", "Unauthorized", "", None, "AUTH"),
        (
            "RuntimeError",
            "You have reached your weekly limit; the limit will reset at 09:00",
            "",
            None,
            "SUBSCRIPTION_LIMIT",
        ),
        ("RuntimeError", "", "adapter returned empty output", None, "OUTPUT_EMPTY"),
        ("RuntimeError", "sha256 mismatch on the page render", "", None, "CHECKSUM"),
        ("RuntimeError", "something nobody has seen before", "", None, "UNKNOWN"),
        ("RuntimeError", "", "", None, "UNKNOWN"),
    ],
)
def test_classify_failure_table(
    exc_name: str, message: str, stderr: str, http_status: int | None, expected: str
) -> None:
    error_class, retryable = classify_failure(exc_name, message, stderr, http_status)
    assert error_class.value == expected
    assert retryable is is_retryable(error_class)


def test_classify_failure_prefers_oom_over_a_co_occurring_timeout() -> None:
    error_class, _ = classify_failure(
        "RuntimeError", "CUDA out of memory after the request timed out"
    )
    assert error_class is ErrorClass.CUDA_OOM


def test_classify_failure_prefers_subscription_limit_over_rate_limit() -> None:
    error_class, retryable = classify_failure(
        "RuntimeError", "Claude usage limit reached; rate limit style wording included"
    )
    assert error_class is ErrorClass.SUBSCRIPTION_LIMIT
    assert retryable is False


def test_an_unclassified_failure_is_never_reported_as_retryable() -> None:
    error_class, retryable = classify_failure("Exception", "opaque")
    assert error_class is ErrorClass.UNKNOWN
    assert retryable is False


def test_ordinary_text_is_not_forced_into_a_class() -> None:
    """Conservative: line numbers and file names must not look like failures."""

    for message in (
        "wrote 429 receipts to disk",
        "loaded runtimes/glm_ocr/adapter.py line 401",
        "task-list rebuilt",
    ):
        error_class, _ = classify_failure("RuntimeError", message)
        assert error_class is ErrorClass.UNKNOWN, message
