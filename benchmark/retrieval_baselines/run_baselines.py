"""Run exact-token, BM25, hybrid, graph-entity and (pinned) dense on one host and budget.

Corpus JSONL rows: tenant + SemanticSource fields (logical_id, source_id, source_version_id,
evidence_id, text, authority) + optional ``metadata`` (valid_from, valid_to, recorded_at,
available_at; ISO-8601 with offset). Logical ids are globally unique. Task JSONL: see
metrics.Task. Exit 1 when any retriever returns a future-leaking or other-tenant hit.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import sys
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from types import SimpleNamespace
from typing import Any

from akc_product_core.retrieval import (
    SemanticRetrievalCandidate,
    rank_exact_token_baseline,
    rank_semantic_candidates,
    retrieval_candidates,
)
from akc_product_core.semantics import SemanticSource, compile_semantics

from .metrics import CUT_KEYS, KINDS, Task, load_tasks, mean, ratio, score_task, violates_cut

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


class Corpus:
    def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
        by_tenant: dict[str, list[SemanticSource]] = defaultdict(list)
        self.metadata: dict[str, Mapping[str, Any]] = {}
        self.tenant_of: dict[str, str] = {}
        self.evidence_of: dict[str, frozenset[str]] = {}
        for row in rows:
            source = SemanticSource(**{f: row[f] for f in _SOURCE_FIELDS})
            if source.logical_id in self.metadata:
                raise ValueError(f"logical id {source.logical_id!r} appears twice in the corpus")
            by_tenant[row["tenant"]].append(source)
            self.metadata[source.logical_id] = row.get("metadata") or {}
        self.candidates: dict[str, Candidates] = {}
        for tenant, sources in by_tenant.items():
            compilation = compile_semantics(tuple(sources))  # once per tenant
            self.candidates[tenant] = retrieval_candidates(compilation)
            evidence: dict[str, set[str]] = defaultdict(set)
            for claim in compilation.claims:
                evidence[claim.logical_id].add(claim.evidence_id)
            for logical_id, ids in evidence.items():
                self.tenant_of[logical_id] = tenant
                self.evidence_of[logical_id] = frozenset(ids)


def exact_token(query: str, candidates: Candidates, k: int) -> tuple[str, ...]:
    return rank_exact_token_baseline(query, candidates, top_k=k)


def _all_hits(query: str, candidates: Candidates) -> tuple[Any, ...]:
    # ponytail: rank_semantic_candidates caps top_k at 100, so re-sorts see <=100 candidates.
    return rank_semantic_candidates(query, candidates, top_k=min(len(candidates), 100))


def bm25_only(query: str, candidates: Candidates, k: int) -> tuple[str, ...]:
    hits = _all_hits(query, candidates) if candidates else ()
    ordered = sorted(hits, key=lambda h: (-h.lexical_score, h.logical_id))
    return tuple(h.logical_id for h in ordered[:k])


def hybrid_current(query: str, candidates: Candidates, k: int) -> tuple[str, ...]:
    if not candidates:
        return ()
    return tuple(h.logical_id for h in rank_semantic_candidates(query, candidates, top_k=k))


def graph_entity(query: str, candidates: Candidates, k: int) -> tuple[str, ...]:
    hits = _all_hits(query, candidates) if candidates else ()
    ordered = sorted(hits, key=lambda h: (-h.graph_score, h.logical_id))
    return tuple(h.logical_id for h in ordered[:k])


BASELINES: dict[str, Retriever] = {
    "exact_token": exact_token,
    "bm25_only": bm25_only,
    "hybrid_current": hybrid_current,
    "graph_entity": graph_entity,
}


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
            raise KeyError(f"no pinned query vector for {query!r}")
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


def run(
    corpus: Corpus,
    tasks: Sequence[Task],
    retrievers: Mapping[str, Retriever],
    *,
    top_k: int = TOP_K,
    admit: Callable[..., Any] | None = None,
    not_run: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    admit = admit if admit is not None else _admit
    report: dict[str, Any] = {"top_k": top_k, "retrievers": {}}
    for name, reason in (not_run or {}).items():
        report["retrievers"][name] = {"status": "not_run", "reason": reason}
    for name, retriever in retrievers.items():
        recall: dict[str, list[float]] = defaultdict(list)
        precision: dict[str, list[float]] = defaultdict(list)
        tp = fp = fn = leaks = denied = ran = skipped = 0
        started = time.perf_counter()
        for task in tasks:
            candidates = corpus.candidates.get(task.tenant, ())
            if task.cut is not None:
                if admit is None:
                    skipped += 1
                    continue
                cut = SimpleNamespace(
                    **{"include_unknown_validity": False, **dict.fromkeys(CUT_KEYS), **task.cut}
                )
                candidates = tuple(
                    c
                    for c in candidates
                    if admit(corpus.metadata.get(c.logical_id, {}), cut).admitted
                )
            hits = tuple(retriever(task.query, candidates, top_k))[:top_k]
            ran += 1
            for hit in hits:
                owner = corpus.tenant_of.get(hit)
                denied += owner is not None and owner != task.tenant
                leaks += task.cut is not None and violates_cut(
                    corpus.metadata.get(hit, {}), task.cut
                )
            scores = score_task(hits, task.gold_evidence_ids, corpus.evidence_of)
            if scores["recall"] is not None:
                recall[task.kind].append(scores["recall"])
            if scores["precision"] is not None:
                precision[task.kind].append(scores["precision"])
            if not hits:
                tp, fp = tp + (not task.answerable), fp + task.answerable
            elif not task.answerable:
                fn += 1
        report["retrievers"][name] = {
            "status": "ran",
            "wall_seconds": time.perf_counter() - started,
            "tasks": ran,
            "not_run_tasks": skipped,
            "not_run_reason": "akc_retrieval.temporal unavailable" if skipped else None,
            "recall_at_k": {k: mean(recall[k]) for k in sorted(KINDS)},
            "source_precision_at_k": {k: mean(precision[k]) for k in sorted(KINDS)},
            "abstention_precision": ratio(tp, tp + fp),
            "abstention_recall": ratio(tp, tp + fn),
            "future_leaks": leaks,
            "denied_content": denied,
        }
    ran_reports = [r for r in report["retrievers"].values() if r["status"] == "ran"]
    report["future_leaks"] = sum(r["future_leaks"] for r in ran_reports)
    report["denied_content"] = sum(r["denied_content"] for r in ran_reports)
    return report


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
        tasks = load_tasks(handle)
    retrievers: dict[str, Retriever] = dict(BASELINES)
    not_run: dict[str, str] = {}
    pin: dict[str, str] | None = None
    if args.embeddings:
        retrievers["dense"], pin = load_dense(args.embeddings)
    else:
        not_run["dense"] = "no pinned embedding provider"
    report = run(corpus, tasks, retrievers, not_run=not_run)
    report["host"] = {
        "cpu": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    report["dense_pin"] = pin
    report["task_provenance"] = sorted({t.provenance for t in tasks})
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    return 1 if report["future_leaks"] or report["denied_content"] else 0


if __name__ == "__main__":
    sys.exit(main())
