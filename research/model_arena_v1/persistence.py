"""Import authentic frozen external receipts into the Arena persistence boundary.

This module never invokes a model. It accepts only a completed, measured bundle
whose referenced receipt and artifact bytes are locally present and hash-bound.
"""

from __future__ import annotations

import hashlib
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_API_SOURCE = _REPOSITORY_ROOT / "services" / "api" / "src"
if str(_API_SOURCE) not in sys.path:
    sys.path.insert(0, str(_API_SOURCE))

from akc_api.arena_models import ArenaRun  # noqa: E402
from akc_api.arena_repository import (  # noqa: E402
    ArenaCaseSpec,
    ArenaRunOutcome,
    ArenaRunSpec,
    ArenaScoreSpec,
    add_case,
    complete_run,
    create_campaign,
    finish_campaign,
    freeze_campaign,
    record_score,
    start_campaign,
    start_run,
)
from akc_api.database import Database  # noqa: E402
from akc_api.settings import Settings  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402
from jsonschema.exceptions import ValidationError  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from .protocol import (  # noqa: E402
    ArenaError,
    canonical_bytes,
    file_digest,
    load_json,
    load_jsonl,
    validate_inputs,
)

_IDENTITY_NAMESPACE = uuid.UUID("eff33991-58c4-51af-8b95-f5bb6d05621e")
_SCHEMA_ROOT = Path(__file__).with_name("schemas")
_PROVENANCE_ASSURANCE = "CALLER_SUPPLIED_HASH_BOUND_BYTES"
_DATABASE_ORIGINS = {
    "OLMOCR",
    "OMNIDOC",
    "PARSEBENCH",
    "DART",
    "SEC",
    "FAILURE_ZOO",
    "CLEAN_CONTROL",
    "OTHER_PUBLIC",
}


class ArenaImportError(ArenaError):
    """A measured external bundle cannot cross the persistence boundary."""


@dataclass(frozen=True, slots=True)
class ImportSummary:
    campaign_id: str
    case_count: int
    run_count: int
    success_count: int
    failure_count: int
    replay_safe: bool
    provenance_assurance: str = _PROVENANCE_ASSURANCE
    execution_attested: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.arena.persistence_import.v1",
            "campaign_id": self.campaign_id,
            "case_count": self.case_count,
            "run_count": self.run_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "replay_safe": self.replay_safe,
            "provenance_assurance": self.provenance_assurance,
            "execution_attested": self.execution_attested,
        }


def _bare(value: str) -> str:
    if not value.startswith("sha256:") or len(value) != 71:
        raise ArenaImportError("expected sha256:<64 lowercase hex>")
    return value[7:]


def _database_origin(value: object) -> str:
    origin = str(value)
    if origin in _DATABASE_ORIGINS:
        return origin
    # The frozen corpus manifest retains the precise upstream origin. The DB
    # deliberately has a smaller reporting taxonomy for other public sources.
    return "OTHER_PUBLIC"


