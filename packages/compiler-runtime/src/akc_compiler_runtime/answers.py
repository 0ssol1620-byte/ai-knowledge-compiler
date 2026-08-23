"""Turning a question into draft claims, then into a compiled answer.

Draft selection is deliberately lexical and deterministic: the same question
against the same world always nominates the same claims, in the same order --
otherwise replay (§19) could not trust its own input. Everything after
selection belongs to ``akc_cir.answer_compiler``: freshness against the ACTIVE
world state first, then §N17's authority tuple, then the closed outcome set.

A claim that has been invalidated by a dependency removal is *not* nominated:
serving it as current would be exactly the failure the invalidation stamp
exists to prevent.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from akc_cir.answer_compiler import DraftClaim
from akc_cir.authority import AuthorityClass, ScopedClaim, SourceStatus
from akc_cir.identity import normalize_text_for_identity

__all__ = [
    "STOPWORDS",
    "informative_tokens",
    "select_drafts",
]

#: Words that say *how* something is asked, never *what* it is about.
STOPWORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "what",
        "which", "who", "when", "where", "why", "how", "does", "do", "did",
        "of", "for", "to", "in", "on", "at", "by", "with", "about", "tell",
        "me", "our", "we", "us", "my", "i", "it", "its", "and", "or",
        "current", "currently", "latest", "today", "now", "please",
        "현재", "최신", "지금", "알려줘", "뭐야", "무엇",
    }
)

_MAX_DRAFTS = 12


def _fold_token(token: str) -> str:
    """A deliberately small suffix fold so ``requires`` meets ``require``.

    Matching is token-based, and questions conjugate: "what does the policy
    require" vs a claim that says "requires". Stripping one trailing plural /
    third-person -s on both sides keeps the lexical gate honest without
    pretending to be a stemmer.
    """
    if token.endswith("'s"):
        token = token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def informative_tokens(question: str) -> tuple[str, ...]:
    """The question's content words, normalized and folded, order preserved."""
    tokens = [
        _fold_token(token)
        for token in normalize_text_for_identity(question).split()
        if token not in STOPWORDS
    ]
    return tuple(dict.fromkeys(tokens))


def _claim_is_answerable(row: Mapping[str, object]) -> bool:
    if row.get("invalidated_by"):
        return False
    if row.get("kind") == "dependency":
        # A pointer is not a statement of fact: ``Depends on: x`` records an
        # edge, and edges never answer questions (cf. REFERENCES being inert).
        return False
    return int(row["source_status"]) != int(SourceStatus.WITHDRAWN)


def select_drafts(
    question: str,
    claims: Mapping[str, Mapping[str, object]],
    *,
    world_state_id: str,
) -> tuple[DraftClaim, ...]:
    """Nominate the claims a question is *about*, best-first.

    A claim qualifies when every informative token of the question occurs in
    its subject or text -- AND semantics, so "launch date" does not drag in
    every claim that merely mentions a date. Qualifying claims are ranked by
    how strongly their subject matches, which is what keeps the canonical
    claim ahead of passing mentions.
    """
    wanted = informative_tokens(question)
    if not wanted:
        return ()

    scored: list[tuple[int, str, Mapping[str, object]]] = []
    for logical_id, row in claims.items():
        if not _claim_is_answerable(row):
            continue
        subject_tokens = {
            _fold_token(token)
            for token in normalize_text_for_identity(str(row["subject"])).split()
        }
        text_tokens = {
            _fold_token(token)
            for token in normalize_text_for_identity(str(row["value"])).split()
        }
        if not all(token in subject_tokens or token in text_tokens for token in wanted):
            continue
        subject_hits = sum(1 for token in wanted if token in subject_tokens)
        scored.append((subject_hits, logical_id, row))

    scored.sort(key=lambda item: (-item[0], item[1]))
    drafts: list[DraftClaim] = []
    for _, _, row in scored[:_MAX_DRAFTS]:
        drafts.append(
            DraftClaim(
                claim=_scoped_claim(row),
                world_state_id=world_state_id,
            )
        )
    return tuple(drafts)


def _scoped_claim(row: Mapping[str, object]) -> ScopedClaim:
    recorded_at = row.get("recorded_at")
    return ScopedClaim(
        claim_id=str(row["logical_id"]),
        subject=str(row["subject"]),
        value=str(row["value"]),
        authority=AuthorityClass(int(row["authority"])),
        source_status=SourceStatus(int(row["source_status"])),
        scope=dict(row["scope"]),  # type: ignore[arg-type]
        valid_from=_parse(row.get("valid_from")),
        valid_to=_parse(row.get("valid_to")),
        recorded_at=_parse(recorded_at),
        required_permission=(
            str(row["required_permission"]) if row.get("required_permission") else None
        ),
        evidence_id=str(row["evidence_id"]) if row.get("evidence_id") else None,
    )


def _parse(raw: object) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(str(raw))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
