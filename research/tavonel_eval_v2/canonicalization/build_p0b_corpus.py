#!/usr/bin/env python3
"""Assemble the P0b corpus: the P0 v1 canonical documents plus lexical controls.

The P0 v1 canonical documents are read as INPUT ONLY. No P0 v1 result, plan,
state, comparison or receipt is opened, and nothing under the P0 v1 output roots
is written.

The lexical positive control is the measurement that separates facet-typed
invalidation from both alternatives the founder rejected. It is constructed, and
its construction is verified rather than asserted: every unit's LEXICAL
projection must move and every unit's SEMANTIC projection must not. A
construction that fails either check is excluded with a reason code instead of
being quietly repaired.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "facets"))

from common import NS, ROOT, canonical_json, canonical_sha, now, rel, sha_file, write_hashed  # noqa: E402
from facets import LEXICAL, SEMANTIC, project  # noqa: E402

LEXICAL_CONTROL_TARGET = 4
LEXICAL_CONTROL_MIN_UNITS = 4


def upper_case_units(document: dict[str, Any]) -> dict[str, Any]:
    """Case-only perturbation: the edit class that escaped P0 v1."""
    units = [{**unit, "text": unit["text"].upper()} for unit in document["units"]]
    control = {
        **document,
        "version_id": document["version_id"] + "+case-raised",
        "units": units,
    }
    control["source_digest"] = canonical_sha(
        {"basis": document["source_digest"], "transform": "upper", "facet": LEXICAL}
    )
    return control


def lexically_invariant(before: dict[str, Any], after: dict[str, Any]) -> tuple[bool, str]:
    if len(before["units"]) != len(after["units"]):
        return False, "unit count changed"
    for left, right in zip(before["units"], after["units"]):
        if project(SEMANTIC, left) != project(SEMANTIC, right):
            return False, "semantic projection moved for " + "/".join(left["explicit_path"])
        if project(LEXICAL, left) == project(LEXICAL, right):
            return False, "lexical projection did not move for " + "/".join(left["explicit_path"])
    return True, ""


def write_document(root: Path, pair_id: str, side: str, document: dict[str, Any]) -> dict[str, Any]:
    target = root / pair_id / (side + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(document), encoding="utf-8")
    return {"path": rel(target), "canonical_sha256": canonical_sha(document)}


def run(source_manifest: Path, output: Path) -> int:
    upstream = json.loads(source_manifest.read_text(encoding="utf-8"))
    root = NS / "artifacts" / "development" / "canonical_p0b"

    pairs: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for record in upstream["pairs"]:
        pairs.append(
            {
                key: record[key]
                for key in (
                    "pair_id",
                    "group",
                    "constructed",
                    "source_family",
                    "source_id",
                    "license",
                    "relation_basis",
                    "before_version_id",
                    "after_version_id",
                    "before_source_digest",
                    "after_source_digest",
                    "unit_counts",
                    "before",
                    "after",
                    "before_canonical_digest",
                    "after_canonical_digest",
                )
            }
        )

    natural = [item for item in pairs if item["group"] == "natural"]
    for record in sorted(natural, key=lambda item: item["pair_id"]):
        if len([item for item in pairs if item["group"] == "lexical_positive_control"]) >= (
            LEXICAL_CONTROL_TARGET
        ):
            break
        if record["unit_counts"]["after"] < LEXICAL_CONTROL_MIN_UNITS:
            continue
        base = json.loads((ROOT / record["after"]["path"]).read_text(encoding="utf-8"))
        control = upper_case_units(base)
        ok, why = lexically_invariant(base, control)
        control_id = "lex-" + record["pair_id"]
        if not ok:
            excluded.append(
                {
                    "pair_id": control_id,
                    "reason": "INELIGIBLE_NOT_LEXICALLY_INVARIANT",
                    "detail": why,
                }
            )
            continue
        entry = {
            "pair_id": control_id,
            "group": "lexical_positive_control",
            "constructed": True,
            "constructed_from": record["pair_id"],
            "construction": (
                "every unit text upper-cased; verified that every LEXICAL projection "
                "moved and every SEMANTIC projection did not"
            ),
            "source_family": record["source_family"],
            "source_id": record["source_id"],
            "license": record["license"],
            "relation_basis": "CONSTRUCTED -- not a natural revision relation",
            "before_version_id": base["version_id"],
            "after_version_id": control["version_id"],
            "before_source_digest": base["source_digest"],
            "after_source_digest": control["source_digest"],
            "unit_counts": {"before": len(base["units"]), "after": len(control["units"])},
            "before": write_document(root, control_id, "before", base),
            "after": write_document(root, control_id, "after", control),
        }
        entry["before_canonical_digest"] = entry["before"]["canonical_sha256"]
        entry["after_canonical_digest"] = entry["after"]["canonical_sha256"]
        pairs.append(entry)

    counts = {
        group: sum(1 for item in pairs if item["group"] == group)
        for group in sorted({item["group"] for item in pairs})
    }
    body: dict[str, Any] = {
        "schema": "tavonel.v2.p0b_corpus_manifest.v1",
        "generated_at": now(),
        "protocol_sha256": json.loads(
            (NS / "receipts" / "p0b-protocol-freeze.json").read_text(encoding="utf-8")
        )["protocol_sha256"],
        "upstream_manifest": rel(source_manifest),
        "upstream_manifest_file_sha256": sha_file(source_manifest),
        "upstream_use": "canonical documents read as input only; no P0 v1 result was read",
        "builder_sha256": sha_file(Path(__file__).resolve()),
        "group_counts": counts,
        "source_lineage_count": len(
            {item["source_id"] for item in pairs if item["group"] == "natural"}
        ),
        "family_counts": {
            family: sum(
                1
                for item in pairs
                if item["group"] == "natural" and item["source_family"] == family
            )
            for family in sorted(
                {item["source_family"] for item in pairs if item["group"] == "natural"}
            )
        },
        "excluded": excluded,
        "pairs": pairs,
        "gpu_seconds": 0,
        "external_gpu_cost_usd": 0.0,
    }
    write_hashed(output, body, "receipt_sha256")
    print(json.dumps({"groups": counts, "excluded": len(excluded), "manifest": rel(output)}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path, default=NS / "receipts" / "p0-canonicalisation-manifest.json"
    )
    parser.add_argument(
        "--output", type=Path, default=NS / "receipts" / "p0b-corpus-manifest.json"
    )
    args = parser.parse_args()
    return run(args.source, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
