"""Fail-closed adapters from official evaluator failures to recovery taxonomy."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from benchmark.v6.failure_detection import FailurePrediction

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}$")
_NON_RECOVERABLE = frozenset({"T03", "H01", "H02"})


@dataclass(frozen=True, slots=True)
class AdapterRule:
    failure_code: str
    minimum_scope: str


@dataclass(frozen=True, slots=True)
class EvaluatorFailureRecord:
    benchmark_id: str
    case_id: str
    evaluator_revision: str
    evaluator_type: str
    location_id: str
    prediction_sha256: str
    authority_sha256: str
    failure_evidence_sha256: str
    passed: bool
    score: float | None = None

    def validate(self) -> None:
        if self.benchmark_id not in PUBLIC_FAILURE_RULES:
            raise ValueError(f"unsupported public benchmark: {self.benchmark_id}")
        for label, value in (
            ("case_id", self.case_id),
            ("evaluator_type", self.evaluator_type),
            ("location_id", self.location_id),
        ):
            if not _IDENTIFIER.fullmatch(value):
                raise ValueError(f"{label} is invalid")
        if not _REVISION.fullmatch(self.evaluator_revision):
            raise ValueError("evaluator_revision must be an immutable revision")
        for label, value in (
            ("prediction_sha256", self.prediction_sha256),
            ("authority_sha256", self.authority_sha256),
            ("failure_evidence_sha256", self.failure_evidence_sha256),
        ):
            if not _SHA256.fullmatch(value):
                raise ValueError(f"{label} must be sha256-bound")
        if not self.passed and self.prediction_sha256 == self.authority_sha256:
            raise ValueError("failed evaluator evidence cannot bind identical artifacts")
        if self.score is not None and (
            not math.isfinite(self.score) or not 0.0 <= self.score <= 1.0
        ):
            raise ValueError("evaluator score must be finite and between zero and one")


_PARSE_B01 = {
    "missing_specific_word",
    "missing_specific_sentence",
    "missing_word_percent",
    "missing_sentence_percent",
}
_PARSE_R01 = {"layout", "order", "title_hierarchy_percent"}
_PARSE_N01 = {"chart_data_point", "bag_of_digit_percent"}
_PARSE_G01 = {
    "expected_markdown",
    "is_bold",
    "is_title",
    "is_italic",
    "is_underline",
    "is_sup",
    "is_footer",
    "is_header",
    "is_mark",
    "is_strikeout",
    "is_sub",
    "is_code_block",
}
_PARSE_H01 = {"unexpected_word_percent", "unexpected_sentence_percent"}
_PARSE_H02 = {
    "too_many_word_occurence_percent",
    "too_many_sentence_occurence_percent",
}

PUBLIC_FAILURE_RULES: dict[str, dict[str, AdapterRule]] = {
    "omnidocbench": {
        "missing_page": AdapterRule("P01", "page"),
        "text_block": AdapterRule("B01", "region"),
        "display_formula": AdapterRule("F01", "region"),
        "table": AdapterRule("T05", "cell"),
        "reading_order": AdapterRule("R01", "region"),
    },
    "parsebench": {
        **{name: AdapterRule("B01", "region") for name in _PARSE_B01},
        **{name: AdapterRule("R01", "region") for name in _PARSE_R01},
        **{name: AdapterRule("N01", "cell") for name in _PARSE_N01},
        **{name: AdapterRule("G01", "region") for name in _PARSE_G01},
        **{name: AdapterRule("H01", "region") for name in _PARSE_H01},
        **{name: AdapterRule("H02", "region") for name in _PARSE_H02},
        "is_latex": AdapterRule("F01", "region"),
    },
    "olmocr-bench": {
        "math": AdapterRule("F01", "region"),
        "order": AdapterRule("R01", "region"),
        "table": AdapterRule("T05", "cell"),
        "absent": AdapterRule("H01", "region"),
        "present": AdapterRule("B01", "region"),
        "baseline": AdapterRule("G01", "region"),
    },
}


def adapt_failure(record: EvaluatorFailureRecord) -> FailurePrediction | None:
    """Convert one official evaluator decision without guessing unknown types."""

    record.validate()
    rule = PUBLIC_FAILURE_RULES[record.benchmark_id].get(record.evaluator_type)
    if rule is None:
        raise ValueError(
            f"unmapped evaluator failure type: {record.benchmark_id}/{record.evaluator_type}"
        )
    if record.passed:
        return None
    return FailurePrediction(
        item_id=record.case_id,
        failure_codes=frozenset({rule.failure_code}),
        scope_level=rule.minimum_scope,
        scope_id=f"{record.case_id}:{record.location_id}",
        request_recovery=rule.failure_code not in _NON_RECOVERABLE,
        escalate=False,
    )


def adapt_failures(
    records: tuple[EvaluatorFailureRecord, ...],
) -> tuple[FailurePrediction, ...]:
    seen: set[tuple[str, str, str, str]] = set()
    predictions: list[FailurePrediction] = []
    for record in records:
        identity = (
            record.benchmark_id,
            record.case_id,
            record.evaluator_type,
            record.location_id,
        )
        if identity in seen:
            raise ValueError("duplicate public evaluator failure record")
        seen.add(identity)
        prediction = adapt_failure(record)
        if prediction is not None:
            predictions.append(prediction)
    return tuple(predictions)


__all__ = [
    "PUBLIC_FAILURE_RULES",
    "AdapterRule",
    "EvaluatorFailureRecord",
    "adapt_failure",
    "adapt_failures",
]
