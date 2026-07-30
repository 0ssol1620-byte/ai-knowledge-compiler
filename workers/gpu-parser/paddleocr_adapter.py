"""Production PaddleOCR-VL 1.6 adapter.

The generic GPU runtime imports this module only when ``AKC_ADAPTER_MODE`` is
``production``.  Model files must already exist in the image or an immutable
read-only volume.  Automatic model downloads are deliberately impossible: a
deployment supplies a checksummed manifest whose upstream revision is bound to
``MODEL_REVISION``.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
from pathlib import Path
from typing import Any

from runtime import SafeWorkerError

_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PIPELINE_VERSION = "v1.6"
_PROVIDER_KEY = "paddleocr_vl_1_6"

_LABEL_TO_BLOCK_TYPE = {
    "doc_title": "title",
    "title": "title",
    "paragraph_title": "heading",
    "section_title": "heading",
    "text": "paragraph",
    "paragraph": "paragraph",
    "list": "list",
    "table": "table",
    "image": "figure",
    "figure": "figure",
    "chart": "figure",
    "figure_title": "caption",
    "caption": "caption",
    "formula": "formula",
    "display_formula": "formula",
    "code": "code",
    "quote": "quote",
    "footnote": "footnote",
    "vision_footnote": "footnote",
    "header": "header",
    "header_image": "header",
    "footer": "footer",
    "footer_image": "footer",
    "number": "page_number",
    "page_number": "page_number",
}


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise SafeWorkerError("paddleocr_non_json_output") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest() -> tuple[dict[str, Any], Path]:
    manifest_value = os.getenv("PADDLEOCR_MODEL_MANIFEST", "").strip()
    manifest_digest = os.getenv("PADDLEOCR_MODEL_MANIFEST_SHA256", "").strip().lower()
    if not manifest_value or not _SHA256.fullmatch(manifest_digest):
        raise SafeWorkerError("paddleocr_model_manifest_required")
    try:
        manifest_path = Path(manifest_value).resolve(strict=True)
    except OSError as exc:
        raise SafeWorkerError("paddleocr_model_manifest_invalid") from exc
    if not manifest_path.is_file():
        raise SafeWorkerError("paddleocr_model_manifest_invalid")
    raw = manifest_path.read_bytes()
    if not hashlib.sha256(raw).hexdigest() == manifest_digest:
        raise SafeWorkerError("paddleocr_model_manifest_checksum_mismatch")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SafeWorkerError("paddleocr_model_manifest_invalid") from exc
    if not isinstance(value, dict):
        raise SafeWorkerError("paddleocr_model_manifest_invalid")
    return value, manifest_path.parent


def _resolve_model_directory(root: Path, value: Any, *, field: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise SafeWorkerError(f"invalid_{field}")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise SafeWorkerError(f"invalid_{field}")
    try:
        resolved = (root / relative).resolve(strict=True)
    except OSError as exc:
        raise SafeWorkerError(f"invalid_{field}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SafeWorkerError(f"invalid_{field}") from exc
    if not resolved.is_dir():
        raise SafeWorkerError(f"invalid_{field}")
    return resolved


def _verify_model_manifest(
    value: dict[str, Any],
    root: Path,
    *,
    model_revision: str,
) -> tuple[Path, Path]:
    if value.get("schema_version") != "1.0":
        raise SafeWorkerError("paddleocr_model_manifest_schema_unsupported")
    if value.get("provider_key") != _PROVIDER_KEY:
        raise SafeWorkerError("paddleocr_model_manifest_provider_mismatch")
    if value.get("pipeline_version") != _PIPELINE_VERSION:
        raise SafeWorkerError("paddleocr_pipeline_version_mismatch")
    if value.get("upstream_revision") != model_revision:
        raise SafeWorkerError("paddleocr_model_revision_mismatch")

    layout_dir = _resolve_model_directory(
        root,
        value.get("layout_detection_model_dir"),
        field="layout_detection_model_dir",
    )
    recognition_dir = _resolve_model_directory(
        root,
        value.get("vl_rec_model_dir"),
        field="vl_rec_model_dir",
    )
    files = value.get("files")
    if not isinstance(files, dict) or not files:
        raise SafeWorkerError("paddleocr_model_file_manifest_required")
    covered_layout = False
    covered_recognition = False
    for relative_name, expected_digest in sorted(files.items()):
        if (
            not isinstance(relative_name, str)
            or not relative_name
            or "\\" in relative_name
            or not isinstance(expected_digest, str)
            or not _SHA256.fullmatch(expected_digest.lower())
        ):
            raise SafeWorkerError("paddleocr_model_file_manifest_invalid")
        relative = Path(relative_name)
        if relative.is_absolute() or ".." in relative.parts:
            raise SafeWorkerError("paddleocr_model_file_manifest_invalid")
        try:
            candidate = (root / relative).resolve(strict=True)
        except OSError as exc:
            raise SafeWorkerError("paddleocr_model_file_manifest_invalid") from exc
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise SafeWorkerError("paddleocr_model_file_manifest_invalid") from exc
        if not candidate.is_file() or _sha256_file(candidate) != expected_digest.lower():
            raise SafeWorkerError("paddleocr_model_file_checksum_mismatch")
        covered_layout = covered_layout or candidate.is_relative_to(layout_dir)
        covered_recognition = covered_recognition or candidate.is_relative_to(recognition_dir)
    if not covered_layout or not covered_recognition:
        raise SafeWorkerError("paddleocr_model_manifest_incomplete")
    return layout_dir, recognition_dir


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise SafeWorkerError("paddleocr_non_json_output")
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    if hasattr(value, "item"):
        return _jsonable(value.item())
    raise SafeWorkerError("paddleocr_non_json_output")


def _result_json(result: Any) -> dict[str, Any]:
    value = getattr(result, "json", None)
    if callable(value):
        value = value()
    value = _jsonable(value)
    if not isinstance(value, dict):
        raise SafeWorkerError("paddleocr_invalid_result")
    wrapped = value.get("res")
    if isinstance(wrapped, dict):
        value = wrapped
    # Raw media is not part of the durable provider record.  It is already
    # represented by immutable source/page assets and can exceed output limits.
    for key in ("input_img", "outputImages", "inputImage", "doc_preprocessor_res"):
        value.pop(key, None)
    return value


def _dimensions(input_path: Path, options: dict[str, Any]) -> tuple[int, int]:
    width = options.get("page_width_px")
    height = options.get("page_height_px")
    if isinstance(width, int) and width > 0 and isinstance(height, int) and height > 0:
        return width, height
    try:
        from PIL import Image

        with Image.open(input_path) as image:
            return image.size
    except Exception as exc:
        raise SafeWorkerError("paddleocr_page_dimensions_required") from exc


def _boolean_option(
    options: dict[str, Any],
    key: str,
    *,
    default: bool = False,
) -> bool:
    value = options.get(key, default)
    if not isinstance(value, bool):
        raise SafeWorkerError(f"paddleocr_{key}_invalid")
    return value


def _bbox1000(value: Any, *, width: int, height: int) -> list[int]:
    converted = _jsonable(value)
    if (
        not isinstance(converted, list)
        or len(converted) != 4
        or any(not isinstance(item, (int, float)) or isinstance(item, bool) for item in converted)
    ):
        raise SafeWorkerError("paddleocr_invalid_bbox")
    x1, y1, x2, y2 = (float(item) for item in converted)
    if x1 < 0 or y1 < 0 or x1 >= x2 or y1 >= y2 or x2 > width * 1.02 or y2 > height * 1.02:
        raise SafeWorkerError("paddleocr_invalid_bbox")
    normalized = [
        max(0, min(1000, round(x1 / width * 1000))),
        max(0, min(1000, round(y1 / height * 1000))),
        max(0, min(1000, round(x2 / width * 1000))),
        max(0, min(1000, round(y2 / height * 1000))),
    ]
    if normalized[0] >= normalized[2]:
        normalized[2] = min(1000, normalized[0] + 1)
    if normalized[1] >= normalized[3]:
        normalized[3] = min(1000, normalized[1] + 1)
    if normalized[0] >= normalized[2] or normalized[1] >= normalized[3]:
        raise SafeWorkerError("paddleocr_invalid_bbox")
    return normalized


def _source_ref(request: dict[str, Any], bbox: list[int]) -> dict[str, Any]:
    page_index = request.get("page_index0", request.get("page_index", 0))
    if not isinstance(page_index, int) or isinstance(page_index, bool) or page_index < 0:
        raise SafeWorkerError("invalid_page_index0")
    document_id = request.get("document_id")
    version_id = request.get("document_version_id")
    if not isinstance(document_id, str) or not document_id:
        raise SafeWorkerError("invalid_document_id")
    if not isinstance(version_id, str) or not version_id:
        raise SafeWorkerError("invalid_document_version_id")
    return {
        "document_id": document_id,
        "document_version_id": version_id,
        "page_index0": page_index,
        "page_number1": page_index + 1,
        "bbox1000": bbox,
    }


def _confidence(value: Any, *, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not 0.0 <= float(value) <= 1.0
    ):
        raise SafeWorkerError(f"paddleocr_invalid_{field}")
    return float(value)


def _confidence_evidence(item: dict[str, Any]) -> tuple[float, list[float]]:
    block_value = next(
        (
            item[key]
            for key in ("confidence", "block_confidence", "block_score", "score")
            if key in item
        ),
        None,
    )
    token_value = next(
        (item[key] for key in ("token_confidences", "token_scores", "rec_scores") if key in item),
        None,
    )
    if not isinstance(token_value, list) or not token_value:
        raise SafeWorkerError("paddleocr_token_confidence_required")
    return (
        _confidence(block_value, field="block_confidence"),
        [_confidence(value, field="token_confidence") for value in token_value],
    )


def _canonical_table(
    item: dict[str, Any],
    *,
    request: dict[str, Any],
    block_id: str,
    block_bbox: list[int],
) -> dict[str, Any]:
    supplied = item.get("canonical_table")
    if isinstance(supplied, dict):
        return supplied
    raw_cells = item.get("table_cells")
    if not isinstance(raw_cells, list) or not raw_cells:
        raise SafeWorkerError("paddleocr_canonical_table_required")
    width = request["options"]["page_width_px"]
    height = request["options"]["page_height_px"]
    cells: list[dict[str, Any]] = []
    row_count = 0
    column_count = 0
    for index, cell in enumerate(raw_cells):
        if not isinstance(cell, dict):
            raise SafeWorkerError("paddleocr_invalid_table_cell")
        row = cell.get("row_index0")
        column = cell.get("column_index0")
        row_span = cell.get("row_span", 1)
        column_span = cell.get("column_span", 1)
        text = cell.get("text")
        if (
            not isinstance(row, int)
            or isinstance(row, bool)
            or row < 0
            or not isinstance(column, int)
            or isinstance(column, bool)
            or column < 0
            or not isinstance(row_span, int)
            or isinstance(row_span, bool)
            or row_span < 1
            or not isinstance(column_span, int)
            or isinstance(column_span, bool)
            or column_span < 1
            or not isinstance(text, str)
        ):
            raise SafeWorkerError("paddleocr_invalid_table_cell")
        cell_confidence, _token_confidences = _confidence_evidence(cell)
        cell_bbox = _bbox1000(cell.get("bbox"), width=width, height=height)
        row_count = max(row_count, row + row_span)
        column_count = max(column_count, column + column_span)
        cells.append(
            {
                "id": f"{block_id}_cell_{index}",
                "rowIndex0": row,
                "columnIndex0": column,
                "rowSpan": row_span,
                "columnSpan": column_span,
                "rawText": text,
                "normalizedText": text,
                "origin": "ocr_extracted",
                "sourceRefs": [_source_ref(request, cell_bbox)],
                "confidence": cell_confidence,
                "qualityFlags": [],
            }
        )
    return {
        "id": f"{block_id}_table",
        "rowCount": row_count,
        "columnCount": column_count,
        "headerRowCount": int(item.get("header_row_count", 0)),
        "cells": cells,
        "sourceRefs": [_source_ref(request, block_bbox)],
        "qualityFlags": [],
    }


class PaddleOcrVlAdapter:
    def __init__(self, *, model_revision: str) -> None:
        if not _REVISION.fullmatch(model_revision):
            raise SafeWorkerError("exact_model_revision_required")
        manifest, root = _manifest()
        layout_dir, recognition_dir = _verify_model_manifest(
            manifest,
            root,
            model_revision=model_revision,
        )
        try:
            paddleocr = importlib.import_module("paddleocr")
            pipeline_type = paddleocr.PaddleOCRVL
        except (ImportError, AttributeError) as exc:
            raise SafeWorkerError("paddleocr_runtime_not_installed") from exc
        engine = os.getenv("PADDLEOCR_ENGINE", "paddle").strip()
        if engine not in {"paddle", "paddle_static", "paddle_dynamic", "transformers"}:
            raise SafeWorkerError("paddleocr_engine_invalid")
        device = os.getenv("PADDLEOCR_DEVICE", "gpu:0").strip()
        if not re.fullmatch(r"(?:gpu|cpu)(?::[0-9]+)?", device):
            raise SafeWorkerError("paddleocr_device_invalid")
        self._model_revision = model_revision
        self._pipeline = pipeline_type(
            pipeline_version=_PIPELINE_VERSION,
            layout_detection_model_dir=str(layout_dir),
            vl_rec_model_dir=str(recognition_dir),
            use_layout_detection=True,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_queues=True,
            engine=engine,
            device=device,
        )

    def self_test(self) -> None:
        if not callable(getattr(self._pipeline, "predict", None)):
            raise SafeWorkerError("paddleocr_runtime_self_test_failed")

    def process(self, input_path: Path, request: dict[str, Any]) -> dict[str, Any]:
        options = request.get("options")
        if not isinstance(options, dict):
            raise SafeWorkerError("invalid_adapter_options")
        width, height = _dimensions(input_path, options)
        max_new_tokens = options.get("max_output_tokens", 4096)
        if (
            not isinstance(max_new_tokens, int)
            or isinstance(max_new_tokens, bool)
            or not 128 <= max_new_tokens <= 16_384
        ):
            raise SafeWorkerError("paddleocr_max_new_tokens_invalid")
        prediction = self._pipeline.predict(
            input=str(input_path),
            use_doc_orientation_classify=_boolean_option(
                options,
                "orientation_classify",
            ),
            use_doc_unwarping=_boolean_option(options, "unwarp"),
            use_layout_detection=True,
            use_chart_recognition=_boolean_option(options, "chart_recognition"),
            use_seal_recognition=_boolean_option(options, "seal_recognition"),
            use_ocr_for_image_block=_boolean_option(options, "ocr_image_blocks"),
            format_block_content=True,
            temperature=0.0,
            max_new_tokens=max_new_tokens,
        )
        raw_pages = [_result_json(result) for result in prediction]
        if len(raw_pages) != 1:
            raise SafeWorkerError("paddleocr_single_page_result_required")
        raw = raw_pages[0]
        parsed = raw.get("parsing_res_list")
        if not isinstance(parsed, list) or not parsed:
            raise SafeWorkerError("paddleocr_empty_result")
        blocks: list[dict[str, Any]] = []
        for index, item in enumerate(parsed):
            if not isinstance(item, dict):
                raise SafeWorkerError("paddleocr_invalid_block")
            text = item.get("block_content")
            label = item.get("block_label")
            if not isinstance(text, str) or len(text) > 1_000_000:
                raise SafeWorkerError("paddleocr_invalid_block_content")
            if not isinstance(label, str) or not label:
                raise SafeWorkerError("paddleocr_invalid_block_label")
            bbox = _bbox1000(item.get("block_bbox"), width=width, height=height)
            confidence, token_confidences = _confidence_evidence(item)
            identity = _canonical_json(
                {
                    "bbox1000": bbox,
                    "index": index,
                    "label": label,
                    "revision": self._model_revision,
                    "text": text,
                }
            )
            block_id = "blk_" + hashlib.sha256(identity).hexdigest()[:32]
            block_type = _LABEL_TO_BLOCK_TYPE.get(label.casefold(), "unknown")
            block: dict[str, Any] = {
                "block_id": block_id,
                "type": block_type,
                "text": text,
                "origin": "ocr_extracted",
                "source_refs": [_source_ref(request, bbox)],
                "confidence": confidence,
                "token_confidences": token_confidences,
                "quality_flags": (
                    [] if label.casefold() in _LABEL_TO_BLOCK_TYPE else ["unknown_layout_label"]
                ),
            }
            if block_type == "table":
                block["table"] = _canonical_table(
                    item,
                    request=request,
                    block_id=block_id,
                    block_bbox=bbox,
                )
            elif block_type == "formula":
                formula = item.get("formula_latex", text)
                if not isinstance(formula, str) or not formula.strip():
                    raise SafeWorkerError("paddleocr_formula_latex_required")
                block["formulaLatex"] = formula
            elif block_type == "figure":
                block["cropProvenance"] = "source_bbox"
            blocks.append(block)
        raw_hash = hashlib.sha256(_canonical_json(raw_pages)).hexdigest()
        return {
            "blocks": blocks,
            "generated_claims": [],
            "warnings": [],
            "provider_metrics": {
                "pipeline_version": _PIPELINE_VERSION,
                "block_count": len(blocks),
                "raw_output_sha256": f"sha256:{raw_hash}",
                "orientation_classify": _boolean_option(
                    options,
                    "orientation_classify",
                ),
                "unwarp": _boolean_option(options, "unwarp"),
            },
            # Raw provider pages can contain OCR text, secrets, and media.
            # Only their digest crosses the durable boundary.
            "provider_raw": {},
        }


def create_adapter(*, model_revision: str) -> PaddleOcrVlAdapter:
    return PaddleOcrVlAdapter(model_revision=model_revision)
