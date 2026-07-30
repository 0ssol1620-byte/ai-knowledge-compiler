"""Advisory indirect-prompt-injection signals; source remains untrusted data."""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum

from akc_cir import ContractModel


class InjectionRisk(StrEnum):
    NONE = "none"
    LOW = "low"
    HIGH = "high"


class InjectionSignal(ContractModel):
    rule_id: str
    excerpt: str


class PromptInjectionAssessment(ContractModel):
    suspected: bool
    risk: InjectionRisk
    signals: tuple[InjectionSignal, ...]


_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_previous",
        re.compile(r"\bignore\s+(?:all\s+)?previous\s+(?:instructions?|prompts?)\b"),
    ),
    (
        "role_override",
        re.compile(r"\b(?:system|developer)\s*(?:message|prompt|instructions?)\s*:"),
    ),
    (
        "secret_exfiltration",
        re.compile(r"\b(?:reveal|print|return|exfiltrate)\b.{0,80}\b(?:secret|token|api key)\b"),
    ),
    (
        "tool_execution",
        re.compile(r"\b(?:call|invoke|execute|run)\b.{0,60}\b(?:tool|shell|command|curl|wget)\b"),
    ),
    (
        "korean_ignore",
        re.compile(r"(?:이전|기존).{0,20}(?:지시|명령).{0,10}(?:무시|잊어)"),
    ),
    (
        "korean_secret",
        re.compile(r"(?:시스템\s*프롬프트|비밀|토큰|API\s*키).{0,20}(?:출력|공개|보여)"),
    ),
    (
        "markdown_hidden_instruction",
        re.compile(r"<!--.{0,200}(?:ignore|instruction|system prompt).{0,200}-->", re.DOTALL),
    ),
)


def _normalized(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return normalized.translate({ord(character): None for character in "\u200b\u200c\u200d\ufeff"})


def detect_prompt_injection(
    text: str, *, max_scan_characters: int = 1_000_000
) -> PromptInjectionAssessment:
    if len(text) > max_scan_characters:
        raise ValueError("prompt-injection scan input exceeds the bounded limit")
    normalized = _normalized(text)
    signals: list[InjectionSignal] = []
    for rule_id, pattern in _RULES:
        for match in pattern.finditer(normalized):
            start = max(0, match.start() - 32)
            end = min(len(normalized), match.end() + 32)
            signals.append(
                InjectionSignal(rule_id=rule_id, excerpt=normalized[start:end].replace("\n", " "))
            )
            break
    risk = InjectionRisk.NONE
    if signals:
        risk = InjectionRisk.HIGH if len(signals) >= 2 else InjectionRisk.LOW
    return PromptInjectionAssessment(suspected=bool(signals), risk=risk, signals=tuple(signals))
