"""Download the pinned PP-DocLayoutV3 layout model the glmocr pipeline needs.

The GLM-OCR SDK's document-parsing pipeline is two models, not one: the MIT-licensed
GLM-OCR checkpoint and Apache-2.0 ``PaddlePaddle/PP-DocLayoutV3_safetensors`` for
layout analysis. The second is pinned and hashed exactly like the first, because a
floating layout model would make the pipeline unreproducible while looking healthy.

Reads ``runtime.json``'s ``inference_config.layout_model_*`` keys and writes
``<layout_model_dir>/.arena_layout.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from arena.worker.compat import UTC

RUNTIME_JSON = Path(__file__).resolve().parent / "runtime.json"
SIDECAR_NAME = ".arena_layout.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--layout-dir",
        type=Path,
        default=None,
        help="override runtime.json's layout_model_dir (used by bootstrap mode)",
    )
    args = parser.parse_args(argv)

    config = json.loads(RUNTIME_JSON.read_text(encoding="utf-8"))["inference_config"]
    repo: str = config["layout_model_repo"]
    revision: str = config["layout_model_revision"]
    largest: str = config["layout_model_largest_file"]
    expected: str = config["layout_model_largest_file_sha256"]
    layout_dir: Path = args.layout_dir or Path(config["layout_model_dir"])

    sidecar = layout_dir / SIDECAR_NAME
    cache_hit = sidecar.is_file()
    if cache_hit:
        recorded = json.loads(sidecar.read_text(encoding="utf-8"))
        if recorded.get("revision") != revision:
            print(
                f"cached layout model is revision {recorded.get('revision')!r}, "
                f"campaign pinned {revision!r}; refusing to mix revisions",
                file=sys.stderr,
            )
            return 2
    else:
        from huggingface_hub import snapshot_download  # type: ignore[import-not-found]

        layout_dir.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=repo, revision=revision, local_dir=str(layout_dir))

    largest_path = layout_dir / largest
    if not largest_path.is_file():
        print(f"layout model file {largest} is missing after download", file=sys.stderr)
        return 3
    observed = _sha256(largest_path)
    if observed != expected:
        print(f"{largest} hashes to {observed}, runtime.json pinned {expected}", file=sys.stderr)
        return 4

    payload = {
        "repo": repo,
        "revision": revision,
        "largest_file": largest,
        "largest_file_sha256": observed,
        "license": "Apache-2.0",
        "license_note": (
            "separate from the MIT GLM-OCR model licence; the model card says users "
            "must comply with both"
        ),
        "cache_hit": cache_hit,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    tmp = sidecar.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, sidecar)
    print(f"layout model ready: {repo}@{revision}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
