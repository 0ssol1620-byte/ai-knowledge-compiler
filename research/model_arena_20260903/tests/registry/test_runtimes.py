"""D16/D17/D34 — model_registry.json is a derived copy of runtime.json.

These tests read the real committed artefacts, not fixtures: their whole point is
that the files a paid canary will actually load agree with each other. A lane that
edits `runtimes/<key>/runtime.json` without regenerating the registry, or renames a
`prompt_id` without adding a prompt file, fails here rather than on a GPU.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from arena.constants import GPU_MODEL_KEYS, NAMESPACE_ROOT
from arena.registry.errors import RegistryError
from arena.registry.runtimes import (
    DERIVED_FIELDS,
    OPUS_PROMPT_ID,
    build_overlay,
    load_overlays,
    load_prompt_sha256,
    load_runtime_spec,
    opus_registry_fields,
    overlay_disagreements,
)

PROMPT_DIR = NAMESPACE_ROOT / "prompt_registry"
MODEL_REGISTRY = NAMESPACE_ROOT / "model_registry.json"
EVALUATOR_REGISTRY = NAMESPACE_ROOT / "evaluator_registry.json"
PROVENANCE_RECEIPT = (
    NAMESPACE_ROOT / "receipts" / "registry-updates" / "evaluator-olmocr-provenance.json"
)

#: sha256 of the empty string; every prompt_kind "none" model must land here.
EMPTY_SHA256 = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry() -> dict[str, Any]:
    document = _load(MODEL_REGISTRY)
    assert isinstance(document, dict)
    return document


@pytest.fixture(scope="module")
def overlays() -> dict[str, Any]:
    return dict(load_overlays())


# --------------------------------------------------------------------------- D16


def test_every_gpu_model_has_a_runtime_json() -> None:
    for model_key in GPU_MODEL_KEYS:
        spec = load_runtime_spec(model_key)
        assert spec["model_key"] == model_key


def test_registry_agrees_with_runtime_json(
    registry: dict[str, Any], overlays: dict[str, Any]
) -> None:
    """The D16 gate. Regenerate with `python -m arena.registry resolve --offline`."""
    assert overlay_disagreements(registry, overlays) == ()


def test_registry_carries_every_derived_field(
    registry: dict[str, Any], overlays: dict[str, Any]
) -> None:
    for model_key, overlay in overlays.items():
        record = registry["models"][model_key]
        expected = overlay.as_registry_fields()
        for field in DERIVED_FIELDS:
            assert field in record, f"{model_key} is missing derived field {field}"
            assert record[field] == expected[field]


def test_disagreement_is_detected(registry: dict[str, Any], overlays: dict[str, Any]) -> None:
    """The gate must actually fail when the two files drift apart."""
    tampered = json.loads(json.dumps(registry))
    tampered["models"]["olmocr2"]["revision"] = "0" * 40
    tampered["models"]["glm_ocr"]["prompt_id"] = "glm_ocr_official_v1"
    problems = overlay_disagreements(tampered, overlays)
    assert any("olmocr2.revision" in problem for problem in problems)
    assert any("glm_ocr.prompt_id" in problem for problem in problems)


def test_missing_model_is_a_disagreement(overlays: dict[str, Any]) -> None:
    problems = overlay_disagreements({"models": {}}, overlays)
    assert len(problems) == len(overlays)
    assert all(problem.endswith("absent from model_registry.json") for problem in problems)


def test_registry_without_models_object_fails(overlays: dict[str, Any]) -> None:
    assert overlay_disagreements({}, overlays) == (
        "model_registry.json has no 'models' object",
    )


def test_monkeyocr_and_mineru_copy_runtime_json(registry: dict[str, Any]) -> None:
    """The two disagreements D16 names, resolved in runtime.json's favour."""
    monkey = registry["models"]["monkeyocrv2_b"]
    assert monkey["revision"] == "de7a993bd0f39a97b122dac767e82ae04935bce4"
    assert monkey["identity_source"] == "runtimes/monkeyocrv2_b/runtime.json"
    # Deliberately behind the live HF head; the record must say so rather than hide it.
    assert monkey["identity_pinned_behind_upstream"] is True
    assert monkey["upstream_resolved_revision"] != monkey["revision"]

    mineru = registry["models"]["mineru_pipeline"]
    assert mineru["repo"] == "opendatalab/PDF-Extract-Kit-1.0"
    assert mineru["revision"] == "ed6b654c018d742e65a17671e379c5e6ecc87ec9"
    # The MinerU code release stays visible as a code repository, not as the identity.
    assert any(entry["repo"] == "opendatalab/MinerU" for entry in mineru["code_repositories"])


