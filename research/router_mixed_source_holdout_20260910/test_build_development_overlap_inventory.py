from __future__ import annotations

import json
from pathlib import Path

from .build_development_overlap_inventory import build_inventory


def _jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def test_build_inventory_deduplicates_pages_and_hashes(tmp_path: Path) -> None:
    arena = tmp_path / "arena.jsonl"
    sec = tmp_path / "sec.jsonl"
    output = tmp_path / "development.json"
    _jsonl(
        arena,
        [
            {
                "benchmark": "bench",
                "original_source_relative_path": "docs/report_pg1.pdf",
                "original_source_sha256": "sha256:" + "1" * 64,
                "input_png_sha256": "sha256:" + "2" * 64,
            },
            {
                "benchmark": "bench",
                "original_source_relative_path": "docs/report_pg2.pdf",
                "original_source_sha256": "sha256:" + "1" * 64,
                "input_png_sha256": "sha256:" + "3" * 64,
            },
        ],
    )
    _jsonl(
        sec,
        [
            {
                "filing_html_sha256": "sha256:" + "4" * 64,
                "submissions_sha256": "sha256:" + "5" * 64,
                "accession": "0001-26-000001",
                "cik": "0000000001",
            }
        ],
    )
    inventory = build_inventory(
        arena_manifest=arena, sec_filings=sec, output_path=output
    )
    assert len(inventory["source_sha256"]) == 5
    assert len(inventory["source_family_ids"]) == 3
    assert inventory["truth_accessed"] is False
