"""Bake the C0 weights at image build: download the pinned files, then refuse any difference.

``python mineru_akc_weights.py <weights-manifest.json> <destination>`` downloads exactly the
manifest's files of ``repo_id`` at ``revision`` and fails the build unless every file has the
manifest's size and digest and nothing else is in the tree. LFS files are checked by sha256;
the few small non-LFS files (configs) by the git blob id, the only digest the Hub API gives
for them. The server serves offline afterwards.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


def _digest(path: Path, entry: dict[str, Any]) -> bool:
    if "sha256" in entry:
        sha = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1 << 20):
                sha.update(chunk)
        return bool(sha.hexdigest() == entry["sha256"])
    blob = hashlib.sha1(b"blob %d\0" % path.stat().st_size, usedforsecurity=False)
    blob.update(path.read_bytes())
    return bool(blob.hexdigest() == entry["git_blob_sha1"])


def verify_tree(root: Path, manifest: dict[str, Any]) -> list[str]:
    """Every difference between ``root`` and the manifest; empty means identical."""
    errors: list[str] = []
    expected = {entry["path"]: entry for entry in manifest["files"]}
    present = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    errors += [f"unexpected file {path}" for path in sorted(present - set(expected))]
    for path, entry in sorted(expected.items()):
        target = root / path
        if path not in present:
            errors.append(f"missing file {path}")
        elif target.stat().st_size != entry["size"]:
            errors.append(f"size differs {path}")
        elif not _digest(target, entry):
            errors.append(f"digest differs {path}")
    return errors


def main(manifest_path: str, destination: str) -> None:
    from huggingface_hub import snapshot_download

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    root = Path(destination)
    snapshot_download(
        repo_id=manifest["repo_id"],
        revision=manifest["revision"],
        local_dir=root,
        allow_patterns=[entry["path"] for entry in manifest["files"]],
    )
    shutil.rmtree(root / ".cache", ignore_errors=True)  # the hub's download bookkeeping
    errors = verify_tree(root, manifest)
    if errors:
        raise SystemExit("weights differ from the manifest:\n" + "\n".join(errors))
    print(f"{len(manifest['files'])} files, {manifest['total_bytes']} bytes, verified")


if __name__ == "__main__":
    main(*sys.argv[1:3])