def test_infinity_parser2_pro_licence_is_verified(registry: dict[str, Any]) -> None:
    """Founder decision 2026-09-03 cleared the checkpoint; see the D36 note below."""
    record = registry["models"]["infinity_parser2_pro"]
    assert record["license_status"] == "verified"
    assert record["license_detail"]["status"] == "verified"
    assert "INF-MLLM" in record["license_notes"]
    runtime = load_runtime_spec("infinity_parser2_pro")
    assert runtime["license"]["status"] == "verified"
    assert runtime["license"]["spdx_base"] == "Apache-2.0"


def test_gpu_count_min_matches_runtime_json(registry: dict[str, Any]) -> None:
    assert registry["models"]["infinity_parser2_pro"]["gpu_count_min"] == 2
    for model_key in GPU_MODEL_KEYS:
        if model_key == "infinity_parser2_pro":
            continue
        assert registry["models"][model_key]["gpu_count_min"] == 1


# --------------------------------------------------------------------------- D17/D34


def test_every_runtime_prompt_id_resolves() -> None:
    shas = load_prompt_sha256()
    for model_key in GPU_MODEL_KEYS:
        prompt_id = load_runtime_spec(model_key)["prompt_id"]
        assert prompt_id in shas, f"{model_key}: prompt id {prompt_id} has no sha256 entry"
        assert (PROMPT_DIR / f"{prompt_id}.txt").is_file()


def test_prompt_file_bytes_hash_to_the_recorded_sha256() -> None:
    shas = load_prompt_sha256()
    for prompt_id, digest in shas.items():
        data = (PROMPT_DIR / f"{prompt_id}.txt").read_bytes()
        assert f"sha256:{hashlib.sha256(data).hexdigest()}" == digest, prompt_id


def test_model_specific_prompts_matches_sha256_json() -> None:
    shas = load_prompt_sha256()
    prompts = _load(PROMPT_DIR / "model_specific_prompts.json")
    assert set(prompts) == set(shas)
    for prompt_id, entry in prompts.items():
        assert entry["prompt_id"] == prompt_id
        assert entry["sha256"] == shas[prompt_id]
        text = (PROMPT_DIR / f"{prompt_id}.txt").read_text(encoding="utf-8")
        assert entry["text"] == text
        assert entry["prompt_kind"] in ("text", "toolkit", "none")


def test_prompt_kind_rules(registry: dict[str, Any]) -> None:
    prompts = _load(PROMPT_DIR / "model_specific_prompts.json")
    for model_key in GPU_MODEL_KEYS:
        spec = load_runtime_spec(model_key)
        prompt_id = spec["prompt_id"]
        kind = spec.get("prompt_kind")
        assert kind in ("text", "toolkit", "none"), f"{model_key} declares prompt_kind {kind!r}"
        # runtime.json and the registry entry must agree on the kind.
        assert prompts[prompt_id]["prompt_kind"] == kind
        assert registry["models"][model_key]["prompt_kind"] == kind
        text = (PROMPT_DIR / f"{prompt_id}.txt").read_text(encoding="utf-8")
        if kind == "none":
            assert text == ""
            assert registry["models"][model_key]["prompt_sha256"] == EMPTY_SHA256
        else:
            assert text, f"{model_key}: prompt_kind {kind} needs a non-empty prompt file"


def test_toolkit_bundles_are_canonical_json() -> None:
    """The two prompt-bundle models: the file is the canonical JSON of the mapping."""
    prompts = _load(PROMPT_DIR / "model_specific_prompts.json")
    for prompt_id in (
        "glm_ocr_official_sdk_task_prompts_v1",
        "monkeyocrv2_b_official_pipeline_prompts_v1",
    ):
        entry = prompts[prompt_id]
        bundle = entry["prompt_bundle"]
        assert isinstance(bundle, dict) and bundle
        canonical = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        assert entry["text"] == canonical
        assert (PROMPT_DIR / f"{prompt_id}.txt").read_text(encoding="utf-8") == canonical


