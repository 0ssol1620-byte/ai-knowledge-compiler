"""Model resolution: parsing real payloads, and every way it must fail closed."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from arena.constants import GPU_MODEL_KEYS, OPUS_DISPLAY_NAME
from arena.registry.candidates import CANDIDATES_BY_KEY
from arena.registry.errors import RegistryError, SourceUnavailableError
from arena.registry.http import FixtureStore, JsonFetcher
from arena.registry.models import (
    HEX40,
    ResolvedWeights,
    build_model_record,
    estimate_min_vram_gb,
    resolve_hf_weights,
)
from arena.registry.serialize import canonical_sha256


class _StaticFetcher:
    """Serves one payload for any URL, so a mutated payload can be exercised."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def get_json(self, url: str) -> Any:
        return self._payload


def _weights_for(model_key: str) -> Any:
    spec = CANDIDATES_BY_KEY[model_key]
    assert spec.weights is not None
    return spec.weights


# --------------------------------------------------------------------------
# Happy path against the recorded official payloads.
# --------------------------------------------------------------------------


def test_ovisocr2_resolves_to_a_pinned_revision_and_a_hashed_largest_file(
    offline_fetcher: JsonFetcher,
) -> None:
    resolved = resolve_hf_weights(offline_fetcher, _weights_for("ovisocr2"))
    assert HEX40.match(resolved.revision)
    assert resolved.license_id == "apache-2.0"
    assert resolved.largest_file == "model.safetensors"
    assert resolved.largest_file_sha256 is not None
    assert resolved.largest_file_sha256.startswith("sha256:")
    assert len(resolved.largest_file_sha256) == len("sha256:") + 64
    assert resolved.size_bytes is not None and resolved.size_bytes > 0
    assert resolved.gated is False
    assert resolved.unresolved_reasons == ()


@pytest.mark.parametrize("model_key", sorted(GPU_MODEL_KEYS))
def test_every_gpu_model_has_a_recorded_payload_with_a_40_hex_sha(
    model_key: str, offline_fetcher: JsonFetcher
) -> None:
    resolved = resolve_hf_weights(offline_fetcher, _weights_for(model_key))
    assert HEX40.match(resolved.revision), f"{model_key} revision is not 40-hex"
    assert resolved.total_weight_bytes > 0


def test_the_largest_file_is_the_largest_weight_file_not_the_largest_file(
    offline_fetcher: JsonFetcher,
) -> None:
    # baidu/Unlimited-OCR publishes an 82 MB demo GIF; the pin must ignore it.
    resolved = resolve_hf_weights(offline_fetcher, _weights_for("unlimited_ocr"))
    assert resolved.largest_file is not None
    assert resolved.largest_file.endswith(".safetensors")


# --------------------------------------------------------------------------
# Licence failure path: a repository with no LICENSE is not reusable.
# --------------------------------------------------------------------------


def test_repository_without_a_declared_licence_records_an_unresolved_reason(
    offline_fetcher: JsonFetcher,
) -> None:
    resolved = resolve_hf_weights(offline_fetcher, _weights_for("mineru_pipeline"))
    assert resolved.license_id is None
    assert any("declares no cardData.license" in reason for reason in resolved.unresolved_reasons)


def test_licenceless_weights_repo_still_carries_the_mineru_licence_id(
    offline_fetcher: JsonFetcher,
) -> None:
    """mineru_pipeline's weight repo (PDF-Extract-Kit-1.0) has no LICENSE of its own,

    so `license_id` would otherwise fall back to None ("unresolved"). Founder
    decision 2026-09-03 clears the lane as a whole under the MinerU Open Source
    License, so `CandidateSpec.extra["license_id"]` overrides the unresolved weights
    id and `license_status` is "verified" rather than a fail-safe "review_required"
    (receipts/registry-updates/license-mineru_pipeline.json).
    """
    spec = CANDIDATES_BY_KEY["mineru_pipeline"]
    weights = resolve_hf_weights(offline_fetcher, _weights_for("mineru_pipeline"))
    assert weights.license_id is None  # the weights repo itself still declares none
    record = build_model_record(
        spec,
        weights=weights,
        code=[
            {
                "repo": "opendatalab/MinerU",
                "role": "official_runtime",
                "revision": "0" * 40,
                "tag": "mineru-3.4.5-released",
            }
        ],
        resolved_at="2026-09-03T00:00:00Z",
        resolution_method="test",
    )
    assert record["license_detail"]["status"] == "verified"
    assert record["license_detail"]["id"] == "LicenseRef-MinerU-Open-Source-License"
    assert record["license"] == "LicenseRef-MinerU-Open-Source-License"
    assert "readable but not reusable" in record["license_detail"]["notes"]
    assert "not patent freedom to operate" in record["license_detail"]["notes"]


