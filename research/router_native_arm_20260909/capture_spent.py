"""CPU-only Native pilot over source-manifest-bound spent public olmOCR pages.

This script never opens evaluator outputs or labels. It emits one row for each
selected source-manifest unit even when parsing fails. It is a development
observation arm, not a Native accuracy or source-grounding claim. The pilot
samples deterministically by source path family before any output is read.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from akc_native_parsers.models import ParseContext, StructuredParseError
from akc_native_parsers.pdf_parser import parse_pdf_to_cir
from akc_router.native_observation import project_native_pages
from pypdf.errors import DependencyError

ROOT = Path(__file__).resolve().parents[2]


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def select_rows(
    manifest: bytes, *, all_units: bool, expected_units: int
) -> tuple[list[dict], int]:
    """Select using source inventory only, never outcomes or benchmark labels."""
    if type(expected_units) is not int or not 1 <= expected_units <= 2000:
        raise ValueError("SPENT_SCOPE_BOUND_INVALID")
    family_rows: dict[str, list[dict]] = defaultdict(list)
    identities: set[str] = set()
    for line in manifest.decode("utf-8-sig").splitlines():
        row = json.loads(line)
        if row["benchmark"] != "olmocr" or row["media_type"] != "pdf":
            continue
        if row.get("campaign_id") != "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1":
            raise ValueError("SPENT_CAMPAIGN_MISMATCH")
        if row["sample_id"] in identities:
            raise ValueError("DUPLICATE_SPENT_SOURCE_UNIT")
        identities.add(row["sample_id"])
        relative = Path(row["original_source_relative_path"])
        if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".pdf":
            raise ValueError("PUBLIC_SOURCE_PATH_INVALID")
        family_rows[relative.parts[2] if len(relative.parts) > 3 else "unspecified"].append(row)
    if not family_rows:
        raise ValueError("NO_ELIGIBLE_SPENT_SOURCE_UNITS")
    eligible = sum(len(rows) for rows in family_rows.values())
    if eligible != expected_units:
        raise ValueError("SPENT_SOURCE_DENOMINATOR_MISMATCH")
    selected = []
    for _family, rows in sorted(family_rows.items()):
        ordered = sorted(rows, key=lambda r: hashlib.sha256(r["sample_id"].encode()).hexdigest())
        selected.extend(ordered if all_units else ordered[:8])
    if not all_units and len(selected) > 256:
        raise ValueError("PILOT_SCOPE_EXCEEDS_BOUND")
    return selected, eligible


def run(*, all_units: bool = False, output_name: str = "native-spent-pilot-v2") -> None:
    arena = Path(os.environ["TAVONEL_SPENT_ARENA_ROOT"]).resolve(strict=True)
    sources = Path(os.environ["TAVONEL_SPENT_SOURCE_ROOT"]).resolve(strict=True)
    if not output_name or Path(output_name).name != output_name or output_name in {".", ".."}:
        raise ValueError("OUTPUT_MUST_BE_SINGLE_NEW_SCRATCH_DIRECTORY")
    output = ROOT / ".chatgpt2codex" / output_name
    manifest = (arena / "source_manifest.jsonl").read_bytes()
    selected, eligible = select_rows(manifest, all_units=all_units, expected_units=1403)
    for row in selected:
        source = (sources / "olmocr-bench" / row["original_source_relative_path"]).resolve(
            strict=True
        )
        if not source.is_relative_to(sources / "olmocr-bench"):
            raise ValueError("PUBLIC_SOURCE_OUTSIDE_ROOT")
        if sha(source.read_bytes()) != row["original_source_sha256"]:
            raise ValueError("SPENT_SOURCE_HASH_MISMATCH")
    output.mkdir(parents=True, exist_ok=False)
    freeze = {
        "confirmatory_eligible": False,
        "quality_verified": False,
        "source_manifest_sha256": sha(manifest),
        "selection": (
            "Every eligible source-manifest unit; family then SHA256(sample_id), before parsing"
            if all_units else
            "Up to 8 per original path family, ascending SHA256(sample_id), before parsing"
        ),
        "revision_note": (
            "Full denominator capture option; earlier pilot evidence remains unchanged"
        ),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pypdf": importlib.metadata.version("pypdf"),
            "pydantic": importlib.metadata.version("pydantic"),
        },
        "native_parser_sha256": sha(
            (ROOT / "packages/native-parsers/src/akc_native_parsers/pdf_parser.py").read_bytes()
        ),
        "eligible_units": eligible,
        "selected_units": len(selected),
        "selected_source_rows": selected,
        "hidden_evaluation_visible_to_runtime": False,
        "code_sha256": sha(Path(__file__).read_bytes()),
        "native_projection_sha256": sha(
            (ROOT / "packages/router/src/akc_router/native_observation.py").read_bytes()
        ),
    }
    with (output / "FREEZE.json").open("x", encoding="utf-8") as stream:
        json.dump(freeze, stream, ensure_ascii=False, indent=2)
    summaries = []
    with (output / "observations.jsonl").open("x", encoding="utf-8") as stream:
        for row in selected:
            source = sources / "olmocr-bench" / row["original_source_relative_path"]
            before, cpu = time.perf_counter(), time.process_time()
            record = {
                "sample_id": row["sample_id"],
                "case_key": row["case_key"],
                "source_sha256": row["original_source_sha256"],
                "route": "native",
                "quality_verified": False,
                "confirmatory_eligible": False,
            }
            try:
                document = parse_pdf_to_cir(
                    filename=source.name,
                    declared_mime="application/pdf",
                    data=source.read_bytes(),
                    max_pages=128,
                    context=ParseContext(
                        tenant_id="native-spent-development",
                        document_id="native-"
                        + hashlib.sha256(row["sample_id"].encode()).hexdigest()[:24],
                        document_version_id=row["original_source_sha256"],
                        created_at=datetime(2026, 9, 9, tzinfo=UTC),
                    ),
                )
                pages = project_native_pages(
                    document,
                    expected_source_sha256=row["original_source_sha256"],
                    expected_page_count=len(document.metadata["pages"]),
                )
                index = row["page_index"]
                if type(index) is not int or not 0 <= index < len(pages):
                    raise ValueError("SOURCE_PAGE_INDEX_INVALID")
                page = pages[index]
                record.update(
                    status=page.status.value,
                    text=page.text,
                    output_sha256=page.output_sha256,
                    page_index0=page.page_index0,
                    located_blocks=page.located_block_count,
                    unlocated_blocks=page.unlocated_block_count,
                )
            except DependencyError:
                record.update(
                    status="native_runtime_unqualified",
                    reason="NATIVE_PARSER_DEPENDENCY_UNAVAILABLE",
                    text="",
                    output_sha256=sha(b""),
                )
            except StructuredParseError as error:
                record.update(
                    status="native_parser_refused",
                    reason=error.code,
                    text="",
                    output_sha256=sha(b""),
                )
            except Exception:
                record.update(
                    status="native_parser_failed",
                    reason="NATIVE_EXECUTION_FAILED",
                    text="",
                    output_sha256=sha(b""),
                )
            record.update(
                local_wall_seconds=time.perf_counter() - before,
                local_cpu_seconds=time.process_time() - cpu,
            )
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            summary = {
                key: value
                for key, value in record.items()
                if key not in {"text", "case_key", "source_sha256", "output_sha256"}
            }
            summaries.append(summary)
            print(
                json.dumps(
                    {
                        "completed": len(summaries),
                        "total": len(selected),
                        "status": record["status"],
                    }
                ),
                flush=True,
            )
    with (output / "RESULT.json").open("x", encoding="utf-8") as stream:
        json.dump(
            {
                "selected": len(selected),
                "output_rows": len(summaries),
                "confirmatory_eligible": False,
                "quality_claim": False,
                "records": summaries,
                "observations_sha256": sha((output / "observations.jsonl").read_bytes()),
            },
            stream,
            ensure_ascii=False,
            indent=2,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-units", action="store_true")
    parser.add_argument("--output-name", default="native-spent-pilot-v2")
    args = parser.parse_args()
    run(all_units=args.all_units, output_name=args.output_name)