def test_opus_prompt_is_unchanged(registry: dict[str, Any]) -> None:
    shas = load_prompt_sha256()
    expected = "sha256:2a8741532324e1fb6be192253eb3a19301a3eb49ef0c8764bf97505382d263ee"
    assert shas[OPUS_PROMPT_ID] == expected
    fields = opus_registry_fields(shas)
    assert fields["prompt_id"] == OPUS_PROMPT_ID
    record = registry["models"]["opus5_subscription"]
    assert record["prompt_id"] == OPUS_PROMPT_ID
    assert record["prompt_sha256"] == expected


def test_retired_prompt_ids_are_documented_not_deleted() -> None:
    """Nothing was dropped silently: README carries the retired -> current mapping."""
    readme = (PROMPT_DIR / "README.md").read_text(encoding="utf-8")
    shas = load_prompt_sha256()
    for model_key in GPU_MODEL_KEYS:
        retired = f"{model_key}_official_v1"
        assert retired not in shas
        assert retired in readme, f"{retired} vanished without a README mapping row"


def test_unresolved_prompt_id_fails_closed() -> None:
    with pytest.raises(RegistryError, match="has no entry in"):
        build_overlay("olmocr2", prompt_shas={})


def test_missing_prompt_registry_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="prompt registry is required"):
        load_prompt_sha256(tmp_path)


def test_null_prompt_sha256_is_refused(tmp_path: Path) -> None:
    (tmp_path / "prompt_registry").mkdir()
    (tmp_path / "prompt_registry" / "sha256.json").write_text(
        json.dumps({"x_v1": None}), encoding="utf-8"
    )
    with pytest.raises(RegistryError, match="not a 'sha256:<hex>' string"):
        load_prompt_sha256(tmp_path)


def test_opus_prompt_missing_fails_closed() -> None:
    with pytest.raises(RegistryError, match="cannot bind a prompt sha256"):
        opus_registry_fields({})


# --------------------------------------------------------------------------- D31


def test_olmocr_provenance_receipt_backs_the_registry() -> None:
    receipt = _load(PROVENANCE_RECEIPT)
    evaluators = _load(EVALUATOR_REGISTRY)["evaluators"]
    olmocr = evaluators["olmocr"]

    assert receipt["decision_ref"] == "ARENA_CONTRACT.md section 11.5 D31"
    conclusion = receipt["conclusion"]
    assert conclusion["recorded_repository_is_wrong"] is False
    assert conclusion["repository_repointed"] is False
    assert olmocr["repository"] == conclusion["repository_kept"]

    # The pin the campaign runs must exist where the registry says it lives.
    pin = receipt["historical_pin"]
    assert olmocr["historical_pin"] == pin
    presence = receipt["historical_pin_presence"]
    assert presence["jina-ai/olmocr-bench"]["exists"] is True
    assert presence["allenai/olmocr"]["exists"] is False

    # Additive provenance only: the pins and the freeze flag are untouched.
    assert olmocr["upstream_source"].startswith("https://github.com/allenai/olmocr")
    assert olmocr["upstream_source_license"] == "Apache-2.0"
    assert olmocr["upstream_relationship"] == "content_extraction_not_github_fork"
    assert olmocr["provenance_receipt"] == (
        "receipts/registry-updates/evaluator-olmocr-provenance.json"
    )
    assert olmocr["frozen"] is False
    assert receipt["repositories"]["jina-ai/olmocr-bench"]["license_file_present"] is False
    assert receipt["repositories"]["allenai/olmocr"]["license_spdx_id"] == "Apache-2.0"


def test_the_cuda_floor_is_read_from_runtime_json_not_the_registry(
    registry: dict[str, Any],
) -> None:
    """``min_cuda_version`` is deliberately not a D16 derived field.

    The provisioning gate reads it straight out of ``runtime.json`` through
    ``arena.controller.runtime_spec``, so copying it into the registry would
    create a second source that could drift without any gate noticing. This
    test exists so that "the registry is missing a field" is answered here
    rather than by adding one.
    """

    assert "min_cuda_version" not in DERIVED_FIELDS
    for model_key in GPU_MODEL_KEYS:
        assert "min_cuda_version" in load_runtime_spec(model_key)
        assert "min_cuda_version" not in registry["models"][model_key]
