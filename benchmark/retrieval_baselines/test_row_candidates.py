"""WO-D14-8: every row is a candidate, reachability before scoring, bm25_rows, labels."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from akc_product_core.retrieval import retrieval_candidates
from akc_product_core.semantics import SemanticSource, compile_semantics

from benchmark.retrieval_baselines import metrics, run_baselines
from benchmark.retrieval_baselines.run_baselines import (
    BASELINES,
    BY_CONSTRUCTION_ABSTENTION,
    HYBRID_CAP,
    Corpus,
    CorpusError,
    bm25_rows,
    run,
)

MARKER = "Zanzibarquux"  # marker text; must never appear in an error or a report


def _src(tenant: str, lid: str, text: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
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


def _row(
    tid: str,
    tenant: str,
    query: str,
    gold: list[str],
    kind: str = "retrieval",
    cut: dict[str, str] | None = None,
    stratum: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "task_id": tid,
        "kind": kind,
        "tenant": tenant,
        "query": query,
        "cut": cut,
        "gold_evidence_ids": gold,
        "answerable": bool(gold),
        "provenance": "generated",
        "generator": "t",
        "seed": 1,
    }
    if stratum is not None:
        row["stratum"] = stratum
    return row


def _task(*args: Any, **kwargs: Any) -> metrics.Task:
    return metrics.parse_task(_row(*args, **kwargs))


NAMES = ["Alder", "Birch", "Cedar", "Dogwood", "Elm", "Fir", "Ginkgo", "Hazel", "Ilex", "Juniper"]


def _sec_like_rows() -> list[dict[str, Any]]:
    """Ten rows; only r0 has an English predicate (the SEC row template has none)."""
    rows = [
        _src("a", f"r{i}", f"{n} Holdings: Revenues: {i + 1}00 USD, fiscal year 2023")
        for i, n in enumerate(NAMES)
    ]
    rows[0] = _src("a", "r0", "Alder Holdings revenue increased in 2023 for the fiscal year.")
    return rows


def _sec_like_tasks() -> list[metrics.Task]:
    return [
        _task(f"t{i}", "a", f"{n} Holdings Revenues fiscal year 2023", [f"ev-r{i}"])
        for i, n in enumerate(NAMES)
    ]


def test_every_row_is_a_candidate_and_predicate_less_gold_is_reachable() -> None:
    rows = _sec_like_rows()
    # The bound before WO-D14-8: claim-only candidates hold 1 of the 10 gold rows.
    sources = tuple(SemanticSource(**{f: r[f] for f in run_baselines._SOURCE_FIELDS}) for r in rows)
    claim_only = {c.logical_id for c in retrieval_candidates(compile_semantics(sources))}
    assert claim_only == {"r0"}  # so claim-only recall over these tasks is at most 1/10

    corpus = Corpus(rows)
    assert [c.logical_id for c in corpus.candidates["a"]] == [f"r{i}" for i in range(10)]
    assert set(corpus.evidence_of) == {f"r{i}" for i in range(10)}
    claimed = {c.logical_id: c for c in corpus.candidates["a"] if c.claim_ids}
    assert set(claimed) == {"r0"}  # claims stay attached to their row

    report = run(corpus, _sec_like_tasks(), BASELINES)
    assert (report["rows_total"], report["rows_with_claim"], report["rows_without_claim"]) == (
        10,
        1,
        9,
    )
    assert (report["answerable_tasks"], report["gold_unreachable_tasks"]) == (10, 0)
    assert report["blocking"] == []
    for name in ("exact_token", "bm25_rows", "bm25_only", "hybrid_current"):
        assert report["retrievers"][name]["recall_at_k"]["retrieval"] == 1.0, name


def _write(
    tmp_path: Path, corpus_rows: list[dict[str, Any]], task_rows: list[dict[str, Any]]
) -> list[str]:
    (tmp_path / "c.jsonl").write_text(
        "\n".join(json.dumps(r) for r in corpus_rows), encoding="utf-8"
    )
    (tmp_path / "t.jsonl").write_text("\n".join(json.dumps(r) for r in task_rows), encoding="utf-8")
    return ["--corpus", str(tmp_path / "c.jsonl"), "--tasks", str(tmp_path / "t.jsonl")]


def test_a_gold_id_not_in_the_corpus_exits_non_zero_and_says_so_at_the_top(tmp_path: Path) -> None:
    corpus_rows = [_src("a", "a1", f"{MARKER} revenue increased in 2024.")]
    task_rows = [
        _row("t1", "a", f"{MARKER} revenue", ["ev-a1"]),
        _row("t2", "a", f"{MARKER} query", ["ev-missing"]),
    ]
    out = tmp_path / "r.json"
    code = run_baselines.main([*_write(tmp_path, corpus_rows, task_rows), "--out", str(out)])
    text = out.read_text(encoding="utf-8")
    report = json.loads(text)
    assert code == 1
    assert report["gold_unreachable_tasks"] == 1
    assert report["gold_unreachable_reasons"] == {"gold evidence id not in the corpus": 1}
    assert report["blocking"][0].startswith("gold_unreachable_tasks: 1 of 2 answerable")
    assert MARKER not in text


def test_gold_in_another_tenant_or_outside_its_cut_is_unreachable() -> None:
    corpus = Corpus(
        [
            _src("a", "a1", "Revenue increased.", {"recorded_at": "2025-06-01T00:00:00+00:00"}),
            _src("b", "b1", "Revenue increased.", {"recorded_at": "2024-06-01T00:00:00+00:00"}),
        ]
    )
    cut = {"known_at": "2025-01-01T00:00:00+00:00"}
    tasks = [
        _task("t1", "a", "revenue", ["ev-a1"], kind="temporal", cut=cut),  # recorded after
        _task("t2", "a", "revenue", ["ev-b1"]),  # other tenant's row
        _task("t3", "b", "revenue", ["ev-b1"], kind="temporal", cut=cut),  # reachable
        _task("t4", "zz", "revenue", [], kind="acl_negative"),  # tenant with no rows
    ]
    report = run(corpus, tasks, {"exact_token": BASELINES["exact_token"]})  # real admit
    assert report["gold_unreachable_tasks"] == 2
    assert report["gold_unreachable_reasons"] == {
        "gold row belongs to another tenant": 1,
        "gold row not admitted by the task's own cut": 1,
    }
    assert report["tasks_with_unknown_tenant"] == 1
    assert len(report["blocking"]) == 2


def test_bm25_rows_matches_a_hand_computed_ranking() -> None:
    # N = 5, avgdl = 12 / 5 = 2.4, k1 = 1.2, b = 0.75; query terms kiwi (df 2), pear (df 2)
    # idf = ln(1 + 3.5 / 2.5) = ln 2.4 for both terms, so compare tf parts:
    #   a (kiwi x2, len 3): 2 * 2.2 / (2 + 1.2 * (0.25 + 0.75 * 3 / 2.4)) = 4.4 / 3.425 = 1.2847
    #   b (kiwi x1, len 2): 2.2 / (1 + 1.2 * (0.25 + 0.75 * 2 / 2.4)) = 2.2 / 2.05 = 1.0732
    #   c (pear x1, len 4): 2.2 / (1 + 1.2 * (0.25 + 0.75 * 4 / 2.4)) = 2.2 / 2.8 = 0.7857
    #   d (pear x1, len 1): 2.2 / (1 + 1.2 * (0.25 + 0.75 * 1 / 2.4)) = 2.2 / 1.675 = 1.3134
    #   e: 0
    # Dropping tf would put b above a; dropping length normalisation would put a above d.
    corpus = Corpus(
        [
            _src("t", "a", "kiwi kiwi lime"),
            _src("t", "b", "kiwi mango"),
            _src("t", "c", "lime mango pear plum"),
            _src("t", "d", "pear"),
            _src("t", "e", "plum plum"),
        ]
    )
    candidates = corpus.candidates["t"]
    assert [len(c.terms) for c in candidates] == [3, 2, 4, 1, 2]
    assert bm25_rows("kiwi pear", candidates, 5) == ("d", "a", "b", "c", "e")
    assert bm25_rows("kiwi pear", candidates, 2) == ("d", "a")
    assert bm25_rows("kiwi pear", (), 5) == ()


def test_hybrid_current_over_its_cap_is_not_run_with_reason_and_count() -> None:
    rows = [
        _src("a", f"d{i:04d}", f"Quartz Holdings reported zephyr filler{i} figures in 2023.")
        for i in range(HYBRID_CAP)
    ]
    rows.append(_src("a", "target", "Mercury Systems reported figures in 2023."))
    corpus = Corpus(rows)
    tasks = [_task("t1", "a", "Mercury Systems", ["ev-target"]), _task("t2", "a", "zephyr", [])]
    retrievers = {n: BASELINES[n] for n in ("hybrid_current", "bm25_rows")}
    entry = run(corpus, tasks, retrievers)["retrievers"]
    hybrid = entry["hybrid_current"]
    assert (hybrid["tasks"], hybrid["not_run_tasks"]) == (0, 2)
    reason = f"candidate set exceeds the hybrid_current cap of {HYBRID_CAP}; "
    assert list(hybrid["not_run_reasons"].values()) == [2]
    assert next(iter(hybrid["not_run_reasons"])).startswith(reason)
    assert entry["bm25_rows"]["tasks"] == 2
    assert entry["bm25_rows"]["recall_at_k"]["retrieval"] == 1.0


def test_by_construction_labels_and_a_measured_no_cut_leak() -> None:
    corpus = Corpus(
        [
            _src("a", "a1", "Revenue increased.", {"recorded_at": "2024-06-01T00:00:00+00:00"}),
            _src(
                "a",
                "a2",
                "Revenue revenue increased sharply.",
                {"recorded_at": "2026-06-01T00:00:00+00:00"},
            ),
        ]
    )
    cut = {"known_at": "2025-01-01T00:00:00+00:00"}
    tasks = [
        _task("t1", "a", "revenue", ["ev-a1"], kind="temporal", cut=cut, stratum="backdated"),
        _task("t2", "a", "revenue", [], kind="temporal", cut=cut, stratum="added_later"),
    ]
    plain = lambda q, c, k: tuple(x.logical_id for x in c)[:k]  # noqa: E731 - undeclared
    report = run(corpus, tasks, {**BASELINES, "plain": plain})
    for name in BASELINES:
        entry = report["retrievers"][name]
        assert entry["by_construction"]["note"] == BY_CONSTRUCTION_ABSTENTION, name
        assert "abstention_precision" not in entry and "abstention_recall" not in entry, name
        stratum = entry["by_stratum"]["added_later"]
        assert stratum["by_construction"]["note"] == BY_CONSTRUCTION_ABSTENTION, name
    cut_entry = report["retrievers"]["bm25_rows"]
    assert cut_entry["by_construction"]["future_leaks"] == 0
    assert "future_leaks" not in cut_entry
    no_cut = report["retrievers"]["no_cut_bm25_rows"]
    assert no_cut["cut"] == "not applied"
    assert (no_cut["future_leaks"], no_cut["cut_tasks"], no_cut["cut_tasks_with_a_leak"]) == (
        2,
        2,
        2,
    )
    assert report["future_leaks"] == 0 and report["blocking"] == []  # measured, not a gate
    assert set(report["retrievers"]["plain"]) >= {"abstention_precision", "future_leaks"}


def test_per_stratum_results_carry_counts_and_say_when_nothing_is_answerable() -> None:
    corpus = Corpus(_sec_like_rows())
    tasks = [
        _task("t1", "a", "Birch Holdings Revenues", ["ev-r1"], stratum="modified"),
        _task("t2", "a", "Cedar Holdings Revenues", ["ev-r2"], stratum="modified"),
        _task("t3", "a", "Birch Holdings Revenues", [], kind="acl_negative", stratum="acl"),
        _task("t4", "a", "Fir Holdings Revenues", ["ev-r5"]),  # no stratum: pooled only
    ]
    entry = run(corpus, tasks, {"exact_token": BASELINES["exact_token"]})["retrievers"]
    by_stratum = entry["exact_token"]["by_stratum"]
    assert set(by_stratum) == {"modified", "acl"}
    assert (by_stratum["modified"]["tasks"], by_stratum["modified"]["answerable_tasks"]) == (2, 2)
    assert by_stratum["modified"]["recall_at_k"] == 1.0
    assert by_stratum["acl"]["tasks"] == 1
    assert by_stratum["acl"]["recall_at_k"] == "no answerable task"
    assert by_stratum["acl"]["source_precision_at_k"] == "no answerable task"
    assert entry["exact_token"]["recall_at_k"]["temporal"] == "no answerable task"


@pytest.mark.parametrize(
    ("row", "fields"),
    [
        ({**_src("a", "x", "   "), "source_id": f"{MARKER}"}, "['text']"),
        (
            {k: v for k, v in _src("a", "x", f"{MARKER} text").items() if k != "evidence_id"},
            "['evidence_id']",
        ),
        ({**_src("a", "x", f"{MARKER} text"), "tenant": 7}, "['tenant']"),
        ({**_src("a", "x", f"{MARKER} text"), "metadata": [MARKER]}, "['metadata']"),
    ],
)
def test_a_row_that_yields_no_candidate_refuses_by_ordinal_and_field(
    row: dict[str, Any], fields: str
) -> None:
    with pytest.raises(CorpusError) as caught:
        Corpus([_src("a", "ok", "Revenue increased."), row])
    message = str(caught.value)
    assert message.startswith("corpus row 1")
    assert fields in message
    assert MARKER not in message


def test_a_non_string_stratum_is_rejected() -> None:
    with pytest.raises(metrics.TaskError):
        metrics.parse_task({**_row("t", "a", "q", ["e"]), "stratum": 3})
    assert metrics.parse_task(_row("t", "a", "q", ["e"], stratum="modified")).stratum == "modified"
