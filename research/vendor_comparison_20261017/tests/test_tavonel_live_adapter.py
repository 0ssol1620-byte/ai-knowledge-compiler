"""AT-6: D-T-live regions -> olmOCR-bench, OmniDocBench and ParseBench input files."""

from __future__ import annotations

import hashlib
import importlib
import json
import socket
from pathlib import Path
from typing import Any

import pytest

from research.vendor_comparison_20261017.adapters import tavonel_live as tl
from research.vendor_comparison_20261017.adapters.base import Document, Pin, ReplayTransport
from research.vendor_comparison_20261017.adapters.tavonel_live_stub import (
    MAX_SOURCE_BYTES,
    TavonelLiveStub,
)

FIXTURES = Path(tl.__file__).parents[1] / "fixtures" / "evaluator_inputs"
PIN = Pin("D-T-live", "SYNTHETIC_TAVONEL_EVAL_KEY_NAME", 85.0)
OLMOCR_SOURCE = "bench_data/pdfs/table_tests/SYNTHETIC-doc.pdf"
OMNIDOC_SOURCE = "images/SYNTHETIC-page.jpg"


def _load(name: str) -> dict[str, Any]:
    path = FIXTURES / name
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    assert path.name.startswith("SYNTHETIC-tavonel_live_") and data["label"] == "SYNTHETIC"
    return data


REGIONS = _load("SYNTHETIC-tavonel_live_regions.json")
TABLE_REF = _load("SYNTHETIC-tavonel_live_table_read_reference.json")


def _regions(name: str) -> list[tl.Region]:
    return tl.read_regions(REGIONS["responses"][name])


def _parsebench(category: str, regions: list[tl.Region]) -> dict[str, Any]:
    files = tl.parsebench_result(
        f"docs/{category}/SYNTHETIC-x.pdf",
        regions,
        image_size_px=(200, 100),
        recorded_at="2026-10-17T00:00:00+00:00",
        latency_ms=1234,
    )
    assert list(files) == [f"{category}/SYNTHETIC-x.result.json"]
    text = files[f"{category}/SYNTHETIC-x.result.json"]
    assert text.endswith("\n")
    envelope: dict[str, Any] = json.loads(text)
    return envelope


def test_regions_are_read_in_page_then_order() -> None:
    regions = _regions("two_page_pdf")
    assert [(r.page, r.order) for r in regions] == [(1, 0), (1, 1), (2, 2)]
    assert regions[0] == tl.Region(1, 0, "SYNTHETIC heading-like line", (100, 100, 900, 140))


def test_olmocr_writes_one_file_per_manifest_page_and_an_empty_page_stays_empty() -> None:
    files = tl.olmocr_candidate(OLMOCR_SOURCE, _regions("two_page_pdf"), pages=3, repeat=2)
    assert files == {
        "table_tests/SYNTHETIC-doc_pg1_repeat2.md": (
            "SYNTHETIC heading-like line\n\nSYNTHETIC second paragraph."
        ),
        "table_tests/SYNTHETIC-doc_pg2_repeat2.md": "SYNTHETIC page two paragraph.",
        "table_tests/SYNTHETIC-doc_pg3_repeat2.md": "",
    }


def test_olmocr_layout_matches_the_frozen_campaign_layout() -> None:
    # The layout the FOLYNTA campaign handed to olmOCR cfa88c1e and OmniDocBench 193627ae.
    frozen = importlib.import_module("build_recovery_counterfactual_candidate")
    regions = _regions("one_page_image")
    olmocr = tl.olmocr_candidate(OLMOCR_SOURCE, regions, pages=1)
    assert list(olmocr) == [frozen.candidate_relative_path(OLMOCR_SOURCE, "_pg1_repeat1")]
    omnidoc = tl.omnidocbench_prediction(OMNIDOC_SOURCE, regions)
    assert list(omnidoc) == [frozen.candidate_relative_path(OMNIDOC_SOURCE, "", frozen.FLAT_LAYOUT)]
    parse = tl.parsebench_result(
        "docs/table/SYNTHETIC-x.pdf", regions, image_size_px=(1, 1), recorded_at="", latency_ms=0
    )
    assert list(parse) == [
        frozen.candidate_relative_path(
            "docs/table/SYNTHETIC-x.pdf", "", frozen.PARSEBENCH_RESULT_LAYOUT
        )
    ]


