from __future__ import annotations

from confirmatory_execution import ArmOutput
from confirmatory_statistics import (
    EvaluationAnchor,
    HiddenPageTruth,
    build_primary_analysis,
    evaluate_output,
    holm_adjust,
    mcnemar_exact,
)
from recovery_protocol import Arm


def output(arm: Arm, page: str, text: str | None, *, escalated: bool = False) -> ArmOutput:
    return ArmOutput(
        arm=arm,
        page_id=page,
        status="ACCEPTED" if text is not None else "UNRESOLVED",
        accepted_text=text,
        escalated_to_strong=escalated,
        strong_invocations=1 if escalated else 0,
        gpu_seconds=6.0 if escalated else 1.0,
        external_cost_usd=0.06 if escalated else 0.01,
        reason="fixture",
        runtime_visible_evidence={"evaluation_truth_visible": False},
    )


def truth(page: str, value: str, family: str = "doc-a") -> HiddenPageTruth:
    return HiddenPageTruth(
        page_id=page,
        document_family=family,
        anchors=(EvaluationAnchor(anchor_id=f"{page}-a", expected_text=value),),
    )


def test_hidden_evaluation_marks_accepted_wrong_output_as_silent_error():
    row = evaluate_output(output(Arm.PRIMARY_ONLY, "p1", "Revenue 100"), truth("p1", "Revenue 900"))
    assert row.accepted
    assert row.accepted_silent_critical_error
    assert row.critical_exact == 0


def test_hidden_evaluation_never_credits_unresolved_as_correct():
    row = evaluate_output(output(Arm.TAVONEL_EVIDENCE_RECOVERY, "p1", None), truth("p1", "900"))
    assert row.unresolved
    assert not row.accepted_silent_critical_error
    assert row.critical_exact == 0


def test_mcnemar_exact_is_paired_on_page_identity():
    left = [
        evaluate_output(output(Arm.PRIMARY_ONLY, "p1", "A"), truth("p1", "B")),
        evaluate_output(output(Arm.PRIMARY_ONLY, "p2", "B"), truth("p2", "B")),
    ]
    right = [
        evaluate_output(output(Arm.TAVONEL_EVIDENCE_RECOVERY, "p1", "B"), truth("p1", "B")),
        evaluate_output(output(Arm.TAVONEL_EVIDENCE_RECOVERY, "p2", "B"), truth("p2", "B")),
    ]
    result = mcnemar_exact(left, right)
    assert result["right_only_correct"] == 1
    assert result["left_only_correct"] == 0
    assert result["effect_difference_in_page_correctness"] == 0.5


def test_holm_adjustment_is_monotone_and_bounded():
    result = holm_adjust({"a": 0.01, "b": 0.04, "c": 0.2})
    assert 0 <= result["a"] <= result["b"] <= result["c"] <= 1


def test_full_primary_analysis_requires_and_compares_all_five_arms():
    rows = []
    arms = (
        Arm.PRIMARY_ONLY,
        Arm.ALWAYS_STRONG,
        Arm.PREDICTION_ONLY,
        Arm.DISAGREEMENT_ONLY,
        Arm.TAVONEL_EVIDENCE_RECOVERY,
    )
    for page_index in range(1, 7):
        page = f"p{page_index}"
        family = f"doc-{(page_index - 1) // 2}"
        page_truth = truth(page, "TARGET", family)
        for arm in arms:
            if arm is Arm.PRIMARY_ONLY and page_index in {1, 2}:
                text = "WRONG"
            elif arm is Arm.TAVONEL_EVIDENCE_RECOVERY and page_index == 2:
                text = None
            else:
                text = "TARGET"
            rows.append(
                evaluate_output(
                    output(
                        arm,
                        page,
                        text,
                        escalated=arm in {Arm.ALWAYS_STRONG, Arm.TAVONEL_EVIDENCE_RECOVERY},
                    ),
                    page_truth,
                )
            )
    result = build_primary_analysis(rows)
    assert len(result["summaries"]) == 5
    assert result["oracle_in_primary_analysis"] is False
    assert len(result["paired_comparisons"]) == 4
    assert result["analysis_digest"].startswith("sha256:")