def test_a_repo_whose_licence_disappears_downgrades_the_status(
    ovisocr2_payload: Any,
) -> None:
    payload = copy.deepcopy(ovisocr2_payload)
    payload["cardData"] = {}
    resolved = resolve_hf_weights(_StaticFetcher(payload), _weights_for("ovisocr2"))
    assert resolved.license_id is None
    record = build_model_record(
        CANDIDATES_BY_KEY["ovisocr2"],
        weights=resolved,
        code=[],
        resolved_at="2026-09-03T00:00:00Z",
        resolution_method="test",
    )
    # The candidate table says approved because upstream declared apache-2.0; when
    # the declaration is gone the record must carry that as an unresolved reason so
    # a human sees the contradiction rather than a silently approved licence.
    assert record["license_detail"]["id"] is None
    assert record["license"].startswith("unresolved:")
    assert any("grants no reuse right" in reason for reason in record["unresolved"])


# --------------------------------------------------------------------------
# Revision-format failure paths.
# --------------------------------------------------------------------------


def test_short_sha_is_rejected(ovisocr2_payload: Any) -> None:
    payload = copy.deepcopy(ovisocr2_payload)
    payload["sha"] = "1fc9221"
    with pytest.raises(SourceUnavailableError, match="not a 40-hex commit id"):
        resolve_hf_weights(_StaticFetcher(payload), _weights_for("ovisocr2"))


def test_uppercase_sha_is_rejected(ovisocr2_payload: Any) -> None:
    payload = copy.deepcopy(ovisocr2_payload)
    payload["sha"] = "1FC9221B7823A371D6E97F92D527CC847E24E107"
    with pytest.raises(SourceUnavailableError, match="not a 40-hex commit id"):
        resolve_hf_weights(_StaticFetcher(payload), _weights_for("ovisocr2"))


def test_missing_sha_is_rejected(ovisocr2_payload: Any) -> None:
    payload = copy.deepcopy(ovisocr2_payload)
    payload.pop("sha")
    with pytest.raises(SourceUnavailableError, match="did not carry a usable 'sha'"):
        resolve_hf_weights(_StaticFetcher(payload), _weights_for("ovisocr2"))


def test_missing_siblings_is_rejected(ovisocr2_payload: Any) -> None:
    payload = copy.deepcopy(ovisocr2_payload)
    payload["siblings"] = []
    with pytest.raises(SourceUnavailableError, match="blobs=true"):
        resolve_hf_weights(_StaticFetcher(payload), _weights_for("ovisocr2"))


def test_non_object_response_is_rejected() -> None:
    with pytest.raises(SourceUnavailableError, match="did not return a model object"):
        resolve_hf_weights(_StaticFetcher(["not", "a", "model"]), _weights_for("ovisocr2"))


def test_weight_file_without_an_lfs_hash_is_reported_not_invented(
    ovisocr2_payload: Any,
) -> None:
    payload = copy.deepcopy(ovisocr2_payload)
    for sibling in payload["siblings"]:
        if sibling["rfilename"] == "model.safetensors":
            sibling.pop("lfs", None)
    resolved = resolve_hf_weights(_StaticFetcher(payload), _weights_for("ovisocr2"))
    assert resolved.largest_file_sha256 is None
    assert any("no sha256" in reason for reason in resolved.unresolved_reasons)


# --------------------------------------------------------------------------
# VRAM sizing.
# --------------------------------------------------------------------------


def _fake_weights(total_bytes: int) -> ResolvedWeights:
    return ResolvedWeights(
        repo="x/y",
        revision="0" * 40,
        last_modified=None,
        license_id="mit",
        largest_file="model.safetensors",
        largest_file_sha256="sha256:" + "0" * 64,
        size_bytes=total_bytes,
        total_weight_bytes=total_bytes,
        file_count=1,
        gated=False,
        unresolved_reasons=(),
    )


@pytest.mark.parametrize(
    ("weights_gb", "expected_tier"),
    [(1.71, 24), (10.06, 24), (20.0, 48), (40.0, 80), (55.0, 96)],
)
def test_vram_sizing_rule_rounds_up_to_a_catalog_tier(
    weights_gb: float, expected_tier: int
) -> None:
    spec = CANDIDATES_BY_KEY["ovisocr2"]
    result = estimate_min_vram_gb(spec, _fake_weights(int(weights_gb * 1e9)))
    assert result["value"] == expected_tier
    assert result["estimated"] is True
    assert "x 1.6 + 4 GB headroom" in result["basis"]


