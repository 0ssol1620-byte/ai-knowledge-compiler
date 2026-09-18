"""Command line interface for validating and exporting Arena bundles."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from .protocol import ArenaError, compile_bundle, load_json, load_jsonl, validate_inputs


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m research.model_arena_v1")
    subparsers = root.add_subparsers(dest="command", required=True)
    for name in ("validate", "export", "import"):
        command = subparsers.add_parser(name)
        command.add_argument("--preregistration", type=Path, required=True)
        command.add_argument("--corpus", type=Path, required=True)
        command.add_argument("--runs", type=Path, required=True)
        command.add_argument("--layers", type=Path, required=True)
        command.add_argument("--artifact-root", type=Path, required=name == "import")
        if name in {"export", "import"}:
            command.add_argument("--output", type=Path, required=True)
        if name == "import":
            command.add_argument("--database-url", required=True)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        preregistration = load_json(args.preregistration)
        corpus = load_jsonl(args.corpus)
        runs = load_jsonl(args.runs)
        layers = load_jsonl(args.layers)
        report = validate_inputs(
            preregistration, corpus, runs, layers, artifact_root=args.artifact_root
        )
        if args.command == "validate":
            print(json.dumps(report.as_dict(), sort_keys=True, ensure_ascii=False, indent=2))
            return 0 if report.valid else 2
        import_summary = None
        if args.command == "import":
            from .persistence import persist_completed_bundle

            import_summary = asyncio.run(
                persist_completed_bundle(
                    database_url=args.database_url,
                    preregistration_path=args.preregistration,
                    corpus_path=args.corpus,
                    runs_path=args.runs,
                    layers_path=args.layers,
                    artifact_root=args.artifact_root,
                )
            )
        manifest = compile_bundle(
            preregistration,
            corpus,
            runs,
            layers,
            args.output,
            artifact_root=args.artifact_root,
        )
        output: object = manifest
        if import_summary is not None:
            output = {"manifest": manifest, "persistence": import_summary.as_dict()}
        print(json.dumps(output, sort_keys=True, ensure_ascii=False, indent=2))
        return 0 if manifest["release_state"] != "WITHHELD" else 3
    except (ArenaError, OSError, RuntimeError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": "tavonel.arena.cli_error.v1", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
