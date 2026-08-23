"""Validation for public metadata, and the source-content injection boundary.

Two responsibilities live here because both sit exactly where untrusted bytes
meet a trust boundary:

1. ``validate_public_payload`` — event/error metadata that must never carry
   document bodies, secrets, binary blobs, NaN or unbounded strings.
2. ``sanitize_source_content`` / ``ToolScopeGuard`` — masterplan §N19's
   text-level boundary for source content on its way into a prompt. Detection
   *labels*; it never decides what may be obeyed (`akc_cir.trust` owns that
   structural rule, and this module reuses its two-channel renderer rather
   than inventing a second one).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .trust import UntrustedBlock, build_data_channel

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "body",
        "content",
        "cookie",
        "credential",
        "decrypted",
        "document",
        "document_text",
        "password",
        "prompt",
        "raw_output",
        "raw_text",
        "secret",
        "source_text",
        "token",
    }
)


def _canonical_key(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).casefold()


def _sensitive_key(value: str) -> bool:
    canonical = _canonical_key(value)
    return (
        canonical in _SENSITIVE_KEYS
        or canonical.endswith(("_api_key", "_credential", "_password", "_secret"))
        or canonical.startswith(("raw_output", "raw_text", "source_text"))
    )


def validate_public_payload(value: Any, *, path: str = "$") -> Any:
    """Recursively reject content, secrets, bytes, NaN, and unbounded strings."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if _sensitive_key(text_key) and item is not None:
                raise ValueError(f"sensitive public payload key at {path}.{text_key}")
            result[text_key] = validate_public_payload(item, path=f"{path}.{text_key}")
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > 1000:
            raise ValueError(f"public payload sequence is too large at {path}")
        return [
            validate_public_payload(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, str):
        if len(value) > 2048:
            raise ValueError(f"public payload string is too long at {path}")
        return value
    if isinstance(value, (bytes, bytearray)):
        raise ValueError(f"binary public payload value is forbidden at {path}")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite public payload number at {path}")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ValueError(f"unsupported public payload type at {path}")


# ---------------------------------------------------------------------------
# Source-content injection boundary (§N19 text level).
#
# Same philosophy as akc_cir.trust: the defence is structural. A detector that
# catches nine of ten injection attempts still executes the tenth, so nothing
# downstream may depend on this scan being complete. What it does guarantee:
#
# - suspicious passages are ESCAPED AND LABELLED, never removed — §N19.1 keeps
#   them as evidence, and a redacted document answers a different question;
# - the original bytes are preserved verbatim and bound to their sha256;
# - the wrapper delimiters are structurally reserved: any occurrence of them
#   in the input is demoted before analysis, so a payload cannot forge or
#   close the wrapper early.
# ---------------------------------------------------------------------------

__all__ = [
    "InjectionFinding",
    "PromptAssembly",
    "SanitizedContent",
    "SourceThreatKind",
    "ToolScope",
    "ToolScopeGuard",
    "ToolScopeViolation",
    "sanitize_source_content",
    "validate_public_payload",
]

#: Reserved wrapper delimiters. U+27E6/U+27E7 (mathematical white square
#: brackets) do not occur in ordinary documents, which is what makes them safe
#: to reserve: anything that carries one is by construction trying to speak in
#: this module's voice.
_FENCE_OPEN_CHAR = "\u27e6"
_FENCE_CLOSE_CHAR = "\u27e7"


class SourceThreatKind(StrEnum):
    """What a source passage resembles. A label for routing, never permission."""

    #: "ignore previous instructions" and its translations.
    IMPERATIVE_OVERRIDE = "IMPERATIVE_OVERRIDE"
    #: Role markers and persona hijacks ("system:", "you are now ...").
    SYSTEM_PROMPT_MIMICRY = "SYSTEM_PROMPT_MIMICRY"
    #: Passages steering the model toward invoking tools or commands.
    TOOL_CALL_INDUCED = "TOOL_CALL_INDUCED"
    #: Input contained this module's reserved wrapper delimiters.
    DELIMITER_NEUTRALIZED = "DELIMITER_NEUTRALIZED"


_SOURCE_THREAT_PATTERNS: tuple[tuple[re.Pattern[str], SourceThreatKind], ...] = (
    (
        re.compile(
            r"(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+)?(?:the\s+)?"
            r"(?:previous|prior|above|earlier)\s+"
            r"(?:instructions?|prompts?|rules?|directions?)",
            re.IGNORECASE,
        ),
        SourceThreatKind.IMPERATIVE_OVERRIDE,
    ),
    (
        # Korean word order varies; keep the gaps loose like trust.py does.
        re.compile(
            r"(?:이전|위의|앞의|기존)[^\n]{0,20}(?:지시|명령|규칙|프롬프트)"
            r"[^\n]{0,10}(?:무시|잊)",
        ),
        SourceThreatKind.IMPERATIVE_OVERRIDE,
    ),
    (
        re.compile(
            r"^[ \t]*(?:system|assistant|developer)[ \t]*:"
            r"|<\s*/?\s*(?:system|assistant)\s*>"
            r"|\[\s*INST\s*\]"
            r"|<\|(?:im_start|im_end|tool_call|function_call)[^>]*\|>",
            re.IGNORECASE | re.MULTILINE,
        ),
        SourceThreatKind.SYSTEM_PROMPT_MIMICRY,
    ),
    (
        re.compile(
            r"\b(?:you\s+are\s+now|from\s+now\s+on[^.\n]{0,20}\byou\s+are"
            r"|act\s+as\s+an?\b)",
            re.IGNORECASE,
        ),
        SourceThreatKind.SYSTEM_PROMPT_MIMICRY,
    ),
    (
        re.compile(
            r"\b(?:call|invoke|execute|run)\s+(?:the\s+)?(?:tool|function|command"
            r"|shell|script)\b"
            r"|도구[를]?\s*(?:호출|실행)",
            re.IGNORECASE,
        ),
        SourceThreatKind.TOOL_CALL_INDUCED,
    ),
)


@dataclass(frozen=True, slots=True)
class InjectionFinding:
    """One detected passage, kept so a reviewer can read it in context."""

    kind: SourceThreatKind
    matched_text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class SanitizedContent:
    """A source text after labelling, with its evidence intact.

    ``sanitized_text`` differs from ``original_text`` only where a threat kind
    was detected: the passage itself is still there verbatim, wrapped between
    reserved delimiters that name what it resembled. Nothing is deleted.
    """

    original_text: str
    original_sha256: str
    sanitized_text: str
    findings: tuple[InjectionFinding, ...] = ()

    @property
    def is_suspicious(self) -> bool:
        return bool(self.findings)

    @property
    def threat_kinds(self) -> tuple[SourceThreatKind, ...]:
        return tuple(dict.fromkeys(finding.kind for finding in self.findings))


def _neutralize_fences(text: str) -> tuple[str, list[InjectionFinding]]:
    """Demote any reserved delimiter in the input before analysis."""
    findings: list[InjectionFinding] = []
    for position, char in enumerate(text):
        if char in (_FENCE_OPEN_CHAR, _FENCE_CLOSE_CHAR):
            findings.append(
                InjectionFinding(
                    kind=SourceThreatKind.DELIMITER_NEUTRALIZED,
                    matched_text=char,
                    start=position,
                    end=position + 1,
                )
            )
    if not findings:
        return text, []
    return (
        text.replace(_FENCE_OPEN_CHAR, "(").replace(_FENCE_CLOSE_CHAR, ")"),
        findings,
    )


def _detect_threats(text: str) -> list[InjectionFinding]:
    found: list[InjectionFinding] = []
    for pattern, kind in _SOURCE_THREAT_PATTERNS:
        for match in pattern.finditer(text):
            found.append(
                InjectionFinding(
                    kind=kind,
                    matched_text=match.group(0),
                    start=match.start(),
                    end=match.end(),
                )
            )
    # Longest match wins inside an overlap so a compound phrase is labelled
    # once with its most specific single wrap instead of nested fragments.
    found.sort(key=lambda f: (f.start, -(f.end - f.start)))
    accepted: list[InjectionFinding] = []
    for finding in found:
        if accepted and finding.start < accepted[-1].end:
            continue
        accepted.append(finding)
    return accepted


#: Characters that bound a passage for labelling purposes. Newlines always
#: separate passages; ., ! and ? terminate one mid-line.
_PASSAGE_BREAKS = ".!?\n"


def _passage_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Grow a match to its surrounding passage so evidence is never split.

    Wrapping only the regex core would carve a flag word out of the middle of
    its sentence ("…무시⟦/UNTRUSTED…⟧하세요."), leaving the passage readable
    but its evidence chopped into fragments across wrapper boundaries. The
    label therefore covers the whole passage containing the match.
    """
    begin = start
    while begin > 0 and text[begin - 1] not in _PASSAGE_BREAKS:
        begin -= 1
    finish = end
    while finish < len(text):
        if text[finish] in _PASSAGE_BREAKS:
            if text[finish] != "\n":
                finish += 1  # keep the terminator inside the labelled passage
            break
        finish += 1
    return begin, finish


def _group_by_passage(
    findings: list[InjectionFinding], text: str
) -> list[tuple[tuple[int, int], list[InjectionFinding]]]:
    """Merge findings whose grown passages overlap into shared spans."""
    groups: list[tuple[tuple[int, int], list[InjectionFinding]]] = []
    for finding in findings:
        span = _passage_span(text, finding.start, finding.end)
        if groups and span[0] < groups[-1][0][1]:
            (prev_begin, prev_end), members = groups[-1]
            groups[-1] = ((prev_begin, max(prev_end, span[1])), [*members, finding])
        else:
            groups.append((span, [finding]))
    return groups


def _wrap(finding_kind: SourceThreatKind, closing: bool = False) -> str:
    prefix = "/" if closing else ""
    return f"{_FENCE_OPEN_CHAR}{prefix}UNTRUSTED:{finding_kind.value}{_FENCE_CLOSE_CHAR}"


def sanitize_source_content(text: str) -> SanitizedContent:
    """Label instruction-like passages in untrusted source text.

    Escape-and-label, not removal: each detection grows to its surrounding
    passage, which is then wrapped between reserved delimiters naming every
    threat kind it resembled, leaving the passage readable as evidence and
    never split mid-phrase. The original text and its sha256 are preserved on
    the result regardless of how many labels were applied. Like
    ``scan_for_injection``, this decides nothing about obedience — the
    two-channel prompt assembly (`ToolScopeGuard.assemble_prompt`) applies
    whether or not anything was found.
    """
    neutralized, fence_findings = _neutralize_fences(text)
    threats = _detect_threats(neutralized)
    parts: list[str] = []
    cursor = 0
    for (begin, finish), members in _group_by_passage(threats, neutralized):
        parts.append(neutralized[cursor:begin])
        # One passage may resemble several threat kinds at once ("ignore
        # previous instructions and invoke the tool …"). Each kind gets its
        # own reserved wrapper, nested around the same intact passage, so no
        # label ever slices the evidence mid-phrase.
        kinds = list(dict.fromkeys(member.kind for member in members))
        for kind in kinds:
            parts.append(_wrap(kind))
        parts.append(neutralized[begin:finish])
        for kind in reversed(kinds):
            parts.append(_wrap(kind, closing=True))
        cursor = finish
    parts.append(neutralized[cursor:])
    return SanitizedContent(
        original_text=text,
        original_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        sanitized_text="".join(parts),
        findings=tuple(sorted([*fence_findings, *threats], key=lambda f: f.start)),
    )


@dataclass(frozen=True, slots=True)
class ToolScope:
    """The tool surface one guarded session may touch. Constructor-set only."""

    allowed_tools: frozenset[str]
    allow_execution: bool = False


class ToolScopeViolation(ValueError):
    """Raised when a call tries to act outside the parameter-declared scope."""


class ToolScopeGuard:
    """Actual tool scope comes from parameters alone — never from source text.

    A document that says "call the admin tool" has expressed a wish, not a
    grant. This guard makes the distinction structural: the allowed set is
    fixed at construction time, scope resolution accepts no text-shaped input
    at all, and any invocation whose *only* backing is source content is
    refused even for a nominally allowed tool name.
    """

    def __init__(
        self, allowed_tools: Iterable[str], *, allow_execution: bool = False
    ) -> None:
        self._scope = ToolScope(
            allowed_tools=frozenset(allowed_tools), allow_execution=allow_execution
        )

    @property
    def scope(self) -> ToolScope:
        return self._scope

    def authorize(self, tool_name: str) -> bool:
        """Is this tool inside the declared scope?"""
        return tool_name in self._scope.allowed_tools

    def authorize_invocation(
        self, tool_name: str, *, requested_by_source_content: bool
    ) -> bool:
        """Content may request, but content may never authorise.

        Even a tool inside the declared scope is denied when the request's
        provenance is source text; §N43 counts any such execution as a breach.
        """
        if requested_by_source_content:
            return False
        return self.authorize(tool_name)

    def require_authorized(self, tool_name: str) -> None:
        if not self.authorize(tool_name):
            raise ToolScopeViolation(
                f"tool {tool_name!r} is outside the declared tool scope "
                f"{sorted(self._scope.allowed_tools)}"
            )

    def resolve_scope(self, requested: Iterable[str] | None = None) -> ToolScope:
        """Intersect a caller-requested subset with the declared scope.

        Deliberately takes no source-text or hint argument: there is no input
        shape here through which content could widen the scope, only narrow it.
        """
        if requested is None:
            return self._scope
        wanted = frozenset(requested) & self._scope.allowed_tools
        return ToolScope(
            allowed_tools=wanted, allow_execution=self._scope.allow_execution
        )

    def assemble_prompt(
        self,
        *,
        system_instruction: str,
        untrusted_source: str | SanitizedContent,
        source_id: str = "source",
    ) -> PromptAssembly:
        """Build a model-bound prompt with the channels structurally apart.

        ``system_instruction`` must be non-empty and lands, verbatim and alone,
        in the system role. Source content — raw or already sanitized — is
        sanitized if needed and rendered through trust.py's two-channel data
        block into the user role. No method on the result can move untrusted
        text into the trusted channel afterwards.
        """
        if not system_instruction.strip():
            raise ValueError("system_instruction must be a non-empty string")
        content = (
            sanitize_source_content(untrusted_source)
            if isinstance(untrusted_source, str)
            else untrusted_source
        )
        data_channel = build_data_channel(
            [UntrustedBlock(block_id=source_id, text=content.sanitized_text)]
        ).render()
        return PromptAssembly(
            system_instruction=system_instruction,
            data_channel=data_channel,
            source_sha256=content.original_sha256,
            suspicious=content.is_suspicious,
            indicators=tuple(kind.value for kind in content.threat_kinds),
        )


@dataclass(frozen=True, slots=True)
class PromptAssembly:
    """A model-bound prompt whose channels never merge.

    ``system_instruction`` holds exactly what the caller passed as system
    instruction — assembling cannot append to it, and being frozen, nothing
    can mutate it afterwards. Source content travels only in
    ``data_channel``, wrapped in trust.py's two-channel rendering with
    ``executable="false"``, labelled by ``sanitize_source_content`` and bound
    to the original text's sha256.
    """

    system_instruction: str
    data_channel: str
    source_sha256: str
    suspicious: bool
    indicators: tuple[str, ...]

    def messages(self) -> tuple[dict[str, str], ...]:
        """Role-separated messages: trusted system channel, untrusted data turn."""
        return (
            {"role": "system", "content": self.system_instruction},
            {"role": "user", "content": self.data_channel},
        )

