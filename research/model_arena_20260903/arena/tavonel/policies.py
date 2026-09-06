"""TAVONEL system variants A-E as pure, versioned routing policies (MP section 25).

A policy is a function from GT-free signals to a route decision. It never
opens a file, never sees an answer key (variant E is the exception and lives in
``oracle.py``), and is identified by a ``policy_id`` plus a ``policy_sha256``
over its parameters *and its own source*, so a decision recorded today can be
matched to the exact code that made it.

Every number a policy compares against is a named :class:`Threshold` carrying
``calibrated: False``. None of these values has been measured against a corpus.
They are starting points chosen to be legible, and the campaign's whole point
is to find out which of them are wrong — presenting one as a measured operating
point would be the failure this repository names ``IMPLEMENTED_NOT_PROVEN``.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final

from arena.tavonel import variants
from arena.tavonel.errors import PolicyError
from arena.tavonel.jsonio import canonical_json, prefixed, sha256_hex

# ---------------------------------------------------------------- parameters

DECISION_ACCEPT: Final = "ACCEPT_PRIMARY"
DECISION_ACCEPT_WITH_RECOVERY: Final = "ACCEPT_PRIMARY_WITH_RECOVERY"
DECISION_ROUTE_SPECIALIST: Final = "ROUTE_SPECIALIST"
DECISION_ESCALATE_OPUS: Final = "ESCALATE_OPUS"
DECISION_ORACLE_SELECT: Final = "ORACLE_SELECT"
DECISIONS: Final = (
    DECISION_ACCEPT,
    DECISION_ACCEPT_WITH_RECOVERY,
    DECISION_ROUTE_SPECIALIST,
    DECISION_ESCALATE_OPUS,
    DECISION_ORACLE_SELECT,
)

RECOVERY_TYPES: Final = (
    "overlap_tiling",
    "crop",
    "region_extract",
    "higher_dpi",
    "alternative_prompt",
    "safer_config",
    "partial_page",
)

_OOM_OR_TIMEOUT_CLASSES: Final = frozenset(
    {"CUDA_OOM", "INFERENCE_TIMEOUT", "INFERENCE_STALL", "GPU_KERNEL", "TENSOR_SHAPE"}
)


@dataclass(frozen=True, slots=True)
class Threshold:
    """One named, uncalibrated policy parameter."""

    name: str
    value: float
    rationale: str
    calibrated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "calibrated": self.calibrated,
            "name": self.name,
            "rationale": self.rationale,
            "value": self.value,
        }


DEFAULT_THRESHOLDS: Final = (
    Threshold(
        "min_output_chars",
        40.0,
        "below this a page produced effectively no text, whatever the receipt says",
    ),
    Threshold(
        "min_chars_per_megapixel",
        120.0,
        "output length per rendered megapixel; a low yield on an inked page is a miss",
    ),
    Threshold(
        "ngram_repetition_ratio_max",
        0.35,
        "share of repeated 5-grams above which the decode loop is degenerate",
    ),
    Threshold(
        "duplicate_paragraph_ratio_max",
        0.30,
        "share of duplicated paragraphs above which the page is looping",
    ),
    Threshold(
        "broken_text_ratio_max",
        0.02,
        "replacement and control characters per non-space character",
    ),
    Threshold(
        "table_min_rows",
        3.0,
        "a table block with fewer rows than this looks collapsed rather than parsed",
    ),
    Threshold(
        "formula_trigger_min_count",
        3.0,
        "formula spans on the page before a formula specialist is worth a second call",
    ),
    Threshold(
        "peer_similarity_min",
        0.60,
        "normalized similarity with the cheap peer below which the two disagree",
    ),
    Threshold(
        "blank_page_near_white_ratio",
        0.995,
        "preflight near-white ratio above which an empty output is a valid blank page",
    ),
    Threshold(
        "tiny_text_edge_density_min",
        0.05,
        "preflight edge density that says there is ink even though little text came out",
    ),
    Threshold(
        "escalation_fraction_cap",
        0.05,
        "hard cap on the share of pages variant D may send to the escalation model",
    ),
    Threshold(
        "escalation_min_risk",
        0.50,
        "risk score below which a page is never escalated, even inside the cap",
    ),
    Threshold("risk_weight_operational_failure", 1.0, "receipt status is not SUCCESS"),
    Threshold("risk_weight_empty_output", 1.0, "no text on a page that is not blank"),
    Threshold("risk_weight_truncated", 0.6, "structural evidence the output was cut off"),
    Threshold("risk_weight_repetition", 0.8, "scaled by the 5-gram repetition ratio"),
    Threshold("risk_weight_duplicate_paragraph", 0.4, "scaled by the duplicate paragraph ratio"),
    Threshold("risk_weight_broken_text", 0.5, "scaled by the broken-character ratio"),
    Threshold("risk_weight_boilerplate", 0.7, "the model talked about the page instead of it"),
    Threshold("risk_weight_table_broken", 0.5, "a table was present and its structure broke"),
    Threshold("risk_weight_low_yield", 0.4, "few characters per megapixel of inked page"),
    Threshold("risk_weight_disagreement", 0.6, "scaled by 1 - similarity with the cheap peer"),
)


@dataclass(frozen=True, slots=True)
class ModelSlots:
    """Which model fills each role. Defaults follow MP sections 13.1 and 25."""

    primary: str = "paddleocr_vl_1_6"
    text_specialist: str = "deepseek_ocr2"
    table_specialist: str = "mineru_vlm"
    formula_specialist: str = "infinity_parser2_pro"
    disagreement_peer: str = "mineru_pipeline"
    disagreement_target: str = "mineru_vlm"
    escalation: str = "opus5_subscription"

    def as_dict(self) -> dict[str, str]:
        return {
            "disagreement_peer": self.disagreement_peer,
            "disagreement_target": self.disagreement_target,
            "escalation": self.escalation,
            "formula_specialist": self.formula_specialist,
            "primary": self.primary,
            "table_specialist": self.table_specialist,
            "text_specialist": self.text_specialist,
        }


@dataclass(frozen=True, slots=True)
class PolicyParams:
    models: ModelSlots = field(default_factory=ModelSlots)
    thresholds: tuple[Threshold, ...] = DEFAULT_THRESHOLDS

    def with_threshold(self, name: str, value: float) -> PolicyParams:
        """Return a copy with one threshold overridden; it stays uncalibrated."""
        found = False
        updated: list[Threshold] = []
        for threshold in self.thresholds:
            if threshold.name == name:
                found = True
                updated.append(replace(threshold, value=value))
            else:
                updated.append(threshold)
        if not found:
            raise PolicyError(f"unknown threshold {name!r}")
        return replace(self, thresholds=tuple(updated))

    def as_dict(self) -> dict[str, Any]:
        return {
            "models": self.models.as_dict(),
            "thresholds": [threshold.as_dict() for threshold in sorted(
                self.thresholds, key=lambda item: item.name
            )],
        }


# ------------------------------------------------------------------ context


@dataclass(frozen=True, slots=True)
class CaseContext:
    """Everything a policy is allowed to see about one page."""

    case_key: str
    sample_id: str | None
    benchmark: str | None
    primary_signals: Mapping[str, Any]
    available_models: tuple[str, ...] = ()
    # model_key -> normalized text similarity against the primary output.
    peer_similarity: Mapping[str, float] = field(default_factory=dict)
    peer_similarity_available: bool = False
    # Populated only for the oracle variant, and only after scoring.
    official_scores: Mapping[str, float] | None = None

    def feature(self, name: str) -> Any:
        block = self.primary_signals.get("features")
        if isinstance(block, dict):
            return block.get(name)
        return None

    def derived(self, name: str) -> Any:
        block = self.primary_signals.get("derived")
        if isinstance(block, dict):
            return block.get(name)
        return None

    def geometry(self, name: str) -> Any:
        block = self.primary_signals.get("source_geometry")
        if isinstance(block, dict):
            return block.get(name)
        return None

    def run(self, name: str) -> Any:
        block = self.primary_signals.get("run")
        if isinstance(block, dict):
            return block.get(name)
        return None

    @property
    def signals_sha256(self) -> str | None:
        value = self.primary_signals.get("signals_sha256")
        return value if isinstance(value, str) else None


# ----------------------------------------------------------------- triggers


@dataclass(frozen=True, slots=True)
class Triggers:
    """Named, separately recorded trip conditions — never a blended score."""

    operational_failure: bool
    oom_or_timeout: bool
    empty_output: bool
    valid_blank_source: bool
    low_yield: bool
    tiny_text: bool
    truncated: bool
    continuation: bool
    repetition: bool
    table_present: bool
    table_structure_broken: bool
    table_only_page: bool
    formula_heavy: bool
    broken_text: bool
    boilerplate: bool
    disagreement: bool
    disagreement_available: bool
    reasons: tuple[str, ...]
    consulted: Mapping[str, Any]


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def evaluate_triggers(ctx: CaseContext, params: PolicyParams) -> Triggers:
    """Evaluate every named trigger for one page. Pure; no IO."""
    limits = {threshold.name: threshold.value for threshold in params.thresholds}
    reasons: list[str] = []

    status = ctx.run("status")
    error_class = ctx.run("error_class")
    operational_failure = status is not None and status != "SUCCESS"
    oom_or_timeout = isinstance(error_class, str) and error_class in _OOM_OR_TIMEOUT_CLASSES

    output_chars = _as_float(ctx.feature("output_chars")) or 0.0
    empty_flag = bool(ctx.feature("empty_output"))
    empty_output = empty_flag or output_chars < limits["min_output_chars"]

    near_white = _as_float(ctx.geometry("near_white_ratio"))
    valid_blank_source = (
        near_white is not None and near_white >= limits["blank_page_near_white_ratio"]
    )

    ratio = _as_float(ctx.derived("output_to_source_ratio"))
    low_yield = ratio is not None and ratio < limits["min_chars_per_megapixel"]
    edge_density = _as_float(ctx.geometry("edge_density"))
    tiny_text = (
        low_yield
        and edge_density is not None
        and edge_density >= limits["tiny_text_edge_density_min"]
    )

    truncated = bool(ctx.feature("suspicious_truncation"))
    continuation = bool(ctx.feature("continuation_suspicion"))
    repetition_ratio = _as_float(ctx.feature("ngram_repetition_ratio")) or 0.0
    duplicate_ratio = _as_float(ctx.feature("duplicate_paragraph_ratio")) or 0.0
    repetition = (
        repetition_ratio > limits["ngram_repetition_ratio_max"]
        or duplicate_ratio > limits["duplicate_paragraph_ratio_max"]
    )

    table_count = _as_float(ctx.feature("table_count")) or 0.0
    table_rows = _as_float(ctx.feature("table_row_count")) or 0.0
    markdown_ok = ctx.feature("markdown_structural_validity")
    html_table_ok = ctx.feature("html_table_validity")
    table_present = table_count > 0
    table_structure_broken = table_present and (
        markdown_ok is False or html_table_ok is False or table_rows < limits["table_min_rows"]
    )
    heading_count = _as_float(ctx.feature("heading_count")) or 0.0
    list_count = _as_float(ctx.feature("list_count")) or 0.0
    table_only_page = table_present and heading_count == 0 and list_count == 0

    formula_count = _as_float(ctx.feature("formula_count")) or 0.0
    formula_heavy = formula_count >= limits["formula_trigger_min_count"]

    broken_ratio = _as_float(ctx.feature("broken_text_ratio")) or 0.0
    broken_text = broken_ratio > limits["broken_text_ratio_max"]
    boilerplate = bool(ctx.feature("hallucinated_boilerplate"))

    peer_key = params.models.disagreement_peer
    peer_value = ctx.peer_similarity.get(peer_key)
    disagreement_available = ctx.peer_similarity_available and peer_value is not None
    disagreement = bool(
        disagreement_available
        and peer_value is not None
        and peer_value < limits["peer_similarity_min"]
    )

    for name, tripped in (
        ("operational_failure", operational_failure),
        ("oom_or_timeout", oom_or_timeout),
        ("empty_output", empty_output and not valid_blank_source),
        ("valid_blank_source", valid_blank_source),
        ("low_yield", low_yield),
        ("tiny_text", tiny_text),
        ("suspicious_truncation", truncated),
        ("continuation_suspicion", continuation),
        ("repetition", repetition),
        ("table_structure_broken", table_structure_broken),
        ("formula_heavy", formula_heavy),
        ("broken_text", broken_text),
        ("hallucinated_boilerplate", boilerplate),
        ("peer_disagreement", disagreement),
    ):
        if tripped:
            reasons.append(name)

    consulted: dict[str, Any] = {
        "broken_text_ratio": broken_ratio,
        "duplicate_paragraph_ratio": duplicate_ratio,
        "edge_density": edge_density,
        "empty_output": empty_flag,
        "error_class": error_class,
        "formula_count": formula_count,
        "hallucinated_boilerplate": boilerplate,
        "heading_count": heading_count,
        "html_table_validity": html_table_ok,
        "list_count": list_count,
        "markdown_structural_validity": markdown_ok,
        "near_white_ratio": near_white,
        "ngram_repetition_ratio": repetition_ratio,
        "output_chars": output_chars,
        "output_to_source_ratio": ratio,
        "peer_similarity": (
            {peer_key: peer_value} if disagreement_available else None
        ),
        "status": status,
        "suspicious_truncation": truncated,
        "table_count": table_count,
        "table_row_count": table_rows,
    }
    if not disagreement_available:
        consulted["peer_similarity_unavailable_reason"] = (
            f"the cheap peer {peer_key} produced no comparable output for this page"
            if ctx.peer_similarity_available
            else (
                "no disagreement matrix row for this page; run the disagreement command "
                "before freezing routes to use this trigger"
            )
        )

    return Triggers(
        operational_failure=operational_failure,
        oom_or_timeout=oom_or_timeout,
        empty_output=empty_output and not valid_blank_source,
        valid_blank_source=valid_blank_source,
        low_yield=low_yield,
        tiny_text=tiny_text,
        truncated=truncated,
        continuation=continuation,
        repetition=repetition,
        table_present=table_present,
        table_structure_broken=table_structure_broken,
        table_only_page=table_only_page,
        formula_heavy=formula_heavy,
        broken_text=broken_text,
        boilerplate=boilerplate,
        disagreement=disagreement,
        disagreement_available=disagreement_available,
        reasons=tuple(reasons),
        consulted=consulted,
    )


def recovery_types_for(triggers: Triggers) -> tuple[str, ...]:
    """Recovery routes a page's signals justify (MP section 24). Order is fixed."""
    routes: list[str] = []
    if triggers.oom_or_timeout or triggers.repetition:
        # A degenerate decode loop and an OOM are both runtime problems: the
        # answer is the conservative runtime settings, not a different crop.
        routes.append("safer_config")
    if triggers.empty_output:
        routes.append("alternative_prompt")
    if triggers.truncated or triggers.continuation:
        routes.append("overlap_tiling")
    if triggers.table_structure_broken:
        routes.append("crop" if triggers.table_only_page else "region_extract")
    if triggers.tiny_text:
        routes.append("higher_dpi")
    return tuple(dict.fromkeys(routes))


