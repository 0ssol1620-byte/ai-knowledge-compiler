"""Table track at product DPI (programme D3-AX).

The Arena's table scores came from staged PNGs at source resolution. The
product never shows a reader that image. Foundation's CDR
(``quarantine-sidecar/cdr-cloudrun/app.py`` at fnd-main 5919ecd4) renders every
PDF page with pypdfium2 at ``RENDER_SCALE = 1.5`` -- 108 DPI, lowered further
when a page or document would exceed 30 MP / 80 MP and refused below scale 1.0
-- and rebuilds an image-only PDF; the OCR worker
(``workers/foundation-ocr-gpu/app.py``) then renders *that* PDF at
``RENDER_SCALE = 2.0``. :func:`product_raster` performs the same two passes
with the same library calls, so a reader is measured on the pixels it would
get in production. 150 and 200 DPI are the same path with a larger first
scale, for the D1/D3 decision on raising the CDR resolution.

Scoring reuses OmniDocBench's own TEDS (``src/metrics/table_metric.py`` at the
Arena's pinned evaluator commit 193627ae, Apache-2.0, run in that clone's
venv) and adds a numeric-cell exact match. The current product reader is
RapidOCR line OCR, which emits no table structure: its arm scores 0 by
construction, and is reported as that, not left out.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pypdfium2 as pdfium  # type: ignore[import-untyped]
from arena.provider.safety import sha256_bytes, utc_now_iso, write_jsonl_append
from PIL import Image

from karena import CAMPAIGN_ID

__all__ = [
    "PRODUCT_CDR_SCALE",
    "Raster",
    "TableTrackError",
    "numeric_cell_match",
    "product_raster",
    "score_tables",
    "teds_scores",
]

PRODUCT_CDR_SCALE: Final = 1.5  # 108 DPI
PRODUCT_OCR_SCALE: Final = 2.0
MIN_CDR_SCALE: Final = 1.0
MAX_PIXELS_PER_PAGE: Final = 30_000_000
MAX_PIXELS_TOTAL: Final = 80_000_000
PRODUCT_PYPDFIUM2: Final = "5.13.0"
OMNIDOC_COMMIT: Final = "193627ae9e97d89188468ed1ee3b7a856ff76044"
NUMBER: Final = re.compile(r"\(?-?\$?\d[\d,]*\.?\d*\)?")


class TableTrackError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Raster:
    image: Image.Image
    cdr_scale: float
    cdr_dpi: float
    cdr_pixels: tuple[int, int]
    ocr_pixels: tuple[int, int]
    pypdfium2_version: str
    product_parity: bool


def cdr_scale(page_sizes: Sequence[tuple[float, float]], requested: float) -> float:
    """The CDR's own scale rule: the requested scale unless a pixel budget forces it lower."""

    areas = [width * height for width, height in page_sizes]
    scale = min(
        requested,
        math.sqrt(MAX_PIXELS_PER_PAGE / max(areas)),
        math.sqrt(MAX_PIXELS_TOTAL / sum(areas)),
    )
    if scale < MIN_CDR_SCALE:
        raise TableTrackError("the product CDR refuses this document (render budget)")
    return scale


def product_raster(pdf: bytes, page_index: int, *, dpi: float = 108.0) -> Raster:
    source = pdfium.PdfDocument(pdf)
    try:
        sizes = [source[i].get_size() for i in range(len(source))]
        scale = cdr_scale(sizes, dpi / 72.0)
        page = source[page_index]
        width, height = page.get_size()
        bitmap = page.render(scale=scale, fill_color=(255, 255, 255, 255))
        cdr_pixels = (bitmap.width, bitmap.height)
        rebuilt = pdfium.PdfDocument.new()
        try:
            out_page = rebuilt.new_page(width, height)
            image_object = pdfium.PdfImage.new(rebuilt)
            image_object.set_bitmap(bitmap)
            image_object.set_matrix(pdfium.PdfMatrix().scale(width, height))
            out_page.insert_obj(image_object)
            out_page.gen_content()
            second = out_page.render(scale=PRODUCT_OCR_SCALE)
            image = second.to_pil()
        finally:
            rebuilt.close()
    finally:
        source.close()
    return Raster(
        image=image,
        cdr_scale=scale,
        cdr_dpi=72.0 * scale,
        cdr_pixels=cdr_pixels,
        ocr_pixels=image.size,
        pypdfium2_version=pdfium.V_PYPDFIUM2,
        product_parity=pdfium.V_PYPDFIUM2 == PRODUCT_PYPDFIUM2,
    )


