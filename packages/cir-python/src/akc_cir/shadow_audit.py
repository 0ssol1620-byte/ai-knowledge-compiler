"""Deterministic shadow full-rebuild sampling with safe mismatch fallback."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from .recompilation import EquivalenceReport, RecompilationPlan, verify_equivalence

__all__ = [
    "ShadowAuditPolicy",
    "ShadowAuditResult",
    "run_shadow_audit",
    "should_shadow_audit",
]


@dataclass(frozen=True, slots=True)
class ShadowAuditPolicy:
    sample_rate: float = 0.05
    high_risk_threshold: float = 0.80
    seed: str = "tavonel-shadow-audit-v1"

    def __post_init__(self) -> None:
        if not 0.0 <= self.sample_rate <= 1.0:
            raise ValueError("sample_rate must be within 0..1")
        if not 0.0 <= self.high_risk_threshold <= 1.0:
            raise ValueError("high_risk_threshold must be within 0..1")


def should_shadow_audit(
    change_id: str,
    *,
    risk: float,
    policy: ShadowAuditPolicy | None = None,
) -> tuple[bool, str]:
    if not change_id:
        raise ValueError("change_id is required")
    if not 0.0 <= risk <= 1.0:
        raise ValueError("risk must be within 0..1")
    limits = policy or ShadowAuditPolicy()
    if risk >= limits.high_risk_threshold:
        return True, "high-risk change requires a full-rebuild shadow oracle"
    digest = hashlib.sha256(f"{limits.seed}:{change_id}".encode()).digest()
    draw = int.from_bytes(digest[:8], "big") / float(2**64)
    if draw < limits.sample_rate:
        return True, "change selected by deterministic random shadow sample"
    return False, "change outside configured shadow sample"


@dataclass(frozen=True, slots=True)
class ShadowAuditResult:
    ran: bool
    reason: str
    equivalence: EquivalenceReport | None
    fallback_required: bool

    @property
    def safe_to_publish_selective(self) -> bool:
        return self.ran and not self.fallback_required and bool(
            self.equivalence and self.equivalence.equivalent
        )


def run_shadow_audit(
    *,
    change_id: str,
    risk: float,
    full_rebuild: Mapping[str, str],
    selective_rebuild: Mapping[str, str],
    carried_over: Mapping[str, str],
    plan: RecompilationPlan | None = None,
    policy: ShadowAuditPolicy | None = None,
) -> ShadowAuditResult:
    required, reason = should_shadow_audit(change_id, risk=risk, policy=policy)
    if not required:
        return ShadowAuditResult(False, reason, None, False)
    report = verify_equivalence(
        full_rebuild=full_rebuild,
        selective_rebuild=selective_rebuild,
        carried_over=carried_over,
        plan=plan,
    )
    return ShadowAuditResult(
        ran=True,
        reason=reason,
        equivalence=report,
        fallback_required=not report.equivalent,
    )