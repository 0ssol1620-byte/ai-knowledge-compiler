"""Run exact-token, BM25, hybrid, graph-entity and (pinned) dense on one host and budget.

Corpus JSONL rows: tenant + SemanticSource fields (logical_id, source_id, source_version_id,
evidence_id, text, authority) + optional ``metadata`` (valid_from, valid_to, recorded_at,
available_at; ISO-8601 with offset). Logical ids are globally unique. Every row is a candidate
(WO-D14-8, decision D14-D9); claims the product compiles from a row stay attached to it. Task
JSONL: see metrics.Task. Exit 1 when any cut-applied retriever returns a future-leaking hit, any
retriever returns an other-tenant hit, the independent cut oracle (violates_cut) flags a row
the harness admitted, or an answerable task's gold cannot be reached.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import heapq
import json
import math
import platform
import sys
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from akc_product_core.retrieval import (
    SemanticRetrievalCandidate,
    rank_exact_token_baseline,
    rank_semantic_candidates,
    retrieval_candidates,
)
from akc_product_core.semantics import (
    SemanticSource,
    authority_tier,
    compile_semantics,
    semantic_tokens,
)

from .metrics import (
    CUT_KEYS,
    KINDS,
    Task,
    TaskError,
    load_tasks,
    mean,
    ratio,
    score_task,
    violates_cut,
)

try:  # WO-D14-1; absent -> temporal tasks are not_run, never silently uncut.
    from akc_retrieval.temporal import admit as _admit
except ImportError:
    _admit = None

TOP_K = 10
Candidates = tuple[SemanticRetrievalCandidate, ...]
Retriever = Callable[[str, Candidates, int], tuple[str, ...]]
_SOURCE_FIELDS = (
    "logical_id",
    "source_id",
    "source_version_id",
    "evidence_id",
    "text",
    "authority",
)
_ROW_FIELDS = ("tenant", *_SOURCE_FIELDS)


class CorpusError(ValueError):
    """A corpus row that cannot be a candidate. Names the ordinal and fields, never the text."""


class Corpus:
    def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
        by_tenant: dict[str, list[SemanticSource]] = defaultdict(list)
        self.metadata: dict[str, Mapping[str, Any]] = {}
        self.tenant_of: dict[str, str] = {}
        self.evidence_of: dict[str, frozenset[str]] = {}
        self.rows_of_evidence: dict[str, list[str]] = defaultdict(list)
        for ordinal, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise CorpusError(f"corpus row {ordinal} is not an object")
            bad = [f for f in _ROW_FIELDS if not isinstance(row.get(f), str) or not row[f].strip()]
            if bad:
                raise CorpusError(
                    f"corpus row {ordinal} yields no candidate: field(s) {bad} missing, "
                    "empty or not a string"
                )
            metadata = row.get("metadata")  # optional by contract; absent = no dates known
            if metadata is not None and not isinstance(metadata, Mapping):
                raise CorpusError(f"corpus row {ordinal}: field(s) ['metadata'] not an object")
            source = SemanticSource(**{f: row[f] for f in _SOURCE_FIELDS})
            if source.logical_id in self.metadata:
                raise CorpusError(f"corpus row {ordinal}: logical id appears twice in the corpus")
            by_tenant[row["tenant"]].append(source)
            self.metadata[source.logical_id] = metadata or {}
            self.tenant_of[source.logical_id] = row["tenant"]
            self.evidence_of[source.logical_id] = frozenset({source.evidence_id})
            self.rows_of_evidence[source.evidence_id].append(source.logical_id)
        self.candidates: dict[str, Candidates] = {}
        self.rows_with_claim = 0
        for tenant, sources in by_tenant.items():
            compilation = compile_semantics(tuple(sources))  # once per tenant
            claimed = {c.logical_id: c for c in retrieval_candidates(compilation)}
            self.rows_with_claim += len(claimed)
            self.candidates[tenant] = tuple(
                _row_candidate(s, claimed.get(s.logical_id))
                for s in sorted(sources, key=lambda s: s.logical_id)
            )
        self.rows_total = len(self.metadata)


def _row_candidate(
    source: SemanticSource, claimed: SemanticRetrievalCandidate | None
) -> SemanticRetrievalCandidate:
    """The row's own text and tokens; entity, temporal and claim links where it has claims."""
    return SemanticRetrievalCandidate(
        logical_id=source.logical_id,
        text=source.text,
        terms=semantic_tokens(source.text),
        entity_names=claimed.entity_names if claimed else (),
        temporal_refs=claimed.temporal_refs if claimed else (),
        authority_score=authority_tier(source.authority)[1],
        claim_ids=claimed.claim_ids if claimed else (),
    )


