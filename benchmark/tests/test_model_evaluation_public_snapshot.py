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
    # The measured snapshot lives in the evidence tree, not under apps/web.
    #
    # It used to be read from the file the site imports, which turned out to be
    # two different artifacts wearing one name. The site's copy is a 1.0
    # placeholder whose datasets carry text/numbers/tables/provenance; the
    # measured run produces 1.1 with edit-distance and TEDS companions. They are
    # not a version apart, they are a different shape, and the marketing page
    # now reads its figures from the claims pack rather than from either.
    #
    # Publishing the measured one would mean rewriting the site's consumer and
    # everything that renders it, which belongs to the design session. This
    # validates the artifact we produce; the handoff carries the contract change.
    snapshot = json.loads(
        (
            ROOT
            / "docs/evidence/artifacts"
            / "folynta-measured-model-evaluation-snapshot-2026-08-02.json"
        ).read_text(encoding="utf-8")
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
