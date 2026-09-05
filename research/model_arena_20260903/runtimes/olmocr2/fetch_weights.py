"""Download the pinned checkpoint and record what actually landed on disk.

Run inside the runtime image (build time for ``weights_strategy: baked``, boot time
for ``volume_cache``). It reads ``runtime.json`` next to itself, so the repo,
revision and expected largest-file digest have exactly one source of truth.

It writes ``<weights_dir>/.arena_weights.json``:

    {"repo", "revision", "largest_file", "largest_file_sha256",
     "files_manifest_sha256", "cache_hit", "fetched_at"}

``adapter.load`` refuses to serve when the recorded revision is not the one the
campaign pinned, or when the largest file does not hash to the recorded value.
Nothing here retries and nothing falls back to a different revision.
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
SIDECAR_NAME = ".arena_weights.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _manifest_sha256(root: Path) -> str:
    pairs = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if path.name == SIDECAR_NAME:
            continue
        pairs.append(f"{path.relative_to(root).as_posix()}:{_sha256(path)[len('sha256:'):]}")
    return "sha256:" + hashlib.sha256("\n".join(pairs).encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights-dir", required=True, type=Path)
    parser.add_argument(
        "--manifest",
        action="store_true",
        help="hash every file (slow on large checkpoints); otherwise only the largest",
    )
    args = parser.parse_args(argv)

    spec = json.loads(RUNTIME_JSON.read_text(encoding="utf-8"))
    weights = spec["weights"]
    repo: str = weights["repo"]
    revision: str = weights["revision"]
    largest: str = weights["largest_file"]
    expected: str = weights["largest_file_sha256"]

    weights_dir: Path = args.weights_dir
    sidecar = weights_dir / SIDECAR_NAME
    cache_hit = sidecar.is_file()
    if cache_hit:
        recorded = json.loads(sidecar.read_text(encoding="utf-8"))
        if recorded.get("revision") != revision:
            print(
                f"cached weights are revision {recorded.get('revision')!r}, "
                f"campaign pinned {revision!r}; refusing to mix revisions",
                file=sys.stderr,
            )
            return 2
        print(f"cache hit for {repo}@{revision}", file=sys.stderr)
    else:
        from huggingface_hub import snapshot_download  # type: ignore[import-not-found]

        weights_dir.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=repo,
            revision=revision,
            local_dir=str(weights_dir),
            max_workers=int(os.environ.get("ARENA_HF_MAX_WORKERS", "4")),
        )

    largest_path = weights_dir / largest
    if not largest_path.is_file():
        print(f"largest weight file {largest} is missing after download", file=sys.stderr)
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
        "files_manifest_sha256": _manifest_sha256(weights_dir) if args.manifest else None,
        "cache_hit": cache_hit,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    tmp = sidecar.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, sidecar)
    print(f"weights ready: {repo}@{revision}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
