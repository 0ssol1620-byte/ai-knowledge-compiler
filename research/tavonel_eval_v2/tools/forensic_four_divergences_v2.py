#!/usr/bin/env python3
"""Would SOURCE_FACT_IR have caught the four confirmed stale escapes? Forensic only.

`forensic-stale-escape` confirmed, against the production path on freshly fetched
bytes, that four named cases carried a stale artifact forward:
`clean_full_rebuild` moved the artifact and `selective` carried the old value.
`forensic-stale-escape-root-cause` classified *why*: three were typographic
punctuation, one was a topic-bucket membership gap.

This tool asks the next question, mechanically, for the same four cases:

    would `source_fact_ir` (lanes 1-4) have named the artifact the clean
    rebuild moved, and through which fact kind and dependency channel?

It answers it the only way that is not circular: refetch the bytes again, build
both canonical documents, run the production clean rebuild and the production
selective path exactly as `forensic-stale-escape` does, and *separately* run
`ir.extract_all` over both revisions and hand the result to
`source_fact_ir.fingerprint.aligned` — lane 4's own alignment invariant, which
compares a typed delta against two clean rebuilds and reports which artifacts
moved without being named. Nothing here reimplements that comparison; it calls
the lane's own answer and reports it.

Three things this is not, stated up front because each is an easy slide:

* **not a rate.** Four named cases are re-examined. Four is not a denominator.
* **not a rescore.** Neither the differential study's receipt nor the
  stale-escape confirmation's receipt is touched; both are read only.
* **not a verdict on the design.** Four cases can show the typed design names
  (or does not name) four named artifacts. They cannot show the design works.
  That comes from a fresh, disjoint, held-out corpus, later.

Lanes 2 and 3 (`source_fact_ir/reference.py`, `source_fact_ir/metadata.py`) were
being written by other agents while this tool was written and may not exist
when it runs. A case whose only typed evidence would have come from a missing
lane is reported `NOT_EXERCISED`, never as a miss and never as a catch — a
result nobody computed is not the same thing as a result that came back
negative, and collapsing the two is exactly the kind of silent drop this whole
programme exists to make impossible.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
import time
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
#: `source_fact_ir/fingerprint.py` imports itself as `from source_fact_ir import ir`,
#: a namespace-package import that needs the *parent* of `source_fact_ir/` on the
#: path as well. It is a second, independent load of `ir` from the bare one the
#: extractors register into (see `_load_source_fact_ir` below); that is safe here
#: because nothing in this chain uses `isinstance` against `ir.SourceFact` — every
#: crossing is attribute or string based — but it is a real seam, so it is named
#: rather than left to be rediscovered.
sys.path.insert(0, str(NS))

import selective_build as engine  # noqa: E402
from canonical_document import canonical_document  # noqa: E402
from common import canonical_sha, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from http_pool import HttpPool, install  # noqa: E402

FORENSIC = sorted((NS / "receipts").glob("forensic-stale-escape--*.json"))[-1]
FRAME = NS / "artifacts" / "development" / "vbc2_lineages.json"
USER_AGENT = "tavonel-eval-v2 forensic-four-divergences-v2 (research; contact via repository)"

#: The lane modules this tool needs but does not own. `core` is not listed:
#: without it there is no typed extraction at all and every case degrades to
#: NOT_EXERCISED regardless of what else is present.
CORE_MODULE = "core_extractor"
FINGERPRINT_MODULE = "fingerprint"
OPTIONAL_LANE_MODULES: tuple[str, ...] = ("reference", "metadata")

#: Conclusion vocabulary. Deliberately four labels and nothing that can be
#: averaged, divided or otherwise turned into a rate — a case-level finding
#: about one named artifact, not a fraction of anything.
WOULD_HAVE_NAMED = "TYPED_DELTA_WOULD_HAVE_NAMED_THE_STALE_ARTIFACT"
WOULD_NOT_HAVE_NAMED = "TYPED_DELTA_WOULD_NOT_HAVE_NAMED_THE_STALE_ARTIFACT"
NOT_EXERCISED = "NOT_EXERCISED"
UNREPRODUCIBLE = "UNREPRODUCIBLE_SOURCE_MOVED"

CONCLUSIONS: frozenset[str] = frozenset(
    {WOULD_HAVE_NAMED, WOULD_NOT_HAVE_NAMED, NOT_EXERCISED, UNREPRODUCIBLE}
)


def _load_source_fact_ir() -> tuple[Any, Any, dict[str, dict[str, Any]]]:
    """Import `ir` (bare) and, defensively, every extraction/lane module.

    Returns `(ir_module, fingerprint_module_or_None, import_report)`. Never
    raises: an absent lane is exactly as legitimate an outcome this early in
    the parallel programme as a present one, and this function's whole job is
    to say which happened rather than assume.

    `ir` itself is not defensive — it is this tool's frozen input contract and
    its absence is a setup error, not a lane that has not landed yet.
    """
    import ir as ir_module

    report: dict[str, dict[str, Any]] = {}
    for name in (CORE_MODULE, *OPTIONAL_LANE_MODULES):
        try:
            importlib.import_module(name)
            report[name] = {"imported": True}
        except Exception as error:
            report[name] = {
                "imported": False,
                "reason": f"{type(error).__name__}: {error}",
            }

    fingerprint_module: Any = None
    try:
        fingerprint_module = importlib.import_module(FINGERPRINT_MODULE)
        report[FINGERPRINT_MODULE] = {"imported": True}
    except Exception as error:
        report[FINGERPRINT_MODULE] = {
            "imported": False,
            "reason": f"{type(error).__name__}: {error}",
        }

    return ir_module, fingerprint_module, report


def lineages() -> dict[str, dict[str, Any]]:
    body = json.loads(FRAME.read_text(encoding="utf-8"))
    return {row["lineage_id"]: row for row in body["lineages"]}


def confirmed_cases() -> list[dict[str, Any]]:
    """The exact cases `forensic-stale-escape` confirmed, read from its receipt.

    Re-derived from the receipt rather than hardcoded, so a change to the
    upstream confirmation is visible here rather than silently stale.
    """
    body = json.loads(FORENSIC.read_text(encoding="utf-8"))
    return [row for row in body["cases"] if row["verdict"] == "CONFIRMED_SELECTIVE_STALE_ESCAPE"]


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


def compare_case(
    confirmed_stale_artifacts: list[str],
    typed_invalidated: list[str],
    moved_facts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pure comparison: does the typed delta name each confirmed-stale artifact?

    Takes only plain data (no network, no filesystem, no source_fact_ir import)
    so it can be exercised directly by tests. `moved_facts` is a list of
    `{"kind": ..., "channel": ..., "dependency_keys": [...]}` — one entry per
    fact the typed delta reports as added, removed or changed — and is used
    only to explain a "yes", never to decide it; the decision is entirely
    `artifact in typed_invalidated`.
    """
    named = set(typed_invalidated)
    per_artifact: dict[str, dict[str, Any]] = {}
    for artifact in confirmed_stale_artifacts:
        via = sorted(
            {
                (entry["kind"], entry["channel"])
                for entry in moved_facts
                if artifact in entry.get("dependency_keys", ())
            }
        )
        per_artifact[artifact] = {
            "named_by_typed_delta": artifact in named,
            "via_fact_kind_and_channel": [list(pair) for pair in via],
        }
    all_named = bool(confirmed_stale_artifacts) and all(
        row["named_by_typed_delta"] for row in per_artifact.values()
    )
    return {
        "per_artifact": per_artifact,
        "conclusion": WOULD_HAVE_NAMED if all_named else WOULD_NOT_HAVE_NAMED,
    }


