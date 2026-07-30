"""Deterministic native PDF extraction with page geometry and embedded assets."""

from __future__ import annotations

import hashlib
import io
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from akc_cir import BlockType, CanonicalDocument
from pypdf import PdfReader
from pypdf.generic import ContentStream

from .models import (
    CirBuilder,
    ParseContext,
    ParserLimits,
    SourceLocation,
    StructuredParseError,
    normalize_text,
)

_PATH_OPERATORS = frozenset({b"m", b"l", b"c", b"v", b"y", b"re"})
_PAINT_OPERATORS = frozenset(
    {
        b"S",
        b"s",
        b"f",
        b"F",
        b"f*",
        b"B",
        b"B*",
        b"b",
        b"b*",
    }
)


@dataclass(frozen=True, slots=True)
class _TextObject:
    page_index0: int
    native_object_id: str
    text: str
    bbox1000: tuple[int, int, int, int]
    font_size_pt: float


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    return result if math.isfinite(result) else fallback


def _box_payload(value: Any) -> list[float] | None:
    if value is None:
        return None
    try:
        return [
            round(_safe_float(value.left), 6),
            round(_safe_float(value.bottom), 6),
            round(_safe_float(value.right), 6),
            round(_safe_float(value.top), 6),
        ]
    except (AttributeError, TypeError, ValueError):
        return None


def _display_bbox1000(
    *,
    crop: Sequence[float],
    rotation: int,
    bbox: Sequence[float],
) -> tuple[int, int, int, int] | None:
    left, bottom, right, top = crop
    width = right - left
    height = top - bottom
    if width <= 0 or height <= 0:
        return None
    x1, y1, x2, y2 = bbox
    points = (
        (x1 - left, y1 - bottom),
        (x1 - left, y2 - bottom),
        (x2 - left, y1 - bottom),
        (x2 - left, y2 - bottom),
    )
    effective_rotation = rotation % 360
    if effective_rotation == 90:
        transformed = tuple((y, width - x) for x, y in points)
        display_width, display_height = height, width
    elif effective_rotation == 180:
        transformed = tuple((width - x, height - y) for x, y in points)
        display_width, display_height = width, height
    elif effective_rotation == 270:
        transformed = tuple((height - y, x) for x, y in points)
        display_width, display_height = height, width
    else:
        transformed = points
        display_width, display_height = width, height
    xs = [point[0] for point in transformed]
    ys = [display_height - point[1] for point in transformed]
    normalized = (
        max(0, min(1000, round(min(xs) / display_width * 1000))),
        max(0, min(1000, round(min(ys) / display_height * 1000))),
        max(0, min(1000, round(max(xs) / display_width * 1000))),
        max(0, min(1000, round(max(ys) / display_height * 1000))),
    )
    if normalized[0] >= normalized[2] or normalized[1] >= normalized[3]:
        return None
    return normalized


def _effective_text_origin(
    cm: Sequence[float],
    tm: Sequence[float],
) -> tuple[float, float, float]:
    x = _safe_float(tm[4])
    y = _safe_float(tm[5])
    a, b, c, d, e, f = (_safe_float(value) for value in cm[:6])
    transformed_x = x * a + y * c + e
    transformed_y = x * b + y * d + f
    scale = max(math.hypot(a, b), math.hypot(c, d), 0.01)
    return transformed_x, transformed_y, scale


