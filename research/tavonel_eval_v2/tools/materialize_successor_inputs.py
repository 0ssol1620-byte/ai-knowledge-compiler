#!/usr/bin/env python3
"""Immutable input materializer for SOURCE_FACT_PROPAGATION_MODEL_V1.

Turns a cohort manifest (`tools/build_successor_cohort.py`'s
`typed_fact_cohort.json`) plus the frozen prompt contract
(`endpoint/successor_prompt_schema.py`) into the exact, ordered, hashed set of
prompts the GPU run would consume -- entirely on CPU, before any GPU exists.

The point of this module is narrow and specific: once a cohort manifest
passes, the exact question text, template, decoding parameters and (for each
arm) which context atoms survive the budget must be fixed and provable *before*
a single GPU second is spent, so a later dispute about "what was actually
asked" has an answer that does not depend on trusting whoever ran the study.
`set_digest` and each item's `item_digest` are that answer.

Two things this module deliberately does not do:

* it does not decide which document atoms are candidates for a fact's
  context under either arm. That is retrieval/corpus work this study has not
  built yet (mirroring `endpoint/context_builder.arm_candidates`, which
  needs ranked/document-order pools nobody has computed for this study
  either). Callers pass `context_by_fact`, one ordered candidate list per
  fact per arm, shaped like `context_builder.fit_to_budget`'s own atom
  dicts (`atom_id`, `path`, `text`). What is fixed here is what happens to
  those candidates once supplied: truncation, prompt assembly, and hashing.
* it does not re-tokenize with the pinned model's real tokenizer -- no GPU
  and no model load happens anywhere in this repository's CPU tooling. A
  caller with a real tokenizer wires it in as `count_tokens`; without one,
  `_default_token_counter` is used, a declared word-count approximation
  documented as exactly that, never presented as a measurement.

Both arms materialize from the *same* manifest, and the schema's own
`assert_arms_identical_except_context` check (not a second copy of it) is run
per fact: if anything but `context_blocks`/`user_prompt`/`arm` differs between
`VERIFIED_CURRENT_TYPED` and `STALE_APPEND_ONLY`, materialization refuses
rather than emitting a set nobody would be able to trust the arm comparison of.

**Not run against a real cohort.** No cohort manifest exists yet -- the
held-out study that would produce one has not passed (see
`gpu_successor_preflight.HELD_OUT_STUDY_STEM`). Every test that exercises this
module drives it with small inline fixtures shaped like `build_successor_cohort`'s
own manifest output, never a real one.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_TOOLS = Path(__file__).resolve().parent
_NS = _TOOLS.parent
for _path in (_TOOLS, _NS / "endpoint", _NS / "source_fact_ir"):
    _str = str(_path)
    if _str not in sys.path:
        sys.path.insert(0, _str)

import context_builder  # noqa: E402
import successor_prompt_schema as sps  # noqa: E402
from common import canonical_json, sha_bytes  # noqa: E402
from evidence import write_immutable  # noqa: E402

MATERIALIZED_SCHEMA = "tavonel.v2.successor_materialized_inputs.v1"
RECEIPT_STEM = "successor-materialized-inputs"

TokenCounter = Callable[[str, str], int]


class MaterializationRefused(RuntimeError):
    """The manifest, or the context supplied for it, could not be safely
    materialized. Every raise site names which of the two failed and why."""


# ---------------------------------------------------------------------------
# token counting -- a declared CPU approximation, never a measurement
# ---------------------------------------------------------------------------


def _default_token_counter(system: str, user: str) -> int:
    """A whitespace-token approximation, used only when a caller supplies no
    `count_tokens`.

    This is a declared CPU approximation, not a measurement from the pinned
    model's tokenizer -- that tokenizer is only ever loaded once a GPU runtime
    exists, which this module never provisions. It exists so
    `context_builder.fit_to_budget`'s truncation decision has something to
    divide candidates by even when no real tokenizer has been wired in, and it
    is deliberately conservative: counting words rather than subword tokens
    over-estimates for most tokenizers, so this truncates earlier, not later.
    """
    return len((system + " " + user).split())


# ---------------------------------------------------------------------------
# refusal gates
# ---------------------------------------------------------------------------


def _require_feasible(manifest: dict[str, Any]) -> None:
    if not manifest.get("feasible", False):
        raise MaterializationRefused(
            "manifest reports feasible=False (or omits `feasible`); a manifest "
            "that cannot pose its own floor is never materialized into a "
            "GPU-bound input set"
        )


def _require_matching_prompt_schema_digest(manifest: dict[str, Any]) -> str:
    """Refuse unless the digest recorded alongside the manifest matches the
    prompt schema this process would build prompts from right now.

    `build_successor_cohort.py`'s manifest does not yet carry a
    `prompt_schema_digest` field -- recording one is a change to that module,
    which this tool does not own. Its absence is refused here, not treated as
    "no check needed": a manifest that does not attest which prompt schema it
    was built against cannot be trusted to still match one, and "not
    attested" is a different claim from "matches."
    """
    expected = sps.schema_digest()
    recorded = manifest.get("prompt_schema_digest")
    if recorded is None:
        raise MaterializationRefused(
            "manifest carries no prompt_schema_digest; refusing to materialize "
            "against an unattested prompt schema"
        )
    if recorded != expected:
        raise MaterializationRefused(
            f"manifest's recorded prompt_schema_digest {recorded!r} does not "
            f"match the current prompt schema digest {expected!r}"
        )
    return expected


# ---------------------------------------------------------------------------
# per-fact materialization
# ---------------------------------------------------------------------------


def _fit_context(
    *,
    question: str,
    candidates: list[dict[str, Any]],
    count_tokens: TokenCounter,
    budget: int,
) -> list[str]:
    """Which candidate atoms survive truncation, and their text, in order.

    Reuses `context_builder.fit_to_budget` for the truncation decision --
    this module does not reimplement "add atoms in order until the next
    would not fit." `fit_to_budget` measures against its own frame
    (`context_builder.SYSTEM_PROMPT`/`QUESTION_FRAME`), a different literal
    string from this study's own frame in `successor_prompt_schema`; the two
    frames are held to the same declared budget
    (`successor_prompt_schema.CONTEXT_BUDGET_TOKENS ==
    context_builder.TOTAL_PROMPT_TOKENS`, asserted at import time by that
    module), so this reuses the one truncation algorithm the repository has
    rather than keeping a second copy that could drift from it.
    """
    fitted = context_builder.fit_to_budget(question, candidates, count_tokens, budget)
    kept_ids = fitted["context_atom_ids"]
    by_id = {atom["atom_id"]: atom for atom in candidates}
    return [by_id[atom_id]["text"] for atom_id in kept_ids]


def materialize_fact(
    fact: dict[str, Any],
    *,
    context_by_arm: dict[str, list[dict[str, Any]]],
    count_tokens: TokenCounter = _default_token_counter,
    budget: int = sps.CONTEXT_BUDGET_TOKENS,
) -> dict[str, Any]:
    """Materialize both arms' requests for one eligible fact, hashed.

    Refuses (`MaterializationRefused`) if `context_by_arm` is missing an arm,
    or if the two built requests diverge on anything but context -- the
    schema's own `assert_arms_identical_except_context` decides that, not a
    second copy of the comparison.
    """
    kind = fact["kind"]
    fact_id = fact.get("fact_id")
    representation = fact.get("representation")

    arm_requests: dict[str, sps.ArmRequest] = {}
    for arm in sps.ARMS:
        candidates = context_by_arm.get(arm)
        if candidates is None:
            raise MaterializationRefused(
                f"fact {fact_id!r} has no context candidates for arm {arm!r}; "
                "every eligible fact must carry context for every arm or "
                "materialization refuses"
            )
        question = sps.question_for_fact(kind, representation)
        context_blocks = _fit_context(
            question=question,
            candidates=candidates,
            count_tokens=count_tokens,
            budget=budget,
        )
        arm_requests[arm] = sps.build_arm_request(
            arm=arm,
            kind=kind,
            representation=representation,
            context_blocks=context_blocks,
        )

    first_arm, second_arm = sps.ARMS
    comparison = sps.assert_arms_identical_except_context(
        arm_requests[first_arm], arm_requests[second_arm]
    )
    if not comparison["identical_except_context"]:
        raise MaterializationRefused(
            f"fact {fact_id!r}: the two arms' built requests diverged on "
            f"fields other than context: {comparison['mismatches']}"
        )

    item = {
        "fact_id": fact_id,
        "kind": kind,
        "lineage_id": fact.get("lineage_id"),
        "current_revision": fact.get("current_revision"),
        "preceding_revision": fact.get("preceding_revision"),
        "arms": {arm: request.as_dict() for arm, request in arm_requests.items()},
        "identical_except_context": comparison,
    }
    item_digest = sha_bytes(canonical_json(item).encode("utf-8"))
    return {**item, "item_digest": item_digest}


# ---------------------------------------------------------------------------
# the whole set
# ---------------------------------------------------------------------------


def materialize(
    manifest: dict[str, Any],
    *,
    context_by_fact: dict[str, dict[str, list[dict[str, Any]]]],
    count_tokens: TokenCounter = _default_token_counter,
    budget: int = sps.CONTEXT_BUDGET_TOKENS,
) -> dict[str, Any]:
    """The full materialized, hashed, deterministically-ordered input set.

    Refuses before building anything if the manifest is not `feasible` or its
    recorded prompt schema digest does not match this process's. Refuses
    mid-build, per fact, if `context_by_fact` is missing an entry or the two
    arms diverge on anything but context.

    Ordering is `(kind, fact_id)` -- the same key `build_successor_cohort`
    already sorts its manifest's `facts` by -- so two calls against the same
    manifest and the same context always produce the same `set_digest`
    regardless of dict/JSON key order upstream.
    """
    _require_feasible(manifest)
    prompt_schema_digest = _require_matching_prompt_schema_digest(manifest)

    facts = sorted(manifest.get("facts", []), key=lambda fact: (fact["kind"], fact["fact_id"]))

    items: list[dict[str, Any]] = []
    for fact in facts:
        fact_id = fact.get("fact_id")
        context_by_arm = context_by_fact.get(fact_id)
        if context_by_arm is None:
            raise MaterializationRefused(
                f"no context supplied for fact {fact_id!r}; every eligible "
                "fact in the manifest must have context or materialization "
                "refuses rather than silently skipping it"
            )
        items.append(
            materialize_fact(
                fact,
                context_by_arm=context_by_arm,
                count_tokens=count_tokens,
                budget=budget,
            )
        )

    set_digest = sha_bytes(canonical_json([item["item_digest"] for item in items]).encode("utf-8"))

    return {
        "schema": MATERIALIZED_SCHEMA,
        "study_id": manifest.get("study_id"),
        "prompt_schema_digest": prompt_schema_digest,
        "manifest_facts_digest": manifest.get("facts_digest"),
        "ordering": "sorted by (kind, fact_id); deterministic across builds of the same inputs",
        "item_count": len(items),
        "items": items,
        "set_digest": set_digest,
    }


# ---------------------------------------------------------------------------
# CLI -- not invoked against a real cohort by anything in this repository
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest", type=Path, help="path to a typed_fact_cohort.json cohort manifest"
    )
    parser.add_argument(
        "context",
        type=Path,
        help=(
            "path to a JSON file: {fact_id: {arm: [{atom_id, path, text}, ...]}} "
            "-- the ordered context candidates for every fact in the manifest"
        ),
    )
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    context_by_fact = json.loads(args.context.read_text(encoding="utf-8"))

    body = materialize(manifest, context_by_fact=context_by_fact)
    written = write_immutable(RECEIPT_STEM, body, tool=Path(__file__).resolve(), protocol=None)
    summary = {**written, "item_count": body["item_count"], "set_digest": body["set_digest"]}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