def evaluate(
    case: dict[str, Any],
    lineage: dict[str, Any],
    ir_module: Any,
    fingerprint_module: Any | None,
    lane_report: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Fetch, build, run both paths, and compare. One case, start to finish."""
    base = {
        "lineage_id": case["lineage_id"],
        "family": case["family"],
        "after_version": case["after_version"],
        "before_version": case["before_version"],
        "confirmed_stale_artifacts": case["confirmed_stale_artifacts"],
    }

    #: checked before anything is fetched — an absent lane is a reason not to
    #: run the case at all, not a reason to run it and call the silence a miss.
    if not lane_report.get(CORE_MODULE, {}).get("imported") or fingerprint_module is None:
        missing = [
            name
            for name in (CORE_MODULE, FINGERPRINT_MODULE)
            if not lane_report.get(name, {}).get("imported")
        ]
        reasons = ", ".join(
            f"{name} ({lane_report.get(name, {}).get('reason', 'unknown')})" for name in missing
        )
        return {
            **base,
            "conclusion": NOT_EXERCISED,
            "why": f"required module(s) not importable: {reasons}",
        }

    import run_vbc2_acquire as serial

    revisions = {row["version"]: row for row in serial.ENUMERATORS[lineage["family"]](lineage)}
    for version in (case["after_version"], case["before_version"]):
        if version not in revisions:
            return {
                **base,
                "conclusion": UNREPRODUCIBLE,
                "why": f"revision {version} is no longer listed by the source",
            }

    #: freshly fetched, never from the cache — the same discipline
    #: `forensic-stale-escape` applies, for the same reason.
    after_raw = serial._payload(lineage, revisions[case["after_version"]])
    before_raw = serial._payload(lineage, revisions[case["before_version"]])

    after_known_at = revisions[case["after_version"]].get("known_at")
    before_known_at = revisions[case["before_version"]].get("known_at")
    after_document = document(lineage, case["after_version"], after_known_at, after_raw)
    before_document = document(lineage, case["before_version"], before_known_at, before_raw)

    # --- (a) the production path exactly as today -------------------------
    clean_after = engine.build_all(after_document)
    clean_before = engine.build_all(before_document)
    moved = sorted(
        artifact
        for artifact in set(clean_after) | set(clean_before)
        if clean_after.get(artifact) != clean_before.get(artifact)
    )
    selective = engine.run_pair(before_document, after_document)
    carried = set(selective["carried_forward_set"])
    confirmed_now = sorted(artifact for artifact in moved if artifact in carried)

    # --- (b) the typed path -------------------------------------------------
    before_facts = ir_module.extract_all(raw=before_raw, document=before_document)
    after_facts = ir_module.extract_all(raw=after_raw, document=after_document)
    typed = fingerprint_module.delta(before_facts, after_facts)
    report = fingerprint_module.aligned(before_facts, after_facts, clean_before, clean_after)

    moved_facts = [
        {
            "fact_id": entry.fact_id,
            "kind": entry.kind,
            "channel": entry.channel,
            "dependency_keys": list(entry.dependency_keys),
        }
        for entry in typed.moved
    ]

    comparison = compare_case(
        confirmed_stale_artifacts=case["confirmed_stale_artifacts"],
        typed_invalidated=list(report.invalidated),
        moved_facts=moved_facts,
    )

    return {
        **base,
        "refetched": {
            "after_sha256": "sha256:" + hashlib.sha256(after_raw).hexdigest(),
            "before_sha256": "sha256:" + hashlib.sha256(before_raw).hexdigest(),
        },
        "clean_full_rebuild": {
            "artifacts_that_moved": moved,
            "artifacts_that_moved_count": len(moved),
        },
        "selective": {
            "carried_forward_count": len(carried),
            "confirmed_stale_artifacts_this_run": confirmed_now,
        },
        "typed_delta": {
            "registered_kinds": list(ir_module.registered_kinds()),
            "unclaimed_kinds": list(ir_module.unclaimed_kinds()),
            "before_fact_count": len(before_facts),
            "after_fact_count": len(after_facts),
            "moved_fact_count": len(typed.moved),
            "invalidated_artifact_keys": list(report.invalidated),
            "moved_facts": moved_facts,
        },
        "alignment_report": {
            "moved": list(report.moved),
            "under_invalidated": list(report.under_invalidated),
            "silent_facts": list(report.silent_facts),
            "is_aligned": report.is_aligned,
        },
        **comparison,
        "why": (
            "the typed delta invalidated every confirmed-stale artifact for this case"
            if comparison["conclusion"] == WOULD_HAVE_NAMED
            else "at least one confirmed-stale artifact moved without the typed "
            "delta naming it: " + report.describe()
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()

    started = now()
    clock = time.time()

    ir_module, fingerprint_module, lane_report = _load_source_fact_ir()

    import fetch_p4c_corpus as p4c
    import fetch_p4g_corpus as p4g

    pool = HttpPool()
    install(pool, p4c, p4g, USER_AGENT)

    frame = lineages()
    rows: list[dict[str, Any]] = []
    for case in confirmed_cases():
        lineage = frame.get(case["lineage_id"])
        if lineage is None:
            rows.append(
                {
                    "lineage_id": case["lineage_id"],
                    "family": case["family"],
                    "after_version": case["after_version"],
                    "before_version": case["before_version"],
                    "confirmed_stale_artifacts": case["confirmed_stale_artifacts"],
                    "conclusion": UNREPRODUCIBLE,
                    "why": "lineage not in the frame",
                }
            )
            continue
        try:
            rows.append(evaluate(case, lineage, ir_module, fingerprint_module, lane_report))
        except Exception as error:
            rows.append(
                {
                    "lineage_id": case["lineage_id"],
                    "family": case["family"],
                    "after_version": case["after_version"],
                    "before_version": case["before_version"],
                    "confirmed_stale_artifacts": case["confirmed_stale_artifacts"],
                    "conclusion": UNREPRODUCIBLE,
                    "why": f"{type(error).__name__}: {error}",
                }
            )
        print(f"  {case['lineage_id'][:60]:<60} {rows[-1]['conclusion']}", flush=True)

    by_conclusion = {
        conclusion: sum(1 for row in rows if row["conclusion"] == conclusion)
        for conclusion in sorted({row["conclusion"] for row in rows})
    }

    body: dict[str, Any] = {
        "schema": "tavonel.v2.forensic_four_divergences_v2.v1",
        "what_this_is": (
            "for each of the four cases forensic-stale-escape confirmed against "
            "the production path, on freshly refetched bytes: whether "
            "source_fact_ir's typed delta (ir.extract_all + "
            "source_fact_ir.fingerprint.aligned) would have named the artifact "
            "the clean full rebuild moved and the selective path carried stale, "
            "and through which fact kind and dependency channel"
        ),
        "what_this_is_not": [
            "a rate. Four named cases are not a denominator.",
            "a rescore of forensic-stale-escape or forensic-stale-escape-root-cause; "
            "both receipts are read only, never touched.",
            "a held-out result. The corpus here is the same four named cases the "
            "confirmation already looked at, refetched again. It cannot establish "
            "that the typed design works — only that it does or does not name "
            "these four named artifacts. The real verdict comes later, from a "
            "fresh disjoint held-out corpus.",
        ],
        "confirms": rel(FORENSIC),
        "confirms_sha256": sha_file(FORENSIC),
        "source_fact_ir_lane_imports": lane_report,
        "started_at": started,
        "ended_at": now(),
        "wall_seconds": round(time.time() - clock, 1),
        "cases_examined": len(rows),
        "by_conclusion": by_conclusion,
        "cases": rows,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "http": pool.stats(),
    }
    body["result_digest"] = canonical_sha(
        {
            "by_conclusion": by_conclusion,
            "per_case": [
                {"lineage_id": row["lineage_id"], "conclusion": row["conclusion"]} for row in rows
            ],
        }
    )

    written = write_immutable(
        "forensic-four-divergences-v2", body, tool=Path(__file__).resolve(), protocol=None
    )
    print(json.dumps({**written, "by_conclusion": by_conclusion}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
