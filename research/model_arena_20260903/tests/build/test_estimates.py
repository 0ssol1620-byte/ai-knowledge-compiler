"""estimates.py: every GPU model_key is covered, and nothing invents a
positive number where the model itself says the size is unmeasured."""

from __future__ import annotations

from arena.constants import GPU_MODEL_KEYS
from estimates import PER_MODEL_ESTIMATES


def test_every_gpu_model_key_has_an_estimate() -> None:
    assert set(PER_MODEL_ESTIMATES) == set(GPU_MODEL_KEYS)


def test_every_estimate_declares_a_confidence() -> None:
    for model_key, estimate in PER_MODEL_ESTIMATES.items():
        assert estimate.estimate_confidence in {"low", "unmeasured_placeholder"}, model_key


def test_every_estimate_has_at_least_the_base_risk() -> None:
    for model_key, estimate in PER_MODEL_ESTIMATES.items():
        assert len(estimate.risks) >= 1, model_key
        assert any("not measurements" in risk for risk in estimate.risks), (
            f"{model_key} is missing the standard unmeasured-estimate disclaimer"
        )


def test_hpd_parsing_weights_size_is_null_with_a_reason() -> None:
    """hpd_parsing's weights are baked into the official base image; this
    module must not invent a standalone weights size for them."""
    estimate = PER_MODEL_ESTIMATES["hpd_parsing"]
    assert estimate.weights_size_gb is None
    assert "already inside" in estimate.weights_size_reason


def test_infinity_parser2_pro_uses_volume_cache_sized_weights() -> None:
    estimate = PER_MODEL_ESTIMATES["infinity_parser2_pro"]
    assert estimate.weights_size_gb is not None
    assert estimate.weights_size_gb > 50  # this is the large one, off-image
