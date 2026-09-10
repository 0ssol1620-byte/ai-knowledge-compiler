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


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    blockers: tuple[str, ...]
    units: int
    class_counts: Mapping[str, int]
    protocol_sha256: str
    manifest_sha256: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.router_mixed_source_preflight_result.v1",
            "passed": self.passed,
            "blockers": list(self.blockers),
            "units": self.units,
            "class_counts": dict(sorted(self.class_counts.items())),
            "protocol_sha256": self.protocol_sha256,
            "manifest_sha256": self.manifest_sha256,
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
            key.lower() in FORBIDDEN_PREDICTION_KEYS or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    return False


def evaluate_preopen(
    *,
    protocol_path: Path,
    binding_path: Path,
    manifest_path: Path,
    development_hashes_path: Path,
    candidate_inventory_path: Path,
    predictions_path: Path,
    truth_root: Path,
) -> GateResult:
    blockers: list[str] = []
    protocol_bytes = protocol_path.read_bytes()
    protocol_hash = digest(protocol_bytes)
    protocol = load_json(protocol_path)
    binding = load_json(binding_path)
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

    ordered = tuple(dict.fromkeys(blockers))
    return GateResult(
        passed=not ordered,
        blockers=ordered,
        units=len(rows),
        class_counts=dict(counts),
        protocol_sha256=protocol_hash,
        manifest_sha256=manifest_hash,
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
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result.as_dict(), indent=2) + "\n", encoding="utf-8")
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
