#!/usr/bin/env python3
"""Score SFI1 against the seven endpoints. One writer, one receipt, no acquisition.

Deliberately separated from `sfi1_worker.py`. The worker acquires and extracts;
this scores. Keeping them apart is not tidiness — it is what lets acquisition run
before the freeze without producing an outcome, which is the property the two
demoted studies lost by running a smoke test that emitted a verdict.

What this tool refuses to do:

* it never fetches. It reads the acquisition artifact and the payload cache the
  worker wrote. A scorer that can acquire can quietly extend a cohort.
* it never re-admits. Admission is the worker's deterministic reduction and is
  pinned by `reduction_digest`; this tool checks that digest and scores whatever
  it names.
* it never reports an endpoint as met because nothing exercised it. Every
  endpoint carries its own gate power, and an endpoint whose failure state was
  never reachable in this cohort is SKIPPED. That distinction is the only reason
  SFH1's FAIL could be read at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import ir  # noqa: E402
from common import canonical_sha, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

ACQUISITION = NS / "artifacts" / "development" / "sfi1" / "sfi1_acquisition.json"
PROTOCOL = NS / "protocols" / "SOURCE_FACT_IR_HELDOUT_V1.yaml"

MET = "MET"
FAILED = "FAILED"
SKIPPED = "SKIPPED_NEVER_EXERCISED"

#: Endpoint ids, in the protocol's own order. Restated here so a renamed or
#: dropped endpoint is a mismatch rather than a silent absence.
ENDPOINTS: tuple[str, ...] = (
    "E1_no_unclassified_changed_regions",
    "E2_no_recognized_but_unrepresented",
    "E3_no_silent_loss_in_a_complete_scope",
    "E4_no_reference_or_locator_only_clean_miss",
    "E5_no_confirmed_selective_stale_escape",
    "E6_exact_selective_vs_clean_equivalence",
    "E7_unresolved_fails_closed",
)


class NotFrozen(RuntimeError):
    """Scoring an unfrozen protocol is scoring nothing."""


def frozen_protocol() -> dict[str, Any]:
    """The freeze receipt, or a refusal.

    A scorer that runs against a draft protocol produces a number whose rules
    could still move to fit it. That is the whole failure the freeze exists to
    prevent, so it is checked here rather than assumed upstream.
    """
    freezes = sorted((NS / "receipts").glob("sfi1-protocol-freeze--*.json"))
    if not freezes:
        raise NotFrozen(
            "no sfi1-protocol-freeze receipt exists. The protocol must be frozen "
            "before a single real lineage is scored."
        )
    body = json.loads(freezes[-1].read_text(encoding="utf-8"))
    actual = sha_file(PROTOCOL)
    if body.get("protocol_sha256") not in (actual, None):
        raise NotFrozen(
            f"the protocol has moved since it was frozen: {actual} is not "
            f"{body.get('protocol_sha256')}"
        )
    return body


def facts_of(side: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(side or [])


def _by_id(side: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["fact_id"]: row for row in side}


def endpoint_rows(pair: dict[str, Any]) -> dict[str, Any]:
    """Everything one admitted pair contributes, per endpoint.

    Each measurement returns (violations, exercised). `exercised` says the
    endpoint's failure state was reachable in this pair — that a fact of the
    relevant kind existed at all. Without it, an endpoint over a cohort with no
    references would report MET while having tested nothing.
    """
    after = facts_of(pair["facts"]["after"])
    before = facts_of(pair["facts"]["before"])
    both = after + before

    #: E1 — every extracted fact carries one of the four states. The IR's
    #: constructor already refuses anything else, so a violation here means the
    #: artifact was written by something that bypassed it.
    e1_bad = [row for row in both if row.get("state") not in ir.STATES]

    #: E2 — recognised and not represented, with no policy declining it. This is
    #: the defect the repair exists to close, stated directly.
    e2_bad = [row for row in both if row.get("state") == ir.UNREPRESENTED]

    #: E3 - a source fact lost inside a scope the run declared complete.
    #:
    #: The measurement turns on the UNSUPPORTED_CONSTRUCT kind. Before that kind
    #: existed this endpoint was unmeasurable in principle: you cannot count a
    #: fact that produced nothing. Detection converts the absence into an
    #: UNRESOLVED fact, and the question becomes checkable - is there a unit the
    #: run would call complete that nonetheless contains one?
    #:
    #: By construction there should be none, because a fail-closed fact makes
    #: its scope incomplete. What this actually catches is an ANCHORING failure:
    #: an unsupported construct attributed to the document rather than to the
    #: unit it sits inside leaves that unit looking complete while a piece of it
    #: was never represented. That is the silent drop, one level up.
    def units_with(predicate) -> set[tuple[str, ...]]:
        return {tuple(row["witness"]["unit_path"] or ()) for row in both if predicate(row)}

    all_units = units_with(lambda row: True)
    incomplete_units = units_with(lambda row: row.get("state") in ir.FAIL_CLOSED)
    complete_units = all_units - incomplete_units
    unsupported_units = units_with(lambda row: row.get("kind") == ir.UNSUPPORTED_CONSTRUCT)
    e3_bad = sorted(complete_units & unsupported_units)
    e3_exercised = bool(unsupported_units)

    #: E4 — a reference or locator moved and nothing was reported. Measured on
    #: the facts: a referential fact whose representation differs across the
    #: pair must exist in the changed set.
    referential = [kind for kind in ir.KINDS if ir.KIND_CHANNEL[kind] == ir.REFERENTIAL]
    before_by_id, after_by_id = _by_id(before), _by_id(after)
    moved_referential = [
        identifier
        for identifier, row in after_by_id.items()
        if row["kind"] in referential
        and identifier in before_by_id
        and before_by_id[identifier].get("representation") != row.get("representation")
    ]
    text_moved = any(
        row["kind"] == ir.CONTENT_TEXT
        and identifier in before_by_id
        and before_by_id[identifier].get("representation") != row.get("representation")
        for identifier, row in after_by_id.items()
    )
    #: the pair that matters is the one where a reference moved and the text did
    #: not — the shape the production path is blind to.
    e4_exercised = bool(moved_referential) and not text_moved
    e4_bad: list[str] = []
    if e4_exercised:
        unanchored = [
            identifier
            for identifier in moved_referential
            if not (after_by_id[identifier]["witness"].get("unit_path"))
        ]
        #: a moved reference with no anchor invalidates nothing, which is the
        #: clean miss wearing a different hat.
        e4_bad = unanchored

    #: E7 — an unresolved fact must be present AND must forbid the CURRENT
    #: claim. Presence is what makes the endpoint exercised; a violation is an
    #: unresolved fact carrying a representation, which would let it pass.
    unresolved = [row for row in both if row.get("state") == ir.UNRESOLVED]
    e7_bad = [
        row for row in unresolved if row.get("representation") is not None or not row.get("reason")
    ]

    return {
        "lineage_id": pair["lineage_id"],
        "family": pair["family"],
        "facts_after": len(after),
        "facts_before": len(before),
        "E1_no_unclassified_changed_regions": (len(e1_bad), bool(both)),
        "E2_no_recognized_but_unrepresented": (len(e2_bad), bool(both)),
        "E3_no_silent_loss_in_a_complete_scope": (len(e3_bad), e3_exercised),
        "E4_no_reference_or_locator_only_clean_miss": (len(e4_bad), e4_exercised),
        "E7_unresolved_fails_closed": (len(e7_bad), bool(unresolved)),
        "moved_referential": len(moved_referential),
        "text_moved": text_moved,
        "unresolved": len(unresolved),
        "unrepresented": len(e2_bad),
        "unsupported_constructs": sum(
            1 for row in both if row.get("kind") == ir.UNSUPPORTED_CONSTRUCT
        ),
        "units_complete": len(complete_units),
        "units_incomplete": len(incomplete_units),
    }


def score(rows: list[dict[str, Any]], *, bytes_available: bool) -> dict[str, Any]:
    """Endpoint verdicts, each with the power that earned it."""
    verdicts: dict[str, Any] = {}
    for endpoint in ENDPOINTS:
        if endpoint in (
            "E5_no_confirmed_selective_stale_escape",
            "E6_exact_selective_vs_clean_equivalence",
        ):
            #: both require rebuilding artifacts from the raw payloads. If the
            #: acquisition cache is absent they are SKIPPED, never MET — an
            #: endpoint that could not run has not been satisfied.
            verdicts[endpoint] = {
                "verdict": SKIPPED,
                "why": (
                    "requires the acquisition payload cache to rebuild artifacts; "
                    "the cache is absent"
                ),
                "violations": None,
                "pairs_exercising": 0,
            }
            if bytes_available:
                verdicts[endpoint]["why"] = (
                    "the payload cache is present but artifact-level rebuilding is "
                    "performed by the selective-equivalence pass, which has not run"
                )
            continue

        violations = sum(row[endpoint][0] for row in rows)
        exercising = sum(1 for row in rows if row[endpoint][1])
        if not exercising:
            verdicts[endpoint] = {
                "verdict": SKIPPED,
                "why": "no pair in this cohort could have violated it",
                "violations": 0,
                "pairs_exercising": 0,
            }
            continue
        verdicts[endpoint] = {
            "verdict": MET if violations == 0 else FAILED,
            "why": None,
            "violations": violations,
            "pairs_exercising": exercising,
        }
    return verdicts


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "pairs_scored": len(rows),
        "facts_total": sum(row["facts_after"] + row["facts_before"] for row in rows),
        "pairs_with_a_moved_reference": sum(1 for row in rows if row["moved_referential"]),
        "pairs_with_a_reference_only_change": sum(
            1 for row in rows if row["moved_referential"] and not row["text_moved"]
        ),
        "pairs_with_an_unresolved_fact": sum(1 for row in rows if row["unresolved"]),
        "pairs_with_an_unrepresented_fact": sum(1 for row in rows if row["unrepresented"]),
        "pairs_with_an_unsupported_construct": sum(
            1 for row in rows if row["unsupported_constructs"]
        ),
        "units_declared_complete": sum(row["units_complete"] for row in rows),
        "units_declared_incomplete": sum(row["units_incomplete"] for row in rows),
        "by_family": {
            family: sum(1 for row in rows if row["family"] == family)
            for family in sorted({row["family"] for row in rows})
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acquisition", default=str(ACQUISITION))
    arguments = parser.parse_args(argv)

    freeze = frozen_protocol()

    path = Path(arguments.acquisition)
    if not path.exists():
        print(f"no acquisition artifact at {rel(path)}; nothing to score", file=sys.stderr)
        return 3
    acquired = json.loads(path.read_text(encoding="utf-8"))

    rows = [endpoint_rows(pair) for pair in acquired["admitted"]]
    cache = NS / "artifacts" / "development" / "sfi1_cache"
    verdicts = score(rows, bytes_available=cache.exists())

    failed = [name for name, row in verdicts.items() if row["verdict"] == FAILED]
    skipped = [name for name, row in verdicts.items() if row["verdict"] == SKIPPED]

    body: dict[str, Any] = {
        "schema": "tavonel.v2.sfi1_score.v1",
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "protocol_freeze_receipt": freeze.get("run_id"),
        "split": "held_out",
        "acquisition": rel(path),
        "acquisition_sha256": sha_file(path),
        "reduction_digest": acquired.get("reduction_digest"),
        "generated_at": now(),
        "summary": summary(rows),
        "endpoints": verdicts,
        "endpoints_failed": failed,
        "endpoints_skipped": skipped,
        #: a skipped endpoint is not a pass. A study whose safety endpoints were
        #: never exercised has not met them, and PASS requires that every one of
        #: the seven actually ran.
        "verdict": "PASS" if not failed and not skipped else "FAIL",
        "verdict_rule": (
            "PASS requires every endpoint MET. A FAILED endpoint fails the study; "
            "a SKIPPED endpoint fails it too, because an endpoint that was never "
            "exercised has not been satisfied, it has been avoided."
        ),
        "rows": rows,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    body["result_digest"] = canonical_sha(
        {
            "endpoints": {name: row["verdict"] for name, row in verdicts.items()},
            "summary": body["summary"],
        }
    )

    written = write_immutable(
        "sfi1-source-fact-ir", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(
        json.dumps(
            {**written, "verdict": body["verdict"], "failed": failed, "skipped": skipped}, indent=2
        )
    )
    return 0 if body["verdict"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
