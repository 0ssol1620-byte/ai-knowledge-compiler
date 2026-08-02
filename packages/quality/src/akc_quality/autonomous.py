"""Fail-closed autonomous verification mesh and deterministic recovery policy."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from akc_cir import ContractModel
from pydantic import Field, field_validator, model_validator


class VerificationAgent(StrEnum):
    SOURCE_INTEGRITY = "source_integrity"
    STRUCTURE = "structure"
    NUMERIC = "numeric"
    DIFFERENTIAL = "differential"
    CITATION = "citation"
    KNOWLEDGE = "knowledge"
    EXPORT = "export"
    RETRIEVAL = "retrieval"


class AutonomousState(StrEnum):
    VERIFIED = "verified"
    AUTHORITY_VERIFIED = "authority_verified"
    AUTO_REPAIRED = "auto_repaired"
    VERIFIED_WITH_WARNING = "verified_with_warning"
    UNRESOLVED = "unresolved"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


class FindingLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    HARD = "hard"
    SECURITY = "security"


class RecoveryStage(StrEnum):
    DETERMINISTIC_NORMALIZATION = "deterministic_normalization"
    NATIVE_TEXT_RECONSTRUCTION = "native_text_reconstruction"
    BBOX_EXPANSION_CROP_RETRY = "bbox_expansion_crop_retry"
    OVERLAPPING_TILE = "overlapping_tile"
    SECOND_PARSER = "second_parser"
    AUTHORITY_SOURCE_MAPPING = "authority_source_mapping"
    SCHEMA_REPAIR = "schema_repair"
    ISOLATE = "unresolved_or_quarantine"


class AgentFinding(ContractModel):
    code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,79}$")]
    level: FindingLevel
    source_refs: tuple[str, ...] = ()
    detail: Annotated[str, Field(max_length=500)] = ""


class AgentReport(ContractModel):
    agent: VerificationAgent
    passed: bool
    findings: tuple[AgentFinding, ...] = ()
    authority_confirmed: bool = False
    independent_signal_count: Annotated[int, Field(ge=0, le=16)] = 0

    @model_validator(mode="after")
    def validate_report(self) -> AgentReport:
        if not self.findings:
            raise ValueError("verification agent report requires an evidence finding")
        if any(not finding.source_refs for finding in self.findings):
            raise ValueError("every verification finding requires an evidence receipt")
        if self.passed and any(
            finding.level in {FindingLevel.HARD, FindingLevel.SECURITY} for finding in self.findings
        ):
            raise ValueError("a passing report cannot contain a hard or security finding")
        if self.authority_confirmed and not self.passed:
            raise ValueError("authority confirmation cannot accompany a failed report")
        return self


class AutonomousVerificationInput(ContractModel):
    reports: tuple[AgentReport, ...]
    high_risk: bool = False
    repair_stages_completed: tuple[RecoveryStage, ...] = ()
    schema_valid: bool = True
    source_coverage: Annotated[float, Field(ge=0.0, le=1.0)] = 1.0
    unsupported_content_count: Annotated[int, Field(ge=0)] = 0

    @field_validator("reports")
    @classmethod
    def require_complete_mesh(cls, value: tuple[AgentReport, ...]) -> tuple[AgentReport, ...]:
        agents = [report.agent for report in value]
        if len(agents) != len(set(agents)):
            raise ValueError("verification mesh agents must be unique")
        missing = set(VerificationAgent) - set(agents)
        if missing:
            raise ValueError(
                f"verification mesh is incomplete: {sorted(agent.value for agent in missing)}"
            )
        if any(not report.findings for report in value):
            raise ValueError("every verification mesh report requires an evidence finding")
        if any(
            not finding.source_refs for report in value for finding in report.findings
        ):
            raise ValueError("every verification mesh finding requires an evidence receipt")
        return value

    @field_validator("repair_stages_completed")
    @classmethod
    def require_ordered_recovery(
        cls, value: tuple[RecoveryStage, ...]
    ) -> tuple[RecoveryStage, ...]:
        if len(value) != len(set(value)):
            raise ValueError("recovery stages cannot repeat")
        expected = tuple(RecoveryStage)[: len(value)]
        if value != expected:
            raise ValueError("recovery stages must follow the declared deterministic order")
        return value


class AutonomousVerificationDecision(ContractModel):
    state: AutonomousState
    accepted: bool
    billable: bool
    reason_codes: tuple[str, ...]
    authority_agents: tuple[VerificationAgent, ...]
    next_recovery_stage: RecoveryStage | None


_QUARANTINE_CODES = {
    "active_content",
    "malware_detected",
    "prompt_injection",
    "source_hash_mismatch",
    "unsafe_archive",
}


def _next_recovery_stage(
    completed: tuple[RecoveryStage, ...],
) -> RecoveryStage | None:
    stages = tuple(RecoveryStage)
    return stages[len(completed)] if len(completed) < len(stages) else None


def decide_autonomously(value: AutonomousVerificationInput) -> AutonomousVerificationDecision:
    """Accept only objective evidence; independent agreement alone is never authority."""
    value = AutonomousVerificationInput.model_validate(value.model_dump(mode="python"))
    reports = {report.agent: report for report in value.reports}
    findings = tuple(finding for report in value.reports for finding in report.findings)
    reasons = {
        finding.code
        for finding in findings
        if finding.level in {FindingLevel.HARD, FindingLevel.SECURITY}
    }
    authority_agents = tuple(report.agent for report in value.reports if report.authority_confirmed)
    if any(
        finding.level is FindingLevel.SECURITY or finding.code in _QUARANTINE_CODES
        for finding in findings
    ):
        return AutonomousVerificationDecision(
            state=AutonomousState.QUARANTINED,
            accepted=False,
            billable=False,
            reason_codes=tuple(sorted(reasons or {"security_isolation_required"})),
            authority_agents=authority_agents,
            next_recovery_stage=None,
        )

    objective_failure = (
        not value.schema_valid
        or value.source_coverage < 1.0
        or value.unsupported_content_count > 0
        or any(not report.passed for report in value.reports)
    )
    numeric = reports[VerificationAgent.NUMERIC]
    high_risk_without_authority = value.high_risk and not numeric.authority_confirmed
    if objective_failure or high_risk_without_authority:
        if not value.schema_valid:
            reasons.add("schema_invalid")
        if value.source_coverage < 1.0:
            reasons.add("source_coverage_incomplete")
        if value.unsupported_content_count:
            reasons.add("unsupported_content")
        if high_risk_without_authority:
            reasons.add("independent_agreement_without_authority")
        next_stage = _next_recovery_stage(value.repair_stages_completed)
        if next_stage is RecoveryStage.ISOLATE or next_stage is None:
            return AutonomousVerificationDecision(
                state=AutonomousState.UNRESOLVED,
                accepted=False,
                billable=False,
                reason_codes=tuple(sorted(reasons or {"hard_gate_failed"})),
                authority_agents=authority_agents,
                next_recovery_stage=None,
            )
        return AutonomousVerificationDecision(
            state=AutonomousState.UNRESOLVED,
            accepted=False,
            billable=False,
            reason_codes=tuple(sorted(reasons or {"recovery_required"})),
            authority_agents=authority_agents,
            next_recovery_stage=next_stage,
        )

    warnings = sorted(finding.code for finding in findings if finding.level is FindingLevel.WARNING)
    if authority_agents:
        state = AutonomousState.AUTHORITY_VERIFIED
    elif value.repair_stages_completed:
        state = AutonomousState.AUTO_REPAIRED
    elif warnings:
        state = AutonomousState.VERIFIED_WITH_WARNING
    else:
        state = AutonomousState.VERIFIED
    return AutonomousVerificationDecision(
        state=state,
        accepted=True,
        billable=True,
        reason_codes=tuple(warnings),
        authority_agents=authority_agents,
        next_recovery_stage=None,
    )


__all__ = [
    "AgentFinding",
    "AgentReport",
    "AutonomousState",
    "AutonomousVerificationDecision",
    "AutonomousVerificationInput",
    "FindingLevel",
    "RecoveryStage",
    "VerificationAgent",
    "decide_autonomously",
]
