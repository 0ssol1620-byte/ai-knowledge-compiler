#!/usr/bin/env python3
"""Build the exact three-arm V2 context artifact from typed source records."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common import canonical_sha, sha_file
from gpu_successor_v2_prompt_schema import ARMS

SOURCE_SCHEMA = "tavonel.v2.gpu_successor_context_sources.v1"
OUTPUT_SCHEMA = "tavonel.v2.gpu_successor_context_artifact.v2"
ARM_SEMANTICS = {
    "CURRENT_TYPED": ("current", "typed"),
    "STALE_TYPED": ("stale", "typed"),
    "CURRENT_TEXT_ONLY": ("current", "text_only"),
}


class ContextBuildRefused(RuntimeError):
    """Context sources did not prove the prospective arm semantics."""


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContextBuildRefused(f"{label} is unreadable") from error
    if not isinstance(body, dict):
        raise ContextBuildRefused(f"{label} must be a JSON object")
    return body


def _text_sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def build(*, manifest_path: Path, source_path: Path) -> dict[str, Any]:
    manifest, source = (
        _load(manifest_path, "V2 successor manifest"),
        _load(source_path, "V2 context source authority"),
    )
    manifest_sha = sha_file(manifest_path)
    sfir4 = manifest.get("source_sfir4_acceptance")
    if not isinstance(sfir4, dict) or not sfir4.get("sha256"):
        raise ContextBuildRefused("manifest has no exact SFIR4 acceptance binding")
    if source.get("schema") != SOURCE_SCHEMA:
        raise ContextBuildRefused("context source schema drifted")
    if source.get("successor_manifest_sha256") != manifest_sha:
        raise ContextBuildRefused("context sources bind another successor manifest")
    if source.get("sfir4_acceptance_sha256") != sfir4["sha256"]:
        raise ContextBuildRefused("context sources bind another SFIR4 acceptance")
    facts = manifest.get("facts")
    records = source.get("context_by_fact")
    if not isinstance(facts, list) or len(facts) != 450 or not isinstance(records, dict):
        raise ContextBuildRefused("exactly 450 manifest facts and context records are required")
    expected = {fact.get("fact_id") for fact in facts if isinstance(fact, dict)}
    if len(expected) != 450 or set(records) != expected:
        raise ContextBuildRefused("context source fact ids do not equal the manifest")
    output: dict[str, dict[str, list[dict[str, str]]]] = {}
    for fact_id in sorted(expected):
        arms = records[fact_id]
        if not isinstance(arms, dict) or set(arms) != set(ARMS):
            raise ContextBuildRefused(f"{fact_id}: all and only three arms are required")
        built_arms: dict[str, list[dict[str, str]]] = {}
        for arm in ARMS:
            rows = arms[arm]
            if not isinstance(rows, list) or not rows:
                raise ContextBuildRefused(f"{fact_id}/{arm}: non-empty source atoms required")
            atoms = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ContextBuildRefused(f"{fact_id}/{arm}: source atom is not an object")
                if (row.get("currency"), row.get("representation_mode")) != ARM_SEMANTICS[arm]:
                    raise ContextBuildRefused(f"{fact_id}/{arm}: prospective arm semantics drifted")
                text, path, atom_id = row.get("text"), row.get("path"), row.get("atom_id")
                if not all(isinstance(value, str) and value for value in (text, path, atom_id)):
                    raise ContextBuildRefused(f"{fact_id}/{arm}: atom identity is incomplete")
                if row.get("text_sha256") != _text_sha(text):
                    raise ContextBuildRefused(f"{fact_id}/{arm}: atom text digest drifted")
                atoms.append(
                    {
                        "atom_id": atom_id,
                        "path": path,
                        "text": text,
                        "text_sha256": row["text_sha256"],
                    }
                )
            built_arms[arm] = atoms
        output[fact_id] = built_arms
    return {
        "schema": OUTPUT_SCHEMA,
        "successor_manifest_sha256": manifest_sha,
        "sfir4_acceptance_sha256": sfir4["sha256"],
        "facts_digest": manifest.get("facts_digest"),
        "source_artifact_sha256": sha_file(source_path),
        "context_by_fact": output,
        "contexts_digest": canonical_sha(output),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    body = build(manifest_path=args.manifest, source_path=args.sources)
    args.output.write_text(json.dumps(body, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ARM_SEMANTICS", "OUTPUT_SCHEMA", "SOURCE_SCHEMA", "ContextBuildRefused", "build"]
