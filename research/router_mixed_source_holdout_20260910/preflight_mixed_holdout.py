"""Fail-closed pre-open gate for the mixed-source Router holdout.

This module never downloads a source, reads annotations, launches a model or
opens a holdout. It verifies the immutable inputs required before those actions
can be authorized. A failed row stays a named blocker instead of disappearing
from the denominator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

EXPECTED_SCHEMA = "tavonel.router_mixed_source_holdout_protocol.v1"
EXPECTED_BINDING_SCHEMA = "tavonel.router_mixed_source_holdout_binding.v1"
ALLOWED_RIGHTS = frozenset({"public_domain", "public_research_allowed", "open_licence"})
SHA_PREFIX = "sha256:"
MANIFEST_FIELDS = frozenset(
    {
        "unit_id",
        "source_class",
        "source_sha256",
        "source_size_bytes",
        "media_type",
        "source_family_id",
        "source_url",
        "selection_url_sha256",
        "rights_status",
        "rights_evidence_url",
        "rights_checked_at_utc",
        "allowed_use_scope",
        "language",
        "publisher",
        "acquired_at_utc",
        "target_locator_kind",
        "target_locator",
        "truth_state",
    }
)
PREDICTION_FIELDS = frozenset(
    {"unit_id", "source_sha256", "router_policy_sha256", "route_plan"}
)
FORBIDDEN_PREDICTION_KEYS = frozenset(
    {
        "answer",
        "expected_answer",
        "evaluator_score",
        "gold",
        "ground_truth",
        "hidden_score",
        "label",
        "reference_answer",
        "target_value",
        "truth",
    }
)
FORBIDDEN_PREDICTION_KEY_TOKENS = frozenset(
    {
        "annotation",
        "answer",
        "evaluation",
        "evaluator",
        "gold",
        "label",
        "score",
        "truth",
    }
)
FORBIDDEN_PREDICTION_KEY_PHRASES = frozenset(
    {
        "document_content",
        "document_text",
        "expected_result",
        "expected_value",
        "hidden_result",
        "model_output",
        "reference_value",
        "source_content",
        "source_text",
        "target_value",
    }
)
BOUND_ARTIFACTS = {
    "freeze_generator": "freeze_generator_sha256",
    "native_runtime": "native_runtime_sha256",
    "source_contract": "source_contract_sha256",
    "router_policy": "router_policy_sha256",
    "evaluator": "evaluator_sha256",
    "statistics": "statistics_sha256",
    "model_identity_source": "model_identity_source_sha256",
    "model_snapshot_binding": "model_snapshot_binding_sha256",
    "render_generator": "render_generator_sha256",
    "office_render_script": "office_render_script_sha256",
}
POST_RENDER_ARTIFACTS = {
    "render_manifest_sha256": "RENDER_MANIFEST.jsonl",
    "render_profile_sha256": "RENDER_PROFILE.json",
    "render_runtime_sha256": "RENDER_RUNTIME.json",
    "render_generator_sha256": "render_selected_inputs.py",
    "office_script_sha256": "office_render.ps1",
}


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    blockers: tuple[str, ...]
    units: int
    class_counts: Mapping[str, int]
    protocol_sha256: str
    manifest_sha256: str | None
    binding_sha256: str
    candidate_inventory_sha256: str
    development_inventory_sha256: str
    prediction_manifest_sha256: str
    router_policy_sha256: str | None
    source_bytes_verified: bool
    native_runtime_files_verified: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.router_mixed_source_preflight_result.v1",
            "passed": self.passed,
            "blockers": list(self.blockers),
            "units": self.units,
            "class_counts": dict(sorted(self.class_counts.items())),
            "protocol_sha256": self.protocol_sha256,
            "manifest_sha256": self.manifest_sha256,
            "binding_sha256": self.binding_sha256,
            "candidate_inventory_sha256": self.candidate_inventory_sha256,
            "development_inventory_sha256": self.development_inventory_sha256,
            "prediction_manifest_sha256": self.prediction_manifest_sha256,
            "router_policy_sha256": self.router_policy_sha256,
            "source_bytes_verified": self.source_bytes_verified,
            "native_runtime_files_verified": self.native_runtime_files_verified,
            "holdout_opened": False,
            "model_calls": 0,
            "production_promotion": False,
        }


def digest(data: bytes) -> str:
    return SHA_PREFIX + hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}:OBJECT_REQUIRED")
    return value


def load_jsonl(path: Path) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{number}:OBJECT_REQUIRED")
        rows.append(value)
    return rows


def _sha(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith(SHA_PREFIX):
        return False
    body = value.removeprefix(SHA_PREFIX)
    return len(body) == 64 and all(character in "0123456789abcdef" for character in body)


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _revision(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def _utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return False
    return True


def _strict_https_url(value: object) -> bool:
    if not _nonempty(value):
        return False
    parsed = urlparse(str(value))
    try:
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and port is None
        and not parsed.fragment
        and parsed.netloc == parsed.hostname.lower()
    )


def _json_value(value: object) -> bool:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return True
    if isinstance(value, list):
        return all(_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_value(item) for key, item in value.items())
    return False


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    if isinstance(value, dict):
        return any(
            _forbidden_prediction_key(key) or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    return False


def _forbidden_prediction_key(key: object) -> bool:
    if not isinstance(key, str):
        return True
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    if normalized in FORBIDDEN_PREDICTION_KEYS:
        return True
    if any(phrase in normalized for phrase in FORBIDDEN_PREDICTION_KEY_PHRASES):
        return True
    tokens = normalized.split("_")
    return any(
        token in FORBIDDEN_PREDICTION_KEY_TOKENS
        or token.removesuffix("s") in FORBIDDEN_PREDICTION_KEY_TOKENS
        for token in tokens
    )


def evaluate_preopen(
    *,
    protocol_path: Path,
    binding_path: Path,
    manifest_path: Path,
    development_hashes_path: Path,
    candidate_inventory_path: Path,
    predictions_path: Path,
    truth_root: Path,
    source_root: Path,
    repo_root: Path,
) -> GateResult:
    blockers: list[str] = []
    protocol_bytes = protocol_path.read_bytes()
    protocol_hash = digest(protocol_bytes)
    protocol = load_json(protocol_path)
    binding = load_json(binding_path)
    binding_hash = digest(binding_path.read_bytes())
    manifest_bytes = manifest_path.read_bytes()
    manifest_hash = digest(manifest_bytes)
    rows = load_jsonl(manifest_path)
    candidate_inventory_bytes = candidate_inventory_path.read_bytes()
    development = load_json(development_hashes_path)
    development_bytes = development_hashes_path.read_bytes()
    prediction_bytes = predictions_path.read_bytes()
    predictions = load_jsonl(predictions_path)

    if protocol.get("schema") != EXPECTED_SCHEMA:
        blockers.append("PROTOCOL_SCHEMA_MISMATCH")
    if protocol.get("state") != "FROZEN_SELECTION_PROTOCOL" or not protocol.get(
        "frozen_before_acquisition"
    ):
        blockers.append("SELECTION_PROTOCOL_NOT_FROZEN")
    if binding.get("schema") != EXPECTED_BINDING_SCHEMA:
        blockers.append("BINDING_SCHEMA_MISMATCH")
    if binding.get("state") != "FROZEN_PREOPEN":
        blockers.append("RUNTIME_BINDING_NOT_FROZEN")
    truth_relative = binding.get("truth_root_relative_path")
    frozen_truth = (
        repo_root / truth_relative
        if isinstance(truth_relative, str)
        and truth_relative
        and not Path(truth_relative).is_absolute()
        and ".." not in Path(truth_relative).parts
        else None
    )
    if frozen_truth is None or frozen_truth.resolve() != truth_root.resolve():
        blockers.append("CANONICAL_TRUTH_ROOT_BINDING_MISMATCH")
    if binding.get("protocol_sha256") != protocol_hash:
        blockers.append("PROTOCOL_DIGEST_MISMATCH")
    if binding.get("source_manifest_sha256") != manifest_hash:
        blockers.append("MANIFEST_DIGEST_MISMATCH")
    if binding.get("candidate_inventory_sha256") != digest(candidate_inventory_bytes):
        blockers.append("CANDIDATE_INVENTORY_DIGEST_MISMATCH")
    if binding.get("development_inventory_sha256") != digest(development_bytes):
        blockers.append("DEVELOPMENT_INVENTORY_DIGEST_MISMATCH")
    if binding.get("prediction_manifest_sha256") != digest(prediction_bytes):
        blockers.append("PREDICTION_MANIFEST_DIGEST_MISMATCH")
    if binding.get("preflight_sha256") != digest(Path(__file__).read_bytes()):
        blockers.append("PREFLIGHT_DIGEST_MISMATCH")
    artifact_paths = binding.get("artifact_paths")
    artifact_map = artifact_paths if isinstance(artifact_paths, Mapping) else {}
    if set(artifact_map) != set(BOUND_ARTIFACTS):
        blockers.append("BOUND_ARTIFACT_PATHS_INVALID")
    bound_artifacts: dict[str, Path] = {}
    for artifact_name, digest_field in BOUND_ARTIFACTS.items():
        raw_path = artifact_map.get(artifact_name)
        relative = Path(str(raw_path)) if _nonempty(raw_path) else None
        if (
            relative is None
            or relative.is_absolute()
            or len(relative.parts) != 1
            or relative.name != str(raw_path)
        ):
            blockers.append(f"BOUND_ARTIFACT_{artifact_name.upper()}_PATH_INVALID")
            continue
        path = binding_path.parent / relative
        bound_artifacts[artifact_name] = path
        if not path.is_file():
            blockers.append(f"BOUND_ARTIFACT_{artifact_name.upper()}_MISSING")
        elif binding.get(digest_field) != digest(path.read_bytes()):
            blockers.append(f"BOUND_ARTIFACT_{artifact_name.upper()}_DIGEST_MISMATCH")
    post_render = binding.get("post_render_artifacts")
    if post_render is not None:
        post_render_map = post_render if isinstance(post_render, Mapping) else {}
        if set(post_render_map) != set(POST_RENDER_ARTIFACTS):
            blockers.append("POST_RENDER_ARTIFACTS_SCHEMA_INVALID")
        for digest_field, filename in POST_RENDER_ARTIFACTS.items():
            artifact = binding_path.parent / filename
            if not artifact.is_file():
                blockers.append(f"POST_RENDER_{digest_field.upper()}_MISSING")
            elif post_render_map.get(digest_field) != digest(artifact.read_bytes()):
                blockers.append(f"POST_RENDER_{digest_field.upper()}_DIGEST_MISMATCH")
    if truth_root.exists() and any(truth_root.iterdir()):
        blockers.append("HOLDOUT_TRUTH_ALREADY_PRESENT")

    benchmark_id = protocol.get("benchmark_id")
    if not _nonempty(benchmark_id) or binding.get("benchmark_id") != benchmark_id:
        blockers.append("BENCHMARK_ID_MISMATCH")
    required_classes = tuple(protocol.get("required_classes") or ())
    if not required_classes or not all(_nonempty(value) for value in required_classes):
        blockers.append("REQUIRED_CLASSES_INVALID")
    if len(set(required_classes)) != len(required_classes):
        blockers.append("REQUIRED_CLASSES_DUPLICATED")
    selection = protocol.get("source_selection")
    selection_map = selection if isinstance(selection, Mapping) else {}
    minimum = selection_map.get("minimum_units_per_class")
    maximum = selection_map.get("maximum_units_per_class")
    selected_per_class = selection_map.get("selected_units_per_class")
    total_maximum = selection_map.get("maximum_total_units")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        blockers.append("MINIMUM_CLASS_SIZE_INVALID")
        minimum = 1
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < minimum:
        blockers.append("MAXIMUM_CLASS_SIZE_INVALID")
        maximum = minimum
    if not isinstance(total_maximum, int) or isinstance(total_maximum, bool) or total_maximum < 1:
        blockers.append("TOTAL_SIZE_INVALID")
        total_maximum = 0
    if (
        not isinstance(selected_per_class, int)
        or isinstance(selected_per_class, bool)
        or selected_per_class < 1
        or selected_per_class != minimum
        or selected_per_class != maximum
    ):
        blockers.append("SELECTED_CLASS_SIZE_NOT_EXACT")
        selected_per_class = minimum
    if total_maximum != selected_per_class * len(required_classes):
        blockers.append("TOTAL_SIZE_NOT_EXACT")

    counts: Counter[str] = Counter()
    ids: set[str] = set()
    source_hashes: set[str] = set()
    source_urls: set[str] = set()
    family_ids: set[str] = set()
    if development.get("schema") != "tavonel.router_development_inventory.v1":
        blockers.append("DEVELOPMENT_INVENTORY_SCHEMA_MISMATCH")
    raw_development_hashes = development.get("source_sha256")
    raw_development_families = development.get("source_family_ids")
    if not isinstance(raw_development_hashes, list) or not all(
        _sha(value) for value in raw_development_hashes
    ):
        blockers.append("DEVELOPMENT_SOURCE_HASHES_INVALID")
        development_hashes: set[object] = set()
    else:
        development_hashes = set(raw_development_hashes)
    if not isinstance(raw_development_families, list) or not all(
        _nonempty(value) for value in raw_development_families
    ):
        blockers.append("DEVELOPMENT_FAMILY_IDS_INVALID")
        development_families: set[object] = set()
    else:
        development_families = set(raw_development_families)
    allowed_source_hosts_value = binding.get("allowed_source_hosts")
    allowed_source_hosts = (
        {str(host).lower() for host in allowed_source_hosts_value}
        if isinstance(allowed_source_hosts_value, list)
        and all(_nonempty(host) and "*" not in str(host) for host in allowed_source_hosts_value)
        else set()
    )
    if not allowed_source_hosts:
        blockers.append("ALLOWED_SOURCE_HOSTS_REQUIRED")
    for index, row in enumerate(rows):
        prefix = f"ROW_{index:04d}"
        unit_id = row.get("unit_id")
        class_name = row.get("source_class")
        source_hash = row.get("source_sha256")
        family = row.get("source_family_id")
        url = row.get("source_url")
        rights = row.get("rights_status")
        unexpected_fields = set(row).difference(MANIFEST_FIELDS)
        if unexpected_fields:
            blockers.append(f"{prefix}_UNEXPECTED_FIELDS")
        if not _nonempty(unit_id) or unit_id in ids:
            blockers.append(f"{prefix}_UNIT_ID_INVALID_OR_DUPLICATE")
        else:
            ids.add(str(unit_id))
        if class_name not in required_classes:
            blockers.append(f"{prefix}_SOURCE_CLASS_INVALID")
        else:
            counts[str(class_name)] += 1
        if not _sha(source_hash) or source_hash in source_hashes:
            blockers.append(f"{prefix}_SOURCE_DIGEST_INVALID_OR_DUPLICATE")
        else:
            source_hashes.add(str(source_hash))
            if source_hash in development_hashes:
                blockers.append(f"{prefix}_DEVELOPMENT_SOURCE_OVERLAP")
        if not _nonempty(family) or family in family_ids:
            blockers.append(f"{prefix}_SOURCE_FAMILY_INVALID_OR_DUPLICATE")
        else:
            family_ids.add(str(family))
            if family in development_families:
                blockers.append(f"{prefix}_DEVELOPMENT_FAMILY_OVERLAP")
        parsed = urlparse(str(url)) if _strict_https_url(url) else None
        if parsed is None:
            blockers.append(f"{prefix}_HTTPS_SOURCE_REQUIRED")
        elif str(parsed.hostname).lower() not in allowed_source_hosts:
            blockers.append(f"{prefix}_SOURCE_HOST_NOT_BOUND")
        elif url in source_urls:
            blockers.append(f"{prefix}_SOURCE_URL_DUPLICATE")
        else:
            source_urls.add(str(url))
            if row.get("selection_url_sha256") != digest(str(url).encode("utf-8")):
                blockers.append(f"{prefix}_SELECTION_URL_DIGEST_MISMATCH")
        if rights not in ALLOWED_RIGHTS:
            blockers.append(f"{prefix}_RIGHTS_UNQUALIFIED")
        if row.get("allowed_use_scope") != "local_research_evaluation_no_redistribution":
            blockers.append(f"{prefix}_USE_SCOPE_INVALID")
        if not _strict_https_url(row.get("rights_evidence_url")):
            blockers.append(f"{prefix}_RIGHTS_EVIDENCE_URL_INVALID")
        for field in (
            "language",
            "publisher",
            "media_type",
            "target_locator_kind",
            "target_locator",
        ):
            if not _nonempty(row.get(field)):
                blockers.append(f"{prefix}_{field.upper()}_REQUIRED")
        if not isinstance(row.get("source_size_bytes"), int) or isinstance(
            row.get("source_size_bytes"), bool
        ) or row.get("source_size_bytes", 0) < 1:
            blockers.append(f"{prefix}_SOURCE_SIZE_BYTES_INVALID")
        for field in ("acquired_at_utc", "rights_checked_at_utc"):
            if not _utc_timestamp(row.get(field)):
                blockers.append(f"{prefix}_{field.upper()}_INVALID")
        if row.get("truth_state") != "SEALED_UNOPENED":
            blockers.append(f"{prefix}_TRUTH_STATE_INVALID")

    class_order = {class_name: index for index, class_name in enumerate(required_classes)}
    observed_order = [
        (
            class_order.get(str(row.get("source_class")), len(class_order)),
            row.get("selection_url_sha256"),
        )
        for row in rows
    ]
    if all(_sha(item[1]) for item in observed_order) and observed_order != sorted(observed_order):
        blockers.append("SOURCE_SELECTION_ORDER_INVALID")

    for class_name in required_classes:
        count = counts[class_name]
        if count < minimum:
            blockers.append(f"CLASS_{class_name}_BELOW_MINIMUM")
        if count > maximum:
            blockers.append(f"CLASS_{class_name}_ABOVE_MAXIMUM")
        if count != selected_per_class:
            blockers.append(f"CLASS_{class_name}_NOT_EXACT")
    if len(rows) > total_maximum:
        blockers.append("TOTAL_SIZE_EXCEEDED")
    if len(rows) != total_maximum:
        blockers.append("TOTAL_SIZE_NOT_MET")
    if len(rows) != len(ids):
        blockers.append("DENOMINATOR_IDENTITY_INCOMPLETE")

    raw_model_keys = tuple(protocol.get("model_keys") or ())
    if not raw_model_keys or not all(_nonempty(value) for value in raw_model_keys):
        blockers.append("MODEL_KEYS_INVALID")
    if len(set(raw_model_keys)) != len(raw_model_keys):
        blockers.append("MODEL_KEYS_DUPLICATED")
    model_keys = set(raw_model_keys)
    models = binding.get("models")
    model_map = models if isinstance(models, Mapping) else {}
    if set(model_map) != model_keys:
        blockers.append("MODEL_PORTFOLIO_MISMATCH")
    for model_key in sorted(model_keys):
        model = model_map.get(model_key)
        model_row = model if isinstance(model, Mapping) else {}
        identity_fields = (
            "model_revision",
            "runtime_sha256",
            "bundle_sha256",
            "inference_config_sha256",
        )
        for field in identity_fields:
            if not _nonempty(model_row.get(field)):
                blockers.append(f"MODEL_{model_key}_{field.upper()}_REQUIRED")
        if _nonempty(model_row.get("model_revision")) and not _revision(
            model_row.get("model_revision")
        ):
            blockers.append(f"MODEL_{model_key}_MODEL_REVISION_INVALID")
        for field in ("runtime_sha256", "bundle_sha256", "inference_config_sha256"):
            if _nonempty(model_row.get(field)) and not _sha(model_row.get(field)):
                blockers.append(f"MODEL_{model_key}_{field.upper()}_INVALID")
    model_identity_path = bound_artifacts.get("model_identity_source")
    if model_identity_path is not None and model_identity_path.is_file():
        model_identity = load_json(model_identity_path)
        identity_models = model_identity.get("models")
        if (
            model_identity.get("schema")
            != "tavonel.router_model_identity_source.v1"
            or not isinstance(identity_models, Mapping)
            or identity_models != model_map
        ):
            blockers.append("MODEL_IDENTITY_SOURCE_MISMATCH")
    native_runtime_files_verified = True
    native_runtime_path = bound_artifacts.get("native_runtime")
    if native_runtime_path is not None and native_runtime_path.is_file():
        native_runtime = load_json(native_runtime_path)
        runtime_files = native_runtime.get("files")
        if not isinstance(runtime_files, list) or not runtime_files:
            blockers.append("NATIVE_RUNTIME_FILE_MANIFEST_INVALID")
            native_runtime_files_verified = False
        else:
            allowed_runtime_roots = (
                "packages/cir-python/src/",
                "packages/contracts/python/",
                "packages/native-parsers/src/",
                "packages/router/src/",
            )
            for index, runtime_file in enumerate(runtime_files):
                if not isinstance(runtime_file, Mapping):
                    blockers.append(f"NATIVE_RUNTIME_FILE_{index:04d}_INVALID")
                    native_runtime_files_verified = False
                    continue
                raw_relative = runtime_file.get("path")
                relative = Path(str(raw_relative)) if _nonempty(raw_relative) else None
                portable = str(raw_relative).replace("\\", "/")
                if (
                    relative is None
                    or relative.is_absolute()
                    or ".." in relative.parts
                    or not portable.startswith(allowed_runtime_roots)
                ):
                    blockers.append(f"NATIVE_RUNTIME_FILE_{index:04d}_PATH_INVALID")
                    native_runtime_files_verified = False
                    continue
                actual = repo_root / relative
                if not actual.is_file():
                    blockers.append(f"NATIVE_RUNTIME_FILE_{index:04d}_MISSING")
                    native_runtime_files_verified = False
                elif digest(actual.read_bytes()) != runtime_file.get("sha256"):
                    blockers.append(f"NATIVE_RUNTIME_FILE_{index:04d}_DIGEST_MISMATCH")
                    native_runtime_files_verified = False
    for field in (
        "native_runtime_sha256",
        "source_contract_sha256",
        "router_policy_sha256",
        "evaluator_sha256",
        "statistics_sha256",
    ):
        if not _sha(binding.get(field)):
            blockers.append(f"{field.upper()}_INVALID")
    if binding.get("predictions_frozen") is not True:
        blockers.append("ROUTE_PREDICTIONS_NOT_FROZEN")
    if binding.get("input_manifest_contains_truth") is not False:
        blockers.append("INPUT_MANIFEST_TRUTH_BOUNDARY_INVALID")
    prediction_by_id: dict[str, Mapping[str, Any]] = {}
    for index, prediction in enumerate(predictions):
        prefix = f"PREDICTION_{index:04d}"
        if set(prediction) != PREDICTION_FIELDS:
            blockers.append(f"{prefix}_SCHEMA_INVALID")
        prediction_id = prediction.get("unit_id")
        if not _nonempty(prediction_id) or prediction_id in prediction_by_id:
            blockers.append(f"{prefix}_UNIT_ID_INVALID_OR_DUPLICATE")
        else:
            prediction_by_id[str(prediction_id)] = prediction
        if not _sha(prediction.get("source_sha256")):
            blockers.append(f"{prefix}_SOURCE_DIGEST_INVALID")
        if prediction.get("router_policy_sha256") != binding.get("router_policy_sha256"):
            blockers.append(f"{prefix}_ROUTER_POLICY_MISMATCH")
        route_plan = prediction.get("route_plan")
        if not isinstance(route_plan, dict) or not route_plan or not _json_value(route_plan):
            blockers.append(f"{prefix}_ROUTE_PLAN_INVALID")
        elif _contains_forbidden_key(route_plan):
            blockers.append(f"{prefix}_ROUTE_PLAN_TRUTH_FIELD_FORBIDDEN")
    manifest_by_id = {
        str(row.get("unit_id")): row for row in rows if _nonempty(row.get("unit_id"))
    }
    if set(prediction_by_id) != set(manifest_by_id):
        blockers.append("PREDICTION_DENOMINATOR_MISMATCH")
    else:
        for unit_id, prediction in prediction_by_id.items():
            if prediction.get("source_sha256") != manifest_by_id[unit_id].get("source_sha256"):
                blockers.append(f"PREDICTION_{unit_id}_SOURCE_MISMATCH")

    source_bytes_verified = True
    for unit_id, row in manifest_by_id.items():
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", unit_id):
            blockers.append(f"SOURCE_{unit_id}_UNIT_ID_UNSAFE")
            source_bytes_verified = False
            continue
        source_path = source_root / (unit_id.replace(":", "_") + ".source")
        if not source_path.is_file():
            blockers.append(f"SOURCE_{unit_id}_BYTES_MISSING")
            source_bytes_verified = False
            continue
        if source_path.stat().st_size != row.get("source_size_bytes"):
            blockers.append(f"SOURCE_{unit_id}_SIZE_MISMATCH")
            source_bytes_verified = False
        if digest(source_path.read_bytes()) != row.get("source_sha256"):
            blockers.append(f"SOURCE_{unit_id}_DIGEST_MISMATCH")
            source_bytes_verified = False

    ordered = tuple(dict.fromkeys(blockers))
    return GateResult(
        passed=not ordered,
        blockers=ordered,
        units=len(rows),
        class_counts=dict(counts),
        protocol_sha256=protocol_hash,
        manifest_sha256=manifest_hash,
        binding_sha256=binding_hash,
        candidate_inventory_sha256=digest(candidate_inventory_bytes),
        development_inventory_sha256=digest(development_bytes),
        prediction_manifest_sha256=digest(prediction_bytes),
        router_policy_sha256=(
            str(binding.get("router_policy_sha256"))
            if _sha(binding.get("router_policy_sha256"))
            else None
        ),
        source_bytes_verified=source_bytes_verified,
        native_runtime_files_verified=native_runtime_files_verified,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--development-hashes", type=Path, required=True)
    parser.add_argument("--candidate-inventory", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--truth-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = evaluate_preopen(
        protocol_path=args.protocol,
        binding_path=args.binding,
        manifest_path=args.manifest,
        development_hashes_path=args.development_hashes,
        candidate_inventory_path=args.candidate_inventory,
        predictions_path=args.predictions,
        truth_root=args.truth_root,
        source_root=args.source_root,
        repo_root=args.repo_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result.as_dict(), indent=2) + "\n", encoding="utf-8")
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
