#!/usr/bin/env python3
"""Prospective protocol contract for TAVONEL evidence-driven document recovery.

This module is intentionally PRE-FREEZE.  It exists to remove scientific degrees
of freedom *before* a fresh confirmatory cohort is opened.  Historical public
benchmark and DART/SEC results are development evidence only; they may motivate
this protocol but may not select, tune, or score its confirmatory cohort.

The central contrast is not "small model versus big model".  It is whether
production-available, independent evidence can decide *where* to spend stronger
inference while preserving unresolved cases instead of silently accepting them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

PROTOCOL_ID = "TAVONEL_RECOVERY_FRESH_CONFIRMATORY_V1"
SCHEMA = "tavonel.recovery.confirmatory.protocol.v1"
PRE_FREEZE_DRAFT = "PRE_FREEZE_DRAFT"
FROZEN = "FROZEN"


class ProtocolRefused(RuntimeError):
    """A requested action would make the confirmatory result uninterpretable."""


class Arm(StrEnum):
    PRIMARY_ONLY = "PRIMARY_ONLY"
    ALWAYS_STRONG = "ALWAYS_STRONG"
    PREDICTION_ONLY = "PREDICTION_ONLY"
    DISAGREEMENT_ONLY = "DISAGREEMENT_ONLY"
    TAVONEL_EVIDENCE_RECOVERY = "TAVONEL_EVIDENCE_RECOVERY"
    ORACLE_DIAGNOSTIC = "ORACLE_DIAGNOSTIC"


PRIMARY_ARMS = (
    Arm.PRIMARY_ONLY,
    Arm.ALWAYS_STRONG,
    Arm.PREDICTION_ONLY,
    Arm.DISAGREEMENT_ONLY,
    Arm.TAVONEL_EVIDENCE_RECOVERY,
)

REQUIRED_MODEL_ROLES = frozenset({"primary", "peer", "strong"})

PRIMARY_ENDPOINTS = (
    "accepted_silent_critical_error_rate",
    "critical_semantic_exactness",
    "unresolved_rate",
    "recovery_success_given_escalation",
    "strong_model_invocation_fraction",
    "gpu_seconds_per_1000_pages",
    "external_cost_usd_per_1000_pages",
)

# Production-available evidence classes.  Evaluation-only truth is deliberately
# absent.  "Disagreement is evidence, not truth": disagreement can trigger more
# work but cannot by itself declare one model correct.
TRIGGER_EVIDENCE_CLASSES = (
    "SOURCE_NATIVE",
    "RASTER_VISUAL",
    "PARSER_A",
    "PARSER_B",
    "STRUCTURAL_CONSTRAINT",
    "CRITICAL_TOKEN_CONSTRAINT",
    "AUTHORITY",
)

# The historical blind detector is retained as a deliberately weak baseline.
PREDICTION_ONLY_SIGNALS = (
    "empty_output",
    "repetition_ratio",
    "table_schema_failure",
    "table_row_ragged_ratio",
    "alpha_ratio",
    "length_z",
    "truncated_tail",
)

# No threshold in this protocol may be selected on confirmatory outcomes.  A
# future freeze receipt must bind the concrete values and their calibration
# source before cohort opening.
TUNING_POLICY = "CALIBRATION_OR_DEVELOPMENT_ONLY_NEVER_CONFIRMATORY"
UNRESOLVED_POLICY = "FAIL_CLOSED_NO_SILENT_ACCEPT"
MERGE_POLICY = "PROVENANCE_PRESERVING_REGION_OR_PAGE_REPLACEMENT_ONLY"

# Historical corpora are explicitly spent for *confirmatory* selection.  A
# concrete spent-manifest must bind exact document/page identities before freeze.
SPENT_DEVELOPMENT_FAMILIES = (
    "PARSEBENCH_2026_08_09_2078",
    "OMNIDOCBENCH_2026_08_09_1651",
    "OLMOCR_BENCH_2026_08_09_1403",
    "DART_SEC_20_PAGE_A40_FIXED_SET",
    "SEC_PUBLIC_DEMO_FIXTURES_AND_KNOWN_FAILURE_CASES",
)

# Automatic external-spend caps are intentionally lower than the older broad
# assurance harness.  A larger run requires a separate explicit budget receipt.
STAGE1_MAX_PAGES = 300
STAGE1_MAX_GPU_SECONDS = 18_000.0
STAGE1_MAX_EXTERNAL_COST_USD = 30.0
STAGE2_MAX_PAGES = 1_000
STAGE2_MAX_GPU_SECONDS = 72_000.0
STAGE2_MAX_EXTERNAL_COST_USD = 120.0
QUALIFICATION_MAX_PAGES = 50
QUALIFICATION_MAX_GPU_SECONDS = 10_800.0
QUALIFICATION_MAX_EXTERNAL_COST_USD = 10.0
CACHE_PREPARATION_MAX_GPU_SECONDS = 14_400.0
CACHE_PREPARATION_MAX_EXTERNAL_COST_USD = 10.0
CACHE_PREPARATION_MAX_VOLUME_GB = 60

_SECRET_MARKERS = ("secret", "token", "password", "api_key", "apikey", "credential")
_OUTCOME_MARKERS = (
    "accuracy",
    "score",
    "correct",
    "failure_count",
    "error_rate",
    "winner",
    "effect_size",
    "p_value",
    "confidence_interval",
    "result",
)


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _walk_keys(value: Any) -> Sequence[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            found.append(str(key))
            found.extend(_walk_keys(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found.extend(_walk_keys(nested))
    return found


def reject_secret_like_metadata(metadata: Mapping[str, Any]) -> None:
    for key in _walk_keys(metadata):
        folded = key.casefold()
        if any(marker in folded for marker in _SECRET_MARKERS):
            raise ProtocolRefused(f"secret-like metadata field is forbidden: {key}")


def reject_confirmatory_outcomes(metadata: Mapping[str, Any]) -> None:
    """Prevent outcome-bearing data from entering a pre-freeze authority object."""
    for key in _walk_keys(metadata):
        folded = key.casefold()
        if any(marker in folded for marker in _OUTCOME_MARKERS):
            raise ProtocolRefused(
                f"confirmatory outcome-like field is forbidden before freeze: {key}"
            )


@dataclass(frozen=True, slots=True)
class ModelPin:
    role: str
    model_id: str
    model_revision: str
    runtime_id: str
    runtime_digest: str
    prompt_or_schema_digest: str

    def validate(self) -> None:
        if not all(
            (
                self.role,
                self.model_id,
                self.model_revision,
                self.runtime_id,
                self.runtime_digest,
                self.prompt_or_schema_digest,
            )
        ):
            raise ProtocolRefused(f"model pin {self.role!r} is incomplete")
        for name, value in (
            ("runtime_digest", self.runtime_digest),
            ("prompt_or_schema_digest", self.prompt_or_schema_digest),
        ):
            if not value.startswith("sha256:") or len(value) != 71:
                raise ProtocolRefused(f"{self.role}.{name} is not a full sha256 pin")


@dataclass(frozen=True, slots=True)
class EvidenceSplit:
    """Hash-partitioned production evidence and hidden evaluation truth.

    The same anchor cannot be both a recovery trigger and evaluation truth.  The
    split must be produced before inference from stable anchor IDs and a frozen
    salt.  Public benchmark evaluator labels are always evaluation-only.
    """

    split_salt_digest: str
    trigger_anchor_ids: tuple[str, ...]
    evaluation_anchor_ids: tuple[str, ...]

    def validate(self) -> None:
        if not self.split_salt_digest.startswith("sha256:") or len(self.split_salt_digest) != 71:
            raise ProtocolRefused("evidence split salt must be represented by a full sha256 digest")
        trigger = set(self.trigger_anchor_ids)
        evaluation = set(self.evaluation_anchor_ids)
        overlap = trigger & evaluation
        if overlap:
            raise ProtocolRefused(
                f"trigger evidence overlaps hidden evaluation truth: {sorted(overlap)[:3]}"
            )
        if not trigger or not evaluation:
            raise ProtocolRefused(
                "both trigger and evaluation evidence partitions must be non-empty"
            )


@dataclass(frozen=True, slots=True)
class FreshCohortAuthority:
    corpus_id: str
    source_manifest_digest: str
    spent_manifest_digest: str
    selection_rule_digest: str
    cohort_seal_digest: str | None = None
    family_overlap_with_spent: bool = False

    def validate_pre_open(self) -> None:
        for name, value in (
            ("source_manifest_digest", self.source_manifest_digest),
            ("spent_manifest_digest", self.spent_manifest_digest),
            ("selection_rule_digest", self.selection_rule_digest),
        ):
            if not value.startswith("sha256:") or len(value) != 71:
                raise ProtocolRefused(f"{name} is not a full sha256 pin")
        if self.cohort_seal_digest is not None:
            raise ProtocolRefused("pre-open authority must not already contain a cohort seal")
        if self.family_overlap_with_spent:
            raise ProtocolRefused("fresh confirmatory cohort overlaps spent development evidence")


@dataclass(frozen=True, slots=True)
class RecoveryProtocol:
    state: str = PRE_FREEZE_DRAFT
    model_pins: tuple[ModelPin, ...] = field(default_factory=tuple)
    cohort: FreshCohortAuthority | None = None
    evidence_split: EvidenceSplit | None = None
    calibration_manifest_digest: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def terms(self) -> dict[str, Any]:
        return {
            "protocol_id": PROTOCOL_ID,
            "schema": SCHEMA,
            "state": self.state,
            "research_question": (
                "Can production-available independent evidence selectively escalate only "
                "untrustworthy document regions/pages and approach always-strong reliability "
                "at lower inference cost while failing closed on unresolved outputs?"
            ),
            "primary_arms": [arm.value for arm in PRIMARY_ARMS],
            "oracle_diagnostic": {
                "arm": Arm.ORACLE_DIAGNOSTIC.value,
                "primary_inference": False,
                "may_read_evaluation_truth": True,
                "why": "diagnostic ceiling only; never eligible for a primary TAVONEL claim",
            },
            "primary_endpoints": list(PRIMARY_ENDPOINTS),
            "trigger_evidence_classes": list(TRIGGER_EVIDENCE_CLASSES),
            "prediction_only_baseline_signals": list(PREDICTION_ONLY_SIGNALS),
            "policies": {
                "tuning": TUNING_POLICY,
                "unresolved": UNRESOLVED_POLICY,
                "merge": MERGE_POLICY,
                "disagreement_semantics": "EVIDENCE_OF_UNCERTAINTY_NOT_CORRECTNESS",
                "confirmatory_labels_visible_to_runtime": False,
                "threshold_retuning_after_cohort_open": False,
                "accept_only_improved_using_confirmatory_ground_truth": False,
            },
            "spent_development_families": list(SPENT_DEVELOPMENT_FAMILIES),
            "gpu_guardrails": {
                "development_cache_preparation": {
                    "fresh_confirmatory_pages": 0,
                    "max_gpu_seconds": CACHE_PREPARATION_MAX_GPU_SECONDS,
                    "max_external_cost_usd": CACHE_PREPARATION_MAX_EXTERNAL_COST_USD,
                    "max_persistent_volume_gb": CACHE_PREPARATION_MAX_VOLUME_GB,
                    "fresh_cohort_must_remain_unopened": True,
                    "purpose": (
                        "prepare exact pinned runtime/model bytes on persistent storage before "
                        "runtime qualification; this lane contributes no confirmatory observation"
                    ),
                },
                "development_runtime_qualification": {
                    "max_pages": QUALIFICATION_MAX_PAGES,
                    "max_gpu_seconds": QUALIFICATION_MAX_GPU_SECONDS,
                    "max_external_cost_usd": QUALIFICATION_MAX_EXTERNAL_COST_USD,
                    "spent_inputs_only": True,
                    "fresh_cohort_must_remain_unopened": True,
                },
                "stage1": {
                    "max_pages": STAGE1_MAX_PAGES,
                    "max_gpu_seconds": STAGE1_MAX_GPU_SECONDS,
                    "max_external_cost_usd": STAGE1_MAX_EXTERNAL_COST_USD,
                },
                "stage2": {
                    "max_pages": STAGE2_MAX_PAGES,
                    "max_gpu_seconds": STAGE2_MAX_GPU_SECONDS,
                    "max_external_cost_usd": STAGE2_MAX_EXTERNAL_COST_USD,
                },
                "large_run_requires_separate_explicit_budget_receipt": True,
            },
            "statistics": {
                "unit": "page_or_region_with_document_family_cluster",
                "paired_primary_comparison": (
                    "McNemar exact where binary paired correctness applies"
                ),
                "intervals": "document-family cluster bootstrap 95% CI",
                "cost_latency": "paired bootstrap or permutation; preserve heavy tails",
                "multiple_primary_comparisons": "Holm correction",
                "report_effect_size_before_p_value": True,
            },
            "model_pins": [
                {
                    "role": pin.role,
                    "model_id": pin.model_id,
                    "model_revision": pin.model_revision,
                    "runtime_id": pin.runtime_id,
                    "runtime_digest": pin.runtime_digest,
                    "prompt_or_schema_digest": pin.prompt_or_schema_digest,
                }
                for pin in self.model_pins
            ],
            "cohort": None
            if self.cohort is None
            else {
                "corpus_id": self.cohort.corpus_id,
                "source_manifest_digest": self.cohort.source_manifest_digest,
                "spent_manifest_digest": self.cohort.spent_manifest_digest,
                "selection_rule_digest": self.cohort.selection_rule_digest,
                "cohort_seal_digest": self.cohort.cohort_seal_digest,
                "family_overlap_with_spent": self.cohort.family_overlap_with_spent,
            },
            "evidence_split": None
            if self.evidence_split is None
            else {
                "split_salt_digest": self.evidence_split.split_salt_digest,
                "trigger_anchor_count": len(self.evidence_split.trigger_anchor_ids),
                "evaluation_anchor_count": len(self.evidence_split.evaluation_anchor_ids),
                # Anchor identities themselves belong in the sealed manifest, not in
                # the protocol summary that people may inspect during execution.
            },
            "calibration_manifest_digest": self.calibration_manifest_digest,
            "metadata": dict(self.metadata),
        }

    def validate_draft(self) -> None:
        if self.state != PRE_FREEZE_DRAFT:
            raise ProtocolRefused("draft validation requires PRE_FREEZE_DRAFT")
        reject_secret_like_metadata(self.metadata)
        reject_confirmatory_outcomes(self.metadata)

    def validate_ready_to_freeze(self) -> None:
        self.validate_draft()
        if len(self.model_pins) < len(REQUIRED_MODEL_ROLES):
            raise ProtocolRefused("freeze requires primary, peer, and strong model pins")
        roles = [pin.role for pin in self.model_pins]
        if len(roles) != len(set(roles)):
            raise ProtocolRefused("model roles must be unique")
        missing_roles = REQUIRED_MODEL_ROLES.difference(roles)
        if missing_roles:
            raise ProtocolRefused(
                f"freeze is missing required model roles: {sorted(missing_roles)}"
            )
        for pin in self.model_pins:
            pin.validate()
        if self.cohort is None:
            raise ProtocolRefused("freeze requires a fresh cohort authority")
        self.cohort.validate_pre_open()
        if self.evidence_split is None:
            raise ProtocolRefused("freeze requires a trigger/evaluation evidence split")
        self.evidence_split.validate()
        if not self.calibration_manifest_digest:
            raise ProtocolRefused("freeze requires a calibration/development manifest pin")
        if not self.calibration_manifest_digest.startswith("sha256:") or len(
            self.calibration_manifest_digest
        ) != 71:
            raise ProtocolRefused("calibration manifest is not a full sha256 pin")

    def digest(self) -> str:
        return _canonical_digest(self.terms())


def authorize_gpu_stage(
    *,
    protocol_state: str,
    cohort_sealed: bool,
    cpu_gate_green: bool,
    stage: int,
    pages: int,
    estimated_gpu_seconds: float,
    estimated_external_cost_usd: float,
    prior_gpu_stage_green: bool = False,
) -> str:
    """Return an authorization code or refuse before any external GPU spend."""
    if protocol_state != FROZEN:
        raise ProtocolRefused("GPU work requires a committed/frozen protocol")
    if not cohort_sealed:
        raise ProtocolRefused("GPU work requires a sealed fresh cohort")
    if not cpu_gate_green:
        raise ProtocolRefused("GPU work requires a GREEN CPU/synthetic preflight")
    if pages < 0 or estimated_gpu_seconds < 0 or estimated_external_cost_usd < 0:
        raise ProtocolRefused("GPU workload and cost estimates cannot be negative")
    if stage == 1:
        if pages > STAGE1_MAX_PAGES:
            raise ProtocolRefused("Stage 1 page cap exceeded")
        if estimated_gpu_seconds > STAGE1_MAX_GPU_SECONDS:
            raise ProtocolRefused("Stage 1 GPU-seconds cap exceeded")
        if estimated_external_cost_usd > STAGE1_MAX_EXTERNAL_COST_USD:
            raise ProtocolRefused("Stage 1 external-cost cap exceeded")
        return "STAGE1_GPU_AUTHORIZED"
    if stage == 2:
        if not prior_gpu_stage_green:
            raise ProtocolRefused("Stage 2 requires Stage 1 GREEN")
        if pages > STAGE2_MAX_PAGES:
            raise ProtocolRefused("Stage 2 page cap exceeded")
        if estimated_gpu_seconds > STAGE2_MAX_GPU_SECONDS:
            raise ProtocolRefused("Stage 2 GPU-seconds cap exceeded")
        if estimated_external_cost_usd > STAGE2_MAX_EXTERNAL_COST_USD:
            raise ProtocolRefused("Stage 2 external-cost cap exceeded")
        return "STAGE2_GPU_AUTHORIZED"
    raise ProtocolRefused("large GPU runs require a separate explicit budget receipt")


def authorize_development_runtime_qualification(
    *,
    protocol_state: str,
    fresh_cohort_opened: bool,
    spent_development_only: bool,
    pages: int,
    gpu_seconds: float,
    external_cost_usd: float,
) -> str:
    """Authorize only pre-freeze runtime qualification on already-spent inputs.

    This lane exists to obtain exact model/runtime pins before the confirmatory
    protocol is frozen.  It cannot see or score a fresh cohort and therefore
    cannot contribute primary confirmatory observations.
    """
    if protocol_state != PRE_FREEZE_DRAFT:
        raise ProtocolRefused("runtime qualification is a pre-freeze development lane")
    if fresh_cohort_opened:
        raise ProtocolRefused("runtime qualification must finish before fresh cohort opening")
    if not spent_development_only:
        raise ProtocolRefused("runtime qualification may use spent development inputs only")
    if pages < 0 or gpu_seconds < 0 or external_cost_usd < 0:
        raise ProtocolRefused("runtime qualification workload cannot be negative")
    if pages > QUALIFICATION_MAX_PAGES:
        raise ProtocolRefused("runtime qualification page cap exceeded")
    if gpu_seconds > QUALIFICATION_MAX_GPU_SECONDS:
        raise ProtocolRefused("runtime qualification GPU-seconds cap exceeded")
    if external_cost_usd > QUALIFICATION_MAX_EXTERNAL_COST_USD:
        raise ProtocolRefused("runtime qualification external-cost cap exceeded")
    return "DEVELOPMENT_RUNTIME_QUALIFICATION_AUTHORIZED"


def authorize_development_cache_preparation(
    *,
    protocol_state: str,
    fresh_cohort_opened: bool,
    gpu_seconds: float,
    external_cost_usd: float,
    persistent_volume_gb: int,
) -> str:
    """Authorize bounded pre-freeze persistent runtime/model cache preparation."""

    if protocol_state != PRE_FREEZE_DRAFT:
        raise ProtocolRefused("cache preparation is a pre-freeze development lane")
    if fresh_cohort_opened:
        raise ProtocolRefused("cache preparation must finish before fresh cohort opening")
    if gpu_seconds < 0 or external_cost_usd < 0 or persistent_volume_gb < 0:
        raise ProtocolRefused("cache preparation workload cannot be negative")
    if gpu_seconds > CACHE_PREPARATION_MAX_GPU_SECONDS:
        raise ProtocolRefused("cache preparation GPU-seconds cap exceeded")
    if external_cost_usd > CACHE_PREPARATION_MAX_EXTERNAL_COST_USD:
        raise ProtocolRefused("cache preparation external-cost cap exceeded")
    if persistent_volume_gb < 1 or persistent_volume_gb > CACHE_PREPARATION_MAX_VOLUME_GB:
        raise ProtocolRefused("cache preparation persistent-volume cap exceeded")
    return "DEVELOPMENT_CACHE_PREPARATION_AUTHORIZED"


__all__ = [
    "FROZEN",
    "PRE_FREEZE_DRAFT",
    "Arm",
    "EvidenceSplit",
    "FreshCohortAuthority",
    "ModelPin",
    "ProtocolRefused",
    "RecoveryProtocol",
    "authorize_development_cache_preparation",
    "authorize_development_runtime_qualification",
    "authorize_gpu_stage",
    "reject_confirmatory_outcomes",
    "reject_secret_like_metadata",
]
