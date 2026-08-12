"""Create a canonical byte-level manifest for a model artifact directory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument(
        "--exclude-prefix",
        action="append",
        default=[],
        help="Root-relative POSIX path prefix to exclude; may be repeated.",
    )
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            relative_path = path.relative_to(root).as_posix()
            if any(
                relative_path == prefix.rstrip("/")
                or relative_path.startswith(f"{prefix.rstrip('/')}/")
                for prefix in args.exclude_prefix
            ):
                continue
            files.append(
                {
                    "path": relative_path,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    manifest = {
        "schema_version": "1.0.0",
        "identity": args.identity,
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "files": files,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    payload = encoded + b"\n"
    args.output.write_bytes(payload)
    print(
        json.dumps(
            {
                "path": str(args.output),
                "sha256": f"sha256:{hashlib.sha256(payload).hexdigest()}",
                "file_count": manifest["file_count"],
                "total_bytes": manifest["total_bytes"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
