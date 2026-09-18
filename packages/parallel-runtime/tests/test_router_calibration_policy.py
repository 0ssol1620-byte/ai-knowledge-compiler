from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from akc_parallel_runtime.calibrated_router import (
    CalibratedPolicyBindingError,
    CalibratedRoutingPolicyRouter,
    CalibratedScoreRow,
    CalibratedScoreTable,
)
from akc_parallel_runtime.calibration import (
    AbstentionPolicy,
    CalibrationObservation,
    CanaryReceipt,
    Ed25519CanaryReceiptVerifier,
    HmacSha256ReceiptAuthenticator,
    SelectiveAction,
    calibration_metrics,
    evaluate_policy_authority,
    risk_coverage_curve,
    select_risk_threshold,
    selective_decision,
)
from akc_parallel_runtime.evaluation import (
    MeasuredRouteOutcome,
    OutcomeStatus,
    UtilityPolicy,
    allowed_oracle,
    document_performance_map,
    oracle_regret,
    recovery_utility,
)
from akc_parallel_runtime.identity import canonical_sha256, sha256_hex
from akc_parallel_runtime.policy_artifact import (
    CalibratedPolicyArtifact,
    FamilySplitBinding,
    ModelIdentityBinding,
    PolicyArtifactIntegrityError,
    RepeatRunBinding,
)
from akc_parallel_runtime.policy_loader import (
    PolicyBundleLoadError,
    build_scheduler_router_config,
    encode_canary_receipt,
    encode_policy_artifact,
    encode_score_table,
    load_calibrated_policy_bundle_bytes,
    load_calibrated_policy_bundle_paths,
)
from akc_parallel_runtime.routing import (
    QualityEstimate,
    RecipeProfile,
    RouteRequest,
    RouterStage,
    RouteTier,
    RoutingUnavailable,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from helpers import HASH_A, HASH_B, HASH_C, HASH_D, worker

NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)
HASH_E = "e" * 64
HASH_F = "f" * 64
HASH_1 = "1" * 64
HASH_2 = "2" * 64
HASH_3 = "3" * 64
HASH_4 = "4" * 64
HASH_5 = "5" * 64
HASH_6 = "6" * 64


def artifact_values() -> dict[str, object]:
    family_split = FamilySplitBinding(
        train_family_ids=frozenset({"train-a", "train-b", "train-c"}),
        calibration_family_ids=frozenset({"cal-a"}),
        holdout_family_ids=frozenset({"hold-a"}),
    )
    models = (
        ModelIdentityBinding(
            provider="local",
            model_id="document-vlm",
            revision="sha256:model-revision",
            input_mode="page_image",
            settings_sha256=HASH_A,
            capability_receipt_sha256=HASH_B,
        ),
    )
    experiment = {
        "corpus_manifest_sha256": HASH_C,
        "family_split": family_split.as_binding(),
        "prompt_calibration_corpus_sha256": HASH_D,
        "prompt_calibration_family_ids_sha256": canonical_sha256(["prompt-only"]),
        "evaluator_registry_sha256": HASH_E,
        "model_identities": models,
        "price_measurements_sha256": HASH_F,
        "price_evidence_kind": "mixed_actual_receipts",
        "price_measurement_count": 30,
        "prompt_receipt_sha256": HASH_1,
        "hardware_receipt_sha256": HASH_2,
        "hardware_measurement_count": 30,
        "preregistration_sha256": HASH_3,
    }
    experiment_sha = canonical_sha256(experiment)
    runs = tuple(
        RepeatRunBinding(
            run_id=f"run-{index}",
            run_receipt_sha256=receipt_hash,
            result_sha256=result_hash,
            experiment_binding_sha256=experiment_sha,
            completed_at=NOW - timedelta(hours=3) + timedelta(minutes=index),
        )
        for index, (receipt_hash, result_hash) in enumerate(
            ((HASH_A, HASH_D), (HASH_B, HASH_E), (HASH_C, HASH_F)), start=1
        )
    )
    return {
        "policy_version": "router-policy-2026-09-12.1",
        "created_at": NOW - timedelta(hours=2),
        "corpus_manifest_sha256": HASH_C,
        "family_split": family_split,
        "prompt_calibration_corpus_sha256": HASH_D,
        "prompt_calibration_family_ids": frozenset({"prompt-only"}),
        "evaluator_registry_sha256": HASH_E,
        "model_identities": models,
        "price_measurements_sha256": HASH_F,
        "price_evidence_kind": "mixed_actual_receipts",
        "price_measurement_count": 30,
        "prompt_receipt_sha256": HASH_1,
        "hardware_receipt_sha256": HASH_2,
        "hardware_measurement_count": 30,
        "preregistration_sha256": HASH_3,
        "calibration_table_sha256": HASH_4,
        "repeat_runs": runs,
    }


