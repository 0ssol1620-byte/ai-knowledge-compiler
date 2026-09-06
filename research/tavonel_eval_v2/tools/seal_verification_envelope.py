#!/usr/bin/env python3
"""Wrap a run of the sealed evidence verifier in an immutable receipt.

``tools/verify_sealed_evidence.py`` is inside the P0 v1 seal, so it cannot be
changed to write through the INC-V2-005 plumbing — editing it to improve
provenance would break the seal it exists to check. It writes where it is told
to write, on a mutable path.

So the raw output stays as the sealed tool produced it, and this wraps it: an
immutable receipt carrying that file's digest, the verifier's own digest and the
totals, so the run itself is pinned even though the tool's output path is not.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, git_head, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

VERIFIER = NS / "tools" / "verify_sealed_evidence.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--stem", default="sealed-evidence-verification")
    parser.add_argument("--occasion", required=True)
    args = parser.parse_args()

    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    body = {
        "schema": "tavonel.v2.sealed_verification_envelope.v1",
        "occasion": args.occasion,
        "git_head": git_head(),
        "raw_output": rel(args.raw),
        "raw_output_file_sha256": sha_file(args.raw),
        "raw_output_receipt_sha256": raw.get("receipt_sha256"),
        "verifier": rel(VERIFIER),
        "verifier_sha256": sha_file(VERIFIER),
        "verifier_is_sealed_by": "research/tavonel_eval_v2/receipts/p0-v1-seal.json",
        "totals": raw.get("totals"),
        "verdict": raw.get("verdict"),
        "note": (
            "The verifier is sealed and writes to a mutable path. This envelope "
            "pins the run; it does not make that path immutable, and a later run "
            "may still overwrite the raw file. The digest recorded here is what "
            "makes that detectable."
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    written = write_immutable(args.stem, body, tool=Path(__file__).resolve())
    print(json.dumps({"verdict": body["verdict"], **written}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
