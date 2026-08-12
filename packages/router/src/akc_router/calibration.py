"""Observed route calibration error."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    confidence: float
    correct: bool


def expected_calibration_error(items: tuple[CalibrationBin, ...], *, bins: int = 10) -> float:
    if not items or bins < 1:
        raise ValueError("calibration requires observations and positive bins")
    if any(not 0 <= item.confidence <= 1 for item in items):
        raise ValueError("confidence must be between zero and one")
    total = len(items)
    error = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        bucket = tuple(
            item
            for item in items
            if low <= item.confidence <= high and (index == bins - 1 or item.confidence < high)
        )
        if not bucket:
            continue
        confidence = sum(item.confidence for item in bucket) / len(bucket)
        accuracy = sum(item.correct for item in bucket) / len(bucket)
        error += len(bucket) / total * abs(accuracy - confidence)
    return error


__all__ = ["CalibrationBin", "expected_calibration_error"]
