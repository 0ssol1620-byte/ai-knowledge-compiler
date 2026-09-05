"""Validate `model_registry.json` and `evaluator_registry.json`.

Two schemas are checked, and both results are printed:

1. ``arena/registry/fallback_schemas/*.schema.json`` - ARENA_CONTRACT section 3.7
   / 3.8 plus the lane A3 brief's evidence fields. This one decides the exit code.
2. ``arena/core/schemas/*.schema.json`` (lane A1) when it exists. A mismatch here
   is reported as an INTERFACE CONFLICT naming every field, because two lanes
   cannot both be right about one record shape and the orchestrator has to
   resolve it. ``--strict-core`` makes that conflict fatal.

Nothing is skipped and nothing is silently downgraded: when lane A1's schema is
absent the report says so, and when it is present and disagrees the report says
exactly where.

Schema conformance is necessary but not sufficient. The structural checks below
carry the campaign invariants a JSON Schema cannot express - a 40-hex revision
for every GPU model, MinerU VLM's per-worker concurrency of 1, GPU pool names
that exist in the RunPod catalog, and the fail-closed state of
`full_run_eligible`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from arena.constants import BENCHMARK_KEYS, GPU_MODEL_KEYS, MODEL_KEYS, NAMESPACE_ROOT
from arena.registry.catalog import RUNPOD_GPU_CATALOG
from arena.registry.errors import SchemaValidationError
from arena.registry.models import HEX40

CORE_SCHEMA_DIR = NAMESPACE_ROOT / "arena" / "core" / "schemas"
FALLBACK_SCHEMA_DIR = Path(__file__).resolve().parent / "fallback_schemas"

MODEL_SCHEMA_NAME = "model-registry-record.schema.json"
EVALUATOR_SCHEMA_NAME = "evaluator-registry-record.schema.json"


@dataclass(frozen=True, slots=True)
class SchemaChoice:
    path: Path
    source: str  # "arena/core/schemas" | "arena/registry/fallback_schemas"

    @property
    def is_fallback(self) -> bool:
        return self.source.endswith("fallback_schemas")


@dataclass(frozen=True, slots=True)
class ValidationReport:
    file_path: Path
    schema: SchemaChoice
    record_count: int
    schema_errors: tuple[str, ...]
    structural_errors: tuple[str, ...]
    core_schema: SchemaChoice | None = None
    core_schema_errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.schema_errors and not self.structural_errors

    @property
    def core_ok(self) -> bool:
        return self.core_schema is None or not self.core_schema_errors

    def render(self) -> str:
        head = (
            f"{self.file_path.name}: {self.record_count} record(s) against "
            f"{self.schema.path.name} from {self.schema.source}"
        )
        lines = [f"{'OK  ' if self.ok else 'FAIL'} {head}"]
        lines += [f"  schema:     {message}" for message in self.schema_errors]
        lines += [f"  structural: {message}" for message in self.structural_errors]
        if self.core_schema is None:
            lines.append(
                "  note:       arena/core/schemas (lane A1) has no schema for this file "
                "yet; only the contract fallback schema was checked"
            )
        elif self.core_schema_errors:
            lines.append(
                f"  INTERFACE CONFLICT with {self.core_schema.source}/"
                f"{self.core_schema.path.name}: {len(self.core_schema_errors)} finding(s). "
                "Two lanes cannot both be right about one record shape; see the lane A3 "
                "report for the proposed resolution."
            )
            lines += [
                f"    conflict: {message}"
                for message in distinct_conflicts(self.core_schema_errors)
            ]
        else:
            lines.append(
                f"  also valid against {self.core_schema.source}/{self.core_schema.path.name}"
            )
        return "\n".join(lines)


def distinct_conflicts(messages: tuple[str, ...]) -> list[str]:
    """Collapse one conflict repeated across twelve records into a single line."""
    seen: dict[str, int] = {}
    for message in messages:
        key = message.split(": ", 1)[-1]
        seen[key] = seen.get(key, 0) + 1
    return [
        f"{key} (x{count})" if count > 1 else key
        for key, count in sorted(seen.items(), key=lambda item: (-item[1], item[0]))
    ]


def contract_schema(name: str) -> SchemaChoice:
    """The schema this lane's records are written against; decides the exit code."""
    fallback = FALLBACK_SCHEMA_DIR / name
    if not fallback.is_file():
        raise SchemaValidationError(f"no contract schema available for {name}")
    return SchemaChoice(path=fallback, source="arena/registry/fallback_schemas")