def risk_score(triggers: Triggers, ctx: CaseContext, params: PolicyParams) -> float:
    """An uncalibrated ranking number used only to order pages for escalation.

    It is never a quality score and never decides accept/reject on its own; the
    blind-ranking negative result from the 2026-08 campaign is the reason the
    accept path uses named triggers instead.
    """
    weights = {threshold.name: threshold.value for threshold in params.thresholds}
    similarity = ctx.peer_similarity.get(params.models.disagreement_peer)
    consulted = triggers.consulted
    repetition_ratio = float(consulted.get("ngram_repetition_ratio") or 0.0)
    duplicate_ratio = float(consulted.get("duplicate_paragraph_ratio") or 0.0)
    broken_ratio = float(consulted.get("broken_text_ratio") or 0.0)
    total = 0.0
    total += weights["risk_weight_operational_failure"] * float(triggers.operational_failure)
    total += weights["risk_weight_empty_output"] * float(triggers.empty_output)
    total += weights["risk_weight_truncated"] * float(triggers.truncated)
    total += weights["risk_weight_repetition"] * min(1.0, repetition_ratio)
    total += weights["risk_weight_duplicate_paragraph"] * min(1.0, duplicate_ratio)
    total += weights["risk_weight_broken_text"] * min(1.0, broken_ratio)
    total += weights["risk_weight_boilerplate"] * float(triggers.boilerplate)
    total += weights["risk_weight_table_broken"] * float(triggers.table_structure_broken)
    total += weights["risk_weight_low_yield"] * float(triggers.low_yield)
    if triggers.disagreement_available and similarity is not None:
        total += weights["risk_weight_disagreement"] * max(0.0, 1.0 - float(similarity))
    return round(total, 6)


