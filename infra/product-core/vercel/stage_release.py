"""Build a deterministic, least-content Product-Core Vercel release directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

RUNTIME_FILES = (
    ".python-version",
    "requirements.txt",
    "vercel.json",
    "api/index.py",
)
VENDOR_PACKAGES = (
    ("packages/cir-python/src/akc_cir", "vendor/akc_cir"),
    ("packages/domain-packs/src/akc_domain_packs", "vendor/akc_domain_packs"),
    ("packages/product-core/src/akc_product_core", "vendor/akc_product_core"),
)
MANIFEST_NAME = "release-manifest.json"


def _file_digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _source_manifest(output: Path) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    release_hash = hashlib.sha256()
    files = sorted(
        path for path in output.rglob("*") if path.is_file() and path.name != MANIFEST_NAME
    )
    for path in files:
        relative = path.relative_to(output).as_posix()
        value = path.read_bytes()
        relative_bytes = relative.encode("utf-8")
        release_hash.update(len(relative_bytes).to_bytes(4, "big"))
        release_hash.update(relative_bytes)
        release_hash.update(len(value).to_bytes(8, "big"))
        release_hash.update(value)
        rows.append({"path": relative, "sizeBytes": len(value), "sha256": _file_digest(value)})
    return {
        "schemaVersion": "tavonel.product_core_vercel_release.v1",
        "sourceDigest": f"sha256:{release_hash.hexdigest()}",
        "files": rows,
    }


def stage_release(repository: Path, output: Path) -> dict[str, object]:
    repository = repository.resolve()
    output = output.resolve()
    if output == repository or repository in output.parents:
        raise ValueError("release output must be outside the repository")
    if output.exists() and any(output.iterdir()):
        raise ValueError("release output must be absent or empty")
    output.mkdir(parents=True, exist_ok=True)

    adapter_root = repository / "infra/product-core/vercel"
    for relative in RUNTIME_FILES:
        source = adapter_root / relative
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    for source_relative, destination_relative in VENDOR_PACKAGES:
        shutil.copytree(
            repository / source_relative,
            output / destination_relative,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )

    manifest = _source_manifest(output)
    (output / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = stage_release(args.repository, args.output)
    print(json.dumps(manifest, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