def _text_objects(
    *,
    page: Any,
    page_index0: int,
    crop: Sequence[float],
    rotation: int,
) -> tuple[_TextObject, ...]:
    objects: list[_TextObject] = []

    def visitor(
        text: str,
        cm: Sequence[float],
        tm: Sequence[float],
        _font: dict[str, Any] | None,
        font_size: float,
    ) -> None:
        value = normalize_text(text)
        if not value:
            return
        x, y, scale = _effective_text_origin(cm, tm)
        effective_font = max(1.0, min(512.0, abs(_safe_float(font_size, 10.0)) * scale))
        longest_line = max((len(line) for line in value.splitlines()), default=1)
        width = min(
            crop[2] - crop[0], max(effective_font * 0.42, longest_line * effective_font * 0.52)
        )
        height = max(effective_font * 1.15, len(value.splitlines()) * effective_font * 1.15)
        bbox = _display_bbox1000(
            crop=crop,
            rotation=rotation,
            bbox=(x, y - effective_font * 0.25, x + width, y + height),
        )
        if bbox is None:
            return
        identity = hashlib.sha256(
            f"{page_index0}\x1f{len(objects)}\x1f{x:.6f}\x1f{y:.6f}\x1f{value}".encode()
        ).hexdigest()[:20]
        objects.append(
            _TextObject(
                page_index0=page_index0,
                native_object_id=f"pdf/page/{page_index0}/text/{identity}",
                text=value,
                bbox1000=bbox,
                font_size_pt=round(effective_font, 4),
            )
        )

    page.extract_text(visitor_text=visitor)
    return tuple(objects)


def _media_type(filename: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".jp2": "image/jp2",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }.get(Path(filename).suffix.casefold(), "application/octet-stream")


def _register_images(
    page: Any,
    *,
    page_index0: int,
    builder: CirBuilder,
) -> dict[str, str]:
    assets: dict[str, str] = {}
    for index, image in enumerate(page.images):
        payload = bytes(image.data)
        if not payload:
            continue
        name = normalize_text(str(image.name or f"image-{index}"))
        asset_id = builder.register_asset(
            payload=payload,
            native_part=f"pdf/page/{page_index0}/image/{index}/{name}",
            media_type=_media_type(name),
            kind="embedded-image",
            filename=name,
            width_px=getattr(getattr(image, "image", None), "width", None),
            height_px=getattr(getattr(image, "image", None), "height", None),
            metadata={"pageIndex0": page_index0, "objectName": name},
        )
        assets[name.casefold()] = asset_id
        assets[Path(name).stem.casefold()] = asset_id
    return assets