def valid_artifact() -> CalibratedPolicyArtifact:
    return CalibratedPolicyArtifact.create(**artifact_values())


def authenticator() -> HmacSha256ReceiptAuthenticator:
    return HmacSha256ReceiptAuthenticator({"release-reviewer": b"k" * 32})


def valid_receipt(artifact: CalibratedPolicyArtifact) -> CanaryReceipt:
    return CanaryReceipt.create(
        signer=authenticator(),
        policy_artifact_sha256=artifact.artifact_sha256,
        calibration_table_sha256=artifact.calibration_table_sha256,
        cohort_id="low-risk-clean-control-v1",
        eligible=True,
        low_risk_only=True,
        valid_from=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        signer_key_id="release-reviewer",
    )


def outcome(
    case_id: str,
    path_id: str,
    *,
    status: OutcomeStatus = OutcomeStatus.TRUSTED,
    quality: str = "1",
    cost: str = "1",
    failure_code: str | None = None,
    permitted: bool = True,
    catastrophic: bool = False,
) -> MeasuredRouteOutcome:
    return MeasuredRouteOutcome(
        case_id=case_id,
        family_id=f"family-{case_id}",
        path_id=path_id,
        permitted=permitted,
        status=status,
        quality=Decimal(quality),
        actual_cost=Decimal(cost),
        latency_seconds=Decimal("2"),
        catastrophic=catastrophic,
        failure_code=failure_code,
    )


def utility_policy() -> UtilityPolicy:
    return UtilityPolicy(
        quality_reward=Decimal("10"),
        cost_penalty=Decimal("1"),
        latency_penalty=Decimal("0"),
        untrusted_penalty=Decimal("20"),
        catastrophic_penalty=Decimal("100"),
    )


def calibrated_router_fixture() -> tuple[
    CalibratedRoutingPolicyRouter, RecipeProfile, object, QualityEstimate
]:
    artifact, table, recipe, runtime_worker = frozen_bundle_fixture()
    calibrated_estimate = table.rows[0].estimate
    return (
        CalibratedRoutingPolicyRouter(policy_artifact=artifact, score_table=table),
        recipe,
        runtime_worker,
        calibrated_estimate,
    )


def frozen_bundle_fixture() -> tuple[
    CalibratedPolicyArtifact, CalibratedScoreTable, RecipeProfile, object
]:
    values = artifact_values()
    models = values["model_identities"]
    assert isinstance(models, tuple)
    row = CalibratedScoreRow(
        recipe_id="calibrated-recipe",
        worker_id="worker-a",
        model_revision="model@abc123",
        runtime_image_digest="sha256:image-a",
        model_identity_sha256=canonical_sha256(models[0]),
        estimate=QualityEstimate(0.9, 0.9, 0.9, 0.01, 0.01, 0.01, 2, 1),
    )
    table = CalibratedScoreTable.create(
        evaluator_registry_sha256=HASH_E,
        model_identities_sha256=canonical_sha256(models),
        rows=(row,),
    )
    values["calibration_table_sha256"] = table.table_sha256
    artifact = CalibratedPolicyArtifact.create(**values)
    recipe = RecipeProfile(
        recipe_id="calibrated-recipe",
        model_revision="model@abc123",
        runtime_image_digest="sha256:image-a",
        tier=RouteTier.PRECISION,
        capabilities=frozenset({"scan"}),
        supported_languages=frozenset({"ko"}),
        independent_family="document-vlm-family",
    )
    return artifact, table, recipe, worker()


