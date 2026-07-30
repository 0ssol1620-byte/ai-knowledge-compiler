"""One-shot parser process executed inside the CPU worker sandbox."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import re
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from akc_api.parsers import FileValidationError, parse_document, validate_file
from akc_api.settings import Settings
from akc_cir import CanonicalDocument, normalize_block_text
from akc_native_parsers import (
    ParseContext,
    ParserLimits,
    StructuredParseError,
    parse_non_pdf_to_cir,
    parse_pdf_to_cir,
)
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pypdfium2 import PdfDocument  # type: ignore[import-untyped]

from .preprocessing import preprocess_inference_raster

_TEXT_TYPES = frozenset({"csv", "html", "htm", "txt", "md", "vtt", "srt"})
_IMAGE_TYPES = frozenset({"png", "jpg", "jpeg", "webp", "tif", "tiff"})
_STRUCTURED_NATIVE_EXTENSIONS = frozenset(
    {".docx", ".pptx", ".xlsx", ".html", ".htm", ".srt", ".vtt"}
)
_SAFE_FILENAME = re.compile(
    r"^page-[1-9][0-9]{0,4}-(?:preview|thumbnail|inference-(?:200|300))\.png$"
)


def _disable_network() -> None:
    """Deny Python-level network access inside the parser child."""

    def denied(*_args: object, **_kwargs: object) -> Any:
        raise PermissionError("parser_network_disabled")

    socket_module: Any = socket
    socket_module.socket = denied
    socket_module.create_connection = denied


def _install_resource_limits(request: dict[str, Any]) -> None:
    """Apply kernel limits when available (the production image is Linux)."""

    if os.name == "nt":
        return
    resource: Any = importlib.import_module("resource")

    memory = int(request["child_memory_bytes"])
    file_bytes = int(request["child_file_bytes"])
    open_files = int(request["child_open_files"])
    cpu_seconds = max(1, math.ceil(float(request["timeout_seconds"])) + 1)
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (open_files, open_files))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    os.umask(0o077)


def _parser_settings(request: dict[str, Any]) -> Settings:
    return Settings(
        env="test",
        data_dir=Path(request["workspace"]),
        # Settings retains the product's 50 MiB minimum while the sandbox
        # applies its independent (and potentially smaller) byte fence before
        # materializing the source.
        max_upload_bytes=max(50 * 1024 * 1024, int(request["max_upload_bytes"])),
        analysis_max_source_bytes=int(request["max_upload_bytes"]),
        max_pages=int(request["max_pages"]),
        max_archive_files=int(request["max_archive_files"]),
        max_archive_uncompressed_bytes=int(request["max_archive_uncompressed_bytes"]),
        max_archive_ratio=float(request["max_archive_ratio"]),
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
    )


def _native_parser_limits(request: dict[str, Any]) -> ParserLimits:
    archive_bytes = int(request["max_archive_uncompressed_bytes"])
    return ParserLimits(
        max_input_bytes=int(request["max_upload_bytes"]),
        max_archive_entries=int(request["max_archive_files"]),
        max_archive_uncompressed_bytes=archive_bytes,
        max_archive_member_bytes=min(64 * 1024 * 1024, archive_bytes),
        max_compression_ratio=float(request["max_archive_ratio"]),
        max_total_text_chars=int(request["max_extracted_chars_total"]),
        max_slides=int(request["max_pages"]),
        max_sheets=int(request["max_pages"]),
    )


def _native_page_rows(canonical: CanonicalDocument) -> list[dict[str, Any]]:
    page_parts: dict[int, list[str]] = {}
    for block in canonical.ordered_blocks():
        source_ref = block.source_refs[0]
        text = block.normalized_text or block.raw_text or block.markdown or ""
        if text:
            page_parts.setdefault(source_ref.page_number1, []).append(text)
    geometry_rows = canonical.metadata.get("pages")
    geometry_by_page = (
        {
            int(item["pageIndex0"]) + 1: item
            for item in geometry_rows
            if isinstance(item, dict) and isinstance(item.get("pageIndex0"), int)
        }
        if isinstance(geometry_rows, list)
        else {}
    )
    page_numbers = sorted(set(page_parts) | set(geometry_by_page))
    if page_numbers != list(range(1, len(page_numbers) + 1)):
        raise FileValidationError(
            "PARSER_RESULT_INVALID",
            "native parser returned non-contiguous logical pages",
        )
    return [
        {
            "page_number": page_number,
            "text": "\n\n".join(page_parts.get(page_number, ())),
            "width_pt": geometry_by_page.get(page_number, {}).get("widthPt"),
            "height_pt": geometry_by_page.get(page_number, {}).get("heightPt"),
            "image_coverage": 0.0,
        }
        for page_number in page_numbers
    ]


def _fit_image(image: Image.Image, max_long_edge: int) -> Image.Image:
    copy = image.convert("RGB")
    copy.thumbnail((max_long_edge, max_long_edge), Image.Resampling.LANCZOS)
    return copy


def _write_png(
    image: Image.Image,
    *,
    output_dir: Path,
    page_number: int,
    kind: str,
    max_long_edge: int,
    max_bytes: int,
    dpi: int | None = None,
    transform: dict[str, Any] | None = None,
) -> dict[str, Any]:
    filename = f"page-{page_number}-{kind}.png"
    if not _SAFE_FILENAME.fullmatch(filename):
        raise RuntimeError("unsafe_preview_filename")
    target = output_dir / filename
    fitted = _fit_image(image, max_long_edge)
    save_options: dict[str, Any] = {"format": "PNG", "optimize": False}
    if dpi is not None:
        save_options["dpi"] = (dpi, dpi)
    fitted.save(target, **save_options)
    size = target.stat().st_size
    if size <= 0 or size > max_bytes:
        target.unlink(missing_ok=True)
        raise FileValidationError(
            "PREVIEW_SIZE_LIMIT",
            "rendered preview exceeds the configured bound",
        )
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = {
        "filename": filename,
        "sha256": digest,
        "size_bytes": size,
        "width": fitted.width,
        "height": fitted.height,
        "content_type": "image/png",
    }
    if dpi is not None:
        manifest["dpi"] = dpi
        manifest["colorspace"] = "RGB"
    if transform is not None:
        manifest["transform"] = transform
    return manifest


def _write_preview_pair(
    image: Image.Image,
    *,
    output_dir: Path,
    page_number: int,
    request: dict[str, Any],
    source_render_dpi: int = 300,
) -> dict[str, Any]:
    if image.width <= 0 or image.height <= 0:
        raise FileValidationError("PREVIEW_DIMENSIONS", "preview has invalid dimensions")
    if image.width * image.height > int(request["inference_raster_max_pixels"]):
        raise FileValidationError(
            "PREVIEW_DIMENSIONS",
            "inference raster exceeds the configured pixel limit",
        )
    inference_rasters = []
    processed, transform = preprocess_inference_raster(image)
    try:
        for dpi in request["inference_raster_dpis"]:
            target_long_edge = max(
                1,
                round(max(processed.width, processed.height) * int(dpi) / source_render_dpi),
            )
            inference_rasters.append(
                _write_png(
                    processed,
                    output_dir=output_dir,
                    page_number=page_number,
                    kind=f"inference-{dpi}",
                    max_long_edge=target_long_edge,
                    max_bytes=int(request["inference_raster_max_bytes_per_asset"]),
                    dpi=int(dpi),
                    transform=transform,
                )
            )
    finally:
        processed.close()
    display_image = ImageOps.exif_transpose(image)
    try:
        preview = _write_png(
            display_image,
            output_dir=output_dir,
            page_number=page_number,
            kind="preview",
            max_long_edge=int(request["preview_max_long_edge"]),
            max_bytes=int(request["preview_max_bytes_per_asset"]),
        )
        thumbnail = _write_png(
            display_image,
            output_dir=output_dir,
            page_number=page_number,
            kind="thumbnail",
            max_long_edge=int(request["preview_thumbnail_long_edge"]),
            max_bytes=int(request["preview_max_bytes_per_asset"]),
        )
    finally:
        display_image.close()
    return {
        "status": "available",
        "preview": preview,
        "thumbnail": thumbnail,
        "inference_rasters": inference_rasters,
    }


def _render_pdf_pages(
    source_path: Path,
    *,
    output_dir: Path,
    request: dict[str, Any],
    password: bytes | None,
) -> dict[int, dict[str, Any]]:
    rendered: dict[int, dict[str, Any]] = {}
    document = PdfDocument(
        str(source_path),
        password=password.decode("utf-8") if password is not None else None,
    )
    try:
        for index in range(len(document)):
            number = index + 1
            page = document[index]
            try:
                width_pt, height_pt = page.get_size()
                scale = max(int(dpi) for dpi in request["inference_raster_dpis"]) / 72.0
                width = max(1, math.ceil(width_pt * scale))
                height = max(1, math.ceil(height_pt * scale))
                if width * height > int(request["inference_raster_max_pixels"]):
                    rendered[number] = {
                        "status": "unavailable",
                        "reason": "render_dimensions_exceeded",
                    }
                    continue
                bitmap = page.render(scale=scale)
                try:
                    rendered[number] = _write_preview_pair(
                        bitmap.to_pil(),
                        output_dir=output_dir,
                        page_number=number,
                        request=request,
                        source_render_dpi=max(int(dpi) for dpi in request["inference_raster_dpis"]),
                    )
                finally:
                    bitmap.close()
            except FileValidationError as exc:
                rendered[number] = {
                    "status": "unavailable",
                    "reason": exc.code.casefold(),
                }
            except Exception:
                rendered[number] = {
                    "status": "unavailable",
                    "reason": "render_failed",
                }
            finally:
                page.close()
    finally:
        document.close()
    return rendered


def _render_image(
    source_path: Path,
    *,
    output_dir: Path,
    request: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    with Image.open(source_path) as image:
        image.load()
        return {
            1: _write_preview_pair(
                image,
                output_dir=output_dir,
                page_number=1,
                request=request,
                source_render_dpi=max(int(dpi) for dpi in request["inference_raster_dpis"]),
            )
        }


def _render_text_page(
    text: str,
    *,
    output_dir: Path,
    request: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    width, height = 1200, 1600
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    sanitized = "".join(char if char in "\n\t" or ord(char) >= 32 else "\ufffd" for char in text)
    lines: list[str] = []
    for logical_line in sanitized[:12_000].splitlines():
        lines.extend(
            logical_line[start : start + 100]
            for start in range(0, min(len(logical_line), 1000), 100)
        )
        if len(lines) >= 70:
            break
    draw.multiline_text(
        (70, 70),
        "\n".join(lines[:70]) or "(empty text page)",
        fill="#1f2933",
        font=font,
        spacing=8,
    )
    return {
        1: _write_preview_pair(
            canvas,
            output_dir=output_dir,
            page_number=1,
            request=request,
            source_render_dpi=max(int(dpi) for dpi in request["inference_raster_dpis"]),
        )
    }


def _render_previews(
    *,
    source_path: Path,
    document_type: str,
    page_text: dict[int, str],
    output_dir: Path,
    request: dict[str, Any],
    pdf_password: bytes | None,
) -> dict[int, dict[str, Any]]:
    if not bool(request["preview_enabled"]):
        return {
            number: {"status": "unavailable", "reason": "preview_disabled"} for number in page_text
        }
    if document_type == "pdf":
        rendered = _render_pdf_pages(
            source_path,
            output_dir=output_dir,
            request=request,
            password=pdf_password,
        )
    elif document_type in _IMAGE_TYPES:
        rendered = _render_image(
            source_path,
            output_dir=output_dir,
            request=request,
        )
    elif document_type in _TEXT_TYPES:
        rendered = _render_text_page(
            page_text.get(1, ""),
            output_dir=output_dir,
            request=request,
        )
    else:
        rendered = {
            number: {
                "status": "unavailable",
                "reason": "unsupported_document_preview",
            }
            for number in page_text
        }
    preview_total = 0
    inference_total = 0
    preview_maximum = int(request["preview_max_total_bytes"])
    inference_maximum = int(request["inference_raster_max_total_bytes"])
    for page_number in sorted(rendered):
        preview = rendered[page_number]
        if preview.get("status") != "available":
            continue
        preview_descriptors = [preview["preview"], preview["thumbnail"]]
        inference_descriptors = list(preview["inference_rasters"])
        preview_size = sum(int(descriptor["size_bytes"]) for descriptor in preview_descriptors)
        inference_size = sum(int(descriptor["size_bytes"]) for descriptor in inference_descriptors)
        if (
            preview_total + preview_size <= preview_maximum
            and inference_total + inference_size <= inference_maximum
        ):
            preview_total += preview_size
            inference_total += inference_size
            continue
        for descriptor in (*preview_descriptors, *inference_descriptors):
            (output_dir / str(descriptor["filename"])).unlink(missing_ok=True)
        rendered[page_number] = {
            "status": "unavailable",
            "reason": "derived_raster_total_limit",
        }
    return rendered


def _success_manifest(
    request: dict[str, Any],
    *,
    pdf_password: bytearray | None,
) -> dict[str, Any]:
    source_path = Path(str(request["source_path"])).resolve(strict=True)
    workspace = Path(str(request["workspace"])).resolve(strict=True)
    output_dir = Path(str(request["preview_dir"])).resolve(strict=False)
    if workspace not in source_path.parents or output_dir.parent != workspace:
        raise RuntimeError("sandbox_path_escape")
    if source_path.stat().st_size > int(request["max_upload_bytes"]):
        raise FileValidationError(
            "FILE_TOO_LARGE",
            "file exceeds the isolated analysis source limit",
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    raw = source_path.read_bytes()
    settings = _parser_settings(request)
    extension, digest = validate_file(
        filename=str(request["filename"]),
        declared_mime=str(request["content_type"]),
        data=raw,
        expected_sha256=str(request["sha256"]),
        settings=settings,
    )
    password_bytes = bytes(pdf_password) if pdf_password is not None else None
    canonical = None
    parser_context = ParseContext(
        tenant_id=str(request["tenant_id"]),
        document_id=str(request["document_id"]),
        document_version_id=str(request["document_version_id"]),
        created_at=datetime.fromisoformat(str(request["created_at"])),
        retrieved_at=datetime.fromisoformat(str(request["retrieved_at"])),
    )
    if extension in _STRUCTURED_NATIVE_EXTENSIONS or extension == ".pdf":
        if extension == ".pdf":
            canonical = parse_pdf_to_cir(
                filename=str(request["filename"]),
                declared_mime=str(request["content_type"]),
                data=raw,
                context=parser_context,
                limits=_native_parser_limits(request),
                password=password_bytes,
                max_pages=int(request["max_pages"]),
            )
        else:
            canonical = parse_non_pdf_to_cir(
                filename=str(request["filename"]),
                declared_mime=str(request["content_type"]),
                data=raw,
                context=parser_context,
                limits=_native_parser_limits(request),
            )
        document_type = str(canonical.metadata["documentType"])
        page_rows = _native_page_rows(canonical)
    else:
        parsed = parse_document(
            str(request["filename"]),
            raw,
            settings,
            pdf_password=password_bytes,
        )
        document_type = parsed.document_type or extension.removeprefix(".")
        page_rows = [
            {
                "page_number": page.page_number,
                "text": page.text,
                "width_pt": page.width_pt,
                "height_pt": page.height_pt,
                "image_coverage": page.image_coverage,
            }
            for page in parsed.pages
        ]
    total_characters = sum(len(str(page["text"])) for page in page_rows)
    if total_characters > int(request["max_extracted_chars_total"]):
        raise FileValidationError(
            "EXTRACTED_TEXT_LIMIT",
            "extracted text exceeds the total character limit",
        )
    if any(
        len(str(page["text"])) > int(request["max_extracted_chars_per_page"]) for page in page_rows
    ):
        raise FileValidationError(
            "EXTRACTED_TEXT_LIMIT",
            "extracted text exceeds the per-page character limit",
        )
    page_text = {int(page["page_number"]): str(page["text"]) for page in page_rows}
    previews = _render_previews(
        source_path=source_path,
        document_type=document_type,
        page_text=page_text,
        output_dir=output_dir,
        request=request,
        pdf_password=password_bytes,
    )
    normalized_page_rows: list[dict[str, Any]] = []
    for page in page_rows:
        normalized = normalize_block_text(
            str(page["text"]),
            block_type="paragraph",
        )
        normalized_page_rows.append(
            {
                **page,
                "normalized_text": normalized.normalized_text,
                "normalization": normalized.payload(),
            }
        )
    return {
        "schema_version": "1.0",
        "ok": True,
        "source_sha256": digest,
        "document_type": document_type,
        "pages": [
            {
                **page,
                "preview": previews.get(
                    int(page["page_number"]),
                    {
                        "status": "unavailable",
                        "reason": "preview_not_generated",
                    },
                ),
            }
            for page in normalized_page_rows
        ],
        "canonical_document": (
            canonical.model_dump(mode="json", by_alias=True, exclude_none=True)
            if canonical is not None
            else None
        ),
    }


def _read_pdf_password(request: dict[str, Any]) -> bytearray | None:
    if not bool(request.get("pdf_password_from_stdin", False)):
        return None
    length_bytes = sys.stdin.buffer.read(4)
    if len(length_bytes) != 4:
        raise FileValidationError("PDF_PASSWORD_CHANNEL_INVALID", "password channel is incomplete")
    length = int.from_bytes(length_bytes, "big")
    if length <= 0 or length > 1024:
        raise FileValidationError("PDF_PASSWORD_CHANNEL_INVALID", "password length is invalid")
    password = bytearray(sys.stdin.buffer.read(length))
    if len(password) != length or sys.stdin.buffer.read(1):
        for index in range(len(password)):
            password[index] = 0
        password.clear()
        raise FileValidationError("PDF_PASSWORD_CHANNEL_INVALID", "password channel is invalid")
    return password


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(2)
    request_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    _install_resource_limits(request)
    _disable_network()
    password: bytearray | None = None
    try:
        password = _read_pdf_password(request)
        result = _success_manifest(request, pdf_password=password)
    except StructuredParseError as exc:
        result = {
            "schema_version": "1.0",
            "ok": False,
            "error_code": exc.code,
            "retryable": False,
        }
    except FileValidationError as exc:
        result = {
            "schema_version": "1.0",
            "ok": False,
            "error_code": exc.code,
            "retryable": False,
        }
    except Exception:
        result = {
            "schema_version": "1.0",
            "ok": False,
            "error_code": "PARSER_INTERNAL_ERROR",
            "retryable": True,
        }
    finally:
        if password is not None:
            for index in range(len(password)):
                password[index] = 0
            password.clear()
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    result_path.write_bytes(encoded)


if __name__ == "__main__":
    main()
