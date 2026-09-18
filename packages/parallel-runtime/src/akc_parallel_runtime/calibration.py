"""Calibration metrics, abstention, and fail-closed router policy authority."""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, cast, final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .identity import canonical_json, canonical_sha256, require_sha256
from .policy_artifact import CalibratedPolicyArtifact, PolicyArtifactIntegrityError

RouterMode = Literal["deterministic", "shadow", "canary"]


def _is_bool(value: object) -> bool:
    return type(value) is bool


def _strict_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a sha256 string")
    return require_sha256(value, field_name=field_name)


@dataclass(frozen=True, slots=True)
class CalibrationObservation:
    case_id: str
    family_id: str
    probability: float
    outcome: bool

    def __post_init__(self) -> None:
        if not self.case_id or not self.family_id:
            raise ValueError("case_id and family_id are required")
        if not _is_bool(self.outcome):
            raise ValueError("outcome must be a bool")
        if not math.isfinite(self.probability) or not 0 <= self.probability <= 1:
            raise ValueError("probability must be finite and between zero and one")


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    lower: float
    upper: float
    count: int
    mean_probability: float
    outcome_rate: float


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    sample_count: int
    expected_calibration_error: float
    brier_score: float
    reliability: tuple[ReliabilityBin, ...]


@dataclass(frozen=True, slots=True)
class RiskCoveragePoint:
    threshold: float
    coverage: float
    empirical_risk: float
    risk_upper_95: float


@dataclass(frozen=True, slots=True)
class ThresholdSelection:
    threshold: float
    coverage: float
    risk_upper_95: float


def calibration_metrics(
    observations: tuple[CalibrationObservation, ...], *, bins: int = 10
) -> CalibrationMetrics:
    if not observations:
        raise ValueError("calibration observations are required")
    if bins < 2:
        raise ValueError("at least two reliability bins are required")
    if len({item.case_id for item in observations}) != len(observations):
        raise ValueError("calibration case ids must be unique")
    grouped: list[list[CalibrationObservation]] = [[] for _ in range(bins)]
    for item in observations:
        index = min(int(item.probability * bins), bins - 1)
        grouped[index].append(item)
    reliability: list[ReliabilityBin] = []
    ece = 0.0
    brier = sum((item.probability - float(item.outcome)) ** 2 for item in observations) / len(
        observations
    )
    for index, group in enumerate(grouped):
        if not group:
            continue
        mean_probability = sum(item.probability for item in group) / len(group)
        outcome_rate = sum(item.outcome for item in group) / len(group)
        ece += len(group) / len(observations) * abs(mean_probability - outcome_rate)
        reliability.append(
            ReliabilityBin(
                lower=index / bins,
                upper=(index + 1) / bins,
                count=len(group),
                mean_probability=mean_probability,
                outcome_rate=outcome_rate,
            )
        )
    return CalibrationMetrics(len(observations), ece, brier, tuple(reliability))


def _wilson_upper(failures: int, total: int, z: float = 1.959963984540054) -> float:
    rate = failures / total
    denominator = 1 + z * z / total
    centre = rate + z * z / (2 * total)
    radius = z * math.sqrt((rate * (1 - rate) + z * z / (4 * total)) / total)
    return min(1.0, (centre + radius) / denominator)


def risk_coverage_curve(
    observations: tuple[CalibrationObservation, ...],
) -> tuple[RiskCoveragePoint, ...]:
    if not observations:
        raise ValueError("calibration observations are required")
    ordered = sorted(observations, key=lambda item: (-item.probability, item.case_id))
    points: list[RiskCoveragePoint] = []
    failures = 0
    for index, item in enumerate(ordered, start=1):
        failures += int(not item.outcome)
        if index < len(ordered) and ordered[index].probability == item.probability:
            continue
        points.append(
            RiskCoveragePoint(
                threshold=item.probability,
                coverage=index / len(ordered),
                empirical_risk=failures / index,
                risk_upper_95=_wilson_upper(failures, index),
            )
        )
    return tuple(points)


