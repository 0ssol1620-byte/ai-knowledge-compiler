"""Validate Arena evidence and compile a machine-readable, fail-closed bundle.

This package deliberately executes no model or provider calls.  It turns already
frozen, hash-bound observations into an auditable result.  Missing pages remain
in the denominator and prevent a public release rather than disappearing.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeGuard

SHA256 = "sha256:"
SPLITS = {"ROUTER_TRAIN", "ROUTER_CALIBRATION", "ROUTER_HOLDOUT"}
RUN_STATUSES = {
    "SUCCESS",
    "PROVIDER_ERROR",
    "TIMEOUT",
    "UNSUPPORTED",
    "INVALID_OUTPUT",
    "TRUNCATED",
    "FAILED",
}
INPUT_TRACKS = {"I", "N"}
PROMPT_TRACKS = {"STANDARD", "P"}
EXECUTION_TRACKS = {"INTERACTIVE", "B"}
LAYERS = {"A", "B", "C", "D", "E"}
DOWNSTREAM_ARMS = {"RAW_NATIVE", "SINGLE_PARSER", "TAVONEL"}


class ArenaError(ValueError):
    """Raised when an Arena input or release bundle is invalid."""


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    path: str
    message: str
    severity: str = "ERROR"

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass(slots=True)
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "ERROR" for issue in self.issues)

    def error(self, code: str, path: str, message: str) -> None:
        self.issues.append(Issue(code, path, message))

    def warning(self, code: str, path: str, message: str) -> None:
        self.issues.append(Issue(code, path, message, "WARNING"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "tavonel.arena.validation_report.v1",
            "valid": self.valid,
            "error_count": sum(i.severity == "ERROR" for i in self.issues),
            "warning_count": sum(i.severity == "WARNING" for i in self.issues),
            "issues": [issue.as_dict() for issue in self.issues],
        }


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value: object) -> str:
    return SHA256 + hashlib.sha256(canonical_bytes(value)).hexdigest()


def approval_subject_payload(manifest: Mapping[str, Any]) -> bytes:
    """Cross-runtime ASCII payload binding every exported artifact byte hash."""

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping) or not artifacts:
        raise ArenaError("approval subject requires a non-empty artifacts object")
    lines = ["tavonel.arena.approval_subject.v1\n"]
    for name in sorted(artifacts):
        artifact = artifacts[name]
        if not isinstance(name, str) or not name.replace("_", "").isalnum():
            raise ArenaError("approval artifact names must be ASCII alphanumeric/underscore")
        if not name.isascii() or not isinstance(artifact, Mapping):
            raise ArenaError("approval artifact entry is invalid")
        artifact_sha = artifact.get("sha256")
        if not _is_sha(artifact_sha):
            raise ArenaError(f"approval artifact {name} has no valid sha256")
        lines.append(f"artifact\t{name}\t{artifact_sha}\n")
    return "".join(lines).encode("ascii")


def approval_subject_digest(manifest: Mapping[str, Any]) -> str:
    """Hash the artifact-only payload an independent approval must bind."""

    return SHA256 + hashlib.sha256(approval_subject_payload(manifest)).hexdigest()


def approval_signature_payload(receipt: Mapping[str, Any]) -> bytes:
    """Cross-runtime ASCII bytes signed by an independent approver."""

    lines = ["tavonel.arena.approval_signature.v1\n"]
    for field_name in (
        "schema",
        "decision",
        "approval_subject_sha256",
        "manifest_sha256",
        "approved_at",
    ):
        value = receipt.get(field_name)
        if not isinstance(value, str) or not value.isascii() or any(c in value for c in "\r\n\t"):
            raise ArenaError(f"approval receipt {field_name} must be a single-line ASCII string")
        lines.append(f"{field_name}\t{value}\n")
    identity = receipt.get("founder_identity_ref")
    if not isinstance(identity, str) or not identity:
        raise ArenaError("approval receipt founder_identity_ref must be a non-empty string")
    identity_sha = SHA256 + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    lines.append(f"founder_identity_ref_sha256\t{identity_sha}\n")
    reviews = receipt.get("review_receipts")
    if not isinstance(reviews, Mapping) or set(reviews) != {"rights", "ip", "statistical", "claim"}:
        raise ArenaError("approval receipt must bind exactly four review receipts")
    for name in ("claim", "ip", "rights", "statistical"):
        review_sha = reviews.get(name)
        if not _is_sha(review_sha):
            raise ArenaError(f"approval receipt review {name} has no valid sha256")
        lines.append(f"review\t{name}\t{review_sha}\n")
    return "".join(lines).encode("ascii")


def file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return SHA256 + hasher.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ArenaError(f"{path} must contain a JSON object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ArenaError(f"{path}:{number} must contain a JSON object")
        rows.append(value)
    return rows


def _is_sha(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith(SHA256) or len(value) != 71:
        return False
    return all(char in "0123456789abcdef" for char in value[7:])


def _is_number(value: object) -> TypeGuard[int | float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _strict_true(value: object) -> bool:
    return type(value) is bool and value is True


def _required(
    report: ValidationReport, row: Mapping[str, Any], names: Iterable[str], path: str
) -> None:
    for name in names:
        if name not in row or row[name] in (None, "", []):
            report.error("MISSING_FIELD", f"{path}.{name}", "required field is absent")


def _require_sha(report: ValidationReport, row: Mapping[str, Any], name: str, path: str) -> None:
    if not _is_sha(row.get(name)):
        report.error("INVALID_SHA256", f"{path}.{name}", "expected sha256:<64 lowercase hex>")


def _verify_artifact(
    report: ValidationReport,
    row: Mapping[str, Any],
    path_field: str,
    hash_field: str,
    artifact_root: Path | None,
    path: str,
) -> None:
    _require_sha(report, row, hash_field, path)
    relative = row.get(path_field)
    if artifact_root is None or relative in (None, ""):
        return
    candidate = (artifact_root / str(relative)).resolve()
    try:
        candidate.relative_to(artifact_root.resolve())
    except ValueError:
        report.error("ARTIFACT_ESCAPE", f"{path}.{path_field}", "path escapes artifact root")
        return
    if not candidate.is_file():
        report.error("ARTIFACT_MISSING", f"{path}.{path_field}", str(candidate))
    elif file_digest(candidate) != row.get(hash_field):
        report.error("ARTIFACT_HASH_MISMATCH", f"{path}.{hash_field}", str(candidate))


def validate_inputs(
    preregistration: Mapping[str, Any],
    corpus: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]],
    layers: Sequence[Mapping[str, Any]],
    *,
    artifact_root: Path | None = None,
) -> ValidationReport:
    report = ValidationReport()
    _validate_preregistration(report, preregistration)
    cases = _validate_corpus(report, preregistration, corpus, artifact_root)
    _validate_runs(report, preregistration, cases, runs, artifact_root)
    _validate_layers(report, preregistration, cases, layers)
    return report


def _validate_preregistration(report: ValidationReport, prereg: Mapping[str, Any]) -> None:
    _required(
        report,
        prereg,
        (
            "schema",
            "study_id",
            "study_kind",
            "evidence_class",
            "preregistered_at",
            "evaluation_commit",
            "corpus_requirements",
            "frozen_protocol",
            "models",
            "arms",
            "public_release",
        ),
        "preregistration",
    )
    if prereg.get("schema") != "tavonel.arena.preregistration.v1":
        report.error("SCHEMA_VERSION", "preregistration.schema", "unsupported schema")
    commit = prereg.get("evaluation_commit")
    if (
        not isinstance(commit, str)
        or len(commit) != 40
        or any(c not in "0123456789abcdef" for c in commit)
    ):
        report.error("INVALID_COMMIT", "preregistration.evaluation_commit", "full git SHA required")
    if prereg.get("study_kind") not in {"FIXTURE", "SCREENING", "FINAL_ARENA"}:
        report.error("STUDY_KIND", "preregistration.study_kind", "unknown study kind")
    if prereg.get("evidence_class") not in {"SYNTHETIC_FIXTURE", "MEASURED_RESEARCH"}:
        report.error("EVIDENCE_CLASS", "preregistration.evidence_class", "unknown evidence class")
    if (
        prereg.get("study_kind") == "FINAL_ARENA"
        and prereg.get("evidence_class") != "MEASURED_RESEARCH"
    ):
        report.error(
            "SYNTHETIC_FINAL_FORBIDDEN",
            "preregistration.evidence_class",
            "renaming a synthetic fixture cannot make it final research",
        )
    release = prereg.get("public_release", {})
    repeats = release.get("required_repeats") if isinstance(release, Mapping) else None
    if type(repeats) is not int or repeats < 1:
        report.error(
            "REPEAT_COUNT",
            "preregistration.public_release.required_repeats",
            "positive integer required",
        )
    elif prereg.get("study_kind") != "FIXTURE" and repeats < 3:
        report.error(
            "PUBLIC_REPEATS",
            "preregistration.public_release.required_repeats",
            "public research requires at least three repeats",
        )
    frozen = prereg.get("frozen_protocol", {})
    if isinstance(frozen, Mapping):
        for name in (
            "renderer_sha256",
            "normalizer_sha256",
            "evaluator_sha256",
            "metrics_sha256",
            "failure_policy_sha256",
            "cost_definition_sha256",
        ):
            _require_sha(report, frozen, name, "preregistration.frozen_protocol")
        _required(
            report,
            frozen,
            ("timeout_seconds", "concurrency", "normalization_policy", "failure_policy"),
            "preregistration.frozen_protocol",
        )
    models = prereg.get("models", [])
    model_ids: set[str] = set()
    if not isinstance(models, list) or not models:
        report.error("MODELS_EMPTY", "preregistration.models", "at least one frozen model required")
    else:
        for index, model in enumerate(models):
            path = f"preregistration.models[{index}]"
            if not isinstance(model, Mapping):
                report.error("MODEL_TYPE", path, "model must be an object")
                continue
            _required(report, model, ("model_id", "exact_revision", "model_receipt_sha256"), path)
            _require_sha(report, model, "model_receipt_sha256", path)
            model_id = model.get("model_id")
            if isinstance(model_id, str):
                if model_id in model_ids:
                    report.error("DUPLICATE_MODEL", f"{path}.model_id", model_id)
                model_ids.add(model_id)
    arm_ids: set[str] = set()
    arms = prereg.get("arms", [])
    if not isinstance(arms, list) or not arms:
        report.error("ARMS_EMPTY", "preregistration.arms", "at least one frozen arm required")
        return
    for index, arm in enumerate(arms):
        path = f"preregistration.arms[{index}]"
        if not isinstance(arm, Mapping):
            report.error("ARM_TYPE", path, "arm must be an object")
            continue
        _required(
            report,
            arm,
            (
                "arm_id",
                "model_id",
                "input_track",
                "prompt_track",
                "execution_track",
                "prompt_receipt_sha256",
                "hardware_receipt_sha256",
                "price_snapshot_sha256",
            ),
            path,
        )
        for name in (
            "prompt_receipt_sha256",
            "hardware_receipt_sha256",
            "price_snapshot_sha256",
        ):
            _require_sha(report, arm, name, path)
        arm_id = arm.get("arm_id")
        if isinstance(arm_id, str):
            if arm_id in arm_ids:
                report.error("DUPLICATE_ARM", f"{path}.arm_id", arm_id)
            arm_ids.add(arm_id)
        if arm.get("model_id") not in model_ids:
            report.error("UNKNOWN_MODEL", f"{path}.model_id", str(arm.get("model_id")))
        if arm.get("input_track") not in INPUT_TRACKS:
            report.error("INPUT_TRACK", f"{path}.input_track", "must be I or N")
        if arm.get("prompt_track") not in PROMPT_TRACKS:
            report.error("PROMPT_TRACK", f"{path}.prompt_track", "must be STANDARD or P")
        if arm.get("execution_track") not in EXECUTION_TRACKS:
            report.error("EXECUTION_TRACK", f"{path}.execution_track", "must be INTERACTIVE or B")
        if arm.get("execution_track") == "B":
            _require_sha(report, arm, "batch_equivalence_receipt_sha256", path)
    if isinstance(release, Mapping):
        actual_prices = release.get("current_actual_prices")
        if type(actual_prices) is not bool:
            report.error(
                "STRICT_BOOLEAN",
                "preregistration.public_release.current_actual_prices",
                "must be JSON true or false",
            )


def _validate_corpus(
    report: ValidationReport,
    prereg: Mapping[str, Any],
    corpus: Sequence[Mapping[str, Any]],
    artifact_root: Path | None,
) -> dict[str, Mapping[str, Any]]:
    cases: dict[str, Mapping[str, Any]] = {}
    family_kinds: dict[str, set[str]] = defaultdict(set)
    family_splits: dict[str, set[str]] = defaultdict(set)
    origin_counts: Counter[str] = Counter()
    slice_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    for index, row in enumerate(corpus):
        path = f"corpus[{index}]"
        _required(
            report,
            row,
            (
                "case_id",
                "corpus_kind",
                "source_id",
                "source_uri",
                "source_sha256",
                "document_family_id",
                "origin",
                "slices",
                "split",
                "license",
            ),
            path,
        )
        case_id = row.get("case_id")
        if isinstance(case_id, str):
            if case_id in cases:
                report.error("DUPLICATE_CASE", f"{path}.case_id", case_id)
            cases[case_id] = row
        _verify_artifact(report, row, "artifact_path", "source_sha256", artifact_root, path)
        kind = row.get("corpus_kind")
        if kind not in {"ARENA", "CALIBRATION"}:
            report.error("CORPUS_KIND", f"{path}.corpus_kind", "must be ARENA or CALIBRATION")
        split = row.get("split")
        if split not in SPLITS:
            report.error("SPLIT", f"{path}.split", "unknown router split")
        family = row.get("document_family_id")
        if isinstance(family, str):
            family_kinds[family].add(str(kind))
            family_splits[family].add(str(split))
        license_info = row.get("license")
        if not isinstance(license_info, Mapping):
            report.error("LICENSE_TYPE", f"{path}.license", "license must be an object")
        else:
            _required(
                report,
                license_info,
                ("license_id", "evidence_uri", "evidence_sha256", "publication_allowed"),
                f"{path}.license",
            )
            _require_sha(report, license_info, "evidence_sha256", f"{path}.license")
            if type(license_info.get("publication_allowed")) is not bool:
                report.error(
                    "STRICT_BOOLEAN",
                    f"{path}.license.publication_allowed",
                    "must be JSON true or false",
                )
        if kind == "ARENA":
            origin_counts[str(row.get("origin"))] += 1
            slices = row.get("slices", [])
            if not isinstance(slices, list) or not slices:
                report.error(
                    "SLICES_EMPTY", f"{path}.slices", "at least one preregistered slice required"
                )
            else:
                slice_counts.update(str(value) for value in set(slices))
        kind_counts[str(kind)] += 1
    for family, kinds in family_kinds.items():
        if len(kinds) > 1:
            report.error(
                "CALIBRATION_LEAKAGE", f"family:{family}", "family occurs in calibration and Arena"
            )
    for family, splits in family_splits.items():
        if len(splits) > 1:
            report.error(
                "FAMILY_SPLIT_LEAKAGE", f"family:{family}", "one family spans router splits"
            )
    requirements = prereg.get("corpus_requirements", {})
    if isinstance(requirements, Mapping):
        expected_arena = requirements.get("arena_total")
        expected_calibration = requirements.get("calibration_total")
        if kind_counts["ARENA"] != expected_arena:
            report.error(
                "ARENA_TOTAL",
                "corpus",
                f"expected {expected_arena}, observed {kind_counts['ARENA']}",
            )
        if kind_counts["CALIBRATION"] != expected_calibration:
            report.error(
                "CALIBRATION_TOTAL",
                "corpus",
                f"expected {expected_calibration}, observed {kind_counts['CALIBRATION']}",
            )
        for origin, expected in dict(requirements.get("origin_counts", {})).items():
            if origin_counts[origin] != expected:
                report.error(
                    "ORIGIN_COUNT",
                    f"corpus.origin:{origin}",
                    f"expected {expected}, observed {origin_counts[origin]}",
                )
        for slice_name, expected in dict(requirements.get("slice_counts", {})).items():
            if slice_counts[slice_name] != expected:
                report.error(
                    "SLICE_COUNT",
                    f"corpus.slice:{slice_name}",
                    f"expected {expected}, observed {slice_counts[slice_name]}",
                )
    return cases


def _validate_runs(
    report: ValidationReport,
    prereg: Mapping[str, Any],
    cases: Mapping[str, Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]],
    artifact_root: Path | None,
) -> None:
    arena_cases = {case_id for case_id, row in cases.items() if row.get("corpus_kind") == "ARENA"}
    arms = {
        str(arm["arm_id"]): arm
        for arm in prereg.get("arms", [])
        if isinstance(arm, Mapping) and "arm_id" in arm
    }
    release = prereg.get("public_release", {})
    repeats = release.get("required_repeats", 1) if isinstance(release, Mapping) else 1
    if type(repeats) is not int or repeats < 1:
        repeats = 1
    expected = {
        (case_id, arm_id, repeat)
        for case_id in arena_cases
        for arm_id in arms
        for repeat in range(1, repeats + 1)
    }
    observed: set[tuple[str, str, int]] = set()
    for index, row in enumerate(runs):
        path = f"runs[{index}]"
        _required(
            report,
            row,
            (
                "run_id",
                "case_id",
                "arm_id",
                "repeat",
                "status",
                "input_artifact_sha256",
                "receipt_sha256",
                "latency_ms",
                "actual_cost_usd",
            ),
            path,
        )
        case_id, arm_id, repeat = row.get("case_id"), row.get("arm_id"), row.get("repeat")
        key = (
            (str(case_id), str(arm_id), repeat)
            if type(repeat) is int and 1 <= repeat <= repeats
            else None
        )
        if type(repeat) is not int or not 1 <= repeat <= repeats:
            report.error(
                "REPEAT_LABEL",
                f"{path}.repeat",
                f"must be an integer from 1 through {repeats}",
            )
        if key is not None:
            if key in observed:
                report.error("DUPLICATE_RUN", path, str(key))
            observed.add(key)
        if case_id not in arena_cases:
            report.error("UNKNOWN_ARENA_CASE", f"{path}.case_id", str(case_id))
        if arm_id not in arms:
            report.error("UNKNOWN_ARM", f"{path}.arm_id", str(arm_id))
        if row.get("status") not in RUN_STATUSES:
            report.error("RUN_STATUS", f"{path}.status", "unknown status")
        _require_sha(report, row, "input_artifact_sha256", path)
        _require_sha(report, row, "receipt_sha256", path)
        for name in ("latency_ms", "actual_cost_usd"):
            value = row.get(name)
            if not _is_number(value) or float(value) < 0:
                report.error(
                    "ATTEMPT_METRIC",
                    f"{path}.{name}",
                    "every attempt requires a non-negative measured value",
                )
        if row.get("status") == "SUCCESS":
            for name in ("raw_output_sha256", "normalized_output_sha256"):
                _require_sha(report, row, name, path)
            value = row.get("quality")
            if not _is_number(value) or float(value) < 0:
                report.error(
                    "SUCCESS_METRIC", f"{path}.quality", "non-negative measured value required"
                )
            quality = row.get("quality")
            if _is_number(quality) and float(quality) > 1:
                report.error("QUALITY_RANGE", f"{path}.quality", "must be between 0 and 1")
            _verify_artifact(
                report, row, "raw_output_path", "raw_output_sha256", artifact_root, path
            )
            _verify_artifact(
                report,
                row,
                "normalized_output_path",
                "normalized_output_sha256",
                artifact_root,
                path,
            )
        elif row.get("error_class") in (None, ""):
            report.error(
                "FAILURE_UNCLASSIFIED",
                f"{path}.error_class",
                "non-success pages require an error class",
            )
    missing = expected - observed
    extra = observed - expected
    if missing:
        report.error(
            "INCOMPLETE_ACCOUNTING",
            "runs",
            f"{len(missing)} planned case/arm/repeat receipts missing",
        )
    if extra:
        report.error(
            "UNPLANNED_RUN", "runs", f"{len(extra)} receipts are outside the preregistered matrix"
        )


def _validate_layers(
    report: ValidationReport,
    prereg: Mapping[str, Any],
    cases: Mapping[str, Mapping[str, Any]],
    layers: Sequence[Mapping[str, Any]],
) -> None:
    seen_layers: set[str] = set()
    downstream_contexts: dict[str, tuple[str, ...]] = {}
    downstream_arms: dict[str, set[str]] = defaultdict(set)
    for index, row in enumerate(layers):
        path = f"layers[{index}]"
        _required(
            report, row, ("record_id", "layer", "case_id", "arm", "metrics", "receipt_sha256"), path
        )
        layer = str(row.get("layer"))
        seen_layers.add(layer)
        if layer not in LAYERS:
            report.error("LAYER", f"{path}.layer", "must be A, B, C, D, or E")
        if row.get("case_id") not in cases:
            report.error("LAYER_CASE", f"{path}.case_id", "unknown corpus case")
        elif cases[str(row.get("case_id"))].get("corpus_kind") != "ARENA":
            report.error(
                "LAYER_CALIBRATION_LEAKAGE",
                f"{path}.case_id",
                "layer evidence must use Arena cases",
            )
        _require_sha(report, row, "receipt_sha256", path)
        metrics = row.get("metrics")
        if not isinstance(metrics, Mapping) or not metrics:
            report.error("LAYER_METRICS", f"{path}.metrics", "measured metrics required")
        elif _contains_non_finite(metrics):
            report.error("NON_FINITE_METRIC", f"{path}.metrics", "NaN and infinity are forbidden")
        if layer == "D":
            experiment_id = str(row.get("experiment_id", ""))
            _required(report, row, ("experiment_id", "fixed_context"), path)
            fixed = row.get("fixed_context", {})
            names = (
                "retriever_sha256",
                "llm_sha256",
                "prompt_sha256",
                "corpus_sha256",
                "questions_sha256",
            )
            if isinstance(fixed, Mapping):
                for name in names:
                    _require_sha(report, fixed, name, f"{path}.fixed_context")
                context = tuple(str(fixed.get(name)) for name in names)
                previous = downstream_contexts.setdefault(experiment_id, context)
                if previous != context:
                    report.error(
                        "DOWNSTREAM_CONTEXT_DRIFT",
                        path,
                        "retriever/LLM/prompt/corpus/questions changed between arms",
                    )
            arm = str(row.get("arm"))
            downstream_arms[experiment_id].add(arm)
            if arm not in DOWNSTREAM_ARMS:
                report.error(
                    "DOWNSTREAM_ARM",
                    f"{path}.arm",
                    "expected raw/native, single parser, or TAVONEL",
                )
            _required(
                report,
                metrics if isinstance(metrics, Mapping) else {},
                (
                    "answer_correctness",
                    "answer_completeness",
                    "citation_correctness",
                    "retrieval_recall",
                    "unsupported_claim_rate",
                    "tokens",
                    "latency_ms",
                    "cost_usd",
                ),
                f"{path}.metrics",
            )
        if layer == "E":
            _require_sha(report, row, "gold_sha256", path)
            _require_sha(report, row, "provenance_sha256", path)
            update = row.get("continuous_update")
            if not isinstance(update, Mapping):
                report.error(
                    "CONTINUOUS_UPDATE",
                    f"{path}.continuous_update",
                    "continuous update evidence required",
                )
            else:
                fraction = update.get("modified_fraction")
                if not _is_number(fraction) or not 0.01 <= float(fraction) <= 0.05:
                    report.error(
                        "MODIFIED_FRACTION",
                        f"{path}.continuous_update.modified_fraction",
                        "must be 0.01 through 0.05",
                    )
                _required(
                    report,
                    update,
                    (
                        "impacted_region_recall",
                        "unnecessary_recompute_ratio",
                        "stale_knowledge_rate",
                        "provenance_correctness",
                        "full_rebuild_equivalence",
                        "cost_saved",
                        "latency_saved",
                    ),
                    f"{path}.continuous_update",
                )
            _required(
                report,
                metrics if isinstance(metrics, Mapping) else {},
                (
                    "entity_precision",
                    "entity_recall",
                    "relation_precision",
                    "relation_recall",
                    "entity_resolution_precision",
                    "entity_resolution_recall",
                    "schema_coverage",
                    "provenance_coverage",
                    "graph_consistency",
                    "update_correctness",
                ),
                f"{path}.metrics",
            )
        if layer == "B":
            _required(
                report,
                metrics if isinstance(metrics, Mapping) else {},
                (
                    "content_coverage",
                    "structure_fidelity",
                    "table_fidelity",
                    "reading_order",
                    "visual_caption_retention",
                    "provenance_coverage",
                    "cross_page_continuity",
                ),
                f"{path}.metrics",
            )
        if layer == "C":
            _required(
                report,
                metrics if isinstance(metrics, Mapping) else {},
                (
                    "oracle_regret",
                    "trust_constraint_violation_rate",
                    "catastrophic_miss_rate",
                    "false_escalation_rate",
                    "missed_escalation_rate",
                    "cost_usd",
                    "latency_ms",
                ),
                f"{path}.metrics",
            )
        if layer == "A":
            _require_sha(report, row, "public_evaluator_sha256", path)
            _required(
                report,
                metrics if isinstance(metrics, Mapping) else {},
                ("quality", "coverage", "failure_rate"),
                f"{path}.metrics",
            )
    for experiment_id, arms in downstream_arms.items():
        if arms != DOWNSTREAM_ARMS:
            report.error(
                "DOWNSTREAM_ARMS_INCOMPLETE",
                f"layers.D:{experiment_id}",
                f"expected {sorted(DOWNSTREAM_ARMS)}, observed {sorted(arms)}",
            )
    required_layers = set(prereg.get("required_layers", []))
    missing_layers = required_layers - seen_layers
    if missing_layers:
        report.error(
            "LAYERS_INCOMPLETE", "layers", f"missing preregistered layers {sorted(missing_layers)}"
        )


def _contains_non_finite(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_non_finite(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_non_finite(item) for item in value)
    return type(value) is float and not math.isfinite(value)


def _quantile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _aggregate_runs(
    prereg: Mapping[str, Any],
    corpus: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    arm_ids = {
        str(arm["arm_id"])
        for arm in prereg.get("arms", [])
        if isinstance(arm, Mapping) and isinstance(arm.get("arm_id"), str)
    }
    release = prereg.get("public_release", {})
    repeat_count = release.get("required_repeats", 1) if isinstance(release, Mapping) else 1
    if type(repeat_count) is not int or repeat_count < 1:
        repeat_count = 1
    arena_case_ids = {
        str(row["case_id"])
        for row in corpus
        if row.get("corpus_kind") == "ARENA" and isinstance(row.get("case_id"), str)
    }
    planned = len(arena_case_ids) * repeat_count
    groups: dict[str, list[Mapping[str, Any]]] = {arm_id: [] for arm_id in arm_ids}
    for row in runs:
        arm_id = row.get("arm_id")
        case_id = row.get("case_id")
        repeat = row.get("repeat")
        if (
            arm_id in groups
            and case_id in arena_case_ids
            and type(repeat) is int
            and 1 <= repeat <= repeat_count
        ):
            groups[str(arm_id)].append(row)
    output: list[dict[str, Any]] = []
    for arm_id, rows in sorted(groups.items()):
        success = [row for row in rows if row.get("status") == "SUCCESS"]
        qualities = [float(row["quality"]) for row in success if _is_number(row.get("quality"))]
        costs = [
            float(row["actual_cost_usd"]) for row in rows if _is_number(row.get("actual_cost_usd"))
        ]
        latencies = [float(row["latency_ms"]) for row in rows if _is_number(row.get("latency_ms"))]
        status_counts = Counter(str(row.get("status")) for row in rows)
        missing_receipts = max(planned - len(rows), 0)
        if missing_receipts:
            status_counts["MISSING_RECEIPT"] = missing_receipts
        output.append(
            {
                "arm_id": arm_id,
                "planned_pages": planned,
                "observed_receipts": len(rows),
                "missing_receipts": missing_receipts,
                "success_pages": len(success),
                "failure_pages": planned - len(success),
                "coverage": len(success) / planned if planned else None,
                "quality_success_only": statistics.fmean(qualities) if qualities else None,
                "end_to_end_effective_score": sum(qualities) / planned if planned else None,
                "actual_cost_total_usd": sum(costs),
                "cost_per_planned_page_usd": sum(costs) / planned if planned else None,
                "cost_per_page_p50_usd": _quantile(costs, 0.50),
                "cost_per_page_p95_usd": _quantile(costs, 0.95),
                "latency_p50_ms": _quantile(latencies, 0.50),
                "latency_p95_ms": _quantile(latencies, 0.95),
                "status_counts": dict(sorted(status_counts.items())),
            }
        )
    return _mark_pareto(output)


def _mark_pareto(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        dominated_by: list[str] = []
        for other in rows:
            if other is row:
                continue
            q1, q2 = row["end_to_end_effective_score"], other["end_to_end_effective_score"]
            c1, c2 = row["cost_per_planned_page_usd"], other["cost_per_planned_page_usd"]
            l1, l2 = row["latency_p50_ms"], other["latency_p50_ms"]
            if (
                None not in (q1, q2, c1, c2, l1, l2)
                and q2 >= q1
                and c2 <= c1
                and l2 <= l1
                and (q2 > q1 or c2 < c1 or l2 < l1)
            ):
                dominated_by.append(str(other["arm_id"]))
        row["pareto_frontier"] = not dominated_by
        row["dominated_by"] = dominated_by
    return rows


def _release_reasons(
    prereg: Mapping[str, Any],
    corpus: Sequence[Mapping[str, Any]],
    report: ValidationReport,
    artifact_root: Path | None,
) -> list[str]:
    reasons = [issue.code for issue in report.issues if issue.severity == "ERROR"]
    release = prereg.get("public_release", {})
    if prereg.get("evidence_class") == "SYNTHETIC_FIXTURE":
        reasons.append("FIXTURE_NOT_PUBLIC_EVIDENCE")
    if not isinstance(release, Mapping) or not _strict_true(release.get("current_actual_prices")):
        reasons.append("CURRENT_ACTUAL_PRICES_REQUIRED")
    reviews = release.get("reviews", {}) if isinstance(release, Mapping) else {}
    for name in ("rights", "ip", "statistical", "claim"):
        review = reviews.get(name, {}) if isinstance(reviews, Mapping) else {}
        if not _release_artifact_matches(review, artifact_root):
            reasons.append(name.upper() + "_REVIEW_BYTES_REQUIRED")
    if any(
        not isinstance(row.get("license"), Mapping)
        or not _strict_true(row["license"].get("publication_allowed"))
        for row in corpus
    ):
        reasons.append("CORPUS_PUBLICATION_RIGHTS_INCOMPLETE")
    if any(
        not _release_artifact_matches(row, artifact_root, "artifact_path", "source_sha256")
        for row in corpus
    ):
        reasons.append("CORPUS_SOURCE_BYTES_REQUIRED")
    if any(
        not isinstance(row.get("license"), Mapping)
        or not _release_artifact_matches(
            row["license"], artifact_root, "evidence_path", "evidence_sha256"
        )
        for row in corpus
    ):
        reasons.append("LICENSE_EVIDENCE_BYTES_REQUIRED")
    for arm in prereg.get("arms", []):
        if not isinstance(arm, Mapping) or not _release_artifact_matches(
            arm, artifact_root, "price_snapshot_path", "price_snapshot_sha256"
        ):
            reasons.append("PRICE_SNAPSHOT_BYTES_REQUIRED")
            break
    return sorted(set(reasons))


def _release_artifact_matches(
    record: object,
    artifact_root: Path | None,
    path_field: str = "path",
    hash_field: str = "sha256",
) -> bool:
    if not isinstance(record, Mapping) or artifact_root is None:
        return False
    relative = record.get(path_field)
    expected = record.get(hash_field)
    if not isinstance(relative, str) or not _is_sha(expected):
        return False
    root = artifact_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return candidate.is_file() and file_digest(candidate) == expected


def compile_bundle(
    preregistration: Mapping[str, Any],
    corpus: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]],
    layers: Sequence[Mapping[str, Any]],
    output_dir: Path,
    *,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    report = validate_inputs(preregistration, corpus, runs, layers, artifact_root=artifact_root)
    aggregates = _aggregate_runs(preregistration, corpus, runs)
    release_reasons = _release_reasons(preregistration, corpus, report, artifact_root)
    results: dict[str, Any] = {
        "schema": "tavonel.arena.results.v1",
        "study_id": preregistration.get("study_id"),
        "study_kind": preregistration.get("study_kind"),
        "evidence_class": preregistration.get("evidence_class"),
        "headline_metric": "end_to_end_effective_score",
        "accounting_policy": (
            "all preregistered pages and repeats, including failures/timeouts/unsupported"
        ),
        "arms": aggregates,
        "layers": list(layers),
        "validation": report.as_dict(),
    }
    manifest: dict[str, Any] = {
        "schema": "tavonel.arena.public_manifest.v1",
        "study_id": preregistration.get("study_id"),
        "study_kind": preregistration.get("study_kind"),
        "evidence_class": preregistration.get("evidence_class"),
        "release_state": "ELIGIBLE_FOR_FOUNDER_RELEASE_REVIEW"
        if not release_reasons
        else "WITHHELD",
        "release_reasons": release_reasons,
        "claims_approved": False,
        "founder_release_decision_required": True,
        "publication_contract": {
            "approval_subject_sha256": None,
            "approval_subject_payload": "arena artifact hash lines v1",
            "external_approval_schema": (
                "https://tavonel.com/schemas/arena/external-approval-receipt-v1.json"
            ),
            "signature_payload": "arena approval signature lines v1",
            "rule": (
                "Publish only after independent signature verification and exact "
                "approval_subject_sha256 plus manifest_sha256 binding."
            ),
        },
        "artifacts": {
            "preregistration": {"path": "preregistration.json", "sha256": None},
            "corpus": {"path": "corpus.jsonl", "sha256": None},
            "runs": {"path": "runs.jsonl", "sha256": None},
            "layers": {"path": "layers.jsonl", "sha256": None},
            "results": {"path": "results.json", "sha256": None},
            "results_csv": {"path": "results.csv", "sha256": None},
        },
        "counts": {
            "corpus_rows": len(corpus),
            "run_receipts": len(runs),
            "layer_receipts": len(layers),
        },
        "public_summary": {
            "headline_metric": "end_to_end_effective_score",
            "arms": aggregates,
            "caveats": [
                "Success-only quality is secondary and never the headline score.",
                "Eligibility is not publication approval or a product superiority claim.",
            ],
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "preregistration.json", preregistration)
    _write_jsonl(output_dir / "corpus.jsonl", corpus)
    _write_jsonl(output_dir / "runs.jsonl", runs)
    _write_jsonl(output_dir / "layers.jsonl", layers)
    _write_json(output_dir / "results.json", results)
    _write_csv(output_dir / "results.csv", aggregates)
    artifacts: dict[str, dict[str, Any]] = manifest["artifacts"]
    for artifact in artifacts.values():
        artifact["sha256"] = file_digest(output_dir / artifact["path"])
    manifest["publication_contract"]["approval_subject_sha256"] = approval_subject_digest(manifest)
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def _write_json(path: Path, value: object) -> None:
    body = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(body, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    body = b"".join(canonical_bytes(row) + b"\n" for row in rows)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(body)
    temporary.replace(path)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    columns = (
        "arm_id",
        "planned_pages",
        "observed_receipts",
        "missing_receipts",
        "success_pages",
        "failure_pages",
        "coverage",
        "quality_success_only",
        "end_to_end_effective_score",
        "actual_cost_total_usd",
        "cost_per_planned_page_usd",
        "cost_per_page_p50_usd",
        "cost_per_page_p95_usd",
        "latency_p50_ms",
        "latency_p95_ms",
        "pareto_frontier",
        "dominated_by",
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            item = dict(row)
            item["dominated_by"] = "|".join(item.get("dominated_by", []))
            writer.writerow(item)
    temporary.replace(path)
