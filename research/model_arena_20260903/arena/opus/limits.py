"""Subscription / rate / capacity limit detection (masterplan section 21.8).

What this module is allowed to do when it fires: stop dispatching, checkpoint,
record a reset time if one was reported, exit 75. What it must never do: retry
with another model, switch to the API, or downgrade. A limit is an operational
failure of the *surface*, not a semantic failure of the model, and the campaign
records it as a pause rather than as a page result.

Sources for the strings matched below (recorded because a matcher built on
guessed wording is not evidence):

- https://code.claude.com/docs/en/headless -- documents the ``system/api_retry``
  event whose ``error`` field takes the values ``authentication_failed``,
  ``oauth_org_not_allowed``, ``billing_error``, ``rate_limit``, ``overloaded``,
  ``invalid_request``, ``model_not_found``, ``server_error``,
  ``max_output_tokens``, ``unknown``. Those category names are the CLI's own
  vocabulary and are matched exactly.
- https://code.claude.com/docs/en/headless -- "Claude Code exits with code 0 on
  success and a non-zero code when the run fails"; SIGTERM produces exit 143.
  "When a failure happens inside the run, such as missing authentication, Claude
  Code prints the failure as the result on stdout" -- which is why the ``result``
  text is searched as well as stderr.
- https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work
  -- fetched 2026-09-03. It describes limits conceptually and states "If you hit
  your usage limit, you'll need to wait for it to reset, upgrade your plan, or
  purchase usage credits." It publishes NO verbatim CLI error string. The
  usage-limit phrases below are therefore matched on the wording families the
  product is known to use ("usage limit", "limit reached", "resets at", "upgrade
  to Max"), and every match records which phrase fired so a wrong matcher is
  visible in the receipt rather than silent.

Because the support article does not publish the exact strings, this classifier
is deliberately biased toward *pausing*: an unrecognised error still stops the
page, and only a recognised limit stops the whole pool. It never converts a limit
into a scored page.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

SUBSCRIPTION_LIMIT: Final = "SUBSCRIPTION_LIMIT"
RATE_LIMIT: Final = "RATE_LIMIT"
TEMPORARY_CAPACITY: Final = "TEMPORARY_CAPACITY"
# The child's OAuth session (subscription auth, not a limit on usage) expired
# and could not be refreshed. This is an infrastructure/auth condition, not a
# page failure: no page receipt is written for it (arena/opus/runner.py), the
# queue pauses, and the checkpoint carries a fixed reset hint pointing at
# `claude login`. There is deliberately no fallback of any kind (no API key,
# no other model) -- a standing founder rule.
AUTH_EXPIRED: Final = "AUTH_EXPIRED"

# TEMPORARY_CAPACITY is an operational condition, not one of the frozen
# ERROR_CLASSES in arena.constants; it is recorded on the receipt as
# INFRA_CAPACITY with the limit kind kept in the checkpoint and error message.
# AUTH_EXPIRED never reaches a receipt at all (see above), but is mapped to the
# frozen "AUTH" error class for anything that logs it before that decision.
LIMIT_KIND_TO_ERROR_CLASS: Final = {
    SUBSCRIPTION_LIMIT: "SUBSCRIPTION_LIMIT",
    RATE_LIMIT: "RATE_LIMIT",
    TEMPORARY_CAPACITY: "INFRA_CAPACITY",
    AUTH_EXPIRED: "AUTH",
}

# Fixed reset hint for AUTH_EXPIRED: unlike the other limit kinds, the CLI's
# auth-failure text never carries a reset time to parse, so the hint is not
# extracted -- it is always this fixed instruction.
AUTH_EXPIRED_RESET_HINT: Final = (
    "re-authenticate with `claude login` (subscription OAuth), then "
    "`python -m arena.opus resume --execute`"
)

# (kind, source_label, compiled pattern). ``source_label`` is written into the
# checkpoint so a future reader can see which documented family matched.
_PATTERNS: Final[tuple[tuple[str, str, re.Pattern[str]], ...]] = (
    (
        AUTH_EXPIRED,
        "code.claude.com/docs/en/headless api_retry error=authentication_failed",
        re.compile(r"authentication_failed", re.IGNORECASE),
    ),
    (
        AUTH_EXPIRED,
        "runs/opus5_subscription/raw/olmocr-bench-83a5e23571dfcfe2482ddf35.claude.json "
        "(2026-09-04T05:46 attempt)",
        re.compile(r"failed to authenticate", re.IGNORECASE),
    ),
    (
        AUTH_EXPIRED,
        "runs/opus5_subscription/raw/olmocr-bench-83a5e23571dfcfe2482ddf35.claude.json "
        "(2026-09-04T05:46 attempt)",
        re.compile(r"oauth session expired", re.IGNORECASE),
    ),
    (
        AUTH_EXPIRED,
        "code.claude.com/docs/en/headless wording family",
        re.compile(r"\bnot logged in\b", re.IGNORECASE),
    ),
    (
        AUTH_EXPIRED,
        "code.claude.com/docs/en/headless wording family",
        re.compile(r"invalid authentication", re.IGNORECASE),
    ),
    (
        AUTH_EXPIRED,
        "code.claude.com/docs/en/headless api_retry error=oauth_org_not_allowed",
        re.compile(r"oauth_org_not_allowed", re.IGNORECASE),
    ),
    (
        SUBSCRIPTION_LIMIT,
        "support.claude.com/11647753 usage-limit wording family",
        re.compile(r"usage limit", re.IGNORECASE),
    ),
    (
        SUBSCRIPTION_LIMIT,
        "support.claude.com/11647753 usage-limit wording family",
        re.compile(r"limit reached", re.IGNORECASE),
    ),
    (
        SUBSCRIPTION_LIMIT,
        "support.claude.com/11647753 usage-limit wording family",
        re.compile(r"\byou(?:'| a)?re out of (?:usage|credits)\b", re.IGNORECASE),
    ),
    (
        SUBSCRIPTION_LIMIT,
        "support.claude.com/11647753 usage-limit wording family",
        re.compile(r"upgrade to (?:max|pro)\b", re.IGNORECASE),
    ),
    (
        SUBSCRIPTION_LIMIT,
        "support.claude.com/11647753 usage-limit wording family",
        re.compile(r"weekly limit", re.IGNORECASE),
    ),
    (
        SUBSCRIPTION_LIMIT,
        # Real text, 2026-09-04 07:17:59 KST, claude -p result with is_error=true:
        # "You've hit your session limit · resets 7:50am (Asia/Seoul)" (D69).
        "claude -p result text observed on the 5-hour window, 2026-09-04",
        re.compile(r"session limit", re.IGNORECASE),
    ),
    (
        SUBSCRIPTION_LIMIT,
        "claude -p result text observed on the 5-hour window, 2026-09-04",
        re.compile(r"hit your (?:session |weekly |usage |daily )?limit", re.IGNORECASE),
    ),
    (
        RATE_LIMIT,
        "code.claude.com/docs/en/headless api_retry error=rate_limit",
        re.compile(r"\brate[_ ]limit", re.IGNORECASE),
    ),
    (
        RATE_LIMIT,
        "HTTP status text for 429",
        re.compile(r"\b429\b"),
    ),
    (
        RATE_LIMIT,
        "HTTP status text for 429",
        re.compile(r"too many requests", re.IGNORECASE),
    ),
    (
        TEMPORARY_CAPACITY,
        "code.claude.com/docs/en/headless api_retry error=overloaded",
        # Matches both "overloaded" and the API's "overloaded_error" type name.
        re.compile(r"\boverloaded", re.IGNORECASE),
    ),
    (
        TEMPORARY_CAPACITY,
        "code.claude.com/docs/en/headless api_retry error=server_error",
        re.compile(r"\bserver[_ ]error", re.IGNORECASE),
    ),
    (
        TEMPORARY_CAPACITY,
        "HTTP status text for 529/503",
        re.compile(r"\b(?:529|503)\b"),
    ),
    (
        TEMPORARY_CAPACITY,
        "capacity wording family",
        re.compile(r"(?:temporarily unavailable|at capacity|capacity constraint)", re.IGNORECASE),
    ),
)

# "resets at 5pm", "resets on 2026-09-04T13:00:00Z", "try again at 14:30".
_RESET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"resets?\s+(?:at|on)\s+([^\n.;]{3,80})", re.IGNORECASE),
    # "resets 7:50am (Asia/Seoul)" -- no "at", a clock time with am/pm and a zone (D69).
    re.compile(r"resets?\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)[^\n.;]{0,60})", re.IGNORECASE),
    re.compile(r"try again\s+(?:at|after|in)\s+([^\n.;]{2,80})", re.IGNORECASE),
    re.compile(r"available again\s+(?:at|on)\s+([^\n.;]{3,80})", re.IGNORECASE),
    re.compile(r"retry[- ]after[:=]?\s*([0-9]{1,7})", re.IGNORECASE),
)

# The docs state SIGTERM produces 143; that is our own kill, not a limit.
SIGTERM_EXIT_CODE: Final = 143


@dataclass(frozen=True, slots=True)
class LimitDetection:
    kind: str
    error_class: str
    matched_pattern: str
    matched_source: str
    matched_in: str
    reset_hint: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "error_class": self.error_class,
            "matched_pattern": self.matched_pattern,
            "matched_source": self.matched_source,
            "matched_in": self.matched_in,
            "reset_hint": self.reset_hint,
        }


def extract_reset_hint(text: str) -> str | None:
    for pattern in _RESET_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()[:120]
    return None


def _scan(text: str, where: str) -> LimitDetection | None:
    for kind, source, pattern in _PATTERNS:
        if pattern.search(text):
            return LimitDetection(
                kind=kind,
                error_class=LIMIT_KIND_TO_ERROR_CLASS[kind],
                matched_pattern=pattern.pattern,
                matched_source=source,
                matched_in=where,
                # AUTH_EXPIRED's source text (an OAuth failure message) never
                # carries a reset time to parse; the hint is always fixed.
                reset_hint=(
                    AUTH_EXPIRED_RESET_HINT if kind == AUTH_EXPIRED else extract_reset_hint(text)
                ),
            )
    return None


def classify(
    *,
    exit_code: int | None,
    stderr: str,
    payload: Mapping[str, Any] | None,
    raw_stdout: str = "",
) -> LimitDetection | None:
    """Return a limit detection, or ``None`` when this is not a limit.

    Order: the structured payload first (``is_error`` plus ``result`` text and
    any ``error``/``subtype`` category), then stderr, then raw stdout for the
    case where the CLI failed before producing JSON. A zero exit code with a
    clean payload never produces a detection.
    """
    if payload is not None:
        is_error = bool(payload.get("is_error"))
        parts: list[str] = []
        for key in ("subtype", "error", "error_type", "message"):
            value = payload.get(key)
            if isinstance(value, str):
                parts.append(value)
        result = payload.get("result")
        if isinstance(result, str) and (is_error or exit_code not in (0, None)):
            # Only search the model's own text when the run itself failed; a
            # successful transcription of a page that happens to contain the
            # words "usage limit" must never pause the campaign.
            parts.append(result)
        if parts:
            detection = _scan("\n".join(parts), "payload")
            if detection is not None:
                return detection
        if is_error and not parts:
            return None

    if stderr:
        detection = _scan(stderr, "stderr")
        if detection is not None:
            return detection

    if raw_stdout and payload is None:
        detection = _scan(raw_stdout, "stdout")
        if detection is not None:
            return detection

    return None


__all__ = [
    "AUTH_EXPIRED",
    "AUTH_EXPIRED_RESET_HINT",
    "LIMIT_KIND_TO_ERROR_CLASS",
    "RATE_LIMIT",
    "SIGTERM_EXIT_CODE",
    "SUBSCRIPTION_LIMIT",
    "TEMPORARY_CAPACITY",
    "LimitDetection",
    "classify",
    "extract_reset_hint",
]
