#!/usr/bin/env python3
"""The four W6 arms, the evidence schema they share, and the fairness contract.

`W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md` §1 and §4.

**The arms differ in exactly one thing: which evidence reaches the model.**
Everything else --- the question, the model, its version, decoding, the answer
schema, Stage 0 subject routing, and the scorer --- is shared, and
`fairness_contract` checks that mechanically instead of asserting it in prose.
The assertion is worth nothing unless something can refuse it, so the contract
returns findings and its control mutates one arm to prove it separates.

| arm | evidence after Stage 0 |
|---|---|
| `RAW` | the subject's whole before + after documents, to the shared budget |
| `BASIC_RAG` | BM25 top-k over the subject's units, both revisions indexed |
| `BASIC_RAG_PLUS` | BM25 + RM3 pseudo-relevance feedback, same units, same k |
| `TAVONEL` | the same units carrying valid-time and provenance |

`BASIC_RAG_PLUS` is deliberately a *retrieval* improvement and not an
intelligence one: RM3 is classical, deterministic, reproducible from what this
repository already contains, and needs no new model, no external API and no
metadata TAVONEL does not also have. A baseline strengthened with an LLM would
break the same-intelligence contract in the baseline's favour and make the
comparison meaningless in the other direction.

**The context budget is shared and is the reason RAW is not silently
handicapped.** RAW receives whole documents, which are far longer than k units,
so without a common budget the comparison would measure context length rather
than knowledge representation. Every arm reports `source_tokens`,
`truncated`, `units_omitted` and `oracle_omitted_by_truncation`, so a result
driven by budget rather than representation is visible in the receipt instead of
being invisible in the conclusion.

**No model is named here.** The protocol pins "the same frozen model" without
identifying one, and choosing it is not this code's call. The arms take an
injected `AnswerModel`; the identity and decoding config it reports are what the
freeze receipt pins. `ExtractiveDevelopmentModel` exists so the harness can be
exercised end to end on development data --- it performs no inference, and any
comparison produced with it is a harness check, never an endpoint.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

ARMS = ("RAW", "BASIC_RAG", "BASIC_RAG_PLUS", "TAVONEL")

#: The retrieval budget, shared by the three retrieval arms. Pinned by the freeze.
CONTEXT_BUDGET_TOKENS = 3000
TOP_K = 5

#: RAW does not share that budget. Founder decision of 2026-08-20, option B:
#: under the shared 3,000-token budget the development run measured RAW
#: truncating on 0.8701 of questions and losing the oracle on 0.5763, which makes
#: its floor a context-budget floor rather than a knowledge-representation floor.
#: RAW therefore receives the whole before + after document pair, up to whatever
#: the frozen model's context allows.
#:
#: The value is the frozen model's context window and is unknown until the model
#: is attested. It is `None` here on purpose: RAW refuses to run rather than
#: silently falling back to the retrieval budget, which would reintroduce exactly
#: the defect this decision removes.
MODEL_CONTEXT_TOKENS: int | None = None

#: The asymmetry is deliberate and is reported, never hidden. RAW is a floor
#: only; the primary comparison remains TAVONEL vs BASIC_RAG.
RAW_BUDGET_POLICY = "RAW_GETS_WHOLE_DOCUMENT_BUDGET"

#: RM3 pseudo-relevance feedback, classical settings. Fixed before measurement.
RM3_FEEDBACK_DOCS = 5
RM3_FEEDBACK_TERMS = 10
RM3_ORIGINAL_WEIGHT = 0.6

_WORD = re.compile(r"[a-z][a-z0-9]{2,}")
STOP = {"the", "and", "for", "with", "that", "this", "from", "was", "were", "are",
        "his", "her", "its", "which", "what", "who", "whom", "where", "when"}


def tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOP]


@dataclass(frozen=True)
class Unit:
    """One retrievable unit of one revision of one document."""

    text: str
    revision: str          # "before" | "after"
    revision_id: int
    path: str
    index: int
    valid_from: str
    valid_to: str | None   # None means still current

    @property
    def is_oracle_revision(self) -> bool:
        return self.revision == "after"


@dataclass
class ArmEvidence:
    """What one arm hands the model, and what it cost to do so."""

    arm: str
    units: list[Unit]
    source_tokens: int
    truncated: bool
    units_available: int
    units_omitted: int
    oracle_omitted_by_truncation: bool
    temporal_metadata_supplied: bool
    budget_tokens: int
    context_utilization: float
    overflow: bool = False
    notes: list[str] = field(default_factory=list)

    def as_context(self) -> str:
        """The literal text the model sees.

        Only `TAVONEL` prefixes valid-time and provenance --- that is the
        variable under test, so no other arm may carry it.
        """
        blocks = []
        for unit in self.units:
            if self.temporal_metadata_supplied:
                validity = f"valid from {unit.valid_from} to {unit.valid_to or 'present'}"
                blocks.append(f"[revision {unit.revision_id}; {validity}; {unit.path}]\n"
                              f"{unit.text}")
            else:
                blocks.append(unit.text)
        return "\n\n".join(blocks)


class AnswerModel(Protocol):
    """The injected model. Identity and decoding are what the freeze pins."""

    @property
    def identity(self) -> dict[str, Any]: ...

    def answer(self, question: str, context: str) -> dict[str, Any]: ...


class BM25:
    """Okapi BM25, written out so the ranking is inspectable."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.docs, self.k1, self.b = docs, k1, b
        self.freqs = [Counter(d) for d in docs]
        self.lengths = [len(d) for d in docs]
        self.avg = sum(self.lengths) / len(docs) if docs else 0.0
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for i, freq in enumerate(self.freqs):
            length = self.lengths[i] or 1
            score = 0.0
            for term in query:
                if term not in freq:
                    continue
                tf = freq[term]
                denom = tf + self.k1 * (1 - self.b + self.b * length / self.avg)
                score += self.idf.get(term, 0.0) * tf * (self.k1 + 1) / denom
            out.append(score)
        return out

    def rank(self, query: list[str], k: int) -> list[int]:
        scores = self.scores(query)
        return sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:k]


