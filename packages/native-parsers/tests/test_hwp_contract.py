from __future__ import annotations

import hashlib

import pytest
from akc_native_parsers.hwp_contract import (
    Accepted,
    FixtureEngine,
    Held,
    HwpAdapterRequest,
    HwpAdapterResult,
    HwpBlock,
    HwpManifest,
    ResourceReceipt,
    UnavailableEngine,
    build_result,
    run_engine,
)
from pydantic import ValidationError

DATA = b"synthetic bytes"


def _request(**over: object) -> HwpAdapterRequest:
    base: dict[str, object] = {
        "job_id": "job-1",
        "source_handle": "src_0001",
        "source_sha256": hashlib.sha256(DATA).hexdigest(),
        "declared_format": "hwp5",
        "authorized_scope_ref": "scope-1",
        "parser_profile": "fixture:complex_table",
        "max_bytes": 1024,
        "max_runtime_ms": 1000,
    }
    base.update(over)
    return HwpAdapterRequest(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "handle",
    ["C:/x/y.hwp", "a/b/c", "a\\b\\c", "file:///etc/passwd", "../abc", "http://x.y/z"],
)
def test_request_rejects_paths_and_urls_in_source_handle(handle: str) -> None:
    with pytest.raises(ValidationError):
        _request(source_handle=handle)


def test_request_model_policy_is_none_only() -> None:
    with pytest.raises(ValidationError):
        _request(model_policy="ocr")


def test_result_hash_is_deterministic_for_identical_input() -> None:
    a = FixtureEngine().parse(DATA, _request())
    b = FixtureEngine().parse(DATA, _request())
    assert a.artifact_hashes["result_sha256"] == b.artifact_hashes["result_sha256"]
    assert a.model_dump_json() == b.model_dump_json()
    tampered = a.model_dump(mode="json", by_alias=True)
    tampered["blocks"][0]["text"] = "changed"
    with pytest.raises(ValidationError):
        HwpAdapterResult.model_validate(tampered)


def test_result_over_block_or_text_caps_is_rejected() -> None:
    block = HwpBlock(
        id="b1", kind="paragraph", text="x", bbox_or_element_anchor="a", original_ref="a"
    )
    manifest = HwpManifest(source_sha256="0" * 64, detected_format="hwp5")
    receipt = ResourceReceipt(wall_ms=0, input_bytes=1, output_bytes=0, exit_code=0)
    with pytest.raises(ValidationError):
        build_result(
            engine_id="t",
            engine_version="1",
            manifest=manifest,
            blocks=(block,) * 50_001,
            resource_receipt=receipt,
        )
    huge = block.model_copy(update={"text": "x" * 10_000_001})
    with pytest.raises(ValidationError):
        build_result(
            engine_id="t",
            engine_version="1",
            manifest=manifest,
            blocks=(huge,),
            resource_receipt=receipt,
        )


def test_anchor_and_ref_reject_absolute_paths_and_urls() -> None:
    for bad in ("C:\\docs\\a.hwp", "/home/u/a.hwp", "https://x.test/a"):
        with pytest.raises(ValidationError):
            HwpBlock(id="b", kind="paragraph", bbox_or_element_anchor="a", original_ref=bad)


def test_confidence_none_is_kept_not_defaulted() -> None:
    result = FixtureEngine().parse(DATA, _request())
    assert all(b.confidence is None for b in result.blocks)
    assert all(b.verification_state == "native_unverified" for b in result.blocks)


def test_table_grid_keeps_spans_and_image_region_keeps_anchor() -> None:
    table = FixtureEngine().parse(DATA, _request()).blocks[1]
    assert table.table_grid is not None and table.table_grid[0].col_span == 2
    image = FixtureEngine().parse(DATA, _request(parser_profile="fixture:embedded_image"))
    assert image.unresolved_regions[0].anchor == "section0/pic1"
    assert image.unresolved_regions[0].critical is True


@pytest.mark.parametrize("fmt", ["hwp3", "hwp5", "hwpx", "hwpml", "unknown"])
def test_unavailable_engine_holds_every_input(fmt: str) -> None:
    outcome = run_engine(UnavailableEngine(), DATA, _request(declared_format=fmt))
    assert isinstance(outcome, Held) and outcome.reason_code == "HWP_ENGINE_UNAVAILABLE"


def test_fixture_engine_outcomes() -> None:
    assert isinstance(run_engine(FixtureEngine(), DATA, _request()), Accepted)
    enc = run_engine(FixtureEngine(), DATA, _request(parser_profile="fixture:encrypted"))
    assert isinstance(enc, Held) and enc.reason_code == "HWP_ENCRYPTED"
    junk = run_engine(FixtureEngine(), DATA, _request(parser_profile="fixture:garbage_output"))
    assert isinstance(junk, Held) and junk.reason_code == "PARSER_RESULT_INVALID"
    mismatch = FixtureEngine().parse(DATA, _request(parser_profile="fixture:hash_mismatch"))
    assert mismatch.manifest.source_sha256 != _request().source_sha256
    unknown = run_engine(FixtureEngine(), DATA, _request(parser_profile="nope"))
    assert isinstance(unknown, Held) and unknown.reason_code == "HWP_ENGINE_UNAVAILABLE"


def test_held_rejects_unknown_reason_code() -> None:
    with pytest.raises(ValidationError):
        Held(reason_code="SOMETHING_ELSE")