def test_omnidocbench_writes_one_page_per_image_and_refuses_a_second_page() -> None:
    files = tl.omnidocbench_prediction(OMNIDOC_SOURCE, _regions("one_page_image"), repeat=3)
    assert files == {
        "markdown-repeat-3/SYNTHETIC-page.md": (
            "SYNTHETIC 표 제목처럼 보이는 문단\n\nSYNTHETIC body | not a table"
        )
    }
    with pytest.raises(tl.MalformedLiveOutput, match=r"pages \[2\] beyond the source's 1"):
        tl.omnidocbench_prediction(OMNIDOC_SOURCE, _regions("two_page_pdf"))


def test_parsebench_parse_envelope_carries_text_and_pixel_boxes() -> None:
    envelope = _parsebench("table", _regions("one_page_image"))
    assert envelope["pipeline_name"] == tl.PIPELINE_NAME
    assert envelope["product_type"] == "parse"
    assert envelope["request"]["example_id"] == "table/SYNTHETIC-x"
    assert envelope["request"]["source_file_path"] == "docs/table/SYNTHETIC-x.pdf"
    assert envelope["latency_in_ms"] == 1234
    output = envelope["output"]
    markdown = "SYNTHETIC 표 제목처럼 보이는 문단\n\nSYNTHETIC body | not a table"
    assert output["markdown"] == markdown
    assert output["pages"] == [{"page_index": 0, "markdown": markdown}]
    (page,) = output["layout_pages"]
    assert (page["page_number"], page["width"], page["height"]) == (1, 200.0, 100.0)
    first, second = page["items"]
    assert first["bbox"] == {
        "x": 0.0,
        "y": 0.0,
        "w": 200.0,
        "h": 10.0,
        "confidence": 1.0,
        "label": "Text",
    }
    assert second["bbox"] == {
        "x": 20.0,
        "y": 50.0,
        "w": 100.0,
        "h": 25.0,
        "confidence": 1.0,
        "label": "Text",
    }
    assert (second["type"], second["md"], second["layout_segments"]) == (
        "text",
        "SYNTHETIC body | not a table",
        [second["bbox"]],
    )
    assert envelope["raw_output"]["adapter"] == tl.ADAPTER_ID


def test_parsebench_layout_category_is_a_layout_detection_result() -> None:
    envelope = _parsebench("layout", _regions("one_page_image"))
    output = envelope["output"]
    assert envelope["product_type"] == output["task_type"] == "layout_detection"
    assert (output["image_width"], output["image_height"]) == (200, 100)
    assert [p["bbox"] for p in output["predictions"]] == [
        [0.0, 0.0, 200.0, 10.0],
        [20.0, 50.0, 120.0, 75.0],
    ]
    assert {p["label"] for p in output["predictions"]} == {"Text"}
    assert {p["score"] for p in output["predictions"]} == {1.0}
    assert output["predictions"][1]["content"] == {
        "type": "text",
        "text": "SYNTHETIC body | not a table",
    }


def test_parsebench_output_is_byte_deterministic() -> None:
    regions = _regions("one_page_image")
    kwargs: dict[str, Any] = {
        "image_size_px": (200, 100),
        "recorded_at": "SYNTHETIC",
        "latency_ms": 0,
    }
    once = tl.parsebench_result("docs/text_content/a.pdf", regions, **kwargs)
    again = tl.parsebench_result("docs/text_content/a.pdf", list(reversed(regions)), **kwargs)
    assert once == again


def test_no_regions_is_the_empty_prediction_for_every_suite() -> None:
    assert tl.olmocr_candidate(OLMOCR_SOURCE, [], pages=2) == {
        "table_tests/SYNTHETIC-doc_pg1_repeat1.md": "",
        "table_tests/SYNTHETIC-doc_pg2_repeat1.md": "",
    }
    assert tl.omnidocbench_prediction(OMNIDOC_SOURCE, []) == {
        "markdown-repeat-1/SYNTHETIC-page.md": ""
    }
    parse = _parsebench("chart", [])
    assert parse["raw_output"] is None
    assert (parse["output"]["markdown"], parse["output"]["pages"]) == ("", [])
    assert parse["output"]["layout_pages"] == []
    layout = _parsebench("layout", [])
    assert (layout["output"]["markdown"], layout["output"]["predictions"]) == ("", [])


