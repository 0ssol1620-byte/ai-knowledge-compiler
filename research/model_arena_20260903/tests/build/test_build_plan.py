"""build_plan.json schema validation and model-key coverage.

Exercises the *static* checked-in file plus the generator's offline path
(``--offline`` / ``offline=True``), never a live network call — CI must not
depend on registry reachability.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from arena.constants import GPU_MODEL_KEYS
from generate_build_plan import build_plan_document

BUILD_DIR = Path(__file__).resolve().parents[2] / "build"


@pytest.fixture(scope="module")
def schema() -> dict[str, object]:
    return json.loads((BUILD_DIR / "build_plan.schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def checked_in_plan() -> dict[str, object]:
    return json.loads((BUILD_DIR / "build_plan.json").read_text(encoding="utf-8"))


def test_checked_in_build_plan_validates_against_schema(schema, checked_in_plan) -> None:
    jsonschema.validate(checked_in_plan, schema)


def test_checked_in_build_plan_has_every_gpu_model_key(checked_in_plan) -> None:
    assert set(checked_in_plan["models"]) == set(GPU_MODEL_KEYS)
    assert len(checked_in_plan["models"]) == 11


def test_checked_in_build_plan_excludes_opus_subscription(checked_in_plan) -> None:
    assert "opus5_subscription" not in checked_in_plan["models"]


@pytest.mark.parametrize("model_key", GPU_MODEL_KEYS)
def test_every_model_entry_has_required_shape(checked_in_plan, model_key: str) -> None:
    entry = checked_in_plan["models"][model_key]
    assert entry["model_key"] == model_key
    assert entry["dockerfile"] == f"runtimes/{model_key}/Dockerfile"
    assert entry["registry_target"] == f"ghcr.io/0ssol1620-byte/tavonel-arena/{model_key}"
    assert entry["builder_pod"]["gpu_required"] is False
    assert entry["builder_pod"]["disk_gb"] >= 40
    assert "strategy" in entry["weights"]
    assert isinstance(entry["risks"], list)
    assert "base_image_config" in entry
    assert "resolved" in entry["base_image_config"]
    assert "detail" in entry["base_image_config"]


def test_offline_generation_never_touches_the_network(schema) -> None:
    """The generator must produce a schema-valid, fully-keyed document with
    every digest null when told to skip the network -- this is what CI runs,
    never the live path exercised manually to produce the checked-in file."""
    document = build_plan_document(offline=True)
    jsonschema.validate(document, schema)
    assert document["offline"] is True
    for model_key in GPU_MODEL_KEYS:
        entry = document["models"][model_key]
        # Digests already embedded in runtime.json survive offline mode (no
        # lookup needed); only *unpinned* base images resolve to null offline.
        if entry["base_image"]["digest"] is None:
            assert entry["risks"], f"{model_key} should record why its digest is null"
        # base_image_config always requires a network call, embedded digest
        # or not, so offline mode must never resolve it.
        assert entry["base_image_config"]["resolved"] is False
        assert entry["base_image_config"]["entrypoint"] is None


def test_offline_generation_is_deterministic_apart_from_timestamp() -> None:
    first = build_plan_document(offline=True)
    second = build_plan_document(offline=True)
    first.pop("generated_at")
    second.pop("generated_at")
    for entry in first["models"].values():
        entry["base_image"].pop("resolved_at", None)
    for entry in second["models"].values():
        entry["base_image"].pop("resolved_at", None)
    assert first == second


def test_missing_runtime_json_is_reported_not_crashed(tmp_path, monkeypatch) -> None:
    """generate_build_plan.py must tolerate another lane's file not existing
    yet (14-lane parallel build) rather than raising."""
    import generate_build_plan

    monkeypatch.setattr(generate_build_plan, "NAMESPACE_ROOT", tmp_path)
    entry = generate_build_plan._model_plan("paddleocr_vl_1_6", offline=True)
    assert entry["model_key"] == "paddleocr_vl_1_6"
    assert any("does not exist yet" in risk for risk in entry["risks"])
    assert entry["base_image"]["digest"] is None
