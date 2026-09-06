"""Arm contexts, the token budget, and the arm schedule. All CPU, all frozen.

The four arms differ in exactly one thing: which revisions of the retrieved
evidence reach the context. Everything else — the prompt template, the budget,
the decoding, the model — is identical, and the prompt carries no arm label, no
revision label and no currency word, so the model cannot tell which arm it is in.

The question frame is a single constant string wrapping the retrieval query. It
is byte-identical for every question and every arm, which is what lets it carry
no provenance of its own: a constant cannot encode anything about the document
it is asked against.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable

COMPILED_CURRENT = "compiled_current"
FULL_CURRENT_ORACLE = "full_current_oracle"
APPEND_ONLY = "append_only_stale_capable"
SUPERSEDED_CONTROL = "superseded_control"

ARMS = (COMPILED_CURRENT, FULL_CURRENT_ORACLE, APPEND_ONLY, SUPERSEDED_CONTROL)

#: The arms whose context is a single revision, and where the target evidence
#: atom must therefore survive truncation or the question tests nothing.
SINGLE_REVISION_ARMS = (COMPILED_CURRENT, FULL_CURRENT_ORACLE, SUPERSEDED_CONTROL)

TOTAL_PROMPT_TOKENS = 4096
MAX_NEW_TOKENS = 256

SYSTEM_PROMPT = (
    "You answer only from the numbered sources provided. "
    "Give the value asked for and nothing else. "
    'If the sources do not state it, answer exactly: not stated.'
)

#: Constant for every question and every arm. No arm, revision or currency word
#: appears anywhere in it.
QUESTION_FRAME = "Question: what value do the sources state for: {query}\nAnswer with the value only."


def prompt_parts(query: str, blocks: list[str]) -> tuple[str, str]:
    """The system and user messages, as they are sent."""
    sources = "\n\n".join(blocks)
    user = "Sources:\n" + sources + "\n\n" + QUESTION_FRAME.format(query=query)
    return SYSTEM_PROMPT, user


def block_for(atom: dict[str, Any], ordinal: int) -> str:
    return "[%d] %s\n%s" % (ordinal, atom["path"], atom["text"])


def fit_to_budget(
    query: str,
    candidates: list[dict[str, Any]],
    count_tokens: Callable[[str, str], int],
    budget: int = TOTAL_PROMPT_TOKENS,
) -> dict[str, Any]:
    """Add atoms in the arm's declared order until the next would not fit.

    Nothing is summarised, paraphrased or re-ranked to fit. An atom is in or it
    is out, and the ones left out are recorded by id rather than counted.
    """
    kept: list[dict[str, Any]] = []
    blocks: list[str] = []
    tokens = count_tokens(*prompt_parts(query, ["[1] placeholder\nplaceholder"]))
    tokens = count_tokens(*prompt_parts(query, []))
    for atom in candidates:
        trial = blocks + [block_for(atom, len(blocks) + 1)]
        size = count_tokens(*prompt_parts(query, trial))
        if size > budget:
            break
        blocks = trial
        kept.append(atom)
        tokens = size
    dropped = [atom["atom_id"] for atom in candidates[len(kept) :]]
    system, user = prompt_parts(query, blocks)
    return {
        "system": system,
        "user": user,
        "context_atom_ids": [atom["atom_id"] for atom in kept],
        "context_atom_paths": [atom["path"] for atom in kept],
        "context_ordering": "as declared by the arm; never re-ranked to fit",
        "context_token_count": tokens,
        "budget": budget,
        "truncated": bool(dropped),
        "dropped_atom_ids": dropped,
        "dropped_count": len(dropped),
        "candidate_count": len(candidates),
    }


def arm_candidates(
    arm: str,
    current_ranked: list[dict[str, Any]],
    superseded_ranked: list[dict[str, Any]],
    current_document_order: list[dict[str, Any]],
    merged_ranked: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """What each arm is allowed to put in front of the model."""
    if arm == COMPILED_CURRENT:
        return current_ranked
    if arm == FULL_CURRENT_ORACLE:
        # the current revision straight from source, in document order, with no
        # compiler ranking. It is the ceiling precisely because it is not a
        # retrieval result.
        return current_document_order
    if arm == APPEND_ONLY:
        return merged_ranked
    if arm == SUPERSEDED_CONTROL:
        return superseded_ranked
    raise ValueError("unknown arm: " + arm)


#: A cyclic Latin square. Row r is the arm order for questions assigned r.
LATIN_SQUARE: tuple[tuple[str, ...], ...] = tuple(
    tuple(ARMS[(column + row) % len(ARMS)] for column in range(len(ARMS)))
    for row in range(len(ARMS))
)


def schedule(question_ids: list[str]) -> dict[str, list[str]]:
    """Arm order per question, exactly balanced and derived from ids alone.

    Running the four arms as four blocks would confound arm with everything that
    drifts over a run. Assignment is by position in the sorted id list, so it is
    deterministic, reproducible, exactly balanced, and cannot depend on any
    property of the document or any outcome.
    """
    return {
        question_id: list(LATIN_SQUARE[index % len(LATIN_SQUARE)])
        for index, question_id in enumerate(sorted(question_ids))
    }


def schedule_balance(assignment: dict[str, list[str]]) -> dict[str, Any]:
    positions = {arm: [0] * len(ARMS) for arm in ARMS}
    for order in assignment.values():
        for position, arm in enumerate(order):
            positions[arm][position] += 1
    counts = {arm: tuple(values) for arm, values in positions.items()}
    spread = max(max(v) - min(v) for v in counts.values()) if assignment else 0
    return {
        "by_arm_and_position": {arm: list(values) for arm, values in counts.items()},
        "max_position_spread": spread,
        "balanced": spread <= 1,
    }


def prompt_template_digest() -> str:
    """The template must be byte-identical across arms; this is how that is shown."""
    blob = SYSTEM_PROMPT + "\x00" + QUESTION_FRAME
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


FORBIDDEN_IN_PROMPT = (
    "compiled_current",
    "full_current_oracle",
    "append_only",
    "superseded",
    "stale",
    "current revision",
    "arm ",
    "revision id",
)


def prompt_carries_no_arm_label(system: str, user: str) -> dict[str, Any]:
    """The check is on the template, not on the sources it happens to carry."""
    template = (system + "\n" + QUESTION_FRAME).casefold()
    found = [word for word in FORBIDDEN_IN_PROMPT if word in template]
    return {"clean": not found, "found": found, "digest": prompt_template_digest()}
