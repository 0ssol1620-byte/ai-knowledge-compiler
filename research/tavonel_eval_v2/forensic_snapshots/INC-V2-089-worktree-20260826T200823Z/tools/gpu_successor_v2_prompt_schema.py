#!/usr/bin/env python3
"""Prospective three-arm prompt contract for GPU successor V2.

The two estimands are deliberately separated: CURRENT_TYPED versus
STALE_TYPED measures currency, while CURRENT_TYPED versus CURRENT_TEXT_ONLY
measures representation lift at the same revision.  Arm names never enter
the model prompt; only the pre-bound context differs.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for sub in ("endpoint", "source_fact_ir", "tools"):
    path = str(NS / sub)
    if path not in sys.path:
        sys.path.insert(0, path)

import successor_prompt_schema as v1  # noqa: E402

ARM_CURRENT_TYPED = "CURRENT_TYPED"
ARM_STALE_TYPED = "STALE_TYPED"
ARM_CURRENT_TEXT_ONLY = "CURRENT_TEXT_ONLY"
ARMS = (ARM_CURRENT_TYPED, ARM_STALE_TYPED, ARM_CURRENT_TEXT_ONLY)

MODEL_REPOSITORY = v1.MODEL_REPOSITORY
MODEL_REVISION = v1.MODEL_REVISION
DECODING = dict(v1.DECODING)
MAX_NEW_TOKENS = v1.MAX_NEW_TOKENS
CONTEXT_BUDGET_TOKENS = v1.CONTEXT_BUDGET_TOKENS
SYSTEM_PROMPT = v1.SYSTEM_PROMPT
QUESTION_FRAME = v1.QUESTION_FRAME
QUESTION_BY_KIND = dict(v1.QUESTION_BY_KIND)


@dataclass(frozen=True)
class ArmRequest:
    arm: str
    question: str
    kind: str
    model_repository: str
    model_revision: str
    decoding: dict[str, Any]
    max_new_tokens: int
    context_budget_tokens: int
    template_digest: str
    context_blocks: tuple[str, ...]
    system_prompt: str
    user_prompt: str
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "question": self.question,
            "kind": self.kind,
            "model_repository": self.model_repository,
            "model_revision": self.model_revision,
            "decoding": self.decoding,
            "max_new_tokens": self.max_new_tokens,
            "context_budget_tokens": self.context_budget_tokens,
            "template_digest": self.template_digest,
            "context_blocks": list(self.context_blocks),
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
            "extra": self.extra,
        }


IDENTICAL_FIELDS = (
    "question",
    "kind",
    "model_repository",
    "model_revision",
    "decoding",
    "max_new_tokens",
    "context_budget_tokens",
    "template_digest",
    "system_prompt",
)


def prompt_template_digest() -> str:
    body = SYSTEM_PROMPT + "\x00" + QUESTION_FRAME
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


def build_arm_request(
    *, arm: str, kind: str, representation: Any, context_blocks: list[str] | tuple[str, ...]
) -> ArmRequest:
    if arm not in ARMS:
        raise ValueError(f"unknown V2 arm {arm!r}")
    question = v1.question_for_fact(kind, representation)
    v1.assert_no_forbidden_language(SYSTEM_PROMPT)
    v1.assert_no_forbidden_language(question)
    sources = "\n\n".join(f"[{index + 1}] {block}" for index, block in enumerate(context_blocks))
    return ArmRequest(
        arm=arm,
        question=question,
        kind=kind,
        model_repository=MODEL_REPOSITORY,
        model_revision=MODEL_REVISION,
        decoding=dict(DECODING),
        max_new_tokens=MAX_NEW_TOKENS,
        context_budget_tokens=CONTEXT_BUDGET_TOKENS,
        template_digest=prompt_template_digest(),
        context_blocks=tuple(context_blocks),
        system_prompt=SYSTEM_PROMPT,
        user_prompt=QUESTION_FRAME.format(question=question, sources=sources),
    )


def assert_arms_identical_except_context(a: ArmRequest, b: ArmRequest) -> dict[str, Any]:
    mismatches = {
        name: {"a": getattr(a, name), "b": getattr(b, name)}
        for name in IDENTICAL_FIELDS
        if getattr(a, name) != getattr(b, name)
    }
    return {
        "compared_fields": list(IDENTICAL_FIELDS),
        "mismatches": mismatches,
        "identical_except_context": not mismatches,
    }


def assert_all_arms_identical_except_context(
    requests: dict[str, ArmRequest],
) -> dict[str, Any]:
    if set(requests) != set(ARMS):
        raise ValueError("all and only the three V2 arms are required")
    pairs = (
        (ARM_CURRENT_TYPED, ARM_STALE_TYPED),
        (ARM_CURRENT_TYPED, ARM_CURRENT_TEXT_ONLY),
        (ARM_STALE_TYPED, ARM_CURRENT_TEXT_ONLY),
    )
    checks = {
        f"{left}__{right}": assert_arms_identical_except_context(requests[left], requests[right])
        for left, right in pairs
    }
    return {
        "pairs": checks,
        "identical_except_context": all(
            check["identical_except_context"] for check in checks.values()
        ),
    }


def frozen_contract() -> dict[str, Any]:
    return {
        "schema": "tavonel.v2.gpu_successor_prompt_schema.v2",
        "arms": list(ARMS),
        "estimands": {
            "currency": [ARM_CURRENT_TYPED, ARM_STALE_TYPED],
            "representation": [ARM_CURRENT_TYPED, ARM_CURRENT_TEXT_ONLY],
        },
        "model": {"repository": MODEL_REPOSITORY, "revision": MODEL_REVISION},
        "decoding": DECODING,
        "max_new_tokens": MAX_NEW_TOKENS,
        "context_budget_tokens": CONTEXT_BUDGET_TOKENS,
        "prompt_template_digest": prompt_template_digest(),
        "question_by_kind": dict(sorted(QUESTION_BY_KIND.items())),
        "question_selection": "one SHA-256-selected eligible fact per lineage",
    }


def schema_digest() -> str:
    body = json.dumps(frozen_contract(), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


__all__ = [
    "ARMS",
    "ARM_CURRENT_TEXT_ONLY",
    "ARM_CURRENT_TYPED",
    "ARM_STALE_TYPED",
    "CONTEXT_BUDGET_TOKENS",
    "DECODING",
    "MAX_NEW_TOKENS",
    "MODEL_REPOSITORY",
    "MODEL_REVISION",
    "ArmRequest",
    "assert_all_arms_identical_except_context",
    "build_arm_request",
    "schema_digest",
]
