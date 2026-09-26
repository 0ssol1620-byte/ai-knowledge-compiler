"""Every GPU runtime declares the host CUDA floor its base image needs.

Pod ``3xag0y00rgoj4n`` (GLM-OCR, RTX 4090 SECURE) passed its architecture
preflight, resolved ``GlmOcrMTPModel``, and then died in
``torch._C._cuda_init`` with CUDA error 804, "forward compatibility was
attempted on non supported HW": the pinned image ships a CUDA 12.9 runtime and
RunPod placed it on a host reporting ``cudaVersion: "12.8"``. The constraint
was never expressed in the create payload, so nothing could refuse the
placement and the pod billed until it was torn down.

These are static checks over all eleven GPU runtimes: no network, no GPU, no
container runtime. They prove the field is present and well formed, that it
turns into a non-empty ``allowedCudaVersions``, and that the evidence for the
number is written down next to the runtime rather than carried in a head.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import jsonschema
import pytest
from arena.constants import GPU_MODEL_KEYS
from arena.controller.provision import RUNPOD_CUDA_VERSIONS, allowed_cuda_versions
from conftest import NAMESPACE_ROOT, load_runtime_json, runtime_dir

RUNTIME_SCHEMA: Final = NAMESPACE_ROOT / "arena" / "core" / "schemas" / "runtime.schema.json"


def _evidence_text(model_key: str) -> str:
    """Everything the runtime lane wrote down about this runtime, as one blob.

    The evidence lives in ``provenance.json`` where the runtime has one and in
    ``runtime.json``'s ``notes`` where it does not (glm_ocr). Both are read so
    the check is about the evidence existing, not about which file holds it.
    """

    parts: list[str] = []
    provenance = runtime_dir(model_key) / "provenance.json"
    if provenance.is_file():
        parts.append(provenance.read_text(encoding="utf-8"))
    parts.append(json.dumps(load_runtime_json(model_key).get("notes"), ensure_ascii=False))
    return "\n".join(parts)


@pytest.mark.parametrize("model_key", GPU_MODEL_KEYS)
def test_every_runtime_json_validates_against_the_schema(model_key: str) -> None:
    schema: Any = json.loads(RUNTIME_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(instance=load_runtime_json(model_key), schema=schema)


@pytest.mark.parametrize("model_key", GPU_MODEL_KEYS)
def test_every_gpu_runtime_declares_a_cuda_floor(model_key: str) -> None:
    """Every one of these rents a GPU and starts a CUDA process."""

    document = load_runtime_json(model_key)
    assert document["gpu_pool_priority"], "a runtime with no pool rents nothing"
    version = document.get("min_cuda_version")
    assert isinstance(version, str) and version, (
        f"runtimes/{model_key}/runtime.json declares no min_cuda_version; a CUDA image "
        "placed below its floor fails at torch._C._cuda_init after the pod is billing"
    )
    major, _, minor = version.partition(".")
    assert major.isdigit() and minor.isdigit(), version


@pytest.mark.parametrize("model_key", GPU_MODEL_KEYS)
def test_every_floor_is_a_version_runpod_can_actually_filter_on(model_key: str) -> None:
    """A floor RunPod does not list would send an empty filter, i.e. no filter."""

    version = str(load_runtime_json(model_key)["min_cuda_version"])
    allowed = allowed_cuda_versions(version)
    assert allowed, model_key
    assert version in RUNPOD_CUDA_VERSIONS, (
        f"{model_key}: {version} is not one of the CUDA versions RunPod's "
        f"PodCreateInput.allowedCudaVersions enum offers {list(RUNPOD_CUDA_VERSIONS)}"
    )
    assert allowed[0] == version


@pytest.mark.parametrize("model_key", GPU_MODEL_KEYS)
def test_the_number_is_backed_by_evidence_next_to_the_runtime(model_key: str) -> None:
    """Never publish a number without a receipt: the URL and the read are recorded."""

    evidence = _evidence_text(model_key)
    version = str(load_runtime_json(model_key)["min_cuda_version"])
    assert version in evidence, f"{model_key}: the floor {version} is asserted nowhere"
    assert "min_cuda_version" in evidence or "MIN CUDA" in evidence, model_key
    assert "https://" in evidence, f"{model_key}: no evidence URL recorded"


def test_the_two_runtimes_that_share_an_image_share_a_floor() -> None:
    """monkeyocrv2_b and olmocr2 pin the same digest, so the same config blob."""

    monkey = load_runtime_json("monkeyocrv2_b")
    olmo = load_runtime_json("olmocr2")
    assert monkey["base_image"] == olmo["base_image"]
    assert monkey["min_cuda_version"] == olmo["min_cuda_version"]

    pipeline = load_runtime_json("mineru_pipeline")
    vlm = load_runtime_json("mineru_vlm")
    assert pipeline["base_image"] == vlm["base_image"]
    assert pipeline["min_cuda_version"] == vlm["min_cuda_version"]


def test_a_tag_that_states_its_cuda_version_agrees_with_the_declared_floor() -> None:
    """Where the pinned tag itself carries the version, the two must not drift.

    Only the two images whose tag states a CUDA version are checked. The others
    are read from the image config, which a tag cannot be substituted for.
    """

    for model_key, marker in (("deepseek_ocr2", "cuda11.8"), ("unlimited_ocr", "12.9.1")):
        document = load_runtime_json(model_key)
        assert marker in str(document["base_image"]), model_key
        assert marker.startswith(f"cuda{document['min_cuda_version']}") or marker.startswith(
            str(document["min_cuda_version"])
        ), model_key


def test_the_incident_receipt_that_motivated_the_field_is_still_on_disk() -> None:
    path = Path(NAMESPACE_ROOT) / "receipts" / "incidents" / (
        "glm_ocr-3xag0y00rgoj4n-cuda804.json"
    )
    assert path.is_file(), "the incident this field answers must stay citable"
    incident = json.loads(path.read_text(encoding="utf-8"))
    assert incident["host_cuda_version_reported"] == "12.8"
    assert load_runtime_json("glm_ocr")["min_cuda_version"] == "12.9"
