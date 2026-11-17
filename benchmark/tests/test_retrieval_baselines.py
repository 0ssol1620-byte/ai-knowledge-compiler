from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from benchmark.retrieval_baselines import metrics, run_baselines
from benchmark.retrieval_baselines.run_baselines import BASELINES, Corpus, run

ADMIT_ALL = lambda metadata, query: SimpleNamespace(admitted=True)  # noqa: E731


def _src(tenant, lid, text, meta=None):
    return {
        "tenant": tenant,
        "logical_id": lid,
        "source_id": f"s-{lid}",
        "source_version_id": "v1",
        "evidence_id": f"ev-{lid}",
        "text": text,
        "authority": "primary",
        "metadata": meta or {},
    }


def _row(tid, tenant, query, gold, kind="retrieval", cut=None, answerable=None):
    return {
        "task_id": tid,
        "kind": kind,
        "tenant": tenant,
        "query": query,
        "cut": cut,
        "gold_evidence_ids": gold,
        "answerable": bool(gold) if answerable is None else answerable,
        "provenance": "generated",
        "generator": "t",
        "seed": 1,
    }


def _task(*args, **kwargs):
    return metrics.parse_task(_row(*args, **kwargs))


CORPUS = [
    _src("a", "a1", "The revenue increased in 2024 for Mercury Systems."),
    _src("a", "a2", "The contract termination period is thirty days."),
    _src("b", "b1", "The Quartz Holdings dataset policy period is sixty days."),
]


def test_metrics_on_a_hand_computed_three_task_set():
    ev = {"h1": frozenset({"e1"}), "h2": frozenset({"e2"}), "h3": frozenset({"e9"})}
    gold = frozenset({"e1", "e2"})
    assert metrics.score_task(("h1", "h3"), gold, ev) == {"recall": 0.5, "precision": 0.5}
    assert metrics.score_task(("h1", "h2"), gold, ev) == {"recall": 1.0, "precision": 1.0}
    assert metrics.score_task((), frozenset(), ev) == {"recall": None, "precision": None}
    assert metrics.mean([0.5, 1.0]) == 0.75


def test_a_future_hit_is_counted_as_a_leak():
    cut = {"known_at": "2025-01-01T00:00:00+00:00"}
    corpus = Corpus(
        [
            _src("a", "a1", "Revenue increased.", {"recorded_at": "2024-06-01T00:00:00+00:00"}),
            _src("a", "a2", "Revenue grew later.", {"recorded_at": "2025-06-01T00:00:00+00:00"}),
        ]
    )
    task = _task("t1", "a", "revenue", ["ev-a1"], kind="temporal", cut=cut)
    bypass = lambda query, candidates, k: ("a2",)  # noqa: E731 - ignores the cut
    report = run(corpus, [task], {"bypass": bypass}, admit=ADMIT_ALL)
    assert report["retrievers"]["bypass"]["future_leaks"] == 1
    assert report["future_leaks"] == 1


def test_a_cross_tenant_hit_is_counted_as_denied_content():
    task = _task("t1", "a", "Quartz dataset", [], kind="acl_negative")
    report = run(Corpus(CORPUS), [task], {"bad": lambda q, c, k: ("b1",)})
    assert report["retrievers"]["bad"]["denied_content"] == 1
    assert report["retrievers"]["bad"]["abstention_recall"] == 0.0


def test_missing_embeddings_are_reported_not_run(tmp_path):
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps(r) for r in CORPUS), encoding="utf-8")
    row = _row("t1", "a", "revenue increase", ["ev-a1"])
    (tmp_path / "t.jsonl").write_text(json.dumps(row), encoding="utf-8")
    out = tmp_path / "r.json"
    code = run_baselines.main(
        [
            "--corpus",
            str(tmp_path / "c.jsonl"),
            "--tasks",
            str(tmp_path / "t.jsonl"),
            "--out",
            str(out),
        ]
    )
    report = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0
    assert report["retrievers"]["dense"] == {
        "status": "not_run",
        "reason": "no pinned embedding provider",
    }
    assert set(report["retrievers"]) >= set(BASELINES)


