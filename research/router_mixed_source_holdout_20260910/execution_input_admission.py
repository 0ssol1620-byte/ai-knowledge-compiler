"""Worker-side admission gate that runs immediately before any model call."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .preflight_mixed_holdout import (
    _contains_forbidden_key,
    digest,
    evaluate_preopen,
    load_json,
    load_jsonl,
)

SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]+$")
PINNED_IMAGE = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")
RENDER_FIELDS = frozenset(
    {
        "unit_id",
        "source_sha256",
        "target_locator",
        "render_sha256",
        "render_size_bytes",
        "render_relative_path",
        "render_profile_sha256",
        "render_runtime_sha256",
    }
)
MODEL_FIELDS = frozenset(
    {
        "model_key",
        "model_revision",
        "runtime_sha256",
        "runtime_relative_path",
        "bundle_sha256",
        "bundle_relative_path",
        "inference_config_sha256",
        "inference_config_relative_path",
        "weight_files",
    }
)
WEIGHT_FIELDS = frozenset({"relative_path", "sha256", "size_bytes"})
SNAPSHOT_FIELDS = frozenset(
    {
        "repository",
        "revision",
        "official_api_url",
        "official_snapshot_descriptor_sha256",
        "official_file_count",
        "files",
    }
)
REQUEST_FIELDS = frozenset(
    {
        "request_id",
        "unit_id",
        "model_key",
        "source_sha256",
        "target_locator",
        "render_sha256",
        "router_policy_sha256",
        "runtime_sha256",
        "bundle_sha256",
        "inference_config_sha256",
    }
)
HARD_EXECUTION_CAPS: Mapping[str, int | float] = {
    "maximum_new_gpu_spend_usd": 20.0,
    "maximum_model_unit_calls": 600,
    "maximum_parallel_pods": 3,
}


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    passed: bool
    blockers: tuple[str, ...]
    units: int
    rendered_units: int
    models: int
    requests: int
    input_digests: Mapping[str, str]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.router_execution_input_admission.v1",
            "passed": self.passed,
            "blockers": list(self.blockers),
            "units": self.units,
            "rendered_units": self.rendered_units,
            "models": self.models,
            "requests": self.requests,
            "input_digests": dict(sorted(self.input_digests.items())),
            "gate_sha256": digest(Path(__file__).read_bytes()),
            "actual_source_bytes_verified": self.passed,
            "actual_render_bytes_verified": self.passed,
            "actual_model_artifact_bytes_verified": self.passed,
            "truth_opened": False,
            "model_calls_before_admission": 0,
            "model_call_authorized": self.passed,
            "production_promotion": False,
        }


def _safe_path(root: Path, relative: object) -> Path | None:
    if not isinstance(relative, str) or not relative:
        return None
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        return None
    resolved_root = root.resolve()
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved


def _verify_file(
    *,
    root: Path,
    relative: object,
    expected_sha: object,
    expected_size: object | None,
    prefix: str,
    blockers: list[str],
) -> Path | None:
    path = _safe_path(root, relative)
    if path is None:
        blockers.append(f"{prefix}_PATH_INVALID")
        return None
    if not path.is_file():
        blockers.append(f"{prefix}_MISSING")
        return None
    if expected_size is not None and (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or path.stat().st_size != expected_size
    ):
        blockers.append(f"{prefix}_SIZE_MISMATCH")
    if not isinstance(expected_sha, str) or not SHA.fullmatch(expected_sha):
        blockers.append(f"{prefix}_DIGEST_INVALID")
    elif _streaming_digest(path) != expected_sha:
        blockers.append(f"{prefix}_DIGEST_MISMATCH")
    return path


def _streaming_digest(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Hash arbitrarily large artifacts without loading them into memory."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _write_immutable_receipt(path: Path, payload: bytes) -> None:
    """Create a receipt once; never replace a different admission decision."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ValueError("ADMISSION_RECEIPT_ALREADY_EXISTS_DIFFERENT") from None


def _request_id(unit_id: str, model_key: str, render_sha256: str) -> str:
    value = f"{unit_id}\0{model_key}\0{render_sha256}".encode()
    return "sha256:" + hashlib.sha256(value).hexdigest()


