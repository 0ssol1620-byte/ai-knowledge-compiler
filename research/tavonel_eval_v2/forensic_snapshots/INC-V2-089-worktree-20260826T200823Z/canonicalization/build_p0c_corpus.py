#!/usr/bin/env python3
"""Build the P0c corpus: the P0b corpus plus the three declared controls.

The P0b pairs are carried through by reference and are not rebuilt, re-parsed or
re-canonicalised. Only the controls are constructed here, and each one is
verified at construction rather than assumed:

* ``unclassified_access_probe`` — the after revision of a natural pair with an
  extra unit field the projection map does not name. Verified: the field is
  present on every unit, and no other field moved.
* ``unclassified_source_change_positive`` — the after revision with only
  ``source_digest`` perturbed. Verified: every unit is byte-identical, so no
  projection can move, and the digest differs.
* ``unclassified_source_change_negative`` — the after revision paired with
  itself. Verified: digest and units both unchanged.

A control that fails its own construction check is excluded and recorded, never
quietly repaired into shape.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from common import NS, ROOT, canonical_sha, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

OUT = NS / "artifacts" / "development" / "canonical_p0c"
PROBE_FIELD = "unmapped_probe_field"
CONTROL_SOURCES = 3


def load(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def emit(pair_id: str, side: str, document: dict[str, Any]) -> dict[str, str]:
    target = OUT / pair_id / (side + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {"path": rel(target), "canonical_sha256": canonical_sha(document)}


def with_probe_field(document: dict[str, Any], pair_id: str) -> dict[str, Any]:
    made = copy.deepcopy(document)
    made["source_id"] = document["source_id"] + "#p0c-probe"
    for index, unit in enumerate(made["units"]):
        unit[PROBE_FIELD] = "probe-" + pair_id + "-" + str(index)
    return made


def probe_field_only_change(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Every unit gained the probe field and nothing else moved."""
    if len(before["units"]) != len(after["units"]):
        return False
    for left, right in zip(before["units"], after["units"], strict=True):
        if PROBE_FIELD not in right:
            return False
        stripped = {key: value for key, value in right.items() if key != PROBE_FIELD}
        if stripped != left:
            return False
    return True


def perturb_source_digest(document: dict[str, Any]) -> dict[str, Any]:
    made = copy.deepcopy(document)
    made["source_digest"] = "sha256:" + ("c0" * 32)
    return made