# ---------------------------------------------------------------- decisions


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """One frozen route decision (contract section 3.5, MP sections 23.2 and 26)."""

    case_key: str
    sample_id: str | None
    benchmark: str | None
    primary: str
    decision: str
    target: str | None
    final_model: str
    candidate_models: tuple[str, ...]
    route_stages: tuple[Mapping[str, Any], ...]
    escalation_stage: int
    escalation_reasons: tuple[str, ...]
    number_of_model_calls: int
    recovery_required: bool
    recovery_types: tuple[str, ...]
    trigger_signals: Mapping[str, Any]
    signals_sha256: str | None
    risk_score: float | None = None
    notes: tuple[str, ...] = ()
    deployability: str | None = None

    def as_record(self, *, campaign_id: str, variant: str, policy: RoutePolicy) -> dict[str, Any]:
        record: dict[str, Any] = {
            "schema": "tavonel.arena.route-decision.v1",
            "campaign_id": campaign_id,
            "variant": variant,
            "case_key": self.case_key,
            "sample_id": self.sample_id,
            "benchmark": self.benchmark,
            "primary": self.primary,
            "decision": self.decision,
            "target": self.target,
            "final_model": self.final_model,
            "candidate_models": list(self.candidate_models),
            "route_stages": [dict(stage) for stage in self.route_stages],
            "escalation_stage": self.escalation_stage,
            "escalation_reason": list(self.escalation_reasons),
            "number_of_model_calls": self.number_of_model_calls,
            "recovery_required": self.recovery_required,
            "recovery_types": list(self.recovery_types),
            "risk_score": self.risk_score,
            "signals": dict(self.trigger_signals),
            "signals_sha256": self.signals_sha256,
            "notes": list(self.notes),
            "policy_id": policy.policy_id,
            "policy_sha256": policy.policy_sha256,
            "decided_before_gt": True,
        }
        if self.deployability is not None:
            record["deployability"] = self.deployability
        record["decision_sha256"] = prefixed(
            sha256_hex(
                canonical_json(
                    {key: value for key, value in record.items() if key != "decision_sha256"}
                )
            )
        )
        return record


