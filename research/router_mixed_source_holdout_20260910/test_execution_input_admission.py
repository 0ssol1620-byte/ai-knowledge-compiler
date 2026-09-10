from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from . import preflight_mixed_holdout
from . import render_selected_inputs as render_selected_inputs_module
from .execution_input_admission import (
    RENDER_FIELDS,
    _request_id,
    _streaming_digest,
    _write_immutable_receipt,
    evaluate_admission,
)
from .execution_input_admission import (
    main as admission_main,
)
from .preflight_mixed_holdout import digest, evaluate_preopen
from .render_selected_inputs import RenderedPng, RenderLimits, render_selected_inputs

MODELS = ("mineru_vlm", "paddleocr_vl_1_6", "ovisocr2")


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def _world(tmp_path: Path) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    sources_root = tmp_path / "sources"
    render_root = tmp_path / "renders"
    model_root = tmp_path / "models"
    for root in (sources_root, render_root, model_root):
        root.mkdir()
    source_rows = []
    for index, (unit_id, source_class, content) in enumerate(
        (
            ("native-1", "native_structured", b"a,b\n1,2\n"),
            ("scan-1", "scanned_pdf", b"%PDF-test"),
        )
    ):
        (sources_root / f"{unit_id}.source").write_bytes(content)
        source_rows.append(
            {
                "unit_id": unit_id,
                "source_class": source_class,
                "source_sha256": digest(content),
                "source_size_bytes": len(content),
                "media_type": (
                    "text/csv"
                    if source_class == "native_structured"
                    else "application/pdf"
                ),
                "source_family_id": f"official-family-{index}",
                "source_url": f"https://official-{index}.example.invalid/source",
                "selection_url_sha256": digest(
                    f"https://official-{index}.example.invalid/source".encode()
                ),
                "rights_status": "public_research_allowed",
                "rights_evidence_url": "https://rights.example.invalid/research",
                "rights_checked_at_utc": "2026-09-10T00:00:00Z",
                "allowed_use_scope": "local_research_evaluation_no_redistribution",
                "language": "en",
                "publisher": f"Publisher {index}",
                "acquired_at_utc": "2026-09-10T00:00:00Z",
                "target_locator_kind": "source_native_or_bbox1000",
                "target_locator": (
                    "source-native:whole"
                    if source_class == "native_structured"
                    else "page:1:bbox1000:0,0,1000,1000"
                ),
                "truth_state": "SEALED_UNOPENED",
            }
        )
    source_manifest = tmp_path / "sources.jsonl"
    _jsonl(source_manifest, source_rows)
    protocol = tmp_path / "protocol.json"
    _json(
        protocol,
        {
            "schema": "tavonel.router_mixed_source_holdout_protocol.v1",
            "state": "FROZEN_SELECTION_PROTOCOL",
            "benchmark_id": "TEST-HOLDOUT-V1",
            "frozen_before_acquisition": True,
            "source_selection": {
                "selected_units_per_class": 1,
                "minimum_units_per_class": 1,
                "maximum_units_per_class": 1,
                "maximum_total_units": 2,
            },
            "required_classes": ["native_structured", "scanned_pdf"],
            "model_keys": list(MODELS),
            "execution_budget": {
                "maximum_new_gpu_spend_usd": 20,
                "maximum_model_unit_calls": 600,
                "maximum_parallel_pods": 3,
            },
        },
    )
    predictions = tmp_path / "predictions.jsonl"
    policy = tmp_path / "policy.json"
    _json(policy, {"schema": "test.policy.v1"})
    policy_hash = digest(policy.read_bytes())
    _jsonl(
        predictions,
        [
            {
                "unit_id": row["unit_id"],
                "source_sha256": row["source_sha256"],
                "router_policy_sha256": policy_hash,
                "route_plan": {"first": "native_only"},
            }
            for row in source_rows
        ],
    )

    contract = tmp_path / "contract.json"
    _json(
        contract,
        {
            "representations": {
                "native_structured": {"visual_required": False},
                "scanned_pdf": {"visual_required": True},
            }
        },
    )
    profile = tmp_path / "RENDER_PROFILE.json"
    runtime = tmp_path / "RENDER_RUNTIME.json"
    office_script = tmp_path / "office_render.ps1"
    office_script.write_text("# pinned test office renderer\n", encoding="utf-8")
    render_manifest = tmp_path / "RENDER_MANIFEST.jsonl"
    def fake_pdf_renderer(
        _source: Path,
        _page_number: int,
        _bbox: tuple[int, int, int, int],
        output: Path,
        _limits: RenderLimits,
    ) -> RenderedPng:
        Image.new("RGB", (16, 12), (1, 2, 3)).save(output, format="PNG")
        return RenderedPng(16, 12)

    def fake_runtime_builder(
        _script: Path,
        profile_sha256: str,
        generator_sha256: str,
        office_script_sha256: str,
    ) -> dict[str, object]:
        return {
            "schema": "tavonel.router_render_runtime.v1",
            "state": "FROZEN_BEFORE_MODEL_EXECUTION",
            "truth_opened": False,
            "model_calls": 0,
            "production_promotion": False,
            "profile_sha256": profile_sha256,
            "generator_sha256": generator_sha256,
            "office_script_sha256": office_script_sha256,
        }

    render_result = render_selected_inputs(
        protocol_path=protocol,
        source_manifest_path=source_manifest,
        source_contract_path=contract,
        source_root=sources_root,
        render_root=render_root,
        manifest_path=render_manifest,
        attempt_report_path=tmp_path / "render-attempts.jsonl",
        profile_path=profile,
        runtime_path=runtime,
        office_script=office_script,
        pdf_renderer=fake_pdf_renderer,
        runtime_builder=fake_runtime_builder,
    )
    assert render_result.passed
    render = (render_root / "scan-1.png").read_bytes()

    bound_models: dict[str, dict[str, str]] = {}
    model_rows: list[dict[str, object]] = []
    for index, key in enumerate(MODELS):
        revision = str(index + 1) * 40
        runtime_payload = json.dumps(
            {
                "model_key": key,
                "model_revision": revision,
                "base_image": "registry.example/model@sha256:" + str(index + 1) * 64,
            },
            separators=(",", ":"),
        ).encode()
        artifacts: dict[str, tuple[str, bytes]] = {
            "runtime": (f"{key}/runtime.json", runtime_payload),
            "bundle": (f"{key}/bundle.tar", f"bundle-{key}".encode()),
            "config": (f"{key}/config.json", f"config-{key}".encode()),
            "weight": (f"{key}/weights.bin", f"weights-{key}".encode()),
        }
        for relative, content in artifacts.values():
            path = model_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        bound_models[key] = {
            "model_revision": revision,
            "runtime_sha256": digest(artifacts["runtime"][1]),
            "bundle_sha256": digest(artifacts["bundle"][1]),
            "inference_config_sha256": digest(artifacts["config"][1]),
        }
        model_rows.append(
            {
                "model_key": key,
                "model_revision": revision,
                "runtime_sha256": bound_models[key]["runtime_sha256"],
                "runtime_relative_path": artifacts["runtime"][0],
                "bundle_sha256": bound_models[key]["bundle_sha256"],
                "bundle_relative_path": artifacts["bundle"][0],
                "inference_config_sha256": bound_models[key][
                    "inference_config_sha256"
                ],
                "inference_config_relative_path": artifacts["config"][0],
                "weight_files": [
                    {
                        "relative_path": artifacts["weight"][0],
                        "sha256": digest(artifacts["weight"][1]),
                        "size_bytes": len(artifacts["weight"][1]),
                    }
                ],
            }
        )
    model_manifest = tmp_path / "models.jsonl"
    _jsonl(model_manifest, model_rows)
    snapshot_binding = tmp_path / "model-snapshots.json"
    _json(
        snapshot_binding,
        {
            "schema": "tavonel.router_model_snapshot_binding.v1",
            "state": "FROZEN_BEFORE_REMOTE_EXECUTION",
            "source": "official_huggingface_revision_api_and_resolve_endpoints",
            "models": {
                str(row["model_key"]): {
                    "repository": str(row["model_key"]) + "/repository",
                    "revision": row["model_revision"],
                    "official_api_url": "https://huggingface.co/api/models/test",
                    "official_snapshot_descriptor_sha256": "sha256:" + "a" * 64,
                    "official_file_count": 1,
                    "files": row["weight_files"],
                }
                for row in model_rows
            },
            "truth_opened": False,
            "model_calls": 0,
            "production_promotion": False,
        },
    )
    for model in model_rows:
        runtime_path = model_root / str(model["runtime_relative_path"])
        runtime_value = json.loads(runtime_path.read_text(encoding="utf-8"))
        runtime_value["model_repo"] = str(model["model_key"]) + "/repository"
        runtime_path.write_text(
            json.dumps(runtime_value, separators=(",", ":")), encoding="utf-8"
        )
        model["runtime_sha256"] = digest(runtime_path.read_bytes())
        bound_models[str(model["model_key"])]["runtime_sha256"] = str(
            model["runtime_sha256"]
        )
    _jsonl(model_manifest, model_rows)

    request_rows = []
    for model in model_rows:
        key = str(model["model_key"])
        request_rows.append(
            {
                "request_id": _request_id("scan-1", key, digest(render)),
                "unit_id": "scan-1",
                "model_key": key,
                "source_sha256": source_rows[1]["source_sha256"],
                "target_locator": source_rows[1]["target_locator"],
                "render_sha256": digest(render),
                "router_policy_sha256": policy_hash,
                "runtime_sha256": model["runtime_sha256"],
                "bundle_sha256": model["bundle_sha256"],
                "inference_config_sha256": model["inference_config_sha256"],
                "base_image": (
                    "registry.example/model@sha256:" + str(MODELS.index(key) + 1) * 64
                ),
            }
        )
    request_manifest = tmp_path / "requests.jsonl"
    _jsonl(request_manifest, request_rows)

    candidate_inventory = tmp_path / "candidate-inventory.json"
    _json(candidate_inventory, {"schema": "test.candidate_inventory.v1"})
    development_inventory = tmp_path / "development.json"
    _json(
        development_inventory,
        {
            "schema": "tavonel.router_development_inventory.v1",
            "source_sha256": [],
            "source_family_ids": [],
        },
    )
    limits = tmp_path / "limits.json"
    _json(
        limits,
        {
            "schema": "tavonel.router_execution_limits.v1",
            "state": "FROZEN_BEFORE_EXECUTION",
            "campaign_id": "test-holdout",
            "maximum_new_gpu_spend_usd": 1,
            "maximum_model_unit_calls": 3,
            "maximum_parallel_pods": 1,
        },
    )
    binding = tmp_path / "binding.json"
    runtime_source = tmp_path / "packages/router/src/runtime.py"
    runtime_source.parent.mkdir(parents=True)
    runtime_source.write_bytes(b"runtime")
    native_runtime = tmp_path / "native.json"
    _json(
        native_runtime,
        {
            "schema": "tavonel.router_native_runtime_binding.v1",
            "files": [
                {
                    "path": "packages/router/src/runtime.py",
                    "sha256": digest(runtime_source.read_bytes()),
                }
            ],
        },
    )
    for filename, content in (
        ("freeze.py", b"freeze"),
        ("evaluator.json", b"evaluator"),
        ("statistics.json", b"statistics"),
        (
            "render_selected_inputs.py",
            Path(render_selected_inputs_module.__file__).read_bytes(),
        ),
    ):
        (tmp_path / filename).write_bytes(content)
    model_identity = tmp_path / "model-identity.json"
    _json(
        model_identity,
        {
            "schema": "tavonel.router_model_identity_source.v1",
            "models": bound_models,
        },
    )
    _json(
        binding,
        {
                "schema": "tavonel.router_mixed_source_holdout_binding.v1",
                "state": "FROZEN_PREOPEN",
                "truth_root_relative_path": "truth",
            "benchmark_id": "TEST-HOLDOUT-V1",
            "protocol_sha256": digest(protocol.read_bytes()),
            "source_manifest_sha256": digest(source_manifest.read_bytes()),
            "candidate_inventory_sha256": digest(candidate_inventory.read_bytes()),
            "development_inventory_sha256": digest(
                development_inventory.read_bytes()
            ),
            "prediction_manifest_sha256": digest(predictions.read_bytes()),
            "source_contract_sha256": digest(contract.read_bytes()),
            "model_snapshot_binding_sha256": digest(snapshot_binding.read_bytes()),
            "render_generator_sha256": digest(
                (tmp_path / "render_selected_inputs.py").read_bytes()
            ),
            "office_render_script_sha256": digest(office_script.read_bytes()),
            "router_policy_sha256": policy_hash,
            "preflight_sha256": digest(
                Path(preflight_mixed_holdout.__file__).read_bytes()
            ),
            "freeze_generator_sha256": digest((tmp_path / "freeze.py").read_bytes()),
            "native_runtime_sha256": digest(native_runtime.read_bytes()),
            "evaluator_sha256": digest((tmp_path / "evaluator.json").read_bytes()),
            "statistics_sha256": digest((tmp_path / "statistics.json").read_bytes()),
            "model_identity_source_sha256": digest(model_identity.read_bytes()),
            "models": bound_models,
            "post_render_artifacts": {
                "render_manifest_sha256": digest(render_manifest.read_bytes()),
                "render_profile_sha256": digest(profile.read_bytes()),
                "render_runtime_sha256": digest(runtime.read_bytes()),
                "render_generator_sha256": digest(
                    Path(render_selected_inputs_module.__file__).read_bytes()
                ),
                "office_script_sha256": digest(office_script.read_bytes()),
            },
            "allowed_source_hosts": [
                "official-0.example.invalid",
                "official-1.example.invalid",
            ],
            "artifact_paths": {
                "freeze_generator": "freeze.py",
                "native_runtime": "native.json",
                "source_contract": "contract.json",
                "router_policy": "policy.json",
                "evaluator": "evaluator.json",
                "statistics": "statistics.json",
                "model_identity_source": "model-identity.json",
                "model_snapshot_binding": "model-snapshots.json",
                "render_generator": "render_selected_inputs.py",
                "office_render_script": "office_render.ps1",
            },
            "predictions_frozen": True,
            "input_manifest_contains_truth": False,
        },
    )
    preopen = tmp_path / "preopen.json"
    preopen_result = evaluate_preopen(
        protocol_path=protocol,
        binding_path=binding,
        manifest_path=source_manifest,
        development_hashes_path=development_inventory,
        candidate_inventory_path=candidate_inventory,
        predictions_path=predictions,
        truth_root=tmp_path / "truth",
        source_root=sources_root,
        repo_root=tmp_path,
    )
    assert preopen_result.passed, preopen_result.blockers
    _json(preopen, preopen_result.as_dict())
    return {
        "binding_path": binding,
        "preopen_result_path": preopen,
        "protocol_path": protocol,
        "source_manifest_path": source_manifest,
        "development_inventory_path": development_inventory,
        "candidate_inventory_path": candidate_inventory,
        "predictions_path": predictions,
        "source_contract_path": contract,
        "source_root": sources_root,
        "render_manifest_path": render_manifest,
        "render_root": render_root,
        "render_profile_path": profile,
        "render_runtime_path": runtime,
        "office_script_path": office_script,
        "model_manifest_path": model_manifest,
        "model_snapshot_binding_path": snapshot_binding,
        "model_root": model_root,
        "request_manifest_path": request_manifest,
        "execution_limits_path": limits,
        "truth_root": tmp_path / "truth",
        "repo_root": tmp_path,
    }


