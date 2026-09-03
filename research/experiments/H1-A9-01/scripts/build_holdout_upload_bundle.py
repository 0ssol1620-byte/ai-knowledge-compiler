#!/usr/bin/env python3
"""Build the A9 confirmatory-holdout upload bundle.

Byte-for-byte the sealed hard-200 builder, with four constants turned into
arguments and the hardcoded 200 replaced by the shard's own declared count.
Every integrity check the original performs is kept: shard/parent schema, GT
absence, content-hash self-consistency, parent binding, per-input hash
verification, tar member order and the GT-like-path scan.

It is a copy rather than an import because the original binds its paths at
module scope and rewriting it in place would change the artifact that produced
the discovery bundle.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmark.v6.contracts import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path()  # set in main()
SHARD = SOURCE / "inference-input-manifest.json"
INPUTS = SOURCE / "inputs"
PARENT = (
    ROOT
    / "benchmark"
    / "datasets"
    / "staged-public-core"
    / "omnidocbench"
    / "inference-input-manifest.json"
)
OUT = Path()  # set in main()
RECEIPT = (
    ROOT / ".chatgpt2codex" / "formal-runtime-v28" / "stage1-hard-200-source-only-v2.receipt.json"
)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def content_sha256(value: dict[str, Any]) -> str:
    content = {key: item for key, item in value.items() if key != "content_sha256"}
    return canonical_sha256(content)


def tar_info(name: str, size: int, mode: int = 0o644) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    return info


def add_file(archive: tarfile.TarFile, path: Path, name: str) -> None:
    data = path.read_bytes()
    archive.addfile(tar_info(name, len(data)), io.BytesIO(data))


def main() -> int:
    import argparse

    global SOURCE, SHARD, INPUTS, PARENT, OUT, RECEIPT
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice-dir", type=Path, required=True)
    parser.add_argument("--parent-manifest", type=Path, required=True)
    parser.add_argument("--out-tar", type=Path, required=True)
    parser.add_argument("--out-receipt", type=Path, required=True)
    args = parser.parse_args()
    SOURCE = args.slice_dir.resolve()
    SHARD = SOURCE / "inference-input-manifest.json"
    INPUTS = SOURCE / "inputs"
    PARENT = args.parent_manifest.resolve()
    OUT = args.out_tar.resolve()
    RECEIPT = args.out_receipt.resolve()
    expected_count = int(json.loads(SHARD.read_text(encoding="utf-8"))["input_count"])

    if OUT.exists() or RECEIPT.exists():
        raise RuntimeError("upload bundle already exists")
    shard = json.loads(SHARD.read_text(encoding="utf-8"))
    parent = json.loads(PARENT.read_text(encoding="utf-8"))
    if shard.get("schema") != "folynta.public-core-inference-shard.v1":
        raise RuntimeError("Stage-1 manifest is not a public-core shard")
    if parent.get("schema") != "folynta.public-core-inference-inputs.v1":
        raise RuntimeError("Stage-1 parent manifest is not full public-core")
    if (
        shard.get("input_count") != expected_count
        or len(shard.get("inputs") or []) != expected_count
    ):
        raise RuntimeError(f"Stage-1 shard is not exactly {expected_count} inputs")
    if (
        shard.get("ground_truth_mounted") is not False
        or parent.get("ground_truth_mounted") is not False
    ):
        raise RuntimeError("Stage-1 shard or parent manifest is not GT-free")
    if shard.get("content_sha256") != content_sha256(shard):
        raise RuntimeError("Stage-1 shard content hash is invalid")
    if parent.get("content_sha256") != content_sha256(parent):
        raise RuntimeError("Stage-1 parent content hash is invalid")
    if shard.get("parent_input_manifest_sha256") != parent.get("content_sha256"):
        raise RuntimeError("Stage-1 shard does not bind to the selected parent manifest")
    for key in ("benchmark_id", "dataset_revision", "source_count"):
        if shard.get(key) != parent.get(key):
            raise RuntimeError(f"Stage-1 shard/parent identity drifted: {key}")

    parent_by_case = {str(item.get("case_id")): item for item in parent["inputs"]}
    entries: list[tuple[Path, str, str]] = []
    seen: set[str] = set()
    total_bytes = 0
    for item in shard["inputs"]:
        case_id = str(item.get("case_id", ""))
        if not case_id or parent_by_case.get(case_id) != item:
            raise RuntimeError("Stage-1 shard input is not identical to its parent entry")
        relative = str(item["input_relative_path"])
        if not relative.startswith("inputs/"):
            raise RuntimeError(f"Stage-1 input escapes sealed inputs/: {relative}")
        if relative in seen:
            raise RuntimeError(f"duplicate Stage-1 input path: {relative}")
        seen.add(relative)
        path = SOURCE / relative
        if not path.is_file():
            raise RuntimeError(f"Stage-1 sealed input is missing: {relative}")
        observed = sha_file(path)
        if observed != item.get("input_sha256"):
            raise RuntimeError(f"Stage-1 input hash drifted: {relative}")
        entries.append((path, relative, observed))
        total_bytes += path.stat().st_size

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(OUT, mode="w", format=tarfile.PAX_FORMAT) as archive:
        add_file(archive, SHARD, "inference-input-manifest.json")
        add_file(archive, PARENT, "parent-inference-input-manifest.json")
        for path, relative, _ in sorted(entries, key=lambda row: row[1]):
            add_file(archive, path, relative)

    with tarfile.open(OUT, mode="r") as archive:
        names = archive.getnames()
    expected_names = [
        "inference-input-manifest.json",
        "parent-inference-input-manifest.json",
    ] + [row[1] for row in sorted(entries, key=lambda row: row[1])]
    if names != expected_names:
        raise RuntimeError("Stage-1 v2 tar member order/content drifted")
    suspicious = [
        name
        for name in names
        if "ground_truth" in name.lower()
        or "ground-truth" in name.lower()
        or Path(name).stem.lower() in {"gt", "groundtruth"}
    ]
    if suspicious:
        raise RuntimeError("Stage-1 v2 upload tar contains a suspicious GT-like path")

    receipt = {
        "schema": "tavonel.stage1-source-only-upload-bundle.v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "benchmark_id": "omnidocbench",
        "evidence_class": "public-core-shard",
        "input_count": expected_count,
        "source_input_bytes": total_bytes,
        "tar_bytes": OUT.stat().st_size,
        "tar_sha256": sha_file(OUT),
        "shard_file_sha256": sha_file(SHARD),
        "shard_content_sha256": shard["content_sha256"],
        "parent_file_sha256": sha_file(PARENT),
        "parent_content_sha256": parent["content_sha256"],
        "dataset_revision": shard["dataset_revision"],
        "ground_truth_mounted": False,
        "ground_truth_in_bundle": False,
        "parent_manifest_is_source_only": True,
        "tar_member_count": len(names),
        "all_input_hashes_verified": True,
        "shard_parent_binding_verified": True,
        "public_benchmark_inference_allowed_only_after_ready": True,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS",
                "inputs": expected_count,
                "source_bytes": total_bytes,
                "tar_bytes": OUT.stat().st_size,
                "members": len(names),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
