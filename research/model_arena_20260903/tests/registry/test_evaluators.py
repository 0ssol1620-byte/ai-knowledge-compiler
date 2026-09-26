"""Evaluator pin resolution, including the ParseBench move that must not be silent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from arena.constants import BENCHMARK_KEYS, HISTORICAL_EVALUATOR_PINS
from arena.registry.errors import RegistryError, SourceUnavailableError
from arena.registry.evaluators import (
    EVALUATOR_REPOSITORIES,
    GT_PATHS,
    OBSERVED_HEADS,
    OLMOCR_TOOLKIT_REPOSITORY,
    LiveGitRefResolver,
    RecordedGitRefResolver,
    load_benchmark_lock,
    missing_gt_paths,
    resolve_evaluators,
)


def _recorded_resolver(**overrides: str) -> RecordedGitRefResolver:
    heads = {url: OBSERVED_HEADS[key] for key, url in EVALUATOR_REPOSITORIES.items()}
    heads[OLMOCR_TOOLKIT_REPOSITORY] = OBSERVED_HEADS["_olmocr_toolkit"]
    for benchmark, sha in overrides.items():
        heads[EVALUATOR_REPOSITORIES[benchmark]] = sha
    return RecordedGitRefResolver(heads)


@pytest.fixture(scope="module")
def registry() -> dict[str, Any]:
    return resolve_evaluators(_recorded_resolver())


def test_benchmark_lock_is_readable_and_has_all_three_suites() -> None:
    lock = load_benchmark_lock()
    assert {"omnidocbench", "parsebench", "olmocr-bench"} <= set(lock)


def test_lock_missing_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="not found"):
        load_benchmark_lock(tmp_path / "absent.yaml")


def test_every_benchmark_key_is_resolved(registry: dict[str, Any]) -> None:
    assert set(registry["evaluators"]) == set(BENCHMARK_KEYS)
    assert registry["evaluator_count"] == 3


@pytest.mark.parametrize("benchmark", sorted(BENCHMARK_KEYS))
def test_dataset_identity_comes_from_the_lock(
    benchmark: str, registry: dict[str, Any]
) -> None:
    record = registry["evaluators"][benchmark]
    assert record["dataset_repository"]
    assert len(str(record["dataset_revision"])) == 40
    assert str(record["dataset_manifest_sha256"]).startswith("sha256:")
    assert record["lock_source"] == "benchmark/benchmark-registry.lock.yaml"
    assert record["frozen"] is False


@pytest.mark.parametrize("benchmark", sorted(BENCHMARK_KEYS))
def test_gt_paths_stay_inside_the_acquired_tree(
    benchmark: str, registry: dict[str, Any]
) -> None:
    paths = registry["evaluators"][benchmark]["gt_paths"]
    assert paths
    for path in paths:
        assert path.startswith("benchmark/datasets/acquired/public-core/")


def test_parsebench_pin_moved_and_keeps_the_historical_lane(
    registry: dict[str, Any],
) -> None:
    record = registry["evaluators"]["parsebench"]
    assert record["historical_pin"] == HISTORICAL_EVALUATOR_PINS["parsebench"]
    assert record["main_pin"] == "45298128406f5bcc3942ccf97c618af15289770c"
    assert record["moved_since_historical_pin"] is True
    assert record["historical_lane_required"] is True
    summary = record["upstream_diff_summary"]
    assert summary["scoring_semantics_changed"] is True
    assert summary["dataset_contract_changed"] is False
    assert summary["cli_contract_changed"] is False
    assert len(summary["scoring_changes"]) >= 2


@pytest.mark.parametrize("benchmark", ["omnidoc", "olmocr"])
def test_unmoved_evaluators_need_no_second_lane(
    benchmark: str, registry: dict[str, Any]
) -> None:
    record = registry["evaluators"][benchmark]
    assert record["main_pin"] == record["historical_pin"]
    assert record["moved_since_historical_pin"] is False
    assert record["historical_lane_required"] is False


def test_olmocr_records_its_absent_licence(registry: dict[str, Any]) -> None:
    record = registry["evaluators"]["olmocr"]
    assert record["license"] == "upstream-license-file-absent"
    assert "Readable is not reusable" in record["license_note"]


def test_olmocr_toolkit_revision_is_pinned_alongside(registry: dict[str, Any]) -> None:
    toolkit = registry["olmocr_toolkit"]
    assert toolkit["revision"] == "f7cfe4c22098b154c76b6ec950d1c0a464eecf8d"
    assert toolkit["repository"] == OLMOCR_TOOLKIT_REPOSITORY


def test_an_unreviewed_upstream_move_fails_closed() -> None:
    moved = "0" * 39 + "1"
    with pytest.raises(RegistryError, match="only ParseBench has a reviewed"):
        resolve_evaluators(_recorded_resolver(omnidoc=moved))


def test_a_non_hex_head_fails_closed() -> None:
    with pytest.raises(SourceUnavailableError, match="not a 40-hex"):
        resolve_evaluators(_recorded_resolver(parsebench="HEAD-of-main"))


def test_a_missing_recorded_head_fails_closed() -> None:
    resolver = RecordedGitRefResolver({})
    with pytest.raises(SourceUnavailableError, match="no recorded head"):
        resolve_evaluators(resolver)


def test_live_resolver_rejects_a_url_it_cannot_reach() -> None:
    resolver = LiveGitRefResolver(timeout_seconds=5.0)
    with pytest.raises(SourceUnavailableError, match="failed"):
        resolver.head("https://github.invalid/does/not-exist.git")


def test_gt_presence_is_observed_not_asserted(tmp_path: Path) -> None:
    # An empty root has none of them; the helper reports that instead of raising,
    # because benchmark/datasets/acquired/ is git-ignored and may legitimately be
    # absent on a machine that is not running evaluators.
    missing = missing_gt_paths("omnidoc", repo_root=tmp_path)
    assert missing == list(GT_PATHS["omnidoc"])


def test_gt_presence_is_recorded_on_every_record(registry: dict[str, Any]) -> None:
    for benchmark in BENCHMARK_KEYS:
        record = registry["evaluators"][benchmark]
        assert isinstance(record["gt_paths_present_on_resolution_host"], bool)
        assert isinstance(record["gt_paths_missing_on_resolution_host"], list)
        assert record["gt_paths_present_on_resolution_host"] == (
            not record["gt_paths_missing_on_resolution_host"]
        )
