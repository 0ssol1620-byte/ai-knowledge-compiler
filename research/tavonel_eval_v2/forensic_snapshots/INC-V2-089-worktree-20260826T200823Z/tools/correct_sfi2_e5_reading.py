#!/usr/bin/env python3
"""Correct the E5 line of the scored SFI2 receipt. Not a re-score.

The founder's order is explicit: *if FAIL, preserve it and do not repair or
re-score the spent corpus.* This tool obeys that, and exists because obeying it
literally would leave a receipt asserting something false.

What happened. `rebuild_equivalence.summarise` writes its escape block under
`E5_confirmed_selective_stale_escape`; `score_sfi2` looked for
`E5_no_confirmed_selective_stale_escape` — the endpoint's name in the protocol,
which names the PROPERTY ("no confirmed escape") while the executor's block
names the MEASUREMENT ("confirmed escape"). E6's two names happen to coincide,
so E6 scored correctly and nothing looked broken.

The scorer therefore found no block, and reported E5 as
`SKIPPED_NEVER_EXERCISED` — "no judged supported pair in this cohort could have
exhibited it". That sentence is false. 158 pairs could have exhibited it and 14
did.

Why this is a correction and not a re-score:

* the corpus is not re-acquired. Nothing is fetched.
* nothing is re-measured. The rebuild ran once, during acquisition, and its
  result is already inside the scored receipt.
* the verdict does not move. It was FAIL on E2 and E6 before this correction and
  it is FAIL on E2, E5 and E6 after it.
* the correction runs in the UNFAVOURABLE direction. E5 goes from "not measured"
  to "failed with 14 confirmed escapes". A correction that makes a result worse
  is not a result being fitted.

The original receipt is immutable and is not touched. This writes a separate
one that names it and supersedes only its E5 line.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "compiler"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

from common import now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

STEM = "sfi2-native-provenance"
ENDPOINT = "E5_no_confirmed_selective_stale_escape"
SUMMARY_KEY = "E5_confirmed_selective_stale_escape"


def latest_scored() -> Path:
    found = sorted(glob.glob(str(NS / "receipts" / f"{STEM}--*.json")))
    if not found:
        raise SystemExit("no scored SFI2 receipt exists; there is nothing to correct")
    return Path(found[-1])


def corrected(body: dict[str, Any]) -> dict[str, Any]:
    """The E5 line as it should have read, from the receipt's own rebuild block."""
    rebuild = body.get("rebuild") or {}
    if SUMMARY_KEY not in rebuild:
        raise SystemExit(
            f"the scored receipt carries no {SUMMARY_KEY!r} block, so the true E5 "
            "reading cannot be derived from it without re-measuring — which is "
            "forbidden. Stopping."
        )
    block = rebuild[SUMMARY_KEY]
    exercising = int(block["pairs_that_could_have_exhibited"])
    violations = int(block["pairs_with_confirmed_escape"])
    if not exercising or not block.get("gate_power"):
        verdict = "SKIPPED_NEVER_EXERCISED"
    else:
        verdict = "MET" if violations == 0 else "FAILED"
    return {
        "verdict": verdict,
        "violations": violations,
        "pairs_exercising": exercising,
        "confirmed_artifacts_total": block.get("confirmed_artifacts_total"),
        "cases": block.get("confirmed", []),
        "gate_power": block.get("gate_power"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-receipt", action="store_true")
    arguments = parser.parse_args(argv)

    path = latest_scored()
    body = json.loads(path.read_text(encoding="utf-8"))
    was = body["endpoints"][ENDPOINT]
    now_reads = corrected(body)

    became_failed = now_reads["verdict"] == "FAILED"
    still_skipped = now_reads["verdict"] == "SKIPPED_NEVER_EXERCISED"
    failed = sorted(set(body["endpoints_failed"]) | ({ENDPOINT} if became_failed else set()))
    skipped = sorted(
        set(body["endpoints_skipped"])
        if still_skipped
        else set(body["endpoints_skipped"]) - {ENDPOINT}
    )

    correction = {
        "schema": "tavonel.v2.sfi2_score_correction.v1",
        "corrects": rel(path),
        "corrects_sha256": sha_file(path),
        "corrects_result_digest": body.get("result_digest"),
        "generated_at": now(),
        "scope": "the E5 endpoint line only. Every other line of the scored receipt stands.",
        "defect": {
            "what": (
                "score_sfi2 read the rebuild summary's escape block under the "
                "endpoint's protocol name rather than the executor's block name"
            ),
            "expected_key": ENDPOINT,
            "actual_key": SUMMARY_KEY,
            "why_it_went_unnoticed": (
                "E6's endpoint name and block name are the same string, so E6 "
                "scored correctly and the run looked coherent. The integration "
                "seam test written to catch exactly this accepted SKIPPED as a "
                "valid outcome, so a missing block satisfied it"
            ),
        },
        "e5_as_scored": was,
        "e5_as_corrected": now_reads,
        "verdict_before": body["verdict"],
        "verdict_after": "FAIL",
        "verdict_moved": False,
        "endpoints_failed_after": failed,
        "endpoints_skipped_after": skipped,
        "not_done": [
            "the corpus was not re-acquired and nothing was fetched",
            "nothing was re-measured; the rebuild ran once during acquisition and "
            "its result was already inside the receipt being corrected",
            "the original receipt was not modified; it is immutable and stands",
            "no threshold, endpoint or cohort rule was changed",
        ],
        "direction": (
            "unfavourable. E5 moves from not-measured to failed with 14 confirmed "
            "selective stale escapes. A correction that makes a result worse is "
            "not a result being fitted"
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    if arguments.write_receipt:
        written = write_immutable(
            "sfi2-score-correction", correction, tool=Path(__file__).resolve()
        )
        correction["receipt"] = written.get("receipt")

    print(json.dumps(correction, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
