#!/usr/bin/env python3
"""P0c independent full rebuild. Standard library only.

Implements the artifact specification from the P0c protocol text, not from the
selective engine's code. It imports no project module, installs a meta-path
guard that refuses the implementation it audits, and receives the AFTER
canonical document and nothing else -- no fingerprints, no sensitivity records,
no change facts, no plan, no prior state.

One deliberate consequence is worth naming. The protocol specifies the SEMANTIC
projection in prose: NFKC, casefold, punctuation folded to space, whitespace
collapsed. This file re-derives it from that prose rather than importing
``akc_cir.identity.normalize_text_for_identity``. If the two implementations
disagree, the ``semantic-summary`` artifacts diverge and the finding is that the
prose was not precise enough to re-implement -- which is a real result about the
specification, and is the reason the projection is not simply copied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

BLOCKED_PREFIXES = (
    "akc_cir",
    "facets",
    "selective_build",
    "selective_build_p0b",
    "selective_build_p0c",
    "facet_coverage",
    "tavonel_eval_v2",
    "common",
    "compare_states",
)


class SelectivePathBlocked(ImportError):
    """Raised when the oracle process reaches for the implementation it audits."""


class ImportGuard:
    triggered: list[str] = []

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        if fullname.split(".")[0] in BLOCKED_PREFIXES:
            ImportGuard.triggered.append(fullname)
            raise SelectivePathBlocked("the independent oracle may not import " + fullname)
        return None


sys.meta_path.insert(0, ImportGuard())

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def semantic_projection(text: str) -> str:
    """P0c section 2 / P0b section 3, SEMANTIC, re-derived from the prose."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = _NON_WORD.sub(" ", folded)
    return _SPACES.sub(" ", folded).strip()


def digest(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def unit_identity(source: str, path_parts: list[str]) -> str:
    return "u:" + hashlib.sha256(
        ("%s\n%s" % (source, "/".join(path_parts))).encode("utf-8")
    ).hexdigest()[:24]


def document_identity(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def bucket_index(identity: str) -> int:
    return int(hashlib.sha256(identity.encode("utf-8")).hexdigest()[0:8], 16) % 4


def section_artifacts(revision: dict[str, Any]) -> dict[str, str]:
    source = revision["source_id"]
    return {
        "section:%s" % unit_identity(source, unit["explicit_path"]): digest(
            {
                "logical_id": unit_identity(source, unit["explicit_path"]),
                "text": unit["text"],
            }
        )
        for unit in revision["units"]
    }


def semantic_summary_artifacts(revision: dict[str, Any]) -> dict[str, str]:
    source = revision["source_id"]
    built: dict[str, str] = {}
    for unit in revision["units"]:
        identity = unit_identity(source, unit["explicit_path"])
        built["semantic-summary:%s" % identity] = digest(
            {"logical_id": identity, "semantic_text": semantic_projection(unit["text"])}
        )
    return built


def index_artifact(revision: dict[str, Any]) -> dict[str, str]:
    source = revision["source_id"]
    key = document_identity(source)
    in_order = sorted(revision["units"], key=lambda unit: unit["ordinal"])
    members = [unit_identity(source, unit["explicit_path"]) for unit in in_order]
    return {"document-index:%s" % key: digest({"doc_key": key, "members": members})}


def structure_artifact(revision: dict[str, Any]) -> dict[str, str]:
    key = document_identity(revision["source_id"])
    in_order = sorted(revision["units"], key=lambda unit: unit["ordinal"])
    paths = ["/".join(unit["explicit_path"]) for unit in in_order]
    headings = [unit["heading"] for unit in in_order]
    return {
        "structure-map:%s"
        % key: digest({"doc_key": key, "paths": paths, "headings": headings})
    }


def coverage_probe_artifact(revision: dict[str, Any]) -> dict[str, str]:
    """The declared control artifact, built here as the spec describes it.

    The selective side refuses to give this one a digest, because its builder
    reads a field the projection map does not name. The oracle has no such
    notion -- it rebuilds everything from the after revision -- so it produces a
    value, and the comparator records the artifact as unverifiable on the
    selective side rather than as a mismatch. That asymmetry is the control
    working, not a divergence.
    """
    units = revision["units"]
    if not units or not all("unmapped_probe_field" in unit for unit in units):
        return {}
    key = document_identity(revision["source_id"])
    in_order = sorted(units, key=lambda unit: unit["ordinal"])
    return {
        "coverage-probe:%s"
        % key: digest(
            {
                "doc_key": key,
                "probe_values": [unit["unmapped_probe_field"] for unit in in_order],
            }
        )
    }


def bucket_artifacts(revision: dict[str, Any]) -> dict[str, str]:
    source = revision["source_id"]
    key = document_identity(source)
    grouped: dict[int, list[str]] = {}
    for unit in revision["units"]:
        identity = unit_identity(source, unit["explicit_path"])
        grouped.setdefault(bucket_index(identity), []).append(identity)
    return {
        "topic-bucket:%s:%d" % (key, bucket): digest(
            {"doc_key": key, "bucket": bucket, "members": sorted(set(grouped[bucket]))}
        )
        for bucket in sorted(grouped)
    }


def full_rebuild(revision: dict[str, Any]) -> dict[str, str]:
    state: dict[str, str] = {}
    for producer in (
        section_artifacts,
        semantic_summary_artifacts,
        index_artifact,
        structure_artifact,
        bucket_artifacts,
        coverage_probe_artifact,
    ):
        for artifact, value in producer(revision).items():
            if artifact in state:
                raise SystemExit("artifact id produced twice: " + artifact)
            state[artifact] = value
    return state


def import_evidence() -> dict[str, Any]:
    loaded = sorted({name.split(".")[0] for name in sys.modules})
    return {
        "pid": os.getpid(),
        "executable": sys.executable,
        "isolated_mode": bool(sys.flags.isolated),
        "no_site": bool(sys.flags.no_site),
        "argv": sys.argv,
        "sys_path": [str(item) for item in sys.path],
        "cir_python_on_path": any("cir-python" in str(item) for item in sys.path),
        "akc_cir_imported": any(name.startswith("akc_cir") for name in sys.modules),
        "facets_imported": "facets" in sys.modules,
        "blocked_prefixes": list(BLOCKED_PREFIXES),
        "guard_triggered_on": list(ImportGuard.triggered),
        "non_stdlib_modules_loaded": [
            name
            for name in loaded
            if name not in sys.stdlib_module_names and not name.startswith("_")
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    started = time.perf_counter()
    revision = json.loads(args.after.read_text(encoding="utf-8"))
    state = full_rebuild(revision)
    result = {
        "source_id": revision["source_id"],
        "engine": "independent_full_rebuild_p0c",
        "version_id": revision["version_id"],
        "input_sha256": "sha256:" + hashlib.sha256(args.after.read_bytes()).hexdigest(),
        "artifact_inventory": sorted(state),
        "state": state,
        "state_hash": digest(state),
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "semantic_projection_source": "re-derived from P0c protocol prose",
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
