#!/usr/bin/env python3
"""A deterministic fixture whose only job is to be run twice. R1.

Its payload is a pure function of a pinned literal and this file's own source.
No clock, no randomness, no environment, no filesystem scan, no corpus file —
the last of those on purpose, so the reproducibility check does not depend on
some other result staying unchanged.

``semantic_result_digest`` is the canonical hash of the payload alone. That is
the field the two runs are compared on. Whole-file comparison would fail on the
run id and the timestamp *by design*: a receipt scheme in which two runs
produced identical bytes could not tell two runs apart, which is the property
INC-V2-005 needed and did not have.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, canonical_sha, sha_text  # noqa: E402
from evidence import write_immutable  # noqa: E402

PROTOCOL = NS / "protocols" / "R1_receipt_reproducibility.yaml"
STEM = "r1-reproducibility-fixture"

#: Pinned input. Changing it changes the semantic result, which is the point:
#: the digest is a function of something, not a constant.
INPUT: tuple[str, ...] = (
    "the quick brown fox",
    "jumps over",
    "the lazy dog",
    "ΑΒΓ δεζ",
    "full-width ＡＢＣ",
)


def payload() -> dict[str, Any]:
    """Deterministic. Same input, same source, same bytes, on any machine."""
    rows = [
        {"index": index, "value": value, "sha256": sha_text(value)}
        for index, value in enumerate(INPUT)
    ]
    return {
        "fixture": "R1",
        "input_count": len(INPUT),
        "rows": rows,
        "joined_sha256": sha_text("\n".join(INPUT)),
        "reversed_sha256": sha_text("\n".join(reversed(INPUT))),
    }


def main() -> int:
    body = payload()
    body = {
        "schema": "tavonel.v2.r1_reproducibility_fixture.v1",
        "protocol": "R1_receipt_reproducibility",
        "deterministic": True,
        "reads_clock": False,
        "reads_environment": False,
        "reads_filesystem": False,
        "payload": body,
        "semantic_result_digest": canonical_sha(body),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    written = write_immutable(STEM, body, tool=Path(__file__).resolve(), protocol=PROTOCOL)
    # stdout is the only channel back to the checker, which runs this as a
    # subprocess so the two runs cannot share a process id
    print(
        '{"receipt": "%s", "run_id": "%s", "semantic_result_digest": "%s"}'
        % (written["receipt"], written["run_id"], body["semantic_result_digest"])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
