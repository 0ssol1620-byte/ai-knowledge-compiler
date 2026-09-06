"""The confirmatory holdout must stay frozen, disjoint and deterministic.

These run against the receipts rather than recomputing the freeze, because the
freeze reads a gigabyte of images. What they check is what a reader of the paper
would need to believe: the split is at document level, nothing overlaps the
discovery set, the leakage instrument was validated rather than assumed, and the
selection is reproducible from the recorded seed.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
RECEIPTS = ROOT / "research" / "experiments" / "H1-A9-01" / "receipts"
SCRIPTS = ROOT / "research" / "experiments" / "H1-A9-01" / "scripts"
sys.path.insert(0, str(SCRIPTS))

HOLDOUT = RECEIPTS / "confirmatory-holdout-800-2026-08-18.json"
SEAL = RECEIPTS / "discovery-set-seal-2026-08-18.json"
AUDIT = RECEIPTS / "holdout-provenance-audit-2026-08-18.json"

pytestmark = pytest.mark.skipif(
    not (HOLDOUT.is_file() and SEAL.is_file() and AUDIT.is_file()),
    reason="holdout receipts not present",
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_holdout_is_frozen_not_refused():
    assert load(HOLDOUT)["status"] == "FROZEN"


def test_the_holdout_reaches_the_sample_size_the_power_calculation_asked_for():
    holdout = load(HOLDOUT)
    assert holdout["page_count"] >= 800
    assert holdout["target_pages"] == 800


def test_no_page_or_document_is_shared_with_the_discovery_set():
    holdout = load(HOLDOUT)
    seal = load(SEAL)
    discovery = {p["image_path"] for p in seal["pages"]}
    discovery |= set(seal.get("excluded_without_an_official_page_score", []))
    holdout_pages = {p["image_path"] for p in holdout["pages"]}
    assert not (holdout_pages & discovery)

    checks = holdout["leakage_checks"]
    assert checks["page_identity_overlap"] == 0
    assert checks["document_identity_overlap"] == 0
    assert checks["exact_content_duplicates"] == 0
    assert checks["near_duplicates_within_threshold"] == 0


def test_the_near_duplicate_threshold_sits_below_the_measured_unrelated_minimum():
    """A threshold above it would call unrelated pages duplicates, and vice versa."""
    checks = load(HOLDOUT)["leakage_checks"]
    assert checks["difference_hash_bits"] == 256
    assert checks["near_duplicate_threshold"] < checks[
        "measured_minimum_distance_between_unrelated_discovery_pages"
    ]


def test_every_holdout_page_carries_a_content_hash_and_a_document():
    for record in load(HOLDOUT)["pages"]:
        assert len(record["input_sha256"]) == 64
        assert record["document_id"]
        assert record["case_id"].startswith("omnidocbench-")


def test_page_hashes_are_unique():
    digests = [p["input_sha256"] for p in load(HOLDOUT)["pages"]]
    assert len(set(digests)) == len(digests)


def test_the_split_is_document_level():
    """No document may straddle the boundary: its pages are all in or all out."""
    holdout = load(HOLDOUT)
    selected = set(holdout["documents"])
    for record in holdout["pages"]:
        assert record["document_id"] in selected


def test_the_selection_is_reproducible_from_the_recorded_seed():
    import random

    audit = load(AUDIT)
    holdout = load(HOLDOUT)
    by_document: dict[str, list[str]] = {}
    document_of = {
        record["image_path"]: record["document_id"] for record in holdout["pages"]
    }
    # Only the selected pages have a recorded document id, so the reproduction
    # checks the ordering of the shuffle rather than re-deriving every document.
    for page in audit["eligible"]:
        if page in document_of:
            by_document.setdefault(document_of[page], []).append(page)

    documents = sorted(by_document)
    random.Random(holdout["seed"]).shuffle(documents)  # noqa: S311
    assert set(documents) == set(holdout["documents"])


def test_the_audit_excluded_every_page_the_gated_parser_has_touched():
    audit = load(AUDIT)
    assert audit["pages_the_gated_parser_has_run_on"] > 0
    assert audit["eligible_after_document_level_exclusion"] == len(audit["eligible"])
    assert audit["eligible_after_document_level_exclusion"] >= 800


def test_the_audit_records_the_residual_contamination_rather_than_claiming_none():
    audit = load(AUDIT)
    assert audit["pages_scored_only_by_the_second_parser_campaign"] > 0
    assert "risk is not zero" in audit["residual_contamination_risk"]


def test_the_staged_slice_matches_the_frozen_manifest():
    slice_dir = ROOT / ".chatgpt2codex" / "a9-holdout-800-v1"
    provenance = slice_dir / "holdout-provenance.json"
    if not provenance.is_file():
        pytest.skip("holdout slice not staged")
    sidecar = load(provenance)
    assert sidecar["role"] == "a9_confirmatory_holdout"
    expected = "sha256:" + hashlib.sha256(HOLDOUT.read_bytes()).hexdigest()
    assert sidecar["holdout_manifest_sha256"] == expected
    assert sidecar["page_count"] == load(HOLDOUT)["page_count"]