# ----------------------------------------------------------------- policies


class RoutePolicy:
    """Base class. Subclasses implement ``decide`` or override ``decide_all``."""

    variant: str = ""
    policy_id: str = ""

    def __init__(self, params: PolicyParams | None = None) -> None:
        self.params = params or PolicyParams()

    # -- identity ---------------------------------------------------------

    def parameters(self) -> dict[str, Any]:
        return self.params.as_dict()

    def class_source_sha256(self) -> str:
        try:
            source = inspect.getsource(type(self))
        except OSError as exc:
            raise PolicyError(
                f"cannot read the source of {type(self).__name__}; a policy that cannot "
                "hash its own code may not freeze route decisions"
            ) from exc
        return prefixed(sha256_hex(source))

    @property
    def policy_sha256(self) -> str:
        return prefixed(
            sha256_hex(
                canonical_json(
                    {
                        "class_source_sha256": self.class_source_sha256(),
                        "parameters": self.parameters(),
                        "policy_id": self.policy_id,
                        "variant": self.variant,
                    }
                )
            )
        )

    def describe(self) -> dict[str, Any]:
        return {
            "class_source_sha256": self.class_source_sha256(),
            "description": variants.VARIANT_DESCRIPTIONS[self.variant],
            "parameters": self.parameters(),
            "policy_id": self.policy_id,
            "policy_sha256": self.policy_sha256,
            "variant": self.variant,
        }

    # -- decisions --------------------------------------------------------

    def decide(self, ctx: CaseContext) -> RouteDecision:
        raise NotImplementedError

    def decide_all(self, contexts: Sequence[CaseContext]) -> list[RouteDecision]:
        return [self.decide(ctx) for ctx in contexts]

    # -- helpers ----------------------------------------------------------

    def _primary_stage(self, reason: str = "primary") -> dict[str, Any]:
        return {"stage": 0, "model_key": self.params.models.primary, "reason": reason}

    def _base(self, ctx: CaseContext, triggers: Triggers) -> RouteDecision:
        primary = self.params.models.primary
        return RouteDecision(
            case_key=ctx.case_key,
            sample_id=ctx.sample_id,
            benchmark=ctx.benchmark,
            primary=primary,
            decision=DECISION_ACCEPT,
            target=None,
            final_model=primary,
            candidate_models=(primary,),
            route_stages=(self._primary_stage(),),
            escalation_stage=0,
            escalation_reasons=(),
            number_of_model_calls=1,
            recovery_required=False,
            recovery_types=(),
            trigger_signals=triggers.consulted,
            signals_sha256=ctx.signals_sha256,
        )