def core_schema(name: str) -> SchemaChoice | None:
    """Lane A1's schema, when it exists. Reported, never silently preferred."""
    core = CORE_SCHEMA_DIR / name
    if core.is_file():
        return SchemaChoice(path=core, source="arena/core/schemas")
    return None


def choose_schema(name: str) -> SchemaChoice:
    """A single schema for callers that want one; prefers lane A1's when present."""
    return core_schema(name) or contract_schema(name)


def _load(path: Path) -> Any:
    if not path.is_file():
        raise SchemaValidationError(
            f"{path} does not exist; run `python -m arena.registry resolve`"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_errors(validator: Draft202012Validator, key: str, record: Any) -> list[str]:
    return [
        f"{key}: {'/'.join(str(part) for part in error.absolute_path) or '<root>'}: "
        f"{error.message}"
        for error in sorted(validator.iter_errors(record), key=lambda e: list(e.absolute_path))
    ]


def structural_model_errors(document: Any) -> list[str]:
    """Campaign invariants a JSON Schema cannot express."""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["model_registry.json is not an object"]
    models = document.get("models")
    if not isinstance(models, dict):
        return ["model_registry.json has no 'models' object"]

    missing = [key for key in MODEL_KEYS if key not in models]
    if missing:
        errors.append(f"missing records for {missing}")
    extra = [key for key in models if key not in MODEL_KEYS]
    if extra:
        errors.append(f"records for keys outside arena.constants.MODEL_KEYS: {extra}")

    for key in GPU_MODEL_KEYS:
        record = models.get(key)
        if not isinstance(record, dict):
            continue
        revision = record.get("revision")
        if not isinstance(revision, str) or not HEX40.match(revision):
            errors.append(f"{key}: revision {revision!r} is not a 40-hex commit id")
        weights = record.get("weights")
        if isinstance(weights, dict):
            weights_revision = weights.get("revision")
            if not isinstance(weights_revision, str) or not HEX40.match(weights_revision):
                errors.append(
                    f"{key}: weights.revision {weights_revision!r} is not a 40-hex commit id"
                )
        if not record.get("gpu_pool_priority"):
            errors.append(f"{key}: gpu_pool_priority is empty; the scheduler has nothing to try")

    for key, record in models.items():
        if not isinstance(record, dict):
            errors.append(f"{key}: record is not an object")
            continue
        if record.get("full_run_eligible") is not False:
            errors.append(
                f"{key}: full_run_eligible must stay false until the canary passes "
                "(ARENA_CONTRACT section 3.7)"
            )
        if record.get("canary_status") != "PENDING":
            errors.append(f"{key}: canary_status must be PENDING before any canary runs")
        for field in ("recommended_gpu_pool", "gpu_pool_priority"):
            pool = record.get(field)
            if isinstance(pool, list):
                unknown = [gpu for gpu in pool if gpu not in RUNPOD_GPU_CATALOG]
                if unknown:
                    errors.append(f"{key}: {field} names GPU types outside the catalog: {unknown}")

    vlm = models.get("mineru_vlm")
    if isinstance(vlm, dict):
        policy = vlm.get("concurrency_policy")
        if policy != {"per_worker": 1, "scale": "replicas_only"}:
            errors.append(
                "mineru_vlm: concurrency_policy must be exactly "
                '{"per_worker": 1, "scale": "replicas_only"} (masterplan section 14)'
            )
        if vlm.get("max_concurrency_per_worker") != 1:
            errors.append(
                "mineru_vlm: max_concurrency_per_worker must be 1 (masterplan section 14)"
            )

    opus = models.get("opus5_subscription")
    if isinstance(opus, dict) and opus.get("runtime_type") != "subscription":
        errors.append("opus5_subscription: runtime_type must be 'subscription'")

    return errors


def structural_evaluator_errors(document: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["evaluator_registry.json is not an object"]
    evaluators = document.get("evaluators")
    if not isinstance(evaluators, dict):
        return ["evaluator_registry.json has no 'evaluators' object"]

    missing = [key for key in BENCHMARK_KEYS if key not in evaluators]
    if missing:
        errors.append(f"missing evaluator records for {missing}")

    for key, record in evaluators.items():
        if not isinstance(record, dict):
            errors.append(f"{key}: record is not an object")
            continue
        historical = record.get("historical_pin")
        main = record.get("main_pin")
        head = record.get("upstream_head_at_start")
        if main not in (head, historical):
            errors.append(
                f"{key}: main_pin {main!r} is neither the verified upstream head "
                f"{head!r} nor the historical pin {historical!r}; the campaign only "
                "pins a revision it actually verified"
            )
        rationale = record.get("main_pin_rationale")
        if not isinstance(rationale, str) or len(rationale) < 120:
            errors.append(
                f"{key}: main_pin_rationale is missing or too short; masterplan "
                "section 1.1 requires a written reason for the pin that was chosen"
            )
        if main != historical and record.get("historical_lane_required") is not True:
            errors.append(
                f"{key}: main_pin moved away from the historical pin, so "
                "historical_lane_required must be true (masterplan section 1.1)"
            )
        for path in record.get("gt_paths") or []:
            if not str(path).startswith("benchmark/datasets/acquired/public-core"):
                errors.append(
                    f"{key}: gt_path {path!r} is outside the acquired ground-truth tree"
                )
    return errors


def _validate_records(
    path: Path,
    *,
    container_key: str,
    schema_name: str,
    structural: Callable[[Any], list[str]],
) -> ValidationReport:
    document = _load(path)
    raw = document.get(container_key) if isinstance(document, dict) else None
    records: dict[str, Any] = raw if isinstance(raw, dict) else {}
    keys = sorted(records)

    contract = contract_schema(schema_name)
    contract_validator = Draft202012Validator(
        json.loads(contract.path.read_text(encoding="utf-8"))
    )
    schema_errors: list[str] = []
    for key in keys:
        schema_errors.extend(_schema_errors(contract_validator, key, records[key]))

    core = core_schema(schema_name)
    core_errors: list[str] = []
    if core is not None:
        core_validator = Draft202012Validator(json.loads(core.path.read_text(encoding="utf-8")))
        for key in keys:
            core_errors.extend(_schema_errors(core_validator, key, records[key]))

    return ValidationReport(
        file_path=path,
        schema=contract,
        record_count=len(keys),
        schema_errors=tuple(schema_errors),
        structural_errors=tuple(structural(document)),
        core_schema=core,
        core_schema_errors=tuple(core_errors),
    )


def validate_model_registry(path: Path) -> ValidationReport:
    return _validate_records(
        path,
        container_key="models",
        schema_name=MODEL_SCHEMA_NAME,
        structural=structural_model_errors,
    )


def validate_evaluator_registry(path: Path) -> ValidationReport:
    return _validate_records(
        path,
        container_key="evaluators",
        schema_name=EVALUATOR_SCHEMA_NAME,
        structural=structural_evaluator_errors,
    )


__all__ = [
    "EVALUATOR_SCHEMA_NAME",
    "MODEL_SCHEMA_NAME",
    "SchemaChoice",
    "ValidationReport",
    "choose_schema",
    "contract_schema",
    "core_schema",
    "distinct_conflicts",
    "structural_evaluator_errors",
    "structural_model_errors",
    "validate_evaluator_registry",
    "validate_model_registry",
]