def test_main_exits_one_on_a_leak(tmp_path, monkeypatch):
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps(r) for r in CORPUS), encoding="utf-8")
    row = _row("t1", "a", "Quartz dataset", [], kind="acl_negative")
    (tmp_path / "t.jsonl").write_text(json.dumps(row), encoding="utf-8")
    monkeypatch.setitem(run_baselines.BASELINES, "bad", lambda q, c, k: ("b1",))
    code = run_baselines.main(
        [
            "--corpus",
            str(tmp_path / "c.jsonl"),
            "--tasks",
            str(tmp_path / "t.jsonl"),
            "--out",
            str(tmp_path / "r.json"),
        ]
    )
    assert code == 1


def test_every_retriever_gets_the_same_candidates_and_top_k():
    seen = {}

    def spy(name):
        def retriever(query, candidates, k):
            seen[name] = (query, tuple(c.logical_id for c in candidates), k)
            return ()

        return retriever

    run(Corpus(CORPUS), [_task("t1", "a", "revenue", ["ev-a1"])], {n: spy(n) for n in BASELINES})
    assert len(seen) == len(BASELINES)
    assert len(set(seen.values())) == 1
    assert next(iter(seen.values()))[2] == 10


def test_the_real_baselines_find_the_matching_source():
    task = _task("t1", "a", "contract termination period", ["ev-a2"])
    report = run(Corpus(CORPUS), [task], BASELINES)
    for name in BASELINES:
        assert report["retrievers"][name]["recall_at_k"]["retrieval"] == 1.0, name
    assert report["future_leaks"] == report["denied_content"] == 0


def test_temporal_tasks_are_not_run_without_the_temporal_module(monkeypatch):
    monkeypatch.setattr(run_baselines, "_admit", None)
    cut = {"known_at": "2025-01-01T00:00:00+00:00"}
    task = _task("t1", "a", "revenue", ["ev-a1"], kind="temporal", cut=cut)
    report = run(Corpus(CORPUS), [task], BASELINES)
    entry = report["retrievers"]["hybrid_current"]
    assert (entry["tasks"], entry["not_run_tasks"]) == (0, 1)


def test_a_naive_cut_and_an_inconsistent_answerable_flag_are_rejected():
    with pytest.raises(metrics.TaskError):
        _task("t1", "a", "q", ["e"], kind="temporal", cut={"known_at": "2025-01-01T00:00:00"})
    with pytest.raises(metrics.TaskError):
        _task("x", "a", "q", [], answerable=True)


def test_a_logical_id_shared_by_two_tenants_is_refused():
    with pytest.raises(ValueError):
        Corpus([_src("a", "x", "Revenue increased."), _src("b", "x", "Contract period.")])


def _big_corpus():
    rows = [
        _src(
            "a", f"d{i:03d}", f"Quartz Holdings reported zephyr mercury filler{i} figures in 2023."
        )
        for i in range(150)
    ]
    rows.append(_src("a", "target", "Mercury Systems reported figures in 2023."))
    return rows


def test_over_cap_candidate_set_is_scored_in_full_for_graph_and_not_run_for_bm25():
    corpus = Corpus(_big_corpus())
    task = _task("t1", "a", "zephyr Mercury", ["ev-target"])
    entry = run(corpus, [task], BASELINES)["retrievers"]
    assert entry["graph_entity"]["recall_at_k"]["retrieval"] == 1.0
    assert (entry["bm25_only"]["tasks"], entry["bm25_only"]["not_run_tasks"]) == (0, 1)
    assert "cap of 100" in entry["bm25_only"]["not_run_reason"]
    assert entry["hybrid_current"]["tasks"] == entry["exact_token"]["tasks"] == 1


def test_string_gold_and_non_string_fields_are_rejected():
    with pytest.raises(metrics.TaskError):
        metrics.parse_task({**_row("t", "a", "q", ["ev-a2"]), "gold_evidence_ids": "ev-a2"})
    with pytest.raises(metrics.TaskError):
        metrics.parse_task({**_row("t", "a", "q", ["ev-a2"]), "query": None})


# ---- WO-D17-1: one admitted set per task, graph on entity rows, cut oracle, label_blind ----

