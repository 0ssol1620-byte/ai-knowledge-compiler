"""Build the truth-free development overlap inventory for the mixed holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .preflight_mixed_holdout import digest, load_jsonl

SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
PAGE_SUFFIX = re.compile(
    r"(?i)(?:[_-](?:pg|page)[_-]?\d+|[._-]p\d+)$"
)


def _require_sha(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(f"{field}:SHA256_REQUIRED")
    return value


def _family_id(benchmark: object, relative_path: object) -> str:
    if not isinstance(benchmark, str) or not benchmark.strip():
        raise ValueError("ARENA_BENCHMARK_REQUIRED")
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("ARENA_SOURCE_PATH_REQUIRED")
    normalized = relative_path.replace("\\", "/").strip().lower()
    path = Path(normalized)
    stem = PAGE_SUFFIX.sub("", path.stem)
    family_key = f"{benchmark.strip().lower()}:{path.parent.as_posix()}:{stem}"
    return "development:arena:" + hashlib.sha256(family_key.encode("utf-8")).hexdigest()


def build_inventory(
    *, arena_manifest: Path, sec_filings: Path, output_path: Path
) -> Mapping[str, Any]:
    arena_rows = load_jsonl(arena_manifest)
    sec_rows = load_jsonl(sec_filings)
    hashes: set[str] = set()
    families: set[str] = set()
    for index, row in enumerate(arena_rows):
        hashes.add(
            _require_sha(row.get("original_source_sha256"), field=f"ARENA_{index}_SOURCE")
        )
        hashes.add(_require_sha(row.get("input_png_sha256"), field=f"ARENA_{index}_INPUT"))
        families.add(_family_id(row.get("benchmark"), row.get("original_source_relative_path")))

    for index, row in enumerate(sec_rows):
        hashes.add(
            _require_sha(row.get("filing_html_sha256"), field=f"SEC_{index}_FILING")
        )
        hashes.add(
            _require_sha(row.get("submissions_sha256"), field=f"SEC_{index}_SUBMISSIONS")
        )
        accession = row.get("accession")
        cik = row.get("cik")
        if not isinstance(accession, str) or not accession:
            raise ValueError(f"SEC_{index}_ACCESSION_REQUIRED")
        if not isinstance(cik, str) or not cik:
            raise ValueError(f"SEC_{index}_CIK_REQUIRED")
        families.add(f"development:sec:filing:{accession}")
        families.add(f"development:sec:submissions:{cik}")

    inventory: Mapping[str, Any] = {
        "schema": "tavonel.router_development_inventory.v1",
        "benchmark_id": "TAVONEL-ROUTER-MIXED-SOURCE-HOLDOUT-20260910-V1",
        "state": "FROZEN_BEFORE_HOLDOUT_EXECUTION",
        "source_artifacts": [
            {
                "kind": "spent_arena_source_manifest",
                "sha256": digest(arena_manifest.read_bytes()),
                "rows": len(arena_rows),
            },
            {
                "kind": "spent_sec_source_fact_filings",
                "sha256": digest(sec_filings.read_bytes()),
                "rows": len(sec_rows),
            },
        ],
        "family_derivation": (
            "arena benchmark plus normalized original source path with terminal page suffix "
            "removed; SEC accession and submissions CIK"
        ),
        "source_sha256": sorted(hashes),
        "source_family_ids": sorted(families),
        "truth_accessed": False,
    }
    output_path.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return inventory


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arena-manifest", type=Path, required=True)
    parser.add_argument("--sec-filings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    inventory = build_inventory(
        arena_manifest=args.arena_manifest,
        sec_filings=args.sec_filings,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "source_hashes": len(inventory["source_sha256"]),
                "source_families": len(inventory["source_family_ids"]),
                "truth_accessed": False,
                "output_sha256": digest(args.output.read_bytes()),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
