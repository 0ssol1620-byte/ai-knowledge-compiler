"""Candidate model registry for the knowledge Arena.

Rows are CANDIDATES. Nothing here says a model can do a task: every
``capabilities`` field starts ``None`` and only an Arena receipt may fill it
(CLAUDE.md: never infer capability from a name). Code, weights, dataset and
hosted-API terms are four separate licence records; clearing one clears none
of the others, and none of them is patent freedom to operate.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import httpx
from arena.provider.safety import utc_now_iso, write_json_atomic

from karena import CAMPAIGN_ID, NAMESPACE_ROOT

__all__ = ["REGISTRY_PATH", "RegistryError", "load_registry", "refresh_registry", "validate_rows"]

REGISTRY_PATH: Final = NAMESPACE_ROOT / "config" / "model_candidates.json"
LICENCE_KINDS: Final = ("code", "weights", "dataset", "hosted_api")
CAPABILITIES: Final = (
    "text_input",
    "korean_text",
    "json_schema_output",
    "max_context_tokens_measured",
    "doc_type",
    "schema_induction",
    "typed_extraction",
    "grounded_answer",
)
ROLES: Final = frozenset({"CANDIDATE", "REFERENCE_ONLY"})
VLLM_IMAGE: Final = (
    "vllm/vllm-openai:v0.19.0-ubuntu2404@"
    "sha256:69234fc31ff1d5e1687b2f06bba39e0f8c58dd4755f0508dbe0595cd3692b851"
)
VLLM_LICENCE_URL: Final = "https://raw.githubusercontent.com/vllm-project/vllm/v0.19.0/LICENSE"
#: Chosen for licence class and size (fits one 24-48 GB GPU at bf16), not for any
#: claimed skill. Qwen3-8B is the Stage 0 smoke candidate only because its
#: architecture already runs on the pinned vLLM image.
CANDIDATE_IDS: Final = (
    ("qwen3_8b", "Qwen/Qwen3-8B"),
    ("qwen3_5_9b", "Qwen/Qwen3.5-9B"),
    ("mistral_small_3_2_24b", "mistralai/Mistral-Small-3.2-24B-Instruct-2506"),
    ("phi_4", "microsoft/phi-4"),
    ("gemma_3_12b_it", "google/gemma-3-12b-it"),
)
NOT_FTO: Final = (
    "NOT_ASSESSED: an open-source licence is copyright permission from the publisher, not "
    "patent freedom to operate"
)


class RegistryError(ValueError):
    pass


def _hf(model_id: str, client: httpx.Client) -> dict[str, Any]:
    response = client.get(f"https://huggingface.co/api/models/{model_id}")
    response.raise_for_status()
    body: dict[str, Any] = response.json()
    return body


def _row(key: str, model_id: str, meta: Mapping[str, Any], vllm_licence: str) -> dict[str, Any]:
    sha = str(meta["sha"])
    card = meta.get("cardData") or {}
    files = sorted(s["rfilename"] for s in meta.get("siblings", []))
    licence_files = [f for f in files if f.upper().startswith(("LICENSE", "LICENCE", "NOTICE"))]
    gated = meta.get("gated")
    declared = card.get("license")
    return {
        "registry_id": f"karena:{key}",
        "model_key": key,
        "role": "CANDIDATE",
        "exact_model_id": model_id,
        "exact_revision": sha,
        "revision_resolved_at": utc_now_iso(),
        "revision_source": f"https://huggingface.co/api/models/{model_id}",
        "declared_parameter_count": (meta.get("safetensors") or {}).get("total"),
        "gated": gated,
        "input_mode": "TEXT (chat completion over OpenAI-compatible vLLM); pinned per run",
        "capabilities": dict.fromkeys(CAPABILITIES),
        "capability_receipts": [],
        "licences": {
            "code": {
                "status": "DECLARED_NOT_REVIEWED",
                "serving_runtime": f"{VLLM_IMAGE} (vLLM; {vllm_licence})",
                "custom_code_in_model_repo": [f for f in files if f.endswith(".py")],
                "source": VLLM_LICENCE_URL,
            },
            "weights": {
                "status": (
                    "DECLARED_NOT_REVIEWED"
                    if declared in {"apache-2.0", "mit"} and not gated
                    else "CUSTOM_OR_GATED_TERMS_REVIEW_REQUIRED"
                ),
                "declared_licence": declared,
                "declared_licence_name": card.get("license_name"),
                "licence_files": licence_files,
                "source": f"https://huggingface.co/{model_id}/tree/{sha}",
            },
            "dataset": {
                "status": "UNDISCLOSED_BY_PUBLISHER" if not card.get("datasets") else "DECLARED",
                "declared_datasets": card.get("datasets"),
                "note": "training data terms are separate from the weights licence",
            },
            "hosted_api": {
                "status": "NOT_USED",
                "note": "self-hosted weights on RunPod; no hosted-API arm (founder F-5/F-14)",
            },
        },
        "patent_fto": NOT_FTO,
        "serving": {"image": VLLM_IMAGE, "min_cuda_version": "12.9"},
    }


def reference_row() -> dict[str, Any]:
    return {
        "registry_id": "karena:opus_subscription_reference",
        "model_key": "opus_subscription_reference",
        "role": "REFERENCE_ONLY",
        "exact_model_id": None,
        "exact_revision": None,
        "pin_at_run": "the exact model id the Claude Code CLI reports is written into each receipt",
        "input_mode": "TEXT via `claude -p` on the founder's subscription OAuth (arena.opus lane)",
        "rules": [
            "reference arm only: never a routing candidate, never compared as a same-condition arm",
            "subscription OAuth only; no API key; no automatic switch to another model or the API",
            "public corpus only; stops at the subscription limit and does not auto-resume",
        ],
        "capabilities": dict.fromkeys(CAPABILITIES),
        "capability_receipts": [],
        "licences": {
            "code": {"status": "NOT_APPLICABLE", "note": "closed model; CLI is a client"},
            "weights": {"status": "NOT_APPLICABLE", "note": "weights not distributed"},
            "dataset": {"status": "UNDISCLOSED_BY_PUBLISHER"},
            "hosted_api": {
                "status": "SUBSCRIPTION_TERMS_NOT_REVIEWED_FOR_EVALUATION",
                "note": "consumer subscription surface, not the API; F-5/F-14 decide any API arm",
            },
        },
        "patent_fto": NOT_FTO,
        "serving": None,
    }


def refresh_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        vllm = client.get(VLLM_LICENCE_URL)
        vllm.raise_for_status()
        first = next((line.strip() for line in vllm.text.splitlines() if line.strip()), "")
        vllm_licence = f"LICENSE at v0.19.0 begins {first!r}"
        rows = [
            _row(key, model_id, _hf(model_id, client), vllm_licence)
            for key, model_id in CANDIDATE_IDS
        ]
    rows.append(reference_row())
    document = {
        "schema": "tavonel.karena.model_candidates.v1",
        "campaign_id": CAMPAIGN_ID,
        "resolved_at": utc_now_iso(),
        "rows": rows,
    }
    validate_rows(rows)
    write_json_atomic(path, document, context="model candidates")
    return document


def validate_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    for row in rows:
        name = row.get("registry_id")
        if row.get("role") not in ROLES:
            raise RegistryError(f"{name}: role must be one of {sorted(ROLES)}")
        licences = row.get("licences") or {}
        missing = [kind for kind in LICENCE_KINDS if not (licences.get(kind) or {}).get("status")]
        if missing:
            raise RegistryError(f"{name}: licence record(s) missing {missing}; each is separate")
        capabilities = row.get("capabilities") or {}
        claimed = [k for k, v in capabilities.items() if v is not None]
        if claimed and not row.get("capability_receipts"):
            raise RegistryError(f"{name}: capabilities {claimed} set without an Arena receipt")
        if row.get("role") == "CANDIDATE" and not (
            row.get("exact_model_id") and row.get("exact_revision")
        ):
            raise RegistryError(f"{name}: a candidate must pin exact model id and revision")


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = document["rows"]
    validate_rows(rows)
    return {row["model_key"]: row for row in rows}
