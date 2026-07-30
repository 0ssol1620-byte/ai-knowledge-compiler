from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.operational.run_matrix import load_matrix, resolve_command, run_scenario

HERE = Path(__file__).parent


def test_matrix_is_schema_valid_and_has_unique_ids() -> None:
    matrix = load_matrix()
    schema = json.loads(
        (HERE / "scenario-matrix.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(matrix)
    ids = [scenario["id"] for scenario in matrix["scenarios"]]
    assert len(ids) == len(set(ids))


def test_matrix_covers_every_required_operational_scenario() -> None:
    matrix = load_matrix()
    names = " ".join(scenario["name"] for scenario in matrix["scenarios"])
    required_terms = {
        "fairness",
        "duplicate dispatch",
        "duplicate provider completion",
        "callback loss",
        "429",
        "5xx",
        "out-of-memory",
        "acknowledgement loss",
        "expired",
        "partial deletion",
        "Redis",
        "rollback",
        "clock skew",
        "API restart",
        "PostgreSQL restart",
        "SSE",
        "uploads",
        "ten-thousand-page",
        "export burst",
    }
    assert all(term in names for term in required_terms)


def test_external_profiles_are_declared_and_fail_closed() -> None:
    matrix = load_matrix()
    profiles: dict[str, Any] = json.loads(
        (HERE.parent / "load" / "profiles.json").read_text(encoding="utf-8")
    )
    assert profiles["safety"] == {
        "required_confirmation": "NONPRODUCTION_LOAD_ONLY",
        "remote_https_required": True,
        "exact_origin_allowlist_required": True,
        "customer_data_permitted": False,
        "automatic_production_execution": False,
    }
    external = {
        scenario["profile"]
        for scenario in matrix["scenarios"]
        if scenario["class"] == "external_scale"
    }
    assert external == set(profiles["profiles"])
    for profile in profiles["profiles"].values():
        script = HERE.parents[1] / profile["script"]
        assert script.is_file(), profile["script"]
    with pytest.raises(ValueError, match="approved deployment"):
        run_scenario(
            next(
                scenario
                for scenario in matrix["scenarios"]
                if scenario["class"] == "external_scale"
            )
        )


def test_manual_chaos_never_runs_through_automatic_matrix() -> None:
    chaos = next(
        scenario
        for scenario in load_matrix()["scenarios"]
        if scenario["class"] == "guarded_local_chaos"
    )
    with pytest.raises(ValueError, match="operator opt-in"):
        run_scenario(chaos)


def test_python_placeholder_is_not_shell_expansion() -> None:
    command = resolve_command(["{python}", "-m", "pytest"])
    assert command[0]
    assert command[1:] == ["-m", "pytest"]