def test_family_holdout_and_prompt_calibration_leakage_are_rejected() -> None:
    with pytest.raises(PolicyArtifactIntegrityError, match="split disjointly"):
        FamilySplitBinding(
            train_family_ids=frozenset({"same"}),
            calibration_family_ids=frozenset({"cal"}),
            holdout_family_ids=frozenset({"same"}),
        )
    values = artifact_values()
    values["prompt_calibration_family_ids"] = frozenset({"hold-a"})
    with pytest.raises(PolicyArtifactIntegrityError, match="overlap"):
        CalibratedPolicyArtifact.create(**values)


def test_artifact_requires_three_distinct_repeat_receipts_with_same_binding() -> None:
    values = artifact_values()
    runs = values["repeat_runs"]
    assert isinstance(runs, tuple)
    values["repeat_runs"] = runs[:2]
    with pytest.raises(PolicyArtifactIntegrityError, match="exactly three"):
        CalibratedPolicyArtifact.create(**values)

    values = artifact_values()
    runs = values["repeat_runs"]
    assert isinstance(runs, tuple)
    values["repeat_runs"] = (runs[0], replace(runs[1], run_id="run-1"), runs[2])
    with pytest.raises(PolicyArtifactIntegrityError, match="ids must be distinct"):
        CalibratedPolicyArtifact.create(**values)

    values = artifact_values()
    runs = values["repeat_runs"]
    assert isinstance(runs, tuple)
    values["repeat_runs"] = (runs[0], replace(runs[1], experiment_binding_sha256=HASH_6), runs[2])
    with pytest.raises(PolicyArtifactIntegrityError, match="binding mismatch"):
        CalibratedPolicyArtifact.create(**values)

    values = artifact_values()
    runs = values["repeat_runs"]
    assert isinstance(runs, tuple)
    values["repeat_runs"] = (
        runs[0],
        runs[1],
        replace(runs[2], completed_at=NOW + timedelta(minutes=1)),
    )
    with pytest.raises(PolicyArtifactIntegrityError, match="after artifact creation"):
        CalibratedPolicyArtifact.create(**values)


def test_artifact_hash_tamper_fails_closed() -> None:
    artifact = replace(valid_artifact(), artifact_sha256=HASH_6)
    with pytest.raises(PolicyArtifactIntegrityError, match="sha256 mismatch"):
        artifact.verify_integrity()
    decision = evaluate_policy_authority(
        requested_mode="shadow",
        policy_artifact=artifact,
        canary_receipt=None,
        verifier=None,
        now=NOW,
        low_risk_cohort=False,
    )
    assert decision.effective_mode == "deterministic"
    assert decision.reason_codes == ("policy_artifact_invalid",)


def test_unmeasured_price_estimate_cannot_become_policy_evidence() -> None:
    values = artifact_values()
    values["price_evidence_kind"] = "projected_estimate"
    with pytest.raises(PolicyArtifactIntegrityError, match="actual usage or runtime"):
        CalibratedPolicyArtifact.create(**values)