def _stub_result(document: Document, body: bytes | None) -> tuple[Any, bytes | None]:
    exchanges = [] if body is None else [{"status": 200, "text": body.decode("utf-8")}]
    result = TavonelLiveStub(ReplayTransport(exchanges), sleep=lambda _s: None).parse(document, PIN)
    return result, body


def test_every_refused_document_stays_in_the_denominator_as_empty() -> None:
    body = json.dumps(REGIONS["responses"]["two_page_pdf"]).encode("utf-8")
    documents = [
        (Document("SYNTHETIC-ok", b"%PDF SYNTHETIC", 3), body),
        (Document("SYNTHETIC-too-many-pages", b"%PDF SYNTHETIC", 81), None),
        (Document("SYNTHETIC-too-big", b" " * (MAX_SOURCE_BYTES + 1), 1), None),
        (Document("SYNTHETIC-empty", b"%PDF SYNTHETIC", 2), b'{"regions": []}'),
    ]
    written = {}
    for document, raw in documents:
        result, raw = _stub_result(document, raw)
        regions = tl.live_regions(result, raw)
        source = f"bench_data/pdfs/old_scans/{document.doc_id}.pdf"
        written[document.doc_id] = (
            result.status.value,
            tl.olmocr_candidate(source, regions, pages=document.pages),
        )
    assert [status for status, _ in written.values()] == [
        "ok",
        "size_rejected",
        "size_rejected",
        "empty_output",
    ]
    assert len(written) == len(documents)
    for doc_id in ("SYNTHETIC-too-many-pages", "SYNTHETIC-too-big", "SYNTHETIC-empty"):
        files = written[doc_id][1]
        assert files and set(files.values()) == {""}, doc_id
    assert len(written["SYNTHETIC-too-many-pages"][1]) == 81
    assert written["SYNTHETIC-ok"][1]["old_scans/SYNTHETIC-ok_pg2_repeat1.md"] == (
        "SYNTHETIC page two paragraph."
    )


def test_a_body_that_is_not_the_recorded_one_is_refused() -> None:
    body = json.dumps(REGIONS["responses"]["one_page_image"]).encode("utf-8")
    result, _ = _stub_result(Document("SYNTHETIC-doc", b"%PDF SYNTHETIC", 1), body)
    assert result.raw_sha256 == hashlib.sha256(body).hexdigest()
    with pytest.raises(tl.EvidenceMismatch, match="SYNTHETIC-doc"):
        tl.live_regions(result, body + b" ")
    with pytest.raises(tl.EvidenceMismatch):
        tl.live_regions(result, None)


def test_a_body_without_boxes_is_malformed_at_the_stub_and_never_scored() -> None:
    body = b'{"regions": [{"pageNumber1": 1, "order": 0, "text": "SYNTHETIC"}]}'
    result, raw = _stub_result(Document("SYNTHETIC-doc", b"%PDF SYNTHETIC", 1), body)
    assert result.status.value == "malformed_response"
    assert tl.live_regions(result, raw) == []
    with pytest.raises(tl.MalformedLiveOutput):
        tl.read_regions(json.loads(body))


@pytest.mark.parametrize(
    "case",
    [c for c in REGIONS["malformed"] if c["name"].startswith("bbox_")],
    ids=lambda c: c["name"],
)
def test_the_stub_refuses_every_bbox_the_adapter_refuses(case: dict[str, Any]) -> None:
    body = json.dumps(case["payload"]).encode("utf-8")
    result, _ = _stub_result(Document("SYNTHETIC-doc", b"%PDF SYNTHETIC", 1), body)
    assert (result.status.value, result.markdown) == ("malformed_response", "")
    with pytest.raises(tl.MalformedLiveOutput, match="bbox1000"):
        tl.read_regions(case["payload"])


def test_the_stub_accepts_the_bodies_the_adapter_accepts() -> None:
    assert len([c for c in REGIONS["malformed"] if c["name"].startswith("bbox_")]) == 8
    for name, pages in (("two_page_pdf", 2), ("one_page_image", 1)):
        body = json.dumps(REGIONS["responses"][name]).encode("utf-8")
        result, raw = _stub_result(Document("SYNTHETIC-doc", b"%PDF SYNTHETIC", pages), body)
        assert result.status.value == "ok", name
        assert tl.live_regions(result, raw) == _regions(name)


