#!/usr/bin/env python3
"""P2 acquisition: multi-revision chains from the declared documentation paths.

A chain is the same document across consecutive commits, oldest first. The
relation between adjacent revisions is the repository's own commit history for
that path, not a similarity guess.

Read-only HTTP GET against public endpoints. No credential is sent, no GPU is
touched, no paid API is called. Blob bodies come from raw.githubusercontent, so
only the commit listing costs an API call.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "canonicalization"))

from canonical_document import canonical_document  # noqa: E402
from common import NS, canonical_json, canonical_sha, now, rel, sha_bytes, sha_file, write_hashed  # noqa: E402
from sources import GIT_DOCS, REDISTRIBUTION  # noqa: E402

USER_AGENT = "TAVONEL Research claude23@vieworks.com"
GITHUB_SLEEP = 1.0
MIN_UNITS = 3


def get(url: str, *, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as handle:
        return handle.read()


def run(length: int, output: Path) -> int:
    raw_root = NS / "artifacts" / "development" / "chains" / "raw"
    canonical_root = NS / "artifacts" / "development" / "chains" / "canonical"
    chains: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    started = now()

    for entry in GIT_DOCS:
        listing = (
            "https://api.github.com/repos/"
            + entry["owner"]
            + "/"
            + entry["repo"]
            + "/commits?per_page="
            + str(length + 4)
            + "&path="
            + urllib.parse.quote(entry["path"])
        )
        try:
            commits = json.loads(get(listing))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            excluded.append(
                {"path": entry["path"], "reason": "INELIGIBLE_FETCH", "detail": type(error).__name__}
            )
            continue
        time.sleep(GITHUB_SLEEP)
        if not isinstance(commits, list) or len(commits) < 3:
            excluded.append(
                {
                    "path": entry["path"],
                    "reason": "INELIGIBLE_CHAIN_TOO_SHORT",
                    "detail": "fewer than three commits touch this path",
                }
            )
            continue

        chain_id = "chain-" + entry["repo"] + "-" + Path(entry["path"]).stem.replace("_", "-")
        source_id = "git:" + entry["owner"] + "/" + entry["repo"] + ":" + entry["path"]
        ordered = list(reversed(commits[:length]))  # oldest first
        revisions: list[dict[str, Any]] = []
        rejected_here: list[dict[str, Any]] = []

        for position, commit in enumerate(ordered):
            url = (
                "https://raw.githubusercontent.com/"
                + entry["owner"]
                + "/"
                + entry["repo"]
                + "/"
                + commit["sha"]
                + "/"
                + entry["path"]
            )
            try:
                payload = get(url)
            except (urllib.error.URLError, TimeoutError) as error:
                rejected_here.append(
                    {"sha": commit["sha"], "reason": "INELIGIBLE_FETCH", "detail": str(error)[:120]}
                )
                continue
            document = canonical_document(
                source_family="git_docs",
                source_id=source_id,
                version_id=commit["sha"],
                payload=payload,
                source_digest=sha_bytes(payload),
                known_at=commit["commit"]["committer"]["date"],
                valid_from=None,
                licence=entry["license"],
            )
            if len(document["units"]) < MIN_UNITS:
                rejected_here.append(
                    {
                        "sha": commit["sha"],
                        "reason": "INELIGIBLE_PARSE_FLOOR",
                        "units": len(document["units"]),
                    }
                )
                continue
            raw_path = raw_root / chain_id / ("%02d-%s.md" % (position, commit["sha"][:12]))
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(payload)
            canonical_path = canonical_root / chain_id / ("%02d.json" % position)
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text(canonical_json(document), encoding="utf-8")
            revisions.append(
                {
                    "position": position,
                    "version_id": commit["sha"],
                    "known_at": commit["commit"]["committer"]["date"],
                    "source_digest": document["source_digest"],
                    "raw_path": rel(raw_path),
                    "canonical_path": rel(canonical_path),
                    "canonical_sha256": canonical_sha(document),
                    "unit_count": len(document["units"]),
                }
            )

        # Positions are renumbered only after admission, so a chain never claims
        # a step between two revisions that are not actually adjacent in it.
        for index, revision in enumerate(revisions):
            revision["chain_position"] = index

        if len(revisions) < 3:
            excluded.append(
                {
                    "path": entry["path"],
                    "reason": "INELIGIBLE_CHAIN_TOO_SHORT",
                    "detail": "fewer than three admitted revisions",
                    "rejected_revisions": rejected_here,
                }
            )
            continue

        chains.append(
            {
                "chain_id": chain_id,
                "source_family": "git_docs",
                "source_id": source_id,
                "license": entry["license"],
                "redistribution": REDISTRIBUTION,
                "relation_basis": "consecutive commits touching this path, oldest first",
                "length": len(revisions),
                "revisions": revisions,
                "rejected_revisions": rejected_here,
            }
        )

    body: dict[str, Any] = {
        "schema": "tavonel.v2.chain_manifest.v1",
        "started_at": started,
        "ended_at": now(),
        "requested_length": length,
        "fetcher_sha256": sha_file(Path(__file__).resolve()),
        "canonicaliser_sha256": sha_file(
            Path(__file__).resolve().parents[1] / "canonicalization" / "canonical_document.py"
        ),
        "chain_count": len(chains),
        "revision_count": sum(chain["length"] for chain in chains),
        "step_count": sum(chain["length"] - 1 for chain in chains),
        "length_histogram": {
            str(value): sum(1 for chain in chains if chain["length"] == value)
            for value in sorted({chain["length"] for chain in chains})
        },
        "excluded": excluded,
        "chains": chains,
        "network_reads_only": True,
        "credentials_sent": False,
        "gpu_seconds": 0,
        "external_gpu_cost_usd": 0.0,
    }
    write_hashed(output, body, "receipt_sha256")
    print(
        json.dumps(
            {
                "chains": len(chains),
                "revisions": body["revision_count"],
                "steps": body["step_count"],
                "lengths": body["length_histogram"],
                "manifest": rel(output),
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--length", type=int, default=12)
    parser.add_argument("--output", type=Path, default=NS / "receipts" / "p2-chain-manifest.json")
    args = parser.parse_args()
    return run(args.length, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
