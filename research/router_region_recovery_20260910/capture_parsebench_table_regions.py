"""Capture source-bound regions for the spent ParseBench table surface.

The capture reads only the public source manifest and source PDFs. It does not
open ParseBench rule files, score files, model output or ground truth, and it
emits no document text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from akc_native_parsers.models import ParseContext, StructuredParseError
from akc_native_parsers.pdf_parser import parse_pdf_to_cir
from akc_router.region_recovery import project_source_bound_text_regions
from pypdf.errors import DependencyError, LimitReachedError

EXPECTED_MANIFEST = (
    "sha256:2ec00f371db5069216362ee946b084ed0d222474162d7eadcbf717f09ae55e7c"
)
EXPECTED_CAMPAIGN = "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1"
EXPECTED_UNITS = 503


class RegionRecord(TypedDict):
    region_id: str
    block_id: str
    bbox1000: tuple[int, int, int, int]
    witness_sha256: str
    expected_content_sha256: str


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def source_rows(manifest: bytes) -> list[dict[str, object]]:
    if digest(manifest) != EXPECTED_MANIFEST:
        raise ValueError("PARSEBENCH_SOURCE_MANIFEST_MISMATCH")
    rows: list[dict[str, object]] = []
    identities: set[str] = set()
    for line in manifest.decode("utf-8-sig").splitlines():
        row = json.loads(line)
        relative = Path(str(row.get("original_source_relative_path") or ""))
        if not (
            row.get("benchmark") == "parsebench"
            and row.get("media_type") == "pdf"
            and relative.parts[:2] == ("docs", "table")
        ):
            continue
        if row.get("campaign_id") != EXPECTED_CAMPAIGN:
            raise ValueError("PARSEBENCH_CAMPAIGN_MISMATCH")
        sample_id = row.get("sample_id")
        case_key = row.get("case_key")
        if (
            not isinstance(sample_id, str)
            or not isinstance(case_key, str)
            or sample_id in identities
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.suffix.lower() != ".pdf"
        ):
            raise ValueError("PARSEBENCH_SOURCE_IDENTITY_INVALID")
        identities.add(sample_id)
        rows.append(row)
    if len(rows) != EXPECTED_UNITS:
        raise ValueError("PARSEBENCH_TABLE_DENOMINATOR_MISMATCH")
    return sorted(rows, key=lambda row: str(row["sample_id"]))


def parser_reason(error: Exception) -> str:
    if isinstance(error, DependencyError):
        return "NATIVE_RUNTIME_UNQUALIFIED"
    if isinstance(error, LimitReachedError):
        return "PDF_DECOMPRESSION_LIMIT_REACHED"
    if isinstance(error, StructuredParseError):
        return error.code
    if isinstance(error, KeyError):
        return (
            "PYPDF_IMAGE_METADATA_MISSING"
            if error.args == ("/N",)
            else "PDF_OBJECT_REFERENCE_MISSING"
        )
    return "NATIVE_PARSER_FAILED"


def run(args: argparse.Namespace) -> None:
    arena = args.arena.resolve(strict=True)
    sources = args.sources.resolve(strict=True)
    rows = source_rows((arena / "source_manifest.jsonl").read_bytes())
    output = args.output.resolve()
    if output.exists():
        raise ValueError("PARSEBENCH_REGION_OUTPUT_MUST_BE_NEW")
    output.mkdir(parents=True)
    records_path = output / "REGIONS.jsonl"
    statuses: Counter[str] = Counter()
    region_count = 0
    started = time.perf_counter()
    with records_path.open("x", encoding="utf-8", newline="\n") as stream:
        for index, row in enumerate(rows, start=1):
            relative = Path(str(row["original_source_relative_path"]))
            source = (sources / "parsebench" / relative).resolve(strict=True)
            if not source.is_relative_to(sources / "parsebench"):
                raise ValueError("PARSEBENCH_SOURCE_PATH_ESCAPE")
            data = source.read_bytes()
            if digest(data) != row["original_source_sha256"]:
                raise ValueError("PARSEBENCH_SOURCE_HASH_MISMATCH")
            record: dict[str, object] = {
                "sample_id": row["sample_id"],
                "case_key": row["case_key"],
                "unit_key": str(relative).removeprefix("docs/").removesuffix(".pdf"),
                "page_index0": row["page_index"],
                "source_sha256": row["original_source_sha256"],
                "status": "unresolved",
                "regions": [],
            }
            try:
                document = parse_pdf_to_cir(
                    filename=source.name,
                    declared_mime="application/pdf",
                    data=data,
                    max_pages=128,
                    context=ParseContext(
                        tenant_id="parsebench-table-region-development",
                        document_id="table-"
                        + hashlib.sha256(str(row["sample_id"]).encode()).hexdigest()[:24],
                        document_version_id=str(row["original_source_sha256"]),
                        created_at=datetime(2026, 9, 10, tzinfo=UTC),
                    ),
                )
                inventory = project_source_bound_text_regions(
                    document,
                    expected_source_sha256=str(row["original_source_sha256"]),
                    representation_sha256=str(row["original_source_sha256"]),
                )
                page_index = row["page_index"]
                if type(page_index) is not int:
                    raise ValueError("PARSEBENCH_PAGE_INDEX_INVALID")
                regions: list[RegionRecord] = [
                    {
                        "region_id": region.binding.region_id,
                        "block_id": region.block_id,
                        "bbox1000": region.binding.bbox1000,
                        "witness_sha256": region.witness.observation.output_sha256,
                        "expected_content_sha256": region.expected_content_sha256,
                    }
                    for region in inventory.regions
                    if region.binding.page_index0 == page_index
                ]
                record.update(
                    status=(
                        "source_regions_available" if regions else "source_regions_unavailable"
                    ),
                    regions=regions,
                    document_unresolved_region_count=len(inventory.unresolved),
                )
            except Exception as error:
                record.update(status="native_parser_refused", reason=parser_reason(error))
            statuses[str(record["status"])] += 1
            region_count += len(record["regions"])  # type: ignore[arg-type]
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            if index % 100 == 0:
                print(json.dumps({"completed": index, "total": len(rows)}), flush=True)
    result = {
        "units": len(rows),
        "status_counts": dict(sorted(statuses.items())),
        "regions": region_count,
        "regions_sha256": digest(records_path.read_bytes()),
        "elapsed_seconds": time.perf_counter() - started,
        "hidden_table_truth_visible": False,
        "text_disclosed": False,
        "quality_claim": False,
        "gpu_cost_usd": 0,
    }
    (output / "RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
