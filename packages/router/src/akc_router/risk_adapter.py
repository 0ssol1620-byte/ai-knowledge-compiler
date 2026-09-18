"""`PageMetrics` -> `RiskVector` (program §4 / blueprint §16).

The whole point of this module is the *absence* of values. `PageMetrics` carries
observations for twelve of the twenty-two §4 signals; the other ten have no
estimator on this lane, and each of them is emitted as an explicitly unknown
`RiskSignal` rather than as a confident 0.0. C-09 is what the alternative costs.

Nothing here is calibrated. No signal states a confidence, so
`RiskVector.confidence()` returns 0.0 for every feature and a policy that wants
certainty has to go and measure it. `CalibrationTable.calibrated` is `False`
across this repository and this module does not pretend otherwise.
"""

from __future__ import annotations

from .preflight import PageMetrics
from .risk import ObservationSource, RiskFeature, RiskSignal, RiskVector

_F = RiskFeature
_S = ObservationSource

#: §4 signals no lane-A/lane-B page estimator can observe. Cross-page, document
#: history and authority facts are not page-local; sensitive-data and numeric
#: risk need the text, which `PageMetrics` deliberately does not carry.
PAGE_LOCAL_BLIND_SPOTS: frozenset[RiskFeature] = frozenset(
    {
        _F.NUMERIC_RISK,
        _F.SIGN_UNIT_CURRENCY_RISK,
        _F.CROSS_PAGE_DEPENDENCY_RISK,
        _F.FOOTNOTE_COMMENT_RISK,
        _F.TRACKED_CHANGE_RISK,
        _F.AUTHORITY_CONFLICT_RISK,
        _F.PROVENANCE_RISK,
        _F.SENSITIVE_DATA_RISK,
    }
)


def _observed(value: float, source: ObservationSource) -> RiskSignal:
    return RiskSignal(
        value=min(1.0, max(0.0, value)),
        confidence=None,
        observation_source=source,
        calibrated=False,
    )


def _unknown() -> RiskSignal:
    return RiskSignal(unknown=True, observation_source=_S.UNAVAILABLE)


def _optional(value: float | None, source: ObservationSource) -> RiskSignal:
    return _unknown() if value is None else _observed(value, source)


def page_metrics_to_risk_vector(
    metrics: PageMetrics,
    *,
    authority_available: bool = False,
    known: dict[RiskFeature, RiskSignal] | None = None,
) -> RiskVector:
    """Map the measured `PageMetrics` fields onto their §4 `RiskFeature`s.

    `known` lets a caller that *has* measured a blind-spot signal supply it --
    a document-level dependency scan, an authority lane, a sensitive-data
    detector. Anything it does not supply stays unknown.
    """
    supplied = known or {}
    native_quality = min(
        metrics.native_reading_order_score,
        1.0 if metrics.native_text_chars >= 100 else metrics.native_text_chars / 100,
    )
    corruption = min(
        1.0,
        metrics.invalid_unicode_ratio * 20 + metrics.replacement_char_ratio * 200,
    )
    signals: dict[RiskFeature, RiskSignal] = {
        _F.SOURCE_INTEGRITY_RISK: _observed(corruption, _S.NATIVE_INSPECT),
        _F.NATIVE_QUALITY: _observed(native_quality, _S.NATIVE_INSPECT),
        # A page with no extractable text needs a raster pass; one with text and
        # a large image area may still need one.
        _F.SCAN_NEED: _observed(
            1.0 if metrics.native_text_chars < 30 else metrics.image_coverage,
            _S.NATIVE_INSPECT,
        ),
        _F.TEXT_LOSS_RISK: _observed(
            max(corruption, metrics.whitespace_anomaly_score, 1.0 - native_quality),
            _S.DERIVED,
        ),
        _F.TABLE_STRUCTURE_RISK: _observed(metrics.table_density, _S.NATIVE_INSPECT),
        _F.FORMULA_RISK: _observed(min(1.0, metrics.formula_density * 4), _S.NATIVE_INSPECT),
        _F.CHART_VISUAL_RISK: _observed(metrics.chart_probability, _S.NATIVE_INSPECT),
        _F.READING_ORDER_RISK: _observed(
            max(
                1.0 - metrics.native_reading_order_score,
                0.5 if metrics.estimated_columns >= 2 else 0.0,
            ),
            _S.DERIVED,
        ),
        _F.IMAGE_SEMANTICS_RISK: _observed(metrics.image_coverage, _S.NATIVE_INSPECT),
        _F.PROMPT_INJECTION_RISK: _observed(
            1.0 if metrics.suspected_prompt_injection else 0.0,
            _S.NATIVE_INSPECT,
        ),
        # The six C-09 fields. Unmeasured stays unmeasured.
        _F.HANDWRITING_RISK: _optional(metrics.handwriting_probability, _S.VISUAL_SCAN),
        _F.SMALL_TEXT_RISK: _optional(metrics.small_text_score, _S.VISUAL_SCAN),
        _F.DEGRADATION_RISK: _degradation(metrics),
        _F.ROTATION_SKEW_RISK: _rotation_skew(metrics),
    }
    for feature in PAGE_LOCAL_BLIND_SPOTS:
        signals[feature] = _unknown()
    signals.update(supplied)
    return RiskVector(
        signals=signals,
        unknown_features=tuple(feature for feature in RiskFeature if signals[feature].unknown),
        language_script=tuple(sorted(metrics.script_distribution)),
        authority_available=authority_available,
    )


def _degradation(metrics: PageMetrics) -> RiskSignal:
    """Blur and low contrast both degrade a raster; either alone is enough."""
    parts = [
        value
        for value in (
            metrics.blur_score,
            None if metrics.contrast_score is None else 1.0 - metrics.contrast_score,
        )
        if value is not None
    ]
    return _observed(max(parts), _S.VISUAL_SCAN) if parts else _unknown()


def _rotation_skew(metrics: PageMetrics) -> RiskSignal:
    rotation = metrics.rotation_degrees
    skew = metrics.skew_degrees
    parts = [
        value
        for value in (
            None if rotation is None else (1.0 if rotation else 0.0),
            None if skew is None else min(1.0, abs(skew) / 8.0),
        )
        if value is not None
    ]
    return _observed(max(parts), _S.VISUAL_SCAN) if parts else _unknown()


__all__ = ["PAGE_LOCAL_BLIND_SPOTS", "page_metrics_to_risk_vector"]
