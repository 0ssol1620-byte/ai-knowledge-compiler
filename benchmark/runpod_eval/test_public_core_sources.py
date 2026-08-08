from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from public_core_sources import (
    EXPECTED_SOURCE_COUNTS,
    build_source_manifest,
    content_sha256,
    sha256_file,
    stage_inference_inputs,
)


def _image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 12), color=(20, 40, 60)).save(path)


def test_omnidoc_manifest_contains_only_source_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _image(tmp_path / "images/a.png")
    _image(tmp_path / "images/b.png")
    index = [
        {
            "page_info": {"image_path": "a.png", "page_no": 0},
            "layout_dets": [{"text": "SECRET-GROUND-TRUTH"}],
        },
        {
            "page_info": {"image_path": "b.png", "page_no": 0},
            "layout_dets": [{"text": "OTHER-GROUND-TRUTH"}],
        },
    ]
    (tmp_path / "OmniDocBench.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setitem(EXPECTED_SOURCE_COUNTS, "omnidocbench", 2)

    manifest = build_source_manifest(
        dataset_root=tmp_path,
        benchmark_id="omnidocbench",
        dataset_revision="revision-1",
    )

    serialized = json.dumps(manifest)
    assert manifest["source_count"] == 2
    assert manifest["complete_source_coverage"] is True
    assert manifest["ground_truth_mounted"] is False
    assert "SECRET-GROUND-TRUTH" not in serialized
    assert "OTHER-GROUND-TRUTH" not in serialized
    assert manifest["content_sha256"] == content_sha256(manifest)


def test_parsebench_deduplicates_rules_by_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "page.pdf"
    source.write_bytes(b"fixture-pdf")
    row = {"pdf": "docs/page.pdf", "page": 1, "expected_markdown": "DO-NOT-COPY"}
    for filename in (
        "chart.jsonl",
        "layout.jsonl",
        "table.jsonl",
        "text_content.jsonl",
        "text_formatting.jsonl",
    ):
        (tmp_path / filename).write_text(json.dumps(row) + "\n", encoding="utf-8")
    monkeypatch.setitem(EXPECTED_SOURCE_COUNTS, "parsebench", 1)

    manifest = build_source_manifest(
        dataset_root=tmp_path,
        benchmark_id="parsebench",
        dataset_revision="revision-2",
    )

    assert manifest["source_count"] == 1
    assert manifest["sources"][0]["source_relative_path"] == "docs/page.pdf"
    assert manifest["sources"][0]["page_index"] == 0
    assert "DO-NOT-COPY" not in json.dumps(manifest)


def test_image_staging_binds_original_and_staged_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = tmp_path / "dataset"
    _image(dataset / "images/a.png")
    (dataset / "OmniDocBench.json").write_text(
        json.dumps([{"page_info": {"image_path": "a.png", "page_no": 0}}]),
        encoding="utf-8",
    )
    monkeypatch.setitem(EXPECTED_SOURCE_COUNTS, "omnidocbench", 1)
    source_manifest = build_source_manifest(
        dataset_root=dataset,
        benchmark_id="omnidocbench",
        dataset_revision="revision-3",
    )

    stage = tmp_path / "stage"
    input_manifest = stage_inference_inputs(
        dataset_root=dataset,
        source_manifest=source_manifest,
        stage_dir=stage,
        dpi=144,
    )

    item = input_manifest["inputs"][0]
    staged_path = stage / item["input_relative_path"]
    assert staged_path.is_file()
    assert item["source_sha256"] == sha256_file(dataset / "images/a.png")
    assert item["input_sha256"] == sha256_file(staged_path)
    assert input_manifest["content_sha256"] == content_sha256(input_manifest)


def test_pdf_staging_renders_the_referenced_page(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    pypdf = pytest.importorskip("pypdf")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    source = dataset / "one-page.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source.open("wb") as handle:
        writer.write(handle)
    source_manifest = {
        "schema": "folynta.public-core-source-manifest.v1",
        "benchmark_id": "fixture",
        "dataset_revision": "revision-4",
        "ground_truth_mounted": False,
        "source_count": 1,
        "complete_source_coverage": True,
        "sources": [
            {
                "case_id": "fixture-case",
                "source_relative_path": source.name,
                "source_sha256": sha256_file(source),
                "media_type": "pdf",
                "page_index": 0,
            }
        ],
    }
    source_manifest["content_sha256"] = content_sha256(source_manifest)

    stage = tmp_path / "stage"
    manifest = stage_inference_inputs(
        dataset_root=dataset,
        source_manifest=source_manifest,
        stage_dir=stage,
        dpi=72,
    )

    output = stage / manifest["inputs"][0]["input_relative_path"]
    with Image.open(output) as image:
        assert image.size == (72, 72)
