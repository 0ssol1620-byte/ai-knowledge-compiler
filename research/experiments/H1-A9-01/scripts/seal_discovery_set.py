#!/usr/bin/env python3
"""Seal the 198-page discovery set so the confirmatory test cannot reuse it.

Every operating point in A9 was chosen after looking at these pages. That makes
them unusable as confirmatory evidence -- not because the numbers are wrong, but
because the selection already spent their evidential value. Sealing is the act
that makes the distinction enforceable rather than a promise: the manifest below
names each page and hashes each prediction, so a later run that quietly includes
one of them can be caught by comparison instead of by memory.

This does not delete or move anything. The discovery set stays exactly where it
is and stays citable as an effect *estimate*. What the seal forbids is counting
it toward the confirmatory endpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--run-a-predictions", type=Path, required=True)
    parser.add_argument("--run-a-artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    edit = json.loads(
        (args.run_a_artifacts.resolve() / "text_block_per_page_edit.json").read_text(
            encoding="utf-8"
        )
    )
    samples = json.loads(args.ground_truth.resolve().read_text(encoding="utf-8"))

    pages = []
    excluded = []
    for sample in samples:
        image = str(sample["page_info"]["image_path"])
        prediction = args.run_a_predictions.resolve() / f"{Path(image).stem}.md"
        if image not in edit:
            excluded.append(image)
            continue
        pages.append(
            {
                "image_path": image,
                "prediction_sha256": sha256(prediction),
                "official_text_edit_distance": float(edit[image]),
            }
        )

    manifest = {
        "schema": "tavonel.a9-discovery-set-seal.v1",
        "sealed_on": "2026-08-18",
        "experiment_id": "H1-A9-01",
        "what_this_forbids": (
            "These pages may be cited as an effect estimate. They may not be "
            "counted toward the confirmatory endpoint, and no threshold may be "
            "re-tuned on them and then reported as confirmed."
        ),
        "page_count": len(pages),
        "excluded_without_an_official_page_score": sorted(excluded),
        "pages": sorted(pages, key=lambda p: p["image_path"]),
    }
    body = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(body, encoding="utf-8")
    print(f"sealed {len(pages)} pages, {len(excluded)} excluded")
    print(f"manifest sha256: {hashlib.sha256(body.encode('utf-8')).hexdigest()}")
    print(f"receipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
