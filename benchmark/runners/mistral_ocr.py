"""Mistral OCR through the AKC external-runner protocol. The GA model id is a required
parameter; the retired ``mistral-ocr-4-0`` and every alias are refused before any call."""

from __future__ import annotations

import re
from typing import Any

from .base import RunnerConfig, RunnerUnavailable, run_external

PROVIDER = "mistral_ocr_4"
RETIRED = frozenset({"mistral-ocr-4-0"})  # retired by Mistral on 2026-09-30
_PINNED = re.compile(r"^mistral-ocr-\d+-\d+$")  # family-major-minor; no -latest, no labs-


def config(*, revision: str | None = None, model: str | None = None) -> dict[str, Any]:
    if revision:
        raise RunnerUnavailable("a hosted model is pinned by model id; revision must be empty")
    if not isinstance(model, str) or not model:
        raise RunnerUnavailable("mistral runner requires an explicit model id")
    if model in RETIRED:
        raise RunnerUnavailable(f"mistral model id {model!r} is retired")
    if _PINNED.fullmatch(model) is None:
        raise RunnerUnavailable(f"mistral model id {model!r} is an alias or not a pinned GA id")
    return {"provider": PROVIDER, "model": model, "protocol": "akc_external_runner_v1"}


def run(
    case: dict[str, Any],
    *,
    endpoint: str | None,
    revision: str | None = None,
    allow_network: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    pinned = config(revision=revision, model=model)
    return run_external(RunnerConfig(PROVIDER, pinned["model"], endpoint, allow_network), case)