class BasePrimaryPolicy(RoutePolicy):
    """Variant A — the primary model's output, unconditionally (MP 25.A)."""

    variant = variants.VARIANT_A
    policy_id = "tavonel.variant-a.base-primary.v1"

    def decide(self, ctx: CaseContext) -> RouteDecision:
        return self._base(ctx, evaluate_triggers(ctx, self.params))


class PrimaryPlusRecoveryPolicy(RoutePolicy):
    """Variant B — the same output as A, plus a recovery plan (MP 25.B).

    B never changes which model's text is delivered. Its whole effect is the
    recovery rows it plans for pages whose signals trip a trigger, so the
    difference between A and B after scoring is the value of recovery alone.
    """

    variant = variants.VARIANT_B
    policy_id = "tavonel.variant-b.primary-plus-recovery.v1"

    def decide(self, ctx: CaseContext) -> RouteDecision:
        triggers = evaluate_triggers(ctx, self.params)
        decision = self._base(ctx, triggers)
        routes = recovery_types_for(triggers)
        if not routes:
            return decision
        return replace(
            decision,
            decision=DECISION_ACCEPT_WITH_RECOVERY,
            recovery_required=True,
            recovery_types=routes,
            escalation_reasons=triggers.reasons,
        )


class AdaptivePolicy(RoutePolicy):
    """Variant C — specialist selection on non-GT signals (MP 25.C).

    The rule list is ordered and the first match wins, so the decision is a
    function of the signals alone and does not depend on dictionary order.
    """

    variant = variants.VARIANT_C
    policy_id = "tavonel.variant-c.adaptive.v1"

    def _rules(self, triggers: Triggers) -> list[tuple[bool, str, str]]:
        models = self.params.models
        return [
            (triggers.operational_failure, models.text_specialist, "operational_failure"),
            (triggers.empty_output, models.text_specialist, "empty_output"),
            (triggers.truncated, models.text_specialist, "suspicious_truncation"),
            (triggers.repetition, models.text_specialist, "repetition"),
            (triggers.table_structure_broken, models.table_specialist, "table_structure_broken"),
            (triggers.formula_heavy, models.formula_specialist, "formula_heavy"),
            (triggers.disagreement, models.disagreement_target, "peer_disagreement"),
        ]

    def decide(self, ctx: CaseContext) -> RouteDecision:
        triggers = evaluate_triggers(ctx, self.params)
        decision = self._base(ctx, triggers)
        matched = [(target, reason) for tripped, target, reason in self._rules(triggers) if tripped]
        if not matched:
            return decision
        target, reason = matched[0]
        reasons = tuple(item[1] for item in matched)
        if ctx.available_models and target not in ctx.available_models:
            return replace(
                decision,
                escalation_reasons=reasons,
                notes=(
                    f"specialist {target} was selected for {reason} but has no frozen output "
                    "for this page; the primary output stands and the case is reported as "
                    "routed-but-unavailable",
                ),
            )
        return replace(
            decision,
            decision=DECISION_ROUTE_SPECIALIST,
            target=target,
            final_model=target,
            candidate_models=(self.params.models.primary, target),
            route_stages=(
                self._primary_stage(),
                {"stage": 1, "model_key": target, "reason": reason},
            ),
            escalation_stage=1,
            escalation_reasons=reasons,
            number_of_model_calls=2,
        )


