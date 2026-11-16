"""WO-LPC-6B: SEC temporal tasks on the first-reporting accession. Synthetic rows only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benchmark.local_public import pit_rows as pr
from benchmark.local_public import pit_tasks as pt
from benchmark.retrieval_baselines.metrics import parse_moment, parse_task, violates_cut

K, Q, Q2 = "0000000001-25-000001", "0000000001-25-000002", "0000000001-25-000003"
STAMP = {
    K: "2025-03-01T12:00:00+00:00",
    Q: "2025-08-29T20:00:00+00:00",
    Q2: "2025-11-01T20:00:00+00:00",
}


def make(
    adsh: str, tag: str, value: str, first: str | None, valid: bool = True, ddate: str = "20250731"
) -> tuple[dict[str, Any], dict[str, Any]]:
    lid = f"lpc-sec/1/{tag}/p@{adsh}"
    row = {
        "tenant": "lpc-sec",
        "logical_id": lid,
        "source_id": adsh,
        "source_version_id": adsh,
        "evidence_id": f"ev:{lid}",
        "text": f"ACME Corp: {tag}: {value} USD, 2025-05-04 to 2025-08-02.",
        "authority": "official",
        "metadata": {
            "valid_from": "2025-05-04T00:00:00+00:00" if valid else None,
            "valid_to": "2025-08-03T00:00:00+00:00" if valid else None,
            "recorded_at": STAMP[adsh],
            "available_at": STAMP[adsh],
        },
    }
    key = {"cik": "1", "tag": tag, "ddate": ddate, "qtrs": "1", "uom": "USD"}
    return row, {"logical_id": lid, "adsh": adsh, "fsds_key": key, "first_reported_by": first}


def world() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pairs = [
        make(K, "Revenues", "100", K),  # reported in the 10-K ...
        make(Q, "Revenues", "100", K),  # ... and again as a 10-Q comparative
        make(K, "Cost", "10", K, valid=False),  # restated later
        make(Q2, "Cost", "12", K, valid=False),
        make(Q, "NewTag", "5", Q),  # first reported in Q; K precedes it
    ]
    return [p[0] for p in pairs], [p[1] for p in pairs]


def by(tasks: list[dict[str, Any]], stratum: str, text: str) -> list[dict[str, Any]]:
    return [t for t in tasks if t["stratum"] == stratum and text in t["query"]]


def test_comparative_in_later_filing_is_never_a_backdated_target() -> None:
    corpus, index = world()
    res = pt.generate(corpus, index)
    rev = by(res["tasks"], "backdated", "Revenues")
    assert {t["variant"] for t in rev} == {"A", "B"}
    assert all(t["gold_evidence_ids"] in ([], [f"ev:lpc-sec/1/Revenues/p@{K}"]) for t in rev)
    meta = {r["logical_id"]: r for r in corpus}
    a = next(t for t in rev if t["variant"] == "A")
    cut = {k: parse_moment(v, field=k) for k, v in a["cut"].items()}
    assert a["gold_evidence_ids"] == [] and not a["answerable"]
    assert violates_cut(meta[f"lpc-sec/1/Revenues/p@{K}"]["metadata"], cut)  # returning R leaks


def test_cut_b_carries_valid_at_and_known_at_so_later_comparatives_do_not_count() -> None:
    corpus, index = world()
    res = pt.generate(corpus, index)
    b = next(t for t in by(res["tasks"], "backdated", "Revenues") if t["variant"] == "B")
    assert b["gold_evidence_ids"] == [f"ev:lpc-sec/1/Revenues/p@{K}"]
    assert b["cut"] == {
        "valid_at": "2025-08-02T00:00:00+00:00",
        "known_at": "2025-03-01T12:00:01+00:00",
    }
    cut = {k: parse_moment(v, field=k) for k, v in b["cut"].items()}
    md = {r["logical_id"]: r["metadata"] for r in corpus}
    assert not violates_cut(md[f"lpc-sec/1/Revenues/p@{K}"], cut)
    assert violates_cut(md[f"lpc-sec/1/Revenues/p@{Q}"], cut)  # the comparative is not recorded yet


def test_cut_b_needs_validity_and_is_counted_when_absent() -> None:
    corpus, index = world()
    res = pt.generate(corpus, index)
    assert not [t for t in by(res["tasks"], "backdated", "Cost") if t["variant"] == "B"]
    assert res["skipped"]["backdated_cut_b_no_validity"] == 1


def test_modified_gold_is_a_only_and_b_shares_the_query_tokens() -> None:
    corpus, index = world()
    res = pt.generate(corpus, index)
    (m,) = by(res["tasks"], "modified", "Cost")
    assert m["gold_evidence_ids"] == [f"ev:lpc-sec/1/Cost/p@{K}"]
    assert m["cut"] == {"known_at": "2025-03-01T12:00:01+00:00"}
    b_row = next(r for r in corpus if r["source_id"] == Q2)
    assert m["query"] in b_row["text"].replace(" 12 USD,", "")  # same tokens, value removed
    assert violates_cut(
        b_row["metadata"], {"known_at": parse_moment(m["cut"]["known_at"], field="k")}
    )
    assert not by(res["tasks"], "modified", "Revenues")  # same value later: not a modification


def test_added_later_abstains_inside_previous_filing_window() -> None:
    corpus, index = world()
    res = pt.generate(corpus, index)
    (t,) = by(res["tasks"], "added_later", "NewTag")
    assert t["gold_evidence_ids"] == [] and not t["answerable"]
    known = parse_moment(t["cut"]["known_at"], field="known_at")
    assert parse_moment(STAMP[K], field="x") <= known < parse_moment(STAMP[Q], field="x")
    row = next(r for r in corpus if r["logical_id"].endswith(f"NewTag/p@{Q}"))
    assert violates_cut(row["metadata"], {"known_at": known})
    assert not by(res["tasks"], "added_later", "Revenues")  # K is the CIK's first filing


def test_sec_late_recorded_is_refused() -> None:
    corpus, index = world()
    with pytest.raises(pt.PitTaskError, match="late_recorded"):
        pt.generate(corpus, index, strata=("late_recorded",))


def test_every_task_passes_parse_task_and_ids_are_unique() -> None:
    res = pt.generate(*world())
    ids = [t["task_id"] for t in res["tasks"]]
    assert ids and len(set(ids)) == len(ids)
    for t in res["tasks"]:
        parse_task(t)


def test_unresolved_first_reporter_is_skipped_not_guessed() -> None:
    corpus, index = world()
    for i in index:
        i["first_reported_by"] = None
    res = pt.generate(corpus, index)
    assert res["tasks"] == [] and res["skipped"]["first_reporting_unresolved"] == 3


def test_index_must_cover_the_corpus() -> None:
    corpus, index = world()
    with pytest.raises(pt.PitTaskError):
        pt.generate(corpus, index[:-1])


def test_alfred_absent_is_counted_and_present_is_merged() -> None:
    corpus, index = world()
    assert pt.generate(corpus, index)["skipped"]["alfred_input_absent"] == 1
    extra_row = {"logical_id": "alfred/x", "evidence_id": "ev:alfred/x"}
    extra_task = {
        "task_id": "late_recorded-alfred-1", "kind": "temporal", "stratum": "late_recorded",
        "tenant": "t", "query": "UNRATE 2020-01-01", "cut": {"known_at": STAMP[K]},
        "gold_evidence_ids": [], "answerable": False, "provenance": "generated",
        "generator": "alfred", "seed": 0,
    }  # fmt: skip
    res = pt.generate(corpus, index, alfred=([extra_row], [extra_task]))
    assert "alfred_input_absent" not in res["skipped"]
    assert extra_row in res["corpus"] and extra_task in res["tasks"]


def test_max_per_stratum_caps_deterministically() -> None:
    a = pt.generate(*world(), seed=3, max_per_stratum=1)
    b = pt.generate(*world(), seed=3, max_per_stratum=1)
    assert a["tasks"] == b["tasks"]
    assert all(sum(t["stratum"] == s for t in a["tasks"]) <= 1 for s in pt.STRATA)


def test_shortfall_exits_1_and_reports_the_number(tmp_path: Path) -> None:
    rows = tmp_path / "rows"
    rows.mkdir()
    corpus, index = world()
    (rows / "corpus.jsonl").write_text("".join(json.dumps(r) + "\n" for r in corpus), "utf-8")
    (rows / "rows_index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in index), "utf-8")
    (rows / "pit_rows_meta.json").write_text(json.dumps({"valid_time_basis": pr.BASIS}), "utf-8")
    out = tmp_path / "out"
    assert pt.main(["build", "--rows-dir", str(rows), "--out", str(out)]) == 1
    man = json.loads((out / "tasks_manifest.json").read_text("utf-8"))
    assert man["floor"] == 200 and man["shortfall"] == 200 - man["tasks"] > 0
    assert man["valid_time_basis"] == pr.BASIS and man["statements"]
    assert len((out / "tasks.jsonl").read_text("utf-8").splitlines()) == man["tasks"]


def test_missing_rows_dir_refuses(tmp_path: Path) -> None:
    assert (
        pt.main(["build", "--rows-dir", str(tmp_path / "nope"), "--out", str(tmp_path / "o")]) == 1
    )
