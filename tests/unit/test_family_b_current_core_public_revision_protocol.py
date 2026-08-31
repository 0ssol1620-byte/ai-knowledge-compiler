from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / "research" / "experiments" / "H3-B-CURRENT-CORE-PUBLIC-REVISION-01"
PROTOCOL = EXPERIMENT / "protocol.json"
RUNNER = EXPERIMENT / "run_experiment.py"

PREVIOUSLY_USED_TITLES = {
    "Artificial intelligence",
    "Machine learning",
    "Large language model",
    "Quantum computing",
    "Climate change",
    "CRISPR",
    "Bitcoin",
    "Kubernetes",
    "Rust (programming language)",
    "JSON",
    "World Wide Web",
    "Cryptography",
    "Artificial general intelligence",
    "Generative artificial intelligence",
    "Gemini (language model)",
    "Claude (language model)",
    "Meta AI",
    "Apple Intelligence",
    "Robotics",
    "Self-driving car",
    "Solar power",
    "Nuclear power",
    "Space exploration",
    "Mars",
}


def _load_runner():
    spec = importlib.util.spec_from_file_location("h3_b_current_core_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_protocol_is_pre_registered_without_performance_pass_threshold() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))

    assert protocol["status"] == "PREPARED_BEFORE_FETCH"
    assert protocol["integrity"]["freeze_before_fetch"] is True
    assert protocol["cost_policy"]["external_gpu_allowed"] is False
    assert protocol["cost_policy"]["external_gpu_cost_usd"] == 0.0
    assert protocol["frozen_safety_gates"] == {
        "all_evaluated_pairs_equivalent": True,
        "stale_left_behind_total": 0,
        "minimum_changed_pair_count": 8,
    }
    assert "mean_rebuild_fraction" in protocol[
        "performance_metrics_are_measurements_not_pass_gates"
    ]
    assert "max_rebuild_fraction" in protocol[
        "performance_metrics_are_measurements_not_pass_gates"
    ]


def test_title_set_is_unique_and_disjoint_from_known_prior_public_revision_sets() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    titles = protocol["titles"]

    assert len(titles) == 12
    assert len(set(titles)) == 12
    assert set(titles).isdisjoint(PREVIOUSLY_USED_TITLES)


def test_frozen_hash_verification_fails_closed_on_drift(tmp_path: Path) -> None:
    runner = _load_runner()
    target = tmp_path / "frozen.txt"
    target.write_text("before", encoding="utf-8")
    expected = {"frozen.txt": runner.sha_file(target)}

    runner.verify_hash_map(expected, root=tmp_path)
    target.write_text("after", encoding="utf-8")

    with pytest.raises(RuntimeError, match="frozen input drift"):
        runner.verify_hash_map(expected, root=tmp_path)


def test_live_core_hash_inputs_exist_before_freeze() -> None:
    runner = _load_runner()

    assert runner.PROTOCOL.is_file()
    assert runner.Path(runner.__file__).is_file()
    for relative in runner.LIVE_INPUTS:
        assert (runner.ROOT / relative).is_file(), relative


def test_offline_pair_execution_exercises_current_core_before_freeze() -> None:
    runner = _load_runner()
    filler = " ".join(["stable evidence sentence"] * 14)
    before = runner.Revision(
        requested_title="Synthetic current-core smoke",
        resolved_title="Synthetic current-core smoke",
        revid=100,
        parentid=99,
        timestamp="2026-07-30T00:00:00Z",
        mw_sha1="before",
        text=f"== Architecture ==\n{filler} release version is 1.5.3.",
    )
    after = runner.Revision(
        requested_title="Synthetic current-core smoke",
        resolved_title="Synthetic current-core smoke",
        revid=101,
        parentid=100,
        timestamp="2026-07-31T00:00:00Z",
        mw_sha1="after",
        text=f"== Architecture ==\n{filler} release version is 1.5.4.",
    )

    record = runner.run_pair(before, after, set())

    assert record["artifact_count"] > 0
    assert record["changed_logical_id_count"] >= 1
    assert 0.0 <= record["rebuild_fraction"] <= 1.0
    assert 0.0 <= record["work_avoided_fraction"] <= 1.0
    assert record["equivalent"] is True
    assert record["stale_left_behind"] == []