def units_identical(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return before["units"] == after["units"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--upstream", type=Path, default=NS / "receipts" / "p0b-corpus-manifest.json"
    )
    args = parser.parse_args()

    upstream = json.loads(args.upstream.read_text(encoding="utf-8"))
    natural = [pair for pair in upstream["pairs"] if pair["group"] == "natural"]

    pairs: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    # carried through by reference, not rebuilt
    for pair in upstream["pairs"]:
        pairs.append({**pair, "corpus": "p0b", "constructed_in_p0c": False})

    donors = natural[:CONTROL_SOURCES]

    for index, donor in enumerate(donors):
        after = load(donor["after"]["path"])

        # 1. unclassified access probe
        pair_id = "probe-%03d-%s" % (index, donor["pair_id"])
        before_doc = with_probe_field(after, pair_id)
        after_doc = copy.deepcopy(before_doc)
        if not probe_field_only_change(after, before_doc):
            excluded.append({"pair_id": pair_id, "reason": "INELIGIBLE_PROBE_CONSTRUCTION"})
        else:
            pairs.append(
                {
                    "pair_id": pair_id,
                    "group": "unclassified_access_probe",
                    "corpus": "p0c",
                    "constructed_in_p0c": True,
                    "source_id": before_doc["source_id"],
                    "source_family": donor["source_family"],
                    "derived_from": donor["pair_id"],
                    "construction": (
                        "the donor's after revision, with one extra unit field the "
                        "projection map does not name, on both sides"
                    ),
                    "verified_at_construction": {
                        "probe_field_present_on_every_unit": True,
                        "no_other_field_moved": True,
                    },
                    "expect": (
                        "coverage-probe records UNCLASSIFIED, coverage_proven false, "
                        "never carried"
                    ),
                    "before": emit(pair_id, "before", before_doc),
                    "after": emit(pair_id, "after", after_doc),
                    "unit_counts": {
                        "before": len(before_doc["units"]),
                        "after": len(after_doc["units"]),
                    },
                    "license": donor.get("license"),
                }
            )

        # 2. unclassified source change, positive
        pair_id = "usc-pos-%03d-%s" % (index, donor["pair_id"])
        before_doc = copy.deepcopy(after)
        after_doc = perturb_source_digest(after)
        ok = units_identical(before_doc, after_doc) and (
            before_doc["source_digest"] != after_doc["source_digest"]
        )
        if not ok:
            excluded.append({"pair_id": pair_id, "reason": "INELIGIBLE_USC_CONSTRUCTION"})
        else:
            pairs.append(
                {
                    "pair_id": pair_id,
                    "group": "unclassified_source_change_positive",
                    "corpus": "p0c",
                    "constructed_in_p0c": True,
                    "source_id": after_doc["source_id"],
                    "source_family": donor["source_family"],
                    "derived_from": donor["pair_id"],
                    "construction": (
                        "the donor's after revision on both sides, with only "
                        "source_digest perturbed"
                    ),
                    "verified_at_construction": {
                        "every_unit_byte_identical": True,
                        "source_digest_differs": True,
                    },
                    "expect": (
                        "UNCLASSIFIED_SOURCE_CHANGE fires; no proven-coverage "
                        "artifact rebuilt; equivalent to the full rebuild"
                    ),
                    "before": emit(pair_id, "before", before_doc),
                    "after": emit(pair_id, "after", after_doc),
                    "unit_counts": {
                        "before": len(before_doc["units"]),
                        "after": len(after_doc["units"]),
                    },
                    "license": donor.get("license"),
                }
            )

        # 3. unclassified source change, negative
        pair_id = "usc-neg-%03d-%s" % (index, donor["pair_id"])
        before_doc = copy.deepcopy(after)
        after_doc = copy.deepcopy(after)
        if before_doc["source_digest"] != after_doc["source_digest"]:
            excluded.append({"pair_id": pair_id, "reason": "INELIGIBLE_NEGATIVE_CONTROL"})
        else:
            pairs.append(
                {
                    "pair_id": pair_id,
                    "group": "unclassified_source_change_negative",
                    "corpus": "p0c",
                    "constructed_in_p0c": True,
                    "source_id": after_doc["source_id"],
                    "source_family": donor["source_family"],
                    "derived_from": donor["pair_id"],
                    "construction": "the donor's after revision paired with itself",
                    "verified_at_construction": {
                        "source_digest_unchanged": True,
                        "every_unit_byte_identical": True,
                    },
                    "expect": "the diagnostic does not fire",
                    "before": emit(pair_id, "before", before_doc),
                    "after": emit(pair_id, "after", after_doc),
                    "unit_counts": {
                        "before": len(before_doc["units"]),
                        "after": len(after_doc["units"]),
                    },
                    "license": donor.get("license"),
                }
            )

    groups: dict[str, int] = {}
    for pair in pairs:
        groups[pair["group"]] = groups.get(pair["group"], 0) + 1

    body = {
        "schema": "tavonel.v2.p0c_corpus_manifest.v1",
        "protocol": "P0c_coverage_completeness",
        "upstream_manifest": rel(args.upstream),
        "upstream_manifest_file_sha256": sha_file(args.upstream),
        "upstream_use": (
            "P0b pairs are carried through by reference. They are not rebuilt, "
            "re-parsed or re-canonicalised, so P0b's corpus is unchanged by this."
        ),
        "builder_sha256": sha_file(Path(__file__).resolve()),
        "pair_count": len(pairs),
        "group_counts": groups,
        "excluded": excluded,
        "pairs": pairs,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    written = write_immutable(
        "p0c-corpus-manifest",
        body,
        tool=Path(__file__).resolve(),
        protocol=NS / "protocols" / "P0c_coverage_completeness.yaml",
    )
    print(json.dumps({"pairs": len(pairs), "groups": groups, **written}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
