"""Prompt / schema / config / case freeze, before any measurement (programme DoD #14).

A freeze file is written once and never overwritten. Changing a prompt, a
schema, the sampling config or a case file after a freeze means a new freeze
version -- and the runner refuses to measure against a freeze whose hashes no
longer match the bytes on disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from arena.provider.safety import sha256_file, utc_now_iso, write_json_atomic

from karena import CAMPAIGN_ID, NAMESPACE_ROOT
from karena.corpus import SPLITS

__all__ = ["FreezeError", "freeze", "frozen_paths", "verify_frozen"]

FREEZE_DIR: Final = NAMESPACE_ROOT / "freeze"


class FreezeError(RuntimeError):
    pass


def frozen_paths() -> list[Path]:
    paths = sorted((NAMESPACE_ROOT / "prompt_registry").glob("*.txt"))
    paths += sorted((NAMESPACE_ROOT / "schemas").glob("*.json"))
    paths.append(NAMESPACE_ROOT / "config" / "tasks.json")
    paths += [
        NAMESPACE_ROOT / "cases" / f"{task}.{split}.jsonl"
        for task in ("doc_type", "schema_induction", "typed_extraction", "grounded_answer")
        for split in SPLITS
    ]
    return paths


def _relative(path: Path) -> str:
    return path.relative_to(NAMESPACE_ROOT).as_posix()


def freeze(version: str) -> Path:
    target = FREEZE_DIR / f"FROZEN_{version}.json"
    if target.exists():
        raise FreezeError(
            f"{target.name} exists; a freeze is never overwritten -- use a new version"
        )
    missing = [_relative(p) for p in frozen_paths() if not p.is_file()]
    if missing:
        raise FreezeError(f"cannot freeze, missing: {missing}")
    document: dict[str, Any] = {
        "schema": "tavonel.karena.freeze.v1",
        "campaign_id": CAMPAIGN_ID,
        "version": version,
        "frozen_at": utc_now_iso(),
        "files": {_relative(p): sha256_file(p) for p in frozen_paths()},
    }
    write_json_atomic(target, document, context="freeze manifest")
    return target


def verify_frozen(version: str) -> dict[str, Any]:
    target = FREEZE_DIR / f"FROZEN_{version}.json"
    if not target.is_file():
        raise FreezeError(f"no freeze {target.name}: freeze before measuring")
    document: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    problems = []
    for relative, recorded in document["files"].items():
        path = NAMESPACE_ROOT / relative
        if not path.is_file():
            problems.append(f"{relative}: missing")
        elif sha256_file(path) != recorded:
            problems.append(f"{relative}: bytes changed since the freeze")
    if problems:
        raise FreezeError("freeze violated: " + "; ".join(problems))
    document["freeze_file_sha256"] = sha256_file(target)
    return document
