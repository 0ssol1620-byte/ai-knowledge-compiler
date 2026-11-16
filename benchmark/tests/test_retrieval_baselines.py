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
