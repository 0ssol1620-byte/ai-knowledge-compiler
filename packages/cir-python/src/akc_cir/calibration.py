"""Leakage-safe detector calibration artifacts and reliability metrics.

Calibration is deliberately separate from detector implementation. Raw detector
values remain in inspection receipts; this module only learns/version-controls a
mapping from a raw score to an empirical risk estimate. No external ML runtime is
required, so fitting and evaluation are reproducible on CPU.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "CalibrationArtifact",
    "CalibrationExample",
    "CalibrationMethod",
    "CalibrationMetrics",
    "ReliabilityBin",
    "evaluate_calibrator",
    "fit_calibrator",
]


class CalibrationMethod(StrEnum):
    ISOTONIC = "isotonic"
    LOGISTIC = "logistic"
    CONFORMAL = "conformal"


@dataclass(frozen=True, slots=True)
class CalibrationExample:
    sample_id: str
    score: float
    label: bool

    def __post_init__(self) -> None:
        if not self.sample_id:
            raise ValueError("sample_id is required for leakage detection")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be within 0..1")


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    lower: float
    upper: float
    count: int
    mean_prediction: float
    observed_rate: float


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    count: int
    brier: float
    ece: float
    reliability: tuple[ReliabilityBin, ...]


def _sample_fingerprint(sample_id: str) -> str:
    return hashlib.sha256(sample_id.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class CalibrationArtifact:
    method: CalibrationMethod
    detector_code: str
    artifact_version: int
    calibrated_from: str
    training_sample_fingerprints: tuple[str, ...]
    parameters: tuple[tuple[str, object], ...]
    artifact_id: str
    output_semantics: str = "empirical_probability"

    def _params(self) -> dict[str, Any]:
        return dict(self.parameters)

    def predict(self, score: float) -> float:
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be within 0..1")
        params = self._params()
        if self.method is CalibrationMethod.LOGISTIC:
            z = float(params["a"]) * score + float(params["b"])
            return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, z))))
        if self.method is CalibrationMethod.ISOTONIC:
            knots = tuple(float(x) for x in params["knots"])
            values = tuple(float(x) for x in params["values"])
            for knot, value in zip(knots, values, strict=True):
                if score <= knot:
                    return value
            return values[-1]
        # One-class conformal anomaly risk against labelled clean examples.
        clean_scores = tuple(float(x) for x in params["clean_scores"])
        ge = sum(value >= score for value in clean_scores)
        p_clean = (ge + 1.0) / (len(clean_scores) + 1.0)
        return max(0.0, min(1.0, 1.0 - p_clean))

    def as_record(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_version": self.artifact_version,
            "method": self.method.value,
            "detector_code": self.detector_code,
            "calibrated_from": self.calibrated_from,
            "training_sample_fingerprints": list(self.training_sample_fingerprints),
            "parameters": dict(self.parameters),
            "output_semantics": self.output_semantics,
        }


def _isotonic_parameters(examples: Sequence[CalibrationExample]) -> dict[str, object]:
    ordered = sorted(examples, key=lambda item: (item.score, item.sample_id))
    # [max_score, positives, count]
    blocks: list[list[float]] = []
    for item in ordered:
        blocks.append([item.score, float(item.label), 1.0])
        while len(blocks) >= 2:
            left = blocks[-2][1] / blocks[-2][2]
            right = blocks[-1][1] / blocks[-1][2]
            if left <= right:
                break
            b = blocks.pop()
            a = blocks.pop()
            blocks.append([b[0], a[1] + b[1], a[2] + b[2]])
    return {
        "knots": tuple(block[0] for block in blocks),
        "values": tuple(block[1] / block[2] for block in blocks),
    }


def _logistic_parameters(examples: Sequence[CalibrationExample]) -> dict[str, object]:
    a = 1.0
    b = 0.0
    n = float(len(examples))
    # Deterministic Platt-style fit; tiny L2 term avoids runaway coefficients on
    # perfectly separable pilot corpora.
    for step in range(1200):
        grad_a = grad_b = 0.0
        for item in examples:
            z = max(-40.0, min(40.0, a * item.score + b))
            pred = 1.0 / (1.0 + math.exp(-z))
            error = pred - float(item.label)
            grad_a += error * item.score
            grad_b += error
        rate = 0.25 / math.sqrt(1.0 + step / 100.0)
        a -= rate * (grad_a / n + 1e-4 * a)
        b -= rate * grad_b / n
    return {"a": a, "b": b}


def fit_calibrator(
    examples: Sequence[CalibrationExample],
    *,
    method: CalibrationMethod,
    detector_code: str,
    calibrated_from: str,
    artifact_version: int = 1,
) -> CalibrationArtifact:
    if not examples:
        raise ValueError("calibration needs labelled examples")
    if not detector_code or not calibrated_from:
        raise ValueError("detector_code and calibrated_from are required")
    sample_ids = [item.sample_id for item in examples]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("duplicate sample_id would leak repeated evidence into calibration")
    if method is CalibrationMethod.ISOTONIC:
        params = _isotonic_parameters(examples)
        semantics = "empirical_probability"
    elif method is CalibrationMethod.LOGISTIC:
        params = _logistic_parameters(examples)
        semantics = "empirical_probability"
    else:
        clean = sorted(item.score for item in examples if not item.label)
        if not clean:
            raise ValueError("conformal calibration needs at least one labelled clean example")
        params = {"clean_scores": tuple(clean)}
        semantics = "conformal_anomaly_risk"
    fingerprints = tuple(sorted(_sample_fingerprint(value) for value in sample_ids))
    canonical = {
        "method": method.value,
        "detector_code": detector_code,
        "artifact_version": artifact_version,
        "calibrated_from": calibrated_from,
        "training": fingerprints,
        "parameters": params,
        "output_semantics": semantics,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return CalibrationArtifact(
        method=method,
        detector_code=detector_code,
        artifact_version=artifact_version,
        calibrated_from=calibrated_from,
        training_sample_fingerprints=fingerprints,
        parameters=tuple(params.items()),
        artifact_id=f"cal_{digest[:32]}",
        output_semantics=semantics,
    )


def evaluate_calibrator(
    artifact: CalibrationArtifact,
    examples: Sequence[CalibrationExample],
    *,
    bins: int = 10,
) -> CalibrationMetrics:
    if not examples:
        raise ValueError("evaluation needs labelled examples")
    if bins <= 0:
        raise ValueError("bins must be positive")
    train = set(artifact.training_sample_fingerprints)
    overlap = [item.sample_id for item in examples if _sample_fingerprint(item.sample_id) in train]
    if overlap:
        raise ValueError("calibration/evaluation split leakage detected")
    pairs = [(artifact.predict(item.score), float(item.label)) for item in examples]
    brier = sum((pred - label) ** 2 for pred, label in pairs) / len(pairs)
    reliability: list[ReliabilityBin] = []
    ece = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        selected = [
            pair for pair in pairs
            if lower <= pair[0] < upper or (index == bins - 1 and pair[0] == 1.0)
        ]
        if not selected:
            continue
        mean_prediction = sum(p for p, _ in selected) / len(selected)
        observed = sum(y for _, y in selected) / len(selected)
        ece += (len(selected) / len(pairs)) * abs(mean_prediction - observed)
        reliability.append(
            ReliabilityBin(lower, upper, len(selected), mean_prediction, observed)
        )
    return CalibrationMetrics(len(pairs), brier, ece, tuple(reliability))