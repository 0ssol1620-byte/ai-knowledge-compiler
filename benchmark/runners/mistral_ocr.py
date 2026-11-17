"""Mistral OCR through the AKC external-runner protocol. The model id is a required parameter
and must be one of the GA ids listed here exactly; the retired ``mistral-ocr-4-0``, every
alias and every other spelling are refused before any call."""

from __future__ import annotations

from typing import Any

from .base import PROVIDER_CREDENTIAL, RunnerConfig, RunnerUnavailable, external_exchange, guarded

PROVIDER = "mistral_ocr_4"
# Exact GA ids (docs.mistral.ai/getting-started/models snapshot 6155ede1..., intake register).
# A new GA id is added here by a reviewed change, never matched by a pattern; mistral-ocr-4-0
# was retired by Mistral on 2026-09-30 and is therefore absent.
GA_MODEL_IDS = frozenset({"mistral-ocr-4-1"})


def config(*, revision: str | None = None, model: str | None = None) -> dict[str, Any]:
    if revision:
        raise RunnerUnavailable("a hosted model is pinned by model id; revision must be empty")
    if not isinstance(model, str) or not model:
        raise RunnerUnavailable("mistral runner requires an explicit model id")
    if model not in GA_MODEL_IDS:
        raise RunnerUnavailable("mistral model id is an alias or not a pinned GA id")
    return {"provider": PROVIDER, "model": model, "protocol": "akc_external_runner_v1"}


def run(
    case: dict[str, Any],
    *,
    endpoint: str | None,
    revision: str | None = None,
    allow_network: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    def body(token: str | None) -> dict[str, Any]:  # after the door, inside the exit guard
        pinned = config(revision=revision, model=model)
        run_config = RunnerConfig(PROVIDER, pinned["model"], endpoint, allow_network)
        return external_exchange(run_config, case, token)

    return guarded(PROVIDER_CREDENTIAL, endpoint, PROVIDER, case, body)