def rm3_expand(index: BM25, query: list[str], docs: list[list[str]]) -> list[str]:
    """Classical RM3: expand the query from the top feedback documents.

    Deterministic, no model, no external resource. This is what makes
    `BASIC_RAG_PLUS` a stronger retriever without giving the baseline
    intelligence that `TAVONEL` does not also have.
    """
    top = index.rank(query, RM3_FEEDBACK_DOCS)
    weights: Counter = Counter()
    for i in top:
        for term, count in Counter(docs[i]).items():
            weights[term] += count * index.idf.get(term, 0.0)
    expansion = [t for t, _w in weights.most_common(RM3_FEEDBACK_TERMS) if t not in query]
    repeats = max(1, round(RM3_ORIGINAL_WEIGHT / max(1e-9, 1 - RM3_ORIGINAL_WEIGHT)))
    return query * repeats + expansion


def _budget(units: list[Unit], available: int, arm: str, *, temporal: bool,
            oracle_indices: set[int], budget: int | None = None) -> ArmEvidence:
    """Apply a context budget and record exactly what it cost."""
    limit = CONTEXT_BUDGET_TOKENS if budget is None else budget
    kept: list[Unit] = []
    used = 0
    for unit in units:
        cost = len(tokens(unit.text))
        if used + cost > limit and kept:
            break
        kept.append(unit)
        used += cost
    omitted = len(units) - len(kept)
    kept_keys = {(u.revision, u.index) for u in kept}
    oracle_dropped = bool(oracle_indices) and not any(
        ("after", i) in kept_keys for i in oracle_indices)
    return ArmEvidence(
        arm=arm, units=kept, source_tokens=used, truncated=omitted > 0,
        units_available=available, units_omitted=omitted,
        oracle_omitted_by_truncation=oracle_dropped,
        temporal_metadata_supplied=temporal,
        budget_tokens=limit, context_utilization=round(used / limit, 4) if limit else 0.0,
    )


class RawContextOverflow(RuntimeError):
    """The whole-document pair does not fit the frozen model's context.

    Raised rather than truncated. Truncating here would silently recreate the
    budget-limited floor that the 2026-08-20 decision exists to remove, and the
    result would look like a representation finding.
    """


