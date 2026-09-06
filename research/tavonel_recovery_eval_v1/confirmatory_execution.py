#!/usr/bin/env python3
"""Frozen-arm orchestration for the TAVONEL-R confirmatory experiment.

The module deliberately separates runtime-visible trigger evidence from hidden
post-run evaluation truth. It reuses TAVONEL's existing blind prediction signals,
critical-token/parser disagreement policy, and assurance receipt types.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for path in (
    REPO / "benchmark" / "runpod_eval",
    REPO / "packages" / "cir-python" / "src",
    REPO / "packages" / "absorption" / "src",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from akc_cir.inspection import FailureCode  # noqa: E402
from akc_cir.parser_verification import (  # noqa: E402
    ParserObservation,
    compare_parser_outputs,
)
from evaluate_blind_quality_detection import compute_signals  # noqa: E402
from recovery_protocol import Arm, ProtocolRefused  # noqa: E402

PREDICTION_ONLY_THRESHOLD = 0.50
DISAGREEMENT_SIMILARITY_THRESHOLD = 0.65


class ExecutionRefused(ProtocolRefused):
    pass


@dataclass(frozen=True, slots=True)
class TriggerEvidence:
    """Evidence visible to recovery policy before hidden evaluation is opened."""

    risk: float
    uncertainty: float
    native_or_source_text: str | None = None
    structural_failure: bool = False
    critical_token_constraint_failure: bool = False
    visual_round_trip_failure: bool = False
    cross_page_failure: bool = False
    strong_verified_by_independent_evidence: bool = False

    def validate(self) -> None:
        if not 0.0 <= self.risk <= 1.0 or not 0.0 <= self.uncertainty <= 1.0:
            raise ExecutionRefused("risk and uncertainty must be within 0..1")

    @property
    def hard_failure_codes(self) -> tuple[FailureCode, ...]:
        result: list[FailureCode] = []
        if self.structural_failure:
            result.append(FailureCode.F13_TABLE_STRUCTURE)
        if self.cross_page_failure:
            result.append(FailureCode.F16_CROSS_PAGE)
        if self.visual_round_trip_failure:
            result.append(FailureCode.F17_NATIVE_RENDER_DISAGREEMENT)
        if self.critical_token_constraint_failure:
            result.append(FailureCode.F18_PARSER_DISAGREEMENT)
        return tuple(result)


@dataclass(frozen=True, slots=True)
class PageRuntimeInputs:
    page_id: str
    benchmark_id: str
    primary_text: str | None
    peer_text: str | None
    strong_text: str | None
    trigger: TriggerEvidence
    primary_gpu_seconds: float = 0.0
    strong_gpu_seconds: float = 0.0
    primary_cost_usd: float = 0.0
    strong_cost_usd: float = 0.0

    def validate(self) -> None:
        if not self.page_id or not self.benchmark_id:
            raise ExecutionRefused("page identity is required")
        self.trigger.validate()
        for value in (
            self.primary_gpu_seconds,
            self.strong_gpu_seconds,
            self.primary_cost_usd,
            self.strong_cost_usd,
        ):
            if value < 0:
                raise ExecutionRefused("runtime cost values cannot be negative")


@dataclass(frozen=True, slots=True)
class ArmOutput:
    arm: Arm
    page_id: str
    status: str
    accepted_text: str | None
    escalated_to_strong: bool
    strong_invocations: int
    gpu_seconds: float
    external_cost_usd: float
    reason: str
    runtime_visible_evidence: dict[str, Any]

    @property
    def unresolved(self) -> bool:
        return self.status == "UNRESOLVED"

    @property
    def accepted(self) -> bool:
        return self.status == "ACCEPTED"


def _nonempty(text: str | None) -> bool:
    return bool(text and text.strip())


def _blind_score(inputs: PageRuntimeInputs) -> float:
    if not _nonempty(inputs.primary_text):
        return 1.0
    signal = compute_signals(inputs.benchmark_id, inputs.page_id, inputs.primary_text or "")
    # length_z is deliberately zero in the per-page runtime baseline. The
    # historical detector's corpus-level z-normalisation is a development-only
    # convenience and is not recomputed from hidden confirmatory outcomes.
    return signal.score()


def _agreement(primary: str | None, peer: str | None) -> dict[str, Any]:
    if not _nonempty(primary) or not _nonempty(peer):
        return {
            "compared": 0,
            "normalized_text_similarity_min": 0.0,
            "critical_token_agreement": False,
            "critical_token_mismatch_count": 0,
            "unresolved": True,
        }
    result = compare_parser_outputs(
        (
            ParserObservation(parser_name="primary", text=primary or ""),
            ParserObservation(parser_name="peer-native-source", text=peer or ""),
        )
    )
    return {
        "compared": result.compared,
        "normalized_text_similarity_min": result.normalized_text_similarity_min,
        "critical_token_agreement": result.critical_token_agreement,
        "critical_token_mismatch_count": result.critical_token_mismatch_count,
        "unresolved": result.unresolved,
    }


def _base_cost(inputs: PageRuntimeInputs) -> tuple[float, float]:
    return inputs.primary_gpu_seconds, inputs.primary_cost_usd


def _with_strong_cost(inputs: PageRuntimeInputs) -> tuple[float, float]:
    return (
        inputs.primary_gpu_seconds + inputs.strong_gpu_seconds,
        inputs.primary_cost_usd + inputs.strong_cost_usd,
    )


def _unresolved(
    arm: Arm,
    inputs: PageRuntimeInputs,
    reason: str,
    *,
    escalated: bool,
    evidence: dict[str, Any],
) -> ArmOutput:
    gpu, cost = _with_strong_cost(inputs) if escalated else _base_cost(inputs)
    return ArmOutput(
        arm=arm,
        page_id=inputs.page_id,
        status="UNRESOLVED",
        accepted_text=None,
        escalated_to_strong=escalated,
        strong_invocations=1 if escalated else 0,
        gpu_seconds=gpu,
        external_cost_usd=cost,
        reason=reason,
        runtime_visible_evidence=evidence,
    )


def _accept(
    arm: Arm,
    inputs: PageRuntimeInputs,
    text: str,
    reason: str,
    *,
    escalated: bool,
    evidence: dict[str, Any],
) -> ArmOutput:
    gpu, cost = _with_strong_cost(inputs) if escalated else _base_cost(inputs)
    return ArmOutput(
        arm=arm,
        page_id=inputs.page_id,
        status="ACCEPTED",
        accepted_text=text,
        escalated_to_strong=escalated,
        strong_invocations=1 if escalated else 0,
        gpu_seconds=gpu,
        external_cost_usd=cost,
        reason=reason,
        runtime_visible_evidence=evidence,
    )


def execute_arm(arm: Arm, inputs: PageRuntimeInputs) -> ArmOutput:
    inputs.validate()
    if arm is Arm.ORACLE_DIAGNOSTIC:
        raise ExecutionRefused("oracle diagnostic cannot execute as a primary runtime arm")

    primary_ok = _nonempty(inputs.primary_text)
    strong_ok = _nonempty(inputs.strong_text)
    agreement = _agreement(inputs.primary_text, inputs.peer_text)
    blind_score = _blind_score(inputs)
    base_evidence: dict[str, Any] = {
        "blind_score": blind_score,
        "parser_agreement": agreement,
        "risk": inputs.trigger.risk,
        "uncertainty": inputs.trigger.uncertainty,
        "hard_failure_codes": [code.value for code in inputs.trigger.hard_failure_codes],
        "evaluation_truth_visible": False,
    }

    if arm is Arm.PRIMARY_ONLY:
        if not primary_ok:
            return _unresolved(
                arm,
                inputs,
                "primary produced no usable output",
                escalated=False,
                evidence=base_evidence,
            )
        return _accept(
            arm,
            inputs,
            inputs.primary_text or "",
            "primary output accepted without recovery",
            escalated=False,
            evidence=base_evidence,
        )

    if arm is Arm.ALWAYS_STRONG:
        if not strong_ok:
            return _unresolved(
                arm,
                inputs,
                "always-strong model produced no usable output",
                escalated=True,
                evidence=base_evidence,
            )
        return _accept(
            arm,
            inputs,
            inputs.strong_text or "",
            "always-strong baseline",
            escalated=True,
            evidence=base_evidence,
        )

    if arm is Arm.PREDICTION_ONLY:
        escalate = (not primary_ok) or blind_score >= PREDICTION_ONLY_THRESHOLD
        if escalate:
            if not strong_ok:
                return _unresolved(
                    arm,
                    inputs,
                    "prediction-only escalation had no strong output",
                    escalated=True,
                    evidence=base_evidence,
                )
            return _accept(
                arm,
                inputs,
                inputs.strong_text or "",
                "prediction-only suspicion threshold escalated",
                escalated=True,
                evidence=base_evidence,
            )
        return _accept(
            arm,
            inputs,
            inputs.primary_text or "",
            "prediction-only suspicion below threshold",
            escalated=False,
            evidence=base_evidence,
        )

    if arm is Arm.DISAGREEMENT_ONLY:
        escalate = (not primary_ok) or agreement["unresolved"]
        if escalate:
            if not strong_ok:
                return _unresolved(
                    arm,
                    inputs,
                    "disagreement escalation had no strong output",
                    escalated=True,
                    evidence=base_evidence,
                )
            return _accept(
                arm,
                inputs,
                inputs.strong_text or "",
                "parser disagreement escalated",
                escalated=True,
                evidence=base_evidence,
            )
        return _accept(
            arm,
            inputs,
            inputs.primary_text or "",
            "primary and independent peer agreed",
            escalated=False,
            evidence=base_evidence,
        )

    if arm is not Arm.TAVONEL_EVIDENCE_RECOVERY:
        raise ExecutionRefused(f"unsupported primary arm: {arm}")

    hard_failure = bool(inputs.trigger.hard_failure_codes)
    evidence_deficient = (
        not primary_ok
        or not _nonempty(inputs.peer_text)
        or agreement["unresolved"]
        or hard_failure
        or inputs.trigger.risk >= 0.55
        or inputs.trigger.uncertainty >= 0.35
    )
    if not evidence_deficient:
        return _accept(
            arm,
            inputs,
            inputs.primary_text or "",
            "independent evidence supports primary output",
            escalated=False,
            evidence=base_evidence,
        )

    if not strong_ok:
        return _unresolved(
            arm,
            inputs,
            "evidence required escalation but strong output was unavailable",
            escalated=True,
            evidence=base_evidence,
        )

    strong_agreement = _agreement(inputs.strong_text, inputs.peer_text)
    base_evidence["strong_peer_agreement"] = strong_agreement
    strong_supported = (
        inputs.trigger.strong_verified_by_independent_evidence
        and not strong_agreement["unresolved"]
        and strong_agreement["normalized_text_similarity_min"] >= DISAGREEMENT_SIMILARITY_THRESHOLD
    )
    if not strong_supported:
        return _unresolved(
            arm,
            inputs,
            "strong result did not obtain independent support; fail closed",
            escalated=True,
            evidence=base_evidence,
        )
    return _accept(
        arm,
        inputs,
        inputs.strong_text or "",
        "strong result independently supported after evidence-driven escalation",
        escalated=True,
        evidence=base_evidence,
    )


def execute_all_primary_arms(inputs: PageRuntimeInputs) -> tuple[ArmOutput, ...]:
    return tuple(
        execute_arm(arm, inputs)
        for arm in (
            Arm.PRIMARY_ONLY,
            Arm.ALWAYS_STRONG,
            Arm.PREDICTION_ONLY,
            Arm.DISAGREEMENT_ONLY,
            Arm.TAVONEL_EVIDENCE_RECOVERY,
        )
    )


__all__ = [
    "DISAGREEMENT_SIMILARITY_THRESHOLD",
    "PREDICTION_ONLY_THRESHOLD",
    "ArmOutput",
    "ExecutionRefused",
    "PageRuntimeInputs",
    "TriggerEvidence",
    "execute_all_primary_arms",
    "execute_arm",
]
