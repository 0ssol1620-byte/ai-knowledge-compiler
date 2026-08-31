"""Assemble a ``folynta.baked-runtime-qualification.v1`` receipt from evidence.

This tool exists to make it structurally impossible to fabricate or
post-hoc-tune ``smoke_expected_sha256``.  There is exactly one legitimate
source for it: ``established_expected_sha256`` read out of a sealed
``folynta.baked-runtime-smoke-baseline.v1`` receipt (see
``runtime_smoke_baseline.py``) produced by an earlier, separate pod session.
There is no command-line flag, environment variable, or literal in this
module that can inject an expected hash or force ``passed: true`` - every
gate field is a computed boolean derived from an actual comparison, and the
frozen ``BakedRuntimeQualification.from_mapping`` contract (not a
reimplementation of its logic here) is the final authority on whether the
assembled object is accepted.

Zero network access, zero GPU access, zero provider client construction -
this tool only reads local evidence files and writes a JSON receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from infra.runpod.v6.runtime_qualification import BakedRuntimeQualification
from infra.runpod.v6.runtime_smoke_baseline import canonical_smoke_prediction_bytes

_SCHEMA: Final = "folynta.baked-runtime-qualification.v1"

_BUILD_RECEIPT_REQUIRED_FIELDS: Final = (
    "source_commit",
    "source_tree_sha256",
    "dockerfile_sha256",
    "image_digest",
    "sbom_sha256",
    "vulnerability_scan_sha256",
    "critical_vulnerability_count",
    # Read too, but only for cross-verification against the lineage target -
    # never copied into the assembled object's own model_revision /
    # model_artifact_sha256 fields. See ``model_artifact_verified`` below.
    "model_revision",
    "model_artifact_sha256",
)
_RUNTIME_IDENTITY_REQUIRED_FIELDS: Final = ("gpu_type", "cuda_version", "framework_version")
_LINEAGE_TARGET_REQUIRED_FIELDS: Final = ("weights_revision", "artifact_sha256")


class QualificationRefused(RuntimeError):
    """Raised when evidence does not authorize a runtime qualification receipt.

    Every raise site names exactly which check failed so a human reading the
    exception does not have to guess which of the trust conditions broke.
    """


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise QualificationRefused(f"{label} is missing or unreadable: {path}") from exc
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise QualificationRefused(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise QualificationRefused(f"{label} must be a JSON object: {path}")
    return value


def _require_fields(value: dict[str, Any], fields: tuple[str, ...], label: str) -> None:
    # A field that is absent, or present but blank, is still missing evidence.
    blank_or_missing = [
        field
        for field in fields
        if field not in value or (isinstance(value[field], str) and not value[field].strip())
    ]
    if blank_or_missing:
        raise QualificationRefused(f"{label} is missing field(s): {sorted(set(blank_or_missing))}")


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise QualificationRefused(f"{label} is not a valid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QualificationRefused(f"{label} must be timezone-aware: {value!r}")
    return parsed


def build_qualification_receipt(
    *,
    baseline_receipt_path: Path,
    validation_run_id: str,
    validation_started_at: str,
    validation_image_digest: str,
    validation_markdown_dir: Path,
    smoke_input_path: Path,
    build_receipt_path: Path,
    runtime_identity_path: Path,
    lineage_path: Path,
    lineage_target: str,
    baked_runtime_file_sha256: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Assemble the 22-field qualification object. Does not write or validate it.

    Raises ``QualificationRefused`` if the baseline is not trustworthy or any
    required evidence source is missing. Does *not* call
    ``BakedRuntimeQualification.from_mapping`` - that authoritative check is
    the caller's final step (see ``validate_and_write``), so a rejected
    validation still has an assembled object available for a caller that
    wants to persist evidence of the failed attempt.
    """

    if not validation_run_id.strip():
        raise QualificationRefused("validation_run_id is required")
    if not validation_image_digest.strip():
        raise QualificationRefused("validation_image_digest is required")
    if not baked_runtime_file_sha256.strip():
        raise QualificationRefused("baked_runtime_file_sha256 is required")

    baseline = _load_json_object(baseline_receipt_path, "baseline receipt")  # check 1

    if baseline.get("passed") is not True:  # check 2
        raise QualificationRefused("baseline receipt refused: baseline.passed is not true")

    if baseline.get("intra_pod_determinism") is not True:  # check 3
        raise QualificationRefused(
            "baseline receipt refused: baseline.intra_pod_determinism is not true"
        )

    baseline_run_id = str(baseline.get("baseline_run_id", ""))
    if not baseline_run_id or baseline_run_id == validation_run_id:  # check 4
        raise QualificationRefused(
            "baseline receipt refused: baseline_run_id must be a genuinely different "
            f"pod session than validation_run_id (got {baseline_run_id!r} == "
            f"{validation_run_id!r})"
        )

    baseline_sealed_at = _parse_utc(str(baseline.get("sealed_at", "")), "baseline sealed_at")
    validation_started = _parse_utc(validation_started_at, "validation_started_at")
    if not baseline_sealed_at < validation_started:  # check 5
        raise QualificationRefused(
            "baseline receipt refused: baseline sealed_at "
            f"({baseline_sealed_at.isoformat()}) is not strictly before "
            f"validation_started_at ({validation_started.isoformat()}) - a baseline "
            "sealed at or after validation start cannot be trusted"
        )

    baseline_image_digest = str(baseline.get("image_digest", ""))
    if not baseline_image_digest or baseline_image_digest != validation_image_digest:  # check 6
        raise QualificationRefused(
            "baseline receipt refused: baseline image_digest "
            f"({baseline_image_digest!r}) does not match validation_image_digest "
            f"({validation_image_digest!r})"
        )

    established_expected_sha256 = baseline.get("established_expected_sha256")
    if not established_expected_sha256:
        raise QualificationRefused(
            "baseline receipt refused: no established_expected_sha256 recorded"
        )

    build_receipt = _load_json_object(build_receipt_path, "build-integrity receipt")
    _require_fields(build_receipt, _BUILD_RECEIPT_REQUIRED_FIELDS, "build-integrity receipt")
    if str(build_receipt["image_digest"]) != validation_image_digest:
        raise QualificationRefused(
            "build-integrity receipt image_digest "
            f"({build_receipt['image_digest']!r}) does not match validation_image_digest "
            f"({validation_image_digest!r})"
        )

    runtime_identity = _load_json_object(runtime_identity_path, "runtime identity file")
    _require_fields(runtime_identity, _RUNTIME_IDENTITY_REQUIRED_FIELDS, "runtime identity file")

    lineage = _load_json_object(lineage_path, "lineage file")
    targets = lineage.get("targets")
    if not isinstance(targets, dict) or lineage_target not in targets:
        raise QualificationRefused(f"lineage file has no target entry: {lineage_target!r}")
    target = targets[lineage_target]
    if not isinstance(target, dict):
        raise QualificationRefused(f"lineage target {lineage_target!r} is not an object")
    _require_fields(target, _LINEAGE_TARGET_REQUIRED_FIELDS, f"lineage target {lineage_target!r}")

    smoke_input_sha256 = _file_sha256(smoke_input_path)
    validation_bytes = canonical_smoke_prediction_bytes(validation_markdown_dir)
    smoke_prediction_sha256 = "sha256:" + hashlib.sha256(validation_bytes).hexdigest()

    identity_verified = (
        validation_image_digest == str(build_receipt["image_digest"])
        and validation_image_digest == baseline_image_digest
    )
    model_artifact_verified = (
        str(build_receipt["model_revision"]) == str(target["weights_revision"])
        and str(build_receipt["model_artifact_sha256"]) == str(target["artifact_sha256"])
    )
    smoke_passed = smoke_prediction_sha256 == established_expected_sha256
    critical_count = int(build_receipt["critical_vulnerability_count"])
    passed = identity_verified and model_artifact_verified and smoke_passed and critical_count == 0

    return {
        "schema": _SCHEMA,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "source_commit": str(build_receipt["source_commit"]),
        "source_tree_sha256": str(build_receipt["source_tree_sha256"]),
        "dockerfile_sha256": str(build_receipt["dockerfile_sha256"]),
        "image_digest": str(build_receipt["image_digest"]),
        "gpu_type": str(runtime_identity["gpu_type"]),
        "cuda_version": str(runtime_identity["cuda_version"]),
        "framework_version": str(runtime_identity["framework_version"]),
        "model_revision": str(target["weights_revision"]),
        "model_artifact_sha256": str(target["artifact_sha256"]),
        "baked_runtime_file_sha256": baked_runtime_file_sha256,
        "sbom_sha256": str(build_receipt["sbom_sha256"]),
        "vulnerability_scan_sha256": str(build_receipt["vulnerability_scan_sha256"]),
        "critical_vulnerability_count": critical_count,
        "smoke_input_sha256": smoke_input_sha256,
        "smoke_prediction_sha256": smoke_prediction_sha256,
        # The ONLY assignment of smoke_expected_sha256 anywhere in this module:
        # it is read verbatim from the sealed baseline receipt, never from a
        # CLI argument, environment variable, or literal.
        "smoke_expected_sha256": established_expected_sha256,
        "identity_verified": identity_verified,
        "model_artifact_verified": model_artifact_verified,
        "smoke_passed": smoke_passed,
        "passed": passed,
    }


