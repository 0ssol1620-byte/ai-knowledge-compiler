"""CLI smoke entrypoint for deterministic exports."""

from __future__ import annotations

import argparse
from pathlib import Path

from akc_worker_export.worker import compile_markdown_zip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    files = {
        str(path.relative_to(args.source)): path.read_text(encoding="utf-8")
        for path in args.source.rglob("*.md")
        if path.is_file()
    }
    payload, digest = compile_markdown_zip(files)
    args.target.write_bytes(payload)
    print(digest)


if __name__ == "__main__":
    main()
