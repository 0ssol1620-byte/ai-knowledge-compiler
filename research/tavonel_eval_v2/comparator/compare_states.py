#!/usr/bin/env python3
"""Compare two independently produced active states.

Imports neither build path and neither build path imports it. Standard library
only, so the comparison cannot inherit a helper from the side it is judging.

The comparison is over canonicalised artifact ids and digests, which is the one
thing protocol section 8.4 permits the two sides to share.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

BLOCKED = ("akc_cir", "selective_build", "independent_full_build", "common")


class ComparatorIsolationBreach(ImportError):
    pass


class Guard:
    triggered: list[str] = []

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        if fullname.split(".")[0] in BLOCKED:
            Guard.triggered.append(fullname)
            raise ComparatorIsolationBreach("the comparator may not import " + fullname)
        return None


sys.meta_path.insert(0, Guard())


def digest(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compare(selective: dict[str, Any], oracle: dict[str, Any]) -> dict[str, Any]:
    left = selective["state"]
    right = oracle["state"]

    only_selective = sorted(set(left) - set(right))
    only_oracle = sorted(set(right) - set(left))
    shared = sorted(set(left) & set(right))
    diverged = [key for key in shared if left[key] != right[key]]

    carried = set(selective.get("carried_forward_set", ()))
    rebuilt = set(selective.get("selective_rebuild_set", ()))

    # A stale escape is the failure this whole comparison exists to detect: an
    # artifact the selective path decided not to rebuild, whose bytes the full
    # rebuild says should have changed.
    stale_escapes = sorted(key for key in diverged if key in carried)
    wrong_rebuilds = sorted(key for key in diverged if key in rebuilt)

    equal = not only_selective and not only_oracle and not diverged
    return {
        "equivalent": equal,
        "selective_state_hash": selective["state_hash"],
        "oracle_state_hash": oracle["state_hash"],
        "state_hash_equal": selective["state_hash"] == oracle["state_hash"],
        "artifact_count_selective": len(left),
        "artifact_count_oracle": len(right),
        "missing_from_selective": only_oracle,
        "extra_in_selective": only_selective,
        "diverged": sorted(diverged),
        "stale_left_behind": stale_escapes,
        "wrongly_rebuilt": wrong_rebuilds,
        "unplanned_missing": sorted(selective.get("unplanned_missing", ())),
        "per_artifact_difference": [
            {"artifact": key, "selective": left[key], "oracle": right[key]}
            for key in sorted(diverged)
        ],
        "comparator_guard_triggered_on": list(Guard.triggered),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selective", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    selective = json.loads(args.selective.read_text(encoding="utf-8"))
    oracle = json.loads(args.oracle.read_text(encoding="utf-8"))
    result = compare(selective, oracle)
    result["comparator_sha256"] = (
        "sha256:" + hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"equivalent": result["equivalent"]}))
    return 0 if result["equivalent"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
