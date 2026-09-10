from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from . import preflight_mixed_holdout
from .preflight_mixed_holdout import digest, evaluate_preopen

CLASSES = (
    "native_structured",
    "born_digital_pdf_table",
    "scanned_pdf",
    "layout_heavy_pdf",
    "office_korean_docx",
    "office_korean_pptx",
    "office_korean_xlsx",
    "target_alignment_failure",
)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def valid_world(tmp_path: Path) -> dict[str, Path]:
    protocol = {
        "schema": "tavonel.router_mixed_source_holdout_protocol.v1",
        "state": "FROZEN_SELECTION_PROTOCOL",
        "benchmark_id": "TEST-HOLDOUT-V1",
        "frozen_before_acquisition": True,
        "required_classes": list(CLASSES),
        "model_keys": ["mineru_vlm", "paddleocr_vl_1_6", "ovisocr2"],
        "source_selection": {
            "selected_units_per_class": 2,
            "minimum_units_per_class": 2,
            "maximum_units_per_class": 2,
            "maximum_total_units": 16,
        },
    }
    protocol_path = tmp_path / "protocol.json"
    write_json(protocol_path, protocol)
    rows = []
    source_root = tmp_path / "sources"
    source_root.mkdir(exist_ok=True)
    for class_index, source_class in enumerate(CLASSES):
        for item_index in range(2):
            unit = f"{class_index}-{item_index}"
            source_bytes = unit.encode()
            (source_root / f"{unit}.source").write_bytes(source_bytes)
            rows.append(
                {
                    "unit_id": unit,
                    "source_class": source_class,
                    "source_sha256": "sha256:" + hashlib.sha256(unit.encode()).hexdigest(),
                    "source_size_bytes": len(source_bytes),
                    "media_type": "application/octet-stream",
                    "source_family_id": f"official-{class_index}-{item_index}",
                    "source_url": (
                        f"https://official-{class_index}.example.invalid/{item_index}"
                    ),
                    "selection_url_sha256": digest(
                        f"https://official-{class_index}.example.invalid/{item_index}".encode()
                    ),
                    "rights_status": "public_research_allowed",
                    "rights_evidence_url": "https://rights.example.invalid/research",
                    "rights_checked_at_utc": "2026-09-10T00:00:00Z",
                    "allowed_use_scope": "local_research_evaluation_no_redistribution",
                    "language": "ko" if "korean" in source_class else "en",
                    "publisher": f"Publisher {class_index}",
                    "acquired_at_utc": "2026-09-10T00:00:00Z",
                    "target_locator_kind": "source_native_or_bbox1000",
                    "target_locator": f"unit:{unit}",
                    "truth_state": "SEALED_UNOPENED",
                }
            )
    class_order = {source_class: index for index, source_class in enumerate(CLASSES)}
    rows.sort(key=lambda row: (class_order[row["source_class"]], row["selection_url_sha256"]))
    manifest_path = tmp_path / "manifest.jsonl"
    manifest_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    candidate_inventory_path = tmp_path / "candidate-inventory.json"
    write_json(candidate_inventory_path, {"schema": "test.candidate_inventory.v1"})
    development_path = tmp_path / "development.json"
    write_json(
        development_path,
        {
            "schema": "tavonel.router_development_inventory.v1",
            "source_sha256": [],
            "source_family_ids": [],
        },
    )
    (tmp_path / "policy.json").write_bytes(b"policy")
    router_policy_sha256 = digest((tmp_path / "policy.json").read_bytes())
    predictions_path = tmp_path / "predictions.jsonl"
    predictions_path.write_text(
        "".join(
            json.dumps(
                {
                    "unit_id": row["unit_id"],
                    "source_sha256": row["source_sha256"],
                    "router_policy_sha256": router_policy_sha256,
                    "route_plan": {"first": "native_only"},
                }
            )
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    model = {
        "model_revision": "a" * 40,
        "runtime_sha256": "sha256:" + "b" * 64,
        "bundle_sha256": "sha256:" + "c" * 64,
        "inference_config_sha256": "sha256:" + "d" * 64,
    }
    runtime_file = tmp_path / "packages/router/src/runtime.py"
    runtime_file.parent.mkdir(parents=True, exist_ok=True)
    runtime_file.write_bytes(b"runtime")
    native_path = tmp_path / "native.json"
    write_json(
        native_path,
        {
            "schema": "tavonel.router_native_runtime_binding.v1",
            "files": [
                {
                    "path": "packages/router/src/runtime.py",
                    "sha256": digest(runtime_file.read_bytes()),
                }
            ],
        },
    )
    artifacts = {
        "freeze_generator": ("freeze.py", b"freeze"),
        "source_contract": ("contract.json", b"contract"),
        "router_policy": ("policy.json", b"policy"),
        "evaluator": ("evaluator.json", b"evaluator"),
        "statistics": ("statistics.json", b"statistics"),
    }
    for _, (name, content) in artifacts.items():
        (tmp_path / name).write_bytes(content)
    identity_path = tmp_path / "model-identity.json"
    write_json(
        identity_path,
        {
            "schema": "tavonel.router_model_identity_source.v1",
            "models": {key: model for key in protocol["model_keys"]},
        },
    )
    snapshot_path = tmp_path / "model-snapshot.json"
    write_json(
        snapshot_path,
        {
            "schema": "tavonel.router_model_snapshot_binding.v1",
            "models": {
                key: {"revision": model["model_revision"]}
                for key in protocol["model_keys"]
            },
        },
    )
    binding = {
        "schema": "tavonel.router_mixed_source_holdout_binding.v1",
        "state": "FROZEN_PREOPEN",
        "benchmark_id": protocol["benchmark_id"],
        "protocol_sha256": digest(protocol_path.read_bytes()),
        "source_manifest_sha256": digest(manifest_path.read_bytes()),
        "candidate_inventory_sha256": digest(candidate_inventory_path.read_bytes()),
        "development_inventory_sha256": digest(development_path.read_bytes()),
        "prediction_manifest_sha256": digest(predictions_path.read_bytes()),
        "preflight_sha256": digest(Path(preflight_mixed_holdout.__file__).read_bytes()),
        "models": {key: model for key in protocol["model_keys"]},
        "allowed_source_hosts": [f"official-{index}.example.invalid" for index in range(8)],
        "freeze_generator_sha256": digest((tmp_path / "freeze.py").read_bytes()),
        "native_runtime_sha256": digest(native_path.read_bytes()),
        "source_contract_sha256": digest((tmp_path / "contract.json").read_bytes()),
        "router_policy_sha256": digest((tmp_path / "policy.json").read_bytes()),
        "evaluator_sha256": digest((tmp_path / "evaluator.json").read_bytes()),
        "statistics_sha256": digest((tmp_path / "statistics.json").read_bytes()),
        "model_identity_source_sha256": digest(identity_path.read_bytes()),
        "model_snapshot_binding_sha256": digest(snapshot_path.read_bytes()),
        "artifact_paths": {
            "freeze_generator": "freeze.py",
            "native_runtime": "native.json",
            "source_contract": "contract.json",
            "router_policy": "policy.json",
            "evaluator": "evaluator.json",
            "statistics": "statistics.json",
            "model_identity_source": "model-identity.json",
            "model_snapshot_binding": "model-snapshot.json",
        },
        "predictions_frozen": True,
        "input_manifest_contains_truth": False,
    }
    binding_path = tmp_path / "binding.json"
    write_json(binding_path, binding)
    truth_root = tmp_path / "truth"
    return {
        "protocol_path": protocol_path,
        "binding_path": binding_path,
        "manifest_path": manifest_path,
        "development_hashes_path": development_path,
        "candidate_inventory_path": candidate_inventory_path,
        "predictions_path": predictions_path,
        "truth_root": truth_root,
        "source_root": source_root,
        "repo_root": tmp_path,
    }


def evaluate(world: dict[str, Path]):
    return evaluate_preopen(**world)


def rewrite_binding(world: dict[str, Path], mutate) -> None:
    path = world["binding_path"]
    binding = json.loads(path.read_text(encoding="utf-8"))
    mutate(binding)
    write_json(path, binding)


def rewrite_manifest(world: dict[str, Path], mutate) -> None:
    path = world["manifest_path"]
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    mutate(rows)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    rewrite_binding(
        world,
        lambda value: value.update(source_manifest_sha256=digest(path.read_bytes())),
    )


def rewrite_development_inventory(world: dict[str, Path], mutate) -> None:
    path = world["development_hashes_path"]
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    write_json(path, value)
    rewrite_binding(
        world,
        lambda binding: binding.update(development_inventory_sha256=digest(path.read_bytes())),
    )


def rewrite_predictions(world: dict[str, Path], mutate) -> None:
    path = world["predictions_path"]
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    mutate(rows)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    rewrite_binding(
        world,
        lambda binding: binding.update(prediction_manifest_sha256=digest(path.read_bytes())),
    )


def test_complete_preopen_world_passes_without_opening_truth(tmp_path: Path) -> None:
    result = evaluate(valid_world(tmp_path))
    assert result.passed
    assert result.units == 16
    assert set(result.class_counts) == set(CLASSES)
    assert result.as_dict()["holdout_opened"] is False
    assert result.as_dict()["model_calls"] == 0


@pytest.mark.parametrize(
    ("mutation", "blocker"),
    [
        (lambda row: row.update(truth_state="OPENED"), "ROW_0000_TRUTH_STATE_INVALID"),
        (
            lambda row: row.update(source_url="http://official-0.example.invalid/file"),
            "ROW_0000_HTTPS_SOURCE_REQUIRED",
        ),
        (
            lambda row: row.update(source_url="https://unbound.example.invalid/file"),
            "ROW_0000_SOURCE_HOST_NOT_BOUND",
        ),
        (lambda row: row.update(rights_status="unknown"), "ROW_0000_RIGHTS_UNQUALIFIED"),
    ],
)
def test_unqualified_source_row_blocks_the_holdout(tmp_path: Path, mutation, blocker: str) -> None:
    world = valid_world(tmp_path)
    rewrite_manifest(world, lambda rows: mutation(rows[0]))
    result = evaluate(world)
    assert not result.passed and blocker in result.blockers


def test_development_overlap_is_rejected(tmp_path: Path) -> None:
    world = valid_world(tmp_path)
    first = json.loads(world["manifest_path"].read_text(encoding="utf-8").splitlines()[0])
    rewrite_development_inventory(
        world,
        lambda value: value["source_sha256"].append(first["source_sha256"]),
    )
    assert "ROW_0000_DEVELOPMENT_SOURCE_OVERLAP" in evaluate(world).blockers


def test_missing_class_never_shrinks_the_denominator_silently(tmp_path: Path) -> None:
    world = valid_world(tmp_path)
    rewrite_manifest(world, lambda rows: rows.__setitem__(slice(0, 2), []))
    result = evaluate(world)
    assert not result.passed
    assert "CLASS_native_structured_BELOW_MINIMUM" in result.blockers
    assert "CLASS_native_structured_NOT_EXACT" in result.blockers
    assert "TOTAL_SIZE_NOT_MET" in result.blockers


def test_truth_bytes_present_block_preopen(tmp_path: Path) -> None:
    world = valid_world(tmp_path)
    world["truth_root"].mkdir()
    (world["truth_root"] / "annotations.jsonl").write_text("{}\n", encoding="utf-8")
    assert "HOLDOUT_TRUTH_ALREADY_PRESENT" in evaluate(world).blockers


def test_changed_protocol_or_predictions_block_execution(tmp_path: Path) -> None:
    world = valid_world(tmp_path)
    protocol = json.loads(world["protocol_path"].read_text(encoding="utf-8"))
    protocol["purpose"] = "changed after binding"
    write_json(world["protocol_path"], protocol)
    rewrite_binding(world, lambda value: value.update(predictions_frozen=False))
    blockers = evaluate(world).blockers
    assert "PROTOCOL_DIGEST_MISMATCH" in blockers
    assert "ROUTE_PREDICTIONS_NOT_FROZEN" in blockers


def test_model_identity_must_be_exact_and_complete(tmp_path: Path) -> None:
    world = valid_world(tmp_path)
    rewrite_binding(
        world,
        lambda value: value["models"]["ovisocr2"].update(runtime_sha256="latest"),
    )
    assert "MODEL_ovisocr2_RUNTIME_SHA256_INVALID" in evaluate(world).blockers


def test_development_inventory_must_match_frozen_digest(tmp_path: Path) -> None:
    world = valid_world(tmp_path)
    value = json.loads(world["development_hashes_path"].read_text(encoding="utf-8"))
    value["source_family_ids"].append("late-mutation")
    write_json(world["development_hashes_path"], value)
    assert "DEVELOPMENT_INVENTORY_DIGEST_MISMATCH" in evaluate(world).blockers


def test_manifest_rejects_truth_or_unregistered_fields(tmp_path: Path) -> None:
    world = valid_world(tmp_path)
    rewrite_manifest(world, lambda rows: rows[0].update(expected_answer="secret"))
    assert "ROW_0000_UNEXPECTED_FIELDS" in evaluate(world).blockers


def test_selection_order_and_url_digest_are_enforced(tmp_path: Path) -> None:
    world = valid_world(tmp_path)
    rewrite_manifest(world, lambda rows: rows.__setitem__(slice(0, 2), reversed(rows[:2])))
    assert "SOURCE_SELECTION_ORDER_INVALID" in evaluate(world).blockers
    world = valid_world(tmp_path)
    rewrite_manifest(world, lambda rows: rows[0].update(selection_url_sha256="sha256:" + "0" * 64))
    assert "ROW_0000_SELECTION_URL_DIGEST_MISMATCH" in evaluate(world).blockers


def test_prediction_bytes_and_denominator_are_bound(tmp_path: Path) -> None:
    world = valid_world(tmp_path)
    path = world["predictions_path"]
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert "PREDICTION_MANIFEST_DIGEST_MISMATCH" in evaluate(world).blockers
    world = valid_world(tmp_path)
    rewrite_predictions(world, lambda rows: rows.pop())
    assert "PREDICTION_DENOMINATOR_MISMATCH" in evaluate(world).blockers


def test_prediction_rejects_truth_fields_and_policy_drift(tmp_path: Path) -> None:
    world = valid_world(tmp_path)
    rewrite_predictions(world, lambda rows: rows[0].update(score=1.0))
    assert "PREDICTION_0000_SCHEMA_INVALID" in evaluate(world).blockers
    world = valid_world(tmp_path)
    rewrite_predictions(
        world,
        lambda rows: rows[0].update(router_policy_sha256="sha256:" + "9" * 64),
    )
    assert "PREDICTION_0000_ROUTER_POLICY_MISMATCH" in evaluate(world).blockers
    world = valid_world(tmp_path)
    rewrite_predictions(
        world,
        lambda rows: rows[0]["route_plan"].update(expected_answer="secret"),
    )
    assert "PREDICTION_0000_ROUTE_PLAN_TRUTH_FIELD_FORBIDDEN" in evaluate(world).blockers


def test_bound_artifact_bytes_cannot_change_after_binding(tmp_path: Path) -> None:
    world = valid_world(tmp_path)
    (tmp_path / "policy.json").write_bytes(b"changed")
    result = evaluate(world)
    assert not result.passed
    assert "BOUND_ARTIFACT_ROUTER_POLICY_DIGEST_MISMATCH" in result.blockers


def test_model_identity_source_must_equal_bound_models(tmp_path: Path) -> None:
    world = valid_world(tmp_path)
    path = tmp_path / "model-identity.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["models"]["ovisocr2"]["model_revision"] = "9" * 40
    write_json(path, value)
    rewrite_binding(
        world,
        lambda binding: binding.update(
            model_identity_source_sha256=digest(path.read_bytes())
        ),
    )
    result = evaluate(world)
    assert not result.passed
    assert "MODEL_IDENTITY_SOURCE_MISMATCH" in result.blockers


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "annotations",
        "evaluator_output",
        "hidden_scores",
        "model_output_quality",
        "source_text",
    ],
)
def test_prediction_rejects_leakage_key_variants(
    tmp_path: Path, forbidden_key: str
) -> None:
    world = valid_world(tmp_path)
    rewrite_predictions(
        world,
        lambda rows: rows[0]["route_plan"].update({forbidden_key: "sealed"}),
    )
    assert (
        "PREDICTION_0000_ROUTE_PLAN_TRUTH_FIELD_FORBIDDEN"
        in evaluate(world).blockers
    )
