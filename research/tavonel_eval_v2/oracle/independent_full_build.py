#!/usr/bin/env python3
"""Independent full rebuild. Standard library only, by rule and by check.

This file is the other half of the equivalence comparison and it is written to
share nothing with the selective path except the specification both implement:

* it imports no project module -- not ``akc_cir``, not the compiler, not the
  shared ``tools/common.py``;
* it installs a meta-path finder that raises if anything tries to, so the rule
  is enforced at runtime rather than trusted;
* it takes the AFTER canonical document and nothing else. No dirty set, no
  recompilation plan, no prior state, no cache directory, no oracle-side
  memoisation between pairs;
* it rebuilds every artifact of the revision from scratch, every time.

Run it as a subprocess with ``-I``. It is not importable as a library from the
selective side: importing it triggers the guard.

The artifact rules below are a deliberate re-implementation of protocol section
4 rather than a shared helper. Where the selective side folds the four kinds
into one pass over a precomputed id list, this one derives each kind separately
from the document, so a mistake in one is unlikely to be the same mistake in the
other.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

BLOCKED_PREFIXES = ("akc_cir", "tavonel_eval_v2", "selective_build", "common", "compare_states")


class SelectivePathBlocked(ImportError):
    """Raised when the oracle process reaches for the implementation it audits."""


class ImportGuard:
    """A sys.meta_path finder that refuses the selective implementation."""

    triggered: list[str] = []

    def find_module(self, fullname: str, path: Any = None) -> None:  # legacy API
        self.find_spec(fullname, path)
        return None

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        root = fullname.split(".")[0]
        if root in BLOCKED_PREFIXES:
            ImportGuard.triggered.append(fullname)
            raise SelectivePathBlocked(
                "the independent oracle may not import " + fullname
            )
        return None


sys.meta_path.insert(0, ImportGuard())


def digest(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def unit_identity(source: str, path_parts: list[str]) -> str:
    material = "%s\n%s" % (source, "/".join(path_parts))
    return "u:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def document_identity(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def bucket_index(identity: str) -> int:
    head = hashlib.sha256(identity.encode("utf-8")).hexdigest()[0:8]
    return int(head, 16) % 4


def section_artifacts(revision: dict[str, Any]) -> dict[str, str]:
    source = revision["source_id"]
    built: dict[str, str] = {}
    for unit in revision["units"]:
        identity = unit_identity(source, unit["explicit_path"])
        built["section:%s" % identity] = digest(
            {"logical_id": identity, "semantic_text": unit["text"]}
        )
    return built


def index_artifact(revision: dict[str, Any]) -> dict[str, str]:
    source = revision["source_id"]
    key = document_identity(source)
    reading_order = [
        unit_identity(source, unit["explicit_path"]) for unit in revision["units"]
    ]
    return {
        "document-index:%s" % key: digest({"doc_key": key, "members": reading_order})
    }


def structure_artifact(revision: dict[str, Any]) -> dict[str, str]:
    key = document_identity(revision["source_id"])
    # Read from the document's declared reading order, not from the unit list,
    # so a disagreement between the two would surface as a divergence instead of
    # being hidden by rebuilding both sides from the same field.
    paths = list(revision["structure"]["order"])
    return {"structure-map:%s" % key: digest({"doc_key": key, "paths": paths})}


def bucket_artifacts(revision: dict[str, Any]) -> dict[str, str]:
    source = revision["source_id"]
    key = document_identity(source)
    identities = sorted(
        {unit_identity(source, unit["explicit_path"]) for unit in revision["units"]}
    )
    grouped: dict[int, list[str]] = {}
    for identity in identities:
        grouped.setdefault(bucket_index(identity), []).append(identity)
    built: dict[str, str] = {}
    for bucket in sorted(grouped):
        built["topic-bucket:%s:%d" % (key, bucket)] = digest(
            {"doc_key": key, "bucket": bucket, "members": sorted(grouped[bucket])}
        )
    return built


def full_rebuild(revision: dict[str, Any]) -> dict[str, str]:
    state: dict[str, str] = {}
    for producer in (
        section_artifacts,
        index_artifact,
        structure_artifact,
        bucket_artifacts,
    ):
        for artifact, value in producer(revision).items():
            if artifact in state:
                raise SystemExit("artifact id produced twice: " + artifact)
            state[artifact] = value
    return state


def import_evidence() -> dict[str, Any]:
    """What this process actually loaded, recorded rather than asserted."""
    loaded = sorted({name.split(".")[0] for name in sys.modules})
    non_stdlib = [
        name
        for name in loaded
        if name not in sys.stdlib_module_names and not name.startswith("_")
    ]
    return {
        "pid": os.getpid(),
        "executable": sys.executable,
        "isolated_mode": bool(sys.flags.isolated),
        "flags_isolated": sys.flags.isolated,
        "argv": sys.argv,
        "sys_path": [str(item) for item in sys.path],
        "cir_python_on_path": any("cir-python" in str(item) for item in sys.path),
        "akc_cir_imported": any(name.startswith("akc_cir") for name in sys.modules),
        "blocked_prefixes": list(BLOCKED_PREFIXES),
        "guard_triggered_on": list(ImportGuard.triggered),
        "top_level_modules_loaded": loaded,
        "non_stdlib_modules_loaded": non_stdlib,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    started = time.perf_counter()
    revision = json.loads(args.after.read_text(encoding="utf-8"))
    state = full_rebuild(revision)
    elapsed = round((time.perf_counter() - started) * 1000, 3)

    result = {
        "source_id": revision["source_id"],
        "engine": "independent_full_rebuild",
        "version_id": revision["version_id"],
        "input_path": str(args.after),
        "input_sha256": "sha256:"
        + hashlib.sha256(args.after.read_bytes()).hexdigest(),
        "artifact_inventory": sorted(state),
        "state": state,
        "state_hash": digest(state),
        "duration_ms": elapsed,
        "independence": import_evidence(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"state_hash": result["state_hash"], "pid": os.getpid()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