from akc_product_core.retrieval import (  # noqa: E402
    SemanticRetrievalCandidate,
    rank_semantic_candidates,
)
from akc_product_core.semantics import semantic_tokens  # noqa: E402

KNOWN = "2025-01-01T00:00:00+00:00"
_PAST = {"recorded_at": "2024-06-01T00:00:00+00:00"}
_FUTURE = {"recorded_at": "2025-06-01T00:00:00+00:00"}


def _real_admit(metadata, cut):  # a faithful known_at filter, independent of akc_retrieval
    rec = metadata.get("recorded_at")
    return SimpleNamespace(admitted=rec is not None and rec <= cut.known_at.isoformat())


def _old_graph_entity(query, candidates, k):  # the pre-change implementation, verbatim
    hits = [
        h
        for i in range(0, len(candidates), 100)
        for h in rank_semantic_candidates(
            query, candidates[i : i + 100], top_k=len(candidates[i : i + 100])
        )
    ]
    ordered = sorted(hits, key=lambda h: (-h.graph_score, h.logical_id))
    return tuple(h.logical_id for h in ordered[:k])


class _Lcg:  # deterministic, no `random` (lint forbids it in this tree)
    def __init__(self, seed):
        self.state = seed

    def below(self, n):
        self.state = (self.state * 6364136223846793005 + 1442695040888963407) % 2**64
        return (self.state >> 33) % n

    def rand(self):
        return self.below(1000) / 1000

    def randrange(self, n):
        return self.below(n)

    def randint(self, a, b):
        return a + self.below(b - a + 1)

    def choice(self, xs):
        return xs[self.below(len(xs))]

    def sample(self, xs, n):
        pool = list(xs)
        return [pool.pop(self.below(len(pool))) for _ in range(n)]


def test_graph_entity_on_entity_rows_equals_the_full_sort_on_seeded_sets():
    rng = _Lcg(17)
    words = ["alpha", "beta", "gamma", "delta", "omega", "sigma"]
    for trial in range(40):
        n = rng.choice([0, 1, 5, 30, 130, 250])
        cands = tuple(
            SemanticRetrievalCandidate(
                logical_id=f"r{rng.randrange(10**6):06d}-{i}",
                text="x",
                terms=("x",),
                entity_names=tuple(rng.sample(words, rng.randint(0, 2)))
                if rng.rand() < 0.3
                else (),
                temporal_refs=(),
                authority_score=0.5,
                claim_ids=(),
            )
            for i in range(n)
        )
        query = " ".join(rng.sample(words, rng.randint(1, 3)))
        for k in (1, 10, 400):
            assert run_baselines.graph_entity(query, cands, k) == _old_graph_entity(
                query, cands, k
            ), trial
    assert semantic_tokens("alpha")  # the words above are real tokens, so some scores are > 0


def _cut_corpus():
    return Corpus(
        [
            _src("a", "p1", "Revenue increased.", _PAST),
            _src("a", "p2", "Revenue grew.", _PAST),
            _src("a", "f1", "Revenue later.", _FUTURE),
        ]
    )


def test_admit_runs_once_per_task_row_not_per_arm_and_sets_do_not_leak_across_tasks():
    calls = []

    def admit(metadata, cut):
        calls.append(1)
        return _real_admit(metadata, cut)

    seen = {}

    def spy(query, candidates, k):
        seen.setdefault(query, []).append(tuple(c.logical_id for c in candidates))
        return ()

    early = {"known_at": "2024-01-01T00:00:00+00:00"}
    tasks = [
        _task("t1", "a", "q1", ["ev-p1"], kind="temporal", cut={"known_at": KNOWN}),
        _task("t2", "a", "q2", ["ev-p1"], kind="temporal", cut=early),
    ]
    run(_cut_corpus(), tasks, {}, admit=admit)
    no_arm_calls, calls[:] = len(calls), []  # reachability's own calls + one pass per task
    report = run(_cut_corpus(), tasks, {"s1": spy, "s2": spy}, admit=admit)
    assert len(calls) == no_arm_calls  # adding arms adds no admit call
    assert seen["q1"] == [("p1", "p2")] * 2  # both arms, the same set
    assert seen["q2"] == [()] * 2  # not the first task's set
    assert report["cut_oracle_disagreements"] == 0
    assert report["cut_oracle_rows_checked"] == 2
    assert report["blocking"] == [] or all("cut_oracle" not in b for b in report["blocking"])