def exact_token(query: str, candidates: Candidates, k: int) -> tuple[str, ...]:
    return rank_exact_token_baseline(query, candidates, top_k=k)


RANK_CAP = 100  # rank_semantic_candidates rejects top_k > 100
# rank_semantic_candidates' BM25 recounts document frequency per candidate: quadratic. Measured
# on synthetic SEC-shaped rows (receipts/WO-D14-8): 1.3 s at 1,000 candidates, 32 s at 5,000.
HYBRID_CAP = 1_000
BM25_K1 = 1.2
BM25_B = 0.75
BM25_ROWS_PARAMS = {
    "k1": BM25_K1,
    "b": BM25_B,
    "idf": "ln(1 + (N - df + 0.5) / (df + 0.5))",
    "tf": "raw count of the term in the row's tokens",
    "query_terms": "distinct semantic_tokens(query); no synonym expansion",
    "tokenizer": "akc_product_core.semantics.semantic_tokens",
    "index_scope": "the task's candidate set (after the cut, where one applies)",
    "ties": "logical_id ascending; zero-score rows fill the remaining slots",
}


class NotRun(Exception):
    """A retriever cannot honestly score this task; counted in the report, never truncated."""


def bm25_only(query: str, candidates: Candidates, k: int) -> tuple[str, ...]:
    if len(candidates) > RANK_CAP:
        # BM25 IDF and max-normalisation depend on the whole set; slicing would change them.
        raise NotRun(
            f"candidate set exceeds the rank_semantic_candidates cap of {RANK_CAP}; "
            "no public full-set BM25 scorer"
        )
    if not candidates:
        return ()
    hits = rank_semantic_candidates(query, candidates, top_k=len(candidates))
    ordered = sorted(hits, key=lambda h: (-h.lexical_score, h.logical_id))
    return tuple(h.logical_id for h in ordered[:k])


def bm25_rows(query: str, candidates: Candidates, k: int) -> tuple[str, ...]:
    """Okapi BM25 over every candidate row through an inverted index; any corpus size."""
    # ponytail: index rebuilt per call (O(tokens of the candidate set)); cache per tenant
    # and cut if a run is too slow.
    query_terms = frozenset(semantic_tokens(query))
    postings: dict[str, list[tuple[int, int]]] = {t: [] for t in query_terms}
    lengths: list[int] = []
    for i, candidate in enumerate(candidates):
        lengths.append(len(candidate.terms))
        for term in query_terms.intersection(candidate.terms):
            postings[term].append((i, candidate.terms.count(term)))
    if not candidates:
        return ()
    n = len(candidates)
    average = sum(lengths) / n
    scores: dict[int, float] = defaultdict(float)
    for posting in postings.values():
        if not posting:
            continue
        idf = math.log(1 + (n - len(posting) + 0.5) / (len(posting) + 0.5))
        for i, tf in posting:
            norm = tf + BM25_K1 * (1 - BM25_B + BM25_B * lengths[i] / average)
            scores[i] += idf * tf * (BM25_K1 + 1) / norm
    top = heapq.nsmallest(
        k, range(n), key=lambda i: (-scores.get(i, 0.0), candidates[i].logical_id)
    )
    return tuple(candidates[i].logical_id for i in top)


def hybrid_current(query: str, candidates: Candidates, k: int) -> tuple[str, ...]:
    if len(candidates) > HYBRID_CAP:
        # Slicing would change the BM25 normalisation, so over the cap the task is not run.
        raise NotRun(
            f"candidate set exceeds the hybrid_current cap of {HYBRID_CAP}; "
            "rank_semantic_candidates' BM25 is quadratic in the candidate set"
        )
    if not candidates:
        return ()
    return tuple(h.logical_id for h in rank_semantic_candidates(query, candidates, top_k=k))