def test_complete_worker_admission_passes(tmp_path: Path) -> None:
    world = _world(tmp_path)
    render_row = json.loads(
        world["render_manifest_path"].read_text(encoding="utf-8").strip()
    )
    assert set(render_row) == RENDER_FIELDS
    result = evaluate_admission(**world)
    assert result.passed
    assert result.requests == 3


def _admission_argv(world: dict[str, Path], output: Path) -> list[str]:
    argument_names = {
        "binding": "binding_path",
        "preopen-result": "preopen_result_path",
        "protocol": "protocol_path",
        "source-manifest": "source_manifest_path",
        "development-inventory": "development_inventory_path",
        "candidate-inventory": "candidate_inventory_path",
        "predictions": "predictions_path",
        "source-contract": "source_contract_path",
        "source-root": "source_root",
        "render-manifest": "render_manifest_path",
        "render-root": "render_root",
        "render-profile": "render_profile_path",
        "render-runtime": "render_runtime_path",
        "office-script": "office_script_path",
        "model-manifest": "model_manifest_path",
        "model-snapshot-binding": "model_snapshot_binding_path",
        "model-root": "model_root",
        "request-manifest": "request_manifest_path",
        "execution-limits": "execution_limits_path",
        "truth-root": "truth_root",
        "repo-root": "repo_root",
    }
    argv: list[str] = []
    for argument, key in argument_names.items():
        argv.extend([f"--{argument}", str(world[key])])
    argv.extend(["--output", str(output)])
    return argv


