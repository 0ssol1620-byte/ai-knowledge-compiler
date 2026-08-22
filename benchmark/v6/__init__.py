"""Fail-closed benchmark orchestration contracts for Structara v6.

The package is intentionally provider-neutral.  It can plan and validate paid
runs, but it never creates an endpoint or reads a credential by itself.
"""

from .contracts import ContractError, EnvironmentIdentity, canonical_sha256
from .evidence import sign_evidence, verify_signed_evidence
from .promotion import GateStatus, PromotionDecision, evaluate_promotion
from .registry import CandidateRegistry, CandidateSpec
from .repeats import (
    AdaptiveRepeatDecision,
    RepeatObservation,
    RepeatRun,
    RepeatScope,
    build_adaptive_repeat_plan,
    build_exact_repeat_plan,
    evaluate_adaptive_repeats,
    materialize_adaptive_repeat_plan,
    validate_adaptive_repeat_plan,
    validate_repeat_plan,
)
from .sharding import PageManifestEntry, Shard, plan_document_shards, validate_shard_plan

__all__ = [
    "AdaptiveRepeatDecision",
    "CandidateRegistry",
    "CandidateSpec",
    "ContractError",
    "EnvironmentIdentity",
    "GateStatus",
    "PageManifestEntry",
    "PromotionDecision",
    "RepeatObservation",
    "RepeatRun",
    "RepeatScope",
    "Shard",
    "build_adaptive_repeat_plan",
    "build_exact_repeat_plan",
    "canonical_sha256",
    "evaluate_adaptive_repeats",
    "evaluate_promotion",
    "materialize_adaptive_repeat_plan",
    "plan_document_shards",
    "sign_evidence",
    "validate_adaptive_repeat_plan",
    "validate_repeat_plan",
    "validate_shard_plan",
    "verify_signed_evidence",
]
