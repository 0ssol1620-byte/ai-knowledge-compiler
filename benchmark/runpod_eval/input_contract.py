"""Fail-closed source-only input selection for smoke and full public runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True, slots=True)
class InferenceInputSelection:
    inventory: tuple[Path, ...]
    selected: tuple[Path, ...]
    evidence_class: str
    input_manifest_sha256: str | None = None
    benchmark_id: str | None = None
    dataset_revision: str | None = None
    contract_complete: bool | None = None

    @property
    def complete_input_coverage(self) -> bool:
        if self.contract_complete is not None:
            return self.contract_complete
        return len(self.selected) == len(self.inventory)


def select_inference_inputs(
    *,
    input_dir: Path,
    supported_extensions: set[str],
    limit: int,
    evidence_class: str,
    expected_input_count: int | None,
    input_manifest: Path | None = None,
    parent_input_manifest: Path | None = None,
) -> InferenceInputSelection:
    if limit < 0:
        raise ValueError("--limit cannot be negative")
    if evidence_class not in {
        "smoke",
        "public-core",
        "public-core-shard",
        "stratified-audit",
    }:
        raise ValueError(
            "evidence class must be smoke, public-core, public-core-shard, "
            "or stratified-audit"
        )
    inventory = tuple(
        path.resolve()
        for path in sorted(input_dir.rglob("*"))
        if path.is_file() and path.suffix.casefold() in supported_extensions
    )
    if not inventory:
        raise ValueError("no supported images found")
    if evidence_class in {"public-core", "public-core-shard", "stratified-audit"}:
        if (
            limit != 0
            or expected_input_count is None
            or expected_input_count <= 0
            or input_manifest is None
        ):
            raise ValueError(
                f"{evidence_class} requires --limit 0, a positive --expected-input-count, "
                "and --input-manifest"
            )
        manifest = _load_bound_manifest(input_manifest, evidence_class=evidence_class)
        if evidence_class in {"public-core-shard", "stratified-audit"}:
            if parent_input_manifest is None:
                raise ValueError(f"{evidence_class} requires --parent-input-manifest")
            if evidence_class == "stratified-audit":
                _validate_audit_parent(manifest, parent_input_manifest)
            else:
                _validate_shard_parent(manifest, parent_input_manifest)
        manifest_paths = _manifest_input_paths(
            manifest=manifest,
            input_dir=input_dir,
            supported_extensions=supported_extensions,
        )
        if len(manifest_paths) != expected_input_count:
            raise ValueError("public-core input count does not match the frozen manifest")
        if evidence_class in {"public-core", "public-core-shard"} and set(
            inventory
        ) != set(manifest_paths):
            raise ValueError("public-core inventory does not exactly match the frozen manifest")
        if evidence_class == "stratified-audit" and not set(manifest_paths).issubset(inventory):
            raise ValueError("stratified-audit inputs are outside the frozen inventory")
        return InferenceInputSelection(
            inventory=inventory,
            selected=manifest_paths,
            evidence_class=evidence_class,
            input_manifest_sha256=manifest["content_sha256"],
            benchmark_id=manifest["benchmark_id"],
            dataset_revision=manifest["dataset_revision"],
            contract_complete=True,
        )
    selected = inventory if limit == 0 else inventory[:limit]
    return InferenceInputSelection(inventory, selected, evidence_class)


def adaptive_repeat_indices(
    *, evidence_class: str, repeats: int, repeat_start_index: int
) -> tuple[int, ...]:
    if repeats not in {1, 2, 3} or repeat_start_index not in {1, 2, 3}:
        raise ValueError("adaptive repeats and start index must be between one and three")
    if repeat_start_index + repeats - 1 > 3:
        raise ValueError("adaptive repeat indexes cannot exceed three")
    shape = (repeat_start_index, repeats)
    if evidence_class in {"public-core", "public-core-shard"} and shape not in {
        (1, 1),
        (2, 2),
        (1, 3),
    }:
        raise ValueError(
            "public-core permits initial 1, expansion 2-3, or finalist 1-3 only"
        )
    if evidence_class == "stratified-audit" and shape != (1, 3):
        raise ValueError("stratified-audit requires exactly repeat indexes 1-3")
    return tuple(range(repeat_start_index, repeat_start_index + repeats))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_bound_manifest(path: Path, *, evidence_class: str) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    expected_schema = {
        "public-core": "folynta.public-core-inference-inputs.v1",
        "public-core-shard": "folynta.public-core-inference-shard.v1",
        "stratified-audit": "folynta.public-core-stratified-audit.v1",
    }[evidence_class]
    if manifest.get("schema") != expected_schema:
        raise ValueError(f"unsupported {evidence_class} input manifest schema")
    if manifest.get("ground_truth_mounted") is not False:
        raise ValueError("public-core input manifest must be ground-truth-free")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("public-core input manifest has no inputs")
    if manifest.get("input_count") != len(inputs) or manifest.get(
        "complete_input_coverage"
    ) is not True:
        raise ValueError(f"{evidence_class} input manifest is incomplete")
    if evidence_class == "public-core" and (
        manifest.get("source_count") != len(inputs)
        or manifest.get("complete_source_coverage") is not True
    ):
        raise ValueError("public-core input manifest is incomplete")
    if evidence_class == "public-core-shard" and (
        not isinstance(manifest.get("source_count"), int)
        or manifest["source_count"] <= 0
        or manifest.get("complete_source_coverage") is not False
        or not isinstance(manifest.get("parent_input_manifest_sha256"), str)
        or not isinstance(manifest.get("shard_index"), int)
        or not isinstance(manifest.get("shard_count"), int)
        or not 0 <= manifest["shard_index"] < manifest["shard_count"]
    ):
        raise ValueError("public-core-shard manifest contract is incomplete")
    if evidence_class == "stratified-audit" and (
        not isinstance(manifest.get("source_count"), int)
        or manifest["source_count"] <= len(inputs)
        or manifest.get("complete_source_coverage") is not False
        or manifest.get("stratified") is not True
        or not isinstance(manifest.get("parent_input_manifest_sha256"), str)
    ):
        raise ValueError("stratified-audit manifest contract is incomplete")
    expected_hash = manifest.get("content_sha256")
    content = {key: value for key, value in manifest.items() if key != "content_sha256"}
    actual_hash = f"sha256:{hashlib.sha256(_canonical_json(content).encode()).hexdigest()}"
    if expected_hash != actual_hash:
        raise ValueError("public-core input manifest content hash is invalid")
    return cast(dict[str, Any], manifest)


def _manifest_input_paths(
    *, manifest: dict[str, Any], input_dir: Path, supported_extensions: set[str]
) -> tuple[Path, ...]:
    root = input_dir.resolve()
    paths: list[Path] = []
    case_ids: set[str] = set()
    for item in manifest["inputs"]:
        case_id = item.get("case_id")
        relative = item.get("input_relative_path")
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise ValueError("public-core input manifest has invalid case IDs")
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise ValueError("public-core input manifest has an invalid input path")
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("public-core input path escapes input directory") from exc
        if not path.is_file() or path.suffix.casefold() not in supported_extensions:
            raise ValueError("public-core manifest input is missing or unsupported")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if item.get("input_sha256") != f"sha256:{digest}":
            raise ValueError("public-core manifest input hash does not match")
        case_ids.add(case_id)
        paths.append(path)
    if len(set(paths)) != len(paths):
        raise ValueError("public-core input manifest contains duplicate paths")
    return tuple(paths)


def _validate_audit_parent(audit: dict[str, Any], parent_path: Path) -> None:
    parent = _load_bound_manifest(parent_path, evidence_class="public-core")
    if audit.get("parent_input_manifest_sha256") != parent.get("content_sha256"):
        raise ValueError("stratified-audit parent manifest hash does not match")
    if (
        audit.get("benchmark_id") != parent.get("benchmark_id")
        or audit.get("dataset_revision") != parent.get("dataset_revision")
        or audit.get("source_count") != parent.get("source_count")
    ):
        raise ValueError("stratified-audit parent identity does not match")
    parent_by_case = {str(item.get("case_id")): item for item in parent["inputs"]}
    for item in audit["inputs"]:
        case_id = str(item.get("case_id"))
        if parent_by_case.get(case_id) != item:
            raise ValueError("stratified-audit input is not identical to its parent entry")


def _validate_shard_parent(shard: dict[str, Any], parent_path: Path) -> None:
    parent = _load_bound_manifest(parent_path, evidence_class="public-core")
    if shard.get("parent_input_manifest_sha256") != parent.get("content_sha256"):
        raise ValueError("public-core-shard parent manifest hash does not match")
    if (
        shard.get("benchmark_id") != parent.get("benchmark_id")
        or shard.get("dataset_revision") != parent.get("dataset_revision")
        or shard.get("source_count") != parent.get("source_count")
    ):
        raise ValueError("public-core-shard parent identity does not match")
    parent_by_case = {str(item.get("case_id")): item for item in parent["inputs"]}
    for item in shard["inputs"]:
        case_id = str(item.get("case_id"))
        if parent_by_case.get(case_id) != item:
            raise ValueError("public-core-shard input is not identical to its parent entry")


__all__ = [
    "InferenceInputSelection",
    "adaptive_repeat_indices",
    "select_inference_inputs",
]