def _bound_path(root: Path, relative: object, expected: object, context: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ArenaImportError(f"{context} path is required")
    if not isinstance(expected, str):
        raise ArenaImportError(f"{context} sha256 is required")
    root = root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ArenaImportError(f"{context} path escapes artifact root") from error
    if not path.is_file():
        raise ArenaImportError(f"{context} bytes are missing: {relative}")
    if file_digest(path) != expected:
        raise ArenaImportError(f"{context} sha256 mismatch: {relative}")
    return path


def _frozen_receipt(
    root: Path, record: Mapping[str, Any], prefix: str, context: str
) -> dict[str, Any]:
    path = _bound_path(root, record.get(f"{prefix}_path"), record.get(f"{prefix}_sha256"), context)
    document = load_json(path)
    if document.get("frozen") is not True:
        raise ArenaImportError(f"{context} must contain frozen=true")
    return document


def _match_receipt(
    document: Mapping[str, Any], expected: Mapping[str, object], context: str
) -> None:
    for field_name, value in expected.items():
        if document.get(field_name) != value:
            raise ArenaImportError(f"{context} identity mismatch at {field_name}")


def _validate_receipt_schema(document: Mapping[str, Any], name: str, context: str) -> None:
    schema = load_json(_SCHEMA_ROOT / name)
    try:
        Draft202012Validator(schema).validate(document)
    except ValidationError as error:
        location = ".".join(str(item) for item in error.absolute_path) or "<root>"
        raise ArenaImportError(
            f"{context} schema violation at {location}: {error.message}"
        ) from error


def _validate_external_run_receipt(root: Path, row: Mapping[str, Any]) -> None:
    path = _bound_path(root, row.get("receipt_path"), row.get("receipt_sha256"), "run receipt")
    receipt = load_json(path)
    _validate_receipt_schema(receipt, "external_completed_run_receipt.schema.json", "run receipt")
    fields = (
        "run_id",
        "case_id",
        "arm_id",
        "repeat",
        "status",
        "input_artifact_sha256",
        "raw_output_sha256",
        "normalized_output_sha256",
        "latency_ms",
        "actual_cost_usd",
        "error_class",
    )
    for field_name in fields:
        if receipt.get(field_name) != row.get(field_name):
            raise ArenaImportError(f"run receipt identity/outcome mismatch at {field_name}")


def _validate_external_layer_receipt(root: Path, row: Mapping[str, Any]) -> None:
    path = _bound_path(root, row.get("receipt_path"), row.get("receipt_sha256"), "layer receipt")
    receipt = load_json(path)
    _validate_receipt_schema(
        receipt, "external_completed_layer_receipt.schema.json", "layer receipt"
    )
    for field_name in ("record_id", "layer", "case_id", "arm", "metrics"):
        if receipt.get(field_name) != row.get(field_name):
            raise ArenaImportError(f"layer receipt identity/outcome mismatch at {field_name}")


def validate_import_evidence(
    preregistration: Mapping[str, Any],
    corpus: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]],
    layers: Sequence[Mapping[str, Any]],
    artifact_root: Path,
) -> None:
    """Require measured provenance and every externally frozen byte before DB writes."""

    report = validate_inputs(preregistration, corpus, runs, layers, artifact_root=artifact_root)
    if not report.valid:
        codes = sorted(issue.code for issue in report.issues if issue.severity == "ERROR")
        raise ArenaImportError(f"protocol validation failed: {codes}")
    if preregistration.get("evidence_class") != "MEASURED_RESEARCH":
        raise ArenaImportError("only MEASURED_RESEARCH may enter Arena persistence")
    frozen = preregistration.get("frozen_protocol")
    if not isinstance(frozen, Mapping):
        raise ArenaImportError("frozen_protocol is required")
    evaluator = _frozen_receipt(artifact_root, frozen, "evaluator", "evaluator receipt")
    _match_receipt(
        evaluator,
        {"metrics_sha256": frozen.get("metrics_sha256")},
        "evaluator receipt",
    )
    for index, model in enumerate(preregistration.get("models", [])):
        if not isinstance(model, Mapping):
            raise ArenaImportError(f"model {index} is invalid")
        model_receipt = _frozen_receipt(
            artifact_root, model, "model_receipt", f"model {index} receipt"
        )
        try:
            uuid.UUID(str(model.get("model_registry_id")))
        except ValueError as error:
            raise ArenaImportError(f"model {index} has no valid model_registry_id") from error
        _match_receipt(
            model_receipt,
            {
                "model_id": model.get("model_id"),
                "exact_revision": model.get("exact_revision"),
                "model_registry_id": model.get("model_registry_id"),
            },
            f"model {index} receipt",
        )
    for index, arm in enumerate(preregistration.get("arms", [])):
        if not isinstance(arm, Mapping):
            raise ArenaImportError(f"arm {index} is invalid")
        for field_name in ("prompt_sha256", "output_schema_sha256", "settings_sha256"):
            _bare(str(arm.get(field_name)))
        prompt_receipt = _frozen_receipt(
            artifact_root, arm, "prompt_receipt", f"arm {index} prompt receipt"
        )
        _match_receipt(
            prompt_receipt,
            {
                "arm_id": arm.get("arm_id"),
                "prompt_sha256": arm.get("prompt_sha256"),
                "output_schema_sha256": arm.get("output_schema_sha256"),
                "settings_sha256": arm.get("settings_sha256"),
            },
            f"arm {index} prompt receipt",
        )
        hardware_receipt = _frozen_receipt(
            artifact_root, arm, "hardware_receipt", f"arm {index} hardware receipt"
        )
        _match_receipt(
            hardware_receipt, {"arm_id": arm.get("arm_id")}, f"arm {index} hardware receipt"
        )
        price_receipt = _frozen_receipt(
            artifact_root, arm, "price_snapshot", f"arm {index} price snapshot"
        )
        _match_receipt(
            price_receipt,
            {"arm_id": arm.get("arm_id"), "actual_prices": True},
            f"arm {index} price snapshot",
        )
        if arm.get("execution_track") == "B":
            batch_receipt = _frozen_receipt(
                artifact_root, arm, "batch_equivalence_receipt", f"arm {index} batch equivalence"
            )
            _match_receipt(
                batch_receipt,
                {"arm_id": arm.get("arm_id")},
                f"arm {index} batch equivalence",
            )
    for index, row in enumerate(corpus):
        _bound_path(
            artifact_root,
            row.get("artifact_path"),
            row.get("source_sha256"),
            f"case {index} source",
        )
        license_record = row.get("license")
        if not isinstance(license_record, Mapping):
            raise ArenaImportError(f"case {index} license is invalid")
        _bound_path(
            artifact_root,
            license_record.get("evidence_path"),
            license_record.get("evidence_sha256"),
            f"case {index} license",
        )
        if row.get("risk_class") not in {"LOW", "MEDIUM", "HIGH"}:
            raise ArenaImportError(f"case {index} risk_class is required")
    for row in runs:
        _bound_path(
            artifact_root,
            row.get("input_artifact_path"),
            row.get("input_artifact_sha256"),
            "run input",
        )
        _validate_external_run_receipt(artifact_root, row)
        if row.get("status") == "SUCCESS":
            _bound_path(
                artifact_root,
                row.get("raw_output_path"),
                row.get("raw_output_sha256"),
                "raw output",
            )
            _bound_path(
                artifact_root,
                row.get("normalized_output_path"),
                row.get("normalized_output_sha256"),
                "normalized output",
            )
    for row in layers:
        _validate_external_layer_receipt(artifact_root, row)