def select_risk_threshold(
    curve: tuple[RiskCoveragePoint, ...],
    *,
    maximum_risk_upper_95: float,
    minimum_coverage: float,
) -> ThresholdSelection:
    for value in (maximum_risk_upper_95, minimum_coverage):
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("risk and coverage limits must be finite and between zero and one")
    eligible = tuple(
        point
        for point in curve
        if point.risk_upper_95 <= maximum_risk_upper_95
        and point.coverage >= minimum_coverage
    )
    if not eligible:
        raise ValueError("no measured threshold satisfies the risk and coverage constraints")
    selected = max(eligible, key=lambda point: (point.coverage, -point.threshold))
    return ThresholdSelection(
        threshold=selected.threshold,
        coverage=selected.coverage,
        risk_upper_95=selected.risk_upper_95,
    )


class SelectiveAction(StrEnum):
    ROUTE = "route"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class AbstentionPolicy:
    minimum_probability: float
    maximum_ood_score: float
    maximum_uncertainty_radius: float

    def __post_init__(self) -> None:
        values = (
            self.minimum_probability,
            self.maximum_ood_score,
            self.maximum_uncertainty_radius,
        )
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
            raise ValueError("abstention thresholds must be finite and between zero and one")


@dataclass(frozen=True, slots=True)
class SelectiveDecision:
    action: SelectiveAction
    reason_codes: tuple[str, ...]


def selective_decision(
    *, probability: float, uncertainty_radius: float, ood_score: float, policy: AbstentionPolicy
) -> SelectiveDecision:
    values = (probability, uncertainty_radius, ood_score)
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
        raise ValueError("score inputs must be finite and between zero and one")
    reasons: list[str] = []
    if ood_score > policy.maximum_ood_score:
        reasons.append("ood_abstain")
    if uncertainty_radius > policy.maximum_uncertainty_radius:
        reasons.append("uncertainty_abstain")
    if probability - uncertainty_radius < policy.minimum_probability:
        reasons.append("risk_threshold_abstain")
    return SelectiveDecision(
        SelectiveAction.ABSTAIN if reasons else SelectiveAction.ROUTE,
        tuple(sorted(reasons)),
    )


class ReceiptVerifier(Protocol):
    def verify(self, *, payload: bytes, signature: str, key_id: str) -> bool: ...


class ReceiptSigner(Protocol):
    def sign(self, *, payload: bytes, key_id: str) -> str: ...


class HmacSha256ReceiptAuthenticator:
    """Small trust-store primitive; the scheduler must own the trusted keys."""

    def __init__(self, trusted_keys: Mapping[str, bytes]) -> None:
        if (
            not trusted_keys
            or any(
                not isinstance(key_id, str)
                or not key_id.strip()
                or not isinstance(key, bytes)
                or len(key) < 32
                for key_id, key in trusted_keys.items()
            )
        ):
            raise ValueError("trusted receipt keys must contain at least 32 bytes")
        self._trusted_keys = dict(trusted_keys)

    def sign(self, *, payload: bytes, key_id: str) -> str:
        key = self._trusted_keys.get(key_id)
        if key is None:
            raise ValueError("unknown receipt signing key")
        return hmac.new(key, payload, hashlib.sha256).hexdigest()

    def verify(self, *, payload: bytes, signature: str, key_id: str) -> bool:
        key = self._trusted_keys.get(key_id)
        if key is None:
            return False
        expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)


@final
class Ed25519CanaryReceiptVerifier:
    """Production verifier backed only by explicitly pinned Ed25519 public keys."""

    __slots__ = ("_trusted_keys",)

    def __init__(self, trusted_keys: Mapping[str, Ed25519PublicKey]) -> None:
        if not trusted_keys or any(
            not isinstance(key_id, str)
            or not key_id.strip()
            or not isinstance(key, Ed25519PublicKey)
            for key_id, key in trusted_keys.items()
        ):
            raise ValueError("trusted canary keys must be named Ed25519 public keys")
        self._trusted_keys = dict(trusted_keys)

    def verify(self, *, payload: bytes, signature: str, key_id: str) -> bool:
        public_key = self._trusted_keys.get(key_id)
        if public_key is None or not isinstance(signature, str):
            return False
        try:
            signature_bytes = base64.b64decode(signature, validate=True)
            public_key.verify(signature_bytes, payload)
        except (InvalidSignature, TypeError, ValueError):
            return False
        return True


