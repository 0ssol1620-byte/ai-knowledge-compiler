from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import cast

import pytest
import yaml

from benchmark.v6.contracts import ContractError, canonical_sha256
from benchmark.v6.preflight import _validate_champion_matrix, run_local_preflight


def test_local_preflight_passes_contracts_but_rejects_production(repo_root: Path) -> None:
    result = run_local_preflight(repo_root)

    assert result["local_contract_gate"] == "pass"
    assert result["production_gate"] == "reject"
    assert result["production_evidence"] is False
    assert result["paid_endpoints_created_by_preflight"] == 0
    assert result["external_runs_completed_by_preflight"] == 0
    assert cast(int, result["candidate_count"]) >= 45
    assert result["required_candidate_count"] == 28
    assert result["model_revisions_pinned_count"] == 20
    assert result["required_model_revisions_pinned_count"] == 18
    assert result["required_candidates_promotion_eligible"] == 0
    assert result["model_pool_count"] == 16
    assert result["public_core_required_repetitions"] == 3
    blockers = cast(list[str], result["external_blockers"])
    assert "SIGNED_EXTERNAL_EVIDENCE_MISSING" in blockers


def _champion_contract(repo_root: Path) -> tuple[dict[str, object], dict[str, object]]:
    matrix = yaml.safe_load(
        (repo_root / "benchmark/v6/champion-matrix.yaml").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (repo_root / "benchmark/v6/schemas/champion-matrix.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert isinstance(matrix, dict) and isinstance(schema, dict)
    return matrix, schema


def _rehash(matrix: dict[str, object]) -> None:
    material = copy.deepcopy(matrix)
    material.pop("matrix_sha256", None)
    matrix["matrix_sha256"] = canonical_sha256(material)


def test_champion_matrix_artifact_is_schema_valid_and_content_addressed(repo_root: Path) -> None:
    matrix, schema = _champion_contract(repo_root)
    _validate_champion_matrix(matrix, schema)

    wrong_hash = copy.deepcopy(matrix)
    wrong_hash["matrix_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ContractError, match="digest mismatch"):
        _validate_champion_matrix(wrong_hash, schema)

    unexpected = copy.deepcopy(matrix)
    unexpected["status"] = "production_reject"
    with pytest.raises(ContractError, match="schema violation"):
        _validate_champion_matrix(unexpected, schema)


def test_champion_matrix_rejects_incoherent_primary_status_and_evidence(repo_root: Path) -> None:
    matrix, schema = _champion_contract(repo_root)
    rows = cast(dict[str, dict[str, object]], matrix["champions"])

    unresolved_as_production = copy.deepcopy(matrix)
    cast(dict[str, dict[str, object]], unresolved_as_production["champions"])["native_pdf"][
        "status"
    ] = "production"
    _rehash(unresolved_as_production)
    with pytest.raises(ContractError, match="internally inconsistent"):
        _validate_champion_matrix(unresolved_as_production, schema)

    primary_without_evidence = copy.deepcopy(matrix)
    primary_row = cast(
        dict[str, dict[str, object]], primary_without_evidence["champions"]
    )["native_pdf"]
    primary_row["primary"] = "candidate-ready"
    primary_row["status"] = "production"
    primary_row["selection_basis"] = "measured_benchmark"
    assert rows["native_pdf"]["evidence_sha256"] is None
    _rehash(primary_without_evidence)
    with pytest.raises(ContractError, match="lacks signed evidence"):
        _validate_champion_matrix(primary_without_evidence, schema)
