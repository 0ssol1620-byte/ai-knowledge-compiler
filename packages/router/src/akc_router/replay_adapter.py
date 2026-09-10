"""Adapter that lets the offline replay (WP-R10) drive this planner.

Lane A2's harness defines a `Policy` protocol -- `plan(unit_features) ->
UnitPlan` -- and looks for `akc_router.planner.build_replay_policy`. This module
is that entry point, and it is deliberately thin.

Two boundaries it does not cross:

* **It never imports the replay harness at module scope.** The harness lives in
  a research tree that is not a dependency of this package; the `UnitPlan` type
  is resolved lazily at call time and falls back to a structurally identical
  local record, so importing `akc_router` never requires the research tree.
* **It reads only runtime-visible features.** Everything it touches comes from
  the harness's own runtime half. It cannot reach a score file or a ground
  truth, because it is handed features, not paths.

The lane-to-model mapping is the caller's, not this module's: a replay arm
decides which stored model plays "fast visual" and which plays "peer visual",
and nothing here infers a capability from a model name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .planner import UnitFeatures, classify_speculation
from .preflight import PageTechnicalClass
from .risk import ObservationSource, RiskFeature, RiskSignal, RiskVector
from .speculation import speculate

_F = RiskFeature


@dataclass(frozen=True, slots=True)
class _LocalUnitPlan:
    """Stand-in with the harness's field names, used when it is not importable."""

    routes: tuple[str, ...]
    accepted: str | None
    speculative: tuple[str, ...] = ()
    escalate: bool = False
    unresolved_reason: str | None = None
    reason_codes: tuple[str, ...] = ()


def _unit_plan_type() -> Any:
    try:  # pragma: no cover - exercised only with the research tree present
        from research.router_replay_20260908.features import UnitPlan
    except Exception:
        return _LocalUnitPlan
    return UnitPlan


@dataclass(frozen=True)
class RouterV2ReplayPolicy:
    """Router v2's §21 classification, expressed in the replay's model space."""

    primary_model: str
    strong_model: str
    name: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            object.__setattr__(
                self,
                "name",
                f"ROUTER_V2_PAGE@primary={self.primary_model},peer={self.strong_model}",
            )

    def plan(self, unit_features: Any) -> Any:
        plan_type = _unit_plan_type()
        risk = replay_risk_vector(unit_features)
        unit = UnitFeatures(
            unit_id=str(getattr(unit_features, "case_key", "unit")),
            page_index0=max(0, int(getattr(unit_features, "page_index", 0))),
            technical_class=_technical_class(unit_features),
            risk_vector=risk,
        )
        speculation_class = classify_speculation(unit)
        policy = speculate(speculation_class)
        reasons = [f"speculation_class:{speculation_class.value}"]

        outputs = dict(getattr(unit_features, "outputs", {}) or {})
        peers = tuple(
            model
            for model in (self.strong_model,)
            if policy.peer_lanes and model != self.primary_model and model in outputs
        )
        routes = (self.primary_model, *peers)
        accepted = _first_present(outputs, routes)
        if accepted is None:
            return plan_type(
                routes=routes,
                accepted=None,
                speculative=peers,
                escalate=bool(peers),
                unresolved_reason="no invoked model produced an output for this unit",
                reason_codes=tuple(reasons),
            )
        return plan_type(
            routes=routes,
            accepted=accepted,
            speculative=peers,
            escalate=bool(peers),
            reason_codes=tuple(reasons),
        )


def build_replay_policy(
    strong: str, primary: str = "", name: str = ""
) -> RouterV2ReplayPolicy:
    """Entry point the replay harness looks for."""
    return RouterV2ReplayPolicy(
        primary_model=primary or strong,
        strong_model=strong,
        name=name,
    )


