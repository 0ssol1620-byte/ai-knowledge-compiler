"""WO-D17-4: pre-registration, filing-cluster paired bootstrap, the three-outcome rule."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from benchmark.retrieval_baselines import arena, metrics, run_baselines
from benchmark.retrieval_baselines.arena import ArenaError, decide, paired_cluster_bootstrap
from benchmark.retrieval_baselines.run_baselines import Corpus, run

ARMS = ["exact_token", "bm25_rows", "hybrid_current", "graph_entity"]


def _prereg(**over: Any) -> dict[str, Any]:
    return {
        "schema": arena.PREREG_SCHEMA,
        "incumbent": "bm25_rows",
        "arms": ARMS,
        "margin": 0.02,
        "stratum_floor": 0.02,
        "seed": 20261118,
        "resamples": 2000,
        **over,
    }


def _raw(prereg: dict[str, Any]) -> tuple[bytes, str]:
    raw = json.dumps(prereg).encode("utf-8")
    return raw, hashlib.sha256(raw).hexdigest()


# ---- the bootstrap, against hand-computed cases ----


def test_bootstrap_matches_a_hand_computed_two_cluster_case():
    # cluster A holds tasks with delta 1 and 0 (sum 1, size 2); cluster B one task with delta 0.
    # Two draws per resample: AA -> 2/4 = 0.5 (p 1/4), AB/BA -> 1/3 (p 1/2), BB -> 0/2 = 0 (p 1/4).
    # With 25 per mille cut from each tail, the 95% interval is [0, 0.5]; the point is 1/3.
    # A task-level bootstrap would give an upper bound of 2/3 or 1 here: clusters matter.
    deltas = {"t1": 1.0, "t2": 0.0, "t3": 0.0}
    cluster = {"t1": "A", "t2": "A", "t3": "B"}
    point, low, high = paired_cluster_bootstrap(deltas, cluster, seed=7, resamples=10_000)
    assert point == pytest.approx(1 / 3)
    assert (low, high) == (0.0, 0.5)


def test_bootstrap_is_seeded_and_a_constant_delta_has_a_zero_width_interval():
    deltas = {f"t{i}": (1.0 if i % 2 else 0.0) for i in range(8)}
    cluster = {f"t{i}": f"c{i // 2}" for i in range(8)}  # every cluster holds one 1 and one 0
    assert paired_cluster_bootstrap(deltas, cluster, seed=3, resamples=1000) == (0.5, 0.5, 0.5)
    noisy = {f"t{i}": float(i % 3 == 0) for i in range(30)}
    by = {f"t{i}": f"c{i}" for i in range(30)}
    first = paired_cluster_bootstrap(noisy, by, seed=11, resamples=1000)
    assert first == paired_cluster_bootstrap(noisy, by, seed=11, resamples=1000)
    assert first[1] < first[0] < first[2]
    with pytest.raises(ArenaError):
        paired_cluster_bootstrap({}, {}, seed=1, resamples=1000)


# ---- the pre-registration ----


def test_prereg_mismatch_and_malformed_content_are_refused():
    raw, digest = _raw(_prereg())
    assert arena.load_prereg(raw, digest)["incumbent"] == "bm25_rows"
    with pytest.raises(ArenaError, match="sha256 mismatch"):
        arena.load_prereg(raw, "0" * 64)
    with pytest.raises(ArenaError, match="64 hexadecimal"):
        arena.load_prereg(raw, "abc")
    bad: list[dict[str, Any]] = [
        _prereg(incumbent="hybrid_current"),
        _prereg(arms=[*ARMS, "a0_claims_only"]),
        _prereg(arms=[*ARMS, "label_blind"]),
        _prereg(arms=["bm25_rows"]),
        _prereg(arms=["exact_token", "hybrid_current"]),
        _prereg(arms=[*ARMS, "bm25_rows"]),
        _prereg(margin=0),
        _prereg(margin=True),
        _prereg(seed=True),
        _prereg(seed=-1),
        _prereg(resamples=10),
        _prereg(extra=1),
        {k: v for k, v in _prereg().items() if k != "margin"},
    ]
    for prereg in bad:
        with pytest.raises(ArenaError):
            arena.load_prereg(*_raw(prereg))
    nan = json.dumps(_prereg()).replace('"margin": 0.02', '"margin": NaN').encode()
    with pytest.raises(ArenaError, match="finite"):
        arena.load_prereg(nan, hashlib.sha256(nan).hexdigest())
    junk = b"\xff\xfe{"
    with pytest.raises(ArenaError, match="UTF-8 JSON"):
        arena.load_prereg(junk, hashlib.sha256(junk).hexdigest())


def test_rows_index_and_clusters_refuse_what_they_cannot_map():
    line = {"logical_id": "r1", "adsh": "f1", "fsds_key": {"cik": "1"}}
    index = arena.load_rows_index([json.dumps(line), ""])
    assert index == {"r1": ("1", "f1")}
    for broken in ({**line, "adsh": ""}, {**line, "fsds_key": []}, {"logical_id": "r1"}):
        with pytest.raises(ArenaError):
            arena.load_rows_index([json.dumps(broken)])
    with pytest.raises(ArenaError, match="twice"):
        arena.load_rows_index([json.dumps(line), json.dumps(line)])
    two = {"r1": ("1", "f1"), "r2": ("1", "f2")}
    assert arena.task_clusters({"t": ["r1"]}, two) == {"t": ("1", "f1")}
    with pytest.raises(ArenaError, match="span 2 filings"):
        arena.task_clusters({"t": ["r1", "r2"]}, two)
    with pytest.raises(ArenaError, match="not in the rows index"):
        arena.task_clusters({"t": ["r9"]}, two)
    with pytest.raises(ArenaError, match="no gold row"):
        arena.task_clusters({"t": []}, two)


# ---- the decision rule on synthetic reports: each outcome, and each refusal ----

TASKS = [f"t{i:02d}" for i in range(40)]
CLUSTERS = {t: (f"cik{i % 2}", f"f{i // 2:02d}") for i, t in enumerate(TASKS)}  # 20 filings
STRATA = {t: ("s1" if i < 20 else "s2") for i, t in enumerate(TASKS)}


def _entry(recall: dict[str, float], not_run: int = 0) -> dict[str, Any]:
    return {
        "status": "ran",
        "tasks": len(recall),
        "not_run_tasks": not_run,
        "not_run_reason": "capped" if not_run else None,
        "wall_seconds": 2.0,
        "cpu_seconds": 1.0,
        "recall_at_k": {},
        "per_task_recall_at_k": recall,
    }


def _report(**recalls: dict[str, float]) -> dict[str, Any]:
    base = {
        "exact_token": dict.fromkeys(TASKS, 0.0),
        "bm25_rows": dict.fromkeys(TASKS, 1.0),
        "hybrid_current": dict.fromkeys(TASKS, 1.0),
        "graph_entity": dict.fromkeys(TASKS, 1.0),
        "label_blind": dict.fromkeys(TASKS, 0.0),
        **recalls,
    }
    retrievers = {name: _entry(r) for name, r in base.items()}
    a0 = _entry(dict.fromkeys(TASKS, 1.0))  # A0 'wins' everything: it must stay outside
    a0["reachable_answerable_tasks"] = 3
    retrievers[arena.A0] = a0
    return {"blocking": [], "retrievers": retrievers}


def _split(good: float, bad: float) -> dict[str, float]:
    """good on even filings, bad on odd ones: a wide interval around the mean."""
    return {t: (good if int(CLUSTERS[t][1][1:]) % 2 == 0 else bad) for t in TASKS}


def test_outcome_simplest_wins_when_the_incumbent_is_non_inferior_to_every_complex_arm():
    out = decide(_report(), _prereg(), CLUSTERS, STRATA)
    assert out["ranked"] is True and out["outcome"] == "simplest_wins"
    assert out["incumbent"] == "bm25_rows"
    assert out["comparisons"]["hybrid_current"]["ci95"] == [0.0, 0.0]
    assert out["comparisons"]["hybrid_current"]["incumbent_non_inferior"] is True
    assert set(out["comparisons"]) == {"exact_token", "hybrid_current", "graph_entity"}
    assert "cpu_seconds_per_task" in out["comparisons"]["graph_entity"]["cost_per_task"]


def test_outcome_candidate_adr_shadow_when_a_complex_arm_beats_the_incumbent():
    report = _report(bm25_rows=_split(1.0, 0.0), graph_entity=dict.fromkeys(TASKS, 1.0))
    out = decide(report, _prereg(), CLUSTERS, STRATA)
    assert out["outcome"] == "candidate_adr_shadow"
    assert out["winners"] == ["graph_entity", "hybrid_current"]
    graph = out["comparisons"]["graph_entity"]
    assert graph["ci95"][0] > 0 and graph["delta_recall_at_k"] == pytest.approx(0.5)
    assert graph["delta_per_company_macro"] == pytest.approx(0.5)


def test_outcome_no_change_when_nothing_beats_and_non_inferiority_is_not_shown():
    report = _report(
        bm25_rows=_split(1.0, 0.0),
        hybrid_current=_split(0.0, 1.0),
        graph_entity=_split(0.0, 1.0),
    )
    out = decide(report, _prereg(), CLUSTERS, STRATA)
    assert out["outcome"] == "no_change" and out["winners"] == []
    assert out["comparisons"]["hybrid_current"]["incumbent_non_inferior"] is False


def test_a_stratum_below_the_floor_blocks_a_win():
    # graph beats overall (+1 on s1) but is worse on s2 by 0.1: worst stratum -0.1 < -0.02
    graph = {t: (1.0 if STRATA[t] == "s1" else 0.9) for t in TASKS}
    incumbent = {t: (0.0 if STRATA[t] == "s1" else 1.0) for t in TASKS}
    report = _report(bm25_rows=incumbent, graph_entity=graph, hybrid_current=incumbent)
    out = decide(report, _prereg(), CLUSTERS, STRATA)
    c = out["comparisons"]["graph_entity"]
    assert c["ci95"][0] > 0 and c["worst_stratum"]["stratum"] == "s2"
    assert c["worst_stratum"]["delta"] == pytest.approx(-0.1)
    assert c["beats_incumbent"] is False and out["outcome"] == "no_change"


def test_a_family_that_does_not_separate_ranks_nothing():
    flat = dict.fromkeys(TASKS, 1.0)
    out = decide(_report(label_blind=flat), _prereg(), CLUSTERS, STRATA)
    assert out["ranked"] is False and out["outcome"] is None
    assert "does not separate" in out["not_ranked_reason"] and "D17-D3" in out["not_ranked_reason"]
    assert "comparisons" not in out and "ranking" not in out


def test_an_arm_with_not_run_tasks_is_unranked_and_blocks_simplest_wins():
    report = _report()
    report["retrievers"]["hybrid_current"] = _entry(dict.fromkeys(TASKS, 1.0), not_run=1)
    out = decide(report, _prereg(), CLUSTERS, STRATA)
    assert "hybrid_current" in out["unranked"] and "hybrid_current" not in out["comparisons"]
    assert "hybrid_current" not in out["ranking"]
    assert out["outcome"] == "no_change"  # a complex arm was not measured on every task
    report["retrievers"]["bm25_rows"] = _entry(dict.fromkeys(TASKS, 1.0), not_run=2)
    out = decide(report, _prereg(), CLUSTERS, STRATA)
    assert out["ranked"] is False and "incumbent bm25_rows is unranked" in out["not_ranked_reason"]


def test_a0_stays_outside_the_rule_with_its_reachable_count():
    out = decide(_report(), _prereg(), CLUSTERS, STRATA)
    assert arena.A0 not in out["comparisons"] and arena.A0 not in out["ranking"]
    assert out["outside_rule"][arena.A0]["reachable_answerable_tasks"] == 3
    assert "claims only" in out["outside_rule"][arena.A0]["reason"]


def test_a_blocking_report_or_an_unpaired_task_set_ranks_nothing():
    report = _report()
    report["blocking"] = ["future_leaks: 1 hits violate the task's cut"]
    out = decide(report, _prereg(), CLUSTERS, STRATA)
    assert out["ranked"] is False and out["not_ranked_reason"].startswith("hard gate")
    unpaired = _report(graph_entity=dict.fromkeys(TASKS[1:], 1.0))
    with pytest.raises(ArenaError, match="same answerable tasks"):
        decide(unpaired, _prereg(), CLUSTERS, STRATA)
    with pytest.raises(ArenaError, match="no filing cluster"):
        decide(_report(), _prereg(), dict(list(CLUSTERS.items())[1:]), STRATA)


def test_a_missing_floor_makes_separation_untestable():
    report = _report()
    report["retrievers"]["label_blind"] = {"status": "not_run", "reason": "no blind query"}
    out = decide(report, _prereg(), CLUSTERS, STRATA)
    assert out["ranked"] is False and "separation untestable" in out["not_ranked_reason"]


# ---- run(): reviewer notes on WO-D17-1, tie at k, latency, A0 ----


def _src(lid: str, text: str, adsh: str = "f1") -> dict[str, Any]:
    return {
        "tenant": "a",
        "logical_id": lid,
        "source_id": adsh,
        "source_version_id": adsh,
        "evidence_id": f"ev-{lid}",
        "text": text,
        "authority": "primary",
        "metadata": {},
    }


def _task_row(tid: str, query: str, gold: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "task_id": tid,
        "kind": "retrieval",
        "tenant": "a",
        "query": query,
        "cut": None,
        "gold_evidence_ids": gold,
        "answerable": bool(gold),
        "provenance": "generated",
        "generator": "t",
        "seed": 1,
        **extra,
    }


def test_duplicate_task_ids_are_refused_by_name_and_empty_blind_queries_are_not_run():
    corpus = Corpus([_src("r1", "Revenue increased in 2023.")])
    task = metrics.parse_task(_task_row("dup-1", "revenue", ["ev-r1"]))
    with pytest.raises(metrics.TaskError, match="dup-1"):
        run(corpus, [task, task], {})
    entry = run(corpus, [task], {}, blind_queries={})["retrievers"]["label_blind"]
    assert entry == {"status": "not_run", "reason": run_baselines.NO_BLIND_ROWS}


def test_tie_at_k_latency_and_cpu_are_reported_and_a0_carries_its_reachable_count():
    rows = [_src(f"x{i:02d}", f"Quartz filler {i}.") for i in range(12)]
    rows.append(_src("r0", "Alder Holdings revenue increased in 2023 for the fiscal year."))
    corpus = Corpus(rows)
    tasks = [
        metrics.parse_task(_task_row("t1", "quartz", ["ev-x00"])),  # 12 rows tie at k = 10
        metrics.parse_task(_task_row("t2", "Alder revenue 2023", ["ev-r0"])),
    ]
    arms = {**run_baselines.BASELINES, arena.A0: run_baselines.A0_RETRIEVER}
    report = run(corpus, tasks, arms)
    bm25 = report["retrievers"]["bm25_rows"]
    assert bm25["tie_at_k"]["tasks_with_more_than_k_candidates"] == 2
    assert bm25["tie_at_k"]["tasks_whose_rank_k_and_k_plus_1_scores_are_equal"] == 2
    assert report["retrievers"]["exact_token"]["tie_at_k"] == run_baselines.NO_TIE_SCORE
    assert set(bm25["latency_seconds"]) >= {"p50", "p95", "p99", "note"}
    assert bm25["latency_seconds"]["tasks"] == 2 and bm25["cpu_seconds"] >= 0
    assert "never gated" in bm25["latency_seconds"]["note"]
    a0 = report["retrievers"][arena.A0]
    assert corpus.rows_with_claim >= 1 and a0["reachable_answerable_tasks"] == 1
    assert "outside the decision rule" in a0["outside_decision_rule"]
    assert bm25["per_task_recall_at_k"] == {"t1": 1.0, "t2": 1.0}
    assert report["exactness"].startswith("not measured")
    assert report["abstention"].startswith("not measured")


def test_latency_percentiles_are_nearest_rank():
    got = arena.latency_percentiles([float(i) for i in range(1, 101)])
    assert (got["p50"], got["p95"], got["p99"]) == (50.0, 95.0, 99.0)
    assert arena.latency_percentiles([])["p95"] is None


# ---- main(), end to end on synthetic files ----


def _files(tmp_path: Path, prereg: dict[str, Any] | None = None) -> tuple[list[str], str]:
    corpus, tasks, index = [], [], []
    for i in range(6):  # 6 filings over 2 companies, two answerable tasks each
        adsh, cik = f"f{i}", f"{i % 2}"
        for j in range(2):
            lid = f"g{i}{j}"
            corpus.append(_src(lid, f"Zeta{i}{j} gizmo{i}{j} amount.", adsh))
            index.append({"logical_id": lid, "adsh": adsh, "fsds_key": {"cik": cik}})
            tasks.append(
                _task_row(
                    f"t{i}{j}",
                    f"gizmo{i}{j}",
                    [f"ev-{lid}"],
                    stratum=f"s{j}",
                    label_blind_query="nothingmatches",
                )
            )
    for i in range(12):  # zero-score fill ranks these first, so the blind floor recalls 0
        corpus.append(_src(f"a{i:02d}", f"Filler {i}.", "f0"))
        index.append({"logical_id": f"a{i:02d}", "adsh": "f0", "fsds_key": {"cik": "0"}})
    for name, rows in (("c", corpus), ("t", tasks), ("i", index)):
        (tmp_path / f"{name}.jsonl").write_bytes(
            "\n".join(json.dumps(r) for r in rows).encode("utf-8")
        )
    raw, digest = _raw(prereg or _prereg())
    (tmp_path / "prereg.json").write_bytes(raw)
    args = [
        "--corpus",
        str(tmp_path / "c.jsonl"),
        "--tasks",
        str(tmp_path / "t.jsonl"),
        "--rows-index",
        str(tmp_path / "i.jsonl"),
        "--prereg",
        str(tmp_path / "prereg.json"),
    ]
    return args, digest


def test_main_prereg_mismatch_exits_one_and_writes_nothing(tmp_path: Path):
    args, digest = _files(tmp_path)
    out = tmp_path / "r.json"
    assert run_baselines.main([*args, "--prereg-sha256", "f" * 64, "--out", str(out)]) == 1
    assert not out.exists()
    missing = [*args[:-1], str(tmp_path / "absent.json")]
    assert run_baselines.main([*missing, "--prereg-sha256", digest, "--out", str(out)]) == 1
    assert not out.exists()
    assert run_baselines.main([*args, "--prereg-sha256", digest, "--out", str(out)]) == 0
    assert out.exists()


def test_main_ranked_dev_report_carries_the_hash_labels_and_an_outcome(tmp_path: Path):
    args, digest = _files(tmp_path)
    out = tmp_path / "dev.json"
    assert run_baselines.main([*args, "--prereg-sha256", digest, "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    report = json.loads(text)
    a = report["arena"]
    assert a["prereg_sha256"] == digest and a["run"] == "dev" and "not a decision" in a["binding"]
    assert a["ranked"] is True and a["incumbent"] == "bm25_rows"
    assert a["separation"]["separates"] is True
    assert a["outcome"] in arena.OUTCOMES
    assert report["retired"]["bm25_only"] and "bm25_only" not in report["retrievers"]
    assert report["retrievers"]["dense"]["status"] == "not_run"
    assert a["outside_rule"][arena.A0]["status"] == "ran"
    assert "accuracy" not in text.lower()
    assert not (tmp_path / ("prereg.json" + arena.HOLDOUT_RECEIPT_SUFFIX)).exists()


def test_main_without_prereg_is_an_unranked_report(tmp_path: Path):
    args, _ = _files(tmp_path)
    plain = args[:4]  # --corpus and --tasks only
    out = tmp_path / "plain.json"
    assert run_baselines.main([*plain, "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["arena"] == {
        "ranked": False,
        "outcome": None,
        "not_ranked_reason": arena.NO_PREREG,
    }
    with pytest.raises(SystemExit):
        run_baselines.main([*args, "--out", str(out)])  # --prereg without --prereg-sha256
    with pytest.raises(SystemExit):
        run_baselines.main([*plain, "--holdout", "--out", str(out)])


def test_a_second_holdout_run_is_refused_before_reading_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    args, digest = _files(tmp_path)
    first = tmp_path / "holdout.json"
    assert (
        run_baselines.main([*args, "--prereg-sha256", digest, "--holdout", "--out", str(first)])
        == 0
    )
    receipt = json.loads(
        (tmp_path / ("prereg.json" + arena.HOLDOUT_RECEIPT_SUFFIX)).read_text(encoding="utf-8")
    )
    assert receipt["prereg_sha256"] == digest
    assert receipt["report_sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    assert json.loads(first.read_text(encoding="utf-8"))["arena"]["run"] == "holdout"
    (tmp_path / "c.jsonl").write_bytes(b"not json\n")  # read it and the run would crash
    second = tmp_path / "holdout2.json"
    capsys.readouterr()
    code = run_baselines.main([*args, "--prereg-sha256", digest, "--holdout", "--out", str(second)])
    assert code == 1 and not second.exists()
    assert "holdout receipt already exists" in capsys.readouterr().err
