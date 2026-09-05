"""``python -m arena.reports build --out reports/ [--evidence]`` (ARENA_CONTRACT E3)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from arena.reports.build import build_reports
from arena.reports.paths import SourcePaths


def _build(args: argparse.Namespace) -> int:
    # The campaign root is always the parent of the reports directory the
    # caller names, so ``--out reports/`` run from the namespace root and
    # ``--out <root>/reports`` both resolve to the same source root.
    out_path = Path(args.out).resolve()
    source_root = SourcePaths(root=out_path.parent)
    result = build_reports(
        source_root=source_root,
        out_dir_name=out_path.name,
        with_evidence=args.evidence,
    )
    print(f"wrote {len(result.reports_written)} report file(s) under {out_path}", file=sys.stderr)
    if args.evidence:
        print(
            f"wrote {len(result.evidence_written)} evidence file(s); "
            f"{sum(1 for i in result.dod_checklist if i.satisfied)}/"
            f"{len(result.dod_checklist)} DoD checklist items satisfied",
            file=sys.stderr,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m arena.reports")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="generate every MP section 29 report file")
    build_parser.add_argument("--out", default="reports", help="output reports/ directory")
    build_parser.add_argument(
        "--evidence", action="store_true", help="also write the evidence/ bundle"
    )
    build_parser.set_defaults(func=_build)

    args = parser.parse_args(argv)
    func = args.func
    return int(func(args))


__all__ = ["main"]