def replay_risk_vector(unit_features: Any) -> RiskVector:
    """Map the harness's runtime-visible features onto §16 signals.

    Anything the harness did not measure -- and it lists those itself in
    `unknown_fields` -- comes out unknown, not zero.
    """
    unknown_fields = set(getattr(unit_features, "unknown_fields", ()) or ())
    native_chars = int(getattr(unit_features, "native_text_chars", 0) or 0)
    native_available = bool(getattr(unit_features, "native_text_available", False))
    invalid = float(getattr(unit_features, "native_invalid_unicode_ratio", 0.0) or 0.0)
    replacement = float(getattr(unit_features, "native_replacement_ratio", 0.0) or 0.0)
    edge = getattr(unit_features, "render_edge_density", None)
    near_white = getattr(unit_features, "render_near_white_ratio", None)
    critical = float(getattr(unit_features, "critical_token_risk", 0.0) or 0.0)
    kinds = set(getattr(unit_features, "critical_token_kinds", ()) or ())

    signals: dict[RiskFeature, RiskSignal] = {}

    def observe(feature: RiskFeature, value: float, source: ObservationSource) -> None:
        signals[feature] = RiskSignal(
            value=min(1.0, max(0.0, value)), observation_source=source, calibrated=False
        )

    def unknown(feature: RiskFeature) -> None:
        signals[feature] = RiskSignal(
            unknown=True, observation_source=ObservationSource.UNAVAILABLE
        )

    observe(
        _F.SOURCE_INTEGRITY_RISK,
        min(1.0, invalid * 20 + replacement * 200),
        ObservationSource.NATIVE_INSPECT,
    )
    observe(
        _F.NATIVE_QUALITY,
        1.0 if native_available and native_chars >= 100 else 0.0,
        ObservationSource.NATIVE_INSPECT,
    )
    observe(
        _F.SCAN_NEED,
        0.0 if native_available and native_chars >= 30 else 1.0,
        ObservationSource.NATIVE_INSPECT,
    )
    observe(_F.TEXT_LOSS_RISK, critical, ObservationSource.DERIVED)
    observe(
        _F.NUMERIC_RISK,
        critical if kinds & {"number", "sign", "decimal", "percent"} else 0.0,
        ObservationSource.DERIVED,
    )
    observe(
        _F.SIGN_UNIT_CURRENCY_RISK,
        critical if kinds & {"sign", "unit", "currency"} else 0.0,
        ObservationSource.DERIVED,
    )
    observe(
        _F.TABLE_STRUCTURE_RISK,
        critical if "table_cell" in kinds else 0.0,
        ObservationSource.DERIVED,
    )
    if near_white is None:
        unknown(_F.IMAGE_SEMANTICS_RISK)
    else:
        observe(
            _F.IMAGE_SEMANTICS_RISK,
            1.0 - float(near_white),
            ObservationSource.VISUAL_SCAN,
        )
    if edge is None:
        unknown(_F.SMALL_TEXT_RISK)
    else:
        observe(_F.SMALL_TEXT_RISK, min(1.0, float(edge) * 2.0), ObservationSource.VISUAL_SCAN)

    # Everything else: the harness's runtime half does not measure it.
    for feature in RiskFeature:
        if feature not in signals:
            unknown(feature)
    for name in unknown_fields:
        declared = _FIELD_TO_FEATURE.get(name)
        if declared is not None:
            unknown(declared)

    return RiskVector(
        signals=signals,
        unknown_features=tuple(feature for feature in RiskFeature if signals[feature].unknown),
    )


#: Harness field name -> the §16 signal it would have supplied.
_FIELD_TO_FEATURE: dict[str, RiskFeature] = {
    "render_edge_density": _F.SMALL_TEXT_RISK,
    "render_near_white_ratio": _F.IMAGE_SEMANTICS_RISK,
    "render_entropy": _F.DEGRADATION_RISK,
    "native_text_chars": _F.NATIVE_QUALITY,
}


def _technical_class(unit_features: Any) -> PageTechnicalClass:
    """Only what the harness can actually see. Otherwise UNKNOWN, not a guess."""
    if getattr(unit_features, "render_probably_blank", None) is True:
        return PageTechnicalClass.UNKNOWN
    native_chars = int(getattr(unit_features, "native_text_chars", 0) or 0)
    if getattr(unit_features, "native_text_available", False) and native_chars >= 100:
        return PageTechnicalClass.NATIVE_CLEAN
    if native_chars < 30:
        return PageTechnicalClass.SCAN_TEXT
    return PageTechnicalClass.MIXED


def _first_present(outputs: dict[str, Any], models: tuple[str, ...]) -> str | None:
    for model in models:
        found = outputs.get(model)
        if found is not None and getattr(found, "present", True):
            return model
    return None


__all__ = ["RouterV2ReplayPolicy", "build_replay_policy", "replay_risk_vector"]