def test_calibration_metrics_ece_brier_and_risk_coverage_have_sensible_math() -> None:
    observations = (
        CalibrationObservation("a", "fa", 0.9, True),
        CalibrationObservation("b", "fb", 0.8, True),
        CalibrationObservation("c", "fc", 0.2, False),
        CalibrationObservation("d", "fd", 0.1, False),
    )
    metrics = calibration_metrics(observations, bins=2)
    assert metrics.brier_score == pytest.approx(0.025)
    assert metrics.expected_calibration_error == pytest.approx(0.15)
    curve = risk_coverage_curve(observations)
    assert curve[-1].coverage == 1
    assert curve[-1].empirical_risk == 0.5
    assert all(point.risk_upper_95 >= point.empirical_risk for point in curve)
    selected = select_risk_threshold(
        curve, maximum_risk_upper_95=0.9, minimum_coverage=0.5
    )
    assert selected.coverage == 1
    with pytest.raises(ValueError, match="no measured threshold"):
        select_risk_threshold(
            curve, maximum_risk_upper_95=0.01, minimum_coverage=0.5
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_calibration_rejects_nonfinite_or_out_of_range_probability(value: float) -> None:
    with pytest.raises(ValueError, match="probability"):
        CalibrationObservation("a", "family", value, True)


def test_ood_and_uncertainty_force_abstention() -> None:
    policy = AbstentionPolicy(0.8, 0.2, 0.1)
    ood = selective_decision(
        probability=0.99, uncertainty_radius=0.01, ood_score=0.9, policy=policy
    )
    uncertain = selective_decision(
        probability=0.85, uncertainty_radius=0.2, ood_score=0.1, policy=policy
    )
    assert ood.action is SelectiveAction.ABSTAIN
    assert "ood_abstain" in ood.reason_codes
    assert uncertain.action is SelectiveAction.ABSTAIN
    assert set(uncertain.reason_codes) == {
        "risk_threshold_abstain",
        "uncertainty_abstain",
    }


def test_shadow_needs_valid_artifact_but_no_canary_authority() -> None:
    artifact = valid_artifact()
    decision = evaluate_policy_authority(
        requested_mode="shadow",
        policy_artifact=artifact,
        canary_receipt=None,
        verifier=None,
        now=NOW,
        low_risk_cohort=False,
    )
    assert decision.effective_mode == "shadow"
    assert decision.policy_artifact_sha256 == artifact.artifact_sha256


def test_canary_requires_independent_valid_signature_and_true_low_risk_cohort() -> None:
    artifact = valid_artifact()
    receipt = valid_receipt(artifact)
    accepted = evaluate_policy_authority(
        requested_mode="canary",
        policy_artifact=artifact,
        canary_receipt=receipt,
        verifier=authenticator(),
        now=NOW,
        low_risk_cohort=True,
        expected_cohort_id=receipt.cohort_id,
    )
    assert accepted.effective_mode == "canary"
    denied = evaluate_policy_authority(
        requested_mode="canary",
        policy_artifact=artifact,
        canary_receipt=receipt,
        verifier=authenticator(),
        now=NOW,
        low_risk_cohort=False,
        expected_cohort_id=receipt.cohort_id,
    )
    assert denied.effective_mode == "deterministic"
    assert "canary_scope_not_low_risk" in denied.reason_codes


def test_canary_rejects_signature_tamper_expiry_and_policy_mismatch() -> None:
    artifact = valid_artifact()
    receipt = valid_receipt(artifact)
    invalid_signature = replace(receipt, signature="0" * 64)
    invalid_signature = replace(
        invalid_signature,
        receipt_sha256=canonical_sha256(
            {
                "signed_payload": invalid_signature.signed_payload(),
                "signature": invalid_signature.signature,
            }
        ),
    )
    denied = evaluate_policy_authority(
        requested_mode="canary",
        policy_artifact=artifact,
        canary_receipt=invalid_signature,
        verifier=authenticator(),
        now=NOW,
        low_risk_cohort=True,
        expected_cohort_id=receipt.cohort_id,
    )
    assert "canary_signature_invalid" in denied.reason_codes
    expired = evaluate_policy_authority(
        requested_mode="canary",
        policy_artifact=artifact,
        canary_receipt=receipt,
        verifier=authenticator(),
        now=receipt.expires_at,
        low_risk_cohort=True,
        expected_cohort_id=receipt.cohort_id,
    )
    assert "canary_receipt_expired" in expired.reason_codes
    mismatched = replace(receipt, policy_artifact_sha256=HASH_5)
    mismatched = replace(
        mismatched,
        receipt_sha256=canonical_sha256(
            {"signed_payload": mismatched.signed_payload(), "signature": mismatched.signature}
        ),
    )
    denied = evaluate_policy_authority(
        requested_mode="canary",
        policy_artifact=artifact,
        canary_receipt=mismatched,
        verifier=authenticator(),
        now=NOW,
        low_risk_cohort=True,
        expected_cohort_id=receipt.cohort_id,
    )
    assert {"canary_policy_mismatch", "canary_signature_invalid"}.issubset(
        denied.reason_codes
    )


def test_ed25519_canary_verifier_requires_a_real_signature_from_the_pinned_key() -> None:
    private_key = Ed25519PrivateKey.generate()
    verifier = Ed25519CanaryReceiptVerifier({"canary-key": private_key.public_key()})
    payload = b"content-bound-canary-receipt"
    signature = base64.b64encode(private_key.sign(payload)).decode("ascii")

    assert verifier.verify(payload=payload, signature=signature, key_id="canary-key")
    assert not verifier.verify(
        payload=payload + b"-tampered", signature=signature, key_id="canary-key"
    )
    assert not verifier.verify(payload=payload, signature="not-base64", key_id="canary-key")
    assert not verifier.verify(payload=payload, signature=signature, key_id="unknown-key")


def test_canary_receipt_cannot_authorize_another_or_unnamed_cohort() -> None:
    artifact = valid_artifact()
    receipt = valid_receipt(artifact)
    mismatch = evaluate_policy_authority(
        requested_mode="canary",
        policy_artifact=artifact,
        canary_receipt=receipt,
        verifier=authenticator(),
        now=NOW,
        low_risk_cohort=True,
        expected_cohort_id="different-low-risk-cohort",
    )
    assert mismatch.effective_mode == "deterministic"
    assert "canary_cohort_mismatch" in mismatch.reason_codes
    missing = evaluate_policy_authority(
        requested_mode="canary",
        policy_artifact=artifact,
        canary_receipt=receipt,
        verifier=authenticator(),
        now=NOW,
        low_risk_cohort=True,
    )
    assert missing.effective_mode == "deterministic"
    assert "canary_cohort_identity_missing" in missing.reason_codes


def test_canary_rejects_stale_policy_receipt_and_non_bool_verifier_result() -> None:
    artifact = valid_artifact()
    auth = authenticator()
    stale = CanaryReceipt.create(
        signer=auth,
        policy_artifact_sha256=artifact.artifact_sha256,
        calibration_table_sha256=artifact.calibration_table_sha256,
        cohort_id="low-risk-clean-control-v1",
        eligible=True,
        low_risk_only=True,
        valid_from=artifact.created_at - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        signer_key_id="release-reviewer",
    )
    stale_decision = evaluate_policy_authority(
        requested_mode="canary",
        policy_artifact=artifact,
        canary_receipt=stale,
        verifier=auth,
        now=NOW,
        low_risk_cohort=True,
        expected_cohort_id=stale.cohort_id,
    )
    assert "canary_policy_newer_than_receipt" in stale_decision.reason_codes

    class TruthyButInvalidVerifier:
        def verify(self, **_: object) -> str:
            return "true"

    invalid_verifier = evaluate_policy_authority(
        requested_mode="canary",
        policy_artifact=artifact,
        canary_receipt=valid_receipt(artifact),
        verifier=TruthyButInvalidVerifier(),
        now=NOW,
        low_risk_cohort=True,
        expected_cohort_id="low-risk-clean-control-v1",
    )
    assert "canary_signature_invalid" in invalid_verifier.reason_codes


def test_receipt_rejects_truthy_strings_for_boolean_authority_fields() -> None:
    artifact = valid_artifact()
    with pytest.raises(ValueError, match="must be bools"):
        CanaryReceipt.create(
            signer=authenticator(),
            policy_artifact_sha256=artifact.artifact_sha256,
            calibration_table_sha256=artifact.calibration_table_sha256,
            cohort_id="cohort",
            eligible="true",
            low_risk_only=True,
            valid_from=NOW,
            expires_at=NOW + timedelta(hours=1),
            signer_key_id="release-reviewer",
        )


def test_calibrated_router_ignores_arbitrary_scheduler_estimates() -> None:
    router, recipe, runtime_worker, calibrated_estimate = calibrated_router_fixture()
    arbitrary = QualityEstimate(0.01, 0.01, 0.01, 0.9, 0.9, 0.9, 999, 999)
    decision = router.route(
        RouteRequest(
            stage=RouterStage.PAGE,
            required_capabilities=frozenset({"scan"}),
            language="ko",
            high_risk=False,
            private_processing=False,
            external_api_allowed=False,
        ),
        recipes=(recipe,),
        workers=(runtime_worker,),  # type: ignore[arg-type]
        estimates={(recipe.recipe_id, "worker-a"): arbitrary},
    )
    assert decision.primary.estimate == calibrated_estimate
    assert decision.policy_version == "router-policy-2026-09-12.1"


def test_calibrated_router_rejects_score_table_and_runtime_identity_tamper() -> None:
    router, recipe, runtime_worker, _ = calibrated_router_fixture()
    request = RouteRequest(
        stage=RouterStage.PAGE,
        required_capabilities=frozenset({"scan"}),
        language="ko",
        high_risk=False,
        private_processing=False,
        external_api_allowed=False,
    )
    with pytest.raises(CalibratedPolicyBindingError, match="runtime recipe/worker identity"):
        router.route(
            request,
            recipes=(replace(recipe, model_revision="model@tampered"),),
            workers=(runtime_worker,),  # type: ignore[arg-type]
            estimates={},
        )

    values = artifact_values()
    models = values["model_identities"]
    assert isinstance(models, tuple)
    row = CalibratedScoreRow(
        "r",
        "w",
        "model@abc123",
        "sha256:image-a",
        canonical_sha256(models[0]),
        QualityEstimate(0.9, 0.9, 0.9, 0, 0, 0, 1, 1),
    )
    table = CalibratedScoreTable.create(
        evaluator_registry_sha256=HASH_E,
        model_identities_sha256=canonical_sha256(models),
        rows=(row,),
    )
    values["calibration_table_sha256"] = table.table_sha256
    artifact = CalibratedPolicyArtifact.create(**values)
    with pytest.raises(CalibratedPolicyBindingError, match="score-table sha256"):
        CalibratedRoutingPolicyRouter(
            policy_artifact=artifact,
            score_table=replace(table, table_sha256=HASH_6),
        )


def test_frozen_policy_loader_round_trips_only_hash_pinned_blobs() -> None:
    artifact, table, _, _ = frozen_bundle_fixture()
    policy_blob = encode_policy_artifact(artifact)
    table_blob = encode_score_table(table)
    bundle = load_calibrated_policy_bundle_bytes(
        policy_bytes=policy_blob,
        score_table_bytes=table_blob,
        expected_policy_blob_sha256=sha256_hex(policy_blob),
        expected_score_table_blob_sha256=sha256_hex(table_blob),
    )
    assert bundle.policy_artifact == artifact
    assert bundle.score_table == table
    with pytest.raises(PolicyBundleLoadError, match="downloaded blob sha256 mismatch"):
        load_calibrated_policy_bundle_bytes(
            policy_bytes=policy_blob,
            score_table_bytes=table_blob,
            expected_policy_blob_sha256=HASH_6,
            expected_score_table_blob_sha256=sha256_hex(table_blob),
        )


def test_policy_loader_rejects_schema_and_internal_table_tamper() -> None:
    artifact, table, _, _ = frozen_bundle_fixture()
    policy_blob = encode_policy_artifact(artifact)
    table_payload = json.loads(encode_score_table(table))
    table_payload["unexpected"] = True
    schema_tamper = json.dumps(table_payload).encode()
    with pytest.raises(PolicyBundleLoadError, match="schema fields"):
        load_calibrated_policy_bundle_bytes(
            policy_bytes=policy_blob,
            score_table_bytes=schema_tamper,
            expected_policy_blob_sha256=sha256_hex(policy_blob),
            expected_score_table_blob_sha256=sha256_hex(schema_tamper),
        )

    table_payload.pop("unexpected")
    table_payload["score_table"]["rows"][0]["estimate"]["expected_cost"] = 0
    content_tamper = json.dumps(table_payload).encode()
    with pytest.raises(CalibratedPolicyBindingError, match="score-table sha256"):
        load_calibrated_policy_bundle_bytes(
            policy_bytes=policy_blob,
            score_table_bytes=content_tamper,
            expected_policy_blob_sha256=sha256_hex(policy_blob),
            expected_score_table_blob_sha256=sha256_hex(content_tamper),
        )


def test_rooted_policy_loader_rejects_traversal(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"{}")
    with pytest.raises(PolicyBundleLoadError, match="escapes the trusted root"):
        load_calibrated_policy_bundle_paths(
            trusted_root=trusted,
            policy_relative_path=Path("../outside.json"),
            score_table_relative_path=Path("../outside.json"),
            expected_policy_blob_sha256=sha256_hex(b"{}"),
            expected_score_table_blob_sha256=sha256_hex(b"{}"),
        )


def test_scheduler_config_is_atomic_and_requires_authenticated_cohort() -> None:
    artifact, table, _, _ = frozen_bundle_fixture()
    policy_blob = encode_policy_artifact(artifact)
    table_blob = encode_score_table(table)
    bundle = load_calibrated_policy_bundle_bytes(
        policy_bytes=policy_blob,
        score_table_bytes=table_blob,
        expected_policy_blob_sha256=sha256_hex(policy_blob),
        expected_score_table_blob_sha256=sha256_hex(table_blob),
    )
    receipt = valid_receipt(artifact)
    receipt_blob = encode_canary_receipt(receipt)
    config = build_scheduler_router_config(
        bundle=bundle,
        canary_receipt_bytes=receipt_blob,
        expected_receipt_blob_sha256=sha256_hex(receipt_blob),
        verifier=authenticator(),
        now=NOW,
        expected_cohort_id=receipt.cohort_id,
        low_risk_cohort=True,
        maximum_cost=1.0,
    )
    assert set(config.as_coordinator_kwargs()) == {
        "router_authority_evaluator",
        "router_policy_artifact",
        "router_canary_receipt",
        "router_canary_verifier",
        "routing_authority_router",
    }
    with pytest.raises(PolicyBundleLoadError, match="canary_cohort_mismatch"):
        build_scheduler_router_config(
            bundle=bundle,
            canary_receipt_bytes=receipt_blob,
            expected_receipt_blob_sha256=sha256_hex(receipt_blob),
            verifier=authenticator(),
            now=NOW,
            expected_cohort_id="other-cohort",
            low_risk_cohort=True,
            maximum_cost=1,
        )
    with pytest.raises(PolicyBundleLoadError, match="maximum cost snapshot"):
        build_scheduler_router_config(
            bundle=bundle,
            canary_receipt_bytes=receipt_blob,
            expected_receipt_blob_sha256=sha256_hex(receipt_blob),
            verifier=authenticator(),
            now=NOW,
            expected_cohort_id=receipt.cohort_id,
            low_risk_cohort=True,
            maximum_cost=None,
        )


def test_bound_policy_enforces_external_permission_and_maximum_cost() -> None:
    artifact, table, recipe, runtime_worker = frozen_bundle_fixture()
    request = RouteRequest(
        stage=RouterStage.PAGE,
        required_capabilities=frozenset({"scan"}),
        language="ko",
        high_risk=False,
        private_processing=False,
        external_api_allowed=False,
    )
    external_router = CalibratedRoutingPolicyRouter(
        policy_artifact=artifact,
        score_table=table,
    )
    with pytest.raises(RoutingUnavailable):
        external_router.route(
            request,
            recipes=(replace(recipe, external_provider=True),),
            workers=(runtime_worker,),  # type: ignore[arg-type]
            estimates={},
        )
    cost_limited = CalibratedRoutingPolicyRouter(
        policy_artifact=artifact,
        score_table=table,
        maximum_cost=0.5,
    )
    with pytest.raises(RoutingUnavailable):
        cost_limited.route(
            replace(request, external_api_allowed=True),
            recipes=(recipe,),
            workers=(runtime_worker,),  # type: ignore[arg-type]
            estimates={},
        )


def test_measured_rows_require_cost_and_complete_failure_accounting() -> None:
    with pytest.raises(ValueError, match="actual_cost"):
        replace(outcome("a", "p"), actual_cost=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="failure code"):
        outcome("a", "p", status=OutcomeStatus.PROVIDER_FAILURE)
    with pytest.raises(ValueError, match="finite"):
        replace(outcome("a", "p"), actual_cost=Decimal("NaN"))


def test_dpm_accounts_for_each_failure_class_without_hiding_failures() -> None:
    rows = (
        outcome("a", "p"),
        outcome(
            "b",
            "p",
            status=OutcomeStatus.SEMANTIC_FAILURE,
            quality="0",
            failure_code="wrong_table",
        ),
        outcome(
            "c",
            "p",
            status=OutcomeStatus.PROVIDER_FAILURE,
            quality="0",
            failure_code="http_503",
        ),
        outcome(
            "d",
            "p",
            status=OutcomeStatus.OPERATIONAL_FAILURE,
            quality="0",
            failure_code="worker_oom",
        ),
    )
    summary = document_performance_map(rows)[0]
    assert summary.sample_count == 4
    assert summary.trusted_count == 1
    assert summary.semantic_failure_count == 1
    assert summary.provider_failure_count == 1
    assert summary.operational_failure_count == 1


def test_allowed_oracle_excludes_forbidden_path_and_regret_uses_measured_rows() -> None:
    rows = (
        outcome("a", "cheap", quality="0.9", cost="1"),
        outcome("a", "frontier", quality="1", cost="3"),
        outcome("a", "forbidden", quality="1", cost="0", permitted=False),
    )
    policy = utility_policy()
    oracle = allowed_oracle(rows, policy=policy)
    assert oracle[0].path_id == "cheap"
    regret = oracle_regret(rows, selected_paths={"a": "frontier"}, policy=policy)
    assert regret[0].regret == Decimal("1.0")


def test_recovery_utility_uses_actual_failure_denominator_and_cost() -> None:
    base = (
        outcome(
            "a", "base", status=OutcomeStatus.SEMANTIC_FAILURE, quality="0", failure_code="bad"
        ),
        outcome(
            "b", "base", status=OutcomeStatus.OPERATIONAL_FAILURE, quality="0", failure_code="oom"
        ),
        outcome("c", "base"),
    )
    recovery = (
        outcome("a", "recovery", cost="4"),
        outcome(
            "b",
            "recovery",
            status=OutcomeStatus.UNTRUSTED,
            quality="0.5",
            cost="2",
            failure_code="still_untrusted",
        ),
    )
    result = recovery_utility(base_rows=base, recovery_rows=recovery)
    assert result.base_failure_count == 2
    assert result.incrementally_recovered_count == 1
    assert result.incremental_recovery_yield == Decimal("0.5")
    assert result.incremental_cost == Decimal("6")
    assert result.cost_per_incremental_recovery == Decimal("6")
