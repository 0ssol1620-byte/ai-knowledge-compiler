#!/usr/bin/env python3
"""Stage the frozen 800-page holdout as a Stage-1 input slice.

Same shape as the hard-200 slice the discovery run used, so the existing bundle
builder, READY generator and controller stack apply unchanged. Inputs are
hardlinked and named by case id -- the GPU pod must not be able to identify
which benchmark page it is parsing, which is what keeps the run source-only.

Nothing is selected here. The page list comes from the frozen holdout manifest
and every hash is re-verified against it; a mismatch refuses rather than
restages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--parent-manifest", type=Path, required=True)
    parser.add_argument("--parent-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    holdout = json.loads(args.holdout.resolve().read_text(encoding="utf-8"))
    if holdout.get("status") != "FROZEN":
        raise SystemExit(f"holdout is {holdout.get('status')}, not FROZEN")
    parent = json.loads(args.parent_manifest.resolve().read_text(encoding="utf-8"))
    parent_by_case = {entry["case_id"]: entry for entry in parent["inputs"]}

    output = args.output_dir.resolve()
    inputs = output / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)

    staged: list[dict[str, Any]] = []
    methods = {"hardlink": 0, "copy": 0}
    for record in holdout["pages"]:
        entry = parent_by_case[record["case_id"]]
        source = (args.parent_root.resolve() / entry["input_relative_path"]).resolve()
        observed = sha256_file(source)
        if observed != record["input_sha256"]:
            raise SystemExit(f"hash drift for {record['image_path']}")
        target = inputs / source.name
        if not target.exists():
            try:
                os.link(source, target)
                methods["hardlink"] += 1
            except OSError:
                shutil.copy2(source, target)
                methods["copy"] += 1
        staged.append(
            {
                "case_id": entry["case_id"],
                "input_relative_path": f"inputs/{source.name}",
                "input_sha256": f"sha256:{observed}",
                "media_type": entry["media_type"],
                "page_index": entry["page_index"],
                "source_relative_path": entry["source_relative_path"],
                "source_sha256": entry["source_sha256"],
            }
        )

    staged.sort(key=lambda entry: entry["case_id"])
    # Same schema as the hard-200 shard, so the sealed bundle builder, the READY
    # generator and the controller stack all apply without modification. The
    # holdout identity is carried in a separate sidecar rather than added as a
    # field here, because an unexpected key would change content_sha256 and the
    # builder verifies that hash against the shard schema it knows.
    manifest = {
        "benchmark_id": parent["benchmark_id"],
        "complete_input_coverage": True,
        "complete_source_coverage": False,
        "dataset_revision": parent["dataset_revision"],
        "ground_truth_mounted": False,
        "input_count": len(staged),
        "inputs": staged,
        "parent_input_manifest_sha256": parent["content_sha256"],
        "schema": "folynta.public-core-inference-shard.v1",
        "shard_count": 1,
        "shard_index": 0,
        "source_count": parent["source_count"],
    }
    manifest["content_sha256"] = canonical_sha256(dict(manifest))
    (output / "inference-input-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    sidecar = {
        "schema": "tavonel.a9-holdout-slice-provenance.v1",
        "role": "a9_confirmatory_holdout",
        "generated_at": datetime.now(UTC).isoformat(),
        "shard_content_sha256": manifest["content_sha256"],
        "holdout_manifest_sha256": "sha256:"
        + hashlib.sha256(args.holdout.resolve().read_bytes()).hexdigest(),
        "page_count": len(staged),
        "document_count": holdout["document_count"],
    }
    (output / "holdout-provenance.json").write_text(
        json.dumps(sidecar, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"staged {len(staged)} inputs  ({methods})")
    print(f"content_sha256: {manifest['content_sha256']}")
    print(f"slice: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
