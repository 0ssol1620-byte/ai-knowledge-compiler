"""Capture exact source-region availability without reading benchmark labels.

This CPU-only development capture reads the frozen public source manifest and
source PDFs.  It writes no document text and makes no OCR-quality claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

from akc_native_parsers.models import ParseContext, StructuredParseError
from akc_native_parsers.pdf_parser import parse_pdf_to_cir
from akc_router.region_recovery import project_source_bound_text_regions
from pypdf.errors import DependencyError, LimitReachedError

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_UNITS = 1403
EXPECTED_CAMPAIGN = "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1"
EXPECTED_MANIFEST = (
    "sha256:2ec00f371db5069216362ee946b084ed0d222474162d7eadcbf717f09ae55e7c"
)


class RegionRecord(TypedDict):
    region_id: str
    block_id: str
    bbox1000: tuple[int, int, int, int]
    witness_sha256: str
    expected_content_sha256: str


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def source_rows(manifest: bytes) -> list[dict[str, object]]:
    if sha(manifest) != EXPECTED_MANIFEST:
        raise ValueError("SPENT_SOURCE_MANIFEST_MISMATCH")
    rows: list[dict[str, object]] = []
    identities: set[str] = set()
    for line in manifest.decode("utf-8-sig").splitlines():
        row = json.loads(line)
        if row["benchmark"] != "olmocr" or row["media_type"] != "pdf":
            continue
        if row.get("campaign_id") != EXPECTED_CAMPAIGN:
            raise ValueError("SPENT_CAMPAIGN_MISMATCH")
        sample_id = row["sample_id"]
        if not isinstance(sample_id, str) or sample_id in identities:
            raise ValueError("DUPLICATE_OR_INVALID_SPENT_SOURCE_UNIT")
        identities.add(sample_id)
        relative = Path(row["original_source_relative_path"])
        if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".pdf":
            raise ValueError("PUBLIC_SOURCE_PATH_INVALID")
        rows.append(row)
    if len(rows) != EXPECTED_UNITS:
        raise ValueError("SPENT_SOURCE_DENOMINATOR_MISMATCH")
    return sorted(rows, key=lambda row: str(row["sample_id"]))


def overlap_count(regions: list[RegionRecord]) -> int:
    count = 0
    for index, left in enumerate(regions):
        lx0, ly0, lx1, ly1 = left["bbox1000"]
        for right in regions[index + 1 :]:
            rx0, ry0, rx1, ry1 = right["bbox1000"]
            if max(lx0, rx0) < min(lx1, rx1) and max(ly0, ry0) < min(ly1, ry1):
                count += 1
    return count


def run(*, output_name: str) -> None:
    arena = Path(os.environ["TAVONEL_SPENT_ARENA_ROOT"]).resolve(strict=True)
    sources = Path(os.environ["TAVONEL_SPENT_SOURCE_ROOT"]).resolve(strict=True)
    if not output_name or Path(output_name).name != output_name or output_name in {".", ".."}:
        raise ValueError("OUTPUT_MUST_BE_SINGLE_NEW_SCRATCH_DIRECTORY")
    output = ROOT / ".chatgpt2codex" / output_name
    output.mkdir(parents=True, exist_ok=False)
    manifest = (arena / "source_manifest.jsonl").read_bytes()
    rows = source_rows(manifest)
    records: list[dict[str, object]] = []
    started = time.perf_counter()
    with (output / "regions.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            relative = Path(str(row["original_source_relative_path"]))
            source = (sources / "olmocr-bench" / relative).resolve(strict=True)
            if not source.is_relative_to(sources / "olmocr-bench"):
                raise ValueError("PUBLIC_SOURCE_OUTSIDE_ROOT")
            data = source.read_bytes()
            if sha(data) != row["original_source_sha256"]:
                raise ValueError("SPENT_SOURCE_HASH_MISMATCH")
            record: dict[str, object] = {
                "sample_id": row["sample_id"],
                "page_index0": row["page_index"],
                "source_sha256": row["original_source_sha256"],
                "status": "unresolved",
                "regions": [],
                "region_count": 0,
                "overlapping_pair_count": 0,
            }
            try:
                document = parse_pdf_to_cir(
                    filename=source.name,
                    declared_mime="application/pdf",
                    data=data,
                    max_pages=128,
                    context=ParseContext(
                        tenant_id="region-inventory-development",
                        document_id="region-"
                        + hashlib.sha256(str(row["sample_id"]).encode()).hexdigest()[:24],
                        document_version_id=str(row["original_source_sha256"]),
                        created_at=datetime(2026, 9, 10, tzinfo=UTC),
                    ),
                )
            except DependencyError:
                record.update(status="native_runtime_unqualified")
            except LimitReachedError:
                record.update(
                    status="native_parser_refused",
                    reason="PDF_DECOMPRESSION_LIMIT_REACHED",
                )
            except KeyError as error:
                record.update(
                    status="native_parser_refused",
                    reason=(
                        "PYPDF_IMAGE_METADATA_MISSING"
                        if error.args == ("/N",)
                        else "PDF_OBJECT_REFERENCE_MISSING"
                    ),
                )
            except StructuredParseError as error:
                record.update(status="native_parser_refused", reason=error.code)
            except Exception:
                record.update(status="native_parser_failed")
            else:
                try:
                    page_index0 = row["page_index"]
                    if type(page_index0) is not int:
                        raise ValueError("SOURCE_PAGE_INDEX_INVALID")
                    inventory = project_source_bound_text_regions(
                        document,
                        expected_source_sha256=str(row["original_source_sha256"]),
                        representation_sha256=str(row["original_source_sha256"]),
                    )
                    selected: list[RegionRecord] = [
                        {
                            "region_id": region.binding.region_id,
                            "block_id": region.block_id,
                            "bbox1000": region.binding.bbox1000,
                            "witness_sha256": region.witness.observation.output_sha256,
                            "expected_content_sha256": region.expected_content_sha256,
                        }
                        for region in inventory.regions
                        if region.binding.page_index0 == page_index0
                    ]
                    record.update(
                        status=(
                            "source_regions_available"
                            if selected
                            else "source_regions_unavailable"
                        ),
                        regions=selected,
                        region_count=len(selected),
                        overlapping_pair_count=overlap_count(selected),
                        document_unresolved_region_count=len(inventory.unresolved),
                    )
                except ValueError as error:
                    code = str(error)
                    record.update(
                        status="native_region_projection_refused",
                        reason=(
                            code
                            if code.isupper() and " " not in code
                            else "REGION_PROJECTION_CONTRACT_VIOLATION"
                        ),
                    )
                except Exception:
                    record.update(status="native_region_projection_failed")
            records.append(record)
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            if len(records) % 100 == 0:
                print(json.dumps({"completed": len(records), "total": len(rows)}), flush=True)
    counts: dict[str, int] = {}
    for record in records:
        status = str(record["status"])
        counts[status] = counts.get(status, 0) + 1
    result = {
        "units": len(records),
        "status_counts": dict(sorted(counts.items())),
        "pages_with_regions": sum(bool(record["region_count"]) for record in records),
        "regions": sum(cast(int, record["region_count"]) for record in records),
        "pages_with_overlaps": sum(
            bool(record["overlapping_pair_count"]) for record in records
        ),
        "overlapping_pairs": sum(
            cast(int, record["overlapping_pair_count"]) for record in records
        ),
        "elapsed_seconds": time.perf_counter() - started,
        "regions_sha256": sha((output / "regions.jsonl").read_bytes()),
        "quality_claim": False,
        "confirmatory_eligible": False,
        "gpu_cost_usd": 0,
    }
    with (output / "RESULT.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-name", default="router-region-inventory-20260910-v1")
    args = parser.parse_args()
    run(output_name=args.output_name)
