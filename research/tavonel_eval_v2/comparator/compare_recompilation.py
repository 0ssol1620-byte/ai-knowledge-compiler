#!/usr/bin/env python3
"""The third party. ORACLE_INDEPENDENCE_V2 section 3.

Imports neither the engine nor the oracle, and neither imports it. Standard
library only, so the comparison cannot inherit a helper from a side it judges.

It is also the only process here that hashes anything that matters. Both sides
emit artifact CONTENT keyed by a portable identity; this module encodes and
digests it with its own implementation. If either side hashed the comparison,
that side would be the standard, and the whole arrangement would be one
implementation checking itself with extra steps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any

BLOCKED = (
    "akc_cir",
    "selective_build",
    "source_derived_expected",
    "independent_full_build",
    "canonical_document",
    "changed_regions",
    "common",
    "evidence",
)


class ComparatorIsolationBreach(ImportError):
    pass


class Guard:
    triggered: list[str] = []

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        if fullname.split(".")[0] in BLOCKED:
            Guard.triggered.append(fullname)
            raise ComparatorIsolationBreach("the comparator may not import " + fullname)
        return None


_GUARD = Guard()
sys.meta_path.insert(0, _GUARD)


def digest(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fingerprint(state: dict[str, Any]) -> dict[str, str]:
    return {key: digest(value) for key, value in state.items()}


#: Which engine change kinds are consistent with which oracle type. An engine
#: that reports more than the oracle typed is not wrong here — it may be
#: reacting to something the oracle does not model — so the test is one-sided:
#: the oracle's positive claims must be present on the engine side.
REQUIRED_ENGINE_SIGNAL = {
    "structural_only": {"structural_change_present": True},
    "lexical_only": {"structural_change_present": False},
}


def compare(engine: dict[str, Any], oracle: dict[str, Any]) -> dict[str, Any]:
    """One pair. Neither side's digests are trusted; content is re-hashed here."""
    if not oracle.get("judgeable", False):
        return {
            "verdict": "UNJUDGED",
            "why": oracle.get("unresolved", ["oracle could not derive a state"]),
            "equivalent": None,
            "stale_escapes": [],
            "stale_escape_count": 0,
            "false_pass": False,
        }

    left = fingerprint(engine["portable_state"])
    right = fingerprint(oracle["expected_state"])

    only_engine = sorted(set(left) - set(right))
    only_oracle = sorted(set(right) - set(left))
    shared = sorted(set(left) & set(right))
    diverged = [key for key in shared if left[key] != right[key]]

    carried = set(engine.get("portable_carried_forward", ()))
    must_change = set(oracle.get("must_change", ()))

    #: the failure this comparison exists to detect: the oracle says the key had
    #: to change and the engine carried the old value forward.
    stale = sorted(key for key in must_change if key in carried)

    engine_type = {
        "structural_change_present": bool(engine.get("structural_change_present")),
        "detected_change_kinds": list(engine.get("detected_change_kinds", ())),
    }
    label = oracle["change_type"]["label"]
    required = REQUIRED_ENGINE_SIGNAL.get(label)
    typed_consistent: Any = "NOT_TESTED"
    if required is not None:
        typed_consistent = all(
            engine_type.get(key) == value for key, value in required.items()
        )

    equivalent = not (only_engine or only_oracle or diverged)
    return {
        "verdict": "EQUIVALENT" if equivalent else "DIVERGENT",
        "equivalent": equivalent,
        "only_engine": only_engine[:8],
        "only_engine_count": len(only_engine),
        "only_oracle": only_oracle[:8],
        "only_oracle_count": len(only_oracle),
        "diverged": diverged[:8],
        "diverged_count": len(diverged),
        "shared_count": len(shared),
        "stale_escapes": stale[:8],
        "stale_escape_count": len(stale),
        "oracle_change_type": label,
        "oracle_change_detail": oracle["change_type"],
        "engine_change_signal": engine_type,
        "typed_invalidation_consistent": typed_consistent,
        "false_pass": False,
        "comparator_state_digest": {
            "engine": digest(left),
            "oracle": digest(right),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    parser.add_argument("--oracle", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()

    with open(arguments.engine, encoding="utf-8") as handle:
        engine = json.load(handle)
    with open(arguments.oracle, encoding="utf-8") as handle:
        oracle = json.load(handle)

    result = compare(engine, oracle)
    result["comparator"] = "compare_recompilation.v2"
    result["comparator_isolation"] = {
        "armed": _GUARD in sys.meta_path,
        "blocked_prefixes": list(BLOCKED),
        "triggered": list(Guard.triggered),
        "project_modules_imported": sorted(
            name for name in sys.modules if name.split(".")[0] in BLOCKED
        ),
        "isolated": sys.flags.isolated,
        "no_site": sys.flags.no_site,
    }
    with open(arguments.output, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps({"verdict": result["verdict"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
