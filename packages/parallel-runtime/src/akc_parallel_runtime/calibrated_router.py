"""Router that can consume only an artifact-bound immutable calibration table."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .identity import canonical_sha256, require_sha256
from .models import WorkerSnapshot
from .policy_artifact import CalibratedPolicyArtifact
from .routing import (
    AdaptiveRouter,
    QualityEstimate,
    RecipeProfile,
    RouteDecision,
    RouteRequest,
)


class CalibratedPolicyBindingError(ValueError):
    """A score table, model, recipe, or worker is outside the signed policy binding."""


@dataclass(frozen=True, slots=True)
class CalibratedScoreRow:
    recipe_id: str
    worker_id: str
    model_revision: str
    runtime_image_digest: str
    model_identity_sha256: str
    estimate: QualityEstimate

    def __post_init__(self) -> None:
        for value in (
            self.recipe_id,
            self.worker_id,
            self.model_revision,
            self.runtime_image_digest,
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("calibrated score identity fields are required")
        require_sha256(self.model_identity_sha256, field_name="model_identity_sha256")
        numeric_values = (
            self.estimate.pass_hard_gate,
            self.estimate.numeric_exact,
            self.estimate.row_complete,
            self.estimate.repetition_probability,
            self.estimate.timeout_probability,
            self.estimate.oom_probability,
            self.estimate.expected_latency_seconds,
            self.estimate.expected_cost,
        )
        if any(
            type(value) not in {int, float} or not math.isfinite(value)
            for value in numeric_values
        ):
            raise ValueError("calibrated score values must be finite numbers")


@dataclass(frozen=True, slots=True)
class CalibratedScoreTable:
    evaluator_registry_sha256: str
    model_identities_sha256: str
    rows: tuple[CalibratedScoreRow, ...]
    table_sha256: str

    def __post_init__(self) -> None:
        require_sha256(
            self.evaluator_registry_sha256,
            field_name="evaluator_registry_sha256",
        )
        require_sha256(self.model_identities_sha256, field_name="model_identities_sha256")
        require_sha256(self.table_sha256, field_name="table_sha256")
        if not isinstance(self.rows, tuple):
            raise ValueError("calibrated score rows must be an immutable tuple")
        if not self.rows:
            raise ValueError("calibrated score rows are required")
        identities = {(row.recipe_id, row.worker_id) for row in self.rows}
        if len(identities) != len(self.rows):
            raise ValueError("calibrated recipe/worker score rows must be unique")

    def content_payload(self) -> dict[str, object]:
        return {
            "evaluator_registry_sha256": self.evaluator_registry_sha256,
            "model_identities_sha256": self.model_identities_sha256,
            "rows": self.rows,
        }

    def verify_integrity(self) -> None:
        if canonical_sha256(self.content_payload()) != self.table_sha256:
            raise CalibratedPolicyBindingError("calibrated score-table sha256 mismatch")

    @classmethod
    def create(
        cls,
        *,
        evaluator_registry_sha256: str,
        model_identities_sha256: str,
        rows: tuple[CalibratedScoreRow, ...],
    ) -> CalibratedScoreTable:
        payload = {
            "evaluator_registry_sha256": evaluator_registry_sha256,
            "model_identities_sha256": model_identities_sha256,
            "rows": rows,
        }
        return cls(
            evaluator_registry_sha256=evaluator_registry_sha256,
            model_identities_sha256=model_identities_sha256,
            rows=rows,
            table_sha256=canonical_sha256(payload),
        )


class CalibratedRoutingPolicyRouter:
    """Execute only the scores whose complete identity is bound to the policy artifact."""

    def __init__(
        self,
        *,
        policy_artifact: CalibratedPolicyArtifact,
        score_table: CalibratedScoreTable,
        maximum_cost: float | None = None,
    ) -> None:
        policy_artifact.verify_integrity()
        score_table.verify_integrity()
        model_identities_sha256 = canonical_sha256(policy_artifact.model_identities)
        if score_table.table_sha256 != policy_artifact.calibration_table_sha256:
            raise CalibratedPolicyBindingError(
                "score table is not the table bound by the policy artifact"
            )
        if score_table.evaluator_registry_sha256 != policy_artifact.evaluator_registry_sha256:
            raise CalibratedPolicyBindingError("score-table evaluator registry binding mismatch")
        if score_table.model_identities_sha256 != model_identities_sha256:
            raise CalibratedPolicyBindingError("score-table model identity registry mismatch")
        allowed_model_identities = {
            canonical_sha256(identity) for identity in policy_artifact.model_identities
        }
        if any(
            row.model_identity_sha256 not in allowed_model_identities
            for row in score_table.rows
        ):
            raise CalibratedPolicyBindingError("score row references an unbound model identity")
        if maximum_cost is not None and (
            type(maximum_cost) not in {int, float}
            or not math.isfinite(maximum_cost)
            or maximum_cost < 0
        ):
            raise ValueError("maximum_cost must be a finite non-negative number")
        self._artifact = policy_artifact
        self._score_table = score_table
        self._maximum_cost = maximum_cost
        self._router = AdaptiveRouter(policy_version=policy_artifact.policy_version)
        self.policy_artifact_sha256 = policy_artifact.artifact_sha256
        self.calibration_table_sha256 = score_table.table_sha256
        self.model_identities_sha256 = score_table.model_identities_sha256

    def route(
        self,
        request: RouteRequest,
        *,
        recipes: tuple[RecipeProfile, ...],
        workers: tuple[WorkerSnapshot, ...],
        estimates: dict[tuple[str, str], QualityEstimate],
    ) -> RouteDecision:
        """Route with verified table values; the estimates argument is intentionally ignored."""

        del estimates
        recipe_by_id = {recipe.recipe_id: recipe for recipe in recipes}
        worker_by_id = {worker.worker_id: worker for worker in workers}
        if len(recipe_by_id) != len(recipes) or len(worker_by_id) != len(workers):
            raise CalibratedPolicyBindingError("recipe and worker ids must be unique")
        verified_estimates: dict[tuple[str, str], QualityEstimate] = {}
        for row in self._score_table.rows:
            if (
                self._maximum_cost is not None
                and row.estimate.expected_cost > self._maximum_cost
            ):
                continue
            recipe = recipe_by_id.get(row.recipe_id)
            worker = worker_by_id.get(row.worker_id)
            if recipe is None or worker is None:
                continue
            if (
                recipe.model_revision != row.model_revision
                or recipe.runtime_image_digest != row.runtime_image_digest
                or worker.model_revision != row.model_revision
                or worker.runtime_image_digest != row.runtime_image_digest
            ):
                raise CalibratedPolicyBindingError(
                    "runtime recipe/worker identity differs from calibrated score row"
                )
            verified_estimates[(row.recipe_id, row.worker_id)] = row.estimate
        return self._router.route(
            request,
            recipes=recipes,
            workers=workers,
            estimates=verified_estimates,
        )


__all__ = [
    "CalibratedPolicyBindingError",
    "CalibratedRoutingPolicyRouter",
    "CalibratedScoreRow",
    "CalibratedScoreTable",
]