def _omnidoc_root() -> Path:
    configured = os.environ.get("KARENA_OMNIDOC_ROOT")
    if not configured:
        raise TableTrackError(
            "KARENA_OMNIDOC_ROOT must point at an OmniDocBench clone at "
            f"{OMNIDOC_COMMIT} (with its venv); there is no default"
        )
    root = Path(configured)
    head = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(root), "rev-parse", "HEAD"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if head != OMNIDOC_COMMIT:
        raise TableTrackError(
            f"OmniDocBench evaluator at {root} is {head or 'missing'}; "
            f"the Arena pins {OMNIDOC_COMMIT}"
        )
    return root


_TEDS_PROGRAM: Final = """
import json, sys
sys.path.insert(0, sys.argv[1] + "/src")
from metrics.table_metric import TEDS
pairs = json.load(open(sys.argv[2], encoding="utf-8"))
full, structure = TEDS(structure_only=False), TEDS(structure_only=True)
print(json.dumps([[full.evaluate(p, g), structure.evaluate(p, g)] for g, p in pairs]))
"""


def teds_scores(pairs: Sequence[tuple[str, str]], scratch: Path) -> list[tuple[float, float]]:
    """(gold_html, predicted_html) -> (TEDS, TEDS-structure), official implementation."""

    root = _omnidoc_root()
    python = root / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        python = root / ".venv" / "bin" / "python"
    scratch.mkdir(parents=True, exist_ok=True)
    pairs_path = scratch / "teds_pairs.json"
    pairs_path.write_text(json.dumps([list(p) for p in pairs]), encoding="utf-8")
    completed = subprocess.run(  # noqa: S603 - fixed program, paths we wrote
        [str(python), "-I", "-c", _TEDS_PROGRAM, str(root), str(pairs_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=3600,
    )
    if completed.returncode != 0:
        raise TableTrackError(f"official TEDS failed: {completed.stderr[-2000:]}")
    return [(float(a), float(b)) for a, b in json.loads(completed.stdout.strip().splitlines()[-1])]


def _cells(html: str) -> list[str]:
    return [
        re.sub(r"<[^>]+>", "", cell).strip()
        for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", html, flags=re.S | re.I)
    ]


def _number(cell: str) -> str | None:
    match = NUMBER.fullmatch(cell.replace(" ", ""))
    if match is None:
        return None
    text = cell.replace(" ", "").replace(",", "").replace("$", "")
    negative = (text.startswith("(") and text.endswith(")")) or text.startswith("-")
    digits = text.strip("()-")
    return ("-" if negative else "") + digits


def numeric_cell_match(gold_html: str, predicted_html: str | None) -> dict[str, int]:
    """Multiset exact match of numeric cell values (v5 section 18.3 Critical Numeric Fidelity)."""

    gold = Counter(n for n in map(_number, _cells(gold_html)) if n is not None)
    predicted = Counter(n for n in map(_number, _cells(predicted_html or "")) if n is not None)
    matched = sum((gold & predicted).values())
    return {"gold": sum(gold.values()), "predicted": sum(predicted.values()), "matched": matched}


def score_tables(
    cases: Sequence[Mapping[str, Any]],
    reader: Callable[[Image.Image], str | None],
    *,
    arm: str,
    dpi: float,
    out_dir: Path,
    load_pdf: Callable[[Mapping[str, Any]], bytes],
) -> dict[str, Any]:
    """Raster at product DPI -> reader -> official TEDS + numeric cells, one receipt per case."""

    predictions: list[str | None] = []
    receipts: list[dict[str, Any]] = []
    for case in cases:
        raster = product_raster(load_pdf(case), int(case["page_index"]), dpi=dpi)
        predicted = reader(raster.image)
        predictions.append(predicted)
        receipts.append(
            {
                "schema": "tavonel.karena.table_receipt.v1",
                "campaign_id": CAMPAIGN_ID,
                "case_id": case["case_id"],
                "arm": arm,
                "cdr_dpi": round(raster.cdr_dpi, 3),
                "cdr_pixels": list(raster.cdr_pixels),
                "ocr_pixels": list(raster.ocr_pixels),
                "pypdfium2": raster.pypdfium2_version,
                "product_parity": raster.product_parity,
                "image_sha256": sha256_bytes(raster.image.tobytes()),
                "predicted_html_sha256": None
                if predicted is None
                else sha256_bytes(predicted.encode("utf-8")),
                "licence": case["licence"],
            }
        )
    scorable = [(c["gold_html"], p) for c, p in zip(cases, predictions, strict=True) if p]
    teds = iter(teds_scores(scorable, out_dir / "scratch")) if scorable else iter(())
    totals = {"gold": 0, "predicted": 0, "matched": 0}
    teds_values: list[float] = []
    for case, predicted, receipt in zip(cases, predictions, receipts, strict=True):
        if predicted:
            full, structure = next(teds)
            receipt["teds"], receipt["teds_structure"] = full, structure
        else:
            # No table emitted: TEDS against a non-empty gold table is 0 by definition.
            receipt["teds"], receipt["teds_structure"] = 0.0, 0.0
            receipt["teds_note"] = "reader emitted no table structure"
        teds_values.append(float(receipt["teds"]))
        cells = numeric_cell_match(str(case["gold_html"]), predicted)
        receipt["numeric_cells"] = cells
        for name in totals:
            totals[name] += cells[name]
        receipt["scored_at"] = utc_now_iso()
        write_jsonl_append(
            out_dir / f"table_receipts.{arm}.jsonl", receipt, context="table receipt"
        )
    return {
        "arm": arm,
        "dpi": dpi,
        "n": len(cases),
        "teds_mean": sum(teds_values) / len(teds_values) if teds_values else None,
        "numeric_cell_recall": {"count": totals["matched"], "of": totals["gold"]},
        "numeric_cell_precision": {"count": totals["matched"], "of": totals["predicted"]},
        "product_parity": all(r["product_parity"] for r in receipts),
    }


SELF_TEST_GOLD: Final = (
    "<html><body><table><tr><td>Item</td><td>2025</td><td>2024</td></tr>"
    "<tr><td>Revenue</td><td>1,234</td><td>(56)</td></tr></table></body></html>"
)
SELF_TEST_PERTURBED: Final = SELF_TEST_GOLD.replace("1,234", "1,243")


def table_smoke(limit: int = 5) -> dict[str, Any]:
    """Raster licensed KOGL PDFs the product way at three DPIs and self-check the scorer.

    Gold tables (cell HTML) are a person's annotation (programme F-10); until the
    D3 slice exists this proves the raster path and the official TEDS call, and
    measures no reader.
    """

    from arena.provider.safety import write_json_atomic

    from karena import NAMESPACE_ROOT
    from karena.corpus import Document, read_jsonl

    documents = [
        Document.from_dict(row)
        for row in read_jsonl(NAMESPACE_ROOT / "gold" / "documents.jsonl")
        if row["origin"] == "KOGL"
    ][:limit]
    rasters = []
    for document in documents:
        pdf = (NAMESPACE_ROOT / "inputs" / "raw" / f"{document.raw_sha256[7:]}.bin").read_bytes()
        for dpi in (108.0, 150.0, 200.0):
            raster = product_raster(pdf, 0, dpi=dpi)
            rasters.append(
                {
                    "doc_id": document.doc_id,
                    "licence": document.licence.licence_id,
                    "requested_dpi": dpi,
                    "cdr_dpi": round(raster.cdr_dpi, 3),
                    "cdr_pixels": list(raster.cdr_pixels),
                    "ocr_pixels": list(raster.ocr_pixels),
                    "image_sha256": sha256_bytes(raster.image.tobytes()),
                    "pypdfium2": raster.pypdfium2_version,
                    "product_parity": raster.product_parity,
                }
            )
    scratch = NAMESPACE_ROOT / "evidence" / "table_smoke"
    (same, _), (perturbed, perturbed_structure) = teds_scores(
        [(SELF_TEST_GOLD, SELF_TEST_GOLD), (SELF_TEST_GOLD, SELF_TEST_PERTURBED)], scratch
    )
    result = {
        "schema": "tavonel.karena.table_smoke.v1",
        "campaign_id": CAMPAIGN_ID,
        "rasters": rasters,
        "teds_self_check": {
            "identical": same,
            "one_digit_changed": perturbed,
            "one_digit_changed_structure_only": perturbed_structure,
            "no_table_emitted": 0.0,
        },
        "numeric_cells_self_check": {
            "identical": numeric_cell_match(SELF_TEST_GOLD, SELF_TEST_GOLD),
            "one_digit_changed": numeric_cell_match(SELF_TEST_GOLD, SELF_TEST_PERTURBED),
            "no_table_emitted": numeric_cell_match(SELF_TEST_GOLD, None),
        },
        "omnidoc_commit": OMNIDOC_COMMIT,
        "created_at": utc_now_iso(),
    }
    write_json_atomic(scratch / "table_smoke.json", result, context="table smoke")
    return result
