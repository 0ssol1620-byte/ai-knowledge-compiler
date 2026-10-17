"""Offline shadow harness for the table reader lane: files on disk in, one receipt out.

Table/limits plan 2026-10-17 §C5 (same-condition no-regression) and §C9 R2
(`TABLE-LANE-SHADOW-RECEIPT.json`, schema `tavonel.table_lane_shadow.v1`), task T4, ladder
step 1 of §C6.

    python research/table_lane_shadow/run_shadow.py MANIFEST.json --out RECEIPT.json

No reader runs here: no GPU, no network, no subprocess. The harness reads files that already
exist -- the authoritative `ocr.json`, the `ocr.json` written while the table lane ran beside
it, each page's `tavonel.table_read.v1` output and labelled gold -- and passes them through the
T3 functions (`qualify_table_read`, `canonical_tables`, `table_cell_claims`) unchanged.

Same input bytes give the same receipt bytes: no clock, no absolute path, sorted keys, LF.

The whole run is refused, with a reasonCode, rather than written up as a misleading receipt:
gold without labels, corpora of different rights status in one run, a page the manifest skips,
an input that is not on disk, an `ocr.json` bound to other bytes. A page the reader could not
read is not a refusal: it is counted with its reasonCode, and its gold cells stay in every
denominator.

TEDS comes from the pinned OmniDocBench evaluator, never from this file: `omnidoc_teds.py` runs
it (one process, offline) and passes its block in through `build_receipt(teds=...)`. Without an
evaluator the `teds` block is `EVALUATOR_BLOCKED` with a reason and no value, never 0.

Not in the receipt: the §C5 fact-recall verdict (R3, the benchmark receipt) and any threshold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
# This worktree's packages, ahead of any other checkout an editable install points at.
for _src in ("packages/domain-packs/src", "packages/cir-python/src", "packages/product-core/src"):
    sys.path.insert(0, str(ROOT / _src))

from akc_product_core import table_claims  # noqa: E402
from akc_product_core.table_claims import (  # noqa: E402
    OcrRegion,
    TableReadExpectation,
    TableReadRejected,
    canonical_tables,
    is_bbox1000,
    normalize_space,
    qualify_table_read,
    table_cell_claims,
)

RECEIPT_SCHEMA = "tavonel.table_lane_shadow.v1"
MANIFEST_SCHEMA = "tavonel.table_lane_shadow_manifest.v1"
GOLD_SCHEMA = "tavonel.table_lane_gold.v1"
OCR_SCHEMAS = frozenset({"tavonel.ocr_result.v2", "tavonel.ocr_result.v3"})
EVALUATOR = "OmniDocBench"

#: Rights a corpus can carry (§C5 corpus paragraph). One run never mixes two of them.
RIGHTS_STATUSES = frozenset(
    {"synthetic", "research_only_non_commercial", "rights_to_confirm", "customer_consented"}
)
#: How a gold label came to exist. A model's output is not a label, so it is not here.
LABEL_METHODS = frozenset({"synthetic_construction", "human_annotation"})
#: The §C5 conditions that must hold between the two sides. Null means not applicable/unknown.
CONDITION_KEYS = frozenset(
    {
        "renderScale",
        "gpuType",
        "readerImageDigest",
        "modelId",
        "modelRevision",
        "inputMode",
        "promptSha256",
        "outputSchemaSha256",
        "priceSnapshot",
        "evaluatorCommit",
        "existingLaneImageDigest",
        "readerRevision",
        "readerBindingSha256",
    }
)
REFUSAL_CODES = frozenset(
    {
        "SHADOW_MANIFEST_INVALID",
        "SHADOW_INPUT_MISSING",
        "SHADOW_GOLD_UNLABELLED",
        "SHADOW_GOLD_INVALID",
        "SHADOW_CORPUS_RIGHTS_MIXED",
        "SHADOW_OCR_INVALID",
        "SHADOW_OCR_BINDING_MISMATCH",
    }
)
_MANIFEST_KEYS = {"manifestSchema", "synthetic", "note", "corpora", "conditions", "documents"}
_DOCUMENT_KEYS = {
    "documentId",
    "documentVersionId",
    "corpusId",
    "sourceImmutableKey",
    "inputSha256",
    "baselineOcrJson",
    "shadowOcrJson",
    "gold",
    "pages",
}
_PAGE_KEYS = {"pageIndex0", "tableRead", "readerWallSeconds"}
_GOLD_KEYS = {
    "goldSchema",
    "synthetic",
    "note",
    "documentId",
    "inputSha256",
    "labelProvenance",
    "pages",
}
_GOLD_TABLE_KEYS = {"tableId", "bbox1000", "rowCount", "columnCount", "headerRowCount", "cells"}
_GOLD_CELL_KEYS = {"cellId", "rowIndex0", "columnIndex0", "rowSpan", "columnSpan", "text"}
_PAGE_STATUSES = ("read", "no_table", "unreadable", "failed")

Json = dict[str, Any]
#: (pages with their gold and read tables, the manifest's evaluatorCommit, synthetic) -> teds.
TedsRunner = Callable[[list[Json], object, bool], Json]


class ShadowRefused(Exception):
    """The harness will not write a receipt for these inputs."""

    def __init__(self, reason_code: str, detail: str) -> None:
        assert reason_code in REFUSAL_CODES, reason_code
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _is_int(value: object, low: int = 0) -> bool:
    return type(value) is int and value >= low


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _read(base: Path, rel: object, what: str) -> tuple[Json, bytes]:
    """A manifest-relative input: its receipt entry and its bytes."""
    if (
        not isinstance(rel, str)
        or not rel
        or ":" in rel
        or "\\" in rel
        or PurePosixPath(rel).is_absolute()
        or ".." in PurePosixPath(rel).parts
    ):
        raise ShadowRefused(
            "SHADOW_MANIFEST_INVALID", f"{what} path {rel!r} is not relative to the manifest"
        )
    path = base / rel
    if not path.is_file():
        raise ShadowRefused("SHADOW_INPUT_MISSING", f"{what} {rel} is not on disk")
    data = path.read_bytes()
    return {"path": rel, "sha256": _sha256(data), "bytes": len(data)}, data


def _json(data: bytes, code: str, what: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ShadowRefused(code, f"{what} is not UTF-8 JSON: {error}") from error


def _check_manifest(manifest: object) -> Json:
    def bad(detail: str) -> ShadowRefused:
        return ShadowRefused("SHADOW_MANIFEST_INVALID", detail)

    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise bad("manifest keys are not the table_lane_shadow_manifest.v1 set")
    if manifest["manifestSchema"] != MANIFEST_SCHEMA or type(manifest["synthetic"]) is not bool:
        raise bad("manifestSchema or synthetic is wrong")
    corpora = manifest["corpora"]
    if (
        not isinstance(corpora, list)
        or not corpora
        or not all(
            isinstance(c, dict)
            and set(c) == {"corpusId", "rightsStatus"}
            and _is_text(c["corpusId"])
            for c in corpora
        )
    ):
        raise bad("corpora must list corpusId and rightsStatus")
    if len({c["corpusId"] for c in corpora}) != len(corpora):
        raise bad("corpusId repeats")
    for corpus in corpora:
        if corpus["rightsStatus"] not in RIGHTS_STATUSES:
            raise bad(f"rightsStatus {corpus['rightsStatus']!r} is not a known rights status")
    conditions = manifest["conditions"]
    if not isinstance(conditions, dict) or set(conditions) != CONDITION_KEYS:
        raise bad("conditions must carry exactly the §C5 keys")
    if not all(
        value is None or isinstance(value, str | int | float) for value in conditions.values()
    ):
        raise bad("conditions values are JSON scalars or null")
    documents = manifest["documents"]
    if not isinstance(documents, list) or not documents:
        raise bad("documents is empty")
    corpus_ids = {c["corpusId"] for c in corpora}
    for doc in documents:
        if not isinstance(doc, dict) or set(doc) != _DOCUMENT_KEYS:
            raise bad("document keys are not the manifest set")
        if not all(
            _is_text(doc[key])
            for key in ("documentId", "documentVersionId", "sourceImmutableKey", "inputSha256")
        ):
            raise bad("document ids, key and inputSha256 are non-empty strings")
        if doc["corpusId"] not in corpus_ids:
            raise bad(f"document {doc['documentId']} names an unlisted corpus")
        pages = doc["pages"]
        if not isinstance(pages, list) or not all(
            isinstance(page, dict)
            and set(page) == _PAGE_KEYS
            and _is_int(page["pageIndex0"])
            and (page["tableRead"] is None or isinstance(page["tableRead"], str))
            and _is_wall(page["readerWallSeconds"])
            for page in pages
        ):
            raise bad(f"document {doc['documentId']} pages are malformed")
    if len({doc["documentId"] for doc in documents}) != len(documents):
        raise bad("documentId repeats")
    return manifest


def _is_wall(value: object) -> bool:
    return value is None or (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _ocr_regions(ocr: object, doc: Json) -> tuple[int, list[OcrRegion]]:
    """The fields of a persisted ocr.json this harness reads, and its binding to the source.

    ponytail: a shape check of what is read here, not a port of Foundation `qualifyOcrResult`
    (which ran when the file was persisted). Port it if this harness ever reads unqualified OCR.
    """

    def bad(detail: str) -> ShadowRefused:
        return ShadowRefused("SHADOW_OCR_INVALID", f"{doc['documentId']} ocr.json {detail}")

    if not isinstance(ocr, dict) or ocr.get("schemaVersion") not in OCR_SCHEMAS:
        raise bad("is not tavonel.ocr_result.v2 or v3")
    page_count, regions = ocr.get("pageCount"), ocr.get("regions")
    if ocr.get("status") != "ok" or type(page_count) is not int or page_count < 1:
        raise bad("has no ok status or pageCount")
    if not isinstance(regions, list):
        raise bad("has no regions")
    if (
        ocr.get("inputSha256") != doc["inputSha256"]
        or ocr.get("sourceImmutableKey", doc["sourceImmutableKey"]) != doc["sourceImmutableKey"]
    ):
        raise ShadowRefused(
            "SHADOW_OCR_BINDING_MISMATCH",
            f"{doc['documentId']} baseline ocr.json is bound to other source bytes",
        )
    out: list[OcrRegion] = []
    for region in regions:
        if not (
            isinstance(region, dict)
            and _is_text(region.get("regionId"))
            and _is_int(region.get("pageIndex0"))
            and region["pageIndex0"] < page_count
            and isinstance(region.get("text"), str)
            and is_bbox1000(region.get("bbox1000"))
        ):
            raise bad("has a region without id, page, text or bbox1000")
        out.append(
            {
                "regionId": region["regionId"],
                "pageIndex0": region["pageIndex0"],
                "text": region["text"],
                "bbox1000": list(region["bbox1000"]),
            }
        )
    return page_count, out


def _gold_pages(
    gold: object, doc: Json, page_indices: list[int], synthetic: bool
) -> dict[int, list[Json]]:
    """Labelled gold tables by page. Unlabelled gold is refused; it is never inferred."""
    name = doc["documentId"]

    def unlabelled(detail: str) -> ShadowRefused:
        return ShadowRefused("SHADOW_GOLD_UNLABELLED", f"{name} gold {detail}")

    def bad(detail: str) -> ShadowRefused:
        return ShadowRefused("SHADOW_GOLD_INVALID", f"{name} gold {detail}")

    if not isinstance(gold, dict):
        raise bad("is not an object")
    provenance = gold.get("labelProvenance")
    if not (
        isinstance(provenance, dict)
        and set(provenance) == {"method", "labelledBy"}
        and provenance["method"] in LABEL_METHODS
        and _is_text(provenance["labelledBy"])
    ):
        raise unlabelled("has no labelProvenance naming a labelling method and who labelled it")
    if set(gold) != _GOLD_KEYS or gold["goldSchema"] != GOLD_SCHEMA:
        raise bad("keys are not the table_lane_gold.v1 set")
    if gold["documentId"] != name or gold["inputSha256"] != doc["inputSha256"]:
        raise bad("labels another document or other source bytes")
    if gold["synthetic"] is not synthetic:
        raise ShadowRefused(
            "SHADOW_CORPUS_RIGHTS_MIXED", f"{name} gold synthetic label disagrees with its corpus"
        )
    pages = gold["pages"]
    if not isinstance(pages, list) or not all(isinstance(page, dict) for page in pages):
        raise bad("pages is not a list of objects")
    by_page: dict[int, list[Json]] = {}
    for page in pages:
        if "tables" not in page:
            # `tables: []` is a label ("no table here"); a missing key is no label at all.
            raise unlabelled(f"page {page.get('pageIndex0')!r} carries no tables label")
        if set(page) != {"pageIndex0", "tables"} or not _is_int(page["pageIndex0"]):
            raise bad("page keys are not pageIndex0 and tables")
        if page["pageIndex0"] in by_page or not isinstance(page["tables"], list):
            raise bad(f"page {page['pageIndex0']} repeats or its tables is not a list")
        for table in page["tables"]:
            _check_gold_table(table, bad)
        by_page[page["pageIndex0"]] = page["tables"]
    missing = sorted(set(page_indices) - set(by_page))
    if missing:
        raise unlabelled(f"has no label for pages {missing}")
    if set(by_page) != set(page_indices):
        raise bad("labels pages the manifest does not list")
    return by_page


def _check_gold_table(table: object, bad: Callable[[str], ShadowRefused]) -> None:
    if not (
        isinstance(table, dict)
        and set(table) == _GOLD_TABLE_KEYS
        and _is_text(table["tableId"])
        and is_bbox1000(table["bbox1000"])
        and _is_int(table["rowCount"], 1)
        and _is_int(table["columnCount"], 1)
        and _is_int(table["headerRowCount"])
        and isinstance(table["cells"], list)
        and all(
            isinstance(cell, dict)
            and set(cell) == _GOLD_CELL_KEYS
            and _is_text(cell["cellId"])
            and isinstance(cell["text"], str)
            and all(_is_int(cell[k]) for k in ("rowIndex0", "columnIndex0"))
            and all(_is_int(cell[k], 1) for k in ("rowSpan", "columnSpan"))
            for cell in table["cells"]
        )
    ):
        raise bad("table is not a located grid of labelled cells")
    # The CIR grid rule, as the reader's tables get it: no overlap, no span past the edge.
    error = table_claims._grid_error(table)
    if error:
        raise bad(f"table {table['tableId']}: {error}")


def _pairs(gold: list[Json], read: list[Json]) -> list[tuple[Json, Json]]:
    """Gold and reader tables that overlap only each other on the page.

    ponytail: overlap pairing with no IoU cut-off, because no cut-off is calibrated. A box that
    touches two tables pairs with neither, which counts against the numerator, never for it.
    """

    def touch(a: Json, b: Json) -> bool:
        return bool(table_claims._overlaps(a["bbox1000"], b["bbox1000"]))

    out = []
    for g in gold:
        hits = [t for t in read if touch(g, t)]
        if len(hits) == 1 and sum(touch(other, hits[0]) for other in gold) == 1:
            out.append((g, hits[0]))
    return out


def _cell_matches(gold: Json, read: Json) -> int:
    """Gold cells the reader put at the same grid slot with the same normalized text."""
    got = {
        (c["rowIndex0"], c["columnIndex0"], c["rowSpan"], c["columnSpan"]): normalize_space(
            c["text"]
        )
        for c in read["cells"]
    }
    return sum(
        got.get((c["rowIndex0"], c["columnIndex0"], c["rowSpan"], c["columnSpan"]))
        == normalize_space(c["text"])
        for c in gold["cells"]
    )


def _rate(numerator: int, denominator: int, of: str) -> Json:
    assert 0 <= numerator <= denominator, (numerator, denominator, of)
    return {"numerator": numerator, "denominator": denominator, "of": of}


def _wall(values: list[float], pages: int) -> Json:
    """Median, p90 (nearest rank) and maximum over the pages that were timed."""
    ordered = sorted(values)
    return {
        "measuredPages": len(ordered),
        "pages": pages,
        "medianSeconds": statistics.median(ordered) if ordered else None,
        "p90Seconds": ordered[math.ceil(0.9 * len(ordered)) - 1] if ordered else None,
        "maxSeconds": ordered[-1] if ordered else None,
    }


def _code_ref(path: Path) -> Json:
    data = path.read_bytes()
    return {"path": path.resolve().relative_to(ROOT).as_posix(), "sha256": _sha256(data)}


def teds_blocked(commit: object, reason: str) -> Json:
    """The `teds` block when the evaluator did not run: a reason, and no value at all."""
    return {
        "status": "EVALUATOR_BLOCKED",
        "computed": False,
        "evaluator": EVALUATOR,
        "evaluatorCommit": commit,
        "reason": reason,
    }


def build_receipt(manifest_path: Path, teds: TedsRunner | None = None) -> Json:
    """Read the manifest and every file it names; return the receipt or raise ShadowRefused.

    `teds` runs the pinned evaluator over every page's gold and read tables (`omnidoc_teds`).
    Without it the receipt's `teds` block is EVALUATOR_BLOCKED.
    """
    base = manifest_path.parent
    manifest_ref, manifest_raw = _read(base, manifest_path.name, "manifest")
    manifest = _check_manifest(_json(manifest_raw, "SHADOW_MANIFEST_INVALID", "manifest"))
    rights = sorted({corpus["rightsStatus"] for corpus in manifest["corpora"]})
    if len(rights) != 1:
        raise ShadowRefused(
            "SHADOW_CORPUS_RIGHTS_MIXED", f"one run holds corpora of rights {rights}"
        )
    synthetic = rights[0] == "synthetic"
    if manifest["synthetic"] is not synthetic:
        raise ShadowRefused(
            "SHADOW_CORPUS_RIGHTS_MIXED", "manifest synthetic label disagrees with its corpus"
        )
    conditions = manifest["conditions"]

    inputs: list[Json] = []
    byte_compare: list[Json] = []
    page_rows: list[Json] = []
    reasons: Counter[str] = Counter()
    walls: list[float] = []
    teds_pages: list[Json] = []
    n = Counter[str]()  # numerators and denominators, named below
    for doc in manifest["documents"]:
        name = doc["documentId"]
        baseline_ref, baseline_raw = _read(
            base, doc["baselineOcrJson"], f"{name} baseline ocr.json"
        )
        shadow_ref, shadow_raw = _read(base, doc["shadowOcrJson"], f"{name} shadow ocr.json")
        gold_ref, gold_raw = _read(base, doc["gold"], f"{name} gold")
        page_count, regions = _ocr_regions(
            _json(baseline_raw, "SHADOW_OCR_INVALID", f"{name} baseline ocr.json"), doc
        )
        indices = [page["pageIndex0"] for page in doc["pages"]]
        if indices != list(range(page_count)):
            raise ShadowRefused(
                "SHADOW_MANIFEST_INVALID",
                f"{name} pages must list every ocr.json page 0..{page_count - 1} in order",
            )
        gold = _gold_pages(
            _json(gold_raw, "SHADOW_GOLD_INVALID", f"{name} gold"), doc, indices, synthetic
        )
        # Regression condition 1 (§C5): the existing lane's output is byte-identical.
        identical = baseline_raw == shadow_raw
        n["docs"] += 1
        n["docsIdentical"] += identical
        byte_compare.append(
            {
                "documentId": name,
                "baselineSha256": baseline_ref["sha256"],
                "shadowSha256": shadow_ref["sha256"],
                "identical": identical,
            }
        )
        read_refs: list[Json] = []
        for page in doc["pages"]:
            index = page["pageIndex0"]
            payload: object = None  # no file: the reader produced nothing for this page
            if page["tableRead"] is not None:
                ref, raw = _read(base, page["tableRead"], f"{name} page {index} table_read")
                read_refs.append({"pageIndex0": index, **ref})
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    # Bytes that are not JSON are the reader's malformed output, not a missing
                    # one: qualify_table_read fails them as TABLE_READ_SCHEMA_INVALID.
                    payload = raw.decode("utf-8", "replace")
            else:
                read_refs.append({"pageIndex0": index, "path": None, "sha256": None, "bytes": None})
            row, read_tables = _page(
                doc, index, payload, regions, conditions, gold[index], reasons, n
            )
            teds_pages.append(
                {"documentId": name, "pageIndex0": index, "gold": gold[index], "read": read_tables}
            )
            row["readerWallSeconds"] = page["readerWallSeconds"]
            if page["readerWallSeconds"] is not None:
                walls.append(page["readerWallSeconds"])
            page_rows.append(row)
        inputs.append(
            {
                "documentId": name,
                "corpusId": doc["corpusId"],
                "sourceImmutableKey": doc["sourceImmutableKey"],
                "inputSha256": doc["inputSha256"],
                "baselineOcrJson": baseline_ref,
                "shadowOcrJson": shadow_ref,
                "gold": gold_ref,
                "tableRead": read_refs,
            }
        )

    statuses = Counter(row["status"] for row in page_rows)
    teds_block = (
        teds(teds_pages, conditions["evaluatorCommit"], synthetic)
        if teds is not None
        else teds_blocked(conditions["evaluatorCommit"], "no evaluator was given to this run")
    )
    return {
        "schemaVersion": RECEIPT_SCHEMA,
        "synthetic": synthetic,
        "note": (
            "SYNTHETIC corpus: no reader ran and no number here measures any reader."
            if synthetic
            else "Offline shadow receipt over reader output already on disk."
        ),
        "rightsStatus": rights[0],
        "corpora": sorted(manifest["corpora"], key=lambda corpus: corpus["corpusId"]),
        "conditions": {**conditions, "corpusManifestSha256": manifest_ref["sha256"]},
        "harness": {
            "code": [_code_ref(Path(__file__)), _code_ref(Path(table_claims.__file__))],
            "network": False,
            "gpu": False,
        },
        "inputs": {"manifest": manifest_ref, "documents": inputs},
        "ocrJsonByteCompare": byte_compare,
        "pages": page_rows,
        "pageStatusCounts": {status: statuses[status] for status in _PAGE_STATUSES},
        "reasonCodeCounts": dict(sorted(reasons.items())),
        "rates": {
            "ocrJsonByteIdentical": _rate(n["docsIdentical"], n["docs"], "documents"),
            "pagesQualified": _rate(n["pagesOk"], n["pages"], "manifest pages"),
            "tablesReadOfReaderReported": _rate(
                n["tablesRead"],
                n["tablesRead"] + n["tablesRefused"],
                "tables the reader read or refused, on pages that qualified",
            ),
            "goldTablesMatched": _rate(n["goldTablesMatched"], n["goldTables"], "gold tables"),
            "cellExactMatch": _rate(n["goldCellsMatched"], n["goldCells"], "gold cells"),
            "readerCellsConfirmed": _rate(
                n["cellsConfirmed"], n["cellsRead"], "cells in tables the reader read"
            ),
            "dataCellsPromotedToClaims": _rate(
                n["claims"], n["dataCells"], "data cells below a header row in tables read"
            ),
        },
        "teds": teds_block,
        "readerWallSecondsPerPage": _wall(walls, len(page_rows)),
        "doesNotProve": [
            (
                "TEDS: the pinned evaluator's score of the tables on disk; on a SYNTHETIC corpus"
                " it measures no reader."
                if teds_block["computed"]
                else "TEDS: not computed (EVALUATOR_BLOCKED)."
            ),
            "The §C5 verdict (fact recall, unsupported claims against the existing World): R3.",
            "That a reader ran: a page whose readerWallSeconds is null was never timed.",
            "Any threshold: no rate here is compared with a pass mark; none is calibrated.",
        ],
    }


def _page(
    doc: Json,
    index: int,
    payload: object,
    regions: list[OcrRegion],
    conditions: Json,
    gold_tables: list[Json],
    reasons: Counter[str],
    n: Counter[str],
) -> tuple[Json, list[Json]]:
    """One page through T3, and the tables it read; a failed page is counted, never dropped."""
    expected: TableReadExpectation = {
        "sourceImmutableKey": doc["sourceImmutableKey"],
        "inputSha256": doc["inputSha256"],
        "readerRevision": conditions["readerRevision"],
        "readerBindingSha256": conditions["readerBindingSha256"],
        "pageIndex0": index,
        "ocrRegions": [region for region in regions if region["pageIndex0"] == index],
    }
    row: Json = {"documentId": doc["documentId"], "pageIndex0": index, "reasonCode": None}
    read_tables: list[Json] = []
    refusals: Counter[str] = Counter()
    claims = data_cells = 0
    page = qualify_table_read(payload, expected)
    if page["ok"] is False:
        row.update(status="failed", reasonCode=page["reasonCode"])
    else:
        try:
            tables = canonical_tables(
                page,
                expected,
                document_id=doc["documentId"],
                document_version_id=doc["documentVersionId"],
            )
        except TableReadRejected as rejected:
            row.update(status="failed", reasonCode=rejected.reason_code)
        else:
            row["status"] = page["pageStatus"]
            read_tables = [dict(table) for table in page["tables"]]
            refusals.update(refusal["reasonCode"] for refusal in page["refusals"])
            for table in tables:
                claims += len(table_cell_claims(table))
                data_cells += sum(cell.row_index0 >= table.header_row_count for cell in table.cells)
    if row["reasonCode"] is not None:
        reasons[row["reasonCode"]] += 1
    reasons.update(refusals)
    cells = [cell for table in read_tables for cell in table["cells"]]
    unconfirmed = sum(not cell["confirmedBy"] for cell in cells)
    if unconfirmed:
        reasons["TABLE_CELL_TEXT_UNCONFIRMED"] += unconfirmed
    pairs = _pairs(gold_tables, read_tables)
    counts = {
        "tablesRead": len(read_tables),
        "tablesRefused": sum(refusals[code] for code in table_claims._TABLE_REFUSAL_CODES),
        "cellsRead": len(cells),
        "cellsConfirmed": len(cells) - unconfirmed,
        "dataCells": data_cells,
        "claims": claims,
        "goldTables": len(gold_tables),
        "goldTablesMatched": len(pairs),
        "goldCells": sum(len(table["cells"]) for table in gold_tables),
        "goldCellsMatched": sum(_cell_matches(g, t) for g, t in pairs),
    }
    n.update(counts)
    n["pages"] += 1
    n["pagesOk"] += row["status"] != "failed"
    return {**row, "refusalCounts": dict(sorted(refusals.items())), **counts}, read_tables


def receipt_bytes(receipt: Json) -> bytes:
    return (json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def write_receipt(receipt: Json, out: Path) -> None:
    """The receipt and its `.sha256` beside it; prints the digest."""
    data = receipt_bytes(receipt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    Path(f"{out}.sha256").write_bytes(f"{digest}  {out.name}\n".encode())
    print(f"sha256:{digest}  {out.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = build_receipt(args.manifest)
    except ShadowRefused as refused:
        print(f"refused {refused.reason_code}: {refused.detail}", file=sys.stderr)
        return 2
    write_receipt(receipt, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