def test_a_widened_admit_is_counted_by_the_independent_oracle_over_every_admitted_row():
    task = _task("t1", "a", "q", ["ev-p1"], kind="temporal", cut={"known_at": KNOWN})
    never_returns = lambda q, c, k: ()  # noqa: E731 - no arm ever returns the leaking row
    report = run(_cut_corpus(), [task], {"quiet": never_returns}, admit=ADMIT_ALL)
    assert report["retrievers"]["quiet"]["denied_content"] == 0
    assert report["cut_oracle_disagreements"] == 1
    assert any(b.startswith("cut_oracle_disagreements: 1") for b in report["blocking"])


def test_main_exits_one_when_admit_is_widened(tmp_path, monkeypatch):
    rows = [_src("a", "p1", "Revenue.", _PAST), _src("a", "f1", "Revenue later.", _FUTURE)]
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    row = _row("t1", "a", "revenue", ["ev-p1"], kind="temporal", cut={"known_at": KNOWN})
    (tmp_path / "t.jsonl").write_text(json.dumps(row), encoding="utf-8")
    args = ["--corpus", str(tmp_path / "c.jsonl"), "--tasks", str(tmp_path / "t.jsonl")]
    monkeypatch.setattr(run_baselines, "_admit", _real_admit)
    assert run_baselines.main([*args, "--out", str(tmp_path / "ok.json")]) == 0
    monkeypatch.setattr(run_baselines, "_admit", ADMIT_ALL)
    assert run_baselines.main([*args, "--out", str(tmp_path / "bad.json")]) == 1
    bad = json.loads((tmp_path / "bad.json").read_text(encoding="utf-8"))
    assert bad["cut_oracle_disagreements"] > 0


def test_label_blind_runs_on_the_blind_query_and_is_not_run_without_one(tmp_path):
    rows = [_src("a", "z1", "Mercury gadget 2023."), _src("a", "x2", "Quartz widget 2023.")]
    rows += [_src("a", f"f{i:02d}", f"Filler {i} 2023.") for i in range(11)]  # z1 ranks last
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    base = _row("t1", "a", "gadget 2023", ["ev-z1"])
    args = ["--corpus", str(tmp_path / "c.jsonl"), "--tasks", str(tmp_path / "t.jsonl")]
    (tmp_path / "t.jsonl").write_text(json.dumps(base), encoding="utf-8")
    run_baselines.main([*args, "--out", str(tmp_path / "n.json")])
    none = json.loads((tmp_path / "n.json").read_text(encoding="utf-8"))
    assert none["retrievers"]["label_blind"]["status"] == "not_run"
    (tmp_path / "t.jsonl").write_text(
        json.dumps({**base, "label_blind_query": "widget"}), encoding="utf-8"
    )
    run_baselines.main([*args, "--out", str(tmp_path / "b.json")])
    blind = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))["retrievers"]
    assert (
        blind["label_blind"]["recall_at_k"]["retrieval"] == 0.0
    )  # blind query ranks x2 first; z1 is outside the top 10
    assert blind["bm25_rows"]["recall_at_k"]["retrieval"] == 1.0
    (tmp_path / "t.jsonl").write_text(json.dumps({**base, "label_blind_query": 5}), "utf-8")
    with pytest.raises(metrics.TaskError):
        run_baselines.main([*args, "--out", str(tmp_path / "x.json")])


def test_a_task_without_a_blind_query_is_counted_not_run_for_that_arm_only():
    tasks = [_task("t1", "a", "contract", ["ev-a2"]), _task("t2", "a", "contract", ["ev-a2"])]
    report = run(Corpus(CORPUS), tasks, {}, blind_queries={"t1": "termination"})
    entry = report["retrievers"]["label_blind"]
    assert (entry["tasks"], entry["not_run_tasks"]) == (1, 1)
    assert entry["recall_at_k"]["retrieval"] == 1.0
