"""``python -m karena <command>`` from the namespace root.

Nothing spends money without --execute.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from arena.provider.safety import write_json_atomic

from karena import NAMESPACE_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="karena")
    sub = parser.add_subparsers(dest="command", required=True)
    gold = sub.add_parser("gold", help="fetch public gold and build the case sets")
    gold.add_argument("--offline", action="store_true", help="use the fetch cache only")
    sub.add_parser("cases", help="rebuild case sets from gold/ without fetching")
    sub.add_parser("registry", help="re-resolve candidate rows from Hugging Face")
    for name in ("freeze", "verify"):
        command = sub.add_parser(name)
        command.add_argument("--version", default="v1")
    stage0 = sub.add_parser("stage0", help="Stage 0 smoke for one candidate")
    stage0.add_argument("--model", required=True)
    stage0.add_argument("--execute", action="store_true")
    stage0.add_argument("--allow-dirty", action="store_true")
    stage0.add_argument("--budget", type=float, default=60.0)
    stage0.add_argument("--cloud", default="SECURE", choices=("SECURE", "COMMUNITY"))
    score = sub.add_parser("score", help="re-score a run directory offline")
    score.add_argument("run_dir", type=Path)
    sub.add_parser("table-smoke", help="product-DPI raster + official TEDS self-check")
    args = parser.parse_args(argv)

    if args.command in {"gold", "cases"}:
        from karena.gold import build

        config = build.BuildConfig()
        if args.command == "gold":
            from karena.gold.fetch import Fetcher
            from karena.gold.sec import sec_user_agent

            fetcher = Fetcher(
                NAMESPACE_ROOT / "inputs",
                headers={"User-Agent": sec_user_agent(), "Accept-Encoding": "gzip, deflate"},
                min_interval_seconds=0.15,
                offline=args.offline,
            )
            try:
                build.build_gold(fetcher, config)
            finally:
                fetcher.close()
        print(json.dumps(build.build_cases(config), indent=2))
    elif args.command == "registry":
        from karena.registry import refresh_registry

        print(json.dumps([r["registry_id"] for r in refresh_registry()["rows"]]))
    elif args.command == "freeze":
        from karena.freeze import freeze

        print(freeze(args.version))
    elif args.command == "verify":
        from karena.freeze import verify_frozen

        print(verify_frozen(args.version)["freeze_file_sha256"])
    elif args.command == "stage0":
        from karena.stage0 import run_stage0

        print(
            run_stage0(
                args.model,
                execute=args.execute,
                budget_usd=args.budget,
                cloud=args.cloud,
                allow_dirty=args.allow_dirty,
            )
        )
    elif args.command == "score":
        from karena.stage0 import score_run

        summary = score_run(args.run_dir)
        write_json_atomic(args.run_dir / "rescored.json", summary, context="rescore")
        print(json.dumps(summary, indent=2, default=str)[:4000])
    elif args.command == "table-smoke":
        from karena.table_track import table_smoke

        print(json.dumps(table_smoke(), indent=2))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
