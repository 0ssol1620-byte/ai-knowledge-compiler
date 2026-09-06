"""Error taxonomy (masterplan section 16) and retry policy (section 15.9).

Two facts drive the shape of this module.

*The most expensive failure in the previous campaign was retrying a
deterministic runtime error.* So :data:`RETRY_POLICY` is a table, not a
default-with-exceptions: every one of the 26 error classes names its own
retry budget and the operator action that goes with it, and the classes the
masterplan marks as deterministic carry ``max_retries=0``.

*Operational failure and semantic failure are different problems.*
:func:`classify_failure` therefore refuses to guess: it applies an ordered
list of conservative rules and returns ``UNKNOWN`` when none of them fires.
``UNKNOWN`` is not retryable, so an unclassified failure stops rather than
burning GPU seconds in a loop.

Where the masterplan gives a range ("2~3", "1~2", "0~1") or says "bounded"
without a number, this table takes the *lower*, cheaper bound and records the
masterplan row it came from in :attr:`RetryRule.mp_row`. That is a policy
choice, not measured data; see :data:`RETRY_POLICY_NOTES`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal

from arena.constants import ERROR_CLASSES

__all__ = [
    "RETRY_POLICY",
    "RETRY_POLICY_NOTES",
    "BackoffKind",
    "ErrorClass",
    "RetryRule",
    "classify_failure",
    "is_retryable",
    "retry_rule",
]


class ErrorClass(StrEnum):
    """Masterplan section 16 taxonomy, mirrored from ``arena.constants``."""

    INFRA_CAPACITY = "INFRA_CAPACITY"
    INFRA_NETWORK = "INFRA_NETWORK"
    IMAGE_PULL = "IMAGE_PULL"
    MODEL_DOWNLOAD = "MODEL_DOWNLOAD"
    DEPENDENCY = "DEPENDENCY"
    MODEL_LOAD = "MODEL_LOAD"
    CUDA_INIT = "CUDA_INIT"
    CUDA_OOM = "CUDA_OOM"
    GPU_KERNEL = "GPU_KERNEL"
    TENSOR_SHAPE = "TENSOR_SHAPE"
    INPUT_DECODE = "INPUT_DECODE"
    PREPROCESS = "PREPROCESS"
    INFERENCE_TIMEOUT = "INFERENCE_TIMEOUT"
    INFERENCE_STALL = "INFERENCE_STALL"
    OUTPUT_EMPTY = "OUTPUT_EMPTY"
    OUTPUT_TRUNCATED = "OUTPUT_TRUNCATED"
    OUTPUT_MALFORMED = "OUTPUT_MALFORMED"
    OUTPUT_REPETITION = "OUTPUT_REPETITION"
    POSTPROCESS = "POSTPROCESS"
    UPLOAD = "UPLOAD"
    CHECKSUM = "CHECKSUM"
    RATE_LIMIT = "RATE_LIMIT"
    AUTH = "AUTH"
    SUBSCRIPTION_LIMIT = "SUBSCRIPTION_LIMIT"
    EVALUATOR = "EVALUATOR"
    UNKNOWN = "UNKNOWN"


if tuple(member.value for member in ErrorClass) != ERROR_CLASSES:  # pragma: no cover
    raise RuntimeError(
        "arena.core.errors.ErrorClass drifted from arena.constants.ERROR_CLASSES; "
        "the constants file is the single source of truth"
    )


BackoffKind = Literal["none", "exponential_jitter", "retry_after"]


@dataclass(frozen=True, slots=True)
class RetryRule:
    """One row of the masterplan section 15.9 retry table.

    ``mp_row`` names the masterplan row this rule implements so an auditor can
    check the mapping without re-deriving it.
    """

    max_retries: int
    backoff: BackoffKind
    action: str
    mp_row: str

    @property
    def retryable(self) -> bool:
        return self.max_retries > 0


_TRANSIENT_NETWORK: Final = "transient network (max 3, exponential backoff + jitter)"
_RATE_LIMITED: Final = "429/rate limit (bounded, honour Retry-After)"
_PROVIDER_CAPACITY: Final = "provider capacity (2~3, other healthy replica)"
_WORKER_LOST: Final = "worker lost (1~2, requeue with the same job id)"
_OOM: Final = "OOM (1, after reducing batch/concurrency)"
_ONE_OFF_MALFORMED: Final = "malformed one-off response (1, same config retry)"
_DETERMINISTIC_SCHEMA: Final = "deterministic schema failure (0~1, no repeat, quarantine)"
_DEPENDENCY_IMPORT: Final = "dependency/import error (0, worker drain + runtime fix)"
_MODEL_LOAD_FAILURE: Final = "model load failure (0, worker drain + runtime fix)"
_TENSOR_SHAPE_REPEAT: Final = "repeated tensor-shape error (0, runtime quarantine)"
_CORRUPT_SOURCE: Final = "corrupt source (0, source quarantine)"
_EVALUATOR_SIDE: Final = "GT/evaluator error (no inference retry, evaluator side fix)"


RETRY_POLICY: Final[MappingProxyType[ErrorClass, RetryRule]] = MappingProxyType(
    {
        ErrorClass.INFRA_CAPACITY: RetryRule(
            2,
            "exponential_jitter",
            "reschedule onto a different healthy replica or the next gpu_pool_priority entry",
            _PROVIDER_CAPACITY,
        ),
        ErrorClass.INFRA_NETWORK: RetryRule(
            3,
            "exponential_jitter",
            "retry the same job id; a fourth failure escalates to the provider watchdog",
            _TRANSIENT_NETWORK,
        ),
        ErrorClass.IMAGE_PULL: RetryRule(
            3,
            "exponential_jitter",
            "re-pull the pinned image digest; a persistent failure is a runtime fix, not a retry",
            _TRANSIENT_NETWORK,
        ),
        ErrorClass.MODEL_DOWNLOAD: RetryRule(
            3,
            "exponential_jitter",
            "re-fetch the pinned revision and re-verify the largest weight file sha256",
            _TRANSIENT_NETWORK,
        ),
        ErrorClass.DEPENDENCY: RetryRule(
            0,
            "none",
            "drain the worker, fix the runtime image, requalify through the canary",
            _DEPENDENCY_IMPORT,
        ),
        ErrorClass.MODEL_LOAD: RetryRule(
            0,
            "none",
            "drain the worker, fix the runtime, requalify through the canary",
            _MODEL_LOAD_FAILURE,
        ),
        ErrorClass.CUDA_INIT: RetryRule(
            0,
            "none",
            "drain the worker; a CUDA init failure is a driver/image fix, never a retry",
            _MODEL_LOAD_FAILURE,
        ),
        ErrorClass.CUDA_OOM: RetryRule(
            1,
            "none",
            "reduce per-worker concurrency (and batch) to 1, then retry once; "
            "a second OOM quarantines the runtime",
            _OOM,
        ),
        ErrorClass.GPU_KERNEL: RetryRule(
            0,
            "none",
            "quarantine the runtime and collect diagnostics; a kernel fault repeats",
            _TENSOR_SHAPE_REPEAT,
        ),
        ErrorClass.TENSOR_SHAPE: RetryRule(
            0,
            "none",
            "quarantine the runtime (masterplan section 14: MinerU VLM concurrency incident)",
            _TENSOR_SHAPE_REPEAT,
        ),
        ErrorClass.INPUT_DECODE: RetryRule(
            0,
            "none",
            "quarantine the source sample; a corrupt input decodes the same way every time",
            _CORRUPT_SOURCE,
        ),
        ErrorClass.PREPROCESS: RetryRule(
            0,
            "none",
            "quarantine the case; preprocessing is deterministic so a retry repeats",
            _DETERMINISTIC_SCHEMA,
        ),
        ErrorClass.INFERENCE_TIMEOUT: RetryRule(
            1,
            "none",
            "requeue once with the same inference_job_id on another healthy worker",
            _WORKER_LOST,
        ),
        ErrorClass.INFERENCE_STALL: RetryRule(
            1,
            "none",
            "kill the stalled worker, then requeue once with the same inference_job_id",
            _WORKER_LOST,
        ),
        ErrorClass.OUTPUT_EMPTY: RetryRule(
            1,
            "none",
            "retry once with the same config; a repeat is a real blank page "
            "(masterplan section 41) or a runtime bug, never silently dropped",
            _ONE_OFF_MALFORMED,
        ),
        ErrorClass.OUTPUT_TRUNCATED: RetryRule(
            1,
            "none",
            "retry once with the same config; a repeat is recorded, never trimmed to look valid",
            _ONE_OFF_MALFORMED,
        ),
        ErrorClass.OUTPUT_MALFORMED: RetryRule(
            1,
            "none",
            "retry once with the same config; a repeat quarantines the case",
            _ONE_OFF_MALFORMED,
        ),
        ErrorClass.OUTPUT_REPETITION: RetryRule(
            1,
            "none",
            "retry once with the same config; a repeat quarantines the case",
            _ONE_OFF_MALFORMED,
        ),
        ErrorClass.POSTPROCESS: RetryRule(
            0,
            "none",
            "quarantine the case; canonicalization is deterministic so a retry repeats",
            _DETERMINISTIC_SCHEMA,
        ),
        ErrorClass.UPLOAD: RetryRule(
            3,
            "exponential_jitter",
            "re-upload; the page result is already persisted on the worker so no inference repeats",
            _TRANSIENT_NETWORK,
        ),
        ErrorClass.CHECKSUM: RetryRule(
            0,
            "none",
            "quarantine the source; a checksum mismatch is an integrity violation, not a flake",
            _CORRUPT_SOURCE,
        ),
        ErrorClass.RATE_LIMIT: RetryRule(
            3,
            "retry_after",
            "wait out Retry-After, then retry within the bound; never tighten the loop",
            _RATE_LIMITED,
        ),
        ErrorClass.AUTH: RetryRule(
            0,
            "none",
            "stop; an auth failure is a configuration fix and a retry only burns quota",
            _DEPENDENCY_IMPORT,
        ),
        ErrorClass.SUBSCRIPTION_LIMIT: RetryRule(
            0,
            "none",
            "pause the queue and checkpoint (masterplan section 21.8); "
            "no fallback, no model downgrade, no API auto-switch",
            _EVALUATOR_SIDE,
        ),
        ErrorClass.EVALUATOR: RetryRule(
            0,
            "none",
            "fix the evaluator side; never re-run inference because scoring failed",
            _EVALUATOR_SIDE,
        ),
        ErrorClass.UNKNOWN: RetryRule(
            0,
            "none",
            "stop and classify; an unclassified failure is never retried blind",
            _DETERMINISTIC_SCHEMA,
        ),
    }
)

RETRY_POLICY_NOTES: Final[MappingProxyType[str, str]] = MappingProxyType(
    {
        "ranges": (
            "Masterplan section 15.9 gives ranges for provider capacity (2~3), "
            "worker lost (1~2) and deterministic schema failure (0~1). This table "
            "takes the lower bound in each case: fewer retries cost less and the "
            "section's own warning is about over-retrying."
        ),
        "rate_limit_bound": (
            "Section 15.9 says 429 handling is 'bounded' without a number. "
            "3 is this campaign's chosen bound, not a measured value."
        ),
        "unlisted_classes": (
            "IMAGE_PULL, MODEL_DOWNLOAD, UPLOAD, CUDA_INIT, GPU_KERNEL, AUTH, "
            "SUBSCRIPTION_LIMIT and UNKNOWN are not rows of the section 15.9 table. "
            "Each is mapped to the row it behaves like and RetryRule.mp_row names it."
        ),
    }
)


def retry_rule(error_class: ErrorClass | str) -> RetryRule:
    """The retry rule for one error class. Unknown names raise, never default."""

    try:
        resolved = ErrorClass(error_class)
    except ValueError as exc:
        raise ValueError(f"unknown error class {error_class!r}") from exc
    return RETRY_POLICY[resolved]


def is_retryable(error_class: ErrorClass | str) -> bool:
    return retry_rule(error_class).retryable


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Rule:
    error_class: ErrorClass
    pattern: re.Pattern[str] | None = None
    exc_names: frozenset[str] = frozenset()
    http_statuses: frozenset[int] = frozenset()


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# Ordered. The first rule that matches wins, so the specific and expensive
# diagnoses (OOM, tensor shape, subscription limit) sit above the generic ones.
_RULES: Final[tuple[_Rule, ...]] = (
    _Rule(
        ErrorClass.CUDA_OOM,
        _rx(r"cuda out of memory|out of memory.*cuda|gpu out of memory|cublas_status_alloc_failed"),
        frozenset({"OutOfMemoryError", "torch.cuda.OutOfMemoryError", "CudaOutOfMemoryError"}),
    ),
    _Rule(
        ErrorClass.TENSOR_SHAPE,
        _rx(
            r"size mismatch|shape mismatch|mismatched shapes|"
            r"sizes of tensors must match|shapes cannot be multiplied|"
            r"expected .*shape|invalid shape|dimension out of range"
        ),
    ),
    _Rule(
        ErrorClass.DEPENDENCY,
        _rx(r"no module named|cannot import name|modulenotfounderror|importerror"),
        frozenset({"ModuleNotFoundError", "ImportError"}),
    ),
    _Rule(
        ErrorClass.SUBSCRIPTION_LIMIT,
        _rx(
            r"subscription limit|usage limit|plan limit|"
            r"you(?:'ve| have) reached your .*limit|weekly limit|monthly limit|"
            r"limit will reset|upgrade to continue"
        ),
    ),
    _Rule(
        ErrorClass.RATE_LIMIT,
        _rx(r"rate limit|rate_limit|too many requests|retry-after"),
        http_statuses=frozenset({429}),
    ),
    _Rule(
        ErrorClass.AUTH,
        _rx(
            r"unauthorized|forbidden|authentication failed|invalid api key|"
            r"invalid_api_key|permission denied.*credential"
        ),
        http_statuses=frozenset({401, 403}),
    ),
    _Rule(
        ErrorClass.CUDA_INIT,
        _rx(r"cuda error|no cuda-capable device|cuda driver version|nvml|cuda initialization"),
    ),
    _Rule(
        ErrorClass.CHECKSUM,
        _rx(r"checksum mismatch|sha256 mismatch|digest mismatch|hash mismatch"),
    ),
    _Rule(
        ErrorClass.INPUT_DECODE,
        _rx(r"cannot identify image file|truncated file read|broken data stream|unidentifiedimage"),
        frozenset({"UnidentifiedImageError"}),
    ),
    _Rule(
        ErrorClass.INFERENCE_TIMEOUT,
        _rx(r"timed out|timeout"),
        frozenset({"TimeoutError", "ReadTimeout", "ReadTimeoutError", "asyncio.TimeoutError"}),
        http_statuses=frozenset({504}),
    ),
    _Rule(
        ErrorClass.OUTPUT_EMPTY,
        _rx(r"empty output|output is empty|no output (?:was )?produced|returned no text"),
    ),
    _Rule(
        ErrorClass.OUTPUT_TRUNCATED,
        _rx(r"truncated output|output truncated|max(?:_new)?_tokens reached|length limit reached"),
    ),
    _Rule(
        ErrorClass.MODEL_LOAD,
        _rx(
            r"failed to load (?:the )?(?:model|checkpoint)|"
            r"checkpoint .*not found|revision mismatch"
        ),
    ),
    _Rule(
        ErrorClass.INFRA_NETWORK,
        _rx(
            r"connection reset|connection refused|connection aborted|"
            r"temporary failure in name resolution|network is unreachable"
        ),
        frozenset({"ConnectionError", "ConnectionResetError", "ConnectTimeout"}),
        http_statuses=frozenset({502, 503}),
    ),
)


def classify_failure(
    exc_type_name: str,
    message: str,
    stderr: str = "",
    http_status: int | None = None,
) -> tuple[ErrorClass, bool]:
    """Map a raw failure onto the taxonomy plus its retryability.

    Returns ``(ErrorClass.UNKNOWN, False)`` when no conservative rule fires.
    That is deliberate: guessing a retryable class for an unrecognised failure
    is exactly how a deterministic bug turns into a hundred paid retries.

    ``message`` and ``stderr`` are read for classification only. Neither is
    stored by this function, and a caller that puts either into a receipt must
    pass it through ``arena.core.receipts.assert_secret_free`` first.
    """

    haystack = "\n".join(part for part in (message, stderr) if part)
    name = (exc_type_name or "").strip()
    short_name = name.rsplit(".", maxsplit=1)[-1]
    for rule in _RULES:
        if rule.exc_names and (name in rule.exc_names or short_name in rule.exc_names):
            return rule.error_class, is_retryable(rule.error_class)
        if rule.pattern is not None and haystack and rule.pattern.search(haystack):
            return rule.error_class, is_retryable(rule.error_class)
        if http_status is not None and http_status in rule.http_statuses:
            return rule.error_class, is_retryable(rule.error_class)
    return ErrorClass.UNKNOWN, False
