"""Core output budget (F0) and directoryPlan source-id dedupe (F1)."""

from __future__ import annotations

import hashlib
import importlib
import json

import pytest
from akc_cir.base import canonical_json
from akc_product_core import ProductCoreCompiler, ProductCoreCompileRequest, api
from akc_product_core.api import ProductCoreService
from akc_product_core.compiler import (
    OUTPUT_BUDGET_BYTES,
    CoreOutputTooLargeError,
    wire_payload,
)

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


COUNT_KEYS = {"regions", "claims", "contradictionPairs", "files"}


def _sizes() -> tuple[int, int]:
    """(package file bytes, serialised candidate bytes) of the fixture at the default budget."""
    candidate = (
        ProductCoreCompiler(core_release_digest=RELEASE)
        .compile(_fixture(), input_sha256=_sha("budget"))
        .candidate
    )
    package = sum(file.size_bytes for file in candidate.package.files)
    return package, len(canonical_json(wire_payload(candidate)).encode("utf-8"))


def _assert_counts(detail: dict[str, object]) -> None:
    counts = detail["counts"]
    assert isinstance(counts, dict)
    assert set(counts) == COUNT_KEYS
    assert counts["regions"] == 32
    assert counts["files"] == 28
    assert counts["claims"] > 0
    # 30 same-topic fragments with differing numbers already pair quadratically.
    assert counts["contradictionPairs"] > 400


def test_candidate_at_the_budget_compiles() -> None:
    package, candidate = _sizes()
    assert candidate > package

    response = ProductCoreCompiler(
        core_release_digest=RELEASE, output_budget_bytes=candidate
    ).compile(_fixture(), input_sha256=_sha("budget"))

    assert len(canonical_json(wire_payload(response.candidate)).encode("utf-8")) == candidate


def test_candidate_one_byte_over_the_budget_is_refused_before_any_receipt() -> None:
    _, candidate = _sizes()

    with pytest.raises(CoreOutputTooLargeError) as refused:
        ProductCoreCompiler(core_release_digest=RELEASE, output_budget_bytes=candidate - 1).compile(
            _fixture(), input_sha256=_sha("budget")
        )

    detail = refused.value.detail
    assert detail["object"] == "core-candidate"
    assert detail["bytes"] == candidate
    assert detail["budget"] == candidate - 1
    _assert_counts(detail)


def test_package_over_the_budget_is_refused_on_the_probe_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, _ = _sizes()

    def not_reached(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the package was checked and rebuilt before the refusal")

    monkeypatch.setattr(ProductCoreCompiler, "_validation_checks", not_reached)
    with pytest.raises(CoreOutputTooLargeError) as refused:
        ProductCoreCompiler(core_release_digest=RELEASE, output_budget_bytes=package // 2).compile(
            _fixture(), input_sha256=_sha("budget")
        )

    detail = refused.value.detail
    assert detail["object"] == "core-package"
    assert int(str(detail["bytes"])) > package // 2
    _assert_counts(detail)


def test_service_refusal_is_named_logged_cached_and_carries_no_package(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, candidate = _sizes()
    service = ProductCoreService(
        hmac_secret=SECRET, core_release_digest=RELEASE, output_budget_bytes=candidate - 1
    )
    request = _fixture()
    body = canonical_json(request.model_dump(mode="json", by_alias=True, exclude_none=True))

    status, payload = service.compile(
        body=body.encode(), headers=_signed(body.encode(), request.request_id)
    )

    assert status == 422
    assert set(payload) == {"code", "object", "bytes", "budget", "counts"}
    assert payload["code"] == "CORE_OUTPUT_TOO_LARGE"
    assert payload["object"] == "core-candidate"
    assert payload["bytes"] == candidate
    assert payload["budget"] == candidate - 1
    _assert_counts(payload)

    # One numbers-only line, nothing from the document.
    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(lines) == 1
    logged = json.loads(lines[0])
    assert logged == {
        "event": "core_output_too_large",
        "requestId": request.request_id,
        **{key: value for key, value in payload.items() if key != "code"},
    }

    # The same work under the same key is refused again without recompiling.
    def not_recompiled(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a cached refusal was recompiled")

    monkeypatch.setattr(service.compiler, "compile", not_recompiled)
    again = service.compile(body=body.encode(), headers=_signed(body.encode(), request.request_id))
    assert again == (422, payload)


@pytest.mark.parametrize("budget", [0, -1, OUTPUT_BUDGET_BYTES + 1])
def test_budget_can_only_be_lowered(budget: int) -> None:
    with pytest.raises(ValueError, match="output budget"):
        ProductCoreCompiler(core_release_digest=RELEASE, output_budget_bytes=budget)


@pytest.mark.parametrize("value", [str(OUTPUT_BUDGET_BYTES + 1), "0", "32MiB"])
def test_environment_budget_that_is_not_a_lowering_fails_the_process_by_name(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("TAVONEL_PRODUCT_CORE_HMAC", SECRET.decode())
    monkeypatch.setenv("TAVONEL_CORE_RELEASE_DIGEST", RELEASE)
    monkeypatch.setenv("TAVONEL_CORE_OUTPUT_BUDGET_BYTES", value)
    with pytest.raises(RuntimeError, match="TAVONEL_CORE_OUTPUT_BUDGET_BYTES"):
        importlib.reload(importlib.import_module("akc_product_core.__main__"))


def test_environment_budget_lowering_is_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVONEL_PRODUCT_CORE_HMAC", SECRET.decode())
    monkeypatch.setenv("TAVONEL_CORE_RELEASE_DIGEST", RELEASE)
    monkeypatch.setenv("TAVONEL_CORE_OUTPUT_BUDGET_BYTES", "1024")
    main = importlib.reload(importlib.import_module("akc_product_core.__main__"))
    assert main.app.state.product_core_service.compiler.output_budget_bytes == 1024


def _post(service: ProductCoreService, request_id: str) -> int:
    request = _request(
        (_document("filing-a", f"Revenue for {request_id} is 1 won."),), request_id=request_id
    )
    body = canonical_json(
        request.model_dump(mode="json", by_alias=True, exclude_none=True)
    ).encode()
    status, _ = service.compile(body=body, headers=_signed(body, request_id))
    return status


def test_idempotency_cache_evicts_least_recently_used_by_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "CACHE_MAX_ENTRIES", 2)
    service = ProductCoreService(hmac_secret=SECRET, core_release_digest=RELEASE)

    assert [_post(service, rid) for rid in ("c-1", "c-2")] == [200, 200]
    assert _post(service, "c-1") == 200  # replay: c-1 becomes the most recently used
    assert _post(service, "c-3") == 200

    assert [key[2] for key in service._cache] == ["idem-c-1", "idem-c-3"]
    assert service._cache_bytes == sum(entry.size_bytes for entry in service._cache.values())


def test_idempotency_cache_evicts_by_total_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ProductCoreService(hmac_secret=SECRET, core_release_digest=RELEASE)
    assert _post(service, "b-1") == 200
    one_entry = service._cache_bytes
    assert one_entry > 0
    monkeypatch.setattr(api, "CACHE_MAX_BYTES", one_entry + one_entry // 2)

    assert _post(service, "b-2") == 200

    assert [key[2] for key in service._cache] == ["idem-b-2"]
    assert (
        service._cache_bytes
        == service._cache[
            "tenant-foundation-pilot", "workspace-foundation-pilot", "idem-b-2"
        ].size_bytes
    )