def write_qualification_receipt(path: Path, receipt: dict[str, Any]) -> None:
    """Ordinary (non-exclusive) JSON write that refuses to clobber a passing receipt.

    Unlike ``write_receipt_exclusive`` for baselines, re-running a rejected
    qualification attempt against corrected evidence must be possible, so
    this uses a plain overwrite - except when the file already on disk
    recorded ``passed: true``, in which case that good evidence is never
    silently replaced.
    """

    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = None
        if isinstance(existing, dict) and existing.get("passed") is True:
            raise QualificationRefused(
                f"refusing to overwrite a passing runtime qualification receipt: {path}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(serialized, encoding="utf-8")


def validate_and_write(receipt: dict[str, Any], output_path: Path) -> BakedRuntimeQualification:
    """Run the frozen contract's own validation, then persist the receipt.

    ``BakedRuntimeQualification.from_mapping`` - not a reimplementation of its
    logic - is the final authority, including the exact
    ``smoke_prediction_sha256 == smoke_expected_sha256`` gate. The receipt is
    written whether validation passes or raises, so a rejected attempt still
    leaves evidence on disk for debugging; the rejection itself is never
    caught to force a fake ``passed: true`` result, it always propagates.
    """

    try:
        return BakedRuntimeQualification.from_mapping(receipt)
    finally:
        write_qualification_receipt(output_path, receipt)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-receipt", type=Path, required=True)
    parser.add_argument("--validation-run-id", required=True)
    parser.add_argument("--validation-started-at", required=True)
    parser.add_argument("--validation-image-digest", required=True)
    parser.add_argument("--validation-markdown-dir", type=Path, required=True)
    parser.add_argument("--smoke-input", type=Path, required=True)
    parser.add_argument("--build-receipt", type=Path, required=True)
    parser.add_argument("--runtime-identity", type=Path, required=True)
    parser.add_argument("--lineage-json", type=Path, required=True)
    parser.add_argument("--lineage-target", required=True)
    parser.add_argument("--baked-runtime-file-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt = build_qualification_receipt(
        baseline_receipt_path=args.baseline_receipt,
        validation_run_id=args.validation_run_id,
        validation_started_at=args.validation_started_at,
        validation_image_digest=args.validation_image_digest,
        validation_markdown_dir=args.validation_markdown_dir,
        smoke_input_path=args.smoke_input,
        build_receipt_path=args.build_receipt,
        runtime_identity_path=args.runtime_identity,
        lineage_path=args.lineage_json,
        lineage_target=args.lineage_target,
        baked_runtime_file_sha256=args.baked_runtime_file_sha256,
    )
    validate_and_write(receipt, args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "QualificationRefused",
    "build_qualification_receipt",
    "main",
    "validate_and_write",
    "write_qualification_receipt",
]
