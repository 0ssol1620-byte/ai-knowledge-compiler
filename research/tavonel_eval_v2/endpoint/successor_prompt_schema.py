"""GPU_SUCCESSOR_STUDY_V1's frozen input/prompt contract.

This is the successor study's arm design (protocol section 3), question
templates (section 4's typed-fact kinds), scorer classes (section 7) and
context budget, made inspectable and hashable so they can be sealed into a
receipt before any model output exists. It declares the contract; it does not
run a model and it does not build a real cohort.

Two rules this module exists to enforce mechanically, not just in prose:

* **only the served context may differ between arms.** Model, revision,
  decoding, ``max_new_tokens``, the prompt template and the context token
  budget are single frozen constants, not per-arm choices — there is no
  parameter that would let a caller vary them by arm even by mistake. The
  prompt template itself is byte-identical across arms and carries no arm
  label, no revision identifier and no currency word (``current``,
  ``latest``, ``superseded``, ``stale``); ``assert_no_forbidden_language``
  checks that against any prompt text, not just this module's own template.
* **scorer classes are disjoint from the closed exact-value endpoint's.**
  ``tools/gpu_successor_preflight.FORBIDDEN_SCORER_CLASSES`` names the closed
  endpoint's four classes; this module's three are asserted, in code, to
  share no name with them.

The context budget is not restated: it is read directly from
``endpoint/context_builder.TOTAL_PROMPT_TOKENS``, the constant the CPU
materializer this study reuses already declares.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_NS = _HERE.parents[0]
for _path in (_HERE, _NS / "tools", _NS / "source_fact_ir"):
    _str = str(_path)
    if _str not in sys.path:
        sys.path.insert(0, _str)

import context_builder  # noqa: E402
import gpu_successor_preflight as gsp  # noqa: E402
import ir  # noqa: E402

# ---------------------------------------------------------------------------
# arms — currency of served state, nothing else
# ---------------------------------------------------------------------------

ARM_VERIFIED_CURRENT_TYPED = "VERIFIED_CURRENT_TYPED"
ARM_STALE_APPEND_ONLY = "STALE_APPEND_ONLY"
ARMS: tuple[str, ...] = (ARM_VERIFIED_CURRENT_TYPED, ARM_STALE_APPEND_ONLY)

# ---------------------------------------------------------------------------
# everything identical across arms — single constants, not per-arm choices
# ---------------------------------------------------------------------------

#: `protocols/GPU_SUCCESSOR_STUDY_V1.yaml`'s `model:` block, unchanged: the
#: already-pinned model, not a fresh selection.
MODEL_REPOSITORY = "Qwen/Qwen3.6-27B"
MODEL_REVISION = "6a9e13bd6fc8f0983b9b99948120bc37f49c13e9"

DECODING: dict[str, Any] = {"temperature": 0.0, "strategy": "greedy", "thinking": "off"}
MAX_NEW_TOKENS = 256

#: Read from the existing CPU materializer, not restated. A second constant
#: here would be exactly the kind of drift `agreement_with_preflight` in the
#: protocol exists to catch.
CONTEXT_BUDGET_TOKENS = context_builder.TOTAL_PROMPT_TOKENS

#: The frozen prompt template. Byte-identical for every arm and every
#: question; the arm and the revision never reach the model, only the served
#: context does. Deliberately distinct from `context_builder.SYSTEM_PROMPT`
#: and `context_builder.QUESTION_FRAME` — those belong to the closed
#: MODEL_ENDPOINT_V1 endpoint and its exact-value question, not this one.
SYSTEM_PROMPT = (
    "You answer only from the numbered sources provided. "
    "Give a direct answer to the question and nothing else. "
    'If the sources do not state it or you cannot determine it, answer '
    'exactly: not stated.'
)
QUESTION_FRAME = "Question: {question}\n\nSources:\n{sources}\n\nAnswer with the value only."

#: Words that would let the model infer which arm it is being served, or which
#: revision, without either being stated structurally. Checked against every
#: prompt this schema builds, not just the template literal.
CURRENCY_WORDS: tuple[str, ...] = ("current", "latest", "superseded", "stale")
REVISION_WORDS: tuple[str, ...] = ("revision", "version id", "as of revision")


class CurrencyLanguageDetected(ValueError):
    """A prompt carried a currency or revision word and was refused."""


def assert_no_forbidden_language(text: str) -> None:
    """Refuse any prompt text naming currency or a revision.

    This is the check the protocol's `arm_names_never_reach_the_model` rule
    demands: not a description of intent, a function that raises on the
    words that would break it. Applied to this schema's own template and
    question text — never to the served `context_blocks`, which are real
    document content and may legitimately contain any of these words in
    ordinary prose (a source saying "the current tax rate is 7%" is not this
    study leaking its arm). What must never carry these words is the frame
    around the context, not the context itself; `context_builder.py`'s own
    `prompt_carries_no_arm_label` makes the identical choice, checking the
    template rather than the assembled prompt with real sources folded in.
    """
    lowered = text.casefold()
    hits = sorted({word for word in CURRENCY_WORDS + REVISION_WORDS if word in lowered})
    if hits:
        raise CurrencyLanguageDetected(
            f"prompt carries forbidden currency/revision language: {hits}"
        )


def prompt_template_digest() -> str:
    blob = SYSTEM_PROMPT + "\x00" + QUESTION_FRAME
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# question templates — one per eligible typed-fact kind, from the
# representation's typed structure, never from free text
# ---------------------------------------------------------------------------

#: One fixed question per kind. The template is the typed vocabulary itself —
#: `ir.REFERENCE_TARGET` / `ir.LANGUAGE` / `ir.EFFECTIVE_TIME` /
#: `ir.APPLICABILITY` are the four facets the founder's ruling names — never a
#: paraphrase of the witness's excerpt or any other free text. Building the
#: question by reading prose would reintroduce exactly the text-recoverable
#: leakage `gpu_successor_preflight._invisible_in_unit_text` exists to
#: exclude from the cohort in the first place.
QUESTION_BY_KIND: dict[str, str] = {
    ir.REFERENCE_TARGET: "What does the reference at this location resolve to?",
    ir.LANGUAGE: "What language is declared for this content?",
    ir.EFFECTIVE_TIME: "What effective date applies to this content?",
    ir.APPLICABILITY: "What scope does this content apply to?",
}

assert set(QUESTION_BY_KIND) == set(gsp.ELIGIBLE_KINDS), (
    "question templates must cover exactly the preflight's ELIGIBLE_KINDS, "
    "no more and no fewer"
)


def question_for_fact(kind: str, representation: Any) -> str:
    """The fixed question for `kind`, built from the fact's typed slot.

    `representation` is required (not read for its value, only checked for
    presence) because a fact with no typed representation has nothing this
    endpoint can ask about — that is exactly the eligibility rule in section 4
    of the protocol, restated as a precondition here rather than assumed by
    the caller.
    """
    if kind not in QUESTION_BY_KIND:
        raise ValueError(f"no question template for kind {kind!r}")
    if representation is None:
        raise ValueError(
            f"cannot build a question for kind {kind!r} with no typed representation"
        )
    return QUESTION_BY_KIND[kind]


# ---------------------------------------------------------------------------
# scorer classes — disjoint from the closed endpoint's by construction
# ---------------------------------------------------------------------------

ANSWER_MATCHES_CURRENT = "ANSWER_MATCHES_CURRENT"
ANSWER_REFUSED = "ANSWER_REFUSED"
ANSWER_OTHER = "ANSWER_OTHER"

#: Protocol section 7's three classes, in this exact order. `ANSWER_REFUSED`
#: is its own class precisely so a decline is never folded into "wrong" —
#: without it the study could not tell a refusal from an incorrect answer,
#: and a study that cannot make that distinction cannot report either.
SCORER_CLASSES: tuple[str, ...] = (ANSWER_MATCHES_CURRENT, ANSWER_REFUSED, ANSWER_OTHER)

REFUSAL_CLASS = ANSWER_REFUSED

_scorer_overlap = set(SCORER_CLASSES) & set(gsp.FORBIDDEN_SCORER_CLASSES)
assert not _scorer_overlap, (
    "this study's scorer classes must be disjoint from the closed endpoint's "
    f"(FORBIDDEN_SCORER_CLASSES); overlap: {sorted(_scorer_overlap)}"
)


def assert_scorer_classes_disjoint_from_closed_endpoint() -> dict[str, Any]:
    """Runtime-checkable form of the module-load-time assertion above.

    Kept as a callable (not just the bare `assert`) so a test — or a receipt
    writer — can capture the comparison as data rather than relying on import
    succeeding as the only evidence.
    """
    overlap = sorted(set(SCORER_CLASSES) & set(gsp.FORBIDDEN_SCORER_CLASSES))
    return {
        "scorer_classes": list(SCORER_CLASSES),
        "forbidden_scorer_classes": list(gsp.FORBIDDEN_SCORER_CLASSES),
        "overlap": overlap,
        "disjoint": not overlap,
    }


# ---------------------------------------------------------------------------
# per-arm request — the only thing that may vary is `context`
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmRequest:
    """One arm's fully-built request. Every field but `context_blocks` (and
    the prompt text it produces) is one of this module's frozen constants —
    there is no parameter on `build_arm_request` that lets a caller vary
    model, revision, decoding, `max_new_tokens`, the template or the budget
    per arm, so the two calls that build `VERIFIED_CURRENT_TYPED` and
    `STALE_APPEND_ONLY` cannot diverge on anything but which context they
    were given.
    """

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


#: Fields that must be byte-for-byte identical across two arms of the same
#: question. `context_blocks`, `user_prompt` and `arm` are deliberately
#: excluded — those are exactly what is allowed, and required, to differ.
IDENTICAL_ACROSS_ARMS_FIELDS: tuple[str, ...] = (
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


def build_arm_request(
    *,
    arm: str,
    kind: str,
    representation: Any,
    context_blocks: list[str] | tuple[str, ...],
) -> ArmRequest:
    """Build one arm's request from the frozen constants plus its context.

    `context_blocks` is the only caller-supplied thing that ends up in the
    served text. Everything else — model, revision, decoding, generation
    length, template, budget — comes from this module's constants, so it
    cannot be varied by arm even by a caller's mistake.
    """
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}, expected one of {ARMS}")
    question = question_for_fact(kind, representation)
    assert_no_forbidden_language(SYSTEM_PROMPT)
    assert_no_forbidden_language(question)
    sources = "\n\n".join(
        f"[{index + 1}] {block}" for index, block in enumerate(context_blocks)
    )
    user_prompt = QUESTION_FRAME.format(question=question, sources=sources)
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
        user_prompt=user_prompt,
    )


def assert_arms_identical_except_context(a: ArmRequest, b: ArmRequest) -> dict[str, Any]:
    """Compare two arm requests field by field; only context may differ.

    Returns the comparison as data (never a bare assert) so a test or a
    receipt writer can show which field, if any, diverged — not merely that
    something did.
    """
    mismatches = {
        field_name: {"a": getattr(a, field_name), "b": getattr(b, field_name)}
        for field_name in IDENTICAL_ACROSS_ARMS_FIELDS
        if getattr(a, field_name) != getattr(b, field_name)
    }
    return {
        "compared_fields": list(IDENTICAL_ACROSS_ARMS_FIELDS),
        "mismatches": mismatches,
        "identical_except_context": not mismatches,
    }


# ---------------------------------------------------------------------------
# the frozen contract, whole — inspectable and hashable for a receipt
# ---------------------------------------------------------------------------


def frozen_contract() -> dict[str, Any]:
    """Everything this module declares, in one JSON-serializable dict.

    Every field is either a module-level constant or derived deterministically
    from one, so two calls in the same process (or two processes on the same
    code) produce byte-identical output — that is what `schema_digest` below
    freezes.
    """
    return {
        "schema": "tavonel.v2.successor_prompt_schema.v1",
        "arms": list(ARMS),
        "model": {"repository": MODEL_REPOSITORY, "revision": MODEL_REVISION},
        "decoding": dict(DECODING),
        "max_new_tokens": MAX_NEW_TOKENS,
        "context_budget_tokens": CONTEXT_BUDGET_TOKENS,
        "context_budget_source": "endpoint.context_builder.TOTAL_PROMPT_TOKENS",
        "prompt_template_digest": prompt_template_digest(),
        "question_by_kind": dict(sorted(QUESTION_BY_KIND.items())),
        "scorer_classes": list(SCORER_CLASSES),
        "refusal_class": REFUSAL_CLASS,
        "forbidden_scorer_classes": list(gsp.FORBIDDEN_SCORER_CLASSES),
        "currency_words": list(CURRENCY_WORDS),
        "revision_words": list(REVISION_WORDS),
        "identical_across_arms_fields": list(IDENTICAL_ACROSS_ARMS_FIELDS),
    }


def schema_digest() -> str:
    canonical = json.dumps(frozen_contract(), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
