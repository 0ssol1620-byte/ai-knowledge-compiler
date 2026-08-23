"""CLI: ``python -m akc_health_scan <root> --json out.json`` (offline only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import ENGINE_ID, __version__
from .config import HealthScanConfig
from .models import HealthReport
from .scanner import scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="akc_health_scan",
        description=(
            "Local-only Health Scan producing the blueprint §5.2 outputs. "
            "All findings are heuristic; no network/cloud calls."
        ),
    )
    parser.add_argument("root", help="directory to scan")
    parser.add_argument("--json", dest="json_out", default=None, help="write full report JSON here")
    parser.add_argument("--near-duplicate-threshold", type=float, default=None)
    parser.add_argument("--max-near-duplicate-pairs", type=int, default=None)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2
    overrides = {
        key: value
        for key, value in (
            ("near_duplicate_threshold", args.near_duplicate_threshold),
            ("max_near_duplicate_pairs", args.max_near_duplicate_pairs),
        )
        if value is not None
    }
    report: HealthReport = scan(root, HealthScanConfig(**overrides))

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"{ENGINE_ID} v{__version__} - heuristic local scan of {report.root_path}")
    print(f"files discovered      : {report.sources['discovered_files']}")
    print(
        f"duplicates            : {len(report.duplicates['exact_duplicate_clusters'])}"
        f" exact cluster(s), {len(report.duplicates['near_duplicate_pairs'])} near pair(s)"
    )
    print(f"identity collisions   : {len(report.identity_collisions['collisions'])}")
    print(f"conflicting candidates: {len(report.conflicting_candidates['groups'])}")
    print(f"stale references      : {len(report.stale_references['stale'])}")
    print(f"unresolved dates      : {len(report.unresolved_dates['unresolved'])}")
    print(f"sensitive exposure    : {len(report.sensitive_exposure['findings'])}")
    est = report.estimated_compile_work
    print(
        f"compile estimate      : {est['estimated_tokens']:,} tokens,"
        f" {est['estimated_chunks']:,} chunk/call(s)"
    )
    if args.json_out:
        print(f"json written          : {args.json_out}")
    return 0


def main_cli() -> None:
    raise SystemExit(main())
