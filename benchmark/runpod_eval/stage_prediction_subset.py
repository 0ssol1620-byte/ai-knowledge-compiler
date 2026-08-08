#!/usr/bin/env python3
"""Stage exact Markdown prediction subsets from a frozen inference manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def case_ids(manifest: object) -> list[str]:
    if not isinstance(manifest, dict):
        raise ValueError("inference manifest must be an object")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or int(manifest.get("case_count", -1)) != len(cases):
        raise ValueError("inference manifest case count is invalid")
    values: list[str] = []
    for case in cases:
        filename = case.get("filename") if isinstance(case, dict) else None
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError("every case requires a basename filename")
        values.append(Path(filename).stem)
    if len(values) != len(set(values)):
        raise ValueError("duplicate case ids are forbidden")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions-root", type=Path, required=True)
    parser.add_argument("--inference-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("output directory already exists")
    ids = case_ids(json.loads(args.inference_manifest.read_text(encoding="utf-8")))

    records = []
    for repeat in range(1, args.repeats + 1):
        source = args.predictions_root / f"markdown-repeat-{repeat}"
        target = args.output / f"markdown-repeat-{repeat}"
        target.mkdir(parents=True)
        for case_id in ids:
            source_path = source / f"{case_id}.md"
            if not source_path.is_file() or source_path.is_symlink():
                raise FileNotFoundError(f"missing regular prediction: {source_path}")
            target_path = target / source_path.name
            shutil.copy2(source_path, target_path)
            records.append(
                {
                    "repeat_index": repeat,
                    "case_id": case_id,
                    "sha256": sha256_file(target_path),
                }
            )
    receipt = {
        "schema_version": "1.0.0",
        "case_count": len(ids),
        "repeat_count": args.repeats,
        "records": records,
    }
    (args.output / "subset-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"case_count": len(ids), "repeat_count": args.repeats}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
