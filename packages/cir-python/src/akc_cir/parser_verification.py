"""Risk-gated multi-parser and visual/cross-page verification decisions.

This module contains no provider SDKs and therefore creates no hard dependency
on PaddleOCR, GLM-OCR, MonkeyOCR, or any particular VLM. Runtime adapters expose
capabilities; this policy decides whether spending on an alternate parser is
justified and records the interpretable agreement vector afterwards.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import pairwise

from .critical_tokens import verify_critical_tokens
from .inspection import FailureCode

__all__ = [
    "CrossPageFinding",
    "ParserAgreement",
    "ParserCapability",
    "ParserObservation",
    "VerificationDecision",
    "VerificationGate",
    "check_cross_page_consistency",
    "compare_parser_outputs",
    "select_verification_parsers",
]


@dataclass(frozen=True, slots=True)
class ParserCapability:
    name: str
    family: str
    available: bool = True
    estimated_gpu_seconds: float = 0.0
    estimated_cost_usd: float = 0.0
    supports_visual: bool = False
    supports_tables: bool = True

    def __post_init__(self) -> None:
        if not self.name or not self.family:
            raise ValueError("parser name and family are required")
        if self.estimated_gpu_seconds < 0 or self.estimated_cost_usd < 0:
            raise ValueError("parser cost estimates cannot be negative")


@dataclass(frozen=True, slots=True)
class VerificationGate:
    risk_threshold: float = 0.55
    uncertainty_threshold: float = 0.35
    cross_page_risk_threshold: float = 0.55
    max_alternate_parsers: int = 2
    max_gpu_seconds: float = 180.0
    max_cost_usd: float = 1.0

    def __post_init__(self) -> None:
        for value in (
            self.risk_threshold,
            self.uncertainty_threshold,
            self.cross_page_risk_threshold,
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError("verification thresholds must be within 0..1")
        if self.max_alternate_parsers < 0:
            raise ValueError("max_alternate_parsers cannot be negative")


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    selected: tuple[ParserCapability, ...]
    reason: str
    run_visual_round_trip: bool
    run_cross_page_check: bool
    estimated_gpu_seconds: float
    estimated_cost_usd: float

    @property
    def multi_parser(self) -> bool:
        return len(self.selected) > 1


_FORCE_VERIFY_CODES = frozenset(
    {
        FailureCode.F13_TABLE_STRUCTURE,
        FailureCode.F14_FORMULA,
        FailureCode.F15_FIGURE_CAPTION,
        FailureCode.F16_CROSS_PAGE,
        FailureCode.F17_NATIVE_RENDER_DISAGREEMENT,
        FailureCode.F18_PARSER_DISAGREEMENT,
    }
)


def select_verification_parsers(
    primary: ParserCapability,
    alternatives: Iterable[ParserCapability],
    *,
    risk: float,
    uncertainty: float,
    failure_codes: Iterable[FailureCode] = (),
    has_table: bool = False,
    has_image: bool = False,
    cross_page_risk: float = 0.0,
    gate: VerificationGate | None = None,
) -> VerificationDecision:
    """Select only the capabilities justified by current risk and budget."""
    if not 0.0 <= risk <= 1.0 or not 0.0 <= uncertainty <= 1.0:
        raise ValueError("risk and uncertainty must be within 0..1")
    if not 0.0 <= cross_page_risk <= 1.0:
        raise ValueError("cross_page_risk must be within 0..1")
    limits = gate or VerificationGate()
    codes = frozenset(failure_codes)
    force = bool(codes & _FORCE_VERIFY_CODES)
    needs_alt = (
        force
        or risk >= limits.risk_threshold
        or uncertainty >= limits.uncertainty_threshold
    )
    visual = (has_table or has_image) and (
        force or risk >= limits.risk_threshold or uncertainty >= limits.uncertainty_threshold
    )
    cross_page = cross_page_risk >= limits.cross_page_risk_threshold or (
        FailureCode.F16_CROSS_PAGE in codes
    )

    selected: list[ParserCapability] = [primary]
    gpu = primary.estimated_gpu_seconds
    cost = primary.estimated_cost_usd
    if not primary.available:
        selected.clear()
        gpu = cost = 0.0

    if needs_alt:
        candidates = sorted(
            (item for item in alternatives if item.available and item.name != primary.name),
            key=lambda item: (
                item.family == primary.family,
                item.estimated_cost_usd,
                item.estimated_gpu_seconds,
                item.name,
            ),
        )
        for candidate in candidates:
            if len(selected) >= 1 + limits.max_alternate_parsers:
                break
            if gpu + candidate.estimated_gpu_seconds > limits.max_gpu_seconds:
                continue
            if cost + candidate.estimated_cost_usd > limits.max_cost_usd:
                continue
            selected.append(candidate)
            gpu += candidate.estimated_gpu_seconds
            cost += candidate.estimated_cost_usd

    if not selected:
        reason = "primary unavailable and no affordable available alternative"
    elif len(selected) == 1 and needs_alt:
        reason = "verification warranted but no alternate capability fits availability/budget"
    elif len(selected) > 1:
        reason = "risk/uncertainty warrants selective independent parser verification"
    else:
        reason = "primary result is below multi-parser verification thresholds"

    return VerificationDecision(
        selected=tuple(selected),
        reason=reason,
        run_visual_round_trip=visual and any(item.supports_visual for item in selected),
        run_cross_page_check=cross_page,
        estimated_gpu_seconds=gpu,
        estimated_cost_usd=cost,
    )


@dataclass(frozen=True, slots=True)
class ParserObservation:
    parser_name: str
    text: str


@dataclass(frozen=True, slots=True)
class ParserAgreement:
    compared: int
    normalized_text_similarity_min: float
    critical_token_agreement: bool
    critical_token_mismatch_count: int
    unresolved: bool


def compare_parser_outputs(observations: Sequence[ParserObservation]) -> ParserAgreement:
    if len(observations) < 2:
        return ParserAgreement(0, 1.0, True, 0, False)
    baseline = observations[0].text
    similarities: list[float] = []
    mismatch_count = 0
    for observation in observations[1:]:
        similarities.append(
            SequenceMatcher(None, baseline.casefold(), observation.text.casefold()).ratio()
        )
        report = verify_critical_tokens(baseline, observation.text)
        mismatch_count += len(report.mismatches)
    min_similarity = min(similarities, default=1.0)
    critical_ok = mismatch_count == 0
    # Critical facts disagreeing is unresolved regardless of fluent text. Very
    # low text agreement also requires arbitration, but the two facts remain
    # separate in the returned vector instead of becoming one opaque score.
    unresolved = not critical_ok or min_similarity < 0.65
    return ParserAgreement(
        compared=len(observations) - 1,
        normalized_text_similarity_min=min_similarity,
        critical_token_agreement=critical_ok,
        critical_token_mismatch_count=mismatch_count,
        unresolved=unresolved,
    )


@dataclass(frozen=True, slots=True)
class CrossPageFinding:
    left_page: int
    right_page: int
    kind: str
    detail: str


def check_cross_page_consistency(page_texts: Sequence[str]) -> tuple[CrossPageFinding, ...]:
    """Cheap textual pre-gate for obvious duplicate/leakage across page bounds."""
    findings: list[CrossPageFinding] = []
    normalized = [" ".join(text.split()).casefold() for text in page_texts]
    for index, (left, right) in enumerate(pairwise(normalized), start=1):
        if left and right and left == right:
            findings.append(
                CrossPageFinding(index, index + 1, "duplicate_page", "adjacent pages are identical")
            )
            continue
        left_tail = left[-160:]
        right_head = right[:160]
        if len(left_tail) >= 80 and left_tail == right_head:
            findings.append(
                CrossPageFinding(
                    index,
                    index + 1,
                    "boundary_leakage",
                    "long page-tail text is duplicated at the next page head",
                )
            )
    return tuple(findings)