"""RiskVector contract (blueprint 2026-09-08 §16).

Routing never reduces a document to one scalar difficulty score, and an
unobserved signal is never presented as a confident observation (§11).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from akc_cir import ContractModel
from pydantic import Field, model_validator


class RiskFeature(StrEnum):
    """The §16 signal names. New signals are added here, never ad hoc."""

    SOURCE_INTEGRITY_RISK = "source_integrity_risk"
    NATIVE_QUALITY = "native_quality"
    SCAN_NEED = "scan_need"
    TEXT_LOSS_RISK = "text_loss_risk"
    NUMERIC_RISK = "numeric_risk"
    SIGN_UNIT_CURRENCY_RISK = "sign_unit_currency_risk"
    TABLE_STRUCTURE_RISK = "table_structure_risk"
    FORMULA_RISK = "formula_risk"
    CHART_VISUAL_RISK = "chart_visual_risk"
    READING_ORDER_RISK = "reading_order_risk"
    IMAGE_SEMANTICS_RISK = "image_semantics_risk"
    HANDWRITING_RISK = "handwriting_risk"
    DEGRADATION_RISK = "degradation_risk"
    SMALL_TEXT_RISK = "small_text_risk"
    ROTATION_SKEW_RISK = "rotation_skew_risk"
    CROSS_PAGE_DEPENDENCY_RISK = "cross_page_dependency_risk"
    FOOTNOTE_COMMENT_RISK = "footnote_comment_risk"
    TRACKED_CHANGE_RISK = "tracked_change_risk"
    AUTHORITY_CONFLICT_RISK = "authority_conflict_risk"
    PROVENANCE_RISK = "provenance_risk"
    PROMPT_INJECTION_RISK = "prompt_injection_risk"
    SENSITIVE_DATA_RISK = "sensitive_data_risk"


class ObservationSource(StrEnum):
    """Where a signal value came from (§17 lanes)."""

    NATIVE_INSPECT = "native_inspect"
    VISUAL_SCAN = "visual_scan"
    AUTHORITY_SOURCE = "authority_source"
    DERIVED = "derived"
    UNAVAILABLE = "unavailable"


class RiskSignal(ContractModel):
    """One §16 signal: value, calibration/confidence, observation source, unknown flag.

    An unknown signal carries no value and no confidence. `effective_confidence`
    is the only supported way to read confidence, and it returns 0.0 for an
    unknown signal so a missing estimator can never be read as certainty.
    """

    value: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    observation_source: ObservationSource
    unknown: bool = False
    calibrated: bool = False

    @model_validator(mode="after")
    def enforce_unknown_carries_no_certainty(self) -> RiskSignal:
        if self.unknown:
            if self.value is not None or self.confidence is not None:
                raise ValueError("an unknown signal carries neither value nor confidence")
            if self.observation_source is not ObservationSource.UNAVAILABLE:
                raise ValueError("an unknown signal must record source 'unavailable'")
            if self.calibrated:
                raise ValueError("an unknown signal is not calibrated")
            return self
        if self.value is None:
            raise ValueError("an observed signal requires a value")
        if self.observation_source is ObservationSource.UNAVAILABLE:
            raise ValueError("an observed signal requires a real observation source")
        if self.calibrated and self.confidence is None:
            raise ValueError("a calibrated signal requires a confidence")
        return self

    @property
    def effective_confidence(self) -> float:
        """Confidence usable by a policy. Unknown or unstated reads as 0.0."""
        if self.unknown or self.confidence is None:
            return 0.0
        return self.confidence


class RiskVector(ContractModel):
    """Per-page or per-region §16 risk description."""

    signals: dict[RiskFeature, RiskSignal] = Field(default_factory=dict)
    unknown_features: tuple[RiskFeature, ...] = ()
    language_script: tuple[str, ...] = ()
    authority_available: bool = False

    @model_validator(mode="after")
    def enforce_unknown_features_match_signals(self) -> RiskVector:
        declared = set(self.unknown_features)
        if len(declared) != len(self.unknown_features):
            raise ValueError("unknown_features must not repeat a signal")
        observed_unknown = {name for name, signal in self.signals.items() if signal.unknown}
        if not observed_unknown <= declared:
            raise ValueError("every unknown signal must be listed in unknown_features")
        confident = {name for name, signal in self.signals.items() if not signal.unknown}
        if declared & confident:
            raise ValueError("a signal cannot be both unknown and observed")
        return self

    def confidence(self, feature: RiskFeature) -> float:
        """Confidence for a feature. Absent, unstated or unknown all read as 0.0."""
        signal = self.signals.get(feature)
        return signal.effective_confidence if signal is not None else 0.0

    def is_unknown(self, feature: RiskFeature) -> bool:
        signal = self.signals.get(feature)
        return signal is None or signal.unknown


__all__ = ["ObservationSource", "RiskFeature", "RiskSignal", "RiskVector"]
