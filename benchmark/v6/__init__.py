"""Fail-closed benchmark orchestration contracts for Structara v6.

The package is intentionally provider-neutral.  It can plan and validate paid
runs, but it never creates an endpoint or reads a credential by itself.
"""

from .contracts import ContractError, EnvironmentIdentity, canonical_sha256
from .evidence import sign_evidence, verify_signed_evidence
from .promotion import GateStatus, PromotionDecision, evaluate_promotion
from .registry import CandidateRegistry, CandidateSpec
from .repeats import RepeatRun, build_exact_repeat_plan, validate_repeat_plan
from .sharding import PageManifestEntry, Shard, plan_document_shards, validate_shard_plan

__all__ = [
    "CandidateRegistry",
    "CandidateSpec",
    "ContractError",
    "EnvironmentIdentity",
    "GateStatus",
    "PageManifestEntry",
    "PromotionDecision",
    "RepeatRun",
    "Shard",
    "build_exact_repeat_plan",
    "canonical_sha256",
    "evaluate_promotion",
    "plan_document_shards",
    "sign_evidence",
    "validate_repeat_plan",
    "validate_shard_plan",
    "verify_signed_evidence",
]
