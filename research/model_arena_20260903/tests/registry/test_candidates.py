"""Facts in the candidate table that the campaign would be wrong without.

These are not style assertions. Each one pins something that was read out of an
official source on 2026-09-03 and that a later edit could quietly break.
"""

from __future__ import annotations

import pytest
from arena.constants import MODEL_KEYS
from arena.registry.candidates import CANDIDATES, CANDIDATES_BY_KEY, FTO_CAVEAT
from arena.registry.catalog import RUNPOD_GPU_CATALOG


def test_the_table_covers_the_frozen_model_keys_in_order() -> None:
    assert tuple(spec.model_key for spec in CANDIDATES) == MODEL_KEYS


@pytest.mark.parametrize("model_key", sorted(MODEL_KEYS))
def test_every_candidate_carries_the_fto_caveat_and_a_source(model_key: str) -> None:
    spec = CANDIDATES_BY_KEY[model_key]
    assert FTO_CAVEAT in spec.license_note
    assert spec.official_source_urls
    for url in spec.official_source_urls:
        assert url.startswith("https://")


@pytest.mark.parametrize("model_key", sorted(MODEL_KEYS))
def test_every_pool_entry_is_a_real_runpod_gpu_type_id(model_key: str) -> None:
    spec = CANDIDATES_BY_KEY[model_key]
    for gpu in (*spec.recommended_gpu_pool, *spec.gpu_pool_priority):
        assert gpu in RUNPOD_GPU_CATALOG, gpu


@pytest.mark.parametrize("model_key", sorted(MODEL_KEYS))
def test_every_shard_hint_states_where_it_came_from(model_key: str) -> None:
    spec = CANDIDATES_BY_KEY[model_key]
    assert spec.shard_size_hint > 0
    assert "masterplan" in spec.shard_size_hint_basis


def test_mineru_vlm_concurrency_is_the_masterplan_section_14_rule() -> None:
    spec = CANDIDATES_BY_KEY["mineru_vlm"]
    assert spec.max_concurrency_per_worker == 1
    assert spec.concurrency_policy == {"per_worker": 1, "scale": "replicas_only"}
    assert spec.concurrency_plan["scale_after_canary"] == "replicas_only"
    assert spec.historical_evidence is not None
    assert "tensor-shape" in spec.historical_evidence["incident"]


def test_mineru_pipeline_weights_come_from_pdf_extract_kit_not_a_ppocrv6_repo() -> None:
    spec = CANDIDATES_BY_KEY["mineru_pipeline"]
    assert spec.weights is not None
    assert spec.weights.repo == "opendatalab/PDF-Extract-Kit-1.0"
    # Founder decision 2026-09-03: the mineru_pipeline lane (runtime + weights) is
    # verified for research benchmark execution; the weights-level override that used
    # to downgrade it back to review_required is gone.
    assert spec.weights.license_status_override is None
    assert spec.license_status == "verified"
    assert spec.code[0].tag == "mineru-3.4.5-released"
    correction = " ".join(spec.notes)
    assert "PP-OCRv6 is not a separately versioned MinerU asset repository" in correction
    assert "models/OCR/paddleocr_torch" in correction


def test_infinity_parser2_pro_is_the_only_two_gpu_candidate() -> None:
    spec = CANDIDATES_BY_KEY["infinity_parser2_pro"]
    assert spec.official_inference_config["tensor_parallel_size"] == 2
    assert spec.gpu_min_vram_gb_value == 160
    assert all(RUNPOD_GPU_CATALOG[gpu].vram_gb >= 80 for gpu in spec.gpu_pool_priority)
    # Founder decision 2026-09-03: baked-only was an operational stall-risk choice, not
    # a licence one; bootstrap is available again behind a persistent volume cache.
    assert spec.runtime_mode_allowed == ("baked", "bootstrap")
    others = [
        other
        for other in CANDIDATES
        if other.model_key != "infinity_parser2_pro"
        and other.official_inference_config.get("tensor_parallel_size", 1) != 1
    ]
    assert others == []


def test_olmocr2_config_comes_from_the_toolkit_not_the_card_demo() -> None:
    config = CANDIDATES_BY_KEY["olmocr2"].official_inference_config
    assert config["target_longest_image_dim"] == 1288
    assert config["max_tokens"] == 8000
    assert config["temperature"] == 0.1
    assert "truncated demo" in config["note"]


def test_hpd_parsing_pins_the_official_image_and_the_fixed_prompt() -> None:
    spec = CANDIDATES_BY_KEY["hpd_parsing"]
    assert spec.container_image is not None
    assert spec.container_image.endswith("hpd-parsing-vllm:latest-nvidia-gpu")
    assert spec.official_inference_config["prompt"] == "document parsing with fork."
    assert spec.official_inference_config["env"] == {"MAX_PATCHES_WITH_RESIZE": "true"}
    assert spec.official_inference_config["attention_backend"] == "FLASHINFER"
    # The RTX 4090 is not on the official verified-hardware list.
    assert "NVIDIA GeForce RTX 4090" not in spec.gpu_pool_priority


def test_ovisocr2_pins_the_official_runtime_version() -> None:
    spec = CANDIDATES_BY_KEY["ovisocr2"]
    assert spec.runtime_version == "vllm==0.22.1"
    assert spec.official_inference_config["max_tokens"] == 16384
    assert spec.official_inference_config["temperature"] == 0.0
    assert spec.historical_evidence is not None
    assert "abnormally" in spec.historical_evidence["discrepancy"]


def test_glm_ocr_runtime_version_is_null_with_a_reason() -> None:
    spec = CANDIDATES_BY_KEY["glm_ocr"]
    assert spec.runtime_version is None
    reason = spec.extra["runtime_version_unresolved_reason"]
    assert "nightly" in reason


def test_opus_is_not_a_gpu_candidate_and_never_costs_zero() -> None:
    spec = CANDIDATES_BY_KEY["opus5_subscription"]
    assert spec.runtime_type == "subscription"
    assert spec.weights is None
    assert spec.recommended_gpu_pool == ()
    assert spec.gpu_pool_priority == ()
    assert spec.extra["license_id"] == "proprietary-anthropic-commercial-terms"
    price = spec.extra["list_price_reference"]
    assert price["input_usd_per_mtok"] == 5.0
    assert price["output_usd_per_mtok"] == 25.0
    assert "$0/page" in price["note"]


def test_bootstrap_is_denied_for_the_model_that_cannot_afford_it() -> None:
    # infinity_parser2_pro moved to ("baked", "bootstrap") by founder decision
    # 2026-09-03 (a persistent volume cache now backs the bootstrap path); hpd_parsing
    # is unaffected and stays baked-only.
    assert CANDIDATES_BY_KEY["hpd_parsing"].runtime_mode_allowed == ("baked",)


def test_every_historical_row_carries_its_scope_warning() -> None:
    for spec in CANDIDATES:
        if spec.historical_evidence is None:
            continue
        assert "scope_warning" in spec.historical_evidence
        assert spec.historical_evidence["source"].startswith("masterplan section")
