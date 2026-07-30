"""Run the repository's real bounded native parser against corpus bytes.

Unlike ``local_mock``, this lane never copies ground truth into the candidate
output. Every case must identify an immutable file beneath an explicit corpus
root and bind it to a SHA-256 digest.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any

from akc_api.parsers import parse_document, validate_file
from akc_api.settings import Settings

from .base import RunnerUnavailable

PROVIDER = "native_document"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DEPENDENCIES = (
    "beautifulsoup4",
    "bleach",
    "lxml",
    "openpyxl",
    "pillow",
    "pypdf",
    "python-docx",
    "python-pptx",
)


def _native_revision() -> str:
    """Hash code and parser dependency versions into a reproducible revision."""

    parser_path = Path(sys.modules[parse_document.__module__].__file__ or "")
    if not parser_path.is_file():
        raise RunnerUnavailable("native parser source is unavailable")
    versions: dict[str, str] = {}
    for dependency in _DEPENDENCIES:
        try:
            versions[dependency] = importlib.metadata.version(dependency)
        except importlib.metadata.PackageNotFoundError as exc:
            raise RunnerUnavailable(f"native dependency is missing: {dependency}") from exc
    identity = {
        "contract": "akc-native-parser-benchmark-v1",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "parser_sha256": hashlib.sha256(parser_path.read_bytes()).hexdigest(),
        "dependencies": versions,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_path(case: dict[str, Any], corpus_root: Path) -> tuple[Path, dict[str, str]]:
    source = case.get("source")
    if not isinstance(source, dict):
        raise RunnerUnavailable("native benchmark case requires a source object")
    required = ("path", "filename", "content_type", "sha256")
    if any(not isinstance(source.get(field), str) or not source[field] for field in required):
        raise RunnerUnavailable("native benchmark source metadata is incomplete")
    relative = PurePosixPath(source["path"])
    if relative.is_absolute() or ".." in relative.parts or "\\" in source["path"]:
        raise RunnerUnavailable("native benchmark source path is unsafe")
    expected_sha256 = source["sha256"].casefold()
    if _SHA256.fullmatch(expected_sha256) is None:
        raise RunnerUnavailable("native benchmark source SHA-256 is invalid")
    root = corpus_root.resolve(strict=True)
    target = root.joinpath(*relative.parts).resolve(strict=True)
    if target != root and root not in target.parents:
        raise RunnerUnavailable("native benchmark source escaped the corpus root")
    if not target.is_file():
        raise RunnerUnavailable("native benchmark source is not a regular file")
    return target, {
        "filename": source["filename"],
        "content_type": source["content_type"],
        "sha256": expected_sha256,
    }


def run(case: dict[str, Any], *, corpus_root: Path) -> dict[str, Any]:
    source_path, source = _source_path(case, corpus_root)
    payload = source_path.read_bytes()
    maximum = max(50 * 1024 * 1024, len(payload))
    settings = Settings(
        env="test",
        data_dir=corpus_root,
        max_upload_bytes=maximum,
        analysis_max_source_bytes=maximum,
        max_pages=10_000,
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
    )
    started = time.perf_counter()
    _, digest = validate_file(
        filename=source["filename"],
        declared_mime=source["content_type"],
        data=payload,
        expected_sha256=source["sha256"],
        settings=settings,
    )
    parsed = parse_document(source["filename"], payload, settings)
    page_index = int(case.get("page_index", -1))
    if page_index < 0 or page_index >= len(parsed.pages):
        raise RunnerUnavailable("native benchmark page index is outside the source")
    page = parsed.pages[page_index]
    latency_ms = (time.perf_counter() - started) * 1000.0
    block_id = f"native-page-{page.page_number}-block-1"
    block = {
        "block_id": block_id,
        "type": "paragraph",
        "text": page.text,
        "origin": "native_extracted",
        "source_refs": [
            {
                "page_index": page_index,
                "bbox1000": [0, 0, 1000, 1000],
            }
        ],
    }
    return {
        "schema_version": "1.0",
        "benchmark_case_id": str(case["benchmark_case_id"]),
        "provider": PROVIDER,
        "model_revision": _native_revision(),
        "text": page.text,
        "reading_order": [block_id],
        "blocks": [block],
        "generated_claims": [],
        "metrics": {
            "latency_ms": latency_ms,
            "p50_latency_ms": latency_ms,
            "p95_latency_ms": latency_ms,
            "cold_start_ms": 0.0,
            "gpu_seconds": 0.0,
            "peak_vram_mb": 0.0,
            "estimated_cost_usd": 0.0,
        },
        "warnings": [],
        "source_sha256": digest,
    }