def test_admission_cli_malformed_and_oversized_inputs_write_failure_receipts(
    tmp_path: Path,
) -> None:
    malformed = _world(tmp_path / "malformed")
    malformed["render_profile_path"].write_text("{truncated", encoding="utf-8")
    malformed_output = tmp_path / "malformed-admission.json"
    assert admission_main(_admission_argv(malformed, malformed_output)) == 2
    malformed_receipt = json.loads(malformed_output.read_text(encoding="utf-8"))
    assert malformed_receipt["passed"] is False
    assert malformed_receipt["model_call_authorized"] is False
    assert malformed_receipt["blockers"] == ["ADMISSION_INPUT_JSONDECODEERROR"]

    oversized = _world(tmp_path / "oversized")
    with oversized["render_profile_path"].open("wb") as handle:
        handle.seek(64 * 1024 * 1024)
        handle.write(b"x")
    oversized_output = tmp_path / "oversized-admission.json"
    assert admission_main(_admission_argv(oversized, oversized_output)) == 2
    oversized_receipt = json.loads(oversized_output.read_text(encoding="utf-8"))
    assert oversized_receipt["passed"] is False
    assert oversized_receipt["model_call_authorized"] is False
    assert oversized_receipt["blockers"] == ["ADMISSION_INPUT_VALUEERROR"]


