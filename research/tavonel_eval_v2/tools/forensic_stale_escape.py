#!/usr/bin/env python3
"""Forensic confirmation of the four oracle-relative divergences. Production only.

Founder ruling, 2026-08-23:

    production clean full rebuild(new raw)  versus  production selective result(new raw)

    If the clean rebuild changes and selective execution carries the old
    artifact/state forward, record that individual case as a confirmed selective
    stale escape.

Three things this is not, stated up front because each is an easy slide:

* **not a rate.** Four named cases are re-examined. Four is not a denominator.
* **not a rescore.** The differential study's receipt is untouched and its
  counts stand exactly as executed.
* **not an oracle result.** The independent implementation appears nowhere in
  this check. Everything here is the production canonicaliser and the production
  compiler, and the comparison is the production clean full rebuild against the
  production selective execution on the same freshly fetched bytes.

The oracle's role was to say *where to look*. Whether the production path
actually left a stale artifact behind is a question only the production path can
answer, and this is that question asked directly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler"):
    sys.path.insert(0, str(NS / _sub))

from canonical_document import canonical_document  # noqa: E402
from common import canonical_sha, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from http_pool import HttpPool, install  # noqa: E402
import selective_build as engine  # noqa: E402

PAIRS = NS / "artifacts" / "development" / "oracle_v2" / "oracle_v2_pairs.json"
FRAME = NS / "artifacts" / "development" / "vbc2_lineages.json"
USER_AGENT = "tavonel-eval-v2 forensic-confirmation (research; contact via repository)"

CONFIRMED = "CONFIRMED_SELECTIVE_STALE_ESCAPE"
NOT_CONFIRMED = "NOT_CONFIRMED_ORACLE_RELATIVE_DIVERGENCE_ONLY"
UNREPRODUCIBLE = "UNREPRODUCIBLE_SOURCE_MOVED"


def lineages() -> dict[str, dict[str, Any]]:
    body = json.loads(FRAME.read_text(encoding="utf-8"))
    return {row["lineage_id"]: row for row in body["lineages"]}


def cases() -> list[dict[str, Any]]:
    rows = json.loads(PAIRS.read_text(encoding="utf-8"))
    return [
        {
            "lineage_id": row["lineage_id"],
            "family": row["family"],
            "after_version": row["after_version"],
            "before_version": row["before_version"],
            "oracle_relative_escapes": row["verdict"]["stale_escapes"],
            "oracle_change_type": row["verdict"]["oracle_change_type"],
            "engine_change_signal": row["verdict"]["engine_change_signal"],
        }
        for row in rows
        if row["verdict"].get("stale_escape_count", 0) > 0
    ]


def document(
    lineage: dict[str, Any], version: str, known_at: str | None, raw: bytes
) -> dict[str, Any]:
    return canonical_document(
        source_family=lineage["family"],
        source_id=lineage["lineage_id"],
        version_id=version,
        payload=raw,
        source_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        known_at=known_at,
        valid_from=known_at,
        licence=lineage.get("licence", "unknown"),
    )


def confirm(case: dict[str, Any], lineage: dict[str, Any]) -> dict[str, Any]:
    """Fetch the bytes again, rebuild cleanly, run selectively, compare."""
    import run_vbc2_acquire as serial  # noqa: PLC0415

    revisions = {row["version"]: row for row in serial.ENUMERATORS[lineage["family"]](lineage)}
    for version in (case["after_version"], case["before_version"]):
        if version not in revisions:
            return {
                **case,
                "verdict": UNREPRODUCIBLE,
                "why": "revision %s is no longer listed by the source" % version,
            }

    #: freshly fetched, never from the cache. The cache is not evidence and a
    #: forensic check that reads it is checking a copy.
    after_raw = serial._payload(lineage, revisions[case["after_version"]])
    before_raw = serial._payload(lineage, revisions[case["before_version"]])

    after_document = document(
        lineage, case["after_version"], revisions[case["after_version"]].get("known_at"), after_raw
    )
    before_document = document(
        lineage,
        case["before_version"],
        revisions[case["before_version"]].get("known_at"),
        before_raw,
    )

    #: the production clean full rebuild: each revision built from itself alone,
    #: with no prior state and no plan.
    clean_after = engine.build_all(after_document)
    clean_before = engine.build_all(before_document)
    moved = sorted(
        artifact
        for artifact in set(clean_after) | set(clean_before)
        if clean_after.get(artifact) != clean_before.get(artifact)
    )

    #: the production selective execution on the same bytes.
    selective = engine.run_pair(before_document, after_document)
    carried = set(selective["carried_forward_set"])

    confirmed = sorted(artifact for artifact in moved if artifact in carried)
    disagreements = sorted(
        artifact
        for artifact in selective["state"]
        if artifact in clean_after and selective["state"][artifact] != clean_after[artifact]
    )

    return {
        **case,
        "refetched": {
            "after_sha256": "sha256:" + hashlib.sha256(after_raw).hexdigest(),
            "before_sha256": "sha256:" + hashlib.sha256(before_raw).hexdigest(),
            "bytes_differ": after_raw != before_raw,
        },
        "clean_full_rebuild": {
            "artifacts_after": len(clean_after),
            "artifacts_before": len(clean_before),
            "artifacts_that_moved": moved,
            "artifacts_that_moved_count": len(moved),
        },
        "selective": {
            "artifacts": len(selective["state"]),
            "rebuilt": len(selective["selective_rebuild_set"]),
            "carried_forward": len(carried),
            "detected_change_kinds": selective["detected_change_kinds"],
            "structural_change_present": selective["structural_change_present"],
            "state_hash": selective["state_hash"],
        },
        "selective_disagrees_with_clean_rebuild": disagreements,
        "confirmed_stale_artifacts": confirmed,
        "verdict": CONFIRMED if confirmed else NOT_CONFIRMED,
        "why": (
            "the clean full rebuild moved these artifacts and the selective "
            "execution carried the old value forward"
            if confirmed
            else (
                "the production clean full rebuild produced the same artifacts "
                "for both revisions, so there was no change for the selective "
                "path to miss. The divergence is between the production "
                "canonicaliser and the independent implementation, not inside "
                "the selective path."
                if not moved
                else "every artifact the clean rebuild moved was rebuilt selectively"
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()

    started = now()
    clock = time.time()

    import fetch_p4c_corpus as p4c  # noqa: PLC0415
    import fetch_p4g_corpus as p4g  # noqa: PLC0415

    pool = HttpPool()
    install(pool, p4c, p4g, USER_AGENT)

    frame = lineages()
    rows: list[dict[str, Any]] = []
    for case in cases():
        lineage = frame.get(case["lineage_id"])
        if lineage is None:
            rows.append({**case, "verdict": UNREPRODUCIBLE, "why": "lineage not in the frame"})
            continue
        try:
            rows.append(confirm(case, lineage))
        except Exception as error:
            rows.append(
                {
                    **case,
                    "verdict": UNREPRODUCIBLE,
                    "why": "%s: %s" % (type(error).__name__, error),
                }
            )
        print("  %-60s %s" % (case["lineage_id"][:60], rows[-1]["verdict"]), flush=True)

    confirmed = [row for row in rows if row["verdict"] == CONFIRMED]
    body: dict[str, Any] = {
        "schema": "tavonel.v2.forensic_stale_escape.v1",
        "authorised_by": "founder ruling, 2026-08-23",
        "what_this_is": (
            "post-result forensic confirmation of four named cases, using the "
            "production clean full rebuild against the production selective "
            "execution on freshly fetched bytes"
        ),
        "what_this_is_not": [
            "a rate estimate. Four named cases are not a denominator.",
            "a rescore of the differential study, whose receipt is untouched.",
            "an oracle result. The independent implementation appears nowhere in "
            "this check; it only said where to look.",
        ],
        "source_study": rel(PAIRS),
        "source_study_sha256": sha_file(PAIRS),
        "started_at": started,
        "ended_at": now(),
        "wall_seconds": round(time.time() - clock, 1),
        "cases_examined": len(rows),
        "confirmed_selective_stale_escapes": len(confirmed),
        "confirmed_cases": [
            {
                "lineage_id": row["lineage_id"],
                "artifacts": row["confirmed_stale_artifacts"],
            }
            for row in confirmed
        ],
        "by_verdict": {
            verdict: sum(1 for row in rows if row["verdict"] == verdict)
            for verdict in sorted({row["verdict"] for row in rows})
        },
        "cases": rows,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "http": pool.stats(),
    }
    body["result_digest"] = canonical_sha(
        {"by_verdict": body["by_verdict"], "confirmed": body["confirmed_cases"]}
    )

    written = write_immutable(
        "forensic-stale-escape", body, tool=Path(__file__).resolve(), protocol=None
    )
    print(json.dumps({**written, "confirmed": len(confirmed)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
