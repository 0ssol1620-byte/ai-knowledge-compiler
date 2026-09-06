#!/usr/bin/env python3
"""Freeze a protocol, writing the freeze receipt through the immutable plumbing.

``freeze_protocol.py`` still exists and still owns the P0/P0b/P2/P3/P4 freezes.
It writes to a mutable path, which is the defect INC-V2-005 records; it is not
edited, because its receipts are the ones this programme's frozen-before-results
claims rest on and rewriting the tool would put those claims in question.

Freezes from here on go through this one. Re-freezing an unchanged protocol is a
no-op that reports the existing run; re-freezing a *changed* protocol refuses
unless it is declared as an amendment, because after a freeze a change is a
deliberate act with its own receipt naming what it supersedes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, git_head, rel, sha_file, worktree_dirty_paths  # noqa: E402
from evidence import RECEIPTS, runs_of, write_immutable  # noqa: E402


def existing(stem: str) -> list[dict[str, str]]:
    rows = []
    for path in runs_of(stem):
        body = json.loads((NS.parents[1] / path).read_text(encoding="utf-8"))
        rows.append({"receipt": path, "protocol_sha256": body.get("protocol_sha256")})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--stem", required=True)
    parser.add_argument("--amend", default=None, help="reason this amends a frozen protocol")
    args = parser.parse_args()

    protocol = args.protocol.resolve()
    if not protocol.is_file():
        raise SystemExit("protocol not found: " + str(protocol))
    digest = sha_file(protocol)

    prior = existing(args.stem)
    if prior and args.amend is None:
        matching = [row for row in prior if row["protocol_sha256"] == digest]
        if matching:
            print(json.dumps({"state": "ALREADY_FROZEN", **matching[-1]}, sort_keys=True))
            return 0
        print(
            json.dumps(
                {
                    "state": "FROZEN_PROTOCOL_CHANGED",
                    "frozen": [row["protocol_sha256"] for row in prior],
                    "current": digest,
                    "required": "re-run with --amend <reason>",
                },
                sort_keys=True,
            )
        )
        return 3

    body = {
        "schema": "tavonel.v2.protocol_freeze.v2",
        "protocol_path": rel(protocol),
        "protocol_sha256": digest,
        "git_head": git_head(),
        "worktree_dirty_path_count": len(worktree_dirty_paths()),
        "amendment_of": args.amend,
        "frozen_before_any_result": args.amend is None,
        "supersedes_receipts": [row["receipt"] for row in prior],
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    written = write_immutable(args.stem, body, tool=Path(__file__).resolve(), protocol=protocol)
    print(json.dumps({"state": "FROZEN", "protocol_sha256": digest, **written}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
