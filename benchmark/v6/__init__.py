"""Fail-closed benchmark orchestration contracts for Structara v6.

The package is provider-neutral.  Its public convenience exports are loaded
lazily so lightweight contracts can be imported by build-evidence tooling
without importing registry, promotion, or optional parsing dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Final

_EXPORTS: Final = {
    "ContractError": (".contracts", "ContractError"),
    "EnvironmentIdentity": (".contracts", "EnvironmentIdentity"),
    "canonical_sha256": (".contracts", "canonical_sha256"),
    "sign_evidence": (".evidence", "sign_evidence"),
    "verify_signed_evidence": (".evidence", "verify_signed_evidence"),
    "GateStatus": (".promotion", "GateStatus"),
    "PromotionDecision": (".promotion", "PromotionDecision"),
    "evaluate_promotion": (".promotion", "evaluate_promotion"),
    "CandidateRegistry": (".registry", "CandidateRegistry"),
    "CandidateSpec": (".registry", "CandidateSpec"),
    "AdaptiveRepeatDecision": (".repeats", "AdaptiveRepeatDecision"),
    "RepeatObservation": (".repeats", "RepeatObservation"),
    "RepeatRun": (".repeats", "RepeatRun"),
    "RepeatScope": (".repeats", "RepeatScope"),
    "build_adaptive_repeat_plan": (".repeats", "build_adaptive_repeat_plan"),
    "build_exact_repeat_plan": (".repeats", "build_exact_repeat_plan"),
    "evaluate_adaptive_repeats": (".repeats", "evaluate_adaptive_repeats"),
    "materialize_adaptive_repeat_plan": (".repeats", "materialize_adaptive_repeat_plan"),
    "validate_adaptive_repeat_plan": (".repeats", "validate_adaptive_repeat_plan"),
    "validate_repeat_plan": (".repeats", "validate_repeat_plan"),
    "PageManifestEntry": (".sharding", "PageManifestEntry"),
    "Shard": (".sharding", "Shard"),
    "plan_document_shards": (".sharding", "plan_document_shards"),
    "validate_shard_plan": (".sharding", "validate_shard_plan"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve documented convenience exports only when a caller requests one."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