@pytest.mark.parametrize("case", REGIONS["malformed"], ids=lambda c: c["name"])
def test_malformed_output_fails_closed(case: dict[str, Any]) -> None:
    with pytest.raises(tl.MalformedLiveOutput):
        tl.read_regions(case["payload"])


def test_regions_beyond_the_manifest_page_count_are_refused() -> None:
    with pytest.raises(tl.MalformedLiveOutput, match="beyond the source's 1"):
        tl.olmocr_candidate(OLMOCR_SOURCE, _regions("two_page_pdf"), pages=1)


@pytest.mark.parametrize(
    "call",
    [
        lambda: tl.olmocr_candidate(OLMOCR_SOURCE, [], pages=0),
        lambda: tl.olmocr_candidate(OLMOCR_SOURCE, [], pages=1, repeat=0),
        lambda: tl.olmocr_candidate("SYNTHETIC-no-category.pdf", [], pages=1),
        lambda: tl.omnidocbench_prediction(OMNIDOC_SOURCE, [], repeat=0),
        lambda: tl.parsebench_result(
            "docs/table/x.pdf", [], image_size_px=(0, 100), recorded_at="", latency_ms=0
        ),
        lambda: tl.parsebench_result(
            "docs/table/x.pdf", [], image_size_px=(1, 1), recorded_at="", latency_ms=-1
        ),
    ],
    ids=["pages0", "repeat0", "no_category", "omnidoc_repeat0", "image0", "latency_negative"],
)
def test_bad_arguments_are_refused(call: Any) -> None:
    with pytest.raises(ValueError):
        call()


@pytest.mark.parametrize("case", REGIONS["structure"], ids=lambda c: c["name"])
def test_non_paragraph_blocks_are_not_flattened(case: dict[str, Any]) -> None:
    with pytest.raises(tl.StructureNotImplemented) as raised:
        tl.read_regions(case["payload"])
    assert raised.value.reason_code == case["reason_code"]


def test_a_table_read_page_is_refused_wherever_it_sits() -> None:
    document = TABLE_REF["document"]
    assert document["schemaVersion"] == tl.TABLE_READ_SCHEMA
    assert (len(document["tables"]), len(document["formulas"])) == (1, 1)
    regions = [
        {**r, "pageNumber1": r["pageIndex0"] + 1, "order": i, "blockType": "paragraph"}
        for i, r in enumerate(TABLE_REF["ocr_regions"])
    ]
    assert len(tl.read_regions({"regions": regions})) == 7
    payloads = [
        {"regions": regions, "SYNTHETIC_future_key": [document]},
        {"regions": [{**regions[0], "SYNTHETIC_nested": {"page": document}}]},
    ]
    for payload in payloads:
        with pytest.raises(tl.StructureNotImplemented, match="not implemented") as raised:
            tl.read_regions(payload)
        assert raised.value.reason_code == tl.TABLE_READ_NOT_CONVERTED
        assert "'tables': 1, 'formulas': 1, 'refusals': 0" in str(raised.value)


def test_adapter_digest_is_the_module_bytes_with_lf_line_ends() -> None:
    lf = Path(tl.__file__).read_bytes().replace(b"\r\n", b"\n")
    assert b"\r" not in lf
    assert tl.adapter_digest() == f"sha256:{hashlib.sha256(lf).hexdigest()}"


def test_conversion_runs_with_the_network_unplugged() -> None:
    with pytest.raises(AssertionError, match="network access attempted"):
        socket.create_connection(("127.0.0.1", 9))
    regions = _regions("two_page_pdf")
    assert tl.olmocr_candidate(OLMOCR_SOURCE, regions, pages=2)
    assert tl.omnidocbench_prediction(OMNIDOC_SOURCE, _regions("one_page_image"))
    assert _parsebench("layout", _regions("one_page_image"))


def test_module_docstring_states_the_missing_structure_and_the_prediction() -> None:
    doc = tl.__doc__ or ""
    for phrase in (
        "no_table_or_formula_extraction",
        "BEHIND, table-heavy: ParseBench Tables; OmniDocBench table TEDS; olmOCR ``table_tests``",
        "BEHIND, formula-heavy",
        "deliberately unimplemented",
    ):
        assert phrase in doc