class AdaptiveOpusEscalationPolicy(AdaptivePolicy):
    """Variant D — C plus a capped Opus escalation for the riskiest pages (MP 25.D).

    The cap is corpus-level, so D is decided over the whole set at once: pages
    are ranked by an uncalibrated risk score and the top
    ``escalation_fraction_cap`` share that also clears ``escalation_min_risk``
    is escalated. Ranking ties break on ``case_key`` so the outcome does not
    depend on input order.
    """

    variant = variants.VARIANT_D
    policy_id = "tavonel.variant-d.adaptive-opus-escalation.v1"

    def _limit(self, name: str) -> float:
        for threshold in self.params.thresholds:
            if threshold.name == name:
                return threshold.value
        raise PolicyError(f"unknown threshold {name!r}")

    def decide_all(self, contexts: Sequence[CaseContext]) -> list[RouteDecision]:
        base = [AdaptivePolicy.decide(self, ctx) for ctx in contexts]
        scored: list[tuple[float, str, int]] = []
        for index, ctx in enumerate(contexts):
            triggers = evaluate_triggers(ctx, self.params)
            scored.append((risk_score(triggers, ctx, self.params), ctx.case_key, index))

        cap = self._limit("escalation_fraction_cap")
        floor = self._limit("escalation_min_risk")
        budget = math.floor(len(contexts) * cap)
        eligible = sorted(
            (item for item in scored if item[0] >= floor),
            key=lambda item: (-item[0], item[1]),
        )
        chosen = {item[2] for item in eligible[:budget]}

        escalation = self.params.models.escalation
        decisions: list[RouteDecision] = []
        for index, (decision, ctx) in enumerate(zip(base, contexts, strict=True)):
            score = scored[index][0]
            decision = replace(decision, risk_score=score)
            if index not in chosen:
                decisions.append(decision)
                continue
            if ctx.available_models and escalation not in ctx.available_models:
                decisions.append(
                    replace(
                        decision,
                        notes=(
                            *decision.notes,
                            f"escalation model {escalation} has no frozen output for this page; "
                            "the page was selected for escalation but could not be escalated",
                        ),
                    )
                )
                continue
            stage = decision.escalation_stage + 1
            decisions.append(
                replace(
                    decision,
                    decision=DECISION_ESCALATE_OPUS,
                    target=escalation,
                    final_model=escalation,
                    candidate_models=(*decision.candidate_models, escalation),
                    route_stages=(
                        *decision.route_stages,
                        {
                            "stage": stage,
                            "model_key": escalation,
                            "reason": "highest_risk_within_escalation_cap",
                        },
                    ),
                    escalation_stage=stage,
                    escalation_reasons=(
                        *decision.escalation_reasons,
                        "highest_risk_within_escalation_cap",
                    ),
                    number_of_model_calls=decision.number_of_model_calls + 1,
                )
            )
        return decisions


