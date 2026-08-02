from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]


def test_measured_model_snapshot_is_schema_valid() -> None:
    schema = json.loads(
        (ROOT / "benchmark/schemas/model-evaluation-public-snapshot.schema.json").read_text(
            encoding="utf-8"
        )
    )
    snapshot = json.loads(
        (ROOT / "apps/web/src/data/benchmark-public-snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(snapshot)
    )
    assert errors == []


def test_non_promoted_diagnostics_are_schema_valid_and_scoreless() -> None:
    schema = json.loads(
        (
            ROOT
            / "benchmark/schemas/model-evaluation-diagnostic-snapshot.schema.json"
        ).read_text(encoding="utf-8")
    )
    snapshot = json.loads(
        (ROOT / "apps/web/src/data/benchmark-diagnostics.json").read_text(
            encoding="utf-8"
        )
    )
    errors = list(Draft202012Validator(schema).iter_errors(snapshot))
    assert errors == []
    assert all(item["completed_inference_cases"] == 0 for item in snapshot["diagnostics"])
    assert all("metrics" not in item for item in snapshot["diagnostics"])
