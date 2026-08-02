"""Frozen golden-corpus evaluation for FOLYNTA control-plane algorithms.

These fixtures measure deterministic decision contracts. They are deliberately
reported separately from public parser benchmarks and private holdout accuracy.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from akc_parallel_runtime import (
    AttemptKind,
    CreditLedger,
    DiagnosisState,
    FailureObservation,
    PreprocessingVariant,
    RecoveryPlanner,
    RecoveryScope,
    RegionLevel,
    VerificationState,
    diagnose_failure,
)
from akc_quality import text_anomalies
from akc_router import (
    DataPolicy,
    EscalationAction,
    FeatureFlags,
    PageMetrics,
    PageTechnicalClass,
    ProcessingMode,
    QualitySignal,
    RiskTier,
    Route,
    RouterContext,
    classify_page,
    decide_escalation,
    select_first_route,
)

_NOW = datetime(2026, 8, 2, tzinfo=UTC)


def _page(**overrides: object) -> PageMetrics:
    values: dict[str, object] = {
        "page_index0": 0,
        "width": 1000,
        "height": 1400,
        "native_text_chars": 0,
        "native_word_count": 0,
        "native_block_count": 0,
        "native_text_coverage": 0.0,
        "image_coverage": 0.2,
        "invalid_unicode_ratio": 0.0,
        "replacement_char_ratio": 0.0,
        "whitespace_anomaly_score": 0.0,
        "native_reading_order_score": 0.0,
        "font_size_p10": None,
        "estimated_columns": 1,
        "table_density": 0.0,
        "formula_density": 0.0,
        "chart_probability": 0.0,
        "handwriting_probability": 0.0,
        "rotation_degrees": 0,
        "skew_degrees": 0.0,
        "blur_score": 0.0,
        "contrast_score": 1.0,
        "small_text_score": 0.0,
        "script_distribution": {"Hangul": 1.0},
        "suspected_prompt_injection": False,
    }
    values.update(overrides)
    return PageMetrics.model_validate(values)


def _classification() -> dict[str, Any]:
    native = {
        "native_text_chars": 500,
        "native_word_count": 100,
        "native_block_count": 10,
        "native_text_coverage": 0.2,
        "native_reading_order_score": 0.9,
        "image_coverage": 0.1,
    }
    fixtures = (
        ("handwritten", {"handwriting_probability": 0.6}, PageTechnicalClass.HANDWRITTEN),
        ("rotated", {"rotation_degrees": 90}, PageTechnicalClass.ROTATED_OR_WARPED),
        ("table", {"table_density": 0.2}, PageTechnicalClass.TABLE_HEAVY),
        ("formula", {"formula_density": 0.05}, PageTechnicalClass.FORMULA_HEAVY),
        ("chart", {"chart_probability": 0.5}, PageTechnicalClass.CHART_HEAVY),
        ("photo", {"image_coverage": 0.95}, PageTechnicalClass.PHOTO_DOCUMENT),
        ("native_clean", native, PageTechnicalClass.NATIVE_CLEAN),
        (
            "native_complex",
            {**native, "native_text_chars": 100, "estimated_columns": 2},
            PageTechnicalClass.NATIVE_COMPLEX,
        ),
        ("mixed", {"native_text_chars": 50, "image_coverage": 0.3}, PageTechnicalClass.MIXED),
        ("scan_text", {"image_coverage": 0.8}, PageTechnicalClass.SCAN_TEXT),
        (
            "scan_complex",
            {
                "image_coverage": 0.8,
                "blur_score": 1.0,
                "small_text_score": 1.0,
                "skew_degrees": 2.9,
                "formula_density": 0.04,
                "chart_probability": 0.49,
                "script_distribution": {"Hangul": 0.5, "Latin": 0.5},
            },
            PageTechnicalClass.SCAN_COMPLEX,
        ),
        ("unknown", {}, PageTechnicalClass.UNKNOWN),
    )
    outcomes = [
        {
            "fixture": name,
            "expected": expected.value,
            "actual": classify_page(_page(**features)).value,
        }
        for name, features, expected in fixtures
    ]
    correct = sum(row["expected"] == row["actual"] for row in outcomes)
    return {
        "fixtures": len(outcomes),
        "correct": correct,
        "accuracy": correct / len(outcomes),
        "outcomes": outcomes,
    }


def _quality_detection() -> dict[str, Any]:
    fixtures = (
        ("healthy", "Unique evidence sentence with 123 and source lineage.", None, set()),
        ("empty", "", None, {"text.empty"}),
        ("replacement", "valid text" + "�" * 2, None, {"text.replacement_characters"}),
        ("control", "valid\x01text", None, {"text.control_characters"}),
        ("repetition", "abcdefgh" * 20, None, {"text.repetition"}),
        ("length", "short output", 1000, {"text.length_anomaly"}),
    )
    true_positive = false_positive = false_negative = 0
    outcomes = []
    for name, text, reference_length, expected in fixtures:
        actual = {
            finding.code
            for finding in text_anomalies(text, reference_length=reference_length)
        }
        true_positive += len(expected & actual)
        false_positive += len(actual - expected)
        false_negative += len(expected - actual)
        outcomes.append(
            {"fixture": name, "expected": sorted(expected), "actual": sorted(actual)}
        )
    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    return {
        "fixtures": len(outcomes),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / max(precision + recall, 1e-12),
        "outcomes": outcomes,
    }


def _failure_diagnosis() -> dict[str, Any]:
    fixtures: list[tuple[str, FailureObservation, DiagnosisState]] = [
        ("healthy", FailureObservation(200, True, frozenset()), DiagnosisState.HEALTHY),
        (
            "unknown_fail_closed",
            FailureObservation(200, True, frozenset({"novel_corruption"})),
            DiagnosisState.SEMANTIC_FAILED,
        ),
    ]
    for code in (
        "container_crash",
        "oom",
        "health_503",
        "connection_timeout",
        "cuda_error",
        "model_checksum_mismatch",
        "model_identity_mismatch",
        "disk_cache_error",
        "malformed_protocol",
        "dependency_import_failure",
    ):
        fixtures.append(
            (
                code,
                FailureObservation(200, True, frozenset({code})),
                DiagnosisState.INFRASTRUCTURE_FAILED,
            )
        )
    for code in (
        "numeric_mutation",
        "row_omission",
        "repetition",
        "blank_page",
        "table_column_shift",
        "caption_omission",
        "reading_order_error",
        "source_coverage_incomplete",
        "hallucinated_row",
        "false_verified",
        "false_bbox",
        "truncated_output",
    ):
        fixtures.append(
            (code, FailureObservation(200, True, frozenset({code})), DiagnosisState.SEMANTIC_FAILED)
        )
    outcomes = [
        {
            "fixture": name,
            "expected": expected.value,
            "actual": diagnose_failure(observation).state.value,
        }
        for name, observation, expected in fixtures
    ]
    correct = sum(row["expected"] == row["actual"] for row in outcomes)
    return {
        "fixtures": len(outcomes),
        "correct": correct,
        "accuracy": correct / len(outcomes),
        "outcomes": outcomes,
    }


def _recovery_selection() -> dict[str, Any]:
    fixtures = (
        ("authority_numeric_mismatch", RegionLevel.REGION, PreprocessingVariant.AUTHORITY_MAPPING),
        ("numeric_character_ambiguity", RegionLevel.REGION, PreprocessingVariant.OCR_EXACT),
        ("cropped_region", RegionLevel.REGION, PreprocessingVariant.CROP_MARGIN),
        ("rotation_detected", RegionLevel.REGION, PreprocessingVariant.ROTATE),
        ("photographed_low_quality", RegionLevel.REGION, PreprocessingVariant.DEWARP),
        ("row_omission", RegionLevel.TABLE, PreprocessingVariant.CELL_GEOMETRY),
        ("unknown", RegionLevel.REGION, PreprocessingVariant.OVERLAPPING_TILE),
    )
    outcomes = []
    for failure, level, expected in fixtures:
        scope = RecoveryScope(level, f"scope-{failure}", (f"source://{failure}",))
        actual = RecoveryPlanner.choose_variant(frozenset({failure}), scope)
        outcomes.append(
            {"fixture": failure, "expected": expected.value, "actual": actual.value}
        )
    correct = sum(row["expected"] == row["actual"] for row in outcomes)
    minimum_scope = RecoveryPlanner.smallest_scope(
        (
            RecoveryScope(RegionLevel.PAGE, "page", ("source://page",)),
            RecoveryScope(RegionLevel.ROW, "row", ("source://row",)),
            RecoveryScope(RegionLevel.CELL, "cell", ("source://cell",)),
        )
    )
    return {
        "fixtures": len(outcomes),
        "correct": correct,
        "selection_accuracy": correct / len(outcomes),
        "minimum_scope_selected": minimum_scope.level.value,
        "outcomes": outcomes,
    }


def _routing() -> dict[str, Any]:
    ready = frozenset({Route.NATIVE, Route.PADDLE_VL, Route.HPD_FAST, Route.MISTRAL_FALLBACK})
    native = _page(
        native_text_chars=500,
        native_word_count=100,
        native_block_count=10,
        native_text_coverage=0.2,
        native_reading_order_score=0.9,
        image_coverage=0.1,
    )
    decisions: list[tuple[str, str, str]] = []
    native_route = select_first_route(RouterContext(ready_routes=ready), native).route.value
    scan_route = select_first_route(
        RouterContext(ready_routes=ready),
        _page(image_coverage=0.8),
    ).route.value
    decisions.append(("native", Route.NATIVE.value, native_route))
    decisions.append(("scan", Route.PADDLE_VL.value, scan_route))
    decisions.append(
        (
            "speed_hpd",
            Route.HPD_FAST.value,
            select_first_route(
                RouterContext(
                    mode=ProcessingMode.SPEED,
                    dominant_language="en",
                    feature_flags=FeatureFlags(hpd_enabled=True),
                    ready_routes=ready,
                ),
                _page(image_coverage=0.8),
            ).route.value,
        )
    )
    decisions.append(
        (
            "unready",
            Route.UNRESOLVED.value,
            select_first_route(
                RouterContext(ready_routes=frozenset({Route.NATIVE})),
                _page(image_coverage=0.8),
            ).route.value,
        )
    )
    escalation_fixtures = (
        (
            "numeric_unresolved",
            QualitySignal(critical_numeric_mismatch=True),
            RouterContext(risk_tier=RiskTier.HIGH, ready_routes=ready),
            1,
            2,
            EscalationAction.UNRESOLVED,
        ),
        (
            "numeric_authority",
            QualitySignal(critical_numeric_mismatch=True),
            RouterContext(
                risk_tier=RiskTier.HIGH,
                feature_flags=FeatureFlags(authority_verification_enabled=True),
                ready_routes=ready,
            ),
            1,
            2,
            EscalationAction.VERIFY_AUTHORITY,
        ),
        (
            "retry",
            QualitySignal(provider_failure=True),
            RouterContext(ready_routes=ready),
            1,
            2,
            EscalationAction.RETRY,
        ),
        (
            "external_consent",
            QualitySignal(provider_failure=True),
            RouterContext(
                feature_flags=FeatureFlags(external_fallback_enabled=True),
                data_policy=DataPolicy(external_api_allowed=True),
                ready_routes=ready,
            ),
            2,
            2,
            EscalationAction.ESCALATE,
        ),
        (
            "security",
            QualitySignal(security_quarantine_required=True),
            RouterContext(ready_routes=ready),
            1,
            2,
            EscalationAction.QUARANTINE,
        ),
        (
            "accept",
            QualitySignal(passed=True, score=0.95),
            RouterContext(ready_routes=ready),
            1,
            2,
            EscalationAction.ACCEPT,
        ),
    )
    for name, signal, context, attempt, maximum, expected in escalation_fixtures:
        actual = decide_escalation(
            current_route=Route.PADDLE_VL,
            signal=signal,
            attempt_number=attempt,
            max_attempts=maximum,
            context=context,
        ).action
        decisions.append((name, expected.value, actual.value))
    outcomes = [
        {"fixture": name, "expected": expected, "actual": actual}
        for name, expected, actual in decisions
    ]
    correct = sum(row["expected"] == row["actual"] for row in outcomes)
    return {
        "fixtures": len(outcomes),
        "correct": correct,
        "decision_accuracy": correct / len(outcomes),
        "outcomes": outcomes,
    }


def _credits() -> dict[str, Any]:
    ledger = CreditLedger()
    reservation = ledger.reserve(
        account_id="account",
        job_id="job",
        amount=Decimal("10"),
        occurred_at=_NOW,
        idempotency_key="reserve",
    )
    rejected = ledger.settle_work(
        reservation_id=reservation.reservation_id,
        work_key="page-rejected",
        attempt_id="attempt-rejected",
        attempt_kind=AttemptKind.PRIMARY,
        verification_state=VerificationState.FAILED,
        canonical_credits=Decimal("2"),
        occurred_at=_NOW,
        idempotency_key="rejected",
    )
    winner = ledger.settle_work(
        reservation_id=reservation.reservation_id,
        work_key="page-1",
        attempt_id="winner",
        attempt_kind=AttemptKind.RETRY,
        verification_state=VerificationState.AUTO_REPAIRED,
        canonical_credits=Decimal("2"),
        occurred_at=_NOW,
        idempotency_key="winner",
    )
    duplicates = [
        ledger.settle_work(
            reservation_id=reservation.reservation_id,
            work_key="page-1",
            attempt_id=f"hedge-{index}",
            attempt_kind=AttemptKind.HEDGE,
            verification_state=VerificationState.VERIFIED,
            canonical_credits=Decimal("2"),
            occurred_at=_NOW,
            idempotency_key=f"hedge-{index}",
        )
        for index in range(32)
    ]
    second = ledger.settle_work(
        reservation_id=reservation.reservation_id,
        work_key="page-2",
        attempt_id="primary-2",
        attempt_kind=AttemptKind.PRIMARY,
        verification_state=VerificationState.VERIFIED,
        canonical_credits=Decimal("3"),
        occurred_at=_NOW,
        idempotency_key="primary-2",
    )
    release = ledger.release_remaining(
        reservation_id=reservation.reservation_id,
        occurred_at=_NOW,
        idempotency_key="release",
    )
    consumed, released, available = ledger.balance(reservation.reservation_id)
    duplicate_charge = sum(result.user_credits_charged for result in duplicates)
    invariant = (
        rejected.user_credits_charged == 0
        and winner.user_credits_charged == Decimal("2.000000")
        and second.user_credits_charged == Decimal("3.000000")
        and duplicate_charge == 0
        and consumed == Decimal("5.000000")
        and released == release.amount == Decimal("5.000000")
        and available == 0
    )
    return {
        "logical_work_items": 3,
        "duplicate_attempts": len(duplicates),
        "duplicate_charge_credits": str(duplicate_charge),
        "rejected_charge_credits": str(rejected.user_credits_charged),
        "consumed_credits": str(consumed),
        "released_credits": str(released),
        "available_credits": str(available),
        "conservation_invariant": invariant,
    }


def evaluate() -> dict[str, Any]:
    source_paths = (
        Path("packages/router/src/akc_router/preflight.py"),
        Path("packages/router/src/akc_router/engine.py"),
        Path("packages/quality/src/akc_quality/anomalies.py"),
        Path("packages/parallel-runtime/src/akc_parallel_runtime/failures.py"),
        Path("packages/parallel-runtime/src/akc_parallel_runtime/recovery.py"),
        Path("packages/parallel-runtime/src/akc_parallel_runtime/credits.py"),
    )
    source_hashes = {
        path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths
    }
    metrics = {
        "page_classification": _classification(),
        "quality_anomaly_detection": _quality_detection(),
        "failure_diagnosis": _failure_diagnosis(),
        "recovery_selection": _recovery_selection(),
        "routing_and_escalation": _routing(),
        "credit_accounting": _credits(),
    }
    all_pass = (
        metrics["page_classification"]["accuracy"] == 1.0
        and metrics["quality_anomaly_detection"]["f1"] == 1.0
        and metrics["failure_diagnosis"]["accuracy"] == 1.0
        and metrics["recovery_selection"]["selection_accuracy"] == 1.0
        and metrics["routing_and_escalation"]["decision_accuracy"] == 1.0
        and metrics["credit_accounting"]["conservation_invariant"] is True
    )
    return {
        "schema": "folynta.system-algorithm-golden-evaluation.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus_type": "frozen_golden_contract_fixtures",
        "source_hashes": source_hashes,
        "metrics": metrics,
        "gate": "PASS" if all_pass else "FAIL",
        "claim_boundary": (
            "PASS proves deterministic golden-contract behavior only; it does not prove "
            "real-distribution or private-holdout accuracy."
        ),
    }


def write_report(output: Path) -> dict[str, Any]:
    report = evaluate()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = ["evaluate", "write_report"]