def test_vram_sizing_fails_closed_above_every_catalog_tier() -> None:
    spec = CANDIDATES_BY_KEY["ovisocr2"]
    with pytest.raises(RegistryError, match="above every catalog tier"):
        estimate_min_vram_gb(spec, _fake_weights(200 * 10**9))


def test_explicit_vram_override_carries_its_basis() -> None:
    spec = CANDIDATES_BY_KEY["infinity_parser2_pro"]
    result = estimate_min_vram_gb(spec, None)
    assert result["value"] == 160
    assert "tensor-parallel-size 2" in result["basis"]


def test_unresolvable_vram_is_null_with_a_reason_not_zero() -> None:
    spec = CANDIDATES_BY_KEY["ovisocr2"]
    result = estimate_min_vram_gb(spec, _fake_weights(0))
    assert result["value"] is None
    assert result["basis"].startswith("unresolved:")


# --------------------------------------------------------------------------
# Record shape.
# --------------------------------------------------------------------------


def test_opus_record_has_no_repo_and_keeps_the_frozen_display_name() -> None:
    record = build_model_record(
        CANDIDATES_BY_KEY["opus5_subscription"],
        weights=None,
        code=[],
        resolved_at="2026-09-03T00:00:00Z",
        resolution_method="test",
    )
    assert record["repo"] is None
    assert record["weights"] is None
    assert record["display_name"] == OPUS_DISPLAY_NAME
    assert record["revision"] == "claude-opus-5 (confirm via lane D probe)"
    assert record["runtime_type"] == "subscription"
    assert record["list_price_reference"]["input_usd_per_mtok"] == 5.0
    assert record["list_price_reference"]["output_usd_per_mtok"] == 25.0
    assert record["full_run_eligible"] is False
    assert record["canary_status"] == "PENDING"


def test_inference_config_hash_is_over_canonical_json(
    offline_fetcher: JsonFetcher,
) -> None:
    spec = CANDIDATES_BY_KEY["ovisocr2"]
    weights = resolve_hf_weights(offline_fetcher, _weights_for("ovisocr2"))
    record = build_model_record(
        spec,
        weights=weights,
        code=[],
        resolved_at="2026-09-03T00:00:00Z",
        resolution_method="test",
    )
    assert record["official_inference_config_sha256"] == canonical_sha256(
        record["official_inference_config"]
    )


def test_revision_change_detection_against_the_2026_08_registry(
    offline_fetcher: JsonFetcher,
) -> None:
    spec = CANDIDATES_BY_KEY["deepseek_ocr2"]
    weights = resolve_hf_weights(offline_fetcher, _weights_for("deepseek_ocr2"))
    record = build_model_record(
        spec,
        weights=weights,
        code=[],
        resolved_at="2026-09-03T00:00:00Z",
        resolution_method="test",
    )
    assert record["previous_registry_revision"] == "aaa02f3811945a91062062994c5c4a3f4c0af2b0"
    assert record["revision_changed_since_2026_08"] is (
        record["revision"] != record["previous_registry_revision"]
    )


def test_an_unknown_gpu_type_id_fails_closed(offline_fetcher: JsonFetcher) -> None:
    from dataclasses import replace

    spec = replace(CANDIDATES_BY_KEY["ovisocr2"], gpu_pool_priority=("NVIDIA MADE UP 9000",))
    weights = resolve_hf_weights(offline_fetcher, _weights_for("ovisocr2"))
    with pytest.raises(RegistryError, match="outside the catalog"):
        build_model_record(
            spec,
            weights=weights,
            code=[],
            resolved_at="2026-09-03T00:00:00Z",
            resolution_method="test",
        )


def test_gpu_model_without_weights_fails_closed() -> None:
    from dataclasses import replace

    spec = replace(CANDIDATES_BY_KEY["ovisocr2"], weights=None)
    with pytest.raises(RegistryError, match="no weights spec"):
        build_model_record(
            spec,
            weights=None,
            code=[],
            resolved_at="2026-09-03T00:00:00Z",
            resolution_method="test",
        )


def test_fixture_directory_covers_every_weight_repository(
    fixture_store: FixtureStore,
) -> None:
    from arena.registry.models import HF_API

    for key in GPU_MODEL_KEYS:
        spec = CANDIDATES_BY_KEY[key]
        assert spec.weights is not None
        assert fixture_store.has(HF_API.format(repo=spec.weights.repo)), key