def test_canonical_truth_root_is_frozen_before_admission(tmp_path: Path) -> None:
    world = _world(tmp_path)
    world["truth_root"] = tmp_path / "alternate-empty-truth"
    result = evaluate_admission(**world)
    assert "CANONICAL_TRUTH_ROOT_BINDING_MISMATCH" in result.blockers


def test_render_and_request_rebinding_cannot_bypass_frozen_binding(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    render_path = world["render_root"] / "scan-1.png"
    Image.new("RGB", (16, 12), (9, 8, 7)).save(render_path, format="PNG")
    render_rows = [
        json.loads(line)
        for line in world["render_manifest_path"].read_text().splitlines()
    ]
    render_rows[0]["render_sha256"] = digest(render_path.read_bytes())
    render_rows[0]["render_size_bytes"] = render_path.stat().st_size
    _jsonl(world["render_manifest_path"], render_rows)
    requests = [
        json.loads(line)
        for line in world["request_manifest_path"].read_text().splitlines()
    ]
    for request in requests:
        request["render_sha256"] = render_rows[0]["render_sha256"]
        request["request_id"] = _request_id(
            str(request["unit_id"]),
            str(request["model_key"]),
            str(request["render_sha256"]),
        )
    _jsonl(world["request_manifest_path"], requests)

    result = evaluate_admission(**world)

    assert not result.passed
    assert "POST_RENDER_RENDER_MANIFEST_SHA256_MISMATCH" in result.blockers


@pytest.mark.parametrize(
    ("relative", "blocker"),
    [
        ("sources/scan-1.source", "SOURCE_0001_DIGEST_MISMATCH"),
        ("renders/scan-1.png", "RENDER_0000_DIGEST_MISMATCH"),
        ("models/ovisocr2/bundle.tar", "MODEL_0002_BUNDLE_DIGEST_MISMATCH"),
        ("models/ovisocr2/runtime.json", "MODEL_0002_RUNTIME_DIGEST_MISMATCH"),
        ("models/ovisocr2/config.json", "MODEL_0002_INFERENCE_CONFIG_DIGEST_MISMATCH"),
        ("models/ovisocr2/weights.bin", "MODEL_0002_WEIGHT_0000_DIGEST_MISMATCH"),
    ],
)
def test_actual_byte_drift_fails_closed(
    tmp_path: Path, relative: str, blocker: str
) -> None:
    world = _world(tmp_path)
    path = tmp_path / relative
    data = path.read_bytes()
    path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    result = evaluate_admission(**world)
    assert not result.passed
    assert blocker in result.blockers


def test_locator_and_request_denominator_fail_closed(tmp_path: Path) -> None:
    world = _world(tmp_path / "locator")
    path = world["render_manifest_path"]
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["target_locator"] = "page:2:bbox1000:0,0,1000,1000"
    _jsonl(path, rows)
    assert "RENDER_0000_LOCATOR_MISMATCH" in evaluate_admission(**world).blockers

    world = _world(tmp_path / "denominator")
    path = world["request_manifest_path"]
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    _jsonl(path, rows[:-1])
    assert "REQUEST_DENOMINATOR_MISMATCH" in evaluate_admission(**world).blockers


def test_stale_preopen_truth_and_budget_fail_closed(tmp_path: Path) -> None:
    world = _world(tmp_path / "preopen")
    path = world["binding_path"]
    path.write_bytes(path.read_bytes() + b" ")
    assert "LIVE_PREOPEN_BINDING_NOT_ADMITTED" in evaluate_admission(**world).blockers

    world = _world(tmp_path / "truth")
    world["truth_root"].mkdir()
    (world["truth_root"] / "sealed.jsonl").write_text("{}\n", encoding="utf-8")
    assert "HOLDOUT_TRUTH_ALREADY_PRESENT" in evaluate_admission(**world).blockers

    world = _world(tmp_path / "budget")
    limits = json.loads(
        world["execution_limits_path"].read_text(encoding="utf-8")
    )
    limits["maximum_new_gpu_spend_usd"] = 21
    _json(world["execution_limits_path"], limits)
    assert (
        "EXECUTION_MAXIMUM_NEW_GPU_SPEND_USD_EXCEEDED"
        in evaluate_admission(**world).blockers
    )


def test_render_profile_and_runtime_drift_fail_closed(tmp_path: Path) -> None:
    world = _world(tmp_path / "profile")
    world["render_profile_path"].write_text('{"profile":"changed"}\n')
    result = evaluate_admission(**world)
    assert "RENDER_0000_PROFILE_MISMATCH" in result.blockers

    world = _world(tmp_path / "runtime")
    world["render_runtime_path"].write_text('{"runtime":"changed"}\n')
    result = evaluate_admission(**world)
    assert "RENDER_0000_RUNTIME_MISMATCH" in result.blockers


def test_source_class_denominator_fails_closed(tmp_path: Path) -> None:
    world = _world(tmp_path)
    protocol = json.loads(world["protocol_path"].read_text(encoding="utf-8"))
    protocol["source_selection"]["maximum_total_units"] = 3
    _json(world["protocol_path"], protocol)
    result = evaluate_admission(**world)
    assert "SOURCE_TOTAL_DENOMINATOR_MISMATCH" in result.blockers


def test_streaming_digest_handles_large_sparse_file(tmp_path: Path) -> None:
    path = tmp_path / "large-sparse.bin"
    size = 32 * 1024 * 1024 + 17
    with path.open("wb") as handle:
        handle.seek(size - 1)
        handle.write(b"x")
    hasher = __import__("hashlib").sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    assert _streaming_digest(path, chunk_size=1024 * 1024) == (
        "sha256:" + hasher.hexdigest()
    )


def test_admission_receipt_is_immutable(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    _write_immutable_receipt(path, b'{"passed":true}\n')
    _write_immutable_receipt(path, b'{"passed":true}\n')
    with pytest.raises(
        ValueError, match="ADMISSION_RECEIPT_ALREADY_EXISTS_DIFFERENT"
    ):
        _write_immutable_receipt(path, b'{"passed":false}\n')


def test_unlisted_model_file_fails_closed(tmp_path: Path) -> None:
    world = _world(tmp_path)
    (world["model_root"] / "ovisocr2" / "unlisted.safetensors").write_bytes(b"x")
    result = evaluate_admission(**world)
    assert "MODEL_ARTIFACT_FILE_DENOMINATOR_MISMATCH" in result.blockers


def test_unpinned_runtime_image_fails_closed(tmp_path: Path) -> None:
    world = _world(tmp_path)
    runtime_path = world["model_root"] / "ovisocr2" / "runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["base_image"] = "registry.example/model:latest"
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
    models_path = world["model_manifest_path"]
    models = [json.loads(line) for line in models_path.read_text().splitlines()]
    models[2]["runtime_sha256"] = digest(runtime_path.read_bytes())
    _jsonl(models_path, models)
    result = evaluate_admission(**world)
    assert "MODEL_0002_RUNTIME_BASE_IMAGE_NOT_PINNED" in result.blockers


def test_mutable_protocol_cannot_raise_hard_caps(tmp_path: Path) -> None:
    world = _world(tmp_path)
    protocol_path = world["protocol_path"]
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol["execution_budget"]["maximum_new_gpu_spend_usd"] = 100
    _json(protocol_path, protocol)
    binding_path = world["binding_path"]
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding["protocol_sha256"] = digest(protocol_path.read_bytes())
    _json(binding_path, binding)
    preopen = evaluate_preopen(
        protocol_path=protocol_path,
        binding_path=binding_path,
        manifest_path=world["source_manifest_path"],
        development_hashes_path=world["development_inventory_path"],
        candidate_inventory_path=world["candidate_inventory_path"],
        predictions_path=world["predictions_path"],
        truth_root=world["truth_root"],
        source_root=world["source_root"],
        repo_root=world["repo_root"],
    )
    _json(world["preopen_result_path"], preopen.as_dict())
    limits = json.loads(world["execution_limits_path"].read_text(encoding="utf-8"))
    limits["maximum_new_gpu_spend_usd"] = 100
    _json(world["execution_limits_path"], limits)
    result = evaluate_admission(**world)
    assert "PROTOCOL_MAXIMUM_NEW_GPU_SPEND_USD_HARD_CAP_MISMATCH" in result.blockers
    assert "EXECUTION_MAXIMUM_NEW_GPU_SPEND_USD_EXCEEDED" in result.blockers


@pytest.mark.parametrize(
    "target",
    ("render_profile_path", "render_runtime_path", "execution_limits_path"),
)
def test_nested_truth_keys_fail_closed(tmp_path: Path, target: str) -> None:
    world = _world(tmp_path)
    path = world[target]
    value = json.loads(path.read_text(encoding="utf-8"))
    value["nested"] = {"annotations": {"ground_truth": "secret"}}
    _json(path, value)
    result = evaluate_admission(**world)
    prefix = target.removesuffix("_path").upper()
    assert f"{prefix}_TRUTH_FIELD_FORBIDDEN" in result.blockers


def test_mutable_weight_manifest_cannot_rebind_snapshot(tmp_path: Path) -> None:
    world = _world(tmp_path)
    weight_path = world["model_root"] / "ovisocr2" / "weights.bin"
    weight_path.write_bytes(b"attacker-selected-weights")
    manifest_path = world["model_manifest_path"]
    rows = [json.loads(line) for line in manifest_path.read_text().splitlines()]
    rows[2]["weight_files"][0].update(
        sha256=digest(weight_path.read_bytes()), size_bytes=weight_path.stat().st_size
    )
    _jsonl(manifest_path, rows)
    result = evaluate_admission(**world)
    assert "MODEL_0002_WEIGHT_SNAPSHOT_MISMATCH" in result.blockers


def test_forged_saved_preopen_and_native_runtime_drift_fail_closed(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path / "forged")
    preopen_path = world["preopen_result_path"]
    preopen = json.loads(preopen_path.read_text(encoding="utf-8"))
    preopen.update(
        schema="forged",
        native_runtime_files_verified=False,
        holdout_opened=True,
        model_calls=999,
    )
    _json(preopen_path, preopen)
    assert (
        "SAVED_PREOPEN_RESULT_STALE_OR_MUTATED"
        in evaluate_admission(**world).blockers
    )

    world = _world(tmp_path / "native-drift")
    (world["repo_root"] / "packages/router/src/runtime.py").write_bytes(b"drift")
    assert "LIVE_PREOPEN_FAILED" in evaluate_admission(**world).blockers


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("maximum_new_gpu_spend_usd", float("nan")),
        ("maximum_parallel_pods", -1),
        ("maximum_parallel_pods", 1.5),
    ],
)
def test_nonfinite_negative_or_fractional_limits_fail_closed(
    tmp_path: Path, field: str, value: float
) -> None:
    world = _world(tmp_path)
    path = world["execution_limits_path"]
    limits = json.loads(path.read_text(encoding="utf-8"))
    limits[field] = value
    _json(path, limits)
    result = evaluate_admission(**world)
    assert f"EXECUTION_{field.upper()}_INVALID" in result.blockers
