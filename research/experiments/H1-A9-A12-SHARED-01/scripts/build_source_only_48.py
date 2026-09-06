#!/usr/bin/env python3
"""Build the sealed GT-free source bundle for the preregistered 48-case A9/A12 pilot."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
COHORT = (
    ROOT
    / "research"
    / "experiments"
    / "H1-A12-01"
    / "cohorts"
    / "semantic-divergence-pilot-v1.json"
)
STAGED = ROOT / "benchmark" / "datasets" / "staged-public-core"
OUT_ROOT = ROOT / "research" / "experiments" / "H1-A9-A12-SHARED-01" / "source-only-v1"
MANIFEST = OUT_ROOT / "inference-input-manifest.json"
ARCHIVE = OUT_ROOT / "source-only-48.tar"
RECEIPT = OUT_ROOT / "receipt.json"
EXPECTED = {"olmocr-bench": 21, "parsebench": 19, "omnidocbench": 8}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def content_sha256(value: dict[str, Any]) -> str:
    return canonical_sha256(
        {k: v for k, v in value.items() if k not in {"content_sha256", "receipt_sha256"}}
    )


def tar_info(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    return info


def add_bytes(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    archive.addfile(tar_info(name, len(data)), io.BytesIO(data))


def load_full_manifest(benchmark_id: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    path = STAGED / benchmark_id / "inference-input-manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != "folynta.public-core-inference-inputs.v1":
        raise RuntimeError(f"{benchmark_id} staged manifest schema drifted")
    if value.get("benchmark_id") != benchmark_id or value.get("ground_truth_mounted") is not False:
        raise RuntimeError(f"{benchmark_id} staged manifest is not GT-free")
    if value.get("content_sha256") != content_sha256(value):
        raise RuntimeError(f"{benchmark_id} staged manifest content hash is invalid")
    rows = value.get("inputs")
    if not isinstance(rows, list) or len(rows) != int(value.get("input_count", -1)):
        raise RuntimeError(f"{benchmark_id} staged input coverage is invalid")
    mapping = {str(item.get("case_id")): item for item in rows if isinstance(item, dict)}
    if len(mapping) != len(rows):
        raise RuntimeError(f"{benchmark_id} staged case ids are not unique")
    return value, mapping


def main() -> int:
    if OUT_ROOT.exists():
        raise RuntimeError("A9/A12 source-only output directory already exists")
    cohort = json.loads(COHORT.read_text(encoding="utf-8"))
    cases = cohort.get("cases")
    if cohort.get("case_count") != 48 or not isinstance(cases, list) or len(cases) != 48:
        raise RuntimeError("A9/A12 cohort is not exactly 48 cases")
    full: dict[str, tuple[dict[str, Any], dict[str, dict[str, Any]]]] = {
        benchmark: load_full_manifest(benchmark) for benchmark in EXPECTED
    }
    counts = {benchmark: 0 for benchmark in EXPECTED}
    staged_rows: list[dict[str, Any]] = []
    copy_plan: list[tuple[Path, Path]] = []
    seen: set[tuple[str, str]] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise RuntimeError("A9/A12 cohort contains a non-object case")
        benchmark = str(case.get("benchmark_id", ""))
        case_id = str(case.get("case_id", ""))
        if benchmark not in full or not case_id:
            raise RuntimeError("A9/A12 cohort case identity is invalid")
        identity = (benchmark, case_id)
        if identity in seen:
            raise RuntimeError("A9/A12 cohort contains a duplicate case")
        seen.add(identity)
        counts[benchmark] += 1
        full_manifest, mapping = full[benchmark]
        source_row = mapping.get(case_id)
        if source_row is None:
            raise RuntimeError(f"A9/A12 case is absent from frozen staged public core: {benchmark}")
        original_relative = str(source_row.get("input_relative_path", ""))
        if not original_relative.startswith("inputs/"):
            raise RuntimeError("frozen public-core input path escaped inputs/")
        source = STAGED / benchmark / original_relative
        if not source.is_file() or sha_file(source) != source_row.get("input_sha256"):
            raise RuntimeError("frozen public-core input file hash drifted")
        safe_name = f"{benchmark}__{case_id}.png"
        target = OUT_ROOT / "inputs" / safe_name
        copy_plan.append((source, target))
        staged_rows.append(
            {
                "benchmark_id": benchmark,
                "case_id": case_id,
                "dataset_revision": full_manifest.get("dataset_revision"),
                "source_sha256": source_row.get("source_sha256"),
                "source_page_index": source_row.get("page_index"),
                "input_relative_path": f"inputs/{safe_name}",
                "input_sha256": source_row.get("input_sha256"),
            }
        )
    if counts != EXPECTED:
        raise RuntimeError(f"A9/A12 benchmark distribution drifted: {counts!r}")
    OUT_ROOT.mkdir(parents=True)
    (OUT_ROOT / "inputs").mkdir()
    for source, target in copy_plan:
        shutil.copyfile(source, target)
        if sha_file(target) != sha_file(source):
            raise RuntimeError("A9/A12 staged source copy hash mismatch")
    staged_rows.sort(key=lambda row: (str(row["benchmark_id"]), str(row["case_id"])))
    manifest: dict[str, Any] = {
        "schema": "tavonel.a9-a12-source-only-48.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "case_count": 48,
        "benchmark_counts": counts,
        "ground_truth_mounted": False,
        "ground_truth_in_bundle": False,
        "selection_manifest": COHORT.relative_to(ROOT).as_posix(),
        "selection_manifest_sha256": sha_file(COHORT),
        "source": "frozen-staged-public-core",
        "inputs": staged_rows,
    }
    manifest["content_sha256"] = content_sha256(manifest)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with tarfile.open(ARCHIVE, "w", format=tarfile.PAX_FORMAT) as archive:
        add_bytes(archive, "inference-input-manifest.json", MANIFEST.read_bytes())
        for row in staged_rows:
            relative = str(row["input_relative_path"])
            add_bytes(archive, relative, (OUT_ROOT / relative).read_bytes())
    with tarfile.open(ARCHIVE, "r") as archive:
        names = archive.getnames()
    if len(names) != 49 or names[0] != "inference-input-manifest.json":
        raise RuntimeError("A9/A12 source-only archive member coverage drifted")
    if any("ground_truth" in name.lower() or "ground-truth" in name.lower() for name in names):
        raise RuntimeError("A9/A12 source-only archive contains GT-like path")
    receipt: dict[str, Any] = {
        "schema": "tavonel.a9-a12-source-only-48-receipt.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "case_count": 48,
        "benchmark_counts": counts,
        "ground_truth_mounted": False,
        "ground_truth_in_bundle": False,
        "manifest_sha256": sha_file(MANIFEST),
        "manifest_content_sha256": manifest["content_sha256"],
        "archive_sha256": sha_file(ARCHIVE),
        "archive_bytes": ARCHIVE.stat().st_size,
        "archive_member_count": len(names),
        "all_input_hashes_verified": True,
        "selection_manifest_sha256": sha_file(COHORT),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "archive_bytes": ARCHIVE.stat().st_size}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
