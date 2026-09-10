"""Select a bounded, GT-blind source-region recovery pilot.

The selector reads only runtime-visible source files, frozen model outputs and
the sealed Native capture. It emits no document/model text or literal critical
tokens and never imports the hidden scorer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from akc_cir.critical_tokens import verify_critical_tokens
from akc_native_parsers.models import ParseContext, StructuredParseError
from akc_native_parsers.pdf_parser import parse_pdf_to_cir
from akc_router.region_recovery import NativeTextRegion, project_source_bound_text_regions
from pypdf.errors import DependencyError, LimitReachedError

ROOT = Path(__file__).resolve().parents[2]
REPLAY = ROOT / "research" / "router_replay_20260908"
if str(REPLAY) not in sys.path:
    sys.path.insert(0, str(REPLAY))

import features as F  # type: ignore[import-not-found]  # noqa: E402
import native_visible as N  # type: ignore[import-not-found]  # noqa: E402

PRIMARY = "mineru_vlm"
EXPECTED_UNITS = 1403
EXPECTED_REGION_INVENTORY = (
    "sha256:3de6602ad7ee5894c8e26caf43bf398ed9a558a1fdaac734f41244729239c0e7"
)
KIND_ORDER = ("sign", "currency", "date", "number", "unit")
RISK_ORDER = {kind: index for index, kind in enumerate(KIND_ORDER)}
MAX_MISMATCHES = 12
MAX_PER_KIND = 8
MAX_TARGETS = 32


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _token_hash(kind: str, token: str) -> str:
    return "sha256:" + hashlib.sha256(f"{kind}\x1f{token}".encode()).hexdigest()


def _eligible(unit: Any) -> bool:
    return bool(
        unit.native_text_available
        and unit.native_text_chars >= 100
        and unit.native_locator_coverage is not None
        and unit.native_locator_coverage >= 0.99
        and unit.native_invalid_unicode_ratio <= 0.005
        and unit.native_replacement_ratio <= 0.001
        and unit.outputs[PRIMARY].present
    )


def _region_tokens(region: NativeTextRegion) -> set[tuple[str, str]]:
    report = verify_critical_tokens(region.witness.observation.text, "")
    return {
        (mismatch.kind.value, mismatch.token)
        for mismatch in report.mismatches
        if mismatch.source_count > 0
    }


def _common_region(
    regions: tuple[NativeTextRegion, ...], mismatches: tuple[Any, ...]
) -> NativeTextRegion | None:
    by_token: dict[tuple[str, str], set[str]] = defaultdict(set)
    by_id = {region.binding.region_id: region for region in regions}
    for region in regions:
        for token in _region_tokens(region):
            by_token[token].add(region.binding.region_id)
    candidates: set[str] | None = None
    for mismatch in mismatches:
        if mismatch.source_count <= mismatch.output_count:
            return None
        matches = by_token.get((mismatch.kind.value, mismatch.token), set())
        candidates = set(matches) if candidates is None else candidates & matches
        if not candidates:
            return None
    if candidates is None or len(candidates) != 1:
        return None
    return by_id[next(iter(candidates))]


def _safe_parser_reason(error: BaseException) -> str:
    if isinstance(error, DependencyError):
        return "NATIVE_RUNTIME_UNQUALIFIED"
    if isinstance(error, LimitReachedError):
        return "PDF_DECOMPRESSION_LIMIT_REACHED"
    if isinstance(error, KeyError):
        return (
            "PYPDF_IMAGE_METADATA_MISSING"
            if error.args == ("/N",)
            else "PDF_OBJECT_REFERENCE_MISSING"
        )
    if isinstance(error, StructuredParseError):
        return error.code
    return "NATIVE_PARSER_FAILED"


def _primary_kind(row: dict[str, object]) -> str:
    kinds = row.get("mismatch_kinds")
    if not isinstance(kinds, tuple) or not kinds or not isinstance(kinds[0], str):
        raise ValueError("REGION_SELECTION_KIND_INVALID")
    return kinds[0]


def run(args: argparse.Namespace) -> None:
    arena = Path(os.environ["TAVONEL_SPENT_ARENA_ROOT"]).resolve(strict=True)
    sources = Path(os.environ["TAVONEL_SPENT_SOURCE_ROOT"]).resolve(strict=True)
    cache = args.replay_cache.resolve(strict=True)
    native_capture = N.load_capture(args.native_capture)
    if native_capture.observations_sha256 != (
        "sha256:ac4b4e669eb4b2d09913b77dd0420d779866f4adc00edc69e799cd85c39512a8"
    ):
        raise ValueError("NATIVE_CAPTURE_BINDING_MISMATCH")
    inventory_path = args.region_inventory.resolve(strict=True)
    if digest(inventory_path) != EXPECTED_REGION_INVENTORY:
        raise ValueError("REGION_INVENTORY_BINDING_MISMATCH")
    available: set[str] = set()
    with inventory_path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("status") == "source_regions_available":
                available.add(str(row["sample_id"]))

    bind = json.loads(
        (ROOT / "research/router_oracle_20260908/ARENA_BIND.json").read_text(
            encoding="utf-8"
        )
    )
    models = sorted(
        model
        for model, entry in bind["models"].items()
        if not entry["founder_excluded"] and entry["frozen_outputs"]["available"]
    )
    units, texts = F.load_or_build_units(arena, "olmocr", models, cache)
    units, texts = N.augment_units(units, texts, native_capture)
    if len(units) != EXPECTED_UNITS:
        raise ValueError("REGION_SELECTOR_DENOMINATOR_MISMATCH")
    manifest = {str(row["case_key"]): row for row in F.load_manifest(arena, "olmocr")}
    if len(manifest) != EXPECTED_UNITS:
        raise ValueError("REGION_SELECTOR_MANIFEST_MISMATCH")

    counters: Counter[str] = Counter()
    candidates: list[dict[str, object]] = []
    for unit in sorted(units, key=lambda value: value.case_key):
        counters["units"] += 1
        row = manifest[unit.case_key]
        if str(row["sample_id"]) not in available:
            counters["region_inventory_unavailable"] += 1
            continue
        if not _eligible(unit):
            counters["native_or_primary_ineligible"] += 1
            continue
        native_text = texts.get((N.NATIVE_MODEL, unit.unit_key))
        primary_text = texts.get((PRIMARY, unit.unit_key))
        if native_text is None or primary_text is None:
            counters["runtime_text_unavailable"] += 1
            continue
        report = verify_critical_tokens(native_text, primary_text)
        if not report.mismatches:
            counters["primary_token_pass"] += 1
            continue
        if len(report.mismatches) > MAX_MISMATCHES:
            counters["too_many_mismatches"] += 1
            continue

        relative = Path(str(row["original_source_relative_path"]))
        source = (sources / "olmocr-bench" / relative).resolve(strict=True)
        if not source.is_relative_to(sources / "olmocr-bench"):
            raise ValueError("PUBLIC_SOURCE_OUTSIDE_ROOT")
        data = source.read_bytes()
        if "sha256:" + hashlib.sha256(data).hexdigest() != row["original_source_sha256"]:
            raise ValueError("SPENT_SOURCE_HASH_MISMATCH")
        try:
            document = parse_pdf_to_cir(
                filename=source.name,
                declared_mime="application/pdf",
                data=data,
                max_pages=128,
                context=ParseContext(
                    tenant_id="region-selector-development",
                    document_id="region-"
                    + hashlib.sha256(unit.case_key.encode()).hexdigest()[:24],
                    document_version_id=str(row["original_source_sha256"]),
                    created_at=datetime(2026, 9, 10, tzinfo=UTC),
                ),
            )
        except Exception as error:
            counters[_safe_parser_reason(error)] += 1
            continue
        inventory = project_source_bound_text_regions(
            document,
            expected_source_sha256=str(row["original_source_sha256"]),
            representation_sha256=str(row["original_source_sha256"]),
        )
        page_regions = tuple(
            region
            for region in inventory.regions
            if region.binding.page_index0 == unit.page_index
        )
        region = _common_region(page_regions, report.mismatches)
        if region is None:
            counters["mismatch_not_uniquely_localized"] += 1
            continue
        x0, y0, x1, y1 = region.binding.bbox1000
        if x1 - x0 < 5 or y1 - y0 < 5 or (x1 - x0) * (y1 - y0) > 250_000:
            counters["region_geometry_outside_freeze"] += 1
            continue
        kinds = tuple(
            sorted(
                {mismatch.kind.value for mismatch in report.mismatches},
                key=lambda kind: RISK_ORDER.get(kind, len(RISK_ORDER)),
            )
        )
        if not kinds or kinds[0] not in RISK_ORDER:
            counters["mismatch_kind_outside_freeze"] += 1
            continue
        token_hashes = tuple(
            sorted(
                {
                    _token_hash(mismatch.kind.value, mismatch.token)
                    for mismatch in report.mismatches
                }
            )
        )
        selection_sha = "sha256:" + hashlib.sha256(
            f"{unit.case_key}\x1f{region.binding.region_id}".encode()
        ).hexdigest()
        candidates.append(
            {
                "sample_id": row["sample_id"],
                "case_key": unit.case_key,
                "unit_key": unit.unit_key,
                "source_relative_path": str(relative).replace("\\", "/"),
                "source_sha256": row["original_source_sha256"],
                "page_index0": unit.page_index,
                "region_id": region.binding.region_id,
                "block_id": region.block_id,
                "bbox1000": region.binding.bbox1000,
                "witness_sha256": region.witness.observation.output_sha256,
                "mismatch_count": len(report.mismatches),
                "mismatch_kinds": kinds,
                "critical_token_hashes": token_hashes,
                "selection_sha256": selection_sha,
                "primary_model": PRIMARY,
            }
        )
        counters["uniquely_localized"] += 1

    ordered = sorted(candidates, key=lambda row: str(row["selection_sha256"]))
    selected: list[dict[str, object]] = []
    selected_keys: set[str] = set()
    for kind in KIND_ORDER:
        bucket = [row for row in ordered if _primary_kind(row) == kind]
        for row in bucket[:MAX_PER_KIND]:
            key = str(row["case_key"])
            if key not in selected_keys:
                selected.append(row)
                selected_keys.add(key)
    for row in ordered:
        if len(selected) >= MAX_TARGETS:
            break
        key = str(row["case_key"])
        if key not in selected_keys:
            selected.append(row)
            selected_keys.add(key)
    selected = sorted(selected[:MAX_TARGETS], key=lambda row: str(row["selection_sha256"]))

    output = args.output.resolve()
    if output.exists() or output.parent != ROOT / ".chatgpt2codex":
        raise ValueError("REGION_SELECTION_OUTPUT_MUST_BE_NEW_SCRATCH_DIRECTORY")
    output.mkdir()
    targets_path = output / "TARGETS.jsonl"
    with targets_path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in selected:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    result = {
        "denominator": EXPECTED_UNITS,
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "counters": dict(sorted(counters.items())),
        "selected_kind_counts": dict(
            sorted(Counter(_primary_kind(row) for row in selected).items())
        ),
        "targets_sha256": digest(targets_path),
        "hidden_evaluation_visible_to_selector": False,
        "quality_claim": False,
        "gpu_cost_usd": 0,
    }
    (output / "RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-cache", type=Path, required=True)
    parser.add_argument("--native-capture", type=Path, required=True)
    parser.add_argument("--region-inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
