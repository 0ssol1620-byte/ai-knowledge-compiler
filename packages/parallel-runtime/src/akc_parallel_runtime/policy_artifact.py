"""Immutable, content-addressed evidence binding for calibrated router policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .identity import canonical_sha256, require_sha256


class PolicyArtifactIntegrityError(ValueError):
    """The policy artifact is incomplete, leaked, or does not match its digest."""


def _required(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a sha256 string")
    return require_sha256(value, field_name=field_name)


@dataclass(frozen=True, slots=True)
class FamilySplitBinding:
    train_family_ids: frozenset[str]
    calibration_family_ids: frozenset[str]
    holdout_family_ids: frozenset[str]

    def __post_init__(self) -> None:
        if any(
            not isinstance(group, frozenset)
            for group in (
                self.train_family_ids,
                self.calibration_family_ids,
                self.holdout_family_ids,
            )
        ):
            raise ValueError("family split groups must be immutable frozensets")
        groups = (
            self.train_family_ids,
            self.calibration_family_ids,
            self.holdout_family_ids,
        )
        if any(not group for group in groups):
            raise ValueError("train, calibration, and holdout families are required")
        if any(
            not isinstance(family_id, str) or not family_id.strip()
            for group in groups
            for family_id in group
        ):
            raise ValueError("family ids cannot be blank")
        if any(groups[left] & groups[right] for left, right in ((0, 1), (0, 2), (1, 2))):
            raise PolicyArtifactIntegrityError("document families must be split disjointly")

    @property
    def train_sha256(self) -> str:
        return canonical_sha256(sorted(self.train_family_ids))

    @property
    def calibration_sha256(self) -> str:
        return canonical_sha256(sorted(self.calibration_family_ids))

    @property
    def holdout_sha256(self) -> str:
        return canonical_sha256(sorted(self.holdout_family_ids))

    @property
    def all_family_ids(self) -> frozenset[str]:
        return self.train_family_ids | self.calibration_family_ids | self.holdout_family_ids

    def as_binding(self) -> dict[str, str]:
        return {
            "train_sha256": self.train_sha256,
            "calibration_sha256": self.calibration_sha256,
            "holdout_sha256": self.holdout_sha256,
        }


@dataclass(frozen=True, slots=True)
class ModelIdentityBinding:
    provider: str
    model_id: str
    revision: str
    input_mode: str
    settings_sha256: str
    capability_receipt_sha256: str

    def __post_init__(self) -> None:
        for field_name in ("provider", "model_id", "revision", "input_mode"):
            _required(getattr(self, field_name), field_name)
        _sha256(self.settings_sha256, "settings_sha256")
        _sha256(
            self.capability_receipt_sha256,
            "capability_receipt_sha256",
        )


@dataclass(frozen=True, slots=True)
class RepeatRunBinding:
    run_id: str
    run_receipt_sha256: str
    result_sha256: str
    experiment_binding_sha256: str
    completed_at: datetime

    def __post_init__(self) -> None:
        _required(self.run_id, "run_id")
        for field_name in (
            "run_receipt_sha256",
            "result_sha256",
            "experiment_binding_sha256",
        ):
            _sha256(getattr(self, field_name), field_name)
        if (
            not isinstance(self.completed_at, datetime)
            or self.completed_at.tzinfo is None
            or self.completed_at.utcoffset() is None
        ):
            raise ValueError("completed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CalibratedPolicyArtifact:
    policy_version: str
    created_at: datetime
    corpus_manifest_sha256: str
    family_split: FamilySplitBinding
    prompt_calibration_corpus_sha256: str
    prompt_calibration_family_ids: frozenset[str]
    evaluator_registry_sha256: str
    model_identities: tuple[ModelIdentityBinding, ...]
    price_measurements_sha256: str
    price_evidence_kind: str
    price_measurement_count: int
    prompt_receipt_sha256: str
    hardware_receipt_sha256: str
    hardware_measurement_count: int
    preregistration_sha256: str
    calibration_table_sha256: str
    repeat_runs: tuple[RepeatRunBinding, ...]
    artifact_sha256: str

    def __post_init__(self) -> None:
        _required(self.policy_version, "policy_version")
        if (
            not isinstance(self.created_at, datetime)
            or self.created_at.tzinfo is None
            or self.created_at.utcoffset() is None
        ):
            raise ValueError("created_at must be timezone-aware")
        for field_name in (
            "corpus_manifest_sha256",
            "prompt_calibration_corpus_sha256",
            "evaluator_registry_sha256",
            "price_measurements_sha256",
            "prompt_receipt_sha256",
            "hardware_receipt_sha256",
            "preregistration_sha256",
            "calibration_table_sha256",
            "artifact_sha256",
        ):
            _sha256(getattr(self, field_name), field_name)
        if not isinstance(self.prompt_calibration_family_ids, frozenset):
            raise ValueError("prompt calibration families must be an immutable frozenset")
        if not self.prompt_calibration_family_ids:
            raise ValueError("prompt calibration families are required")
        if any(
            not isinstance(family_id, str) or not family_id.strip()
            for family_id in self.prompt_calibration_family_ids
        ):
            raise ValueError("prompt calibration family ids cannot be blank")
        if self.prompt_calibration_family_ids & self.family_split.all_family_ids:
            raise PolicyArtifactIntegrityError(
                "prompt calibration and router train/calibration/holdout families overlap"
            )
        if not isinstance(self.model_identities, tuple):
            raise ValueError("model identities must be an immutable tuple")
        if not self.model_identities:
            raise ValueError("at least one exact model identity is required")
        if self.price_evidence_kind not in {
            "actual_usage_receipts",
            "actual_runtime_receipts",
            "mixed_actual_receipts",
        }:
            raise PolicyArtifactIntegrityError(
                "price evidence must come from actual usage or runtime receipts"
            )
        if (
            type(self.price_measurement_count) is not int
            or type(self.hardware_measurement_count) is not int
            or self.price_measurement_count < 1
            or self.hardware_measurement_count < 1
        ):
            raise PolicyArtifactIntegrityError(
                "price and hardware evidence require actual measurement counts"
            )
        identities = {
            (item.provider, item.model_id, item.revision, item.input_mode)
            for item in self.model_identities
        }
        if len(identities) != len(self.model_identities):
            raise ValueError("model identities must be unique")
        if not isinstance(self.repeat_runs, tuple):
            raise ValueError("repeat runs must be an immutable tuple")
        if len(self.repeat_runs) != 3:
            raise PolicyArtifactIntegrityError("exactly three reproducibility runs are required")
        if len({run.run_id for run in self.repeat_runs}) != 3:
            raise PolicyArtifactIntegrityError("reproducibility run ids must be distinct")
        if len({run.run_receipt_sha256 for run in self.repeat_runs}) != 3:
            raise PolicyArtifactIntegrityError("reproducibility run receipts must be distinct")
        if any(run.completed_at > self.created_at for run in self.repeat_runs):
            raise PolicyArtifactIntegrityError(
                "reproducibility runs cannot complete after artifact creation"
            )
        expected_binding = self.experiment_binding_sha256
        if any(run.experiment_binding_sha256 != expected_binding for run in self.repeat_runs):
            raise PolicyArtifactIntegrityError("repeat run experiment binding mismatch")

    @property
    def experiment_binding_sha256(self) -> str:
        return canonical_sha256(self._experiment_payload())

    def _experiment_payload(self) -> dict[str, object]:
        return {
            "corpus_manifest_sha256": self.corpus_manifest_sha256,
            "family_split": self.family_split.as_binding(),
            "prompt_calibration_corpus_sha256": self.prompt_calibration_corpus_sha256,
            "prompt_calibration_family_ids_sha256": canonical_sha256(
                sorted(self.prompt_calibration_family_ids)
            ),
            "evaluator_registry_sha256": self.evaluator_registry_sha256,
            "model_identities": self.model_identities,
            "price_measurements_sha256": self.price_measurements_sha256,
            "price_evidence_kind": self.price_evidence_kind,
            "price_measurement_count": self.price_measurement_count,
            "prompt_receipt_sha256": self.prompt_receipt_sha256,
            "hardware_receipt_sha256": self.hardware_receipt_sha256,
            "hardware_measurement_count": self.hardware_measurement_count,
            "preregistration_sha256": self.preregistration_sha256,
        }

    def content_payload(self) -> dict[str, object]:
        return {
            "policy_version": self.policy_version,
            "created_at": self.created_at,
            "experiment": self._experiment_payload(),
            "calibration_table_sha256": self.calibration_table_sha256,
            "repeat_runs": self.repeat_runs,
        }

    def verify_integrity(self) -> None:
        if canonical_sha256(self.content_payload()) != self.artifact_sha256:
            raise PolicyArtifactIntegrityError("policy artifact sha256 mismatch")

    @classmethod
    def create(cls, **values: object) -> CalibratedPolicyArtifact:
        provisional = cls(artifact_sha256="0" * 64, **values)  # type: ignore[arg-type]
        return cls(
            **values,  # type: ignore[arg-type]
            artifact_sha256=canonical_sha256(provisional.content_payload()),
        )


__all__ = [
    "CalibratedPolicyArtifact",
    "FamilySplitBinding",
    "ModelIdentityBinding",
    "PolicyArtifactIntegrityError",
    "RepeatRunBinding",
]
