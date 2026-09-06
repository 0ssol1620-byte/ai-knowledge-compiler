#!/usr/bin/env python3
"""Select the v8 holdout titles. Deterministic, and blind to their content.

`W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md` §6. The frozen v3 manifest carries
6,987 candidate titles in a hash order fixed on 2026-08-18, before any of this
was designed. The v7 seal records the **750** titles v7 fetched, resolved to, or
excluded. This script writes the same manifest with those 750 removed, order
otherwise untouched.

**It reads titles and nothing else.** No revision is fetched, no article body is
read, no attribute is inspected. Selection cannot be conditioned on an outcome
because at this point no outcome exists --- which is the only sense in which a
holdout is untouched.

**The guard is fail-closed, and it has failed open before.** An earlier version
read the wrong key from the seal, so the development-title set came back empty
and the filter removed nothing while reporting success. A seal that records no
development titles is now a refusal, not an empty exclusion list: an inert guard
is worse than no guard, because it produces a receipt saying the check passed.

The output keeps `tavonel.w6-v3-title-manifest.v1`'s shape, including the v3
protocol and acquisition-script digests, so the existing v5 transport freeze
verifies it without a new code path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[2]
RECEIPTS = EXP / "receipts"
SEAL = RECEIPTS / "v7-development-seal-2026-08-19.json"
SOURCE_MANIFEST = RECEIPTS / "title-manifest-v3-2026-08-19.json"
FREEZE = RECEIPTS / "v8-config-freeze.json"
OUTPUT = RECEIPTS / "holdout-manifest-v8.json"


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_title(title: str) -> str:
    """The v3 normalization, restated: NFC, underscores to spaces, collapsed space."""
    return " ".join(unicodedata.normalize("NFC", title).replace("_", " ").split())


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def development_titles(seal: dict[str, Any]) -> set[str]:
    """The sealed v7 title list. An empty list is a refusal, never an empty filter."""
    block = seal.get("development_titles_excluded_from_v8") or {}
    titles = block.get("titles") or []
    if not titles:
        raise SystemExit(
            "the seal records no development titles. The overlap guard would remove "
            "nothing and report success, which is how a contaminated holdout passes. "
            "Refusing.")
    if block.get("count") is not None and block["count"] != len(titles):
        raise SystemExit(
            f"the seal's count ({block['count']}) disagrees with the list it carries "
            f"({len(titles)}); resolve the seal before selecting a holdout")
    return {normalize_title(t) for t in titles}


def select(source: dict[str, Any], excluded: set[str]) -> tuple[list[dict[str, Any]],
                                                                list[str]]:
    """Filter, preserving the frozen order and reindexing only for readability."""
    kept: list[dict[str, Any]] = []
    removed: list[str] = []
    for row in source["titles"]:
        if normalize_title(row["title"]) in excluded:
            removed.append(row["title"])
            continue
        kept.append({"index": len(kept), "order_key": row["order_key"],
                     "title": row["title"]})
    return kept, removed


def build(*, source: dict[str, Any], seal: dict[str, Any], freeze: dict[str, Any] | None,
          kept: list[dict[str, Any]], removed: list[str]) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        # v3-compatible fields, so the frozen v5 transport freeze verifies this
        # manifest without a second code path.
        "schema": "tavonel.w6-v3-title-manifest.v1",
        "api": source["api"],
        "normalization": source["normalization"],
        "ordering": source["ordering"],
        "selection_rule": source["selection_rule"],
        "source_category": source["source_category"],
        "source_counts_observed_until_selection":
            source["source_counts_observed_until_selection"],
        "protocol_sha256": source["protocol_sha256"],
        "acquisition_script_sha256": source["acquisition_script_sha256"],
        "max_candidates_consumable": source["max_candidates_consumable"],
        "candidate_count": len(kept),
        "titles": kept,
        "generated_at": datetime.now(UTC).isoformat(),
        "external_gpu_cost_usd": 0.0,

        # v8 holdout provenance
        "holdout": {
            "schema": "tavonel.w6-v8-holdout-selection.v1",
            "run_class": "HOLDOUT_CONFIRMATORY",
            "source_manifest": SOURCE_MANIFEST.name,
            "source_manifest_sha256": file_sha256(SOURCE_MANIFEST),
            "source_candidate_count": source["candidate_count"],
            "seal": SEAL.name,
            "seal_sha256": file_sha256(SEAL),
            "seal_receipt_sha256": seal.get("seal_sha256"),
            "development_titles_removed": len(removed),
            "untouched_candidate_count": len(kept),
            "overlap_with_development_after_filter": 0,
            "order": "unchanged from the frozen v3 hash order; only removal and "
                     "reindexing were applied",
            "content_inspected": False,
            "content_inspected_note":
                "no revision was fetched and no article body was read while selecting. "
                "Selection is a function of the frozen order and the sealed exclusion "
                "list only.",
            "config_freeze_sha256": (freeze or {}).get("receipt_sha256"),
            "config_freeze_frozen_at": (freeze or {}).get("frozen_at"),
        },
    }
    manifest["receipt_sha256"] = canonical_sha256(manifest)
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, default=OUTPUT)
    ap.add_argument("--source-manifest", type=Path, default=SOURCE_MANIFEST)
    ap.add_argument("--seal", type=Path, default=SEAL)
    ap.add_argument("--require-freeze", action="store_true", default=True,
                    help="refuse without a config freeze; the holdout opens after the "
                         "lock, never before")
    ap.add_argument("--allow-without-freeze", dest="require_freeze",
                    action="store_false",
                    help="for tests only: exercise selection without the real freeze")
    args = ap.parse_args()

    if args.output.exists():
        existing = read_json(args.output)
        print(f"a holdout manifest already exists, generated at "
              f"{existing.get('generated_at')}")
        body = {k: v for k, v in existing.items() if k != "receipt_sha256"}
        intact = canonical_sha256(body) == existing.get("receipt_sha256")
        print(f"candidates: {existing.get('candidate_count')}")
        print("MANIFEST INTACT" if intact else "MANIFEST BROKEN")
        return 0 if intact else 1

    freeze = read_json(FREEZE) if FREEZE.exists() else None
    if args.require_freeze and not freeze:
        print("refusing: there is no v8 config freeze. Selecting holdout titles before "
              "the lock exists would leave every pinned value adjustable afterwards.")
        return 2
    if freeze and freeze.get("holdout_status") != "UNOPENED":
        print(f"refusing: the freeze records holdout_status="
              f"{freeze.get('holdout_status')}. A holdout is opened once.")
        return 2

    source = read_json(args.source_manifest)
    seal = read_json(args.seal)
    excluded = development_titles(seal)
    kept, removed = select(source, excluded)

    if len(removed) != len(excluded):
        # Not fatal by itself --- a sealed title may not be in the manifest, which is
        # exactly what "v7 resolved to" can produce --- but it is recorded, because a
        # silent difference between "excluded" and "removed" is how a filter drifts.
        print(f"note: the seal lists {len(excluded)} normalized development titles and "
              f"{len(removed)} were present in the source manifest")
    remaining = {normalize_title(r["title"]) for r in kept} & excluded
    if remaining:
        print(f"refusing: {len(remaining)} development titles survived the filter")
        return 3

    manifest = build(source=source, seal=seal, freeze=freeze, kept=kept, removed=removed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"source candidates   : {source['candidate_count']}")
    print(f"development removed : {len(removed)}")
    print(f"untouched candidates: {len(kept)}")
    print("overlap after filter: 0")
    print(f"wrote {args.output.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
