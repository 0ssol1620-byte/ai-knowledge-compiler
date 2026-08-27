#!/usr/bin/env python3
"""Write canonical documents for every acquired pair, and build the controls.

Eligibility is decided here and recorded before any equivalence result exists.
A pair excluded at this stage is written into the receipt with its reason code;
nothing is dropped silently and nothing is dropped later.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from canonical_document import canonical_document  # noqa: E402
from common import NS, ROOT, canonical_json, canonical_sha, now, rel, sha_bytes, write_hashed  # noqa: E402

MIN_UNITS = 3
CONTROL_MIN_UNITS = 6
CONTROL_TARGET = 4


def write_document(root: Path, pair_id: str, side: str, document: dict[str, Any]) -> dict[str, Any]:
    target = root / pair_id / (side + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(document), encoding="utf-8")
    return {"path": rel(target), "canonical_sha256": canonical_sha(document)}


def rotate(document: dict[str, Any]) -> dict[str, Any]:
    """The structural positive control: reading order only, text untouched.

    A deterministic rotation by ``n // 2``. Every unit keeps its exact text and
    its exact heading path, so a content-only differ sees nothing at all while
    every order-sensitive artifact must change.
    """
    units = document["units"]
    shift = len(units) // 2
    rotated = units[shift:] + units[:shift]
    renumbered = [{**unit, "ordinal": index} for index, unit in enumerate(rotated)]
    control = {
        **document,
        "version_id": document["version_id"] + "+order-rotated",
        "units": renumbered,
        "structure": {
            "order": ["/".join(unit["explicit_path"]) for unit in renumbered],
            "block_count": len(renumbered),
        },
    }
    control["source_digest"] = canonical_sha(
        {"basis": document["source_digest"], "transform": "rotate", "shift": shift}
    )
    return control


def run(split: str, manifest: Path, output: Path) -> int:
    acquisition = json.loads(manifest.read_text(encoding="utf-8"))
    root = NS / "artifacts" / split / "canonical"
    admitted: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for pair in acquisition["pairs"]:
        sides: dict[str, dict[str, Any]] = {}
        for side in ("before", "after"):
            payload = (ROOT / pair[side]["path"]).read_bytes()
            sides[side] = canonical_document(
                source_family=pair["source_family"],
                source_id=pair["source_id"],
                version_id=pair[side + "_version_id"]
                if side + "_version_id" in pair
                else pair[side]["sha256"],
                payload=payload,
                source_digest=pair[side]["sha256"],
                known_at=pair.get(side + "_known_at"),
                valid_from=pair.get("valid_from"),
                licence=pair["license"],
            )
        counts = {side: len(document["units"]) for side, document in sides.items()}
        if min(counts.values()) < MIN_UNITS:
            excluded.append(
                {
                    "pair_id": pair["pair_id"],
                    "source_family": pair["source_family"],
                    "reason": "INELIGIBLE_PARSE_FLOOR",
                    "unit_counts": counts,
                    "floor": MIN_UNITS,
                }
            )
            continue
        record = {
            "pair_id": pair["pair_id"],
            "group": "natural",
            "constructed": False,
            "source_family": pair["source_family"],
            "source_id": pair["source_id"],
            "license": pair["license"],
            "relation_basis": pair["relation_basis"],
            "before_version_id": sides["before"]["version_id"],
            "after_version_id": sides["after"]["version_id"],
            "before_source_digest": sides["before"]["source_digest"],
            "after_source_digest": sides["after"]["source_digest"],
            "unit_counts": counts,
            "before": write_document(root, pair["pair_id"], "before", sides["before"]),
            "after": write_document(root, pair["pair_id"], "after", sides["after"]),
        }
        record["before_canonical_digest"] = record["before"]["canonical_sha256"]
        record["after_canonical_digest"] = record["after"]["canonical_sha256"]
        admitted.append(record)

    # Structural positive controls. Deterministic selection: the admitted
    # natural pairs in pair_id order whose AFTER revision has enough units to
    # make a rotation observable. Chosen by that rule, not by which ones later
    # turned out interesting.
    controls: list[dict[str, Any]] = []
    for record in sorted(admitted, key=lambda item: item["pair_id"]):
        if len(controls) >= CONTROL_TARGET:
            break
        if record["unit_counts"]["after"] < CONTROL_MIN_UNITS:
            continue
        base = json.loads((ROOT / record["after"]["path"]).read_text(encoding="utf-8"))
        rotated = rotate(base)
        control_id = "ctl-" + record["pair_id"]
        controls.append(
            {
                "pair_id": control_id,
                "group": "structural_positive_control",
                "constructed": True,
                "constructed_from": record["pair_id"],
                "construction": "reading order rotated by floor(n/2); every unit text byte-identical",
                "source_family": record["source_family"],
                "source_id": record["source_id"],
                "license": record["license"],
                "relation_basis": "CONSTRUCTED -- not a natural revision relation",
                "before_version_id": base["version_id"],
                "after_version_id": rotated["version_id"],
                "before_source_digest": base["source_digest"],
                "after_source_digest": rotated["source_digest"],
                "unit_counts": {
                    "before": len(base["units"]),
                    "after": len(rotated["units"]),
                },
                "before": write_document(root, control_id, "before", base),
                "after": write_document(root, control_id, "after", rotated),
            }
        )
        controls[-1]["before_canonical_digest"] = controls[-1]["before"]["canonical_sha256"]
        controls[-1]["after_canonical_digest"] = controls[-1]["after"]["canonical_sha256"]
        # The control must actually be text-identical, or it is not the case it
        # claims to be. Checked here rather than asserted in prose.
        before_texts = sorted(unit["text_sha256"] for unit in base["units"])
        after_texts = sorted(unit["text_sha256"] for unit in rotated["units"])
        if before_texts != after_texts:
            raise SystemExit("control construction changed unit text: " + control_id)
        if base["structure"]["order"] == rotated["structure"]["order"]:
            raise SystemExit("control construction did not change order: " + control_id)

    body: dict[str, Any] = {
        "schema": "tavonel.v2.canonicalisation_manifest.v1",
        "split": split,
        "generated_at": now(),
        "protocol_sha256": json.loads(
            (NS / "receipts" / "p0-protocol-freeze.json").read_text(encoding="utf-8")
        )["protocol_sha256"],
        "acquisition_manifest": rel(manifest),
        "acquisition_manifest_file_sha256": sha_bytes(manifest.read_bytes()),
        "canonicaliser_sha256": sha_bytes(
            (Path(__file__).resolve().parent / "canonical_document.py").read_bytes()
        ),
        "driver_sha256": sha_bytes(Path(__file__).resolve().read_bytes()),
        "unit_floor": MIN_UNITS,
        "natural_pair_count": len(admitted),
        "control_pair_count": len(controls),
        "family_counts": {
            family: sum(1 for item in admitted if item["source_family"] == family)
            for family in sorted({item["source_family"] for item in admitted})
        },
        "source_lineage_count": len({item["source_id"] for item in admitted}),
        "excluded": excluded,
        "pairs": [*admitted, *controls],
        "gpu_seconds": 0,
        "external_gpu_cost_usd": 0.0,
    }
    write_hashed(output, body, "receipt_sha256")
    print(
        json.dumps(
            {
                "natural": len(admitted),
                "controls": len(controls),
                "excluded": len(excluded),
                "families": body["family_counts"],
                "lineages": body["source_lineage_count"],
                "manifest": rel(output),
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="development")
    parser.add_argument(
        "--manifest", type=Path, default=NS / "receipts" / "p0-acquisition-manifest.json"
    )
    parser.add_argument(
        "--output", type=Path, default=NS / "receipts" / "p0-canonicalisation-manifest.json"
    )
    args = parser.parse_args()
    return run(args.split, args.manifest, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
