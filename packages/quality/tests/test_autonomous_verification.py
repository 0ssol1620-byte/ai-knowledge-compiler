from __future__ import annotations

import pytest
from akc_quality import (
    AgentFinding,
    AgentReport,
    AutonomousState,
    AutonomousVerificationInput,
    FindingLevel,
    RecoveryStage,
    VerificationAgent,
    decide_autonomously,
)

RECEIPT = "sha256:" + ("a" * 64)


def _finding(code: str, level: FindingLevel = FindingLevel.INFO) -> AgentFinding:
    return AgentFinding(code=code, level=level, source_refs=(RECEIPT,))


def _passing_report(agent: VerificationAgent, **updates: object) -> AgentReport:
    return AgentReport(
        agent=agent,
        passed=True,
        findings=(_finding(f"{agent.value}_verified"),),
        **updates,
    )


def _reports(**overrides: AgentReport) -> tuple[AgentReport, ...]:
    return tuple(
        overrides.get(agent.value, _passing_report(agent))
        for agent in VerificationAgent
    )


def test_complete_mesh_verifies_only_with_all_objective_gates() -> None:
    decision = decide_autonomously(AutonomousVerificationInput(reports=_reports()))
    assert decision.state is AutonomousState.VERIFIED
    assert decision.accepted and decision.billable


def test_high_risk_parser_agreement_is_not_authority() -> None:
    reports = _reports(
        differential=_passing_report(
            VerificationAgent.DIFFERENTIAL, independent_signal_count=3
        )
    )
    decision = decide_autonomously(AutonomousVerificationInput(reports=reports, high_risk=True))
    assert decision.state is AutonomousState.UNRESOLVED
    assert not decision.billable
    assert "independent_agreement_without_authority" in decision.reason_codes


def test_high_risk_cannot_bypass_authority_when_no_disagreement_was_recorded() -> None:
    decision = decide_autonomously(AutonomousVerificationInput(reports=_reports(), high_risk=True))
    assert decision.state is AutonomousState.UNRESOLVED
    assert not decision.accepted and not decision.billable


def test_authority_confirmation_allows_high_risk_acceptance() -> None:
    reports = _reports(
        numeric=_passing_report(VerificationAgent.NUMERIC, authority_confirmed=True),
        differential=_passing_report(
            VerificationAgent.DIFFERENTIAL, independent_signal_count=2
        ),
    )
    decision = decide_autonomously(AutonomousVerificationInput(reports=reports, high_risk=True))
    assert decision.state is AutonomousState.AUTHORITY_VERIFIED
    assert decision.authority_agents == (VerificationAgent.NUMERIC,)


def test_security_finding_quarantines_without_billing_or_recovery() -> None:
    reports = _reports(
        source_integrity=AgentReport(
            agent=VerificationAgent.SOURCE_INTEGRITY,
            passed=False,
            findings=(_finding("prompt_injection", FindingLevel.SECURITY),),
        )
    )
    decision = decide_autonomously(AutonomousVerificationInput(reports=reports))
    assert decision.state is AutonomousState.QUARANTINED
    assert not decision.accepted and not decision.billable
    assert decision.next_recovery_stage is None


def test_recovery_sequence_is_exact_and_exhaustion_is_unresolved() -> None:
    reports = _reports(
        structure=AgentReport(
            agent=VerificationAgent.STRUCTURE,
            passed=False,
            findings=(_finding("row_omission", FindingLevel.HARD),),
        )
    )
    first = decide_autonomously(AutonomousVerificationInput(reports=reports))
    assert first.next_recovery_stage is RecoveryStage.DETERMINISTIC_NORMALIZATION
    completed = tuple(RecoveryStage)[:-1]
    exhausted = decide_autonomously(
        AutonomousVerificationInput(
            reports=reports,
            repair_stages_completed=completed,
        )
    )
    assert exhausted.state is AutonomousState.UNRESOLVED
    assert exhausted.next_recovery_stage is None
    assert not exhausted.billable
    already_isolated = decide_autonomously(
        AutonomousVerificationInput(
            reports=reports,
            repair_stages_completed=tuple(RecoveryStage),
        )
    )
    assert already_isolated.state is AutonomousState.UNRESOLVED
    assert already_isolated.next_recovery_stage is None


def test_incomplete_mesh_and_out_of_order_recovery_are_rejected() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        AutonomousVerificationInput(reports=_reports()[:-1])
    with pytest.raises(ValueError, match="declared deterministic order"):
        AutonomousVerificationInput(
            reports=_reports(),
            repair_stages_completed=(RecoveryStage.SECOND_PARSER,),
        )


def test_report_and_direct_decision_reject_evidence_free_passes() -> None:
    with pytest.raises(ValueError, match="requires an evidence finding"):
        AgentReport(agent=VerificationAgent.SOURCE_INTEGRITY, passed=True)
    with pytest.raises(ValueError, match="requires an evidence receipt"):
        AgentReport(
            agent=VerificationAgent.SOURCE_INTEGRITY,
            passed=True,
            findings=(
                AgentFinding(code="source_integrity_verified", level=FindingLevel.INFO),
            ),
        )

    bypassed_reports = tuple(
        AgentReport.model_construct(agent=agent, passed=True, findings=())
        for agent in VerificationAgent
    )
    bypassed_input = AutonomousVerificationInput.model_construct(reports=bypassed_reports)
    with pytest.raises(ValueError, match="requires an evidence finding"):
        decide_autonomously(bypassed_input)