def raw_arm(units: list[Unit], query: str, oracle_indices: set[int], *,
            model_context_tokens: int | None = None) -> ArmEvidence:
    """Whole documents, before then after, in document order. No retrieval.

    RAW gets the frozen model's whole context rather than the retrieval budget.
    If the document pair does not fit, this raises `RawContextOverflow`; the
    caller records `RAW_CONTEXT_OVERFLOW` for that question and reports the RAW
    floor separately. It never truncates quietly.
    """
    limit = MODEL_CONTEXT_TOKENS if model_context_tokens is None else model_context_tokens
    if limit is None:
        raise RawContextOverflow(
            "MODEL_CONTEXT_TOKENS is not set: RAW cannot run before the frozen model is "
            "attested. Falling back to the retrieval budget would reintroduce the "
            "budget-limited floor that option B removes.")
    ordered = sorted(units, key=lambda u: (u.revision != "before", u.index))
    needed = sum(len(tokens(u.text)) for u in ordered)
    if needed > limit:
        raise RawContextOverflow(
            f"the whole-document pair needs {needed} tokens against a {limit}-token "
            "context. Recorded as RAW_CONTEXT_OVERFLOW rather than truncated.")
    ev = _budget(ordered, len(units), "RAW", temporal=False, oracle_indices=oracle_indices,
                 budget=limit)
    ev.notes.append(
        "whole before + after documents against the frozen model context, not the "
        "retrieval budget. The asymmetry is deliberate and favours the floor: RAW is a "
        "floor only, and the primary comparison remains TAVONEL vs BASIC_RAG.")
    return ev


def _retrieved(units: list[Unit], order: list[int], arm: str, *, temporal: bool,
               oracle_indices: set[int]) -> ArmEvidence:
    return _budget([units[i] for i in order], len(units), arm, temporal=temporal,
                   oracle_indices=oracle_indices)


def basic_rag_arm(units: list[Unit], query: str, oracle_indices: set[int]) -> ArmEvidence:
    """BM25 top-k over the subject's units. Both revisions indexed, no temporal hint."""
    docs = [tokens(u.text) for u in units]
    ev = _retrieved(units, BM25(docs).rank(tokens(query), TOP_K), "BASIC_RAG",
                    temporal=False, oracle_indices=oracle_indices)
    ev.notes.append("both revisions indexed; denied temporal metadata only, which is the "
                    "variable under test")
    return ev


def basic_rag_plus_arm(units: list[Unit], query: str,
                       oracle_indices: set[int]) -> ArmEvidence:
    """BM25 + RM3. A stronger retriever, not a smarter model."""
    docs = [tokens(u.text) for u in units]
    index = BM25(docs)
    expanded = rm3_expand(index, tokens(query), docs)
    ev = _retrieved(units, index.rank(expanded, TOP_K), "BASIC_RAG_PLUS",
                    temporal=False, oracle_indices=oracle_indices)
    ev.notes.append("RM3 pseudo-relevance feedback: deterministic, no model, no external "
                    "resource, no metadata TAVONEL does not also have")
    return ev


def tavonel_arm(units: list[Unit], query: str, oracle_indices: set[int], *,
                as_of: str | None = None) -> ArmEvidence:
    """The compiled world: same units, carrying valid-time and provenance.

    Retrieval is the same BM25 over the same units --- the arm is not given a
    better retriever. What it is given is the temporal structure: units valid at
    the asked-about time rank ahead of superseded ones, and each unit carries its
    revision and validity interval into the context.
    """
    docs = [tokens(u.text) for u in units]
    order = BM25(docs).rank(tokens(query), len(units))

    def temporal_key(i: int) -> tuple[int, int]:
        unit = units[i]
        if as_of is None:
            current = unit.valid_to is None
        else:
            current = unit.valid_from <= as_of and (unit.valid_to is None
                                                    or as_of < unit.valid_to)
        return (0 if current else 1, order.index(i))

    ev = _retrieved(units, sorted(order, key=temporal_key)[:TOP_K], "TAVONEL",
                    temporal=True, oracle_indices=oracle_indices)
    ev.notes.append("same retriever and same units as BASIC_RAG; the difference is "
                    "valid-time ordering and provenance carried into the context")
    return ev


ADAPTERS = {
    "RAW": raw_arm,
    "BASIC_RAG": basic_rag_arm,
    "BASIC_RAG_PLUS": basic_rag_plus_arm,
    "TAVONEL": tavonel_arm,
}


# --- the fairness contract --------------------------------------------------

SHARED_KEYS = ("model_identity", "decoding", "answer_schema", "subject_routing", "scorer",
               "top_k", "context_budget_tokens", "question_set_sha256")


