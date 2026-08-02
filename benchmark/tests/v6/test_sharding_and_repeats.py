from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from benchmark.v6.contracts import ContractError, EnvironmentIdentity
from benchmark.v6.repeats import (
    build_exact_repeat_plan,
    materialize_repeat_plan,
    validate_repeat_plan,
)
from benchmark.v6.sharding import (
    PageManifestEntry,
    plan_document_shards,
    validate_shard_plan,
)


def _pages() -> list[PageManifestEntry]:
    return [
        PageManifestEntry("doc-b", 2, "b-2", "sha256:" + "2" * 64, 8.0, "cross_page_table"),
        PageManifestEntry("doc-a", 1, "a-1", "sha256:" + "3" * 64, 1.0, "native_pdf"),
        PageManifestEntry("doc-b", 1, "b-1", "sha256:" + "4" * 64, 7.0, "cross_page_table"),
        PageManifestEntry("doc-c", 1, "c-1", "sha256:" + "5" * 64, 2.0, "scan"),
        PageManifestEntry("doc-b", 3, "b-3", "sha256:" + "6" * 64, 9.0, "cross_page_table"),
    ]


def test_deterministic_shards_are_order_independent_and_preserve_documents() -> None:
    pages = _pages()
    first = plan_document_shards(pages, shard_count=4, namespace="parsebench@revision")
    second = plan_document_shards(reversed(pages), shard_count=4, namespace="parsebench@revision")

    assert [shard.to_dict() for shard in first] == [shard.to_dict() for shard in second]
    owners = {page.document_id: shard.shard_index for shard in first for page in shard.pages}
    assert len({owners["doc-b"]}) == 1
    assert [
        page.page_number for shard in first for page in shard.pages if page.document_id == "doc-b"
    ] == [1, 2, 3]
    receipt = validate_shard_plan(pages, first, namespace="parsebench@revision")
    assert receipt["no_page_loss"] is True
    assert receipt["document_context_preserved"] is True


def test_shard_validation_rejects_page_loss_and_manifest_tampering() -> None:
    pages = _pages()
    shards = list(plan_document_shards(pages, shard_count=2, namespace="suite@sha"))
    occupied_index = next(index for index, shard in enumerate(shards) if shard.pages)
    occupied = shards[occupied_index]
    shards[occupied_index] = replace(occupied, pages=occupied.pages[:-1])

    with pytest.raises(ContractError, match="coverage mismatch"):
        validate_shard_plan(pages, shards, namespace="suite@sha")


def test_exact_three_repeat_plan_has_same_identity_and_isolated_roots(
    tmp_path: Path,
    environment: EnvironmentIdentity,
) -> None:
    runs = build_exact_repeat_plan(
        base_root=tmp_path,
        benchmark_id="parsebench",
        environment=environment,
    )
    receipt = validate_repeat_plan(runs)

    assert [run.repeat_index for run in runs] == [1, 2, 3]
    assert len({run.environment_sha256 for run in runs}) == 1
    assert len({run.prediction_root for run in runs}) == 3
    assert len({run.log_root for run in runs}) == 3
    assert receipt["passed"] is True

    materialize_repeat_plan(runs)
    for run in runs:
        assert (run.repeat_root / "repeat-contract.json").is_file()
        assert run.prediction_root.is_dir()
        assert run.log_root.is_dir()


def test_repeat_validation_rejects_incomplete_or_mixed_environment(
    tmp_path: Path,
    environment: EnvironmentIdentity,
) -> None:
    runs = list(
        build_exact_repeat_plan(
            base_root=tmp_path,
            benchmark_id="omnidocbench",
            environment=environment,
        )
    )
    with pytest.raises(ContractError, match="exactly three"):
        validate_repeat_plan(runs[:2])
    runs[2] = replace(runs[2], environment_sha256="sha256:" + "9" * 64)
    with pytest.raises(ContractError, match="environment_sha256"):
        validate_repeat_plan(runs)
