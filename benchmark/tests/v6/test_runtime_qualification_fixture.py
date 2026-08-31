"""Checks on the D2 synthetic smoke fixture under
infra/runpod/v6/qualification/rq-01/fixtures/.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = ROOT / "infra/runpod/v6/qualification/rq-01/fixtures"
FIXTURE_PNG = FIXTURES_DIR / "rq-01-smoke-001.png"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"
ACQUISITION_RECEIPT_PATH = (
    ROOT / "research/experiments/SEM-RISK-CONF-02/receipts/acquisition-receipt.json"
)

_FORBIDDEN_MANIFEST_STRINGS = ("spent", "SPENT_DEVELOPMENT_ONLY", "benchmark/datasets/private")


def _sha256_hex(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fixture_sha256_matches_manifest_recorded_value() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    observed = _sha256_hex(FIXTURE_PNG)
    assert manifest["sha256"] == observed


def test_fixture_sha256_does_not_appear_in_the_confirmatory_input_inventory() -> None:
    acquisition = json.loads(ACQUISITION_RECEIPT_PATH.read_text(encoding="utf-8"))
    files = acquisition["files"]
    assert len(files) == 192

    fixture_sha256 = "sha256:" + _sha256_hex(FIXTURE_PNG)
    inventory_hashes = {entry["sha256"] for entry in files}
    assert fixture_sha256 not in inventory_hashes


def test_manifest_contains_no_spent_or_private_dataset_markers() -> None:
    manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
    for forbidden in _FORBIDDEN_MANIFEST_STRINGS:
        assert forbidden not in manifest_text, (
            f"manifest.json unexpectedly contains {forbidden!r}"
        )


def test_manifest_records_synthetic_unspent_evidence_class_and_no_ground_truth() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["evidence_class"] == "SYNTHETIC_UNSPENT_NO_GROUND_TRUTH"
    assert manifest["ground_truth_exists"] is False
    assert manifest["derived_from_confirmatory_cohort"] is False
    assert manifest["derived_from_omnidocbench_or_any_external_corpus"] is False


def test_exactly_three_files_exist_in_the_fixtures_directory() -> None:
    entries = sorted(path.name for path in FIXTURES_DIR.iterdir() if path.is_file())
    assert entries == ["generate_fixture.py", "manifest.json", "rq-01-smoke-001.png"]