def graph_entity(query: str, candidates: Candidates, k: int) -> tuple[str, ...]:
    # graph_score is 0 for a row with no entity names and depends only on (query, candidate), so
    # only entity-bearing rows are scored (in slices, exact) and the zero-score rest fills the
    # remaining slots by logical_id ascending, as the full sort did.
    bearing = [c for c in candidates if c.entity_names]
    hits = [
        h
        for i in range(0, len(bearing), RANK_CAP)
        for h in rank_semantic_candidates(
            query, tuple(bearing[i : i + RANK_CAP]), top_k=len(bearing[i : i + RANK_CAP])
        )
        if h.graph_score > 0
    ]
    ordered = sorted(hits, key=lambda h: (-h.graph_score, h.logical_id))
    top = [h.logical_id for h in ordered[:k]]
    if len(top) < k:
        scored = {h.logical_id for h in ordered}
        top += heapq.nsmallest(
            k - len(top), (c.logical_id for c in candidates if c.logical_id not in scored)
        )
    return tuple(top)


BASELINES: dict[str, Retriever] = {
    "exact_token": exact_token,
    "bm25_only": bm25_only,
    "bm25_rows": bm25_rows,
    "no_cut_bm25_rows": bm25_rows,
    "hybrid_current": hybrid_current,
    "graph_entity": graph_entity,
}
# A plain current-state retriever: gets the tenant's whole row set, the cut is NOT applied, so
# its future_leaks is a measured number and is kept out of the stop-the-line gate.
NO_CUT = frozenset({"no_cut_bm25_rows"})
# Floor arm: bm25_rows on the task's own ``label_blind_query`` (the query without the concept
# label). Added by run() only when blind queries are supplied; it is not a BASELINES entry.
LABEL_BLIND = "label_blind"
NO_BLIND_QUERY = "task carries no label_blind_query"
# Retrievers with no score threshold: they return min(k, candidates).
THRESHOLD_FREE = frozenset(BASELINES) | {LABEL_BLIND}
BY_CONSTRUCTION_ABSTENTION = (
    "this retriever returns min(k, candidates); abstention equals an empty candidate set"
)
BY_CONSTRUCTION_LEAKS = (
    "the harness applies the cut before retrieval and this retriever returns only candidates; "
    "a leak here is a harness defect, not a retriever result"
)
NO_ANSWERABLE = "no answerable task"
NO_HIT = "no answerable task returned a hit"


def load_dense(path: str) -> tuple[Retriever, dict[str, str]]:
    """Dense retriever from pinned vectors via InMemoryVectorStore + RetrievalService."""
    from akc_retrieval import InMemoryVectorStore, RetrievalQuery, RetrievalService, VectorRecord
    from akc_retrieval.models import MediaKind

    with open(path, encoding="utf-8") as handle:
        pinned = json.load(handle)
    model_id, revision = pinned["model_id"], pinned["model_revision"]
    docs: Mapping[str, list[float]] = pinned["documents"]
    queries: Mapping[str, list[float]] = pinned["queries"]
    dimension = len(next(iter(docs.values())))
    project = uuid.uuid5(uuid.NAMESPACE_URL, "baseline-project")
    tenant = uuid.uuid5(uuid.NAMESPACE_URL, "baseline-tenant")

    def dense(query: str, candidates: Candidates, k: int) -> tuple[str, ...]:
        if query not in queries:
            raise KeyError("no pinned query vector for a task query")  # never the text
        store = InMemoryVectorStore(dimension=dimension)
        store.upsert(
            VectorRecord(
                tenant_id=tenant,
                project_id=project,
                stable_id=c.logical_id,
                media_kind=MediaKind.TEXT,
                source_hash=hashlib.sha256(c.logical_id.encode()).hexdigest(),
                evidence_block_ids=(uuid.uuid5(uuid.NAMESPACE_URL, c.logical_id),),
                model_id=model_id,
                model_revision=revision,
                vector=tuple(docs[c.logical_id]),
            )
            for c in candidates
        )
        service = RetrievalService(
            vector_store=store,
            reranker=None,
            expected_reranker_id=None,
            expected_reranker_revision=None,
            feature_enabled=True,
            provider_ready=True,
        )
        request = RetrievalQuery(
            tenant_id=tenant,
            project_ids=(project,),
            vector=tuple(queries[query]),
            candidate_k=100,
            top_k=k,
        )
        hits = asyncio.run(service.search(request, query_fingerprint="h1_" + "0" * 64))
        return tuple(h.stable_id for h in hits)

    return dense, {"model_id": model_id, "model_revision": revision}


