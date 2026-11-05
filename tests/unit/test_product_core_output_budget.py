"""Core output budget (F0) and directoryPlan source-id dedupe (F1)."""

from __future__ import annotations

import hashlib
import importlib

import pytest
from akc_cir.base import canonical_json
from akc_product_core import ProductCoreCompiler, ProductCoreCompileRequest
from akc_product_core.api import ProductCoreService
from akc_product_core.compiler import OUTPUT_BUDGET_BYTES, CoreOutputTooLargeError

from .test_product_core_api import SECRET, _signed
from .test_product_core_bridge import RELEASE, _document, _fragmented_document, _request, _sha


def _fixture() -> ProductCoreCompileRequest:
    return _request(
        (
            _fragmented_document("filing-a"),
            _document("filing-b", "Revenue is 100 million won."),
            _document("filing-c", "Revenue is 200 million won."),
        ),
        request_id="golden",
    )


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _package_bytes() -> int:
    response = ProductCoreCompiler(core_release_digest=RELEASE).compile(
        _fixture(), input_sha256=_sha("budget")
    )
    return sum(file.size_bytes for file in response.candidate.package.files)


def test_directory_plan_dedupe_leaves_every_world_digest_unchanged() -> None:
    # Pinned from b187576 (the live Core bundle, before the dedupe). directoryPlan is not an
    # input to any of these; if one moves, the dedupe touched a digest and needs the ladder.
    candidate = (
        ProductCoreCompiler(core_release_digest=RELEASE)
        .compile(_fixture(), input_sha256=_sha("golden"))
        .candidate
    )

    assert candidate.world_state_id == (
        "ws_05c90e1975a9036109d15c52456a2a7a84a5027ba300aeccee44fd86af080fab"
    )
    assert candidate.manifest_digest == (
        "sha256:7b65d57a2afa85e09317f56068105a06d8c547caeda46fa0bbab59c22e6cd5bf"
    )
    assert _digest(candidate.artifact_hashes) == (
        "sha256:d9d4132d659996ea583b5117e7c8f0ee7b5490d473c3da077a73ac88d6841a8b"
    )
    assert _digest({file.path: file.sha256 for file in candidate.package.files}) == (
        "sha256:9f2edfedd79ca057c25ed616fc415ef901f316aa9143dde62b7ec0cb0a25275d"
    )
    sources = {unit.source_id for unit in candidate.units}
    artifact_rows = [row for row in candidate.directory_plan if row["kind"] == "artifact"]
    assert len(candidate.units) == 32
    assert len(sources) == 3
    assert artifact_rows
    # 32 regions over 3 sources: each file names each source once, not once per region.
    for row in artifact_rows:
        source_ids = row["sourceIds"]
        assert isinstance(source_ids, list)
        assert len(source_ids) == 3
        assert set(source_ids) == sources


def test_package_at_the_budget_compiles() -> None:
    size = _package_bytes()

    response = ProductCoreCompiler(core_release_digest=RELEASE, output_budget_bytes=size).compile(
        _fixture(), input_sha256=_sha("budget")
    )

    assert sum(file.size_bytes for file in response.candidate.package.files) == size


def test_package_one_byte_over_the_budget_is_refused_with_counts() -> None:
    size = _package_bytes()

    with pytest.raises(CoreOutputTooLargeError) as refused:
        ProductCoreCompiler(core_release_digest=RELEASE, output_budget_bytes=size - 1).compile(
            _fixture(), input_sha256=_sha("budget")
        )

    detail = refused.value.detail
    assert detail["bytes"] == size
    assert detail["budget"] == size - 1
    counts = detail["counts"]
    assert isinstance(counts, dict)
    assert counts["regions"] == 32
    assert counts["files"] == 28
    assert counts["claims"] > 0
    # 30 same-topic fragments with differing numbers already pair quadratically.
    assert counts["contradictionPairs"] > 400


def test_service_refusal_is_named_carries_no_package_and_is_not_cached() -> None:
    size = _package_bytes()
    service = ProductCoreService(
        hmac_secret=SECRET, core_release_digest=RELEASE, output_budget_bytes=size - 1
    )
    request = _fixture()
    body = canonical_json(request.model_dump(mode="json", by_alias=True, exclude_none=True))

    status, payload = service.compile(
        body=body.encode(), headers=_signed(body.encode(), request.request_id)
    )

    assert status == 422
    assert payload["code"] == "CORE_OUTPUT_TOO_LARGE"
    assert payload["bytes"] == size
    assert payload["budget"] == size - 1
    assert set(payload) == {"code", "bytes", "budget", "counts"}
    assert not service._cache


@pytest.mark.parametrize("budget", [0, -1, OUTPUT_BUDGET_BYTES + 1])
def test_budget_can_only_be_lowered(budget: int) -> None:
    with pytest.raises(ValueError, match="output budget"):
        ProductCoreCompiler(core_release_digest=RELEASE, output_budget_bytes=budget)


def test_environment_budget_above_the_default_fails_the_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TAVONEL_PRODUCT_CORE_HMAC", SECRET.decode())
    monkeypatch.setenv("TAVONEL_CORE_RELEASE_DIGEST", RELEASE)
    monkeypatch.setenv("TAVONEL_CORE_OUTPUT_BUDGET_BYTES", str(OUTPUT_BUDGET_BYTES + 1))
    with pytest.raises(ValueError, match="output budget"):
        importlib.reload(importlib.import_module("akc_product_core.__main__"))

    monkeypatch.setenv("TAVONEL_CORE_OUTPUT_BUDGET_BYTES", "1024")
    main = importlib.reload(importlib.import_module("akc_product_core.__main__"))
    assert main.app.state.product_core_service.compiler.output_budget_bytes == 1024
