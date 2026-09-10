from __future__ import annotations

import json
from pathlib import Path

import pytest

from .prepare_candidate_inventory import CandidateInventoryError, prepare_inventory


def _write_protocol(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "benchmark_id": "TEST",
                "required_classes": ["a", "b"],
                "source_selection": {"selected_units_per_class": 2},
            }
        ),
        encoding="utf-8",
    )


def _seed(source_class: str, index: int) -> dict[str, object]:
    return {
        "candidate_id": f"{source_class}-{index}",
        "source_class": source_class,
        "source_url": f"https://official.example.invalid/{source_class}/{index}",
        "source_family_id": f"family-{source_class}-{index}",
        "publisher": "Official publisher",
        "language": "en",
        "rights_status": "public_research_allowed",
        "rights_evidence_url": "https://rights.example.invalid/item",
        "rights_checked_at_utc": "2026-09-10T00:00:00Z",
        "allowed_use_scope": "local_research_evaluation_no_redistribution",
        "target_locator_rule": "whole_source",
    }


def _world(tmp_path: Path) -> tuple[Path, Path]:
    protocol = tmp_path / "protocol.json"
    _write_protocol(protocol)
    seeds = [_seed(source_class, index) for source_class in ("a", "b") for index in range(3)]
    seed_path = tmp_path / "seeds.jsonl"
    seed_path.write_text(
        "".join(json.dumps(seed) + "\n" for seed in reversed(seeds)), encoding="utf-8"
    )
    return protocol, seed_path


def test_inventory_selection_is_exact_deterministic_and_truth_free(tmp_path: Path) -> None:
    protocol, seeds = _world(tmp_path)
    first = prepare_inventory(protocol_path=protocol, seeds_path=seeds)
    second = prepare_inventory(protocol_path=protocol, seeds_path=seeds)
    assert first == second
    assert first["selected_units"] == 4
    assert first["source_content_accessed"] is False
    assert first["truth_accessed"] is False
    selected = [row for row in first["candidates"] if row["selection_state"] == "SELECTED"]
    assert len(selected) == 4


def test_missing_class_denominator_is_rejected(tmp_path: Path) -> None:
    protocol, seeds = _world(tmp_path)
    rows = [json.loads(line) for line in seeds.read_text(encoding="utf-8").splitlines()]
    seeds.write_text(
        "".join(json.dumps(row) + "\n" for row in rows if row["source_class"] != "b"),
        encoding="utf-8",
    )
    with pytest.raises(CandidateInventoryError, match="CLASS_b_INSUFFICIENT_CANDIDATES"):
        prepare_inventory(protocol_path=protocol, seeds_path=seeds)


@pytest.mark.parametrize("field", ["source_url", "source_family_id", "candidate_id"])
def test_duplicate_identity_is_rejected(tmp_path: Path, field: str) -> None:
    protocol, seeds = _world(tmp_path)
    rows = [json.loads(line) for line in seeds.read_text(encoding="utf-8").splitlines()]
    rows[1][field] = rows[0][field]
    seeds.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises(CandidateInventoryError, match="DUPLICATE"):
        prepare_inventory(protocol_path=protocol, seeds_path=seeds)


def test_truth_or_unknown_metadata_is_rejected(tmp_path: Path) -> None:
    protocol, seeds = _world(tmp_path)
    rows = [json.loads(line) for line in seeds.read_text(encoding="utf-8").splitlines()]
    rows[0]["expected_answer"] = "secret"
    seeds.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises(CandidateInventoryError, match="SCHEMA_INVALID"):
        prepare_inventory(protocol_path=protocol, seeds_path=seeds)
