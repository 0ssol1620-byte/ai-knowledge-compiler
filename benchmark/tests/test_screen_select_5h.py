"""WO-D08-7: section 5H selection on synthetic records with planted outcomes.

Records are made the way run_screen makes them: from an output text scored by reader v1.
No real corpus, no real gold.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import pytest
from akc_router.complementarity import RescueMeasurement

from benchmark.evaluators import metrics as scorer
from benchmark.runners.base import RunnerUnavailable
from benchmark.screen import select_5h as s5
from benchmark.screen.critical_fields import score_critical_fields
from benchmark.screen.manifest import HoldoutGuard, HoldoutSealedError
from benchmark.screen.run_screen import Candidate, run_screen
from benchmark.v6.contracts import ContractError

H_PAGES = [f"h{i:02d}.pdf#0" for i in range(20)]
R_PAGES = [f"r{i:02d}.pdf#0" for i in range(10)]
X_PAGES = [f"x{i:02d}.pdf#0" for i in range(4)]
FIELDS = (("f1", "Revenue", 100), ("f2", "Net income", 500))
HF = [(p, f) for p in H_PAGES for f, _, _ in FIELDS]
RF = [(p, f) for p in R_PAGES for f, _, _ in FIELDS]


def make_gold(shift: int = 0) -> dict[str, dict[str, Any]]:
    return {
        p: {
            "critical_fields": [
                {"field_id": f, "kind": "number", "value": str(base + i + shift), "anchor": a}
                for f, a, base in FIELDS
            ]
        }
        for i, p in enumerate(H_PAGES + R_PAGES + X_PAGES)
    }


GOLD = make_gold()


def guard(tmp_path: Path) -> HoldoutGuard:
    docs = [
        {"doc_id": p[:-2], "page_count": 1, "split": "dev", "page_origin": origin}
        for pages, origin in ((H_PAGES, s5.DEGRADED), (R_PAGES, "born_digital_html_print"))
        for p in pages
    ] + [
        {"doc_id": p[:-2], "page_count": 1, "split": "holdout", "page_origin": s5.DEGRADED}
        for p in X_PAGES
    ]
    return HoldoutGuard(
        {"manifest_sha256": "sha256:" + "e" * 64, "documents": docs},
        tmp_path / "holdout-access.jsonl",
    )


def wrong(fields: list[tuple[str, str]], k: int = 1) -> dict[tuple[str, str], Any]:
    return dict.fromkeys(fields, k)


def text_for(page: str, plan: dict[tuple[str, str], Any]) -> str | None:
    """'R' right (default), int k = gold + k, 'A' anchor absent, 'F' page failed."""
    outs = [plan.get((page, f), "R") for f, _, _ in FIELDS]
    if "F" in outs:
        return None
    lines = []
    for (f, a, _), o in zip(FIELDS, outs, strict=True):
        gold = int(next(x["value"] for x in GOLD[page]["critical_fields"] if x["field_id"] == f))
        if o != "A":
            lines.append(f"{a} {gold + (0 if o == 'R' else o)}")
    return "\n".join(lines)


def world(
    plans: dict[str, dict[tuple[str, str], Any]],
    *,
    gold: dict[str, dict[str, Any]] = GOLD,
    cost: dict[str, float | None] | None = None,
    pages: list[str] | None = None,
    split: str = "dev",
    raw_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    records, texts = [], {}
    for cand, plan in plans.items():
        for page in pages or H_PAGES + R_PAGES:
            text = text_for(page, plan)
            fields = gold[page]["critical_fields"]
            key = "sha256:" + hashlib.sha256(f"{cand}|{page}".encode()).hexdigest()
            raw_sha = None
            exact = 0
            if text is not None:
                data = json.dumps({"text": text}).encode()
                raw_sha = "sha256:" + hashlib.sha256(data).hexdigest()
                texts[raw_sha] = text
                exact = score_critical_fields(fields, text).exact
                if raw_dir is not None:
                    (raw_dir / (key.removeprefix("sha256:") + ".json")).write_bytes(data)
            records.append(
                {
                    "page_id": page,
                    "doc_id": page[:-2],
                    "stratum": "en_native",
                    "split": split,
                    "candidate_id": cand,
                    "revision": "a" * 40,
                    "image_digest": "sha256:" + "b" * 64,
                    "config_sha256": "sha256:" + hashlib.sha256(cand.encode()).hexdigest(),
                    "raw_sha256": raw_sha,
                    "metrics": {},
                    "critical": {
                        "n": len(fields),
                        "exact": exact,
                        "accepted_errors": len(fields) - exact if text is not None else 0,
                    },
                    "hard_failures": [] if text is not None else ["provider_error"],
                    "provider_cost_usd": (cost or {}).get(cand, 0.01),
                    "latency_ms": 100,
                    "record_key": key,
                }
            )
    return records, texts


# ---------------------------------------------------------------- S1


def test_planted_clear_loser_dropped_near_tie_kept_baseline_kept(tmp_path: Path) -> None:
    half = wrong(HF[:20]) | wrong(RF[:10])
    recs, _ = world(
        {
            "L": {},
            "N": wrong(HF[:1]),  # near tie: 39/40 on H
            "X": half,  # clear loser on H and R
            "C0": half,  # also a clear loser, but the baseline
            "Y": wrong(HF[:20]),  # loses on H only: not a clear loser
            "M": wrong(HF[:2]),  # a fourth survivor, so only the baseline rule keeps C0
        }
    )
    s1 = s5.select_s1(recs, guard=guard(tmp_path), baseline="C0")
    assert s1["leader"] == "L"
    assert s1["clear_losers"] == ["C0", "X"]
    assert s1["dropped"] == ["X"]
    assert s1["kept"] == ["L", "N", "M", "C0", "Y"]  # C0 ties Y on H: baseline first
    assert (
        s1["cells"]["H"]["X"]["critical_exact_ci"][1]
        < s1["cells"]["H"]["L"]["critical_exact_ci"][0]
    )
    m = s1["mcnemar_vs_leader"]["H"]["X"]
    assert (m["candidate_only_exact"], m["incumbent_only_exact"]) == (0, 10)
    assert m["mcnemar_p"] < 0.01


def test_more_than_five_keeps_top_five_by_rank_key(tmp_path: Path) -> None:
    plans = {f"c{i}": wrong(HF[:i]) | wrong(RF[:1]) for i in range(5)}
    plans["C0"] = wrong(HF[:6]) | wrong(RF[:1])  # a non-loser, seventh by rank: carried (5H-16)
    plans["rbest"] = wrong(HF[:5])  # sixth on H, only one perfect on R
    recs, _ = world(plans)
    s1 = s5.select_s1(recs, guard=guard(tmp_path), baseline="C0")
    assert s1["clear_losers"] == []
    assert s1["best_on_R"] == "rbest"
    assert s1["kept"] == ["c0", "c1", "c2", "c3", "c4", "C0"]
    assert s1["dropped"] == ["rbest"]


def test_clear_loser_baseline_is_kept_in_addition_to_five_non_losers(tmp_path: Path) -> None:
    plans = {f"c{i}": wrong(HF[:i]) for i in range(7)}
    plans["C0"] = wrong(HF[:20]) | wrong(RF[:10])  # a clear loser
    recs, _ = world(plans)
    s1 = s5.select_s1(recs, guard=guard(tmp_path), baseline="C0")
    assert s1["clear_losers"] == ["C0"]
    assert s1["kept"] == ["c0", "c1", "c2", "c3", "c4", "C0"]  # six: never displaces a non-loser
    assert s1["dropped"] == ["c5", "c6"]


def test_fewer_than_four_tops_up_from_h_order(tmp_path: Path) -> None:
    half = wrong(HF[:20]) | wrong(RF[:10])
    recs, _ = world(
        {
            "L": {},
            "C0": half,
            "x1": wrong(HF[:24]) | wrong(RF[:10]),
            "x2": wrong(HF[:22]) | wrong(RF[:10]),
            "x3": wrong(HF[:26]) | wrong(RF[:10]),
            "x4": wrong(HF[:28]) | wrong(RF[:10]),
        }
    )
    s1 = s5.select_s1(recs, guard=guard(tmp_path), baseline="C0")
    assert s1["clear_losers"] == ["C0", "x1", "x2", "x3", "x4"]
    # L topped up to four non-baseline candidates by H rank; C0 carried beside them (5H-16).
    assert s1["kept"] == ["L", "C0", "x2", "x1", "x3"]
    assert s1["dropped"] == ["x4"]


def test_ties_are_deterministic_and_bytes_repeat(tmp_path: Path) -> None:
    recs, _ = world({"zz": {}, "aa": {}, "C0": wrong(HF[:2])})
    s1 = s5.select_s1(recs, guard=guard(tmp_path), baseline="C0")
    assert s1["leader"] == "aa"  # equal cells: id order
    shuffled = copy.deepcopy(recs[::-1])
    assert s5.dump(s5.select_s1(shuffled, guard=guard(tmp_path), baseline="C0")) == s5.dump(s1)
    tie, _ = world({"zz": {}, "C0": {}})
    assert s5.select_s1(tie, guard=guard(tmp_path), baseline="C0")["leader"] == "C0"


def test_s1_refuses_holdout_missing_and_duplicate_pages(tmp_path: Path) -> None:
    recs, _ = world({"L": {}, "C0": {}})
    hold, _ = world({"L": {}}, pages=X_PAGES[:1], split="holdout")
    with pytest.raises(HoldoutSealedError):
        s5.select_s1(recs + hold, guard=guard(tmp_path), baseline="C0")
    with pytest.raises(ValueError, match="no terminal record"):
        s5.select_s1(recs[1:], guard=guard(tmp_path), baseline="C0")
    with pytest.raises(ValueError, match="duplicate"):
        s5.select_s1([*recs, recs[0]], guard=guard(tmp_path), baseline="C0")
    with pytest.raises(ValueError, match="fewer than 2"):
        s5.select_s1(
            [r for r in recs if r["candidate_id"] == "C0"], guard=guard(tmp_path), baseline="C0"
        )


# ---------------------------------------------------------------- S2


def _s2(tmp_path: Path, plans: dict[str, Any], cost: dict[str, float | None]) -> dict[str, Any]:
    recs, texts = world(plans, cost=cost)
    g = guard(tmp_path)
    return s5.complementarity_s2(
        recs, texts, GOLD, guard=g, s1=s5.select_s1(recs, guard=g, baseline="C0")
    )


def test_matrix_denominators_and_pick_by_rescued_per_usd(tmp_path: Path) -> None:
    plans = {
        "L": wrong(HF[:8]) | wrong(RF[:2]),
        "B": wrong(HF[6:15], 2),  # rescues 6 of L's 8 on H
        "C": wrong(HF[20:30], 3),  # rescues all 8, but five times the cost
        "C0": wrong(HF) | wrong(RF),
    }
    s2 = _s2(tmp_path, plans, {"L": 0.01, "B": 0.02, "C": 0.10, "C0": 0.01})
    rows = {(r["baseline"], r["peer"]): r for r in s2["matrix"]["H"]}
    lb = rows[("L", "B")]
    assert {f.name for f in dataclasses.fields(RescueMeasurement)} <= set(lb)
    assert (lb["baseline_wrong_pages"], lb["rescued_fields"], lb["both_wrong_fields"]) == (8, 6, 2)
    assert (lb["scored_pages"], lb["rescue_rate"], lb["both_wrong_rate"]) == (40, 0.75, 2 / 40)
    assert lb["denominator"] == "8 fields L got wrong, of 40 scored"
    r_lb = next(r for r in s2["matrix"]["R"] if (r["baseline"], r["peer"]) == ("L", "B"))
    assert (r_lb["baseline_wrong_pages"], r_lb["rescued_fields"], r_lb["scored_pages"]) == (
        2,
        2,
        20,
    )
    p_lb = next(r for r in s2["matrix"]["pooled"] if (r["baseline"], r["peer"]) == ("L", "B"))
    assert (p_lb["baseline_wrong_pages"], p_lb["rescued_fields"], p_lb["scored_pages"]) == (
        10,
        8,
        60,
    )
    c0 = next(r for r in s2["matrix"]["H"] if (r["baseline"], r["peer"]) == ("L", "C0"))
    assert (c0["rescued_fields"], c0["both_wrong_rate"]) == (0, 8 / 40)
    assert s2["members"] == ["L", "B"]  # 300 fields/USD beats 80
    third = s2["pick_steps"][1]
    assert third["chosen"] is None and third["fields_missed_by_members"] == 2
    assert {o["candidate"]: o["excluded"] for o in third["options"]}[
        "C"
    ] == "marginal_below_minimum"


def test_third_member_given_the_pair_and_unknown_cost(tmp_path: Path) -> None:
    plans = {
        "L": wrong(HF[:8]),
        "B": wrong(HF[4:15], 2),  # rescues HF[0:4]
        "C": wrong(HF[20:30], 3),  # rescues the 4 the pair still misses
        "D": wrong(HF[30:40], 4),
        "C0": wrong(HF) | wrong(RF),
    }
    s2 = _s2(tmp_path, plans, {"L": 0.01, "B": 0.02, "C": 0.10, "D": None, "C0": 0.01})
    assert s2["members"] == ["L", "B", "C"]
    second = {o["candidate"]: o for o in s2["pick_steps"][0]["options"]}
    assert second["D"]["excluded"] == "cost_unknown"
    assert second["B"]["rescued_per_usd"] == pytest.approx(200.0)
    assert s2["pick_steps"][1]["chosen"] == "C"


def test_failed_page_is_all_wrong_and_text_must_match_record(tmp_path: Path) -> None:
    plans = {"L": {}, "B": {(H_PAGES[0], "f1"): "F"}, "C": {}, "C0": wrong(HF)}
    raw = tmp_path / "raw"
    raw.mkdir()
    recs, texts = world(plans, raw_dir=raw)
    g = guard(tmp_path)
    s2 = s5.complementarity_s2(
        recs, texts, GOLD, guard=g, s1=s5.select_s1(recs, guard=g, baseline="C0")
    )
    bl = next(r for r in s2["matrix"]["H"] if (r["baseline"], r["peer"]) == ("B", "L"))
    assert (bl["baseline_wrong_pages"], bl["rescued_fields"]) == (2, 2)
    forged = copy.deepcopy(recs)
    next(r for r in forged if r["candidate_id"] == "L")["critical"]["exact"] = 1
    with pytest.raises(ValueError, match="record says"):
        s5.complementarity_s2(
            forged, texts, GOLD, guard=g, s1=s5.select_s1(forged, guard=g, baseline="C0")
        )
    # A contract failure keeps its raw text, and its fields are still all wrong and unread.
    failed = copy.deepcopy(recs)
    c_h0 = next(r for r in failed if (r["candidate_id"], r["page_id"]) == ("C", H_PAGES[0]))
    c_h0["hard_failures"] = ["contract_failed"]
    c_h0["critical"] = {"n": 2, "exact": 0, "accepted_errors": 0}
    s2 = s5.complementarity_s2(
        failed, texts, GOLD, guard=g, s1=s5.select_s1(failed, guard=g, baseline="C0", raw_dir=raw)
    )
    lc = next(r for r in s2["matrix"]["H"] if (r["baseline"], r["peer"]) == ("C", "L"))
    assert (lc["baseline_wrong_pages"], lc["rescued_fields"]) == (2, 2)
    s3 = s5.signals_s3(failed, texts, GOLD, guard=g, members=["C", "L"], escalate_on=["no_value"])
    assert s3["scores"]["H"]["no_value"]["flagged"] == 2


def test_load_texts_reads_raw_files_and_refuses_a_changed_byte(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    recs, texts = world({"L": {(H_PAGES[0], "f1"): "F"}}, raw_dir=raw)
    assert s5.load_texts(recs, raw) == texts
    victim = next(raw.iterdir())
    victim.write_bytes(victim.read_bytes().replace(b"Revenue", b"Revenuf"))
    with pytest.raises(ContractError, match="differs"):
        s5.load_texts(recs, raw)
    escape = {**recs[1], "record_key": "sha256:../" + "a" * 61}
    with pytest.raises(ContractError, match="record_key"):
        s5.load_texts([escape], raw)
    # A raw output that is not an object (a contract failure) has no text, and no crash.
    data = b"[1, 2]"
    (raw / ("f" * 64 + ".json")).write_bytes(data)
    listed = {**recs[1], "record_key": "sha256:" + "f" * 64}
    listed["raw_sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    assert s5.load_texts([listed], raw) == {listed["raw_sha256"]: ""}


def test_s2_stop_rule_skips_a_cheap_candidate_that_rescues_almost_nothing(
    tmp_path: Path,
) -> None:
    plans = {
        "L": wrong(HF[:8]),
        "cheap": wrong(HF[2:8], 2) | wrong(HF[20:30], 3),  # rescues HF 0-1 only: 2 < 3
        "dear": wrong(HF[:3], 2) | wrong(HF[20:30], 3),  # rescues HF 3-7: 5 fields
        "C0": wrong(HF) | wrong(RF),
    }
    s2 = _s2(tmp_path, plans, {"L": 0.01, "cheap": 0.001, "dear": 0.5, "C0": 0.01})
    first = {o["candidate"]: o for o in s2["pick_steps"][0]["options"]}
    assert first["cheap"]["excluded"] == "marginal_below_minimum"
    assert s2["members"][:2] == ["L", "dear"]
    assert s2["pick_steps"][-1]["chosen"] is None  # searched until none was left


def test_cost_is_the_mean_of_known_pages_and_unknown_only_above_a_fifth(tmp_path: Path) -> None:
    plans = {
        "L": wrong(HF[:8]),
        "B": wrong(HF[6:15], 2) | {(H_PAGES[0], "f1"): "F"},
        "D": wrong(HF[4:14], 2),  # rescues HF 0-3
        "C0": wrong(HF) | wrong(RF),
    }
    recs, texts = world(plans, cost={"L": 0.01, "B": 0.02, "D": 0.02, "C0": 0.01})
    for r in recs:
        if r["candidate_id"] == "B" and r["page_id"] in H_PAGES[:2]:
            r["provider_cost_usd"] = None  # 2 of 20 H pages: under a fifth
        if r["candidate_id"] == "D" and r["page_id"] in H_PAGES[:5]:
            r["provider_cost_usd"] = None  # 5 of 20 H pages: above a fifth
    g = guard(tmp_path)
    s2 = s5.complementarity_s2(
        recs, texts, GOLD, guard=g, s1=s5.select_s1(recs, guard=g, baseline="C0")
    )
    opts = {o["candidate"]: o for o in s2["pick_steps"][0]["options"]}
    assert opts["B"]["excluded"] is None
    assert opts["B"]["cost_per_page_usd"] == pytest.approx(0.02)
    assert (opts["B"]["cost_pages_known"], opts["B"]["cost_pages_total"]) == (18, 20)
    assert opts["D"]["excluded"] == "cost_unknown"
    assert (opts["D"]["cost_pages_known"], opts["D"]["cost_pages_total"]) == (15, 20)
    assert s2["members"][:2] == ["L", "B"]


def test_s2_refuses_an_s1_computed_from_other_records(tmp_path: Path) -> None:
    recs, texts = world({"L": {}, "B": wrong(HF[:4]), "C0": wrong(HF[:2])})
    g = guard(tmp_path)
    s1 = s5.select_s1(recs, guard=g, baseline="C0")
    other = copy.deepcopy(recs)
    next(r for r in other if r["candidate_id"] == "B")["latency_ms"] = 7
    with pytest.raises(ContractError, match="S1"):
        s5.complementarity_s2(other, texts, GOLD, guard=g, s1=s1)
    other_manifest = {**s1, "inputs": {**s1["inputs"], "manifest_sha256": "sha256:" + "0" * 64}}
    with pytest.raises(ContractError, match="S1"):
        s5.complementarity_s2(recs, texts, GOLD, guard=g, s1=other_manifest)


# ---------------------------------------------------------------- S3


def _s3_plans() -> dict[str, dict[tuple[str, str], Any]]:
    return {
        "P": wrong(HF[:6]) | {HF[6]: "A"} | wrong(RF[:2]),
        # Q: same wrong value on HF 0-1 and RF 0-1 (agrees), another on 2-3, right on 4-6,
        # wrong where P is right on 10-11.
        "Q": wrong(HF[:2]) | wrong(HF[2:4], 2) | wrong(HF[10:12], 3) | wrong(RF[:2]),
        "S": {},
    }


def test_signals_are_raised_without_gold_and_scored_with_it(tmp_path: Path) -> None:
    def run(gold: dict[str, Any]) -> dict[str, Any]:
        recs, texts = world(_s3_plans(), gold=gold)
        return s5.signals_s3(
            recs,
            texts,
            gold,
            guard=guard(tmp_path),
            members=["P", "Q"],
            escalate_on=["disagreement", "no_value"],
        )

    base = run(GOLD)
    h = base["scores"]["H"]
    assert h["disagreement"]["flagged"] == 7  # HF 2-6 and 10-11
    assert h["no_value"]["flagged"] == 1  # HF 6
    assert h["escalate"]["flagged"] == 7
    # P wrong on 7 H fields; HF 0-1 slip through because Q agrees with the wrong value.
    assert (h["escalate"]["false_accepts"], h["escalate"]["unflagged"]) == (2, 33)
    assert h["escalate"]["wasted_escalations"] == 2  # HF 10-11: P right, Q wrong
    assert h["disagreement"]["auroc_wrong_by_disagreeing_peers"] is not None
    assert base["scores"]["R"]["escalate"]["false_accepts"] == 2
    # Same outputs, every gold value moved: signals must not move, only their scores.
    moved = run(make_gold(shift=7000))
    for part in ("H", "R"):
        for name in ("disagreement", "no_value", "escalate"):
            assert moved["scores"][part][name]["flagged"] == base["scores"][part][name]["flagged"]
    assert moved["scores"]["H"]["escalate"]["false_accepts"] == 33


def test_s3_refuses_duplicate_members(tmp_path: Path) -> None:
    recs, texts = world(_s3_plans())
    with pytest.raises(ValueError, match="duplicate"):
        s5.signals_s3(
            recs,
            texts,
            GOLD,
            guard=guard(tmp_path),
            members=["P", "Q", "P"],
            escalate_on=["no_value"],
        )


def test_reread_signal_optional_and_holdout_needs_the_recipe(tmp_path: Path) -> None:
    recs, texts = world(_s3_plans())
    g = guard(tmp_path)
    with pytest.raises(ValueError, match="measured"):
        s5.signals_s3(
            recs, texts, GOLD, guard=g, members=["P", "Q"], escalate_on=["reread_differs"]
        )
    reread = {p: text_for(p, {}) for p in H_PAGES + R_PAGES}
    out = s5.signals_s3(
        recs,
        texts,
        GOLD,
        guard=g,
        members=["P", "Q", "S"],
        escalate_on=["reread_differs"],
        reread_texts=reread,
    )
    assert out["scores"]["H"]["reread_differs"]["flagged"] == 7  # every field P got wrong
    hold, htexts = world(_s3_plans(), pages=X_PAGES, split="holdout")
    with pytest.raises(HoldoutSealedError):
        s5.signals_s3(
            hold,
            htexts,
            GOLD,
            guard=g,
            members=["P", "Q"],
            escalate_on=["disagreement"],
            split="holdout",
        )
    assert not (tmp_path / "holdout-access.jsonl").exists()
    recipe = _recipe(tmp_path, ["P", "Q"], ["disagreement"])
    digest = recipe["recipe_sha256"]
    out = s5.signals_s3(
        hold,
        htexts,
        GOLD,
        guard=g,
        members=["P", "Q"],
        escalate_on=["disagreement"],
        split="holdout",
        frozen_recipe_sha256=digest,
        recipe=recipe,
    )
    assert out["split"] == "holdout" and out["frozen_recipe_sha256"] == digest
    assert digest in (tmp_path / "holdout-access.jsonl").read_text(encoding="utf-8")


def _recipe(tmp_path: Path, members: list[str], escalate_on: list[str]) -> dict[str, Any]:
    # P and Q tie (P first by id); Q rescues the six fields P misses: S2 picks exactly P, Q.
    plans = {"P": wrong(HF[:6]), "Q": wrong(HF[6:12], 2), "C0": wrong(HF)}
    recs, texts = world(plans)
    g = guard(tmp_path / "recipe")
    (tmp_path / "recipe").mkdir(exist_ok=True)
    s1 = s5.select_s1(recs, guard=g, baseline="C0")
    s2 = s5.complementarity_s2(recs, texts, GOLD, guard=g, s1=s1)
    assert s2["members"] == members
    return s5.build_recipe(
        records=recs,
        s1=s1,
        s2=s2,
        escalate_on=escalate_on,
        degradation={"seed": 1, "parameters": {}},
        scoring_commit="1" * 40,
        section_sha256="sha256:" + "2" * 64,
    )


def test_holdout_output_is_compared_with_the_frozen_recipe_body(tmp_path: Path) -> None:
    recipe = _recipe(tmp_path, ["P", "Q"], ["disagreement"])
    digest = recipe["recipe_sha256"]
    hold, htexts = world(_s3_plans(), pages=X_PAGES, split="holdout")
    g = guard(tmp_path)
    base: dict[str, Any] = {
        "guard": g,
        "members": ["P", "Q"],
        "escalate_on": ["disagreement"],
        "split": "holdout",
        "frozen_recipe_sha256": digest,
        "recipe": recipe,
    }
    bad: dict[str, dict[str, Any]] = {
        "members": {"members": ["Q", "P"]},
        "signals": {"escalate_on": ["no_value"]},
        "digest": {"frozen_recipe_sha256": "sha256:" + "0" * 64},
        "no body": {"recipe": None},
        "tampered": {"recipe": {**recipe, "member_order": ["P", "Q", "S"]}},
    }
    for pin, value in (
        ("revision", "e" * 40),
        ("image_digest", "sha256:" + "e" * 64),
        ("config_sha256", "sha256:" + "e" * 64),
    ):
        moved = copy.deepcopy(hold)
        next(r for r in moved if r["candidate_id"] == "Q")[pin] = value
        with pytest.raises(ContractError, match="pins differ"):
            s5.signals_s3(moved, htexts, GOLD, **base)
        assert not (tmp_path / "holdout-access.jsonl").exists(), pin
    for name, change in bad.items():
        with pytest.raises(ContractError):
            s5.signals_s3(hold, htexts, GOLD, **{**base, **change})
        assert not (tmp_path / "holdout-access.jsonl").exists(), name


# ---------------------------------------------------------------- recipe


def test_recipe_digest_moves_with_every_listed_input(tmp_path: Path, monkeypatch: Any) -> None:
    plans = {"L": wrong(HF[:8]), "B": wrong(HF[6:15], 2), "C": wrong(HF[20:30], 3), "C0": wrong(HF)}
    recs, texts = world(plans)
    g = guard(tmp_path)
    s1 = s5.select_s1(recs, guard=g, baseline="C0")
    s2 = s5.complementarity_s2(recs, texts, GOLD, guard=g, s1=s1)
    args: dict[str, Any] = {
        "records": recs,
        "s1": s1,
        "s2": s2,
        "escalate_on": ["disagreement", "no_value"],
        "degradation": {"seed": 11, "parameters": {"scan_poor": {"dpi": 100}}},
        "scoring_commit": "1" * 40,
        "section_sha256": "sha256:" + "2" * 64,
    }
    base = s5.build_recipe(**args)
    assert base == s5.build_recipe(**copy.deepcopy(args))
    assert base["member_order"] == s2["members"]
    repinned = copy.deepcopy(recs)
    for r in repinned:
        if r["candidate_id"] == s2["members"][1]:
            r["image_digest"] = "sha256:" + "9" * 64
    for lineage in ({"records": repinned}, {"s1": {**s1, "leader": "x"}}):
        with pytest.raises(ContractError, match="lineage"):
            s5.build_recipe(**{**args, **lineage})
    s1b = s5.select_s1(repinned, guard=g, baseline="C0")
    s2b = s5.complementarity_s2(repinned, texts, GOLD, guard=g, s1=s1b)
    # WO-D08-9: a reordered member list is no longer a different recipe; it is refused.
    with pytest.raises(ContractError, match="chain"):
        s5.build_recipe(**{**args, "s2": {**s2, "members": list(reversed(s2["members"]))}})
    changes = {
        "records": repinned,
        "s1": s1b,
        "escalate_on": ["disagreement"],
        "degradation": {"seed": 12, "parameters": {"scan_poor": {"dpi": 100}}},
        "scoring_commit": "3" * 40,
        "section_sha256": "sha256:" + "4" * 64,
    }
    for name, value in changes.items():
        moved = {**args, name: value}
        if name in ("records", "s1"):
            moved = {**moved, "records": repinned, "s1": s1b, "s2": s2b}
        assert s5.build_recipe(**moved)["recipe_sha256"] != base["recipe_sha256"], name
    with pytest.raises(ContractError, match="duplicate"):
        s5.build_recipe(**{**args, "s2": {**s2, "members": [s2["members"][0]] * 2}})
    with pytest.raises(ContractError, match="not in S1"):
        s5.build_recipe(**{**args, "s2": {**s2, "members": [*s2["members"], "zz"]}})
    params = {"seed": 11, "parameters": {"scan_poor": {"dpi": 101}}}
    assert (
        s5.build_recipe(**{**args, "degradation": params})["recipe_sha256"] != base["recipe_sha256"]
    )
    split_pins = copy.deepcopy(recs)
    split_pins[0]["revision"] = "f" * 40
    s1c = s5.select_s1(split_pins, guard=g, baseline="C0")
    s2c = s5.complementarity_s2(split_pins, texts, GOLD, guard=g, s1=s1c)
    with pytest.raises(ContractError, match="pins"):
        s5.build_recipe(**{**args, "records": split_pins, "s1": s1c, "s2": s2c})
    monkeypatch.setattr(s5, "READER_V1_SHA256", "sha256:" + "0" * 64)
    with pytest.raises(ContractError, match="reader v1"):
        s5.build_recipe(**args)


# ---------------------------------------------------------------- WO-D08-9


def _truth(i: int) -> dict[str, Any]:
    """Shaped like benchmark.local_public.sec_screen._truth: high_risk and the whole page text."""
    return {
        "critical_fields": [
            {
                "field_id": f"us-gaap:{name}",
                "kind": "number",
                "value": str(base + i),
                "anchor": anchor,
                "ixbrl": {
                    "context_id": "c-1",
                    "start": None,
                    "end": "2026-09-30",
                    "scale": "0",
                    "sign": "",
                    "sign_basis": "fsds",
                },
                "fsds": {"quarter": "2026q3", "adsh": "0000000000-26-000001", "tag": name},
            }
            for name, anchor, base in (
                ("NetIncomeLoss", "Net income", 2000),
                ("Revenues", "Revenue", 1000),
            )
        ],
        "high_risk": True,
        "text": f"Page {i + 7}\nRevenue {1000 + i}\nNet income {2000 + i}\nSee note {i + 3}.",
        "text_source": "html_dom_text",
        "gold_source": "sec_fsds_inline_xbrl",
        "selection_condition": "dom_rule_v2",
        "lpc_manifest_sha256": "sha256:" + "c" * 64,
    }


def _screen(
    tmp_path: Path, plans: dict[str, dict[int, str]], n_h: int = 6, n_r: int = 4
) -> tuple[HoldoutGuard, list[dict[str, Any]], dict[str, dict[str, Any]], Path]:
    """Records written by the real run_screen with a fake runner. Plan values per page index:
    'both' (default), 'one' (Net income misread, CER lower), or a failure: 'unavailable',
    'raise', or a failure.reason the page server answers with (stored raw, recorded
    contract_failed)."""
    corpus, raw = tmp_path / "corpus", tmp_path / "raw"
    corpus.mkdir()
    docs, gold, index = [], {}, {}
    for i in range(n_h + n_r):
        name = f"{'h' if i < n_h else 'r'}{i:02d}.pdf"
        body = f"synthetic page {i}".encode()
        (corpus / name).write_bytes(body)
        docs.append(
            {
                "doc_id": name,
                "source_sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
                "page_count": 1,
                "stratum": "en_native",
                "language": "en",
                "document_class": "sec_statement",
                "split": "dev",
                "page_origin": s5.DEGRADED if i < n_h else "born_digital_html_print",
            }
        )
        gold[f"{name}#0"] = _truth(i)
        index[name] = i
    g = HoldoutGuard({"manifest_sha256": "sha256:" + "e" * 64, "documents": docs}, tmp_path / "log")
    records: list[dict[str, Any]] = []
    for cand, plan in plans.items():

        def call(c: Candidate, case: dict[str, Any], root: Path, plan: Any = plan) -> Any:
            i = index[case["source"]["path"]]
            how = plan.get(i, "both")
            if how == "unavailable":
                raise RunnerUnavailable("pod down")
            if how == "raise":
                raise RuntimeError("runner crashed")
            if how not in ("both", "one"):
                return {"benchmark_case_id": case["benchmark_case_id"], "failure": {"reason": how}}
            # 'one' keeps the page number and the note (lower CER) but misreads Net income.
            text = (
                f"Revenue {1000 + i}\nNet income {2000 + i}"
                if how == "both"
                else f"Page {i + 7}\nRevenue {1000 + i}\nNet income 9999\nSee note {i + 3}."
            )
            return {
                "schema_version": "1.0",
                "benchmark_case_id": case["benchmark_case_id"],
                "provider": "mineru",
                "model_revision": "a" * 40,
                "text": text,
                "reading_order": [],
                "blocks": [],
                "generated_claims": [],
                "metrics": {"latency_ms": 5.0, "estimated_cost_usd": 0.01},
                "warnings": [],
            }

        records += run_screen(
            guard=g,
            split="dev",
            purpose="tune",
            candidate=Candidate(
                cand, "mineru", "a" * 40, "sha256:" + "1" * 64, "sha256:" + "2" * 64
            ),
            corpus_root=corpus,
            gold=gold,
            raw_dir=raw,
            records_path=tmp_path / f"{cand}.jsonl",
            call=call,
        )
    return g, records, gold, raw


def test_scorer_flags_never_fail_a_page_records_from_the_real_runner(tmp_path: Path) -> None:
    g, recs, gold, raw = _screen(tmp_path, {"C0": dict.fromkeys(range(10), "one"), "good": {}})
    assert all(r["hard_failures"] == ["high_risk_numeric_below_threshold"] for r in recs)
    s1 = s5.select_s1(recs, guard=g, baseline="C0", raw_dir=raw)
    assert s1["leader"] == "good"
    assert s1["cells"]["H"]["good"]["critical_exact"] == 12
    assert s1["cells"]["H"]["C0"]["critical_exact"] == 6
    assert s1["cells"]["H"]["good"]["failures"] == 0
    assert s1["failures"]["good"]["score_flags"] == {"high_risk_numeric_below_threshold": 10}
    assert s1["failures"]["good"]["classes"] == dict.fromkeys(s5.FAILURE_CLASSES, 0)
    s2 = s5.complementarity_s2(recs, s5.load_texts(recs, raw), gold, guard=g, s1=s1)
    row = next(r for r in s2["matrix"]["H"] if (r["baseline"], r["peer"]) == ("C0", "good"))
    assert (row["baseline_wrong_pages"], row["rescued_fields"]) == (6, 6)


def test_failure_classes_are_the_5h17_tokens_and_unknown_tokens_refuse() -> None:
    expect = {
        "provider_unavailable": "operational",
        **{f"http_{s}": "operational" for s in (401, 403, 404, 429, 500, 502, 503)},
        "http_524": "time_limit",
        "page_timeout": "time_limit",
        "provider_error": "runner_error",
        "contract_failed": "contract",
        "page_too_large": "page_refused",
        "page_unreadable": "page_refused",
    }
    for token, cls in expect.items():
        assert s5.failure_class(token) == cls, token
    for flag in s5.SCORER_FLAGS:
        assert s5.failure_class(flag) is None, flag
    for bad in ("http_418", "pipeline_exit_nonzero", "other", "page_", "", "HTTP_503", None, 5):
        with pytest.raises(ContractError):
            s5.failure_class(bad)


def test_scorer_flag_set_is_every_flag_the_scorer_raises() -> None:
    source = Path(scorer.__file__).read_text(encoding="utf-8")
    assert set(re.findall(r'hard_failures\.append\("([a-z_]+)"\)', source)) == s5.SCORER_FLAGS


def test_mechanical_rejection_counts_operational_time_limit_and_runner_error(
    tmp_path: Path,
) -> None:
    # 10 pages: the bound is ceil(0.2 * 10) = 2; more than 2 such pages is out.
    plans = {
        "C0": dict.fromkeys(range(5), "unavailable"),  # baseline: never rejected this way
        "out": {0: "http_524", 1: "raise", 2: "http_503"},  # 3 > 2, read from failure.reason
        "edge": {0: "page_timeout", 1: "unavailable"},  # 2: kept
        "contract": {0: "contract_failed", 1: "page_too_large", 2: "contract_failed"},
        "ok": {},
    }
    g, recs, _, raw = _screen(tmp_path, plans)
    s1 = s5.select_s1(recs, guard=g, baseline="C0", raw_dir=raw)
    mech = s1["mechanical_rejection"]
    assert (mech["pages"], mech["bound"]) == (10, math.ceil(0.2 * 10))
    assert mech["counts"] == {"C0": 5, "contract": 0, "edge": 2, "ok": 0, "out": 3}
    assert mech["rejected"] == ["out"]
    assert "out" not in s1["kept"] + s1["dropped"]
    assert s1["failures"]["out"]["classes"]["time_limit"] == 1
    assert s1["failures"]["out"]["reasons"] == {"http_503": 1, "http_524": 1, "provider_error": 1}
    assert s1["failures"]["contract"]["classes"]["page_refused"] == 1
    with pytest.raises(ContractError, match="raw_dir"):
        s5.select_s1(recs, guard=g, baseline="C0")


def test_unknown_failure_reason_or_token_refuses_selection(tmp_path: Path) -> None:
    g, recs, _, raw = _screen(tmp_path, {"C0": {}, "x": {0: "pipeline_exit_nonzero"}})
    with pytest.raises(ContractError, match="pipeline_exit_nonzero"):
        s5.select_s1(recs, guard=g, baseline="C0", raw_dir=raw)
    recs2, _ = world({"L": {}, "C0": {}})
    recs2[0]["hard_failures"] = ["made_up_flag"]
    with pytest.raises(ContractError, match="made_up_flag"):
        s5.select_s1(recs2, guard=guard(tmp_path), baseline="C0")


@pytest.mark.parametrize("cost", [math.nan, math.inf, -0.01, "0.01", True])
def test_provider_cost_must_be_none_or_finite_non_negative(tmp_path: Path, cost: Any) -> None:
    recs, texts = world({"L": {}, "C0": wrong(HF[:2])})
    g = guard(tmp_path)
    s1 = s5.select_s1(recs, guard=g, baseline="C0")
    recs[3]["provider_cost_usd"] = cost
    with pytest.raises(ContractError, match="provider_cost_usd"):
        s5.select_s1(recs, guard=g, baseline="C0")
    with pytest.raises(ContractError, match="provider_cost_usd"):
        s5.complementarity_s2(recs, texts, GOLD, guard=g, s1=s1)


def test_probe_g_baseline_ranked_seventh_is_carried(tmp_path: Path) -> None:
    plans = {f"c{i}": wrong(HF[:i]) for i in range(6)}
    plans["C0"] = wrong(HF[:7])  # a non-loser that ranks seventh
    recs, _ = world(plans)
    s1 = s5.select_s1(recs, guard=guard(tmp_path), baseline="C0")
    assert s1["clear_losers"] == []
    assert s1["kept"] == ["c0", "c1", "c2", "c3", "c4", "C0"]
    assert s1["dropped"] == ["c5"]
    assert s1["baseline"] == {"candidate_id": "C0", "baseline": True, "baseline_loser": False}


def test_probe_d_top_up_counts_non_baseline_candidates_only(tmp_path: Path) -> None:
    lost = wrong(HF[:20]) | wrong(RF[:10])
    plans = {
        "c0": {},
        "c1": wrong(HF[:1]),
        "C0": lost,
        "x": lost,
        "y": wrong(HF[:20]) | wrong(RF[:11]),
    }
    recs, _ = world(plans)
    s1 = s5.select_s1(recs, guard=guard(tmp_path), baseline="C0")
    assert s1["clear_losers"] == ["C0", "x", "y"]
    assert s1["kept"] == ["c0", "c1", "C0", "x", "y"]  # four non-baseline, plus C0
    assert s1["dropped"] == []
    assert s1["baseline"] == {"candidate_id": "C0", "baseline": True, "baseline_loser": True}


def test_probe_m_s2_refuses_an_s1_edited_by_hand(tmp_path: Path) -> None:
    plans = {"L": wrong(HF[:8]), "B": wrong(HF[6:15], 2), "C": wrong(HF[20:30], 3), "C0": wrong(HF)}
    recs, texts = world(plans)
    g = guard(tmp_path)
    s1 = s5.select_s1(recs, guard=g, baseline="C0")
    assert s5.complementarity_s2(recs, texts, GOLD, guard=g, s1=s1)["members"]
    for edit in (
        {"kept": [c for c in s1["kept"] if c != "C"]},
        {"leader": "B"},
        {"s1_sha256": "sha256:" + "0" * 64},
    ):
        with pytest.raises(ContractError, match="S1"):
            s5.complementarity_s2(recs, texts, GOLD, guard=g, s1={**s1, **edit})
    body = {k: v for k, v in s1.items() if k != "s1_sha256"}
    with pytest.raises(ContractError, match="S1"):
        s5.complementarity_s2(recs, texts, GOLD, guard=g, s1=body)


def test_recipe_refuses_members_that_are_not_the_pick_chain(tmp_path: Path) -> None:
    plans = {"L": wrong(HF[:8]), "B": wrong(HF[4:15], 2), "C": wrong(HF[20:30], 3), "C0": wrong(HF)}
    recs, texts = world(plans, cost={"L": 0.01, "B": 0.02, "C": 0.10, "C0": 0.01})
    g = guard(tmp_path)
    s1 = s5.select_s1(recs, guard=g, baseline="C0")
    s2 = s5.complementarity_s2(recs, texts, GOLD, guard=g, s1=s1)
    assert s2["members"] == ["L", "B", "C"]
    args: dict[str, Any] = {
        "records": recs,
        "s1": s1,
        "escalate_on": ["disagreement"],
        "degradation": {"seed": 1, "parameters": {}},
        "scoring_commit": "1" * 40,
        "section_sha256": "sha256:" + "2" * 64,
    }
    assert s5.build_recipe(**args, s2=s2)["member_order"] == ["L", "B", "C"]
    steps = copy.deepcopy(s2["pick_steps"])
    steps[1]["chosen"] = "C0"
    for edited in (
        {"members": ["L", "C", "B"]},
        {"members": ["L", "B"]},
        {"members": ["B", "L", "C"], "primary": "B"},
        {"pick_steps": steps},
    ):
        with pytest.raises(ContractError, match="chain"):
            s5.build_recipe(**args, s2={**s2, **edited})


def test_s3_refuses_a_member_without_records_before_the_guard_is_touched(
    tmp_path: Path,
) -> None:
    recipe = _recipe(tmp_path, ["P", "Q"], ["disagreement"])
    hold, htexts = world(_s3_plans(), pages=X_PAGES, split="holdout")
    only_p = [r for r in hold if r["candidate_id"] == "P"]
    with pytest.raises(ValueError, match="without records"):
        s5.signals_s3(
            only_p,
            htexts,
            GOLD,
            guard=guard(tmp_path),
            members=["P", "Q"],
            escalate_on=["disagreement"],
            split="holdout",
            frozen_recipe_sha256=recipe["recipe_sha256"],
            recipe=recipe,
        )
    assert not (tmp_path / "holdout-access.jsonl").exists()