@dataclass(frozen=True, slots=True)
class CanaryReceipt:
    policy_artifact_sha256: str
    calibration_table_sha256: str
    cohort_id: str
    eligible: bool
    low_risk_only: bool
    valid_from: datetime
    expires_at: datetime
    signer_key_id: str
    signature: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        _strict_sha256(self.policy_artifact_sha256, "policy_artifact_sha256")
        _strict_sha256(self.calibration_table_sha256, "calibration_table_sha256")
        _strict_sha256(self.receipt_sha256, "receipt_sha256")
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.cohort_id, self.signer_key_id, self.signature)
        ):
            raise ValueError("cohort, signer key, and signature are required")
        if not _is_bool(self.eligible) or not _is_bool(self.low_risk_only):
            raise ValueError("canary eligibility fields must be bools")
        if any(
            not isinstance(item, datetime)
            or item.tzinfo is None
            or item.utcoffset() is None
            for item in (self.valid_from, self.expires_at)
        ):
            raise ValueError("canary receipt times must be timezone-aware")
        if self.expires_at <= self.valid_from:
            raise ValueError("canary receipt expiry must follow its valid-from time")

    def signed_payload(self) -> dict[str, object]:
        return {
            "policy_artifact_sha256": self.policy_artifact_sha256,
            "calibration_table_sha256": self.calibration_table_sha256,
            "cohort_id": self.cohort_id,
            "eligible": self.eligible,
            "low_risk_only": self.low_risk_only,
            "valid_from": self.valid_from,
            "expires_at": self.expires_at,
            "signer_key_id": self.signer_key_id,
        }

    def payload_bytes(self) -> bytes:
        return canonical_json(self.signed_payload()).encode("utf-8")

    def verify_integrity(self) -> None:
        expected = canonical_sha256(
            {"signed_payload": self.signed_payload(), "signature": self.signature}
        )
        if expected != self.receipt_sha256:
            raise ValueError("canary receipt sha256 mismatch")

    @classmethod
    def create(cls, *, signer: ReceiptSigner, **values: object) -> CanaryReceipt:
        unsigned = cls(signature="pending", receipt_sha256="0" * 64, **values)  # type: ignore[arg-type]
        signature = signer.sign(
            payload=unsigned.payload_bytes(), key_id=unsigned.signer_key_id
        )
        receipt_sha256 = canonical_sha256(
            {"signed_payload": unsigned.signed_payload(), "signature": signature}
        )
        return cls(signature=signature, receipt_sha256=receipt_sha256, **values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class PolicyAuthorityDecision:
    requested_mode: RouterMode
    effective_mode: RouterMode
    reason_codes: tuple[str, ...]
    policy_artifact_sha256: str | None
    canary_receipt_sha256: str | None
    calibration_table_sha256: str | None
    model_identities_sha256: str | None


def evaluate_policy_authority(
    *,
    requested_mode: str,
    policy_artifact: object | None,
    canary_receipt: object | None,
    verifier: object | None,
    now: datetime,
    low_risk_cohort: bool,
    expected_cohort_id: str | None = None,
) -> PolicyAuthorityDecision:
    """Grant shadow/canary mode; every malformed or unauthenticated input fails closed."""

    normalized: RouterMode = (
        cast(RouterMode, requested_mode)
        if requested_mode in {"deterministic", "shadow", "canary"}
        else "deterministic"
    )
    artifact_sha = (
        policy_artifact.artifact_sha256
        if isinstance(policy_artifact, CalibratedPolicyArtifact)
        else None
    )
    receipt_sha = (
        canary_receipt.receipt_sha256
        if isinstance(canary_receipt, CanaryReceipt)
        else None
    )
    if requested_mode not in {"deterministic", "shadow", "canary"}:
        return PolicyAuthorityDecision(
            normalized,
            "deterministic",
            ("requested_mode_invalid",),
            artifact_sha,
            receipt_sha,
            None,
            None,
        )
    if normalized == "deterministic":
        return PolicyAuthorityDecision(
            normalized, normalized, (), artifact_sha, receipt_sha, None, None
        )
    if not isinstance(policy_artifact, CalibratedPolicyArtifact):
        return PolicyAuthorityDecision(
            normalized,
            "deterministic",
            ("policy_artifact_missing",),
            None,
            receipt_sha,
            None,
            None,
        )
    try:
        policy_artifact.verify_integrity()
    except (PolicyArtifactIntegrityError, ValueError):
        return PolicyAuthorityDecision(
            normalized,
            "deterministic",
            ("policy_artifact_invalid",),
            artifact_sha,
            receipt_sha,
            None,
            None,
        )
    calibration_table_sha = policy_artifact.calibration_table_sha256
    model_identities_sha = canonical_sha256(policy_artifact.model_identities)
    if normalized == "shadow":
        return PolicyAuthorityDecision(
            normalized,
            "shadow",
            (),
            artifact_sha,
            receipt_sha,
            calibration_table_sha,
            model_identities_sha,
        )

    reasons: list[str] = []
    if not _is_bool(low_risk_cohort):
        reasons.append("canary_cohort_flag_invalid")
    if not isinstance(expected_cohort_id, str) or not expected_cohort_id.strip():
        reasons.append("canary_cohort_identity_missing")
    if not isinstance(canary_receipt, CanaryReceipt):
        reasons.append("canary_receipt_missing")
    else:
        try:
            canary_receipt.verify_integrity()
        except ValueError:
            reasons.append("canary_receipt_invalid")
        if canary_receipt.policy_artifact_sha256 != artifact_sha:
            reasons.append("canary_policy_mismatch")
        if canary_receipt.calibration_table_sha256 != policy_artifact.calibration_table_sha256:
            reasons.append("canary_calibration_table_mismatch")
        if (
            isinstance(expected_cohort_id, str)
            and expected_cohort_id.strip()
            and canary_receipt.cohort_id != expected_cohort_id
        ):
            reasons.append("canary_cohort_mismatch")
        if not canary_receipt.eligible:
            reasons.append("canary_not_eligible")
        if not canary_receipt.low_risk_only or low_risk_cohort is not True:
            reasons.append("canary_scope_not_low_risk")
        if policy_artifact.created_at > canary_receipt.valid_from:
            reasons.append("canary_policy_newer_than_receipt")
        if now.tzinfo is None or now.utcoffset() is None:
            reasons.append("authority_clock_invalid")
        elif now < canary_receipt.valid_from:
            reasons.append("canary_not_yet_valid")
        elif now >= canary_receipt.expires_at:
            reasons.append("canary_receipt_expired")
        if verifier is None or not hasattr(verifier, "verify"):
            reasons.append("canary_verifier_missing")
        else:
            try:
                verification_result = verifier.verify(
                    payload=canary_receipt.payload_bytes(),
                    signature=canary_receipt.signature,
                    key_id=canary_receipt.signer_key_id,
                )
                verified = verification_result is True
            except Exception:
                verified = False
            if not verified:
                reasons.append("canary_signature_invalid")
    return PolicyAuthorityDecision(
        normalized,
        "deterministic" if reasons else "canary",
        tuple(sorted(set(reasons))),
        artifact_sha,
        receipt_sha,
        calibration_table_sha,
        model_identities_sha,
    )


__all__ = [
    "AbstentionPolicy",
    "CalibrationMetrics",
    "CalibrationObservation",
    "CanaryReceipt",
    "Ed25519CanaryReceiptVerifier",
    "HmacSha256ReceiptAuthenticator",
    "PolicyAuthorityDecision",
    "ReceiptSigner",
    "ReceiptVerifier",
    "ReliabilityBin",
    "RiskCoveragePoint",
    "RouterMode",
    "SelectiveAction",
    "SelectiveDecision",
    "ThresholdSelection",
    "calibration_metrics",
    "evaluate_policy_authority",
    "risk_coverage_curve",
    "select_risk_threshold",
    "selective_decision",
]