def evaluate_admission(
    *,
    binding_path: Path,
    preopen_result_path: Path,
    protocol_path: Path,
    source_manifest_path: Path,
    development_inventory_path: Path,
    candidate_inventory_path: Path,
    predictions_path: Path,
    source_contract_path: Path,
    source_root: Path,
    render_manifest_path: Path,
    render_root: Path,
    render_profile_path: Path,
    render_runtime_path: Path,
    model_manifest_path: Path,
    model_snapshot_binding_path: Path,
    model_root: Path,
    request_manifest_path: Path,
    execution_limits_path: Path,
    truth_root: Path,
    repo_root: Path,
) -> AdmissionResult:
    blockers: list[str] = []
    binding = load_json(binding_path)
    preopen = load_json(preopen_result_path)
    protocol = load_json(protocol_path)
    contract = load_json(source_contract_path)
    sources = load_jsonl(source_manifest_path)
    predictions = load_jsonl(predictions_path)
    renders = load_jsonl(render_manifest_path)
    model_artifacts = load_jsonl(model_manifest_path)
    snapshot_binding = load_json(model_snapshot_binding_path)
    requests = load_jsonl(request_manifest_path)
    limits = load_json(execution_limits_path)
    binding_sha = digest(binding_path.read_bytes())
    input_digests = {
        "binding": binding_sha,
        "preopen_result": digest(preopen_result_path.read_bytes()),
        "protocol": digest(protocol_path.read_bytes()),
        "source_manifest": digest(source_manifest_path.read_bytes()),
        "development_inventory": digest(development_inventory_path.read_bytes()),
        "candidate_inventory": digest(candidate_inventory_path.read_bytes()),
        "predictions": digest(predictions_path.read_bytes()),
        "source_contract": digest(source_contract_path.read_bytes()),
        "render_manifest": digest(render_manifest_path.read_bytes()),
        "render_profile": digest(render_profile_path.read_bytes()),
        "render_runtime": digest(render_runtime_path.read_bytes()),
        "model_artifact_manifest": digest(model_manifest_path.read_bytes()),
        "model_snapshot_binding": digest(model_snapshot_binding_path.read_bytes()),
        "request_manifest": digest(request_manifest_path.read_bytes()),
        "execution_limits": digest(execution_limits_path.read_bytes()),
    }

    live_preopen = evaluate_preopen(
        protocol_path=protocol_path,
        binding_path=binding_path,
        manifest_path=source_manifest_path,
        development_hashes_path=development_inventory_path,
        candidate_inventory_path=candidate_inventory_path,
        predictions_path=predictions_path,
        truth_root=truth_root,
        source_root=source_root,
        repo_root=repo_root,
    )
    live_preopen_dict = live_preopen.as_dict()
    if not live_preopen.passed:
        blockers.append("LIVE_PREOPEN_FAILED")
    if preopen != live_preopen_dict:
        blockers.append("SAVED_PREOPEN_RESULT_STALE_OR_MUTATED")
    if preopen.get("passed") is not True or preopen.get("binding_sha256") != binding_sha:
        blockers.append("LIVE_PREOPEN_BINDING_NOT_ADMITTED")
    if binding.get("protocol_sha256") != input_digests["protocol"]:
        blockers.append("PROTOCOL_BINDING_MISMATCH")
    if (
        binding.get("model_snapshot_binding_sha256")
        != input_digests["model_snapshot_binding"]
    ):
        blockers.append("MODEL_SNAPSHOT_BINDING_MISMATCH")
    for key, binding_field in (
        ("protocol_sha256", "protocol_sha256"),
        ("manifest_sha256", "source_manifest_sha256"),
        ("prediction_manifest_sha256", "prediction_manifest_sha256"),
        ("router_policy_sha256", "router_policy_sha256"),
    ):
        if preopen.get(key) != binding.get(binding_field):
            blockers.append(f"PREOPEN_{key.upper()}_MISMATCH")
    if truth_root.exists() and any(truth_root.iterdir()):
        blockers.append("HOLDOUT_TRUTH_ALREADY_PRESENT")
    for control_name, control_value in (
        ("RENDER_PROFILE", load_json(render_profile_path)),
        ("RENDER_RUNTIME", load_json(render_runtime_path)),
        ("MODEL_ARTIFACT_MANIFEST", model_artifacts),
        ("MODEL_SNAPSHOT_BINDING", snapshot_binding.get("models")),
        ("REQUEST_MANIFEST", requests),
        ("EXECUTION_LIMITS", limits),
    ):
        if _contains_forbidden_key(control_value):
            blockers.append(f"{control_name}_TRUTH_FIELD_FORBIDDEN")

    source_by_id: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(sources):
        unit_id = row.get("unit_id")
        if not isinstance(unit_id, str) or not SAFE_ID.fullmatch(unit_id):
            blockers.append(f"SOURCE_{index:04d}_UNIT_ID_INVALID")
            continue
        if unit_id in source_by_id:
            blockers.append(f"SOURCE_{index:04d}_UNIT_ID_DUPLICATE")
            continue
        source_by_id[unit_id] = row
        _verify_file(
            root=source_root,
            relative=unit_id.replace(":", "_") + ".source",
            expected_sha=row.get("source_sha256"),
            expected_size=row.get("source_size_bytes"),
            prefix=f"SOURCE_{index:04d}",
            blockers=blockers,
        )
    selection = protocol.get("source_selection")
    selection_map = selection if isinstance(selection, Mapping) else {}
    required_classes = protocol.get("required_classes")
    class_names = required_classes if isinstance(required_classes, list) else []
    per_class = selection_map.get("selected_units_per_class")
    maximum_total = selection_map.get("maximum_total_units")
    if (
        not isinstance(per_class, int)
        or isinstance(per_class, bool)
        or not isinstance(maximum_total, int)
        or isinstance(maximum_total, bool)
        or len(sources) != maximum_total
    ):
        blockers.append("SOURCE_TOTAL_DENOMINATOR_MISMATCH")
    class_counts = {
        source_class: sum(
            row.get("source_class") == source_class for row in sources
        )
        for source_class in class_names
        if isinstance(source_class, str)
    }
    if (
        not class_names
        or not isinstance(per_class, int)
        or any(count != per_class for count in class_counts.values())
        or sum(class_counts.values()) != len(sources)
    ):
        blockers.append("SOURCE_CLASS_DENOMINATOR_MISMATCH")
    if binding.get("source_manifest_sha256") != input_digests["source_manifest"]:
        blockers.append("SOURCE_MANIFEST_BINDING_MISMATCH")
    if binding.get("prediction_manifest_sha256") != input_digests["predictions"]:
        blockers.append("PREDICTION_MANIFEST_BINDING_MISMATCH")
    if binding.get("source_contract_sha256") != input_digests["source_contract"]:
        blockers.append("SOURCE_CONTRACT_BINDING_MISMATCH")

    prediction_by_id = {
        str(row.get("unit_id")): row
        for row in predictions
        if isinstance(row.get("unit_id"), str)
    }
    if set(prediction_by_id) != set(source_by_id) or len(predictions) != len(source_by_id):
        blockers.append("PREDICTION_DENOMINATOR_MISMATCH")

    representations = contract.get("representations")
    representation_map = representations if isinstance(representations, Mapping) else {}
    visual_units = {
        unit_id
        for unit_id, row in source_by_id.items()
        if isinstance(representation_map.get(str(row.get("source_class"))), Mapping)
        and representation_map[str(row.get("source_class"))].get("visual_required") is True
    }
    profile_hash = input_digests["render_profile"]
    runtime_hash = input_digests["render_runtime"]
    render_by_id: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(renders):
        prefix = f"RENDER_{index:04d}"
        if set(row) != RENDER_FIELDS:
            blockers.append(f"{prefix}_SCHEMA_INVALID")
        unit_id = row.get("unit_id")
        if not isinstance(unit_id, str) or unit_id in render_by_id:
            blockers.append(f"{prefix}_UNIT_ID_INVALID_OR_DUPLICATE")
            continue
        render_by_id[unit_id] = row
        source = source_by_id.get(unit_id)
        if source is None:
            blockers.append(f"{prefix}_SOURCE_UNKNOWN")
        else:
            if row.get("source_sha256") != source.get("source_sha256"):
                blockers.append(f"{prefix}_SOURCE_DIGEST_MISMATCH")
            if row.get("target_locator") != source.get("target_locator"):
                blockers.append(f"{prefix}_LOCATOR_MISMATCH")
        if row.get("render_profile_sha256") != profile_hash:
            blockers.append(f"{prefix}_PROFILE_MISMATCH")
        if row.get("render_runtime_sha256") != runtime_hash:
            blockers.append(f"{prefix}_RUNTIME_MISMATCH")
        _verify_file(
            root=render_root,
            relative=row.get("render_relative_path"),
            expected_sha=row.get("render_sha256"),
            expected_size=row.get("render_size_bytes"),
            prefix=prefix,
            blockers=blockers,
        )
    if set(render_by_id) != visual_units or len(renders) != len(visual_units):
        blockers.append("RENDER_DENOMINATOR_MISMATCH")

    bound_models = binding.get("models")
    model_map = bound_models if isinstance(bound_models, Mapping) else {}
    if snapshot_binding.get("schema") != "tavonel.router_model_snapshot_binding.v1":
        blockers.append("MODEL_SNAPSHOT_SCHEMA_INVALID")
    if (
        snapshot_binding.get("state") != "FROZEN_BEFORE_REMOTE_EXECUTION"
        or snapshot_binding.get("truth_opened") is not False
        or snapshot_binding.get("model_calls") != 0
        or snapshot_binding.get("production_promotion") is not False
    ):
        blockers.append("MODEL_SNAPSHOT_STATE_INVALID")
    raw_snapshot_models = snapshot_binding.get("models")
    snapshot_models = (
        raw_snapshot_models if isinstance(raw_snapshot_models, Mapping) else {}
    )
    if set(snapshot_models) != set(model_map):
        blockers.append("MODEL_SNAPSHOT_DENOMINATOR_MISMATCH")
    artifact_by_key: dict[str, Mapping[str, Any]] = {}
    expected_model_files: set[str] = set()
    for index, row in enumerate(model_artifacts):
        prefix = f"MODEL_{index:04d}"
        if set(row) != MODEL_FIELDS:
            blockers.append(f"{prefix}_SCHEMA_INVALID")
        model_key_value = row.get("model_key")
        if (
            not isinstance(model_key_value, str)
            or model_key_value in artifact_by_key
        ):
            blockers.append(f"{prefix}_KEY_INVALID_OR_DUPLICATE")
            continue
        artifact_by_key[model_key_value] = row
        bound = model_map.get(model_key_value)
        if not isinstance(bound, Mapping):
            blockers.append(f"{prefix}_KEY_NOT_BOUND")
            continue
        snapshot = snapshot_models.get(model_key_value)
        if not isinstance(snapshot, Mapping) or set(snapshot) != SNAPSHOT_FIELDS:
            blockers.append(f"{prefix}_SNAPSHOT_INVALID")
            snapshot = {}
        for field in (
            "model_revision",
            "runtime_sha256",
            "bundle_sha256",
            "inference_config_sha256",
        ):
            if row.get(field) != bound.get(field):
                blockers.append(f"{prefix}_{field.upper()}_MISMATCH")
        verified_model_paths: dict[str, Path] = {}
        for field, relative_field in (
            ("runtime_sha256", "runtime_relative_path"),
            ("bundle_sha256", "bundle_relative_path"),
            ("inference_config_sha256", "inference_config_relative_path"),
        ):
            verified_path = _verify_file(
                root=model_root,
                relative=row.get(relative_field),
                expected_sha=row.get(field),
                expected_size=None,
                prefix=f"{prefix}_{field.removesuffix('_sha256').upper()}",
                blockers=blockers,
            )
            if verified_path is not None and isinstance(row.get(relative_field), str):
                expected_model_files.add(str(row[relative_field]).replace("\\", "/"))
                verified_model_paths[field] = verified_path
        runtime_path = verified_model_paths.get("runtime_sha256")
        if runtime_path is not None:
            try:
                runtime_value = load_json(runtime_path)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                blockers.append(f"{prefix}_RUNTIME_JSON_INVALID")
            else:
                if runtime_value.get("model_key") != model_key_value:
                    blockers.append(f"{prefix}_RUNTIME_MODEL_KEY_MISMATCH")
                if runtime_value.get("model_revision") != row.get("model_revision"):
                    blockers.append(f"{prefix}_RUNTIME_MODEL_REVISION_MISMATCH")
                if runtime_value.get("model_repo") != snapshot.get("repository"):
                    blockers.append(f"{prefix}_RUNTIME_MODEL_REPOSITORY_MISMATCH")
                base_image = runtime_value.get("base_image")
                if not isinstance(base_image, str) or not PINNED_IMAGE.fullmatch(
                    base_image
                ):
                    blockers.append(f"{prefix}_RUNTIME_BASE_IMAGE_NOT_PINNED")
        weights = row.get("weight_files")
        if not isinstance(weights, list) or not weights:
            blockers.append(f"{prefix}_WEIGHTS_REQUIRED")
        else:
            seen_weights: set[str] = set()
            for weight_index, weight in enumerate(weights):
                weight_prefix = f"{prefix}_WEIGHT_{weight_index:04d}"
                if not isinstance(weight, Mapping) or set(weight) != WEIGHT_FIELDS:
                    blockers.append(f"{weight_prefix}_SCHEMA_INVALID")
                    continue
                relative = weight.get("relative_path")
                if not isinstance(relative, str) or relative in seen_weights:
                    blockers.append(f"{weight_prefix}_PATH_DUPLICATE_OR_INVALID")
                else:
                    seen_weights.add(relative)
                    expected_model_files.add(relative.replace("\\", "/"))
                _verify_file(
                    root=model_root,
                    relative=relative,
                    expected_sha=weight.get("sha256"),
                    expected_size=weight.get("size_bytes"),
                    prefix=weight_prefix,
                    blockers=blockers,
                )
        snapshot_files = snapshot.get("files")
        if not isinstance(snapshot_files, list) or not snapshot_files:
            blockers.append(f"{prefix}_SNAPSHOT_FILES_REQUIRED")
        elif weights != snapshot_files:
            blockers.append(f"{prefix}_WEIGHT_SNAPSHOT_MISMATCH")
        if snapshot.get("revision") != row.get("model_revision"):
            blockers.append(f"{prefix}_SNAPSHOT_REVISION_MISMATCH")
        if not isinstance(snapshot.get("official_file_count"), int) or not SHA.fullmatch(
            str(snapshot.get("official_snapshot_descriptor_sha256"))
        ):
            blockers.append(f"{prefix}_SNAPSHOT_PROVENANCE_INVALID")
    if set(artifact_by_key) != set(model_map) or len(model_artifacts) != len(model_map):
        blockers.append("MODEL_ARTIFACT_DENOMINATOR_MISMATCH")
    actual_model_files: set[str] = set()
    if not model_root.is_dir():
        blockers.append("MODEL_ARTIFACT_ROOT_MISSING")
    else:
        for path in model_root.rglob("*"):
            if path.is_symlink():
                blockers.append("MODEL_ARTIFACT_SYMLINK_FORBIDDEN")
            if path.is_file():
                actual_model_files.add(path.relative_to(model_root).as_posix())
    if actual_model_files != expected_model_files:
        blockers.append("MODEL_ARTIFACT_FILE_DENOMINATOR_MISMATCH")

    request_pairs: set[tuple[str, str]] = set()
    for index, row in enumerate(requests):
        prefix = f"REQUEST_{index:04d}"
        if set(row) != REQUEST_FIELDS:
            blockers.append(f"{prefix}_SCHEMA_INVALID")
        unit_id = row.get("unit_id")
        model_key = row.get("model_key")
        if not isinstance(unit_id, str) or not isinstance(model_key, str):
            blockers.append(f"{prefix}_IDENTITY_INVALID")
            continue
        pair = (unit_id, model_key)
        if pair in request_pairs:
            blockers.append(f"{prefix}_PAIR_DUPLICATE")
        request_pairs.add(pair)
        source = source_by_id.get(unit_id)
        render = render_by_id.get(unit_id)
        model = artifact_by_key.get(model_key)
        if source is None or render is None or model is None:
            blockers.append(f"{prefix}_INPUT_UNBOUND")
            continue
        expected = {
            "source_sha256": source.get("source_sha256"),
            "target_locator": source.get("target_locator"),
            "render_sha256": render.get("render_sha256"),
            "router_policy_sha256": binding.get("router_policy_sha256"),
            "runtime_sha256": model.get("runtime_sha256"),
            "bundle_sha256": model.get("bundle_sha256"),
            "inference_config_sha256": model.get("inference_config_sha256"),
        }
        for field, expected_value in expected.items():
            if row.get(field) != expected_value:
                blockers.append(f"{prefix}_{field.upper()}_MISMATCH")
        expected_id = _request_id(unit_id, model_key, str(render.get("render_sha256")))
        if row.get("request_id") != expected_id:
            blockers.append(f"{prefix}_REQUEST_ID_MISMATCH")
    expected_pairs = {(unit_id, key) for unit_id in visual_units for key in model_map}
    if request_pairs != expected_pairs or len(requests) != len(expected_pairs):
        blockers.append("REQUEST_DENOMINATOR_MISMATCH")

    budget = protocol.get("execution_budget")
    budget_map = budget if isinstance(budget, Mapping) else {}
    if limits.get("state") != "FROZEN_BEFORE_EXECUTION":
        blockers.append("EXECUTION_LIMITS_NOT_FROZEN")
    for limit_field, protocol_field in (
        ("maximum_new_gpu_spend_usd", "maximum_new_gpu_spend_usd"),
        ("maximum_model_unit_calls", "maximum_model_unit_calls"),
        ("maximum_parallel_pods", "maximum_parallel_pods"),
    ):
        limit_value = limits.get(limit_field)
        maximum = budget_map.get(protocol_field)
        hard_maximum = HARD_EXECUTION_CAPS[limit_field]
        if maximum != hard_maximum:
            blockers.append(f"PROTOCOL_{protocol_field.upper()}_HARD_CAP_MISMATCH")
        if (
            not isinstance(limit_value, (int, float))
            or isinstance(limit_value, bool)
            or not math.isfinite(float(limit_value))
            or limit_value < 0
            or (
                limit_field != "maximum_new_gpu_spend_usd"
                and not isinstance(limit_value, int)
            )
        ):
            blockers.append(f"EXECUTION_{limit_field.upper()}_INVALID")
        elif (
            not isinstance(maximum, (int, float))
            or limit_value > maximum
            or limit_value > hard_maximum
        ):
            blockers.append(f"EXECUTION_{limit_field.upper()}_EXCEEDED")
    if limits.get("maximum_model_unit_calls") != len(expected_pairs):
        blockers.append("EXECUTION_CALL_DENOMINATOR_NOT_EXACT")

    ordered = tuple(dict.fromkeys(blockers))
    return AdmissionResult(
        passed=not ordered,
        blockers=ordered,
        units=len(sources),
        rendered_units=len(renders),
        models=len(model_artifacts),
        requests=len(requests),
        input_digests=input_digests,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    for name in (
        "binding",
        "preopen-result",
        "protocol",
        "source-manifest",
        "development-inventory",
        "candidate-inventory",
        "predictions",
        "source-contract",
        "source-root",
        "render-manifest",
        "render-root",
        "render-profile",
        "render-runtime",
        "model-manifest",
        "model-snapshot-binding",
        "model-root",
        "request-manifest",
        "execution-limits",
        "truth-root",
        "repo-root",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    result = evaluate_admission(
        binding_path=args.binding,
        preopen_result_path=args.preopen_result,
        protocol_path=args.protocol,
        source_manifest_path=args.source_manifest,
        development_inventory_path=args.development_inventory,
        candidate_inventory_path=args.candidate_inventory,
        predictions_path=args.predictions,
        source_contract_path=args.source_contract,
        source_root=args.source_root,
        render_manifest_path=args.render_manifest,
        render_root=args.render_root,
        render_profile_path=args.render_profile,
        render_runtime_path=args.render_runtime,
        model_manifest_path=args.model_manifest,
        model_snapshot_binding_path=args.model_snapshot_binding,
        model_root=args.model_root,
        request_manifest_path=args.request_manifest,
        execution_limits_path=args.execution_limits,
        truth_root=args.truth_root,
        repo_root=args.repo_root,
    )
    payload = (
        json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    _write_immutable_receipt(args.output, payload)
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