def fairness_contract(arm_configs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Every arm must share the model and differ only in evidence.

    Returns findings rather than raising, so a violation is reported in the
    receipt instead of vanishing into a traceback.
    """
    findings: list[dict[str, Any]] = []
    missing = [a for a in ARMS if a not in arm_configs]
    if missing:
        findings.append({"kind": "ARM_MISSING", "arms": missing})

    for key in SHARED_KEYS:
        values = {a: arm_configs[a].get(key) for a in arm_configs}
        distinct = {repr(v) for v in values.values()}
        if len(distinct) > 1:
            findings.append({
                "kind": "SHARED_PARAMETER_DIFFERS", "parameter": key, "values": values,
                "why": "the arms must differ only in knowledge representation; a difference "
                       "here means the comparison is not same-intelligence",
            })

    temporal = {a: bool(c.get("temporal_metadata_supplied")) for a, c in arm_configs.items()}
    expected = {"RAW": False, "BASIC_RAG": False, "BASIC_RAG_PLUS": False, "TAVONEL": True}
    for arm, want in expected.items():
        if arm in temporal and temporal[arm] != want:
            findings.append({
                "kind": "TEMPORAL_METADATA_MISALLOCATED", "arm": arm,
                "expected": want, "observed": temporal[arm],
                "why": "temporal metadata is the variable under test; only TAVONEL may "
                       "carry it, and TAVONEL must",
            })

    for arm, config in arm_configs.items():
        if arm != "TAVONEL" and config.get("uses_external_model_beyond_shared"):
            findings.append({
                "kind": "BASELINE_GIVEN_EXTRA_INTELLIGENCE", "arm": arm,
                "why": "a baseline strengthened with intelligence TAVONEL does not have "
                       "breaks the contract in the baseline's favour",
            })
        if arm == "TAVONEL" and config.get("uses_external_model_beyond_shared"):
            findings.append({
                "kind": "TAVONEL_GIVEN_EXTRA_INTELLIGENCE", "arm": arm,
                "why": "new model intelligence given to TAVONEL alone would make any "
                       "advantage uninterpretable",
            })

    return {"holds": not findings, "finding_count": len(findings), "findings": findings,
            "shared_keys_checked": list(SHARED_KEYS)}


def fairness_control(base: dict[str, Any]) -> dict[str, Any]:
    """The contract must reject what it is meant to reject, in this execution."""
    clean = {arm: dict(base, temporal_metadata_supplied=(arm == "TAVONEL")) for arm in ARMS}

    mutated_decoding = {a: dict(c) for a, c in clean.items()}
    mutated_decoding["TAVONEL"]["decoding"] = dict(base["decoding"], temperature=0.7)

    mutated_temporal = {a: dict(c) for a, c in clean.items()}
    mutated_temporal["BASIC_RAG"]["temporal_metadata_supplied"] = True

    mutated_intelligence = {a: dict(c) for a, c in clean.items()}
    mutated_intelligence["TAVONEL"]["uses_external_model_beyond_shared"] = True

    results = {
        "clean_holds": fairness_contract(clean)["holds"],
        "differing_decoding_rejected": not fairness_contract(mutated_decoding)["holds"],
        "temporal_metadata_leak_rejected": not fairness_contract(mutated_temporal)["holds"],
        "extra_intelligence_rejected": not fairness_contract(mutated_intelligence)["holds"],
    }
    results["separates"] = results["clean_holds"] and all(
        v for k, v in results.items() if k != "clean_holds")
    return results


class ExtractiveDevelopmentModel:
    """A deterministic stand-in so the harness can run before a model is named.

    It performs **no inference**. It returns the first candidate value that the
    supplied context actually contains, which makes every arm's behaviour a pure
    function of the evidence it was handed --- exactly what a harness check
    needs and exactly what an endpoint must not be.

    Any comparison produced with this model is a harness check. It is not a
    result about any model, and the receipt records that as its run class.
    """

    is_real_model = False

    def __init__(self, candidates_for: Any) -> None:
        self._candidates_for = candidates_for

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "name": "ExtractiveDevelopmentModel",
            "is_real_model": False,
            "version": "development-stub-1",
            "note": "performs no inference; selects the first candidate value present in "
                    "the supplied context. Present so the pipeline is exercisable before a "
                    "model is pinned. Never an endpoint.",
        }

    def answer(self, question: str, context: str) -> dict[str, Any]:
        haystack = set(tokens(context))
        for candidate in self._candidates_for(question):
            wanted = set(tokens(candidate))
            if wanted and wanted <= haystack:
                return {"answer": candidate, "abstained": False,
                        "evidence_present": True}
        return {"answer": None, "abstained": True, "evidence_present": False}