def _uuid(parent: uuid.UUID, value: str) -> uuid.UUID:
    return uuid.uuid5(parent, value)


def _db_status(
    status: str,
) -> Literal["SUCCESS", "PROVIDER_ERROR", "TRUNCATED", "INVALID_OUTPUT", "CANCELLED"]:
    if status == "SUCCESS":
        return "SUCCESS"
    if status == "TRUNCATED":
        return "TRUNCATED"
    if status == "INVALID_OUTPUT":
        return "INVALID_OUTPUT"
    if status == "CANCELLED":
        return "CANCELLED"
    return "PROVIDER_ERROR"


def _split(
    row: Mapping[str, Any],
) -> Literal["CALIBRATION", "EVAL", "ROUTER_TRAIN", "ROUTER_HOLDOUT"]:
    if row.get("corpus_kind") == "CALIBRATION":
        return "CALIBRATION"
    split = row.get("split")
    if split == "ROUTER_TRAIN":
        return "ROUTER_TRAIN"
    if split == "ROUTER_HOLDOUT":
        return "ROUTER_HOLDOUT"
    return "EVAL"


def _risk_class(value: object) -> Literal["LOW", "MEDIUM", "HIGH"]:
    if value == "LOW":
        return "LOW"
    if value == "MEDIUM":
        return "MEDIUM"
    if value == "HIGH":
        return "HIGH"
    raise ArenaImportError("case risk_class must be LOW, MEDIUM, or HIGH")


