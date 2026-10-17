"""D-T-live output -> evaluator input files (COMPETITOR-PROTOCOL §4.2-4.4, §7 AT-6).

What the product exposes is all this adapter reads: for every PDF family the live capability
manifest lists ``preserved: ["page", "paragraph_text", "bbox1000"]``. On the wire that is
Foundation's ``CollectionOcrRegion`` (nextjs/lib/collection-compiler.ts:106-117): ``pageNumber1``,
``order``, ``text`` and ``bbox1000`` (integers 0-1000, x1<x2, y1<y2), checked here by the same
rules the product's own validator applies (collection-compiler.ts:520-541). Text is passed
verbatim: not escaped, not marked up, not reflowed. Reading order is (page, order).

The layouts are the ones the frozen FOLYNTA campaign handed to the pinned evaluators, so every
arm meets the evaluator the same way (``benchmark/runpod_eval/public_core_merge.py``
``_official_destination`` / ``build_parsebench_result``, ``build_recovery_counterfactual_
candidate.py`` ``candidate_relative_path`` / ``empty_parsebench_result``):

- olmOCR-bench ``cfa88c1e``: ``<category>/<stem>_pg<page>_repeat<r>.md``, one file for every page
  the corpus manifest gives the source, a page with no region being an empty file.
- OmniDocBench ``193627ae``: ``markdown-repeat-<r>/<stem>.md``. A source is one page image.
- ParseBench ``1d460294``: ``<category>/<stem>.result.json``, the campaign's envelope; the
  ``layout`` category is a ``layout_detection`` result, every other category a ``parse`` result.
  Boxes become pixel boxes of the page image the caller names; the adapter never measures or
  guesses an image size. Every box is labelled ``Text`` (the product's only block type is
  ``paragraph``) and scored 1.0, meaning unranked: the region ``confidence`` is a recognition
  confidence, not a detection score, so it is not passed off as one.

Denominator rule (§4.4): ``live_regions`` turns every non-OK ``ParseResult`` (product-limit
refusal, CDR refusal, OCR timeout, empty output) into no regions, and each converter turns no
regions into the empty prediction the campaign used, so the evaluator scores it over the full N.

What this adapter cannot express. The live reader emits paragraph regions only; the manifest
says ``no_table_or_formula_extraction`` and ``no_native_structure_reader_yet``. So the evaluator
input carries no table (no pipe or HTML table), no formula (no LaTeX), no heading, list, bold or
other formatting, and no block label other than ``Text``: a page header, a table cell and a
caption are all plain paragraphs. Predicted before any run, for the preregistration (a
prediction, not a measurement; the lane receipt carries the full list):

- BEHIND, table-heavy: ParseBench Tables; OmniDocBench table TEDS; olmOCR ``table_tests``.
- BEHIND, formula-heavy: olmOCR ``arxiv_math`` and ``old_scans_math``.
- BEHIND, other absent structure: ParseBench Semantic Formatting (no markup), Visual Grounding
  (one label class), Charts (no table form for data points); olmOCR ``headers_footers`` (page
  furniture is not labelled, so it is not left out).
- No prediction: text-only measures (olmOCR baseline, long_tiny_text, multi_column, old_scans;
  OmniDocBench text and reading-order Edit; ParseBench Content Faithfulness).

The table path is deliberately unimplemented. A ``tavonel.table_read.v1`` document anywhere in
the payload (the P2-19 contract, Foundation ``shared/tableReadContract.ts``), or a region whose
``blockType`` is not ``paragraph``, raises ``StructureNotImplemented`` with a reason code. The
adapter never flattens a table into paragraphs and never makes up a cell, a grid or a formula.

No socket is opened here: the adapter reads bytes the harness already holds and returns text.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .base import ParseResult, Status

ADAPTER_ID = "tavonel_live_evaluator_inputs.v1"
# Unregistered in ParseBench on purpose, like the frozen MinerU lane: a registered provider name
# without its own layout adapter is routed to a generic fallback that drops the layout blocks.
PIPELINE_NAME = "tavonel-live-d-t-live-v1"
TABLE_READ_SCHEMA = "tavonel.table_read.v1"
TABLE_READ_NOT_CONVERTED = "TABLE_READ_NOT_CONVERTED"
BLOCK_TYPE_NOT_CONVERTED = "BLOCK_TYPE_NOT_CONVERTED"

Bbox1000 = tuple[int, int, int, int]


class MalformedLiveOutput(ValueError):
    """The payload is not the product's region list; nothing is scored from it."""


class EvidenceMismatch(ValueError):
    """The body handed over is not the body the ParseResult recorded."""


