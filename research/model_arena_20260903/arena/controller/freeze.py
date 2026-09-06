"""Freeze a model's outputs (ARENA_CONTRACT section 3.10, masterplan Phase 4).

Freezing is the moment the campaign stops being able to change a result. So it
is fail-closed in the strongest sense available here: every receipt's recorded
``raw_output_sha256`` and ``canonical_output_sha256`` are recomputed from the
files on disk, and one mismatch refuses the whole freeze. A frozen manifest
that points at a file whose bytes moved is worse than no manifest.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from arena.constants import CAMPAIGN_ID
from arena.controller.paths import CampaignPaths
from arena.provider.safety import (
    atomic_write_bytes,
    canonical_sha256,
    read_json,
    sha256_file,
    utc_now_iso,
    write_json_atomic,
)

__all__ = ["FreezeError", "FreezeResult", "HashMismatch", "freeze_model"]

SCHEMA_MANIFEST_LINE: Final = "tavonel.arena.frozen_manifest_entry.v1"


class FreezeError(RuntimeError):
    """The outputs cannot be frozen as they stand."""


@dataclass(frozen=True, slots=True)
class HashMismatch:
    case_key: str
    field_name: str
    recorded: str
    recomputed: str
    path: str

    def to_dict(self) -> dict[str, object]:
        return {
            "case_key": self.case_key,
            "field": self.field_name,
            "recorded": self.recorded,
            "recomputed": self.recomputed,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class FreezeResult:
    model_key: str
    frozen: bool
    sample_count: int
    success_count: int
    failed_count: int
    manifest_path: Path | None
    manifest_sha256: str | None
    mismatches: tuple[HashMismatch, ...] = field(default_factory=tuple)
    missing_files: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.arena.freeze_result.v1",
            "campaign_id": CAMPAIGN_ID,
            "model_key": self.model_key,
            "frozen": self.frozen,
            "sample_count": self.sample_count,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "manifest_sha256": self.manifest_sha256,
            "mismatches": [item.to_dict() for item in self.mismatches],
            "missing_files": list(self.missing_files),
        }


def freeze_model(
    model_key: str,
    *,
    paths: CampaignPaths,
    model_revision: str | None = None,
    runtime_image_digest: str | None = None,
    planned_count: int | None = None,
    settled_count: int | None = None,
) -> FreezeResult:
    """Build ``frozen_outputs/<model_key>/manifest.jsonl`` and ``FROZEN.json``."""

    receipt_dir = paths.receipt_dir(model_key)
    if not receipt_dir.is_dir():
        raise FreezeError(f"no receipts under {receipt_dir}; nothing to freeze for {model_key}")

    receipt_files = sorted(receipt_dir.glob("*.json"))
    if not receipt_files:
        raise FreezeError(f"no page receipts under {receipt_dir}")

    entries: list[dict[str, object]] = []
    mismatches: list[HashMismatch] = []
    missing: list[str] = []
    success_count = 0
    failed_count = 0

    for receipt_path in receipt_files:
        document = read_json(receipt_path)
        if not isinstance(document, Mapping):
            raise FreezeError(f"{receipt_path.name} is not a JSON object")
        case_key = _string(document, "case_key", receipt_path.name)
        status = _string(document, "status", receipt_path.name)
        raw_path = paths.raw_dir(model_key) / f"{case_key}.raw.txt"
        canonical_path = paths.canonical_dir(model_key) / f"{case_key}.md"

        if status == "SUCCESS":
            success_count += 1
            _verify(
                document,
                "raw_output_sha256",
                raw_path,
                case_key,
                receipt_path.name,
                mismatches,
                missing,
            )
            _verify(
                document,
                "canonical_output_sha256",
                canonical_path,
                case_key,
                receipt_path.name,
                mismatches,
                missing,
            )
        else:
            failed_count += 1

        entries.append(
            {
                "schema": SCHEMA_MANIFEST_LINE,
                "case_key": case_key,
                "sample_id": _string(document, "sample_id", receipt_path.name),
                "benchmark": _string(document, "benchmark", receipt_path.name),
                "status": status,
                "raw_sha256": document.get("raw_output_sha256"),
                "canonical_sha256": document.get("canonical_output_sha256"),
                "receipt_sha256": sha256_file(receipt_path),
                "raw_path": str(raw_path.relative_to(paths.root)).replace("\\", "/"),
                "canonical_path": str(canonical_path.relative_to(paths.root)).replace("\\", "/"),
            }
        )

    if mismatches or missing:
        return FreezeResult(
            model_key=model_key,
            frozen=False,
            sample_count=len(entries),
            success_count=success_count,
            failed_count=failed_count,
            manifest_path=None,
            manifest_sha256=None,
            mismatches=tuple(mismatches),
            missing_files=tuple(missing),
        )

    entries.sort(key=lambda entry: str(entry["case_key"]))
    manifest_path = paths.frozen_manifest(model_key)
    body = "".join(_canonical_line(entry) for entry in entries)
    manifest_sha256 = atomic_write_bytes(manifest_path, body.encode("utf-8"))

    write_json_atomic(
        paths.frozen_marker(model_key),
        {
            "schema": "tavonel.arena.frozen_marker.v1",
            "campaign_id": CAMPAIGN_ID,
            "frozen_at": utc_now_iso(),
            "manifest_sha256": manifest_sha256,
            "sample_count": len(entries),
            "success_count": success_count,
            "failed_count": failed_count,
            "model_revision": model_revision,
            "runtime_image_digest": runtime_image_digest,
            # D87. Whether the run this manifest seals had finished. A reader
            # must not have to infer it from sample_count, which is a count of
            # receipts and says nothing about how many there should have been.
            "planned_count": planned_count,
            "settled_count": settled_count,
            "complete": (
                None
                if planned_count is None or settled_count is None
                else bool(settled_count >= planned_count)
            ),
        },
        context="frozen marker",
    )
    return FreezeResult(
        model_key=model_key,
        frozen=True,
        sample_count=len(entries),
        success_count=success_count,
        failed_count=failed_count,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
    )


def _canonical_line(entry: Mapping[str, object]) -> str:
    import json

    return json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"


def _verify(
    document: Mapping[str, Any],
    field_name: str,
    path: Path,
    case_key: str,
    receipt_name: str,
    mismatches: list[HashMismatch],
    missing: list[str],
) -> None:
    recorded = document.get(field_name)
    if not isinstance(recorded, str) or not recorded:
        mismatches.append(
            HashMismatch(case_key, field_name, "<absent>", "<not computed>", str(path))
        )
        return
    if not path.is_file():
        missing.append(f"{receipt_name}: {field_name} points at a missing file {path.name}")
        return
    recomputed = sha256_file(path)
    if recomputed != recorded:
        mismatches.append(HashMismatch(case_key, field_name, recorded, recomputed, str(path)))


def _string(document: Mapping[str, Any], key: str, context: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise FreezeError(f"{context} is missing a non-empty {key}")
    return value


def manifest_digest(entries: list[Mapping[str, object]]) -> str:
    """Digest of a manifest's logical content, for cross-checking a rewrite."""

    return canonical_sha256(sorted(entries, key=lambda entry: str(entry.get("case_key"))))