async def persist_completed_bundle(
    *,
    database_url: str,
    preregistration_path: Path,
    corpus_path: Path,
    runs_path: Path,
    layers_path: Path,
    artifact_root: Path,
) -> ImportSummary:
    """Persist a completed external bundle and verify its DB round trip."""

    preregistration = load_json(preregistration_path)
    corpus = load_jsonl(corpus_path)
    runs = load_jsonl(runs_path)
    layers = load_jsonl(layers_path)
    validate_import_evidence(preregistration, corpus, runs, layers, artifact_root)
    prereg_sha = file_digest(preregistration_path)
    corpus_sha = file_digest(corpus_path)
    campaign_id = uuid.uuid5(_IDENTITY_NAMESPACE, f"{preregistration['study_id']}:{prereg_sha}")
    model_by_id = {
        str(model["model_id"]): model
        for model in preregistration["models"]
        if isinstance(model, Mapping)
    }
    arm_by_id = {
        str(arm["arm_id"]): arm for arm in preregistration["arms"] if isinstance(arm, Mapping)
    }
    case_ids = {str(row["case_id"]): _uuid(campaign_id, str(row["case_id"])) for row in corpus}
    import_receipt = hashlib.sha256(
        canonical_bytes(
            {
                "preregistration": prereg_sha,
                "corpus": corpus_sha,
                "runs": file_digest(runs_path),
                "layers": file_digest(layers_path),
            }
        )
    ).hexdigest()
    database = Database(Settings(database_url=database_url))
    try:
        async with database.sessions() as session:
            campaign = await create_campaign(
                session,
                campaign_id=campaign_id,
                name=str(preregistration["study_id"]),
                corpus_manifest_sha256=_bare(corpus_sha),
                protocol_version="model_arena_v1",
                protocol_sha256=_bare(prereg_sha),
            )
            for row in corpus:
                license_record = row["license"]
                assert isinstance(license_record, Mapping)
                await add_case(
                    session,
                    ArenaCaseSpec(
                        id=case_ids[str(row["case_id"])],
                        campaign_id=campaign_id,
                        document_family_id=str(row["document_family_id"]),
                        page_or_document_id=str(row["case_id"]),
                        split=_split(row),
                        origin=_database_origin(row["origin"]),
                        slice_labels=tuple(str(item) for item in row["slices"]),
                        risk_class=_risk_class(row["risk_class"]),
                        source_artifact_ref=str(row["artifact_path"]),
                        source_artifact_sha256=_bare(str(row["source_sha256"])),
                        truth_ref=(None if row.get("truth_ref") is None else str(row["truth_ref"])),
                        license_ref=str(license_record["evidence_path"]),
                    ),
                )
            if campaign.status == "DRAFT":
                campaign = await freeze_campaign(
                    session,
                    campaign_id=campaign_id,
                    expected_manifest_sha256=_bare(corpus_sha),
                    transition_receipt_sha256=import_receipt,
                )
            if campaign.status == "FROZEN":
                campaign = await start_campaign(
                    session,
                    campaign_id=campaign_id,
                    transition_receipt_sha256=import_receipt,
                )
            for row in runs:
                arm = arm_by_id[str(row["arm_id"])]
                model = model_by_id[str(arm["model_id"])]
                run_id = _uuid(campaign_id, str(row["run_id"]))
                run = await start_run(
                    session,
                    ArenaRunSpec(
                        id=run_id,
                        campaign_id=campaign_id,
                        case_id=case_ids[str(row["case_id"])],
                        model_registry_id=uuid.UUID(str(model["model_registry_id"])),
                        idempotency_key=str(row["run_id"]),
                        exact_model_id=str(model["model_id"]),
                        exact_model_revision=str(model["exact_revision"]),
                        input_track=(
                            "STANDARD_IMAGE" if arm["input_track"] == "I" else "NATIVE_PROVIDER"
                        ),
                        prompt_track=(
                            "STANDARD"
                            if arm["prompt_track"] == "STANDARD"
                            else "PROVIDER_OPTIMIZED"
                        ),
                        batch_mode=arm["execution_track"] == "B",
                        prompt_sha256=_bare(str(arm["prompt_sha256"])),
                        schema_sha256=_bare(str(arm["output_schema_sha256"])),
                        settings_sha256=_bare(str(arm["settings_sha256"])),
                        input_artifact_ref=str(row["input_artifact_path"]),
                        input_artifact_sha256=_bare(str(row["input_artifact_sha256"])),
                        price_snapshot_ref=str(arm["price_snapshot_path"]),
                        price_snapshot_sha256=_bare(str(arm["price_snapshot_sha256"])),
                    ),
                )
                source_status = str(row["status"])
                await complete_run(
                    session,
                    run_id=run.id,
                    outcome=ArenaRunOutcome(
                        status=_db_status(source_status),
                        latency_ms=int(row["latency_ms"]),
                        input_units=dict(row.get("input_units", {})),
                        output_units={
                            "external_status": source_status,
                            "measured": dict(row.get("output_units", {})),
                            "provenance_assurance": _PROVENANCE_ASSURANCE,
                            "execution_attested": False,
                        },
                        actual_cost_usd=Decimal(str(row["actual_cost_usd"])),
                        terminal_receipt_sha256=_bare(str(row["receipt_sha256"])),
                        raw_output_artifact_ref=row.get("raw_output_path"),
                        raw_output_sha256=(
                            None
                            if row.get("raw_output_sha256") is None
                            else _bare(str(row["raw_output_sha256"]))
                        ),
                        normalized_output_artifact_ref=row.get("normalized_output_path"),
                        normalized_output_sha256=(
                            None
                            if row.get("normalized_output_sha256") is None
                            else _bare(str(row["normalized_output_sha256"]))
                        ),
                        error_code=(
                            None
                            if source_status == "SUCCESS"
                            else f"{source_status}:{row.get('error_class')}"[:120]
                        ),
                    ),
                )
                if source_status == "SUCCESS":
                    frozen = preregistration["frozen_protocol"]
                    assert isinstance(frozen, Mapping)
                    await record_score(
                        session,
                        run_id=run.id,
                        score=ArenaScoreSpec(
                            evaluator_id="arena-v1-quality",
                            evaluator_revision=_bare(str(frozen["evaluator_sha256"])),
                            metric_name="quality",
                            value=float(row["quality"]),
                            evaluator_artifact_ref=str(frozen["evaluator_path"]),
                            evaluator_artifact_sha256=_bare(str(frozen["evaluator_sha256"])),
                            receipt_ref=str(row["receipt_path"]),
                            receipt_sha256=_bare(str(row["receipt_sha256"])),
                        ),
                    )
            campaign = await finish_campaign(
                session,
                campaign_id=campaign_id,
                status="FINALIZED",
                terminal_receipt_sha256=import_receipt,
            )
            persisted_count = int(
                await session.scalar(
                    select(func.count(ArenaRun.id)).where(ArenaRun.campaign_id == campaign_id)
                )
                or 0
            )
            if persisted_count != len(runs):
                raise ArenaImportError(
                    f"database round trip count mismatch: {persisted_count} != {len(runs)}"
                )
            await session.commit()
        return ImportSummary(
            campaign_id=str(campaign_id),
            case_count=len(corpus),
            run_count=len(runs),
            success_count=sum(row["status"] == "SUCCESS" for row in runs),
            failure_count=sum(row["status"] != "SUCCESS" for row in runs),
            replay_safe=True,
        )
    finally:
        await database.dispose()