def _cut(cut: Mapping[str, datetime]) -> SimpleNamespace:
    return SimpleNamespace(**{"include_unknown_validity": False, **dict.fromkeys(CUT_KEYS), **cut})


def reachability(
    corpus: Corpus, tasks: Sequence[Task], admit: Callable[..., Any] | None
) -> dict[str, Any]:
    """Before scoring: can every answerable task's gold be returned under its own cut?"""
    answerable = unreachable = unknown_tenant = 0
    reasons: Counter[str] = Counter()
    for task in tasks:
        # a tenant with no rows would make every abstention trivially right
        unknown_tenant += task.tenant not in corpus.candidates
        if not task.answerable:
            continue
        answerable += 1
        why: set[str] = set()
        for gold in task.gold_evidence_ids:
            owned = [
                lid
                for lid in corpus.rows_of_evidence.get(gold, ())
                if corpus.tenant_of[lid] == task.tenant
            ]
            if gold not in corpus.rows_of_evidence:
                why.add("gold evidence id not in the corpus")
            elif not owned:
                why.add("gold row belongs to another tenant")
            elif task.cut is None:
                continue
            elif admit is None:
                why.add("cut not checkable: akc_retrieval.temporal unavailable")
            elif not any(admit(corpus.metadata[lid], _cut(task.cut)).admitted for lid in owned):
                why.add("gold row not admitted by the task's own cut")
        unreachable += bool(why)
        reasons.update(why)
    return {
        "answerable_tasks": answerable,
        "gold_unreachable_tasks": unreachable,
        "gold_unreachable_reasons": dict(sorted(reasons.items())),
        "tasks_with_unknown_tenant": unknown_tenant,
    }


@dataclass
class _Tally:
    tasks: int = 0
    answerable: int = 0
    recall: list[float] = field(default_factory=list)
    precision: list[float] = field(default_factory=list)
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def add(self, task: Task, hits: tuple[str, ...], scores: Mapping[str, float | None]) -> None:
        self.tasks += 1
        self.answerable += task.answerable
        if scores["recall"] is not None:
            self.recall.append(scores["recall"])
        if scores["precision"] is not None:
            self.precision.append(scores["precision"])
        if not hits:
            self.tp, self.fp = self.tp + (not task.answerable), self.fp + task.answerable
        elif not task.answerable:
            self.fn += 1

    def quality(self) -> dict[str, Any]:
        return {
            "tasks": self.tasks,
            "answerable_tasks": self.answerable,
            "recall_at_k": mean(self.recall) if self.answerable else NO_ANSWERABLE,
            "source_precision_at_k": (
                mean(self.precision)
                if self.precision
                else (NO_HIT if self.answerable else NO_ANSWERABLE)
            ),
        }

    def abstention(self) -> dict[str, float | None]:
        return {
            "abstention_precision": ratio(self.tp, self.tp + self.fp),
            "abstention_recall": ratio(self.tp, self.tp + self.fn),
        }


def _labelled(name: str, abstention: dict[str, float | None]) -> dict[str, Any]:
    if name in THRESHOLD_FREE:
        return {"by_construction": {"note": BY_CONSTRUCTION_ABSTENTION, **abstention}}
    return dict(abstention)


@dataclass
class _Arm:
    by_kind: dict[str, _Tally] = field(default_factory=lambda: defaultdict(_Tally))
    by_stratum: dict[str, _Tally] = field(default_factory=lambda: defaultdict(_Tally))
    pooled: _Tally = field(default_factory=_Tally)
    reasons: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    leaks: int = 0
    denied: int = 0
    ran: int = 0
    skipped: int = 0
    cut_tasks: int = 0
    leaking_tasks: int = 0
    seconds: float = 0.0


