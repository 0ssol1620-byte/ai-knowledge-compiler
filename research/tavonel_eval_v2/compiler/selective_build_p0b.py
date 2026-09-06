#!/usr/bin/env python3
"""P0b selective side: deterministic identity, facet-typed invalidation.

Two things separate this from the P0 v1 engine beside it, and P0 v1 is not
edited to match:

* identity is explicit-path equality and nothing else. ``diff_documents`` is not
  called, no resolver is constructed, no threshold or tie band exists, and the
  only akc_cir symbol imported is the semantic projection.
* what an artifact is sensitive to is observed while it is built, not declared,
  and an artifact may be carried forward only when the input fingerprint over
  its observed facets is unchanged.

Runs in its own process. It imports neither the oracle nor the P0 v1 engine.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "facets"))

from facets import (  # noqa: E402
    FACETS,
    LEXICAL,
    SEMANTIC,
    STRUCTURAL,
    Recorder,
    RecordingUnitView,
    change_facets,
    project,
)

UNVERIFIABLE = "UNVERIFIABLE_NO_RECORDED_SENSITIVITY"


def digest(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def logical_id(source_id: str, explicit_path: list[str]) -> str:
    material = source_id + "\n" + "/".join(explicit_path)
    return "u:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def doc_key(source_id: str) -> str:
    return hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:16]


def bucket_of(identifier: str) -> int:
    return int(hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:8], 16) % 4


# --- builders. Each one sees units only through the recording view -----------


def build_section(identifier: str, view: RecordingUnitView) -> dict[str, Any]:
    return {"logical_id": identifier, "text": view.text}


def build_semantic_summary(identifier: str, view: RecordingUnitView) -> dict[str, Any]:
    return {"logical_id": identifier, "semantic_text": view.semantic_text}


def build_document_index(key: str, pairs: list[tuple[str, RecordingUnitView]]) -> dict[str, Any]:
    ordered = sorted(pairs, key=lambda item: item[1].ordinal)
    return {"doc_key": key, "members": [identifier for identifier, _ in ordered]}


def build_structure_map(key: str, pairs: list[tuple[str, RecordingUnitView]]) -> dict[str, Any]:
    ordered = sorted(pairs, key=lambda item: item[1].ordinal)
    return {"doc_key": key, "paths": ["/".join(view.explicit_path) for _, view in ordered]}


def build_topic_bucket(
    key: str, bucket: int, pairs: list[tuple[str, RecordingUnitView]]
) -> dict[str, Any]:
    # Membership is the structural fact that these units exist at these paths in
    # this revision, so presence is established by reading the structural facet
    # rather than by inspecting the input list from outside the view.
    members = sorted(
        identifier for identifier, view in pairs if view.explicit_path and bucket_of(identifier) == bucket
    )
    return {"doc_key": key, "bucket": bucket, "members": members}


def plan_of(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Every artifact of one revision, with the units each one reads."""
    source_id = document["source_id"]
    key = doc_key(source_id)
    units = document["units"]
    identified = [(logical_id(source_id, unit["explicit_path"]), unit) for unit in units]

    jobs: list[dict[str, Any]] = []
    for identifier, unit in identified:
        jobs.append(
            {"artifact": "section:" + identifier, "kind": "section", "inputs": [(identifier, unit)]}
        )
        jobs.append(
            {
                "artifact": "semantic-summary:" + identifier,
                "kind": "semantic-summary",
                "inputs": [(identifier, unit)],
            }
        )
    jobs.append(
        {"artifact": "document-index:" + key, "kind": "document-index", "inputs": identified}
    )
    jobs.append(
        {"artifact": "structure-map:" + key, "kind": "structure-map", "inputs": identified}
    )
    for bucket in range(4):
        members = [pair for pair in identified if bucket_of(pair[0]) == bucket]
        if members:
            jobs.append(
                {
                    "artifact": "topic-bucket:" + key + ":" + str(bucket),
                    "kind": "topic-bucket",
                    "bucket": bucket,
                    "inputs": identified,
                }
            )
    return jobs


def execute(job: dict[str, Any], key: str) -> tuple[str, tuple[str, ...]]:
    """Build one artifact and return its digest and its observed sensitivity."""
    recorder = Recorder()
    views = [(identifier, recorder.view(unit)) for identifier, unit in job["inputs"]]
    kind = job["kind"]
    if kind == "section":
        payload = build_section(views[0][0], views[0][1])
    elif kind == "semantic-summary":
        payload = build_semantic_summary(views[0][0], views[0][1])
    elif kind == "document-index":
        payload = build_document_index(key, views)
    elif kind == "structure-map":
        payload = build_structure_map(key, views)
    elif kind == "topic-bucket":
        payload = build_topic_bucket(key, job["bucket"], views)
    else:
        raise SystemExit("unknown artifact kind: " + kind)
    return digest(payload), recorder.sensitivity


def fingerprint(job: dict[str, Any], sensitivity: tuple[str, ...]) -> str:
    rows = [
        {"unit": identifier, "facet": facet, "value": project(facet, unit)}
        for identifier, unit in sorted(job["inputs"], key=lambda item: item[0])
        for facet in sensitivity
    ]
    return digest(rows)


