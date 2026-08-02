from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from akc_parallel_runtime import (
    ArbitrationBasis,
    ArbitrationCandidate,
    Arbitrator,
    ValidationLevel,
    ValidationPolicy,
    ValidatorPipeline,
    VerificationState,
)
from helpers import HASH_A, HASH_B, HASH_C, receipt, valid_observation

ALL_LEVELS = tuple(ValidationLevel)


def policy(**overrides: object) -> ValidationPolicy:
    values: dict[str, object] = {"expected_page_ids": ("p1",)}
    values.update(overrides)
    return ValidationPolicy(**values)  # type: ignore[arg-type]


def candidate(
    attempt_id: str,
    value: str | None,
    *,
    family: str = "family-a",
    hard_gate: bool = True,
    authority: bool | None = None,
    native: bool | None = None,
    specialist: bool = False,
    fingerprint: str | None = "structure-a",
    geometry: bool = False,
    cell_map: bool = False,
    downstream: bool = False,
    prediction_hash: str = HASH_A,
) -> ArbitrationCandidate:
    return ArbitrationCandidate(
        attempt_id=attempt_id,
        prediction_sha256=prediction_hash,
        hard_gate_pass=hard_gate,
        numeric_value=Decimal(value) if value is not None else None,
        structure_fingerprint=fingerprint,
        independent_family=family,
        authority_exact=authority,
        native_exact=native,
        pixel_specialist_exact=specialist,
        source_geometry_exact=geometry,
        table_cell_map_exact=cell_map,
        downstream_consistent=downstream,
        source_coverage=1.0,
        structure_score=0.9,
        cross_model_agreement=0.8,
        runtime_reliability=0.95,
    )


def test_all_required_validator_levels_pass_with_objective_receipts() -> None:
    result = ValidatorPipeline().validate(
        valid_observation(levels=ALL_LEVELS),
        policy(
            native_comparison_required=True,
            authority_required=True,
            differential_required=True,
            multimodal_required=True,
            downstream_required=True,
        ),
    )
    assert result.passed is True
    assert result.hard_failure_count == 0
    assert all(level.passed for level in result.results)


def test_http_200_with_blank_output_is_a_semantic_failure() -> None:
    observation = replace(valid_observation(), block_count=0, output_nonempty=False)
    result = ValidatorPipeline().validate(observation, policy())
    assert result.passed is False
    assert {finding.code for finding in result.findings} >= {"empty_output"}


def test_missing_level_receipt_fails_closed_even_when_flags_are_true() -> None:
    observation = replace(
        valid_observation(),
        evidence=((ValidationLevel.TRANSPORT, (receipt(ValidationLevel.TRANSPORT),)),),
    )
    result = ValidatorPipeline().validate(observation, policy())
    assert result.passed is False
    assert "level_1_evidence_missing" in {finding.code for finding in result.findings}
    assert "level_6_evidence_missing" in {finding.code for finding in result.findings}


def test_authority_required_rejects_dimension_or_numeric_mismatch() -> None:
    observation = replace(
        valid_observation(levels=ALL_LEVELS),
        authority_numeric_exact=False,
        authority_period_unit_account_match=False,
    )
    result = ValidatorPipeline().validate(observation, policy(authority_required=True))
    assert result.passed is False
    codes = {finding.code for finding in result.findings}
    assert {"authority_numeric_mismatch", "authority_dimension_mismatch"} <= codes


def test_native_comparison_required_cannot_be_silently_skipped() -> None:
    observation = replace(
        valid_observation(levels=ALL_LEVELS),
        native_available=False,
        native_text_coverage=None,
        native_numeric_exact=None,
    )
    result = ValidatorPipeline().validate(
        observation, policy(native_comparison_required=True)
    )
    assert result.passed is False
    assert "native_evidence_unavailable" in {finding.code for finding in result.findings}


def test_optional_validator_levels_are_labeled_not_evidence() -> None:
    result = ValidatorPipeline().validate(valid_observation(), policy())
    optional = [item for item in result.results if not item.required]
    assert optional
    assert all(item.passed is False for item in optional)
    assert all(item.reason_codes == ("not_required_not_evidence",) for item in optional)


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("identity_matches", "identity_mismatch"),
        ("checksum_matches", "checksum_mismatch"),
        ("schema_valid", "schema_invalid"),
        ("reading_order_valid", "reading_order_invalid"),
        ("repetition_detected", "repetition_detected"),
        ("retrieval_valid", "retrieval_invalid"),
    ],
)
def test_each_silent_failure_class_is_hard_rejected(field: str, code: str) -> None:
    replacement = field == "repetition_detected"
    result = ValidatorPipeline().validate(
        replace(valid_observation(), **{field: replacement}), policy()
    )
    assert result.passed is False
    assert code in {finding.code for finding in result.findings}


def test_page_order_and_coverage_are_exact_not_set_only() -> None:
    observation = valid_observation(page_ids=("p2", "p1"))
    result = ValidatorPipeline().validate(
        observation, policy(expected_page_ids=("p1", "p2"))
    )
    assert result.passed is False
    assert "page_coverage_mismatch" in {finding.code for finding in result.findings}


def test_validation_digest_is_deterministic() -> None:
    pipeline = ValidatorPipeline()
    observation = valid_observation()
    assert pipeline.validate(observation, policy()).digest == pipeline.validate(
        observation, policy()
    ).digest


