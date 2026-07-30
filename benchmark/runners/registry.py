"""Explicit benchmark-provider registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .deepseek_ocr import run as run_deepseek_ocr
from .hpd_parsing import run as run_hpd_parsing
from .infinity_parser2_flash import run as run_infinity_parser2_flash
from .infinity_parser2_pro import run as run_infinity_parser2_pro
from .mineru import run as run_mineru
from .mistral_ocr import run as run_mistral_ocr
from .olmocr import run as run_olmocr
from .paddleocr_vl import run as run_paddleocr_vl
from .unlimited_ocr import run as run_unlimited_ocr

type ExternalRunner = Callable[..., dict[str, Any]]

EXTERNAL_RUNNERS: Mapping[str, ExternalRunner] = {
    "deepseek_ocr_2": run_deepseek_ocr,
    "hpd_parsing_1b": run_hpd_parsing,
    "infinity_parser2_flash": run_infinity_parser2_flash,
    "infinity_parser2_pro": run_infinity_parser2_pro,
    "mineru": run_mineru,
    "mistral_ocr_4": run_mistral_ocr,
    "olmocr_2": run_olmocr,
    "paddleocr_vl_1_6": run_paddleocr_vl,
    "unlimited_ocr": run_unlimited_ocr,
}