def build_revision(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    key = doc_key(document["source_id"])
    built: dict[str, dict[str, Any]] = {}
    for job in plan_of(document):
        value, sensitivity = execute(job, key)
        built[job["artifact"]] = {
            "digest": value,
            "sensitivity": list(sensitivity),
            "fingerprint": fingerprint(job, sensitivity) if sensitivity else None,
            "state": "CURRENT" if sensitivity else "UNVERIFIABLE",
        }
    return built


def run_pair(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    source_id = after["source_id"]
    key = doc_key(source_id)

    before_units = {
        logical_id(source_id, unit["explicit_path"]): unit for unit in before["units"]
    }
    after_units = {
        logical_id(source_id, unit["explicit_path"]): unit for unit in after["units"]
    }

    continuation = sorted(set(before_units) & set(after_units))
    new_units = sorted(set(after_units) - set(before_units))
    retired_units = sorted(set(before_units) - set(after_units))

    facts: dict[str, tuple[str, ...]] = {}
    for identifier in continuation:
        moved = change_facets(before_units[identifier], after_units[identifier])
        if moved:
            facts[identifier] = moved
    for identifier in new_units:
        facts[identifier] = FACETS

    prior = build_revision(before)
    after_jobs = {job["artifact"]: job for job in plan_of(after)}

    final: dict[str, str] = {}
    detail: dict[str, dict[str, Any]] = {}
    rebuilt: list[str] = []
    carried: list[str] = []
    unverifiable: list[str] = []
    disagreements: list[dict[str, Any]] = []

    for artifact in sorted(after_jobs):
        job = after_jobs[artifact]
        previous = prior.get(artifact)
        input_ids = [identifier for identifier, _ in job["inputs"]]

        if previous is None or previous["state"] == "UNVERIFIABLE":
            reason = "no prior artifact" if previous is None else "prior state was unverifiable"
            value, sensitivity = execute(job, key)
            state = "REBUILT" if sensitivity else "UNVERIFIABLE"
        else:
            edge_facets = set(previous["sensitivity"])
            touched = sorted(
                {facet for identifier in input_ids for facet in facts.get(identifier, ())}
                & edge_facets
            )
            after_fingerprint = fingerprint(job, tuple(previous["sensitivity"]))
            fingerprint_moved = after_fingerprint != previous["fingerprint"]
            if touched or fingerprint_moved:
                if bool(touched) != fingerprint_moved:
                    # The fingerprint decides. A traversal that would have carried
                    # an artifact whose fingerprint moved is a traversal defect and
                    # is recorded rather than absorbed.
                    disagreements.append(
                        {
                            "artifact": artifact,
                            "traversal_says_stale": bool(touched),
                            "fingerprint_says_stale": fingerprint_moved,
                            "facets_on_edge": sorted(edge_facets),
                            "facets_changed": touched,
                        }
                    )
                reason = "facets " + ",".join(touched) if touched else "input fingerprint moved"
                value, sensitivity = execute(job, key)
                state = "REBUILT" if sensitivity else "UNVERIFIABLE"
            else:
                value, sensitivity = previous["digest"], tuple(previous["sensitivity"])
                state, reason = "CARRIED", "input fingerprint unchanged"

        if state == "UNVERIFIABLE":
            unverifiable.append(artifact)
            final[artifact] = UNVERIFIABLE
        else:
            final[artifact] = value
            (rebuilt if state == "REBUILT" else carried).append(artifact)
        detail[artifact] = {
            "state": state,
            "reason": reason,
            "sensitivity": list(sensitivity),
        }

    retired = sorted(set(prior) - set(after_jobs))
    unnecessary = [
        artifact
        for artifact in rebuilt
        if artifact in prior and prior[artifact]["digest"] == final[artifact]
    ]
    inventory = sorted(after_jobs)

    return {
        "source_id": source_id,
        "engine": "selective_p0b",
        "pid": os.getpid(),
        "identity_rule": "deterministic explicit-path equality",
        "identity_outcomes": {
            "continuation": len(continuation),
            "new": len(new_units),
            "retired": len(retired_units),
            "unresolved": 0,
        },
        "changed_units": len(facts),
        "changed_facets": sorted({facet for moved in facts.values() for facet in moved}),
        "artifact_inventory": inventory,
        "selective_rebuild_set": rebuilt,
        "carried_forward_set": carried,
        "unverifiable_set": unverifiable,
        "retired_set": retired,
        "unnecessary_rebuild_set": unnecessary,
        "traversal_fingerprint_disagreements": disagreements,
        "observed_sensitivity_by_kind": sensitivity_by_kind(detail),
        "artifact_detail": detail,
        "rebuilt_fraction": len(rebuilt) / len(inventory) if inventory else 0.0,
        "work_avoided_fraction": len(carried) / len(inventory) if inventory else 0.0,
        "state": final,
        "state_hash": digest(final),
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def sensitivity_by_kind(detail: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    seen: dict[str, set[str]] = {}
    for artifact, row in detail.items():
        kind = artifact.split(":")[0]
        seen.setdefault(kind, set()).update(row["sensitivity"])
    return {kind: sorted(values) for kind, values in sorted(seen.items())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_pair(
        json.loads(args.before.read_text(encoding="utf-8")),
        json.loads(args.after.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"state_hash": result["state_hash"], "pid": result["pid"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