def build_policy(variant: str, params: PolicyParams | None = None) -> RoutePolicy:
    """Construct the policy for a canonical variant id."""
    normalized = variants.normalize_variant(variant)
    if normalized == variants.VARIANT_A:
        return BasePrimaryPolicy(params)
    if normalized == variants.VARIANT_B:
        return PrimaryPlusRecoveryPolicy(params)
    if normalized == variants.VARIANT_C:
        return AdaptivePolicy(params)
    if normalized == variants.VARIANT_D:
        return AdaptiveOpusEscalationPolicy(params)
    from arena.tavonel.oracle import OraclePolicy

    return OraclePolicy(params)


__all__ = [
    "DECISIONS",
    "DECISION_ACCEPT",
    "DECISION_ACCEPT_WITH_RECOVERY",
    "DECISION_ESCALATE_OPUS",
    "DECISION_ORACLE_SELECT",
    "DECISION_ROUTE_SPECIALIST",
    "DEFAULT_THRESHOLDS",
    "RECOVERY_TYPES",
    "AdaptiveOpusEscalationPolicy",
    "AdaptivePolicy",
    "BasePrimaryPolicy",
    "CaseContext",
    "ModelSlots",
    "PolicyParams",
    "PrimaryPlusRecoveryPolicy",
    "RouteDecision",
    "RoutePolicy",
    "Threshold",
    "Triggers",
    "build_policy",
    "evaluate_triggers",
    "recovery_types_for",
    "risk_score",
]