def _transform_point(matrix: Sequence[float], x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return x * a + y * c + e, x * b + y * d + f


def _multiply_matrix(left: Sequence[float], right: Sequence[float]) -> tuple[float, ...]:
    a1, b1, c1, d1, e1, f1 = left
    a2, b2, c2, d2, e2, f2 = right
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def _operand_points(operator: bytes, operands: Sequence[Any]) -> Iterable[tuple[float, float]]:
    values = [_safe_float(value) for value in operands]
    if operator in {b"m", b"l"} and len(values) >= 2:
        yield values[0], values[1]
    elif operator == b"re" and len(values) >= 4:
        x, y, width, height = values[:4]
        yield from ((x, y), (x + width, y), (x, y + height), (x + width, y + height))
    elif operator == b"c" and len(values) >= 6:
        yield from ((values[0], values[1]), (values[2], values[3]), (values[4], values[5]))
    elif operator in {b"v", b"y"} and len(values) >= 4:
        yield from ((values[0], values[1]), (values[2], values[3]))


def _extract_graphics(
    page: Any,
    *,
    page_index0: int,
    crop: Sequence[float],
    rotation: int,
    image_assets: dict[str, str],
    builder: CirBuilder,
) -> None:
    contents = page.get_contents()
    if contents is None:
        return
    stream = ContentStream(contents, page.pdf)
    matrix: tuple[float, ...] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    stack: list[tuple[float, ...]] = []
    path_points: list[tuple[float, float]] = []
    drawing_index = 0
    image_index = 0
    for operands, operator in stream.operations:
        if operator == b"q":
            stack.append(matrix)
        elif operator == b"Q":
            matrix = stack.pop() if stack else (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        elif operator == b"cm" and len(operands) >= 6:
            matrix = _multiply_matrix(
                tuple(_safe_float(value) for value in operands[:6]),
                matrix,
            )
        elif operator in _PATH_OPERATORS:
            path_points.extend(
                _transform_point(matrix, x, y) for x, y in _operand_points(operator, operands)
            )
        elif operator in _PAINT_OPERATORS:
            if path_points:
                xs = [point[0] for point in path_points]
                ys = [point[1] for point in path_points]
                bbox = _display_bbox1000(
                    crop=crop,
                    rotation=rotation,
                    bbox=(min(xs), min(ys), max(xs), max(ys)),
                )
                if bbox is not None:
                    builder.add_block(
                        block_type=BlockType.FIGURE,
                        location=SourceLocation(
                            page_index0=page_index0,
                            native_object_id=f"pdf/page/{page_index0}/drawing/{drawing_index}",
                            bbox1000=bbox,
                        ),
                        markdown="*[Native vector drawing]*",
                        quality_flags=("vector_drawing_native",),
                    )
                    drawing_index += 1
            path_points = []
        elif operator == b"Do" and operands:
            object_name = str(operands[0]).lstrip("/")
            asset_id = image_assets.get(object_name.casefold())
            if asset_id is None:
                candidates = [
                    value
                    for key, value in image_assets.items()
                    if key.startswith(object_name.casefold())
                ]
                asset_id = candidates[0] if candidates else None
            corners = (
                _transform_point(matrix, 0.0, 0.0),
                _transform_point(matrix, 1.0, 0.0),
                _transform_point(matrix, 0.0, 1.0),
                _transform_point(matrix, 1.0, 1.0),
            )
            xs = [point[0] for point in corners]
            ys = [point[1] for point in corners]
            bbox = _display_bbox1000(
                crop=crop,
                rotation=rotation,
                bbox=(min(xs), min(ys), max(xs), max(ys)),
            )
            if bbox is not None and asset_id is not None:
                builder.add_block(
                    block_type=BlockType.FIGURE,
                    location=SourceLocation(
                        page_index0=page_index0,
                        native_object_id=f"pdf/page/{page_index0}/image-placement/{image_index}",
                        bbox1000=bbox,
                        image_asset_id=asset_id,
                    ),
                    markdown=f"![Embedded PDF image]({asset_id})",
                    quality_flags=("embedded_image_native",),
                )
                image_index += 1


def parse_pdf_to_cir(
    *,
    filename: str,
    declared_mime: str,
    data: bytes,
    context: ParseContext,
    limits: ParserLimits | None = None,
    password: bytes | None = None,
    max_pages: int = 10_000,
) -> CanonicalDocument:
    """Parse text objects, page boxes, vector paths, and embedded images into CIR."""

    effective_limits = limits or ParserLimits()
    normalized_filename = Path(filename).name
    if Path(normalized_filename).suffix.casefold() != ".pdf":
        raise StructuredParseError("UNSUPPORTED_PDF_TYPE")
    if declared_mime.split(";", 1)[0].strip().casefold() != "application/pdf":
        raise StructuredParseError("MIME_MISMATCH")
    if not data or len(data) > effective_limits.max_input_bytes:
        raise StructuredParseError("FILE_TOO_LARGE" if data else "FILE_EMPTY")
    if not data.startswith(b"%PDF-"):
        raise StructuredParseError("MAGIC_MISMATCH")
    source_sha256 = "sha256:" + hashlib.sha256(data).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
    except Exception as exc:
        raise StructuredParseError("PDF_PARSE_FAILED") from exc
    if reader.is_encrypted:
        if password is None:
            raise StructuredParseError("ENCRYPTED_PDF")
        try:
            if not reader.decrypt(password):
                raise StructuredParseError("PDF_PASSWORD_INVALID")
        except StructuredParseError:
            raise
        except Exception as exc:
            raise StructuredParseError("PDF_PASSWORD_INVALID") from exc
    if not reader.pages or len(reader.pages) > max_pages:
        raise StructuredParseError("PAGE_LIMIT")

    builder = CirBuilder(
        context=context,
        source_filename=normalized_filename,
        source_sha256=source_sha256,
        document_type="pdf",
        limits=effective_limits,
    )
    builder.metadata["declaredMime"] = "application/pdf"
    page_metadata: list[dict[str, Any]] = []
    all_text: list[_TextObject] = []
    page_inputs: list[tuple[Any, tuple[float, float, float, float], int]] = []
    for page_index0, page in enumerate(reader.pages):
        crop_payload = _box_payload(page.cropbox) or _box_payload(page.mediabox)
        if crop_payload is None:
            raise StructuredParseError("PDF_PAGE_BOX_INVALID")
        crop = (
            crop_payload[0],
            crop_payload[1],
            crop_payload[2],
            crop_payload[3],
        )
        rotation = int(page.rotation or 0) % 360
        page_inputs.append((page, crop, rotation))
        objects = _text_objects(
            page=page,
            page_index0=page_index0,
            crop=crop,
            rotation=rotation,
        )
        all_text.extend(objects)
        page_metadata.append(
            {
                "pageIndex0": page_index0,
                "rotation": rotation,
                "userUnit": _safe_float(page.get("/UserUnit", 1.0), 1.0),
                "mediaBox": _box_payload(page.mediabox),
                "cropBox": _box_payload(page.cropbox),
                "bleedBox": _box_payload(page.bleedbox),
                "trimBox": _box_payload(page.trimbox),
                "artBox": _box_payload(page.artbox),
                "widthPt": round(crop[2] - crop[0], 6),
                "heightPt": round(crop[3] - crop[1], 6),
                "nativeTextObjectCount": len(objects),
            }
        )

    font_sizes = sorted(item.font_size_pt for item in all_text if item.font_size_pt > 0)
    median_font = font_sizes[len(font_sizes) // 2] if font_sizes else 10.0
    largest_first_page = max(
        (item.font_size_pt for item in all_text if item.page_index0 == 0),
        default=median_font,
    )
    first_title_used = False
    for item in sorted(
        all_text,
        key=lambda value: (
            value.page_index0,
            value.bbox1000[1],
            value.bbox1000[0],
            value.native_object_id,
        ),
    ):
        is_title = (
            not first_title_used
            and item.page_index0 == 0
            and item.font_size_pt >= largest_first_page
            and len(item.text) <= 240
        )
        is_heading = (
            not is_title and item.font_size_pt >= median_font * 1.25 and len(item.text) <= 320
        )
        block_type = (
            BlockType.TITLE
            if is_title
            else (BlockType.HEADING if is_heading else BlockType.PARAGRAPH)
        )
        builder.add_block(
            block_type=block_type,
            location=SourceLocation(
                page_index0=item.page_index0,
                native_object_id=item.native_object_id,
                bbox1000=item.bbox1000,
            ),
            raw_text=item.text,
            normalized_text=item.text,
            markdown=(
                f"# {item.text}" if is_title else (f"## {item.text}" if is_heading else item.text)
            ),
            quality_flags=(f"native_font_size_pt:{item.font_size_pt:g}",),
        )
        first_title_used = first_title_used or is_title

    for page_index0, (page, crop, rotation) in enumerate(page_inputs):
        image_assets = _register_images(page, page_index0=page_index0, builder=builder)
        _extract_graphics(
            page,
            page_index0=page_index0,
            crop=crop,
            rotation=rotation,
            image_assets=image_assets,
            builder=builder,
        )

    builder.metadata["pdfPageGeometryVersion"] = "1.0.0"
    builder.metadata["pages"] = page_metadata
    title = next(
        (item.text for item in all_text if item.page_index0 == 0),
        normalized_filename,
    )
    return builder.build(title=title)


__all__ = ["parse_pdf_to_cir"]
