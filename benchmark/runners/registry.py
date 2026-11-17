"""Explicit benchmark-provider registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .deepseek_ocr import run as run_deepseek_ocr
from .gemini_api import run as run_gemini_api
from .hpd_parsing import run as run_hpd_parsing
from .infinity_parser2_flash import run as run_infinity_parser2_flash
from .infinity_parser2_pro import run as run_infinity_parser2_pro
from .mineru import run as run_mineru
from .minicpm_ocr import run as run_minicpm_ocr
from .mistral_ocr import run as run_mistral_ocr
from .nemotron_parse import run as run_nemotron_parse
from .olmocr import run as run_olmocr
from .ovis_ocr2 import run as run_ovis_ocr2
from .paddleocr_vl import run as run_paddleocr_vl
from .teleocr import run as run_teleocr
from .unlimited_ocr import run as run_unlimited_ocr

type ExternalRunner = Callable[..., dict[str, Any]]

EXTERNAL_RUNNERS: Mapping[str, ExternalRunner] = {
    "deepseek_ocr_2": run_deepseek_ocr,
    "gemini_api": run_gemini_api,
    "hpd_parsing_1b": run_hpd_parsing,
    "infinity_parser2_flash": run_infinity_parser2_flash,
    "infinity_parser2_pro": run_infinity_parser2_pro,
    "mineru": run_mineru,
    "minicpm_ocr_1": run_minicpm_ocr,
    "mistral_ocr_4": run_mistral_ocr,
    "nemotron_parse_3_5": run_nemotron_parse,
    "olmocr_2": run_olmocr,
    "ovis_ocr2": run_ovis_ocr2,
    "paddleocr_vl_1_6": run_paddleocr_vl,
    "teleocr": run_teleocr,
    "unlimited_ocr": run_unlimited_ocr,
}
