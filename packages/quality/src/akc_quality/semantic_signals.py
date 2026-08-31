"""Ground-truth-independent signals for semantic-risk routing.

This module lives above the canonical semantic-risk engine.  It converts
observable parser/peer evidence into the engine's explicit feature vector
without consulting benchmark labels or a scalar quality oracle.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from akc_cir.semantic_risk import SemanticRiskAssessment, SemanticRiskFeatures, assess_semantic_risk

from .agreement import compare_engine_outputs
from .models import AgreementScore

__all__ = [
    "PeerSemanticRiskSignals",
    "derive_peer_semantic_risk",
]

_DATE_RE = re.compile(
    r"(?:\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b|"
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b)",
    re.IGNORECASE,
)
_VERSION_RE = re.compile(r"\b[vV]?\d+(?:\.\d+){2,}\b")
_QUANTITY_RE = re.compile(
    r"(?<!\w)(?:[$€£¥₩]\s*)?[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:\s*%|\s*(?:ms|s|kg|g|mm|cm|m|km|gb|mb|kb))?(?!\w)",
    re.IGNORECASE,
)
_TABLE_RE = re.compile(r"<table\b|^\s*\|.*\|\s*$", re.IGNORECASE | re.MULTILINE)
_FORMULA_RE = re.compile(
    r"\$\$.*?\$\$|\\\[.*?\\\]|\\begin\{equation\*?\}.*?\\end\{equation\*?\}|(?<!\$)\$[^$\n]+\$(?!\$)",
    re.DOTALL,
)


def _clip(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _has_critical_token(text: str) -> bool:
    return bool(_DATE_RE.search(text) or _VERSION_RE.search(text) or _QUANTITY_RE.search(text))


def _critical_tokens(text: str) -> frozenset[str]:
    tokens: set[str] = set()
    for pattern in (_DATE_RE, _VERSION_RE, _QUANTITY_RE):
        for match in pattern.finditer(text):
            value = "".join(match.group(0).casefold().split())
            if value:
                tokens.add(value)
    return frozenset(tokens)


@dataclass(frozen=True, slots=True)
class PeerSemanticRiskSignals:
    """Receipt-ready signal decomposition used to build SemanticRiskFeatures."""

    peer_available: bool
    agreement: AgreementScore | None
    text_disagreement: float
    numeric_disagreement: float
    heading_disagreement: float
    table_disagreement: float | None
    critical_token_disagreement: float
    cross_model_disagreement: float
    critical_token_present: bool
    date_present: bool
    table_detected: bool
    formula_detected: bool
    features: SemanticRiskFeatures
    assessment: SemanticRiskAssessment

    def as_dict(self) -> dict[str, object]:
        agreement = None if self.agreement is None else self.agreement.model_dump(mode="json")
        return {
            "peer_available": self.peer_available,
            "agreement": agreement,
            "text_disagreement": self.text_disagreement,
            "numeric_disagreement": self.numeric_disagreement,
            "heading_disagreement": self.heading_disagreement,
            "table_disagreement": self.table_disagreement,
            "critical_token_disagreement": self.critical_token_disagreement,
            "cross_model_disagreement": self.cross_model_disagreement,
            "critical_token_present": self.critical_token_present,
            "date_present": self.date_present,
            "table_detected": self.table_detected,
            "formula_detected": self.formula_detected,
            "features": self.features.as_dict(),
            "assessment": self.assessment.as_dict(),
        }


def derive_peer_semantic_risk(
    primary_text: str,
    peer_text: str | None,
    *,
    primary_error_probability: float = 0.0,
    parsing_uncertainty: float = 0.0,
    table_shape_match: float | None = None,
    semantic_role_criticality: float | None = None,
    entity_criticality: float = 0.0,
    authority_significance: float = 0.0,
    dependency_blast_radius: float = 0.0,
    downstream_consumer_risk: float = 0.35,
) -> PeerSemanticRiskSignals:
    """Derive an explainable semantic-risk vector from independent parser evidence.

    The peer is optional.  Missing peer evidence never becomes synthetic
    disagreement; callers must provide a separate uncertainty/error signal when
    the primary parser itself reports one.  Disagreement is conservative: a
    severe numeric/heading/table mismatch is not averaged away by otherwise
    similar body text.

    ``downstream_consumer_risk`` defaults to 0.35 for knowledge-compilation
    ingestion because parser output is destined for downstream claims/retrieval;
    callers may override it with a measured compiler-specific consequence.
    """

    primary = primary_text or ""
    peer_available = peer_text is not None and bool(peer_text.strip())
    agreement: AgreementScore | None = None
    text_disagreement = 0.0
    numeric_disagreement = 0.0
    heading_disagreement = 0.0
    table_disagreement: float | None = None
    critical_token_disagreement = 0.0
    cross_disagreement = 0.0

    if peer_available:
        agreement = compare_engine_outputs(
            primary,
            peer_text or "",
            table_shape_match=table_shape_match,
        )
        text_disagreement = 1.0 - float(agreement.normalized_edit_similarity)
        numeric_disagreement = 1.0 - float(agreement.numeric_token_match)
        heading_disagreement = 1.0 - float(agreement.heading_match)
        if agreement.table_shape_match is not None:
            table_disagreement = 1.0 - float(agreement.table_shape_match)
        warning_axes = [text_disagreement, numeric_disagreement, heading_disagreement]
        if table_disagreement is not None:
            warning_axes.append(table_disagreement)
        primary_critical = _critical_tokens(primary)
        peer_critical = _critical_tokens(peer_text or "")
        critical_union = primary_critical | peer_critical
        if critical_union:
            critical_token_disagreement = 1.0 - (
                len(primary_critical & peer_critical) / len(critical_union)
            )
            warning_axes.append(critical_token_disagreement)
        cross_disagreement = max(warning_axes)

    joined = primary if not peer_available else f"{primary}\n{peer_text or ''}"
    critical_token_present = _has_critical_token(joined)
    date_present = bool(_DATE_RE.search(joined))
    table_detected = bool(_TABLE_RE.search(joined))
    formula_detected = bool(_FORMULA_RE.search(joined))

    if semantic_role_criticality is None:
        role_axes = [0.35]
        if table_detected:
            role_axes.append(0.85)
        if formula_detected:
            role_axes.append(0.70)
        semantic_role_criticality = max(role_axes)

    features = SemanticRiskFeatures(
        parser_error_probability=_clip(primary_error_probability),
        parsing_uncertainty=_clip(parsing_uncertainty),
        cross_model_disagreement=_clip(cross_disagreement),
        critical_token_sensitivity=0.85 if critical_token_present else 0.10,
        semantic_role_criticality=_clip(semantic_role_criticality),
        entity_criticality=_clip(entity_criticality),
        temporal_significance=0.75 if date_present else 0.0,
        authority_significance=_clip(authority_significance),
        dependency_blast_radius=_clip(dependency_blast_radius),
        downstream_consumer_risk=_clip(downstream_consumer_risk),
    )
    assessment = assess_semantic_risk(features)
    return PeerSemanticRiskSignals(
        peer_available=peer_available,
        agreement=agreement,
        text_disagreement=text_disagreement,
        numeric_disagreement=numeric_disagreement,
        heading_disagreement=heading_disagreement,
        table_disagreement=table_disagreement,
        critical_token_disagreement=critical_token_disagreement,
        cross_model_disagreement=cross_disagreement,
        critical_token_present=critical_token_present,
        date_present=date_present,
        table_detected=table_detected,
        formula_detected=formula_detected,
        features=features,
        assessment=assessment,
    )
