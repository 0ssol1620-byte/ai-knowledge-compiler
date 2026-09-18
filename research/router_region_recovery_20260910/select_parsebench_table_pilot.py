"""Select GT-blind source-bound ParseBench table recovery targets."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from akc_cir.critical_tokens import verify_critical_tokens
from akc_native_parsers.models import ParseContext
from akc_native_parsers.pdf_parser import parse_pdf_to_cir
from akc_router.region_recovery import NativeTextRegion, project_source_bound_text_regions

ROOT = Path(__file__).resolve().parents[2]
REPLAY = ROOT / "research/router_replay_20260908"
if str(REPLAY) not in sys.path:
    sys.path.insert(0, str(REPLAY))

import features as F  # type: ignore[import-not-found]  # noqa: E402

EXPECTED_INVENTORY = (
    "sha256:8893428d6d26824491027a8a4972cf2fe2fdb2fcd3e1dccc19fec8e1ae1293c4"
)
EXPECTED_UNITS = 503
PRIMARY = "mineru_vlm"
KIND_ORDER = ("sign", "currency", "date", "unit", "number")
KIND_RANK = {kind: index for index, kind in enumerate(KIND_ORDER)}
MAX_MISMATCHES = 16
MAX_PER_KIND = 8
MAX_TARGETS = 32


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def token_hash(kind: str, token: str) -> str:
    return "sha256:" + hashlib.sha256(f"{kind}\x1f{token}".encode()).hexdigest()


def row_kind(row: dict[str, object]) -> str:
    kinds = row.get("mismatch_kinds")
    if not isinstance(kinds, tuple) or not kinds or not isinstance(kinds[0], str):
        raise ValueError("PARSEBENCH_TABLE_CANDIDATE_KIND_INVALID")
    return kinds[0]


def row_observations(row: dict[str, object]) -> int:
    value = row.get("source_critical_token_observations")
    if type(value) is not int:
        raise ValueError("PARSEBENCH_TABLE_CANDIDATE_OBSERVATIONS_INVALID")
    return value


def region_tokens(region: NativeTextRegion) -> Counter[tuple[str, str]]:
    report = verify_critical_tokens(region.witness.observation.text, "")
    return Counter(
        {
            (mismatch.kind.value, mismatch.token): mismatch.source_count
            for mismatch in report.mismatches
            if mismatch.source_count > 0
        }
    )


def common_region(
    regions: tuple[NativeTextRegion, ...], mismatches: tuple[Any, ...]
) -> NativeTextRegion | None:
    by_token: dict[tuple[str, str], set[str]] = defaultdict(set)
    by_id = {region.binding.region_id: region for region in regions}
    for region in regions:
        for token in region_tokens(region):
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


def run(args: argparse.Namespace) -> None:
    arena = args.arena.resolve(strict=True)
    sources = args.sources.resolve(strict=True)
    inventory_path = args.inventory.resolve(strict=True)
    if digest(inventory_path) != EXPECTED_INVENTORY:
        raise ValueError("PARSEBENCH_TABLE_INVENTORY_MISMATCH")
    inventory_rows = [
        json.loads(line) for line in inventory_path.read_text(encoding="utf-8").splitlines()
    ]
    if len(inventory_rows) != EXPECTED_UNITS:
        raise ValueError("PARSEBENCH_TABLE_INVENTORY_DENOMINATOR_MISMATCH")
    available = {
        str(row["case_key"]): row
        for row in inventory_rows
        if row.get("status") == "source_regions_available"
    }

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
    units, texts = F.load_or_build_units(arena, "parsebench", models, args.replay_cache)
    units_by_case = {unit.case_key: unit for unit in units}
    manifest = {str(row["case_key"]): row for row in F.load_manifest(arena, "parsebench")}

    counters: Counter[str] = Counter()
    candidates: list[dict[str, object]] = []
    for case_key, _captured in sorted(available.items()):
        counters["source_region_pages"] += 1
        unit = units_by_case.get(case_key)
        row = manifest.get(case_key)
        if unit is None or row is None or not unit.outputs[PRIMARY].present:
            counters["primary_unavailable"] += 1
            continue
        primary_text = texts.get((PRIMARY, unit.unit_key))
        if primary_text is None:
            counters["primary_text_unavailable"] += 1
            continue
        relative = Path(str(row["original_source_relative_path"]))
        source = (sources / "parsebench" / relative).resolve(strict=True)
        if not source.is_relative_to(sources / "parsebench"):
            raise ValueError("PARSEBENCH_TABLE_SOURCE_PATH_ESCAPE")
        data = source.read_bytes()
        if digest_bytes(data) != row["original_source_sha256"]:
            raise ValueError("PARSEBENCH_TABLE_SOURCE_HASH_MISMATCH")
        document = parse_pdf_to_cir(
            filename=source.name,
            declared_mime="application/pdf",
            data=data,
            max_pages=128,
            context=ParseContext(
                tenant_id="parsebench-table-selector-development",
                document_id="table-" + hashlib.sha256(case_key.encode()).hexdigest()[:24],
                document_version_id=str(row["original_source_sha256"]),
                created_at=datetime(2026, 9, 10, tzinfo=UTC),
            ),
        )
        region_inventory = project_source_bound_text_regions(
            document,
            expected_source_sha256=str(row["original_source_sha256"]),
            representation_sha256=str(row["original_source_sha256"]),
        )
        if not region_inventory.complete:
            counters["incomplete_native_inventory"] += 1
            continue
        page_regions = tuple(
            region
            for region in region_inventory.regions
            if region.binding.page_index0 == unit.page_index
        )
        native_text = "\n".join(
            region.witness.observation.text for region in page_regions
        )
        if len(native_text) < 100:
            counters["native_text_too_short"] += 1
            continue
        report = verify_critical_tokens(native_text, primary_text)
        if not report.mismatches:
            counters["primary_token_pass"] += 1
            continue
        if len(report.mismatches) > MAX_MISMATCHES:
            counters["too_many_mismatches"] += 1
            continue
        region = common_region(page_regions, report.mismatches)
        if region is None:
            counters["mismatch_not_uniquely_localized"] += 1
            continue
        x0, y0, x1, y1 = region.binding.bbox1000
        if (
            x1 - x0 < 5
            or y1 - y0 < 5
            or (x1 - x0) * (y1 - y0) > 300_000
            or y0 < 70
            or y1 > 970
        ):
            counters["region_geometry_outside_freeze"] += 1
            continue
        observations = sum(region_tokens(region).values())
        if observations < 2:
            counters["region_token_density_too_low"] += 1
            continue
        kinds = tuple(
            sorted(
                {mismatch.kind.value for mismatch in report.mismatches},
                key=lambda kind: KIND_RANK.get(kind, len(KIND_RANK)),
            )
        )
        if not kinds or kinds[0] not in KIND_RANK:
            counters["mismatch_kind_outside_freeze"] += 1
            continue
        hashes = tuple(
            sorted({token_hash(item.kind.value, item.token) for item in report.mismatches})
        )
        selection = "sha256:" + hashlib.sha256(
            f"{case_key}\x1f{region.binding.region_id}".encode()
        ).hexdigest()
        candidates.append(
            {
                "sample_id": row["sample_id"],
                "case_key": case_key,
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
                "critical_token_hashes": hashes,
                "source_critical_token_observations": observations,
                "selection_sha256": selection,
                "primary_model": PRIMARY,
            }
        )
        counters["eligible_candidates"] += 1

    ordered = sorted(
        candidates,
        key=lambda row: (
            KIND_RANK[row_kind(row)],
            -row_observations(row),
            str(row["selection_sha256"]),
        ),
    )
    selected: list[dict[str, object]] = []
    selected_keys: set[str] = set()
    for kind in KIND_ORDER:
        bucket = [row for row in ordered if row_kind(row) == kind]
        for row in bucket[:MAX_PER_KIND]:
            selected.append(row)
            selected_keys.add(str(row["case_key"]))
    for row in ordered:
        if len(selected) >= MAX_TARGETS:
            break
        if str(row["case_key"]) not in selected_keys:
            selected.append(row)
            selected_keys.add(str(row["case_key"]))
    selected = selected[:MAX_TARGETS]

    output = args.output.resolve()
    if output.exists():
        raise ValueError("PARSEBENCH_TABLE_SELECTION_OUTPUT_MUST_BE_NEW")
    output.mkdir(parents=True)
    targets_path = output / "TARGETS.jsonl"
    with targets_path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in selected:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    result = {
        "units": EXPECTED_UNITS,
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "counters": dict(sorted(counters.items())),
        "selected_kind_counts": dict(
            sorted(Counter(row_kind(row) for row in selected).items())
        ),
        "targets_sha256": digest(targets_path),
        "hidden_table_truth_visible_to_selector": False,
        "text_disclosed": False,
        "quality_claim": False,
        "gpu_cost_usd": 0,
    }
    (output / "RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--replay-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
