"""Checks on infra/runpod/v6/qualification/rq-01/lineage.json (D1).

Independently recomputes both pinned hashes against the live files rather
than trusting the values already written into lineage.json.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LINEAGE_PATH = ROOT / "infra/runpod/v6/qualification/rq-01/lineage.json"
CANDIDATE_REGISTRY_PATH = ROOT / "benchmark/v6/candidate-registry.yaml"
PROTOCOL_PATH = ROOT / "research/experiments/SEM-RISK-CONF-02/protocol.json"
EXPERIMENTS_DIR = ROOT / "research/experiments"


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _lineage() -> dict:
    return json.loads(LINEAGE_PATH.read_text(encoding="utf-8"))


def test_lineage_is_valid_json_matching_the_declared_schema() -> None:
    lineage = _lineage()
    assert lineage["schema"] == "folynta.runtime-qualification-lineage.v1"
    assert lineage["lineage_id"] == "rq-01"
    assert isinstance(lineage["targets"], dict)


def test_candidate_registry_hash_matches_independent_recomputation() -> None:
    lineage = _lineage()
    observed = _sha256_file(CANDIDATE_REGISTRY_PATH)
    assert lineage["candidate_registry_sha256"] == observed.removeprefix("sha256:")


def test_protocol_hash_matches_independent_recomputation() -> None:
    lineage = _lineage()
    observed = _sha256_file(PROTOCOL_PATH)
    assert lineage["protocol_sha256"] == observed.removeprefix("sha256:")


def test_candidate_registry_hash_also_matches_the_frozen_protocol_pin() -> None:
    # Cross-check: lineage.json's own recomputation must agree with the
    # hash the SEM-RISK-CONF-02 protocol independently froze for the same file.
    lineage = _lineage()
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    pinned = protocol["source_hashes"]["benchmark/v6/candidate-registry.yaml"]
    assert pinned.removeprefix("sha256:") == lineage["candidate_registry_sha256"]


def test_paid_capacity_and_ghcr_push_flags_are_false() -> None:
    lineage = _lineage()
    assert lineage["paid_capacity_ready"] is False
    assert lineage["ghcr_push_performed"] is False


def test_no_new_directory_was_created_under_research_experiments() -> None:
    # The lineage explicitly lives under infra/runpod/v6/qualification/rq-01/,
    # not under research/experiments/ (see its README's rationale). No
    # directory name there should reference this lineage.
    for entry in EXPERIMENTS_DIR.iterdir():
        if not entry.is_dir():
            continue
        lowered = entry.name.lower()
        assert "rq-01" not in lowered
        assert "runtime-qualification" not in lowered
        assert "runtime_qualification" not in lowered
