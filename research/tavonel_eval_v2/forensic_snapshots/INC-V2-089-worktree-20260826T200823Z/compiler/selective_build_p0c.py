#!/usr/bin/env python3
"""P0c selective side: the P0b mechanism, plus coverage attribution.

Derived from ``selective_build_p0b.py``, which is left exactly as it is. What
changes:

* builders see units through ``CoverageView``, which records a (field, facet)
  pair per access instead of a bare facet;
* an artifact that made any unattributed access has ``coverage_proven`` false
  and can never be carried forward, in this revision or a later one;
* ``UNCLASSIFIED_SOURCE_CHANGE`` is emitted when the source digest moved and no
  known projection did. It does not trigger a global rebuild; it scopes the
  conservative response to artifacts that cannot prove coverage.

Runs in its own process. It imports neither the oracle nor either earlier
engine.
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

from facet_coverage import (  # noqa: E402
    FACETS,
    UNCLASSIFIED,
    CoverageRecorder,
    CoverageView,
    change_facets,
    project,
    projections_identical,
)

UNVERIFIABLE_NO_SENSITIVITY = "UNVERIFIABLE_NO_RECORDED_SENSITIVITY"
UNVERIFIABLE_UNCLASSIFIED = "UNVERIFIABLE_UNCLASSIFIED_INPUT"
PROBE_FIELD = "unmapped_probe_field"


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


# --- production builders. Every access below is a mapped field ---------------


def build_section(identifier: str, view: CoverageView) -> dict[str, Any]:
    return {"logical_id": identifier, "text": view.text}


def build_semantic_summary(identifier: str, view: CoverageView) -> dict[str, Any]:
    return {"logical_id": identifier, "semantic_text": view.semantic_text}


def build_document_index(key: str, pairs: list[tuple[str, CoverageView]]) -> dict[str, Any]:
    ordered = sorted(pairs, key=lambda item: item[1].ordinal)
    return {"doc_key": key, "members": [identifier for identifier, _ in ordered]}


def build_structure_map(key: str, pairs: list[tuple[str, CoverageView]]) -> dict[str, Any]:
    ordered = sorted(pairs, key=lambda item: item[1].ordinal)
    return {
        "doc_key": key,
        "paths": ["/".join(view.explicit_path) for _, view in ordered],
        "headings": [view.heading for _, view in ordered],
    }


def build_topic_bucket(
    key: str, bucket: int, pairs: list[tuple[str, CoverageView]]
) -> dict[str, Any]:
    members = sorted(
        identifier
        for identifier, view in pairs
        if view.explicit_path and bucket_of(identifier) == bucket
    )
    return {"doc_key": key, "bucket": bucket, "members": members}


def build_coverage_probe(key: str, pairs: list[tuple[str, CoverageView]]) -> dict[str, Any]:
    """Declared control. Reads a field the projection map does not name.

    Its whole purpose is to be refused. A run where no builder ever reaches an
    unmapped field reads identically to a run where the check does not work, and
    this programme has shipped that defect before.
    """
    notes = [getattr(view, PROBE_FIELD) for _, view in pairs]
    return {"doc_key": key, "probe_values": notes}


def plan_of(document: dict[str, Any]) -> list[dict[str, Any]]:
    source_id = document["source_id"]
    key = doc_key(source_id)
    identified = [
        (logical_id(source_id, unit["explicit_path"]), unit) for unit in document["units"]
    ]

    jobs: list[dict[str, Any]] = []
    for identifier, unit in identified:
        jobs.append(
            {
                "artifact": "section:" + identifier,
                "kind": "section",
                "inputs": [(identifier, unit)],
            }
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
        if any(bucket_of(pair[0]) == bucket for pair in identified):
            jobs.append(
                {
                    "artifact": "topic-bucket:" + key + ":" + str(bucket),
                    "kind": "topic-bucket",
                    "bucket": bucket,
                    "inputs": identified,
                }
            )
    if identified and all(PROBE_FIELD in unit for _, unit in identified):
        jobs.append(
            {
                "artifact": "coverage-probe:" + key,
                "kind": "coverage-probe",
                "inputs": identified,
            }
        )
    return jobs


def execute(job: dict[str, Any], key: str) -> dict[str, Any]:
    recorder = CoverageRecorder()
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
    elif kind == "coverage-probe":
        payload = build_coverage_probe(key, views)
    else:
        raise SystemExit("unknown artifact kind: " + kind)
    return {
        "digest": digest(payload),
        "sensitivity": list(recorder.sensitivity),
        "fields_read": list(recorder.fields),
        "unclassified_fields": list(recorder.unclassified_fields),
        "coverage_proven": recorder.coverage_proven,
    }


def known_facets(sensitivity: list[str]) -> tuple[str, ...]:
    return tuple(facet for facet in FACETS if facet in sensitivity)


def fingerprint(job: dict[str, Any], sensitivity: list[str]) -> str | None:
    facets = known_facets(sensitivity)
    if not facets:
        return None
    rows = [
        {"unit": identifier, "facet": facet, "value": project(facet, unit)}
        for identifier, unit in sorted(job["inputs"], key=lambda item: item[0])
        for facet in facets
    ]
    return digest(rows)


def build_revision(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    key = doc_key(document["source_id"])
    built: dict[str, dict[str, Any]] = {}
    for job in plan_of(document):
        result = execute(job, key)
        if not result["coverage_proven"]:
            state = (
                "UNVERIFIABLE_UNCLASSIFIED"
                if result["unclassified_fields"]
                else "UNVERIFIABLE_NO_SENSITIVITY"
            )
        else:
            state = "CURRENT"
        built[job["artifact"]] = {
            **result,
            "fingerprint": fingerprint(job, result["sensitivity"]),
            "state": state,
        }
    return built


def source_change_diagnostic(
    before: dict[str, Any],
    after: dict[str, Any],
    before_units: dict[str, Any],
    after_units: dict[str, Any],
) -> dict[str, Any]:
    digests_differ = before.get("source_digest") != after.get("source_digest")
    identical = projections_identical(before_units, after_units)
    fires = bool(digests_differ and identical)
    return {
        "fires": fires,
        "source_digest_before": before.get("source_digest"),
        "source_digest_after": after.get("source_digest"),
        "source_digest_moved": digests_differ,
        "every_known_projection_identical": identical,
        "response": (
            "scope the conservative rebuild to coverage-unproven artifacts; "
            "global rebuild is forbidden"
            if fires
            else "none"
        ),
    }


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

    diagnostic = source_change_diagnostic(before, after, before_units, after_units)

    prior = build_revision(before)
    after_jobs = {job["artifact"]: job for job in plan_of(after)}

    final: dict[str, str] = {}
    detail: dict[str, dict[str, Any]] = {}
    rebuilt: list[str] = []
    carried: list[str] = []
    unverifiable: list[str] = []
    disagreements: list[dict[str, Any]] = []
    coverage_unproven: list[str] = []

    for artifact in sorted(after_jobs):
        job = after_jobs[artifact]
        previous = prior.get(artifact)
        input_ids = [identifier for identifier, _ in job["inputs"]]

        # An artifact whose coverage was unproven in the prior revision cannot be
        # carried, whatever the projections say: the decision would rest on a
        # comparison that never saw part of what the builder read.
        prior_unusable = previous is None or not previous["coverage_proven"]

        if prior_unusable:
            reason = (
                "no prior artifact"
                if previous is None
                else "prior coverage unproven: " + ",".join(previous["unclassified_fields"])
                or "prior coverage unproven"
            )
            result = execute(job, key)
            state = "REBUILT" if result["coverage_proven"] else "UNVERIFIABLE"
        else:
            edge_facets = set(known_facets(previous["sensitivity"]))
            touched = sorted(
                {facet for identifier in input_ids for facet in facts.get(identifier, ())}
                & edge_facets
            )
            after_fingerprint = fingerprint(job, previous["sensitivity"])
            fingerprint_moved = after_fingerprint != previous["fingerprint"]
            if touched or fingerprint_moved:
                if bool(touched) != fingerprint_moved:
                    disagreements.append(
                        {
                            "artifact": artifact,
                            "traversal_says_stale": bool(touched),
                            "fingerprint_says_stale": fingerprint_moved,
                            "facets_on_edge": sorted(edge_facets),
                            "facets_changed": touched,
                        }
                    )
                reason = (
                    "facets " + ",".join(touched) if touched else "input fingerprint moved"
                )
                result = execute(job, key)
                state = "REBUILT" if result["coverage_proven"] else "UNVERIFIABLE"
            else:
                result = {
                    "digest": previous["digest"],
                    "sensitivity": previous["sensitivity"],
                    "fields_read": previous["fields_read"],
                    "unclassified_fields": previous["unclassified_fields"],
                    "coverage_proven": True,
                }
                state, reason = "CARRIED", "input fingerprint unchanged"

        if not result["coverage_proven"]:
            coverage_unproven.append(artifact)

        if state == "UNVERIFIABLE":
            unverifiable.append(artifact)
            final[artifact] = (
                UNVERIFIABLE_UNCLASSIFIED
                if result["unclassified_fields"]
                else UNVERIFIABLE_NO_SENSITIVITY
            )
        else:
            final[artifact] = result["digest"]
            (rebuilt if state == "REBUILT" else carried).append(artifact)

        detail[artifact] = {
            "state": state,
            "reason": reason,
            "sensitivity": result["sensitivity"],
            "fields_read": result["fields_read"],
            "unclassified_fields": result["unclassified_fields"],
            "coverage_proven": result["coverage_proven"],
        }

    retired = sorted(set(prior) - set(after_jobs))
    unnecessary = [
        artifact
        for artifact in rebuilt
        if artifact in prior and prior[artifact]["digest"] == final[artifact]
    ]
    inventory = sorted(after_jobs)
    proven_rebuilt = [
        artifact for artifact in rebuilt if detail[artifact]["coverage_proven"]
    ]

    return {
        "source_id": source_id,
        "engine": "selective_p0c",
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
        "unclassified_source_change": diagnostic,
        "artifact_inventory": inventory,
        "selective_rebuild_set": rebuilt,
        "proven_coverage_rebuild_set": proven_rebuilt,
        "carried_forward_set": carried,
        "unverifiable_set": unverifiable,
        "coverage_unproven_set": sorted(set(coverage_unproven)),
        "retired_set": retired,
        "unnecessary_rebuild_set": unnecessary,
        "traversal_fingerprint_disagreements": disagreements,
        "observed_sensitivity_by_kind": sensitivity_by_kind(detail),
        "fields_read_by_kind": fields_by_kind(detail),
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
        seen.setdefault(artifact.split(":")[0], set()).update(row["sensitivity"])
    return {kind: sorted(values) for kind, values in sorted(seen.items())}


def fields_by_kind(detail: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    seen: dict[str, set[str]] = {}
    for artifact, row in detail.items():
        seen.setdefault(artifact.split(":")[0], set()).update(row["fields_read"])
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
