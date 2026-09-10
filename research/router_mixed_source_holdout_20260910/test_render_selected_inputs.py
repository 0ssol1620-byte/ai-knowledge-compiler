from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from .render_selected_inputs import (
    RenderBatchResult,
    RenderedPng,
    RenderFailure,
    RenderLimits,
    _digest_file,
    _run_bounded_capture,
    _run_bounded_pdf_render,
    render_selected_inputs,
)

CLASSES = (
    "native_structured",
    "born_digital_pdf_table",
    "scanned_pdf",
    "layout_heavy_pdf",
    "office_korean_docx",
    "office_korean_pptx",
    "office_korean_xlsx",
    "target_alignment_failure",
)


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _make_ooxml(path: Path, member: str) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if member == "word/document.xml":
            archive.writestr(
                member,
                b'<w:document xmlns:w="http://schemas.openxmlformats.org/'
                b'wordprocessingml/2006/main"><w:body><w:p/><w:p/>'
                b'<w:p><w:r><w:t>fixture</w:t></w:r></w:p></w:body></w:document>',
            )
        else:
            archive.writestr(member, b"<root><value>fixture</value></root>")


def _world(tmp_path: Path) -> dict[str, Any]:
    source_root = tmp_path / "private-sources"
    render_root = tmp_path / "private-renders"
    source_root.mkdir()
    render_root.mkdir()
    locators = {
        "native_structured": "source-native:whole",
        "born_digital_pdf_table": "page:2:bbox1000:0,0,1000,1000",
        "scanned_pdf": "page:1:bbox1000:0,0,1000,1000",
        "layout_heavy_pdf": "page:1:bbox1000:0,0,1000,1000",
        "office_korean_docx": "ooxml:word/document.xml#body/*[3]",
        "office_korean_pptx": "ooxml:ppt/slides/slide1.xml",
        "office_korean_xlsx": "ooxml:xl/worksheets/sheet1.xml",
        "target_alignment_failure": "page:3:bbox1000:100,50,900,950",
    }
    media_types = {
        "native_structured": "text/csv",
        "born_digital_pdf_table": "application/pdf",
        "scanned_pdf": "application/pdf",
        "layout_heavy_pdf": "application/pdf",
        "office_korean_docx": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        "office_korean_pptx": (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
        "office_korean_xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "target_alignment_failure": "application/pdf",
    }
    rows: list[dict[str, object]] = []
    for index, source_class in enumerate(CLASSES):
        unit_id = f"unit-{index:02d}"
        source = source_root / f"{unit_id}.source"
        if source_class == "office_korean_docx":
            _make_ooxml(source, "word/document.xml")
        elif source_class == "office_korean_pptx":
            _make_ooxml(source, "ppt/slides/slide1.xml")
        elif source_class == "office_korean_xlsx":
            _make_ooxml(source, "xl/worksheets/sheet1.xml")
        else:
            source.write_bytes(f"%PDF-fixture-{source_class}".encode())
        rows.append(
            {
                "unit_id": unit_id,
                "source_class": source_class,
                "source_sha256": _digest_file(source),
                "source_size_bytes": source.stat().st_size,
                "media_type": media_types[source_class],
                "target_locator": locators[source_class],
                "truth_state": "SEALED_UNOPENED",
            }
        )
    protocol_path = tmp_path / "protocol.json"
    _json(
        protocol_path,
        {
            "source_selection": {
                "selected_units_per_class": 1,
                "maximum_total_units": len(CLASSES),
            },
            "required_classes": list(CLASSES),
        },
    )
    contract_path = tmp_path / "contract.json"
    _json(
        contract_path,
        {
            "representations": {
                source_class: {"visual_required": source_class != "native_structured"}
                for source_class in CLASSES
            }
        },
    )
    source_manifest_path = tmp_path / "sources.jsonl"
    _jsonl(source_manifest_path, rows)
    office_script = tmp_path / "office_render.ps1"
    office_script.write_text("# exact test office script\n", encoding="utf-8")
    return {
        "source_root": source_root,
        "render_root": render_root,
        "rows": rows,
        "protocol_path": protocol_path,
        "contract_path": contract_path,
        "source_manifest_path": source_manifest_path,
        "office_script": office_script,
        "manifest_path": tmp_path / "renders.jsonl",
        "attempt_path": tmp_path / "render-attempt.jsonl",
        "profile_path": tmp_path / "render-profile.json",
        "runtime_path": tmp_path / "render-runtime.json",
    }


def _runtime_builder(
    office_script: Path,
    profile_sha256: str,
    generator_sha256: str,
    office_script_sha256: str,
) -> dict[str, object]:
    return {
        "schema": "test.render-runtime.v1",
        "worker": "isolated-test-worker",
        "office_script_name": office_script.name,
        "profile_sha256": profile_sha256,
        "generator_sha256": generator_sha256,
        "office_script_sha256": office_script_sha256,
        "truth_opened": False,
        "model_calls": 0,
    }


def _pdf_renderer(
    _source: Path,
    _page: int,
    _bbox: tuple[int, int, int, int],
    output: Path,
    _limits: RenderLimits,
) -> RenderedPng:
    Image.new("RGB", (16, 12), (20, 40, 60)).save(output, format="PNG")
    return RenderedPng(16, 12)


def _office_exporter(
    _kind: str,
    _source: Path,
    output: Path,
    _script: Path,
    _timeout: int,
    target_kind: str | None,
    target_ordinal: int | None,
) -> dict[str, object]:
    if _kind == "docx":
        assert target_kind == "p"
        assert target_ordinal == 3
    output.write_bytes(b"%PDF-1.4\n% test intermediate\n")
    return {
        "status": "SUCCEEDED",
        "resolved_page_number": 4 if _kind == "docx" else 1,
        "locator_proof": (
            "word_body_element_formatted_range_page"
            if _kind == "docx"
            else "first_exported_page"
        ),
    }


def _run(world: dict[str, Any], **overrides: object) -> RenderBatchResult:
    values: dict[str, object] = {
        "protocol_path": world["protocol_path"],
        "source_manifest_path": world["source_manifest_path"],
        "source_contract_path": world["contract_path"],
        "source_root": world["source_root"],
        "render_root": world["render_root"],
        "manifest_path": world["manifest_path"],
        "attempt_report_path": world["attempt_path"],
        "profile_path": world["profile_path"],
        "runtime_path": world["runtime_path"],
        "office_script": world["office_script"],
        "pdf_renderer": _pdf_renderer,
        "office_exporter": _office_exporter,
        "runtime_builder": _runtime_builder,
    }
    values.update(overrides)
    return render_selected_inputs(**values)  # type: ignore[arg-type]


def test_exact_denominator_renders_every_visual_unit_and_binds_receipts(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    office_calls: list[str] = []
    pdf_pages: list[int] = []

    def office_exporter(
        kind: str,
        source: Path,
        output: Path,
        script: Path,
        timeout: int,
        target_kind: str | None,
        target_ordinal: int | None,
    ) -> dict[str, object]:
        office_calls.append(kind)
        return _office_exporter(
            kind,
            source,
            output,
            script,
            timeout,
            target_kind,
            target_ordinal,
        )

    def pdf_renderer(
        source: Path,
        page: int,
        bbox: tuple[int, int, int, int],
        output: Path,
        limits: RenderLimits,
    ) -> RenderedPng:
        pdf_pages.append(page)
        return _pdf_renderer(source, page, bbox, output, limits)

    result = _run(world, office_exporter=office_exporter, pdf_renderer=pdf_renderer)

    assert result.passed
    assert result.total_sources == 8
    assert result.expected_visual_units == 7
    assert result.succeeded == 7
    assert result.failed == 0
    assert result.manifest_written
    assert sorted(office_calls) == ["docx", "pptx", "xlsx"]
    assert sorted(pdf_pages) == [1, 1, 1, 1, 1, 2, 3]
    rows = _read_jsonl(world["manifest_path"])
    assert len(rows) == 7
    assert {row["source_class"] for row in rows} == set(CLASSES) - {"native_structured"}
    assert all(row["status"] == "SUCCEEDED" for row in rows)
    assert all(row["render_profile_sha256"] == result.profile_sha256 for row in rows)
    assert all(row["render_runtime_sha256"] == result.runtime_sha256 for row in rows)
    docx_row = next(row for row in rows if row["source_class"] == "office_korean_docx")
    assert docx_row["resolved_page_number"] == 4
    assert docx_row["locator_proof"] == "word_body_element_formatted_range_page"
    assert all(row["render_width_px"] == 16 for row in rows)
    assert all(row["render_height_px"] == 12 for row in rows)
    office_rows = [row for row in rows if row["source_class"].startswith("office_")]
    assert {row["source_class"]: row["resolved_page_number"] for row in office_rows} == {
        "office_korean_docx": 4,
        "office_korean_pptx": 1,
        "office_korean_xlsx": 1,
    }
    assert all(row["intermediate_pdf_sha256"] for row in office_rows)
    assert all(row["intermediate_pdf_relative_path"] for row in office_rows)
    pdf_rows = [row for row in rows if not row["source_class"].startswith("office_")]
    assert all(row["intermediate_pdf_sha256"] is None for row in pdf_rows)
    attempts = _read_jsonl(world["attempt_path"])
    assert len(attempts) == 7
    assert {row["status"] for row in attempts} == {"SUCCEEDED"}
    assert not (world["render_root"] / "unit-00.png").exists()


def test_any_render_failure_withholds_complete_manifest_and_retains_failure(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)

    def failing_renderer(
        source: Path,
        page: int,
        bbox: tuple[int, int, int, int],
        output: Path,
        limits: RenderLimits,
    ) -> RenderedPng:
        if page == 3:
            output.write_bytes(b"partial")
            raise RenderFailure("INJECTED_RENDER_FAILURE")
        return _pdf_renderer(source, page, bbox, output, limits)

    result = _run(world, pdf_renderer=failing_renderer)

    assert not result.passed
    assert result.succeeded == 6
    assert result.failed == 1
    assert not result.manifest_written
    assert not world["manifest_path"].exists()
    attempts = _read_jsonl(world["attempt_path"])
    failed = [row for row in attempts if row["status"] == "FAILED"]
    assert failed == [
        {
            "error_code": "INJECTED_RENDER_FAILURE",
            "source_class": "target_alignment_failure",
            "source_sha256": world["rows"][7]["source_sha256"],
            "status": "FAILED",
            "target_locator": world["rows"][7]["target_locator"],
            "unit_id": "unit-07",
        }
    ]
    assert not list(world["render_root"].rglob("*.part*"))


def test_source_digest_drift_fails_closed_before_that_unit_renders(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    drifted = world["source_root"] / "unit-01.source"
    drifted_bytes = bytearray(drifted.read_bytes())
    drifted_bytes[-1] ^= 1
    drifted.write_bytes(drifted_bytes)

    result = _run(world)

    assert not result.passed
    assert "unit-01:SOURCE_DIGEST_MISMATCH" in result.blockers
    assert not world["manifest_path"].exists()
    attempts = _read_jsonl(world["attempt_path"])
    row = next(item for item in attempts if item["unit_id"] == "unit-01")
    assert row["status"] == "FAILED"
    assert row["error_code"] == "SOURCE_DIGEST_MISMATCH"


def test_missing_source_row_rejects_exact_denominator_before_outputs(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    _jsonl(world["source_manifest_path"], world["rows"][:-1])

    with pytest.raises(RenderFailure, match="SOURCE_TOTAL_DENOMINATOR_MISMATCH"):
        _run(world)

    assert not world["manifest_path"].exists()
    assert not world["attempt_path"].exists()
    assert not list(world["render_root"].rglob("*.png"))


def test_locator_drift_is_recorded_and_manifest_is_withheld(tmp_path: Path) -> None:
    world = _world(tmp_path)
    world["rows"][1]["target_locator"] = "page:0:bbox1000:0,0,1000,1000"
    _jsonl(world["source_manifest_path"], world["rows"])

    result = _run(world)

    assert not result.passed
    assert "unit-01:PDF_LOCATOR_INVALID" in result.blockers
    assert not world["manifest_path"].exists()


def test_office_failure_keeps_intermediate_atomic_and_denominator_incomplete(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)

    def office_failure(
        kind: str,
        _source: Path,
        output: Path,
        _script: Path,
        _timeout: int,
        _target_kind: str | None,
        _target_ordinal: int | None,
    ) -> dict[str, object]:
        if kind == "pptx":
            output.write_bytes(b"partial-office-output")
            raise RenderFailure("OFFICE_EXPORT_FAILED")
        output.write_bytes(b"%PDF-1.4\n% good\n")
        return {
            "status": "SUCCEEDED",
            "resolved_page_number": 1,
            "locator_proof": "first_exported_page",
        }

    result = _run(world, office_exporter=office_failure)

    assert not result.passed
    assert "unit-05:OFFICE_EXPORT_FAILED" in result.blockers
    assert not world["manifest_path"].exists()
    assert not list(world["render_root"].rglob("*.part*"))
    attempts = _read_jsonl(world["attempt_path"])
    pptx = next(row for row in attempts if row["unit_id"] == "unit-05")
    assert pptx["status"] == "FAILED"
    assert pptx["error_code"] == "OFFICE_EXPORT_FAILED"


def test_docx_locator_must_resolve_existing_body_child(tmp_path: Path) -> None:
    world = _world(tmp_path)
    world["rows"][4]["target_locator"] = (
        "ooxml:word/document.xml#body/*[9999]"
    )
    _jsonl(world["source_manifest_path"], world["rows"])

    result = _run(world)

    assert not result.passed
    assert "unit-04:DOCX_TARGET_CHILD_OUT_OF_RANGE" in result.blockers
    assert not world["manifest_path"].exists()


def test_existing_different_runtime_receipt_cannot_be_replaced(tmp_path: Path) -> None:
    world = _world(tmp_path)
    world["runtime_path"].write_text('{"different":true}\n', encoding="utf-8")

    with pytest.raises(RenderFailure, match="IMMUTABLE_RECEIPT_ALREADY_EXISTS_DIFFERENT"):
        _run(world)

    assert world["runtime_path"].read_text(encoding="utf-8") == '{"different":true}\n'
    assert not world["manifest_path"].exists()


def test_pdfium_worker_timeout_is_bounded_and_process_tree_is_terminated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TimedOutProcess:
        pid = 4242
        returncode = None

        def __init__(self) -> None:
            self.wait_calls = 0

        def wait(self, timeout: int) -> int:
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise subprocess.TimeoutExpired("pdfium", timeout)
            return 1

    process = TimedOutProcess()
    terminated: list[int] = []
    monkeypatch.setattr(
        f"{_run_bounded_pdf_render.__module__}.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    monkeypatch.setattr(
        f"{_run_bounded_pdf_render.__module__}._terminate_process_tree",
        lambda value: terminated.append(value.pid),
    )

    with pytest.raises(RenderFailure, match="PDFIUM_RENDER_TIMEOUT"):
        _run_bounded_pdf_render(
            tmp_path / "source.pdf",
            1,
            (0, 0, 1000, 1000),
            tmp_path / "output.png",
            RenderLimits(per_unit_timeout_seconds=7),
        )

    assert terminated == [4242]
    assert process.wait_calls == 2


def test_subprocess_output_is_spooled_and_bounded() -> None:
    with pytest.raises(RenderFailure, match="SUBPROCESS_OUTPUT_LIMIT_EXCEEDED"):
        _run_bounded_capture(
            [sys.executable, "-c", "import sys; sys.stdout.write('x' * 5000)"],
            timeout_seconds=30,
            stdout_limit=1024,
            stderr_limit=1024,
            timeout_error="TEST_TIMEOUT",
        )
