"""Acquire exactly the frozen mixed-source candidates without replacement.

This stage downloads official source bytes and derives only predeclared,
truth-free structural locators. It never reads annotations, calls a model or
opens holdout truth. Original bytes belong in a private ignored directory and
must not be committed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import posixpath
import re
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import requests
from defusedxml import ElementTree as SafeET
from pypdf import PdfReader

from .preflight_mixed_holdout import digest

MAX_SOURCE_BYTES = 300 * 1024 * 1024
SELECTED = "SELECTED"
NUMERIC_TOKEN = re.compile(r"(?<![\w.])[+-]?(?:\d[\d,]*)(?:\.\d+)?%?(?!\w)")
TABLE_HEADING = re.compile(r"^\s*Table\s+[A-Za-z0-9]", re.IGNORECASE)
OOXML_MEMBER = {
    "office_korean_docx": "word/document.xml",
    "office_korean_pptx": "ppt/presentation.xml",
    "office_korean_xlsx": "xl/workbook.xml",
}
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_XML_MEMBER_BYTES = 10 * 1024 * 1024
RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
MEDIA_BY_CLASS = {
    "born_digital_pdf_table": "application/pdf",
    "scanned_pdf": "application/pdf",
    "layout_heavy_pdf": "application/pdf",
    "target_alignment_failure": "application/pdf",
    "office_korean_docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    "office_korean_pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    "office_korean_xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
}


class AcquisitionError(ValueError):
    """A selected source could not be bound without changing the corpus."""


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_inventory(path: Path) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("candidates"), list):
        raise AcquisitionError("CANDIDATE_INVENTORY_INVALID")
    selected = [
        row
        for row in value["candidates"]
        if isinstance(row, dict) and row.get("selection_state") == SELECTED
    ]
    if len(selected) != 96:
        raise AcquisitionError("SELECTED_DENOMINATOR_NOT_96")
    counts = Counter(str(row.get("source_class")) for row in selected)
    if len(counts) != 8 or set(counts.values()) != {12}:
        raise AcquisitionError("SELECTED_CLASS_DENOMINATOR_INVALID")
    return cast(Mapping[str, Any], value), cast(list[Mapping[str, Any]], selected)


def _safe_unit_id(value: object) -> str:
    text = str(value)
    if not text or not re.fullmatch(r"[A-Za-z0-9._:-]+", text):
        raise AcquisitionError("UNIT_ID_UNSAFE")
    return text.replace(":", "_")


def _download(row: Mapping[str, Any], destination: Path, timeout: int) -> dict[str, Any]:
    url = str(row["source_url"])
    unit_id = str(row["candidate_id"])
    temp = destination.with_suffix(destination.suffix + ".part")
    temp.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    size = 0
    try:
        with requests.get(
            url,
            headers={"User-Agent": "TAVONEL-Holdout-Acquisition/1.0"},
            allow_redirects=False,
            stream=True,
            timeout=(30, timeout),
        ) as response:
            if response.status_code != 200:
                raise AcquisitionError(f"HTTP_STATUS_{response.status_code}")
            if response.url != url:
                raise AcquisitionError("EFFECTIVE_URL_CHANGED")
            with temp.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > MAX_SOURCE_BYTES:
                        raise AcquisitionError("SOURCE_SIZE_LIMIT_EXCEEDED")
                    hasher.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    if size < 1:
        temp.unlink(missing_ok=True)
        raise AcquisitionError("SOURCE_EMPTY")
    os.replace(temp, destination)
    return {
        "unit_id": unit_id,
        "source_size_bytes": size,
        "source_sha256": "sha256:" + hasher.hexdigest(),
        "transport_content_type": content_type,
        "acquired_at_utc": _timestamp(),
    }


def _native_media_type(path: Path, filename: str, header_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    known = {
        ".csv": "text/csv",
        ".xml": "application/xml",
        ".json": "application/json",
        ".geojson": "application/geo+json",
    }
    media_type = known.get(suffix)
    if media_type is None:
        raise AcquisitionError("NATIVE_MEDIA_TYPE_UNSUPPORTED")
    if header_type.lower() in {"text/html", "application/xhtml+xml"}:
        raise AcquisitionError("NATIVE_SOURCE_RETURNED_HTML")
    try:
        if suffix == ".csv":
            for encoding in ("utf-8-sig", "cp1252"):
                try:
                    with path.open("r", encoding=encoding, newline="") as handle:
                        header = next(csv.reader(handle))
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise AcquisitionError("CSV_ENCODING_UNSUPPORTED")
            if not header or not any(field.strip() for field in header):
                raise AcquisitionError("CSV_HEADER_EMPTY")
        elif suffix in {".json", ".geojson"}:
            json.loads(path.read_text(encoding="utf-8-sig"))
        elif suffix == ".xml":
            SafeET.parse(path)
    except (csv.Error, SafeET.ParseError, json.JSONDecodeError) as exc:
        raise AcquisitionError("NATIVE_STRUCTURE_INVALID") from exc
    return media_type


def _pdf_geometry_locator(path: Path) -> str:
    reader = PdfReader(str(path), strict=True)
    if not reader.pages:
        raise AcquisitionError("PDF_HAS_NO_PAGES")
    dimensions = []
    for index, page in enumerate(reader.pages, 1):
        box = page.mediabox
        width = float(box.width)
        height = float(box.height)
        rotation = int(page.get("/Rotate", 0) or 0) % 360
        score = (rotation not in {0, 180}, max(width, height), abs(width - height), index)
        dimensions.append((score, index))
    page_number = max(dimensions)[1]
    return f"page:{page_number}:bbox1000:0,0,1000,1000"


def _pdf_table_locator(path: Path) -> str:
    reader = PdfReader(str(path), strict=True)
    fallback: int | None = None
    for index, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if any(TABLE_HEADING.match(line) for line in lines):
            return f"page:{index}:bbox1000:0,0,1000,1000"
        if fallback is None:
            numeric_lines = sum(len(NUMERIC_TOKEN.findall(line)) >= 3 for line in lines)
            if numeric_lines >= 2:
                fallback = index
    if fallback is None:
        raise AcquisitionError("TABLE_LOCATOR_UNRESOLVED")
    return f"page:{fallback}:bbox1000:0,0,1000,1000"


def _read_zip_xml(archive: zipfile.ZipFile, name: str) -> Any:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise AcquisitionError("OOXML_STRUCTURE_INVALID") from exc
    if info.file_size > MAX_XML_MEMBER_BYTES:
        raise AcquisitionError("OOXML_XML_MEMBER_TOO_LARGE")
    try:
        return SafeET.fromstring(archive.read(info))
    except SafeET.ParseError as exc:
        raise AcquisitionError("OOXML_XML_INVALID") from exc


def _relationship_target(
    archive: zipfile.ZipFile,
    rels_name: str,
    rel_id: str,
    *,
    required_prefix: str,
) -> str:
    root = _read_zip_xml(archive, rels_name)
    for relationship in root.findall(f"{{{RELATIONSHIPS_NS}}}Relationship"):
        if relationship.get("Id") != rel_id:
            continue
        target = relationship.get("Target")
        if not target or relationship.get("TargetMode") == "External":
            raise AcquisitionError("OOXML_RELATIONSHIP_TARGET_INVALID")
        base = posixpath.dirname(posixpath.dirname(rels_name))
        resolved = posixpath.normpath(posixpath.join(base, target))
        if (
            resolved.startswith("../")
            or resolved.startswith("/")
            or not resolved.startswith(required_prefix)
            or not resolved.endswith(".xml")
        ):
            raise AcquisitionError("OOXML_RELATIONSHIP_TARGET_INVALID")
        try:
            archive.getinfo(resolved)
        except KeyError as exc:
            raise AcquisitionError("OOXML_RELATIONSHIP_TARGET_MISSING") from exc
        return resolved
    raise AcquisitionError("OOXML_RELATIONSHIP_ID_MISSING")


def _docx_locator(archive: zipfile.ZipFile) -> str:
    root = _read_zip_xml(archive, "word/document.xml")
    body = root.find(f"{{{WORD_NS}}}body")
    if body is None:
        raise AcquisitionError("DOCX_BODY_MISSING")
    for position, child in enumerate(body, 1):
        if child.tag == f"{{{WORD_NS}}}sectPr":
            continue
        has_text = any((node.text or "").strip() for node in child.iter())
        local_name = child.tag.rsplit("}", 1)[-1]
        has_semantic_container = local_name in {"tbl", "sdt", "altChunk", "customXml"}
        has_nontext_object = any(
            node.tag.rsplit("}", 1)[-1]
            in {"drawing", "pict", "object", "graphic", "blip", "fldChar"}
            for node in child.iter()
        )
        if has_text or has_semantic_container or has_nontext_object:
            return f"ooxml:word/document.xml#body/*[{position}]"
    raise AcquisitionError("DOCX_BODY_EMPTY")


def _pptx_locator(archive: zipfile.ZipFile) -> str:
    root = _read_zip_xml(archive, "ppt/presentation.xml")
    slide_id = root.find(
        f"{{{PRESENTATION_NS}}}sldIdLst/{{{PRESENTATION_NS}}}sldId"
    )
    rel_id = slide_id.get(f"{{{OFFICE_REL_NS}}}id") if slide_id is not None else None
    if not rel_id:
        raise AcquisitionError("PPTX_FIRST_SLIDE_RELATIONSHIP_MISSING")
    target = _relationship_target(
        archive,
        "ppt/_rels/presentation.xml.rels",
        rel_id,
        required_prefix="ppt/slides/",
    )
    return f"ooxml:{target}"


def _xlsx_locator(archive: zipfile.ZipFile) -> str:
    root = _read_zip_xml(archive, "xl/workbook.xml")
    sheet = root.find(f"{{{SPREADSHEET_NS}}}sheets/{{{SPREADSHEET_NS}}}sheet")
    rel_id = sheet.get(f"{{{OFFICE_REL_NS}}}id") if sheet is not None else None
    if not rel_id:
        raise AcquisitionError("XLSX_FIRST_SHEET_RELATIONSHIP_MISSING")
    target = _relationship_target(
        archive,
        "xl/_rels/workbook.xml.rels",
        rel_id,
        required_prefix="xl/worksheets/",
    )
    return f"ooxml:{target}"


def _validate_and_locate(
    *, row: Mapping[str, Any], path: Path, transport_content_type: str
) -> tuple[str, str]:
    source_class = str(row["source_class"])
    rule = str(row["target_locator_rule"])
    with path.open("rb") as handle:
        prefix = handle.read(5)
    if source_class in MEDIA_BY_CLASS and source_class.endswith("_pdf") and prefix != b"%PDF-":
        raise AcquisitionError("PDF_MAGIC_INVALID")
    if source_class == "born_digital_pdf_table":
        if prefix != b"%PDF-":
            raise AcquisitionError("PDF_MAGIC_INVALID")
        return MEDIA_BY_CLASS[source_class], _pdf_table_locator(path)
    if source_class in {"scanned_pdf", "layout_heavy_pdf"}:
        PdfReader(str(path), strict=True)
        return MEDIA_BY_CLASS[source_class], "page:1:bbox1000:0,0,1000,1000"
    if source_class == "target_alignment_failure":
        return MEDIA_BY_CLASS[source_class], _pdf_geometry_locator(path)
    if source_class in OOXML_MEMBER:
        if prefix[:4] != b"PK\x03\x04":
            raise AcquisitionError("OOXML_MAGIC_INVALID")
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise AcquisitionError("OOXML_ENTRY_LIMIT_EXCEEDED")
            if sum(info.file_size for info in infos) > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise AcquisitionError("OOXML_UNCOMPRESSED_SIZE_LIMIT_EXCEEDED")
            names = {info.filename for info in infos}
            required_members = {"[Content_Types].xml", OOXML_MEMBER[source_class]}
            if not required_members.issubset(names):
                raise AcquisitionError("OOXML_STRUCTURE_INVALID")
            locator = {
                "office_korean_docx": _docx_locator,
                "office_korean_pptx": _pptx_locator,
                "office_korean_xlsx": _xlsx_locator,
            }[source_class](archive)
        return MEDIA_BY_CLASS[source_class], locator
    if source_class == "native_structured" and rule == "whole_source":
        return _native_media_type(
            path, str(row["source_filename"]), transport_content_type
        ), (
            "source-native:whole"
        )
    raise AcquisitionError("SOURCE_CLASS_OR_LOCATOR_UNSUPPORTED")


def acquire(
    *, inventory_path: Path, output_root: Path, manifest_path: Path, workers: int, timeout: int
) -> dict[str, Any]:
    inventory, rows = _load_inventory(inventory_path)
    source_root = output_root / "sources"
    source_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}

    def one(row: Mapping[str, Any]) -> dict[str, Any]:
        unit_id = str(row["candidate_id"])
        stored = source_root / f"{_safe_unit_id(unit_id)}.source"
        transport = _download(row, stored, timeout)
        try:
            media_type, locator = _validate_and_locate(
                row=row,
                path=stored,
                transport_content_type=str(transport["transport_content_type"]),
            )
        except Exception:
            stored.unlink(missing_ok=True)
            raise
        return {**transport, "media_type": media_type, "target_locator": locator}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_rows = {pool.submit(one, row): row for row in rows}
        for future in as_completed(future_rows):
            row = future_rows[future]
            unit_id = str(row["candidate_id"])
            try:
                results[unit_id] = future.result()
            except Exception as exc:
                errors[unit_id] = f"{type(exc).__name__}:{exc}"

    receipt = {
        "schema": "tavonel.router_source_acquisition_receipt.v1",
        "benchmark_id": inventory.get("benchmark_id"),
        "candidate_inventory_sha256": digest(inventory_path.read_bytes()),
        "selected_units": len(rows),
        "acquired_units": len(results),
        "failed_units": len(errors),
        "errors": dict(sorted(errors.items())),
        "truth_accessed": False,
        "model_calls": 0,
        "gpu_calls": 0,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "ACQUISITION_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if errors:
        manifest_path.unlink(missing_ok=True)
        return receipt

    manifest_rows = []
    for row in rows:
        unit_id = str(row["candidate_id"])
        result = results[unit_id]
        manifest_rows.append(
            {
                "unit_id": unit_id,
                "source_class": row["source_class"],
                "source_sha256": result["source_sha256"],
                "source_size_bytes": result["source_size_bytes"],
                "media_type": result["media_type"],
                "source_family_id": row["source_family_id"],
                "source_url": row["source_url"],
                "selection_url_sha256": row["selection_url_sha256"],
                "rights_status": row["rights_status"],
                "rights_evidence_url": row["rights_evidence_url"],
                "rights_checked_at_utc": row["rights_checked_at_utc"],
                "allowed_use_scope": row["allowed_use_scope"],
                "language": row["language"],
                "publisher": row["publisher"],
                "acquired_at_utc": result["acquired_at_utc"],
                "target_locator_kind": "source_native_or_bbox1000",
                "target_locator": result["target_locator"],
                "truth_state": "SEALED_UNOPENED",
            }
        )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in manifest_rows
        ),
        encoding="utf-8",
    )
    receipt["source_manifest_sha256"] = digest(manifest_path.read_bytes())
    (output_root / "ACQUISITION_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)
    receipt = acquire(
        inventory_path=args.inventory,
        output_root=args.output_root,
        manifest_path=args.manifest,
        workers=args.workers,
        timeout=args.timeout,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["failed_units"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
