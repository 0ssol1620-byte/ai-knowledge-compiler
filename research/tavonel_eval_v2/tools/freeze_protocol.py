#!/usr/bin/env python3
"""Freeze a protocol document and make any later change detectable.

The freeze receipt is written once. Re-running against a changed protocol fails
loudly rather than re-freezing: after the freeze, a change is an amendment with
its own receipt naming what it supersedes, which is a deliberate act, not a
side effect of running a tool again.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, git_head, now, rel, sha_file, worktree_dirty_paths, write_hashed  # noqa: E402


def freeze(protocol: Path, output: Path, amend: str | None) -> int:
    if not protocol.is_file():
        raise SystemExit("protocol not found: " + str(protocol))
    digest = sha_file(protocol)

    if output.is_file() and amend is None:
        previous = json.loads(output.read_text(encoding="utf-8"))
        if previous.get("protocol_sha256") == digest:
            print(
                json.dumps({"state": "ALREADY_FROZEN", "protocol_sha256": digest}, sort_keys=True)
            )
            return 0
        print(
            json.dumps(
                {
                    "state": "FROZEN_PROTOCOL_CHANGED",
                    "frozen": previous.get("protocol_sha256"),
                    "current": digest,
                    "required": "write an amendment receipt with --amend <reason>",
                },
                sort_keys=True,
            )
        )
        return 3

    body: dict[str, Any] = {
        "schema": "tavonel.v2.protocol_freeze.v1",
        "frozen_at": now(),
        "protocol_path": rel(protocol),
        "protocol_sha256": digest,
        "git_head": git_head(),
        "worktree_dirty_path_count": len(worktree_dirty_paths()),
        "amendment_of": amend,
        "frozen_before_any_result": amend is None,
        "external_gpu_cost_usd": 0.0,
    }
    write_hashed(output, body, "receipt_sha256")
    print(
        json.dumps(
            {"state": "FROZEN", "protocol_sha256": digest, "receipt": rel(output)},
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--protocol", type=Path, default=NS / "protocols" / "P0_master_protocol.yaml"
    )
    parser.add_argument("--output", type=Path, default=NS / "receipts" / "p0-protocol-freeze.json")
    parser.add_argument("--amend", default=None)
    args = parser.parse_args()
    return freeze(args.protocol, args.output, args.amend)


if __name__ == "__main__":
    raise SystemExit(main())