def run(
    corpus: Corpus,
    tasks: Sequence[Task],
    retrievers: Mapping[str, Retriever],
    *,
    top_k: int = TOP_K,
    admit: Callable[..., Any] | None = None,
    not_run: Mapping[str, str] | None = None,
    blind_queries: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    admit = admit if admit is not None else _admit
    arms_in: dict[str, Retriever] = dict(retrievers)
    if blind_queries is not None:
        arms_in[LABEL_BLIND] = bm25_rows
    report: dict[str, Any] = {
        "top_k": top_k,
        "rows_total": corpus.rows_total,
        "rows_with_claim": corpus.rows_with_claim,
        "rows_without_claim": corpus.rows_total - corpus.rows_with_claim,
        **reachability(corpus, tasks, admit),
        "bm25_rows": BM25_ROWS_PARAMS,
        "candidate_caps": {"bm25_only": RANK_CAP, "hybrid_current": HYBRID_CAP},
        "retrievers": {},
    }
    for name, reason in (not_run or {}).items():
        report["retrievers"][name] = {"status": "not_run", "reason": reason}
    arms = {name: _Arm() for name in arms_in}
    oracle_rows = oracle_tasks = oracle_bad = 0
    admit_seconds = 0.0
    for task in tasks:
        all_candidates = corpus.candidates.get(task.tenant, ())
        admitted: Candidates | None = None  # ONE admitted set per task, shared by its arms
        if task.cut is not None and admit is not None:
            started = time.perf_counter()
            cut = _cut(task.cut)
            admitted = tuple(
                c for c in all_candidates if admit(corpus.metadata[c.logical_id], cut).admitted
            )
            admit_seconds += time.perf_counter() - started
            # independent predicate over EVERY admitted row, whatever any arm returns
            oracle_tasks += 1
            oracle_rows += len(admitted)
            oracle_bad += sum(
                violates_cut(corpus.metadata[c.logical_id], task.cut) for c in admitted
            )
        for name, retriever in arms_in.items():
            arm = arms[name]
            started = time.perf_counter()
            candidates = all_candidates
            query = task.query
            if name == LABEL_BLIND:
                blind = (blind_queries or {}).get(task.task_id)
                if blind is None:
                    arm.skipped += 1
                    arm.reasons[NO_BLIND_QUERY] += 1
                    continue
                query = blind
            if task.cut is not None and name not in NO_CUT:
                if admitted is None:
                    arm.skipped += 1
                    arm.reasons["akc_retrieval.temporal unavailable"] += 1
                    continue
                candidates = admitted
            try:
                hits = tuple(retriever(query, candidates, top_k))[:top_k]
            except NotRun as exc:
                arm.skipped += 1
                arm.reasons[str(exc)] += 1
                continue
            arm.ran += 1
            task_leaks = 0
            for hit in hits:
                owner = corpus.tenant_of.get(hit)
                arm.denied += owner is not None and owner != task.tenant
                # an id the corpus does not hold has no dates: violates_cut counts it as a leak
                task_leaks += task.cut is not None and violates_cut(
                    corpus.metadata.get(hit, {}), task.cut
                )
            arm.leaks += task_leaks
            arm.cut_tasks += task.cut is not None
            arm.leaking_tasks += task_leaks > 0
            scores = score_task(hits, task.gold_evidence_ids, corpus.evidence_of)
            for tally in (arm.pooled, arm.by_kind[task.kind]):
                tally.add(task, hits, scores)
            if task.stratum is not None:
                arm.by_stratum[task.stratum].add(task, hits, scores)
            arm.seconds += time.perf_counter() - started
    gate_leaks = denied_total = 0
    for name, arm in arms.items():
        cut_applied = name not in NO_CUT
        entry: dict[str, Any] = {
            "status": "ran",
            "cut": "applied by the harness before retrieval" if cut_applied else "not applied",
            "wall_seconds": arm.seconds,
            "tasks": arm.ran,
            "not_run_tasks": arm.skipped,
            "not_run_reason": "; ".join(sorted(arm.reasons)) or None,
            "not_run_reasons": dict(sorted(arm.reasons.items())),
            "recall_at_k": {k: arm.by_kind[k].quality()["recall_at_k"] for k in sorted(KINDS)},
            "source_precision_at_k": {
                k: arm.by_kind[k].quality()["source_precision_at_k"] for k in sorted(KINDS)
            },
            "by_stratum": {
                s: {**t.quality(), **_labelled(name, t.abstention())}
                for s, t in sorted(arm.by_stratum.items())
            },
            **_labelled(name, arm.pooled.abstention()),
            "denied_content": arm.denied,
        }
        if not cut_applied:
            entry["future_leaks"] = arm.leaks
            entry["cut_tasks"] = arm.cut_tasks
            entry["cut_tasks_with_a_leak"] = arm.leaking_tasks
        elif name in THRESHOLD_FREE:
            entry["by_construction"]["future_leaks"] = arm.leaks
            entry["by_construction"]["future_leaks_note"] = BY_CONSTRUCTION_LEAKS
            gate_leaks += arm.leaks
        else:
            entry["future_leaks"] = arm.leaks
            gate_leaks += arm.leaks
        denied_total += arm.denied
        report["retrievers"][name] = entry
    report["future_leaks"] = gate_leaks
    report["denied_content"] = denied_total
    # A count, not an accuracy: admitted rows that violates_cut says could not be known at the cut.
    report["cut_oracle_disagreements"] = oracle_bad
    report["cut_oracle_rows_checked"] = oracle_rows
    report["cut_oracle_tasks"] = oracle_tasks
    report["admit_wall_seconds"] = admit_seconds
    blocking = []
    if report["gold_unreachable_tasks"]:
        blocking.append(
            f"gold_unreachable_tasks: {report['gold_unreachable_tasks']} of "
            f"{report['answerable_tasks']} answerable tasks have a gold evidence id no "
            "retriever can return; recall is bounded by the harness, not measured"
        )
    if report["tasks_with_unknown_tenant"]:
        blocking.append(
            f"tasks_with_unknown_tenant: {report['tasks_with_unknown_tenant']} tasks name a "
            "tenant with no corpus rows"
        )
    if gate_leaks:
        blocking.append(f"future_leaks: {gate_leaks} hits violate the task's cut")
    if oracle_bad:
        blocking.append(
            f"cut_oracle_disagreements: {oracle_bad} rows admitted by the harness filter "
            "violate the task's cut"
        )
    if denied_total:
        blocking.append(f"denied_content: {denied_total} hits come from another tenant")
    report["blocking"] = blocking
    return report


def _blind_queries(lines: Sequence[str]) -> dict[str, str]:
    """task_id -> label_blind_query for rows that carry one; a present bad value is refused."""
    out: dict[str, str] = {}
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        if "label_blind_query" not in row:
            continue
        value = row["label_blind_query"]
        if not isinstance(value, str) or not value.strip():
            raise TaskError("label_blind_query must be a non-empty string when present")
        out[str(row["task_id"])] = value
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--embeddings")
    args = parser.parse_args(argv)
    with open(args.corpus, encoding="utf-8") as handle:
        corpus = Corpus([json.loads(line) for line in handle if line.strip()])
    with open(args.tasks, encoding="utf-8") as handle:
        lines = handle.readlines()
    tasks = load_tasks(lines)
    blind = _blind_queries(lines)
    retrievers: dict[str, Retriever] = dict(BASELINES)
    not_run: dict[str, str] = {}
    pin: dict[str, str] | None = None
    if args.embeddings:
        retrievers["dense"], pin = load_dense(args.embeddings)
    else:
        not_run["dense"] = "no pinned embedding provider"
    if not blind:
        not_run[LABEL_BLIND] = "no task row carries a label_blind_query"
    report = run(corpus, tasks, retrievers, not_run=not_run, blind_queries=blind or None)
    report["host"] = {
        "cpu": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    report["dense_pin"] = pin
    report["task_provenance"] = sorted({t.provenance for t in tasks})
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    return 1 if report["blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
