from __future__ import annotations

import asyncio
import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from akc_api.arena_models import ArenaRun
from akc_api.database import Database
from akc_api.models import ModelRegistry
from akc_api.settings import Settings
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from research.model_arena_v1.__main__ import main as cli_main
from research.model_arena_v1.examples.fixture_inputs import fixture
from research.model_arena_v1.persistence import (
    ArenaImportError,
    persist_completed_bundle,
    validate_import_evidence,
)
from research.model_arena_v1.protocol import file_digest, load_json, load_jsonl


def _write_json(root: Path, relative: str, value: object) -> tuple[str, str]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    return relative, file_digest(path)


def _write_bytes(root: Path, relative: str, value: bytes) -> tuple[str, str]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return relative, file_digest(path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _materialize_measured_bundle(
    root: Path, model_registry_ids: dict[str, uuid.UUID]
) -> dict[str, Path]:
    preregistration, corpus, base_runs, layers = fixture()
    preregistration["study_id"] = "TEST_ONLY-measured-receipt-import"
    preregistration["study_kind"] = "SCREENING"
    preregistration["evidence_class"] = "MEASURED_RESEARCH"
    preregistration["public_release"]["required_repeats"] = 3
    evaluator_path, evaluator_hash = _write_json(
        root,
        "receipts/evaluator.json",
        {
            "schema": "test-only.evaluator.v1",
            "frozen": True,
            "metrics_sha256": preregistration["frozen_protocol"]["metrics_sha256"],
        },
    )
    preregistration["frozen_protocol"]["evaluator_path"] = evaluator_path
    preregistration["frozen_protocol"]["evaluator_sha256"] = evaluator_hash
    for model in preregistration["models"]:
        model["model_registry_id"] = str(model_registry_ids[model["model_id"]])
        path, sha = _write_json(
            root,
            f"receipts/models/{model['model_id']}.json",
            {
                "schema": "test-only.model.v1",
                "frozen": True,
                "model_id": model["model_id"],
                "exact_revision": model["exact_revision"],
                "model_registry_id": model["model_registry_id"],
            },
        )
        model["model_receipt_path"] = path
        model["model_receipt_sha256"] = sha
    for arm in preregistration["arms"]:
        arm["prompt_sha256"] = "sha256:" + "1" * 64
        arm["output_schema_sha256"] = "sha256:" + "2" * 64
        arm["settings_sha256"] = "sha256:" + "3" * 64
        prompt_path, prompt_hash = _write_json(
            root,
            f"receipts/arms/{arm['arm_id']}-prompt.json",
            {
                "schema": "test-only.prompt.v1",
                "frozen": True,
                "arm_id": arm["arm_id"],
                "prompt_sha256": arm["prompt_sha256"],
                "output_schema_sha256": arm["output_schema_sha256"],
                "settings_sha256": arm["settings_sha256"],
            },
        )
        arm["prompt_receipt_path"] = prompt_path
        arm["prompt_receipt_sha256"] = prompt_hash
        for prefix, body in (
            ("hardware_receipt", {"schema": "test-only.hardware.v1", "frozen": True}),
            (
                "price_snapshot",
                {"schema": "test-only.price.v1", "frozen": True, "actual_prices": True},
            ),
        ):
            path, sha = _write_json(
                root,
                f"receipts/arms/{arm['arm_id']}-{prefix}.json",
                {**body, "arm_id": arm["arm_id"]},
            )
            arm[f"{prefix}_path"] = path
            arm[f"{prefix}_sha256"] = sha
        if arm["execution_track"] == "B":
            path, sha = _write_json(
                root,
                f"receipts/arms/{arm['arm_id']}-batch.json",
                {"schema": "test-only.batch.v1", "frozen": True, "arm_id": arm["arm_id"]},
            )
            arm["batch_equivalence_receipt_path"] = path
            arm["batch_equivalence_receipt_sha256"] = sha
    case_by_id: dict[str, dict[str, Any]] = {}
    for row in corpus:
        source_path, source_hash = _write_bytes(
            root, f"sources/{row['case_id']}.bin", f"source:{row['case_id']}".encode()
        )
        license_path, license_hash = _write_bytes(
            root, f"licenses/{row['case_id']}.txt", b"test-only license evidence"
        )
        row["artifact_path"] = source_path
        row["source_sha256"] = source_hash
        row["risk_class"] = "LOW"
        row["license"]["evidence_path"] = license_path
        row["license"]["evidence_sha256"] = license_hash
        case_by_id[row["case_id"]] = row
    runs: list[dict[str, Any]] = []
    for repeat in range(1, 4):
        for template in base_runs:
            row = copy.deepcopy(template)
            row["repeat"] = repeat
            row["run_id"] = f"{template['run_id']}-repeat-{repeat}"
            case = case_by_id[row["case_id"]]
            row["input_artifact_path"] = case["artifact_path"]
            row["input_artifact_sha256"] = case["source_sha256"]
            if row["status"] == "SUCCESS":
                raw_path, raw_hash = _write_bytes(
                    root, f"outputs/{row['run_id']}.raw", f"raw:{row['run_id']}".encode()
                )
                normalized_path, normalized_hash = _write_bytes(
                    root,
                    f"outputs/{row['run_id']}.normalized",
                    f"normalized:{row['run_id']}".encode(),
                )
                row["raw_output_path"] = raw_path
                row["raw_output_sha256"] = raw_hash
                row["normalized_output_path"] = normalized_path
                row["normalized_output_sha256"] = normalized_hash
            receipt = {
                "schema": "tavonel.arena.external_completed_run_receipt.v1",
                "frozen": True,
                **{
                    name: row.get(name)
                    for name in (
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
                },
            }
            receipt_path, receipt_hash = _write_json(
                root, f"receipts/runs/{row['run_id']}.json", receipt
            )
            row["receipt_path"] = receipt_path
            row["receipt_sha256"] = receipt_hash
            runs.append(row)
    for row in layers:
        receipt_path, receipt_hash = _write_json(
            root,
            f"receipts/layers/{row['record_id']}.json",
            {
                "schema": "tavonel.arena.external_completed_layer_receipt.v1",
                "frozen": True,
                **{name: row[name] for name in ("record_id", "layer", "case_id", "arm", "metrics")},
            },
        )
        row["receipt_path"] = receipt_path
        row["receipt_sha256"] = receipt_hash
    paths = {
        "preregistration": root / "preregistration.json",
        "corpus": root / "corpus.jsonl",
        "runs": root / "runs.jsonl",
        "layers": root / "layers.jsonl",
    }
    paths["preregistration"].write_text(
        json.dumps(preregistration, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    _write_jsonl(paths["corpus"], corpus)
    _write_jsonl(paths["runs"], runs)
    _write_jsonl(paths["layers"], layers)
    return paths


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Database:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'arena-import.db').as_posix()}"
    monkeypatch.setenv("AKC_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    command.upgrade(config, "head")
    return Database(Settings(database_url=database_url))


async def _seed_models(database: Database) -> dict[str, uuid.UUID]:
    ids = {"fixture-local": uuid.uuid4(), "fixture-api": uuid.uuid4()}
    async with database.sessions() as session:
        for model_id, registry_id in ids.items():
            session.add(
                ModelRegistry(
                    id=registry_id,
                    endpoint=f"test-only-external-runner/{model_id}",
                    model_id=model_id,
                    revision="fixture-r1",
                    runtime_image_digest="sha256:" + "a" * 64,
                    adapter_version="test-only-v1",
                    policy_version="arena-import-v1",
                    benchmark_report="research/model_arena_v1/test-only",
                )
            )
        await session.commit()
    return ids


def test_measured_frozen_import_is_idempotent_and_persists_every_failure(
    tmp_path: Path, database: Database
) -> None:
    ids = asyncio.run(_seed_models(database))
    root = tmp_path / "measured"
    paths = _materialize_measured_bundle(root, ids)
    kwargs = {
        "database_url": str(database.settings.database_url),
        "preregistration_path": paths["preregistration"],
        "corpus_path": paths["corpus"],
        "runs_path": paths["runs"],
        "layers_path": paths["layers"],
        "artifact_root": root,
    }
    first = asyncio.run(persist_completed_bundle(**kwargs))
    second = asyncio.run(persist_completed_bundle(**kwargs))
    assert first == second
    assert first.run_count == 18
    assert first.failure_count == 3
    assert first.provenance_assurance == "CALLER_SUPPLIED_HASH_BOUND_BYTES"
    assert first.execution_attested is False

    async def persisted_evidence() -> tuple[int, int, dict[str, object]]:
        async with database.sessions() as session:
            total = int(await session.scalar(select(func.count(ArenaRun.id))) or 0)
            failures = int(
                await session.scalar(
                    select(func.count(ArenaRun.id)).where(ArenaRun.status == "PROVIDER_ERROR")
                )
                or 0
            )
            run = await session.scalar(select(ArenaRun).limit(1))
            assert run is not None
            return total, failures, run.output_units

    total, failures, output_units = asyncio.run(persisted_evidence())
    assert (total, failures) == (18, 3)
    assert output_units["provenance_assurance"] == "CALLER_SUPPLIED_HASH_BOUND_BYTES"
    assert output_units["execution_attested"] is False
    asyncio.run(database.dispose())


def test_import_rejects_tampered_terminal_receipt_before_database_write(
    tmp_path: Path, database: Database
) -> None:
    ids = asyncio.run(_seed_models(database))
    root = tmp_path / "tamper"
    paths = _materialize_measured_bundle(root, ids)
    runs = load_jsonl(paths["runs"])
    receipt_path = root / runs[0]["receipt_path"]
    receipt_path.write_bytes(receipt_path.read_bytes() + b"tampered")
    with pytest.raises(ArenaImportError, match="sha256 mismatch"):
        validate_import_evidence(
            load_json(paths["preregistration"]),
            load_jsonl(paths["corpus"]),
            runs,
            load_jsonl(paths["layers"]),
            root,
        )

    async def count() -> int:
        async with database.sessions() as session:
            return int(await session.scalar(select(func.count(ArenaRun.id))) or 0)

    assert asyncio.run(count()) == 0
    asyncio.run(database.dispose())


def test_import_cli_persists_then_exports_withheld_measured_bundle(
    tmp_path: Path, database: Database
) -> None:
    ids = asyncio.run(_seed_models(database))
    root = tmp_path / "cli"
    output = tmp_path / "export"
    paths = _materialize_measured_bundle(root, ids)
    arguments = [
        "import",
        "--database-url",
        str(database.settings.database_url),
        "--artifact-root",
        str(root),
        "--preregistration",
        str(paths["preregistration"]),
        "--corpus",
        str(paths["corpus"]),
        "--runs",
        str(paths["runs"]),
        "--layers",
        str(paths["layers"]),
        "--output",
        str(output),
    ]
    assert cli_main(arguments) == 3
    assert cli_main(arguments) == 3
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["evidence_class"] == "MEASURED_RESEARCH"
    assert manifest["release_state"] == "WITHHELD"
    runs = load_jsonl(paths["runs"])
    receipt_path = root / runs[0]["receipt_path"]
    receipt_path.write_bytes(receipt_path.read_bytes() + b"tampered-after-replay")
    assert cli_main(arguments) == 2
    asyncio.run(database.dispose())
