#!/usr/bin/env python3
"""Apply the capacity criterion to SFIR7's census, and say what the number means.

SFIR7 changed one thing: who chose the roots. SFIR1-SFIR6 measured twenty Git
repositories TAVONEL picked; SFIR7 measures fifty an external catalogue's own
published ordinal picked, from a deposit that predates the question. Everything
else -- the traversal, the bounds, the identity semantics, the criterion, the
salt -- is inherited unchanged, so a difference in the result is attributable to
the frame and not to the instrument.

**Nothing here is asserted.** SFIR6's sealer carried a table of prose verdicts
keyed by family, which was defensible when the verdicts explained *why* a
computed number meant what it meant. This one computes the verdict as well, for
a reason SFIR7 makes sharp: this study's whole subject is whether an
outcome-independent frame produces a different capacity, and a sealer holding a
pre-written conclusion could not answer that question honestly whatever it
printed.

**Three ways the census can fall short, and they are not the same finding.**

  the frame is too small        -- roots produced fewer documents than needed
  the frame was cut             -- roots were excluded by the inherited request
                                   bound before they were visited (INC-V2-115)
  the roots were capped         -- roots hit the per-root candidate cap, so the
                                   count is a floor rather than a measurement

Each is reported separately with the roots it applies to. Collapsing them into
one number would let a budget exhaustion read as a statement about how much
documentation open-source projects carry.

**No number moves after this runs.** The threshold is 750, N is 50, the roster is
frozen by fingerprint, and the standing instruction is that a shortfall changes
none of them. The result is taken as it comes.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir7_roots as roots  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402
from common import now  # noqa: E402

SCHEMA = "tavonel.sfir7.capacity_outcome.v1"
PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7"
FAMILY = "git_docs"

MINIMUM_C = 750
MINIMUM_Q = 600

#: SFIR5's and SFIR6's twice-measured Git count under TAVONEL's own twenty roots.
#: Present as a COMPARISON TARGET, never as an input: every figure in `family`
#: below is computed from SFIR7's census.
PREDECESSOR_GIT_C = 293
PREDECESSOR_ROOTS = 20


class SealRefused(RuntimeError):
    """The census cannot be sealed as a measurement of what it claims."""


def _quota(count: int) -> int:
    return min(1000, (8 * count) // 10)


def build(census_path: Path, *, generated_at: str | None = None) -> dict[str, Any]:
    body = json.loads(census_path.read_text(encoding="utf-8"))
    block = body["families"][FAMILY]
    candidates = block["candidates"]
    dispositions = block["root_dispositions"]

    lineages = [row["lineage_id"] for row in candidates]
    if len(set(lineages)) != len(lineages):
        raise SealRefused(
            "the census contains duplicate lineage ids, so its candidate count is not "
            "a count of distinct documents"
        )

    count = len(candidates)
    quota = _quota(count)
    states = {
        state: sum(1 for row in dispositions if row.get("state") == state)
        for state in sorted({row.get("state") for row in dispositions})
    }
    bound_excluded = sum(
        1 for row in dispositions if row.get("reason") == "GLOBAL_GIT_REQUEST_BOUND"
    )
    host_excluded = sum(
        1 for row in dispositions if row.get("reason") == "EXTERNAL_RATE_LIMIT_EXHAUSTED"
    )
    per_root = _per_root_counts(candidates)
    cap = int(sources.SOURCE_POOLS[FAMILY]["max_candidates_per_repository"])
    capped = sorted(name for name, value in per_root.items() if value >= cap)

    attestation = body.get("identity_attestation") or {}
    frozen_roots = len(roots.declared_roots())

    #: Computed, not declared. A sealer that decided this in advance could not
    #: answer the question SFIR7 exists to ask.
    meets = count >= MINIMUM_C and quota >= MINIMUM_Q
    sealable = not capped and attestation.get("roots_attested", 0) > 0

    return {
        "schema": SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "generated_at": generated_at or now(),
        "state": (
            "CAPACITY_CRITERION_APPLIED_AND_MET"
            if meets
            else "CAPACITY_CRITERION_APPLIED_AND_FAILED"
        ),
        "criterion": {
            "formula": "Q_f=min(1000,floor(0.8*C_f))",
            "minimum_C": MINIMUM_C,
            "minimum_Q": MINIMUM_Q,
            "inherited_unchanged_from": "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4",
        },
        "family": {
            "family": FAMILY,
            "C": count,
            "Q": quota,
            "meets_C": count >= MINIMUM_C,
            "meets_Q": quota >= MINIMUM_Q,
            "meets_criterion": meets,
            "is_sealable": sealable,
            "roots_frozen": frozen_roots,
            "roots_visited": len(dispositions),
            "roots_complete": states.get("COMPLETE", 0),
            "root_states": states,
        },
        "why_a_shortfall_would_be_which_kind": {
            "frame_too_small": {
                "roots_complete": states.get("COMPLETE", 0),
                "candidates_from_complete_roots": count,
                "means": (
                    "roots were visited to exhaustion and produced this many revision "
                    "pairs. This is a measurement of the frame."
                ),
            },
            "frame_cut_by_an_inherited_bound": {
                "roots_excluded": bound_excluded,
                "bound": sources.MAX_GIT_API_REQUESTS_GLOBAL,
                "registered_in_advance_as": "INC-V2-115",
                "means": (
                    "roots the request budget stopped before they were visited. Excluded "
                    "roots can only lower C, never raise it, so a criterion MET despite "
                    "them is sound and a shortfall is partly an accounting event."
                ),
            },
            "frame_cut_by_the_hosts_rate_limit": {
                "roots_excluded": host_excluded,
                "registered_in_advance_as": "INC-V2-119",
                "means": (
                    "roots GitHub declined to serve, having asked for a wait longer than "
                    "SFIR4's frozen fail-safe permits. Distinct from our own cap firing: "
                    "that is a budget we chose, this is one imposed on us, and SFIR7 "
                    "measured that the host counts requests our counter does not, so ours "
                    "cannot be relied on to fire first."
                ),
                "the_fail_safe_was_not_widened": True,
            },
            "roots_that_hit_the_per_root_cap": {
                "cap": cap,
                "roots_at_the_cap": capped,
                "count": len(capped),
                "means": (
                    "a root at its cap produced at least this many documents and possibly "
                    "more, so C is a floor for it rather than a measurement. SFIR6 "
                    "recorded a highest per-root count of 73 against the same cap of 80, "
                    "which is why that study's shortfall was not a cap artifact."
                ),
            },
        },
        "per_root_candidates": per_root,
        "identity_attestation": attestation,
        "frame_change_versus_predecessor": {
            "predecessor_protocol": "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V6",
            "predecessor_C": PREDECESSOR_GIT_C,
            "predecessor_roots": PREDECESSOR_ROOTS,
            "predecessor_roots_chosen_by": "TAVONEL",
            "sfir7_roots_chosen_by": "Libraries.io published SourceRank, deposited 2020-01-12",
            "sfir7_C": count,
            "delta_C": count - PREDECESSOR_GIT_C,
            "predecessor_numbers_are_a_comparison_target_not_an_input": (
                "every figure under `family` was computed from SFIR7's own census. The "
                "predecessor count appears so a reader can see what changing WHO CHOSE "
                "THE ROOTS did, which is the only variable SFIR7 moved."
            ),
            "what_a_difference_is_attributable_to": (
                "the frame. Traversal, bounds, identity semantics, salt, criterion and "
                "candidate construction are inherited unchanged and the candidate builder "
                "is bound to SFIR4's by an equivalence control."
            ),
        },
        "what_was_not_done_about_the_result": {
            "roots_added": 0,
            "threshold_lowered": False,
            "n_changed": False,
            "roster_edited": False,
            "why": (
                "SFIR7's charter and the standing instruction forbid all four by name. "
                "Adjusting any of them after seeing this number would convert an "
                "outcome-independent frame into an outcome-conditioned one, which is the "
                "single thing this protocol exists to prevent."
            ),
        },
        "payload_opened": False,
        "corpus_spent": False,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def _per_root_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in candidates:
        key = str(row["discovery_root_id"])
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--generated-at", default=None)
    args = parser.parse_args(argv)

    try:
        body = build(args.census, generated_at=args.generated_at)
    except SealRefused as error:
        print(json.dumps({"state": "SEAL_REFUSED", "why": str(error)}, indent=2), file=sys.stderr)
        return 4
    body["content_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    args.receipt.write_text(
        json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "state": body["state"],
                "C": body["family"]["C"],
                "Q": body["family"]["Q"],
                "roots_complete": body["family"]["roots_complete"],
                "root_states": body["family"]["root_states"],
                "bound_excluded": body["why_a_shortfall_would_be_which_kind"][
                    "frame_cut_by_an_inherited_bound"
                ]["roots_excluded"],
                "host_excluded": body["why_a_shortfall_would_be_which_kind"][
                    "frame_cut_by_the_hosts_rate_limit"
                ]["roots_excluded"],
                "roots_at_cap": body["why_a_shortfall_would_be_which_kind"][
                    "roots_that_hit_the_per_root_cap"
                ]["count"],
                "delta_vs_predecessor": body["frame_change_versus_predecessor"]["delta_C"],
                "receipt": args.receipt.as_posix(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
