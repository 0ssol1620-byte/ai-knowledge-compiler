"""Scoring refuses incomplete or altered captures before loading hidden rules."""

import hashlib
import json
from pathlib import Path

import pytest
import score_native


def invoke(monkeypatch, capture: Path, output: Path):
    monkeypatch.setattr("sys.argv", [
        "score_native.py", "--capture", str(capture), "--output", str(output),
        "--evaluator", str(capture / "must-not-open-evaluator"),
        "--bench-data", str(capture / "must-not-open-labels"),
    ])
    score_native.main()


def seal(capture: Path, rows: list[dict], source_rows: list[dict] | None = None):
    observations = "\n".join(json.dumps(row) for row in rows).encode()
    (capture / "observations.jsonl").write_bytes(observations)
    (capture / "RESULT.json").write_text(json.dumps({
        "observations_sha256": "sha256:" + hashlib.sha256(observations).hexdigest(),
    }))
    (capture / "FREEZE.json").write_text(json.dumps({
        "confirmatory_eligible": False, "selected_units": 1403,
        "selected_source_rows": source_rows or [],
    }))


@pytest.fixture
def output():
    # Preflight must refuse before this path is created.
    return Path(score_native.__file__).resolve().parents[2] / ".chatgpt2codex" / "refusal-only"


def test_output_cannot_escape_worktree_scratch(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="SCORING_OUTPUT_MUST_BE_NEW_WORKTREE_SCRATCH"):
        invoke(monkeypatch, tmp_path, tmp_path / "outside")


def test_modified_observation_bytes_are_refused_before_labels(monkeypatch, tmp_path, output):
    seal(tmp_path, [])
    (tmp_path / "observations.jsonl").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="CAPTURE_HASH_MISMATCH"):
        invoke(monkeypatch, tmp_path, output)


def test_complete_claim_does_not_substitute_for_actual_rows(monkeypatch, tmp_path, output):
    seal(tmp_path, [])
    with pytest.raises(ValueError, match="OBSERVATION_DENOMINATOR_INVALID"):
        invoke(monkeypatch, tmp_path, output)


def test_per_page_text_digest_is_checked(monkeypatch, tmp_path, output):
    rows = [{"sample_id": str(i), "source_sha256": "source", "text": "changed",
             "output_sha256": "wrong"} for i in range(1403)]
    seal(tmp_path, rows, [{"sample_id": "0", "original_source_sha256": "source"}])
    with pytest.raises(ValueError, match="OBSERVATION_TEXT_HASH_MISMATCH"):
        invoke(monkeypatch, tmp_path, output)


def test_fresh_capture_is_not_relabelled_spent(monkeypatch, tmp_path, output):
    seal(tmp_path, [])
    (tmp_path / "FREEZE.json").write_text(json.dumps({
        "confirmatory_eligible": True, "selected_units": 1403,
    }))
    with pytest.raises(ValueError, match="COMPLETE_SPENT_CAPTURE_REQUIRED"):
        invoke(monkeypatch, tmp_path, output)
