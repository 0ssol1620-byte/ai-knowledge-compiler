#!/usr/bin/env python3
"""Give the corrected evaluator an identity, and record exactly how it differs.

An evaluator revision is part of every result it produces. The frozen one is
named by its upstream commit; the corrected one is not a commit, so it needs a
content hash of its own and a diff that a reader can check rather than trust.

The hash covers every Python source file under the checkout, in sorted path
order. It deliberately excludes results, logs, caches and assets: those change
per run and would make the identity useless for saying "this is the evaluator
that produced that number".

The diff is emitted in full because it is small and because the whole argument
for re-measuring the holdout rests on it being *only* the removal of a
wall-clock decision -- not a change to any metric, threshold or matching rule.
A reader who does not want to take that on faith can read the diff here.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SKIP_DIRECTORIES = {"result", "logs", "__pycache__", ".git", "assets", "demo_data"}


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def source_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.py")
        if not any(part in SKIP_DIRECTORIES for part in path.relative_to(root).parts)
    )


def source_hash(root: Path) -> tuple[str, dict[str, str]]:
    """Content hash over every Python source file, in sorted path order."""
    per_file: dict[str, str] = {}
    digest = hashlib.sha256()
    for path in source_files(root):
        relative = path.relative_to(root).as_posix()
        body = path.read_bytes()
        per_file[relative] = hashlib.sha256(body).hexdigest()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(body)
        digest.update(b"\0")
    return digest.hexdigest(), per_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--corrected", type=Path, required=True)
    parser.add_argument("--frozen-revision", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    frozen, corrected = args.frozen.resolve(), args.corrected.resolve()
    frozen_hash, frozen_files = source_hash(frozen)
    corrected_hash, corrected_files = source_hash(corrected)

    changed = sorted(
        name
        for name in set(frozen_files) & set(corrected_files)
        if frozen_files[name] != corrected_files[name]
    )
    added = sorted(set(corrected_files) - set(frozen_files))
    removed = sorted(set(frozen_files) - set(corrected_files))

    diffs: dict[str, list[str]] = {}
    for name in changed:
        diffs[name] = list(
            difflib.unified_diff(
                (frozen / name).read_text(encoding="utf-8", errors="replace").splitlines(),
                (corrected / name).read_text(encoding="utf-8", errors="replace").splitlines(),
                fromfile=f"frozen/{name}",
                tofile=f"corrected/{name}",
                lineterm="",
                n=3,
            )
        )

    added_lines = sum(
        1 for lines in diffs.values() for line in lines
        if line.startswith("+") and not line.startswith("+++")
    )
    removed_lines = sum(
        1 for lines in diffs.values() for line in lines
        if line.startswith("-") and not line.startswith("---")
    )

    receipt = {
        "schema": "tavonel.a9-evaluator-version.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "version": args.version,
        "derived_from": {
            "checkout": str(frozen),
            "revision": args.frozen_revision,
            "python_source_sha256": frozen_hash,
        },
        "corrected": {
            "checkout": str(corrected),
            "python_source_sha256": corrected_hash,
        },
        "files_changed": changed,
        "files_added": added,
        "files_removed": removed,
        "lines_added": added_lines,
        "lines_removed": removed_lines,
        "what_the_change_does": (
            "adds an opt-in `deterministic_matching` dataset flag. When set, the "
            "exact matcher runs to completion on every page: the outer "
            "func_timeout wrapper is bypassed and the inner truncation deadline "
            "is disabled, so no wall-clock value can influence which algorithm "
            "scores a page."
        ),
        "what_the_change_does_not_do": [
            "no metric definition is altered",
            "no threshold is altered",
            "no matching rule, cost function or normalisation is altered",
            "no ground truth is altered",
            "the default path is unchanged, so artifacts produced before the "
            "correction remain reproducible under the terms they were produced",
        ],
        "unified_diff": diffs,
        "hash_covers": "every .py file under the checkout, sorted by path",
        "hash_excludes": sorted(SKIP_DIRECTORIES),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)

    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"version            : {args.version}")
    print(f"frozen source hash : {frozen_hash}")
    print(f"corrected hash     : {corrected_hash}")
    print(
        f"files changed      : {len(changed)} "
        f"({added_lines} added, {removed_lines} removed lines)"
    )
    for name in changed:
        print(f"  {name}")
    if added or removed:
        print(f"files added/removed: {len(added)}/{len(removed)}")
    print(f"receipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