class StructureNotImplemented(NotImplementedError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code


@dataclass(frozen=True)
class Region:
    page: int
    order: int
    text: str
    bbox1000: Bbox1000


def adapter_digest() -> str:
    """The pin ``adapter_digest`` (VENDOR-COMPARISON-PREREG D-T-live ``pins_required``)."""
    return "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def live_regions(result: ParseResult, raw_body: bytes | None) -> list[Region]:
    """The regions to score for one D-T-live result: none for every non-OK result (§4.4)."""
    if result.status is not Status.OK:
        return []
    if raw_body is None or hashlib.sha256(raw_body).hexdigest() != result.raw_sha256:
        raise EvidenceMismatch(f"{result.doc_id}: body sha256 differs from the recorded raw_sha256")
    return read_regions(json.loads(raw_body))


def _is_int(value: object) -> bool:
    return type(value) is int


def _refuse_table_reads(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("schemaVersion") == TABLE_READ_SCHEMA:
            counts = {
                k: len(v)
                for k in ("tables", "formulas", "refusals")
                if isinstance(v := node.get(k), list)
            }
            raise StructureNotImplemented(
                TABLE_READ_NOT_CONVERTED,
                f"page {node.get('pageNumber1')} carries {TABLE_READ_SCHEMA} {counts}; "
                "table and formula conversion is not implemented",
            )
        for value in node.values():
            _refuse_table_reads(value)
    elif isinstance(node, list):
        for value in node:
            _refuse_table_reads(value)


def read_regions(payload: Any) -> list[Region]:
    """Validate the product's regions and return them in reading order. Fails closed."""
    _refuse_table_reads(payload)
    regions = payload.get("regions") if isinstance(payload, dict) else None
    if not isinstance(regions, list) or not regions:
        raise MalformedLiveOutput("regions: a non-empty list is required")
    out: list[Region] = []
    seen: set[tuple[int, int]] = set()
    for index, region in enumerate(regions):
        if not isinstance(region, dict):
            raise MalformedLiveOutput(f"region {index}: not an object")
        block = region.get("blockType")
        if not isinstance(block, str):
            raise MalformedLiveOutput(f"region {index}: blockType must be a string")
        if block != "paragraph":
            raise StructureNotImplemented(
                BLOCK_TYPE_NOT_CONVERTED, f"region {index}: blockType {block!r}"
            )
        page: Any = region.get("pageNumber1")
        order: Any = region.get("order")
        text: Any = region.get("text")
        bbox: Any = region.get("bbox1000")
        if not (_is_int(page) and page >= 1 and _is_int(order) and order >= 0):
            raise MalformedLiveOutput(f"region {index}: pageNumber1 >= 1 and order >= 0 required")
        if "pageIndex0" in region and region["pageIndex0"] != page - 1:
            raise MalformedLiveOutput(f"region {index}: pageIndex0 is not pageNumber1 - 1")
        if not isinstance(text, str) or not text.strip():
            raise MalformedLiveOutput(f"region {index}: text must be non-blank")
        if not (
            isinstance(bbox, list)
            and len(bbox) == 4
            and all(_is_int(v) and 0 <= v <= 1000 for v in bbox)
            and bbox[0] < bbox[2]
            and bbox[1] < bbox[3]
        ):
            raise MalformedLiveOutput(f"region {index}: bbox1000 needs 4 ints 0-1000, x1<x2, y1<y2")
        if (page, order) in seen:
            raise MalformedLiveOutput(f"region {index}: page {page} order {order} repeats")
        seen.add((page, order))
        out.append(Region(page, order, text, (bbox[0], bbox[1], bbox[2], bbox[3])))
    return sorted(out, key=lambda r: (r.page, r.order))


def _source(source_relative_path: str) -> tuple[str, str]:
    path = PurePosixPath(source_relative_path)
    if len(path.parts) < 2:
        raise ValueError(f"cannot derive category from source path: {source_relative_path}")
    return path.parts[-2], path.stem


def _page_markdown(regions: Sequence[Region], pages: int) -> dict[int, str]:
    if pages < 1:
        raise ValueError("pages comes from the corpus manifest and is at least 1")
    beyond = sorted({r.page for r in regions if r.page > pages})
    if beyond:
        raise MalformedLiveOutput(f"regions on pages {beyond} beyond the source's {pages}")
    ordered = sorted(regions, key=lambda r: (r.page, r.order))
    return {p: "\n\n".join(r.text for r in ordered if r.page == p) for p in range(1, pages + 1)}


def _repeat(repeat: int) -> int:
    if repeat < 1:
        raise ValueError("repeat is 1-based")
    return repeat


def olmocr_candidate(
    source_relative_path: str, regions: Sequence[Region], *, pages: int, repeat: int = 1
) -> dict[str, str]:
    """``bench_data/pdfs/<category>/<stem>.pdf`` -> one Markdown file per manifest page."""
    category, stem = _source(source_relative_path)
    repeat = _repeat(repeat)
    return {
        f"{category}/{stem}_pg{page}_repeat{repeat}.md": markdown
        for page, markdown in _page_markdown(regions, pages).items()
    }


def omnidocbench_prediction(
    source_relative_path: str, regions: Sequence[Region], *, repeat: int = 1
) -> dict[str, str]:
    """One page image -> ``markdown-repeat-<r>/<stem>.md``."""
    stem = PurePosixPath(source_relative_path).stem
    return {f"markdown-repeat-{_repeat(repeat)}/{stem}.md": _page_markdown(regions, 1)[1]}


def parsebench_result(
    source_relative_path: str,
    regions: Sequence[Region],
    *,
    image_size_px: tuple[int, int],
    recorded_at: str,
    latency_ms: int,
) -> dict[str, str]:
    """One single-page source -> ``<category>/<stem>.result.json`` (canonical JSON)."""
    category, stem = _source(source_relative_path)
    width, height = image_size_px
    if not (_is_int(width) and _is_int(height) and width >= 1 and height >= 1):
        raise ValueError("image_size_px is the evaluator page image's (width, height) in pixels")
    if not (_is_int(latency_ms) and latency_ms >= 0):
        raise ValueError("latency_ms is a non-negative int")
    markdown = _page_markdown(regions, 1)[1]
    ordered = sorted(regions, key=lambda r: r.order)
    example_id = f"{category}/{stem}"
    product_type = "layout_detection" if category == "layout" else "parse"
    # bbox1000 -> pixels of the evaluator's page image: [x1, y1, x2, y2].
    boxes = [
        [r.bbox1000[i] * (width if i % 2 == 0 else height) / 1000 for i in range(4)]
        for r in ordered
    ]
    texts = [r.text for r in ordered]
    if product_type == "layout_detection":
        output: dict[str, Any] = {
            "task_type": product_type,
            "example_id": example_id,
            "pipeline_name": PIPELINE_NAME,
            # The label vocabulary the frozen MinerU lane's labels belong to; not a vendor.
            "model": "unstructured_layout",
            "image_width": width,
            "image_height": height,
            "predictions": [
                {
                    "bbox": box,
                    "score": 1.0,
                    "label": "Text",
                    "page": 1,
                    "content": {"type": "text", "text": text},
                    "provider_metadata": {"order_index": i, "source_type": "paragraph"},
                }
                for i, (box, text) in enumerate(zip(boxes, texts, strict=True))
            ],
            "markdown": markdown,
        }
    else:
        segments = [
            {
                "x": x1,
                "y": y1,
                "w": x2 - x1,
                "h": y2 - y1,
                "confidence": 1.0,
                "label": "Text",
            }
            for x1, y1, x2, y2 in boxes
        ]
        items = [
            {"type": "text", "md": t, "value": t, "bbox": s, "layout_segments": [s]}
            for s, t in zip(segments, texts, strict=True)
        ]
        output = {
            "task_type": product_type,
            "example_id": example_id,
            "pipeline_name": PIPELINE_NAME,
            "pages": [{"page_index": 0, "markdown": markdown}] if regions else [],
            "layout_pages": [
                {
                    "page_number": 1,
                    "width": float(width),
                    "height": float(height),
                    "md": markdown,
                    "text": "",
                    "items": items,
                }
            ]
            if regions
            else [],
            "markdown": markdown,
            "job_id": None,
        }
    envelope = {
        "request": {
            "example_id": example_id,
            "source_file_path": source_relative_path,
            "product_type": product_type,
            "schema_override": None,
            "config_override": None,
        },
        "pipeline_name": PIPELINE_NAME,
        "product_type": product_type,
        "raw_output": {
            "adapter": ADAPTER_ID,
            "regions": [
                {"page": r.page, "order": r.order, "text": r.text, "bbox1000": list(r.bbox1000)}
                for r in ordered
            ],
            "image_width": width,
            "image_height": height,
        }
        if regions
        else None,
        "output": output,
        "started_at": recorded_at,
        "completed_at": recorded_at,
        "latency_in_ms": latency_ms,
    }
    text = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {f"{category}/{stem}.result.json": text + "\n"}