def test_authority_exact_beats_three_model_majority() -> None:
    decision = Arbitrator().arbitrate_numeric(
        "cell-1",
        (
            candidate("majority-a", "999", family="a", prediction_hash=HASH_A),
            candidate("majority-b", "999", family="b", prediction_hash=HASH_B),
            candidate("majority-c", "999", family="c", prediction_hash=HASH_C),
            candidate("authority", "100", family="authority", authority=True),
        ),
    )
    assert decision.selected_attempt_id == "authority"
    assert decision.basis is ArbitrationBasis.AUTHORITY_EXACT
    assert decision.verification_state is VerificationState.AUTHORITY_VERIFIED


def test_conflicting_authority_candidates_remain_unresolved_and_unbilled() -> None:
    decision = Arbitrator().arbitrate_numeric(
        "cell-1",
        (
            candidate("a", "100", authority=True),
            candidate("b", "101", family="b", authority=True),
        ),
    )
    assert decision.accepted is False
    assert decision.billable is False
    assert decision.reason_codes == ("authority_conflict",)


def test_high_risk_authority_requirement_cannot_fall_back_to_agreement() -> None:
    decision = Arbitrator().arbitrate_numeric(
        "cell-1",
        (
            candidate("a", "100", family="a"),
            candidate("b", "100", family="b"),
        ),
        authority_required=True,
    )
    assert decision.basis is ArbitrationBasis.UNRESOLVED
    assert decision.reason_codes == ("authority_required_but_unavailable",)


def test_explicit_authority_mismatch_blocks_native_or_model_fallback() -> None:
    decision = Arbitrator().arbitrate_numeric(
        "cell-1",
        (
            candidate("mismatch", "999", authority=False, native=True),
            candidate("agreement", "999", family="b"),
        ),
    )
    assert decision.accepted is False
    assert decision.reason_codes == ("authority_mismatch",)


def test_explicit_native_mismatch_blocks_specialist_fallback() -> None:
    decision = Arbitrator().arbitrate_numeric(
        "cell-1",
        (candidate("mismatch", "999", native=False, specialist=True),),
    )
    assert decision.accepted is False
    assert decision.reason_codes == ("native_source_mismatch",)


def test_native_exact_precedes_specialist_and_independent_agreement() -> None:
    decision = Arbitrator().arbitrate_numeric(
        "cell-1",
        (
            candidate("native", "100", native=True),
            candidate("specialist", "101", family="b", specialist=True),
            candidate("agreement", "101", family="c"),
        ),
    )
    assert decision.selected_attempt_id == "native"
    assert decision.basis is ArbitrationBasis.NATIVE_EXACT


def test_pixel_specialist_precedes_unverified_model_agreement() -> None:
    decision = Arbitrator().arbitrate_numeric(
        "cell-1",
        (
            candidate("specialist", "100", specialist=True),
            candidate("a", "101", family="a"),
            candidate("b", "101", family="b"),
        ),
    )
    assert decision.selected_attempt_id == "specialist"
    assert decision.basis is ArbitrationBasis.PIXEL_SPECIALIST


def test_two_independent_families_can_cross_model_verify() -> None:
    decision = Arbitrator().arbitrate_numeric(
        "cell-1",
        (
            candidate("a", "100", family="a", prediction_hash=HASH_A),
            candidate("b", "100", family="b", prediction_hash=HASH_B),
        ),
    )
    assert decision.accepted is True
    assert decision.basis is ArbitrationBasis.INDEPENDENT_AGREEMENT
    assert decision.verification_state is VerificationState.CROSS_MODEL_VERIFIED


def test_three_votes_from_same_family_are_not_independent_evidence() -> None:
    decision = Arbitrator().arbitrate_numeric(
        "cell-1",
        tuple(candidate(f"a-{index}", "100", family="same") for index in range(3)),
    )
    assert decision.accepted is False
    assert decision.reason_codes == ("independent_agreement_insufficient",)


def test_multiple_independently_supported_values_remain_unresolved() -> None:
    decision = Arbitrator().arbitrate_numeric(
        "cell-1",
        (
            candidate("a1", "100", family="a1"),
            candidate("a2", "100", family="a2"),
            candidate("b1", "101", family="b1"),
            candidate("b2", "101", family="b2"),
        ),
    )
    assert decision.reason_codes == ("independent_values_conflict",)


def test_hard_gate_failures_are_excluded_before_scoring() -> None:
    decision = Arbitrator().arbitrate_numeric(
        "cell-1",
        (
            candidate("bad", "999", hard_gate=False, authority=True),
            candidate("good-a", "100", family="a"),
            candidate("good-b", "100", family="b"),
        ),
    )
    assert decision.selected_attempt_id in {"good-a", "good-b"}
    assert decision.excluded_hard_gate_attempt_ids == ("bad",)


def test_structure_uses_source_geometry_and_detects_conflict() -> None:
    arbitrator = Arbitrator()
    accepted = arbitrator.arbitrate_structure(
        "table-1",
        (
            candidate("a", None, fingerprint="shape-a", geometry=True),
            candidate("b", None, family="b", fingerprint="shape-a", geometry=True),
        ),
    )
    assert accepted.basis is ArbitrationBasis.SOURCE_GEOMETRY
    conflict = arbitrator.arbitrate_structure(
        "table-2",
        (
            candidate("a", None, fingerprint="shape-a", geometry=True),
            candidate("b", None, family="b", fingerprint="shape-b", geometry=True),
        ),
    )
    assert conflict.accepted is False
    assert conflict.reason_codes == ("source_geometry_conflict",)


def test_structure_without_objective_evidence_remains_unresolved() -> None:
    decision = Arbitrator().arbitrate_structure(
        "table-1", (candidate("a", None, fingerprint="shape-a"),)
    )
    assert decision.accepted is False
    assert decision.reason_codes == ("objective_structure_evidence_insufficient",)
