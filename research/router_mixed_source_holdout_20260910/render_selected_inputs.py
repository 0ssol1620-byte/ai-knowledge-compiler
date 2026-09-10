"""Render the frozen mixed-source visual inputs without opening holdout truth.

The complete render manifest is created only when every visual-required source
has produced a bounded, content-addressed PNG.  Partial outputs and a separate
attempt report are retained for diagnosis, but they never form an admissible
denominator.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
import zipfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from defusedxml.ElementTree import fromstring as safe_xml_fromstring

SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_UNIT = re.compile(r"^[A-Za-z0-9._:-]+$")
PDF_LOCATOR = re.compile(
    r"^page:(?P<page>[1-9][0-9]*):bbox1000:"
    r"(?P<x0>[0-9]{1,4}),(?P<y0>[0-9]{1,4}),"
    r"(?P<x1>[0-9]{1,4}),(?P<y1>[0-9]{1,4})$"
)
DOCX_LOCATOR = re.compile(r"^ooxml:word/document\.xml#body/\*\[[1-9][0-9]*\]$")
PPTX_LOCATOR = re.compile(r"^ooxml:ppt/slides/slide(?P<index>[1-9][0-9]*)\.xml$")
XLSX_LOCATOR = re.compile(r"^ooxml:xl/worksheets/sheet(?P<index>[1-9][0-9]*)\.xml$")

SOURCE_REQUIRED_FIELDS = frozenset(
    {
        "unit_id",
        "source_class",
        "source_sha256",
        "source_size_bytes",
        "media_type",
        "target_locator",
        "truth_state",
    }
)
OFFICE_CLASSES = frozenset({"office_korean_docx", "office_korean_pptx", "office_korean_xlsx"})


class RenderFailure(RuntimeError):
    """A stable fail-closed rendering error safe to record as metadata."""


@dataclass(frozen=True, slots=True)
class RenderLimits:
    dpi: int = 144
    maximum_source_bytes: int = 300 * 1024 * 1024
    maximum_intermediate_pdf_bytes: int = 1024 * 1024 * 1024
    maximum_render_bytes: int = 50 * 1024 * 1024
    maximum_pixels: int = 40_000_000
    maximum_dimension_px: int = 12_000
    per_unit_timeout_seconds: int = 600

    def as_profile(self) -> dict[str, object]:
        return {
            "schema": "tavonel.router_render_profile.v1",
            "state": "FROZEN_BEFORE_MODEL_EXECUTION",
            "truth_opened": False,
            "model_calls": 0,
            "dpi": self.dpi,
            "pixel_format": "RGB",
            "output_format": "PNG",
            "png_compress_level": 9,
            "png_optimize": False,
            "bbox_coordinate_space": "top_left_bbox1000",
            "office_export": (
                "Office16_COM_read_only_macro_disabled;DOCX_exact_body_element_"
                "formatted_range_reflowed_to_single_PDF_then_PDFium_page_1;"
                "PPTX_XLSX_first_exported_page_then_PDFium_page_1"
            ),
            "maximum_source_bytes": self.maximum_source_bytes,
            "maximum_intermediate_pdf_bytes": self.maximum_intermediate_pdf_bytes,
            "maximum_render_bytes": self.maximum_render_bytes,
            "maximum_pixels": self.maximum_pixels,
            "maximum_dimension_px": self.maximum_dimension_px,
            "per_unit_timeout_seconds": self.per_unit_timeout_seconds,
            "production_promotion": False,
        }


@dataclass(frozen=True, slots=True)
class RenderedPng:
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class RenderBatchResult:
    passed: bool
    total_sources: int
    expected_visual_units: int
    succeeded: int
    failed: int
    blockers: tuple[str, ...]
    profile_sha256: str
    runtime_sha256: str
    manifest_written: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.router_render_batch_result.v1",
            "passed": self.passed,
            "total_sources": self.total_sources,
            "expected_visual_units": self.expected_visual_units,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "blockers": list(self.blockers),
            "profile_sha256": self.profile_sha256,
            "runtime_sha256": self.runtime_sha256,
            "manifest_written": self.manifest_written,
            "truth_opened": False,
            "model_calls": 0,
            "production_promotion": False,
        }


PdfRenderer = Callable[[Path, int, tuple[int, int, int, int], Path, RenderLimits], RenderedPng]
OfficeExporter = Callable[
    [str, Path, Path, Path, int, str | None, int | None],
    Mapping[str, object],
]
RuntimeBuilder = Callable[[Path, str, str, str], Mapping[str, object]]


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _digest_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _canonical_jsonl(rows: Sequence[Mapping[str, object]]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode()
        for row in rows
    )


def _atomic_replace(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != payload:
            raise RenderFailure("IMMUTABLE_RECEIPT_ALREADY_EXISTS_DIFFERENT") from None


def _load_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise RenderFailure("JSON_OBJECT_REQUIRED")
    return value


def _load_jsonl(path: Path) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise RenderFailure(f"JSONL_EMPTY_LINE_{line_number:04d}")
        value = json.loads(line)
        if not isinstance(value, Mapping):
            raise RenderFailure(f"JSONL_OBJECT_REQUIRED_{line_number:04d}")
        rows.append(value)
    return rows


def _safe_file(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise RenderFailure("RELATIVE_PATH_INVALID")
    resolved_root = root.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        raise RenderFailure("RELATIVE_PATH_ESCAPES_ROOT") from None
    return resolved


def _source_path(source_root: Path, unit_id: str) -> Path:
    return _safe_file(source_root, unit_id.replace(":", "_") + ".source")


def _validate_limits(limits: RenderLimits) -> None:
    for name in (
        "dpi",
        "maximum_source_bytes",
        "maximum_intermediate_pdf_bytes",
        "maximum_render_bytes",
        "maximum_pixels",
        "maximum_dimension_px",
        "per_unit_timeout_seconds",
    ):
        value = getattr(limits, name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise RenderFailure(f"LIMIT_{name.upper()}_INVALID")


def _parse_pdf_locator(locator: str) -> tuple[int, tuple[int, int, int, int]]:
    match = PDF_LOCATOR.fullmatch(locator)
    if match is None:
        raise RenderFailure("PDF_LOCATOR_INVALID")
    page = int(match.group("page"))
    bbox = (
        int(match.group("x0")),
        int(match.group("y0")),
        int(match.group("x1")),
        int(match.group("y1")),
    )
    x0, y0, x1, y1 = bbox
    if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
        raise RenderFailure("PDF_BBOX_INVALID")
    return page, bbox


def _validate_office_locator(
    source: Path, source_class: str, locator: str
) -> tuple[str, int, str, int]:
    if source_class == "office_korean_docx":
        if DOCX_LOCATOR.fullmatch(locator) is None:
            raise RenderFailure("DOCX_LOCATOR_INVALID")
        member = "word/document.xml"
    elif source_class == "office_korean_pptx":
        match = PPTX_LOCATOR.fullmatch(locator)
        if match is None or int(match.group("index")) != 1:
            raise RenderFailure("PPTX_FIRST_SLIDE_LOCATOR_REQUIRED")
        member = locator.removeprefix("ooxml:")
    elif source_class == "office_korean_xlsx":
        match = XLSX_LOCATOR.fullmatch(locator)
        if match is None or int(match.group("index")) != 1:
            raise RenderFailure("XLSX_FIRST_WORKSHEET_LOCATOR_REQUIRED")
        member = locator.removeprefix("ooxml:")
    else:
        raise RenderFailure("OFFICE_CLASS_INVALID")
    try:
        with zipfile.ZipFile(source) as archive:
            info = archive.getinfo(member)
            if info.is_dir() or info.file_size <= 0 or info.file_size > 16 * 1024 * 1024:
                raise RenderFailure("OOXML_TARGET_EMPTY")
            if source_class == "office_korean_docx":
                document = safe_xml_fromstring(archive.read(info))
                body = next(
                    (child for child in document if child.tag.endswith("}body")),
                    None,
                )
                match = DOCX_LOCATOR.fullmatch(locator)
                assert match is not None
                child_index = int(locator.rsplit("*[", 1)[1][:-1])
                if body is None or child_index > len(body):
                    raise RenderFailure("DOCX_TARGET_CHILD_OUT_OF_RANGE")
                target = list(body)[child_index - 1]
                target_kind = target.tag.rsplit("}", 1)[-1]
                if target_kind not in {"p", "tbl"}:
                    raise RenderFailure("DOCX_TARGET_KIND_UNSUPPORTED")
                target_ordinal = 1 + sum(
                    1
                    for sibling in list(body)[: child_index - 1]
                    for descendant in sibling.iter()
                    if descendant.tag.endswith(f"}}{target_kind}")
                )
                return member, child_index, target_kind, target_ordinal
    except (KeyError, zipfile.BadZipFile, OSError):
        raise RenderFailure("OOXML_TARGET_MISSING_OR_INVALID") from None
    return (
        member,
        1,
        "slide" if source_class.endswith("pptx") else "worksheet",
        1,
    )


def _check_dimensions(width: int, height: int, limits: RenderLimits) -> None:
    if width <= 0 or height <= 0:
        raise RenderFailure("RENDER_DIMENSIONS_INVALID")
    if width > limits.maximum_dimension_px or height > limits.maximum_dimension_px:
        raise RenderFailure("RENDER_DIMENSION_LIMIT_EXCEEDED")
    if width * height > limits.maximum_pixels:
        raise RenderFailure("RENDER_PIXEL_LIMIT_EXCEEDED")


def _render_pdf_page(
    source: Path,
    page_number: int,
    bbox: tuple[int, int, int, int],
    output: Path,
    limits: RenderLimits,
) -> RenderedPng:
    try:
        import pypdfium2 as pdfium  # type: ignore[import-untyped]
    except ImportError:
        raise RenderFailure("PDFIUM_UNAVAILABLE") from None
    document: Any = None
    page: Any = None
    bitmap: Any = None
    try:
        document = pdfium.PdfDocument(str(source))
        if page_number > len(document):
            raise RenderFailure("PDF_PAGE_OUT_OF_RANGE")
        page = document[page_number - 1]
        width_points, height_points = page.get_size()
        x0, y0, x1, y1 = bbox
        scale = limits.dpi / 72.0
        width = math.ceil(width_points * scale * (x1 - x0) / 1000)
        height = math.ceil(height_points * scale * (y1 - y0) / 1000)
        _check_dimensions(width, height, limits)
        crop = (
            width_points * x0 / 1000,
            height_points * (1000 - y1) / 1000,
            width_points * (1000 - x1) / 1000,
            height_points * y0 / 1000,
        )
        bitmap = page.render(scale=scale, crop=crop, rev_byteorder=True)
        image = bitmap.to_pil().convert("RGB")
        actual = RenderedPng(width=image.width, height=image.height)
        _check_dimensions(actual.width, actual.height, limits)
        image.save(output, format="PNG", compress_level=9, optimize=False)
        return actual
    except RenderFailure:
        raise
    except Exception:
        raise RenderFailure("PDFIUM_RENDER_FAILED") from None
    finally:
        for resource in (bitmap, page, document):
            close = getattr(resource, "close", None)
            if callable(close):
                close()


def _run_bounded_pdf_render(
    source: Path,
    page_number: int,
    bbox: tuple[int, int, int, int],
    output: Path,
    limits: RenderLimits,
) -> RenderedPng:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--pdf-worker",
        str(source),
        str(page_number),
        ",".join(str(value) for value in bbox),
        str(output),
        json.dumps(limits.as_profile(), separators=(",", ":"), sort_keys=True),
    ]
    returncode, stdout, _ = _run_bounded_capture(
        command,
        timeout_seconds=limits.per_unit_timeout_seconds,
        stdout_limit=4096,
        stderr_limit=64 * 1024,
        timeout_error="PDFIUM_RENDER_TIMEOUT",
    )
    if returncode != 0:
        raise RenderFailure("PDFIUM_RENDER_FAILED")
    try:
        receipt = json.loads(stdout)
        width = receipt["width"]
        height = receipt["height"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise RenderFailure("PDFIUM_RECEIPT_INVALID") from None
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or isinstance(height, bool)
        or not isinstance(height, int)
    ):
        raise RenderFailure("PDFIUM_RECEIPT_INVALID")
    return RenderedPng(width, height)


def _terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    if os.name == "nt":
        taskkill = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32/taskkill.exe"
        subprocess.run(  # noqa: S603 - fixed executable and a numeric child PID only
            [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    else:
        process.kill()


def _run_bounded_capture(
    command: Sequence[str],
    *,
    timeout_seconds: int,
    stdout_limit: int,
    stderr_limit: int,
    timeout_error: str,
) -> tuple[int, str, str]:
    with tempfile.TemporaryFile("w+b") as stdout_file, tempfile.TemporaryFile(
        "w+b"
    ) as stderr_file:
        process = subprocess.Popen(  # noqa: S603 - caller supplies pinned executable
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(process)
            process.wait(timeout=30)
            raise RenderFailure(timeout_error) from None
        stdout_size = stdout_file.tell()
        stderr_size = stderr_file.tell()
        if stdout_size > stdout_limit or stderr_size > stderr_limit:
            raise RenderFailure("SUBPROCESS_OUTPUT_LIMIT_EXCEEDED")
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read(stdout_limit).decode("utf-8", errors="replace")
        stderr = stderr_file.read(stderr_limit).decode("utf-8", errors="replace")
        return returncode, stdout, stderr


def _terminate_owned_office_process(process_receipt: Path) -> None:
    if not process_receipt.is_file() or process_receipt.stat().st_size > 64 * 1024:
        return
    try:
        value = json.loads(process_receipt.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "process_id",
        "process_name",
        "process_started_at_utc",
        "before_process_ids",
        "creation_started_at_utc",
        "stage",
    }:
        return
    process_id = value.get("process_id")
    process_name = value.get("process_name")
    started = value.get("process_started_at_utc")
    before_ids = value.get("before_process_ids")
    creation_started = value.get("creation_started_at_utc")
    stage = value.get("stage")
    if (
        value.get("schema") != "tavonel.office_process_receipt.v1"
        or isinstance(process_id, bool)
        or not isinstance(process_id, int)
        or process_id < 1
        or process_name not in {"WINWORD", "POWERPNT", "EXCEL"}
        or not isinstance(started, str)
        or re.fullmatch(r"[0-9T:.+Z-]{20,40}", started) is None
        or not isinstance(before_ids, list)
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 1
            for item in before_ids
        )
        or not isinstance(creation_started, str)
        or re.fullmatch(r"[0-9T:.+Z-]{20,40}", creation_started) is None
        or stage
        not in {
            "application_created",
            "opening_document",
            "document_opened",
            "target_range_selected",
            "target_page_resolved",
            "exporting_pdf",
            "pdf_exported",
        }
    ):
        return
    powershell = (
        Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    before_literal = ",".join(str(item) for item in before_ids)
    statement = (
        f"$before=@({before_literal});$cutoff=[datetime]::Parse('{creation_started}').ToUniversalTime();"
        "$deadline=(Get-Date).AddSeconds(10);do{"
        f"$owned=@(Get-Process -Name '{process_name}' -ErrorAction SilentlyContinue|"
        "Where-Object{$_.Id -notin $before -and "
        "$_.StartTime.ToUniversalTime() -ge $cutoff.AddSeconds(-2)});"
        "$owned|Stop-Process -Force -ErrorAction SilentlyContinue;Start-Sleep -Milliseconds 250"
        "}while((Get-Date)-lt $deadline);"
        f"$left=@(Get-Process -Name '{process_name}' -ErrorAction SilentlyContinue|"
        "Where-Object{$_.Id -notin $before -and "
        "$_.StartTime.ToUniversalTime() -ge $cutoff.AddSeconds(-2)});"
        "if($left.Count -ne 0){exit 5}"
    )
    try:
        _run_bounded_capture(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", statement],
            timeout_seconds=30,
            stdout_limit=64 * 1024,
            stderr_limit=64 * 1024,
            timeout_error="OFFICE_PROCESS_CLEANUP_TIMEOUT",
        )
    except RenderFailure:
        return


def _run_office_export(
    kind: str,
    source: Path,
    output_pdf: Path,
    office_script: Path,
    timeout_seconds: int,
    target_kind: str | None,
    target_ordinal: int | None,
) -> Mapping[str, object]:
    if os.name != "nt":
        raise RenderFailure("OFFICE_COM_REQUIRES_WINDOWS")
    powershell = (
        Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    process_receipt = output_pdf.with_suffix(".office-process.json")
    command = [
        str(powershell),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(office_script),
        "-Action",
        "Render",
        "-Kind",
        kind,
        "-InputPath",
        str(source),
        "-OutputPdf",
        str(output_pdf),
        "-ProcessReceiptPath",
        str(process_receipt),
    ]
    if target_kind is not None:
        command.extend(["-TargetKind", target_kind])
    if target_ordinal is not None:
        command.extend(["-TargetOrdinal", str(target_ordinal)])
    try:
        returncode, stdout, _ = _run_bounded_capture(
            command,
            timeout_seconds=timeout_seconds,
            stdout_limit=16 * 1024,
            stderr_limit=64 * 1024,
            timeout_error="OFFICE_EXPORT_TIMEOUT",
        )
    finally:
        _terminate_owned_office_process(process_receipt)
    if returncode != 0:
        raise RenderFailure("OFFICE_EXPORT_FAILED")
    try:
        receipt = json.loads(stdout)
    except json.JSONDecodeError:
        raise RenderFailure("OFFICE_RECEIPT_INVALID") from None
    if not isinstance(receipt, Mapping) or receipt.get("status") != "SUCCEEDED":
        raise RenderFailure("OFFICE_RECEIPT_FAILED")
    resolved_page = receipt.get("resolved_page_number")
    if (
        isinstance(resolved_page, bool)
        or not isinstance(resolved_page, int)
        or resolved_page <= 0
    ):
        raise RenderFailure("OFFICE_RESOLVED_PAGE_INVALID")
    expected_proof = (
        "word_body_element_formatted_range_page"
        if kind == "docx"
        else "first_exported_page"
    )
    if receipt.get("locator_proof") != expected_proof:
        raise RenderFailure("OFFICE_LOCATOR_PROOF_INVALID")
    return receipt


def _collect_office_provenance(
    office_script: Path, timeout_seconds: int
) -> list[dict[str, object]]:
    if os.name != "nt":
        raise RenderFailure("OFFICE_COM_REQUIRES_WINDOWS")
    powershell = (
        Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    returncode, stdout, _ = _run_bounded_capture(
        [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(office_script),
            "-Action",
            "Provenance",
        ],
        timeout_seconds=min(timeout_seconds, 120),
        stdout_limit=32 * 1024,
        stderr_limit=64 * 1024,
        timeout_error="OFFICE_PROVENANCE_TIMEOUT",
    )
    if returncode != 0:
        raise RenderFailure("OFFICE_PROVENANCE_FAILED")
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError:
        raise RenderFailure("OFFICE_PROVENANCE_INVALID") from None
    if not isinstance(value, Mapping) or not isinstance(value.get("applications"), list):
        raise RenderFailure("OFFICE_PROVENANCE_INVALID")
    applications: list[dict[str, object]] = []
    expected = {"word", "powerpoint", "excel"}
    for item in value["applications"]:
        if not isinstance(item, Mapping):
            raise RenderFailure("OFFICE_PROVENANCE_INVALID")
        name = item.get("name")
        raw_path = item.get("executable_path")
        version = item.get("file_version")
        if name not in expected or not isinstance(raw_path, str) or not isinstance(version, str):
            raise RenderFailure("OFFICE_PROVENANCE_INVALID")
        executable = Path(raw_path)
        if not executable.is_file() or not version.startswith("16."):
            raise RenderFailure("OFFICE16_EXECUTABLE_INVALID")
        actual_sha = _digest_file(executable)
        if item.get("executable_sha256") != actual_sha:
            raise RenderFailure("OFFICE_EXECUTABLE_DIGEST_MISMATCH")
        applications.append(
            {
                "name": name,
                "file_version": version,
                "product_version": item.get("product_version"),
                "executable_name": executable.name,
                "executable_path": str(executable.resolve()),
                "executable_size_bytes": executable.stat().st_size,
                "executable_sha256": actual_sha,
            }
        )
    if {str(item["name"]) for item in applications} != expected:
        raise RenderFailure("OFFICE_PROVENANCE_DENOMINATOR_MISMATCH")
    return sorted(applications, key=lambda item: str(item["name"]))


def _module_file_receipt(module_name: str) -> dict[str, object]:
    module = importlib.import_module(module_name)
    raw_path = getattr(module, "__file__", None)
    if not isinstance(raw_path, str):
        raise RenderFailure(f"MODULE_{module_name.upper()}_PATH_MISSING")
    path = Path(raw_path)
    if not path.is_file():
        raise RenderFailure(f"MODULE_{module_name.upper()}_PATH_MISSING")
    return {
        "module": module_name,
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": _digest_file(path),
    }


def _package_binary_receipts(module_name: str, suffixes: frozenset[str]) -> list[dict[str, object]]:
    module = importlib.import_module(module_name)
    raw_path = getattr(module, "__file__", None)
    if not isinstance(raw_path, str):
        raise RenderFailure(f"MODULE_{module_name.upper()}_PATH_MISSING")
    package_root = Path(raw_path).parent
    binaries = sorted(
        (
            path
            for path in package_root.rglob("*")
            if path.is_file() and path.suffix.lower() in suffixes
        ),
        key=lambda path: path.as_posix().lower(),
    )
    if not binaries:
        raise RenderFailure(f"MODULE_{module_name.upper()}_BINARY_MISSING")
    return [
        {
            "relative_path": path.relative_to(package_root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _digest_file(path),
        }
        for path in binaries
    ]


def _default_runtime_builder(
    office_script: Path,
    profile_sha256: str,
    generator_sha256: str,
    office_script_sha256: str,
) -> Mapping[str, object]:
    python_executable = Path(sys.executable)
    if not python_executable.is_file():
        raise RenderFailure("PYTHON_EXECUTABLE_MISSING")
    pdfium_modules = [_module_file_receipt("pypdfium2")]
    try:
        pdfium_modules.append(_module_file_receipt("pypdfium2_raw"))
    except (ImportError, RenderFailure):
        pdfium_modules.append(_module_file_receipt("pypdfium2.raw"))
    return {
        "schema": "tavonel.router_render_runtime.v1",
        "state": "FROZEN_BEFORE_MODEL_EXECUTION",
        "truth_opened": False,
        "model_calls": 0,
        "worker": {
            "hostname": socket.gethostname(),
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable_path": str(python_executable.resolve()),
            "executable_size_bytes": python_executable.stat().st_size,
            "executable_sha256": _digest_file(python_executable),
        },
        "pypdfium2": {
            "version": importlib.metadata.version("pypdfium2"),
            "module_files": pdfium_modules,
            "native_binaries": _package_binary_receipts(
                "pypdfium2_raw", frozenset({".dll", ".so", ".dylib"})
            ),
        },
        "pillow": {
            "version": importlib.metadata.version("Pillow"),
            "module_file": _module_file_receipt("PIL"),
            "native_binaries": _package_binary_receipts(
                "PIL", frozenset({".pyd", ".dll", ".so", ".dylib"})
            ),
        },
        "office16": {
            "automation_security": "msoAutomationSecurityForceDisable",
            "open_mode": "read_only_no_recent_files_no_visible_window",
            "applications": _collect_office_provenance(office_script, 120),
        },
        "profile_sha256": profile_sha256,
        "generator_sha256": generator_sha256,
        "office_script_sha256": office_script_sha256,
        "production_promotion": False,
    }


def _verify_png(path: Path, expected: RenderedPng, limits: RenderLimits) -> RenderedPng:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RenderFailure("RENDER_OUTPUT_MISSING")
    if path.stat().st_size > limits.maximum_render_bytes:
        raise RenderFailure("RENDER_SIZE_LIMIT_EXCEEDED")
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            actual = RenderedPng(width=image.width, height=image.height)
            if image.format != "PNG":
                raise RenderFailure("RENDER_FORMAT_INVALID")
    except RenderFailure:
        raise
    except Exception:
        raise RenderFailure("RENDER_PNG_INVALID") from None
    _check_dimensions(actual.width, actual.height, limits)
    if actual != expected:
        raise RenderFailure("RENDER_DIMENSIONS_MISMATCH")
    return actual


def _render_to_atomic_png(
    *,
    source: Path,
    page_number: int,
    bbox: tuple[int, int, int, int],
    destination: Path,
    limits: RenderLimits,
    pdf_renderer: PdfRenderer,
) -> RenderedPng:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{uuid.uuid4().hex}.part.png")
    try:
        expected = pdf_renderer(source, page_number, bbox, temporary, limits)
        actual = _verify_png(temporary, expected, limits)
        os.replace(temporary, destination)
        return actual
    finally:
        temporary.unlink(missing_ok=True)


def _validate_denominator(
    protocol: Mapping[str, Any],
    contract: Mapping[str, Any],
    sources: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    selection = protocol.get("source_selection")
    classes = protocol.get("required_classes")
    representations = contract.get("representations")
    if not isinstance(selection, Mapping) or not isinstance(classes, list):
        raise RenderFailure("PROTOCOL_SCHEMA_INVALID")
    if not isinstance(representations, Mapping):
        raise RenderFailure("SOURCE_CONTRACT_SCHEMA_INVALID")
    per_class = selection.get("selected_units_per_class")
    maximum_total = selection.get("maximum_total_units")
    if (
        isinstance(per_class, bool)
        or not isinstance(per_class, int)
        or isinstance(maximum_total, bool)
        or not isinstance(maximum_total, int)
        or maximum_total != per_class * len(classes)
        or len(sources) != maximum_total
    ):
        raise RenderFailure("SOURCE_TOTAL_DENOMINATOR_MISMATCH")
    counts = Counter(row.get("source_class") for row in sources)
    if set(counts) != set(classes) or any(
        counts[class_name] != per_class for class_name in classes
    ):
        raise RenderFailure("SOURCE_CLASS_DENOMINATOR_MISMATCH")
    unit_ids: set[str] = set()
    for row in sources:
        if not SOURCE_REQUIRED_FIELDS.issubset(row):
            raise RenderFailure("SOURCE_MANIFEST_SCHEMA_INVALID")
        unit_id = row.get("unit_id")
        if not isinstance(unit_id, str) or SAFE_UNIT.fullmatch(unit_id) is None:
            raise RenderFailure("SOURCE_UNIT_ID_INVALID")
        if unit_id in unit_ids:
            raise RenderFailure("SOURCE_UNIT_ID_DUPLICATE")
        unit_ids.add(unit_id)
        if row.get("truth_state") != "SEALED_UNOPENED":
            raise RenderFailure("SOURCE_TRUTH_STATE_INVALID")
        source_hash = row.get("source_sha256")
        if not isinstance(source_hash, str) or SHA.fullmatch(source_hash) is None:
            raise RenderFailure("SOURCE_DIGEST_INVALID")
        source_size = row.get("source_size_bytes")
        if isinstance(source_size, bool) or not isinstance(source_size, int) or source_size <= 0:
            raise RenderFailure("SOURCE_SIZE_INVALID")
        locator = row.get("target_locator")
        if not isinstance(locator, str) or not locator:
            raise RenderFailure("SOURCE_LOCATOR_INVALID")
    visual_rows: list[Mapping[str, Any]] = []
    for row in sources:
        representation = representations.get(row["source_class"])
        if not isinstance(representation, Mapping):
            raise RenderFailure("SOURCE_CLASS_CONTRACT_MISSING")
        if representation.get("visual_required") is True:
            if row["source_class"] in OFFICE_CLASSES:
                if not str(row.get("media_type", "")).startswith(
                    "application/vnd.openxmlformats-officedocument"
                ):
                    raise RenderFailure("OFFICE_MEDIA_TYPE_INVALID")
            elif row.get("media_type") != "application/pdf":
                raise RenderFailure("PDF_MEDIA_TYPE_INVALID")
            visual_rows.append(row)
        elif representation.get("visual_required") is not False:
            raise RenderFailure("SOURCE_VISUAL_REQUIREMENT_INVALID")
    return visual_rows


def _render_one(
    *,
    row: Mapping[str, Any],
    source_root: Path,
    render_root: Path,
    office_script: Path,
    limits: RenderLimits,
    profile_sha256: str,
    runtime_sha256: str,
    generator_sha256: str,
    office_script_sha256: str,
    pdf_renderer: PdfRenderer,
    office_exporter: OfficeExporter,
) -> dict[str, object]:
    unit_id = str(row["unit_id"])
    source_class = str(row["source_class"])
    source = _source_path(source_root, unit_id)
    if not source.is_file():
        raise RenderFailure("SOURCE_FILE_MISSING")
    source_size = source.stat().st_size
    if source_size != row.get("source_size_bytes"):
        raise RenderFailure("SOURCE_SIZE_MISMATCH")
    if source_size > limits.maximum_source_bytes:
        raise RenderFailure("SOURCE_SIZE_LIMIT_EXCEEDED")
    if _digest_file(source) != row.get("source_sha256"):
        raise RenderFailure("SOURCE_DIGEST_MISMATCH")
    locator = str(row["target_locator"])
    output_relative = f"{unit_id.replace(':', '_')}.png"
    output = _safe_file(render_root, output_relative)
    intermediate_relative: str | None = None
    intermediate_sha: str | None = None
    intermediate_size: int | None = None
    if source_class in OFFICE_CLASSES:
        _, _, target_kind, target_ordinal = _validate_office_locator(
            source, source_class, locator
        )
        kind = source_class.removeprefix("office_korean_")
        intermediate_relative = f"intermediate/{unit_id.replace(':', '_')}.pdf"
        intermediate = _safe_file(render_root, intermediate_relative)
        intermediate.parent.mkdir(parents=True, exist_ok=True)
        temporary_pdf = intermediate.with_name(f".{intermediate.stem}.{uuid.uuid4().hex}.part.pdf")
        office_source = intermediate.with_name(
            f".{intermediate.stem}.{uuid.uuid4().hex}.locator.{kind}"
        )
        try:
            shutil.copyfile(source, office_source)
            if _digest_file(office_source) != row.get("source_sha256"):
                raise RenderFailure("OFFICE_SOURCE_COPY_DIGEST_MISMATCH")
            office_receipt = office_exporter(
                kind,
                office_source,
                temporary_pdf,
                office_script,
                limits.per_unit_timeout_seconds,
                target_kind if kind == "docx" else None,
                target_ordinal if kind == "docx" else None,
            )
            if not temporary_pdf.is_file() or temporary_pdf.stat().st_size <= 4:
                raise RenderFailure("OFFICE_PDF_MISSING")
            if temporary_pdf.stat().st_size > limits.maximum_intermediate_pdf_bytes:
                raise RenderFailure("OFFICE_PDF_SIZE_LIMIT_EXCEEDED")
            with temporary_pdf.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise RenderFailure("OFFICE_PDF_MAGIC_INVALID")
            os.replace(temporary_pdf, intermediate)
        finally:
            temporary_pdf.unlink(missing_ok=True)
            office_source.unlink(missing_ok=True)
        intermediate_sha = _digest_file(intermediate)
        intermediate_size = intermediate.stat().st_size
        raw_resolved_page = office_receipt.get("resolved_page_number")
        if (
            isinstance(raw_resolved_page, bool)
            or not isinstance(raw_resolved_page, int)
            or raw_resolved_page <= 0
        ):
            raise RenderFailure("OFFICE_RESOLVED_PAGE_INVALID")
        resolved_page = raw_resolved_page
        dimensions = _render_to_atomic_png(
            source=intermediate,
            page_number=1,
            bbox=(0, 0, 1000, 1000),
            destination=output,
            limits=limits,
            pdf_renderer=pdf_renderer,
        )
        locator_proof = (
            "word_body_element_formatted_range_page"
            if source_class == "office_korean_docx"
            else f"{target_kind}_export_page_1"
        )
    else:
        page_number, bbox = _parse_pdf_locator(locator)
        resolved_page = page_number
        dimensions = _render_to_atomic_png(
            source=source,
            page_number=page_number,
            bbox=bbox,
            destination=output,
            limits=limits,
            pdf_renderer=pdf_renderer,
        )
        locator_proof = "pdf_page_bbox"
    return {
        "unit_id": unit_id,
        "source_class": source_class,
        "source_sha256": row["source_sha256"],
        "target_locator": locator,
        "resolved_page_number": resolved_page,
        "intermediate_pdf_sha256": intermediate_sha,
        "intermediate_pdf_size_bytes": intermediate_size,
        "intermediate_pdf_relative_path": intermediate_relative,
        "render_sha256": _digest_file(output),
        "render_size_bytes": output.stat().st_size,
        "render_width_px": dimensions.width,
        "render_height_px": dimensions.height,
        "render_relative_path": output_relative,
        "render_profile_sha256": profile_sha256,
        "render_runtime_sha256": runtime_sha256,
        "generator_sha256": generator_sha256,
        "office_script_sha256": office_script_sha256,
        "status": "SUCCEEDED",
        "locator_proof": locator_proof,
    }


def render_selected_inputs(
    *,
    protocol_path: Path,
    source_manifest_path: Path,
    source_contract_path: Path,
    source_root: Path,
    render_root: Path,
    manifest_path: Path,
    attempt_report_path: Path,
    profile_path: Path,
    runtime_path: Path,
    office_script: Path,
    limits: RenderLimits | None = None,
    pdf_renderer: PdfRenderer = _run_bounded_pdf_render,
    office_exporter: OfficeExporter = _run_office_export,
    runtime_builder: RuntimeBuilder = _default_runtime_builder,
) -> RenderBatchResult:
    limits = limits or RenderLimits()
    _validate_limits(limits)
    if not office_script.is_file():
        raise RenderFailure("OFFICE_SCRIPT_MISSING")
    protocol = _load_json(protocol_path)
    contract = _load_json(source_contract_path)
    sources = _load_jsonl(source_manifest_path)
    visual_rows = _validate_denominator(protocol, contract, sources)
    profile_bytes = _canonical_json(limits.as_profile())
    _write_immutable(profile_path, profile_bytes)
    profile_sha256 = _digest_bytes(profile_bytes)
    generator_sha256 = _digest_file(Path(__file__))
    office_script_sha256 = _digest_file(office_script)
    runtime = runtime_builder(
        office_script,
        profile_sha256,
        generator_sha256,
        office_script_sha256,
    )
    runtime_bytes = _canonical_json(runtime)
    _write_immutable(runtime_path, runtime_bytes)
    runtime_sha256 = _digest_bytes(runtime_bytes)
    successes: list[dict[str, object]] = []
    attempts: list[dict[str, object]] = []
    blockers: list[str] = []
    for row in visual_rows:
        unit_id = str(row["unit_id"])
        try:
            rendered = _render_one(
                row=row,
                source_root=source_root,
                render_root=render_root,
                office_script=office_script,
                limits=limits,
                profile_sha256=profile_sha256,
                runtime_sha256=runtime_sha256,
                generator_sha256=generator_sha256,
                office_script_sha256=office_script_sha256,
                pdf_renderer=pdf_renderer,
                office_exporter=office_exporter,
            )
            successes.append(rendered)
            attempts.append(
                {
                    "unit_id": unit_id,
                    "source_class": row["source_class"],
                    "source_sha256": row["source_sha256"],
                    "target_locator": row["target_locator"],
                    "status": "SUCCEEDED",
                    "error_code": None,
                }
            )
        except RenderFailure as error:
            code = str(error)
            blockers.append(f"{unit_id}:{code}")
            attempts.append(
                {
                    "unit_id": unit_id,
                    "source_class": row["source_class"],
                    "source_sha256": row["source_sha256"],
                    "target_locator": row["target_locator"],
                    "status": "FAILED",
                    "error_code": code,
                }
            )
        except Exception:
            blockers.append(f"{unit_id}:UNEXPECTED_RENDER_FAILURE")
            attempts.append(
                {
                    "unit_id": unit_id,
                    "source_class": row["source_class"],
                    "source_sha256": row["source_sha256"],
                    "target_locator": row["target_locator"],
                    "status": "FAILED",
                    "error_code": "UNEXPECTED_RENDER_FAILURE",
                }
            )
    _atomic_replace(attempt_report_path, _canonical_jsonl(attempts))
    passed = len(successes) == len(visual_rows) and not blockers
    manifest_written = False
    if passed:
        _write_immutable(manifest_path, _canonical_jsonl(successes))
        manifest_written = True
    return RenderBatchResult(
        passed=passed,
        total_sources=len(sources),
        expected_visual_units=len(visual_rows),
        succeeded=len(successes),
        failed=len(visual_rows) - len(successes),
        blockers=tuple(blockers),
        profile_sha256=profile_sha256,
        runtime_sha256=runtime_sha256,
        manifest_written=manifest_written,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-contract", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--render-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--attempt-report", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument(
        "--office-script",
        type=Path,
        default=Path(__file__).with_name("office_render.ps1"),
    )
    args = parser.parse_args()
    try:
        result = render_selected_inputs(
            protocol_path=args.protocol,
            source_manifest_path=args.source_manifest,
            source_contract_path=args.source_contract,
            source_root=args.source_root,
            render_root=args.render_root,
            manifest_path=args.manifest,
            attempt_report_path=args.attempt_report,
            profile_path=args.profile,
            runtime_path=args.runtime,
            office_script=args.office_script,
        )
    except RenderFailure as error:
        print(json.dumps({"passed": False, "blockers": [str(error)]}, sort_keys=True))
        return 1
    print(json.dumps(result.as_dict(), sort_keys=True))
    return 0 if result.passed else 1


def _pdf_worker_main(arguments: Sequence[str]) -> int:
    if len(arguments) != 5:
        return 2
    source = Path(arguments[0])
    try:
        page_number = int(arguments[1])
        bbox_values = tuple(int(value) for value in arguments[2].split(","))
        profile = json.loads(arguments[4])
        if len(bbox_values) != 4 or not isinstance(profile, Mapping):
            return 2
        limits = RenderLimits(
            dpi=int(profile["dpi"]),
            maximum_source_bytes=int(profile["maximum_source_bytes"]),
            maximum_intermediate_pdf_bytes=int(profile["maximum_intermediate_pdf_bytes"]),
            maximum_render_bytes=int(profile["maximum_render_bytes"]),
            maximum_pixels=int(profile["maximum_pixels"]),
            maximum_dimension_px=int(profile["maximum_dimension_px"]),
            per_unit_timeout_seconds=int(profile["per_unit_timeout_seconds"]),
        )
        rendered = _render_pdf_page(
            source,
            page_number,
            (bbox_values[0], bbox_values[1], bbox_values[2], bbox_values[3]),
            Path(arguments[3]),
            limits,
        )
    except (KeyError, TypeError, ValueError, RenderFailure):
        return 1
    print(json.dumps({"width": rendered.width, "height": rendered.height}))
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--pdf-worker":
        raise SystemExit(_pdf_worker_main(sys.argv[2:]))
    raise SystemExit(main())
