"""Explicit benchmark-provider registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from . import (
    gemini_api,
    minicpm_ocr,
    mistral_ocr,
    nemotron_parse,
    ovis_ocr2,
    ovis_ocr3,
    paddleocr_vl_vllm,
    teleocr,
    xiaomi_ocr,
)
from .deepseek_ocr import run as run_deepseek_ocr
from .hpd_parsing import run as run_hpd_parsing
from .infinity_parser2_flash import run as run_infinity_parser2_flash
from .infinity_parser2_pro import run as run_infinity_parser2_pro
from .mineru import run as run_mineru
from .olmocr import run as run_olmocr
from .paddleocr_vl import run as run_paddleocr_vl
from .unlimited_ocr import run as run_unlimited_ocr

type ExternalRunner = Callable[..., dict[str, Any]]

EXTERNAL_RUNNERS: Mapping[str, ExternalRunner] = {
    "deepseek_ocr_2": run_deepseek_ocr,
    "gemini_api": gemini_api.run,
    "hpd_parsing_1b": run_hpd_parsing,
    "infinity_parser2_flash": run_infinity_parser2_flash,
    "infinity_parser2_pro": run_infinity_parser2_pro,
    "mineru": run_mineru,
    "minicpm_ocr_1": minicpm_ocr.run,
    "mistral_ocr_4": mistral_ocr.run,
    "nemotron_parse_3_5": nemotron_parse.run,
    "olmocr_2": run_olmocr,
    "ovis_ocr2": ovis_ocr2.run,
    "ovis_ocr3": ovis_ocr3.run,
    "paddleocr_vl_1_6": run_paddleocr_vl,
    "paddleocr_vl_1_6_vllm": paddleocr_vl_vllm.run,
    "teleocr": teleocr.run,
    "unlimited_ocr": run_unlimited_ocr,
    "xiaomi_ocr_0": xiaomi_ocr.run,
}

# Providers whose prompt, generation settings and identity are pinned in the runner: the
# document each returns (keyword arguments: revision, plus model and options for an API) is
# what a screen candidate's config_sha256 must digest to. API providers take ``model``.
RUNNER_CONFIGS: Mapping[str, Callable[..., dict[str, Any]]] = {
    "gemini_api": gemini_api.config,
    "minicpm_ocr_1": minicpm_ocr.config,
    "mistral_ocr_4": mistral_ocr.config,
    "nemotron_parse_3_5": nemotron_parse.config,
    "ovis_ocr2": ovis_ocr2.config,
    "ovis_ocr3": ovis_ocr3.config,
    "paddleocr_vl_1_6_vllm": paddleocr_vl_vllm.config,
    "teleocr": teleocr.config,
    "xiaomi_ocr_0": xiaomi_ocr.config,
}
API_PROVIDERS = frozenset({"gemini_api", "mistral_ocr_4"})
