"""Stage S4 (WO-D10-0Z): blind collection on the holdout and the custodian's report.

Every run here goes through the real ``s4.main`` (collect: the S0 driver with the fake pod and
fake model of ``test_screen_s0``; report: the real re-derivation, reader v1 and ``signals_s3``).
Nothing is real: synthetic pages, synthetic gold, a fake token. The worked example in
``test_the_s4_figures_are_the_ones_worked_out_by_hand`` is computed by hand in its comments.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from benchmark.runners.registry import RUNNER_CONFIGS
from benchmark.runners.vlm import config_sha256
from benchmark.screen import normalise_v2, s0, s4, select_5h
from benchmark.screen.manifest import SEC_LICENCE, freeze
from benchmark.tests.test_screen_s0 import (
    CREATED,
    MARKER,
    POD,
    RECIPE,
    REV_CHAT,
    REV_PAGE,
    Clock,
    Model,
    Pod,
    ok,
    refused,
    row,
)
from benchmark.v6.contracts import canonical_sha256

G1, G2, X = "7,654,321", "86,420,135", "9,999"  # gold values and a wrong read
GOLD_TEXT = "GOLD-ONLY-SENTENCE"
IMG = {"C3": "sha256:" + "3" * 64, "C7": "sha256:" + "7" * 64, "C0": "sha256:" + "0" * 64}
CHAT_CONFIG = config_sha256(RUNNER_CONFIGS["ovis_ocr2"](revision=REV_CHAT))
PAGE_CONFIG = "sha256:" + RECIPE
KIND = {"C3": "page", "C7": "chat", "C0": "page"}
PROVIDER = {"C3": "mineru_vlm", "C7": "ovis_ocr2", "C0": "mineru"}
REV = {"C3": REV_PAGE, "C7": REV_CHAT, "C0": REV_PAGE}
CONFIG = {"C3": PAGE_CONFIG, "C7": CHAT_CONFIG, "C0": PAGE_CONFIG}
SRC = [f"zsrc-{i}.pdf" for i in range(4)]  # R: the source pages
DEG = [f"zdeg-{i}.pdf" for i in range(4)]  # H: each a scan_poor of the source of its index
PAGE_IDS = [f"{d}#0" for d in SRC + DEG]
SHARED_PREFIX = "0000000777"  # zsrc-0's filer, also on a dev page: out of the subset
LATENCY = {"C3": 36000.0, "C7": 18000.0, "C0": 7200.0}  # at USD 1/h: 0.01, 0.005, 0.002


def table(a: str | None, b: str | None) -> str:
    rows = [(n, v) for n, v in (("Revenue", a), ("Net income", b)) if v is not None]
    return "<table>" + "".join(f"<tr><td>{n}</td><td>{v}</td></tr>" for n, v in rows) + "</table>"


def _doc(doc_id: str, data: bytes, cik: int, adsh: str) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "source_sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
        "byte_size": len(data),
        "page_count": 1,
        "stratum": "en_native",
        "language": "en",
        "document_class": "sec_statement",
        "page_origin": "born_digital_html_print",
        "rights": {
            "source_url": f"https://example.invalid/{doc_id}",
            "licence_id": SEC_LICENCE,
            "licence_snapshot_sha256": "sha256:" + "a" * 64,
            "rights_class": "public_record",
            "redistribution": False,
            "recorded_by": "tester",
            "recorded_at": "2026-11-16T00:00:00Z",
        },
        "provenance": {"adsh": adsh, "cik": cik},
    }


def world(
    tmp: Path,
    mp: pytest.MonkeyPatch,
    *,
    escalate_on: tuple[str, ...] = ("disagreement", "no_value"),
    no_fields: tuple[str, ...] = (),
) -> Path:
    """Dev manifest (two pages, one filed by zsrc-0's filer), holdout manifest frozen disjoint
    from it (four sources, four scan_poor pages), corpus, gold (``no_fields``: pages whose gold
    has no critical field), recipe and baseline pins. The other filers share nine characters
    with zsrc-0's, so only the tenth tells them apart."""
    corpus = tmp / "corpus"
    corpus.mkdir()
    dev_docs = []
    for i, prefix in enumerate((SHARED_PREFIX, "0000000888")):
        dev_docs.append(_doc(f"dev-{i}.pdf", f"dev page {i}".encode(), 9000 + i, f"{prefix}-25-9"))
    dev = freeze(dev_docs, "d", "lpc_sec", split="dev")
    docs = []
    for i, (src, deg) in enumerate(zip(SRC, DEG, strict=True)):
        data = f"holdout source {i}".encode()
        (corpus / src).write_bytes(data)
        prefix = SHARED_PREFIX if i == 0 else f"{SHARED_PREFIX[:9]}{i}"
        s = _doc(src, data, 100 + i, f"{prefix}-25-00000{i}")
        docs.append(s)
        ddata = f"holdout degraded {i}".encode()
        (corpus / deg).write_bytes(ddata)
        d = _doc(deg, ddata, 100 + i, s["provenance"]["adsh"])
        d.update(
            page_origin=select_5h.DEGRADED,
            derived_from=s["source_sha256"],
            degradation={
                "level": "scan_poor",
                "seed": "s4-test",
                "renderer": {"pypdfium2": s0.PYPDFIUM2_VERSION},
            },
        )
        docs.append(d)
    hold = freeze(docs, "h", "lpc_sec", split="holdout", disjoint_from=dev)
    (tmp / "dev.json").write_text(json.dumps(dev), encoding="utf-8")
    (tmp / "hold.json").write_text(json.dumps(hold), encoding="utf-8")
    truth = {
        "critical_fields": [
            {"field_id": "f1", "kind": "number", "value": G1, "anchor": "Revenue"},
            {"field_id": "f2", "kind": "number", "value": G2, "anchor": "Net income"},
        ],
        "text": GOLD_TEXT,
    }
    empty = {**truth, "critical_fields": []}
    gold = "".join(
        json.dumps({"page_id": p, "truth": empty if p in no_fields else truth}) + "\n"
        for p in PAGE_IDS
    )
    (tmp / "gold.jsonl").write_text(gold, encoding="utf-8")
    members = [
        {"candidate_id": c, "revision": REV[c], "image_digest": IMG[c], "config_sha256": CONFIG[c]}
        for c in ("C3", "C7")
    ]
    body = {
        "members": members,
        "member_order": ["C3", "C7"],
        "escalate_on": sorted(escalate_on),
        "signals": {k: select_5h.SIGNALS[k] for k in sorted(escalate_on)},
    }
    recipe = {**body, "recipe_sha256": canonical_sha256(body)}
    (tmp / "recipe.json").write_text(json.dumps(recipe), encoding="utf-8")
    pins = {
        "candidate_id": "C0",
        "provider": "mineru",
        "revision": REV_PAGE,
        "image_digest": IMG["C0"],
        "config_sha256": PAGE_CONFIG,
    }
    (tmp / "c0-pins.json").write_text(json.dumps(pins), encoding="utf-8")
    mp.setenv("AKC_BENCHMARK_PROVIDER_TOKEN", MARKER)
    mp.setattr(s0, "_pypdfium2_version", lambda: s0.PYPDFIUM2_VERSION)
    return tmp


def digest(w: Path) -> str:
    return str(json.loads((w / "recipe.json").read_text(encoding="utf-8"))["recipe_sha256"])


def host(cid: str, pod: str = POD) -> str:
    return f"{pod}-{8000 if KIND[cid] == 'chat' else 8080}.proxy.runpod.net"


def collect_argv(w: Path, cid: str, **over: str) -> list[str]:
    a = {
        "--candidate-id": cid,
        "--provider": PROVIDER[cid],
        "--revision": REV[cid],
        "--image-digest": IMG[cid],
        "--pod-id": POD,
        "--created-utc": CREATED.isoformat(),
        "--usd-per-hour": "1.0",
        "--manifest": str(w / "hold.json"),
        "--corpus-root": str(w / "corpus"),
        "--out": str(w / "runs" / cid),
        "--recipe": str(w / "recipe.json"),
        "--recipe-sha256": digest(w),
        "--access-log": str(w / "holdout-access.jsonl"),
    }
    if KIND[cid] == "page":
        a["--config-sha256"] = CONFIG[cid]
    if cid == "C0":
        a["--baseline-pins"] = str(w / "c0-pins.json")
    a.update(over)
    return ["collect", *(x for k, v in a.items() if v != "" for x in (k, v))]


def pod_for(cid: str) -> Pod:
    pod = Pod(KIND[cid])
    pod.health["provider"] = PROVIDER[cid]
    return pod


def collect(
    w: Path,
    mp: pytest.MonkeyPatch,
    cid: str,
    model: Model,
    *,
    pod: Pod | None = None,
    clock: Clock | None = None,
    **over: str,
) -> int:
    mp.setenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", host(cid, over.get("--pod-id", POD)))
    pod = pod or pod_for(cid)
    clock = clock or Clock()
    return s4.main(
        collect_argv(w, cid, **over), request=pod, call=model, now=clock.now, sleep=clock.sleep
    )


def answer(cid: str, a: str | None, b: str | None) -> Any:
    return ok(KIND[cid], text=table(a, b), latency=LATENCY[cid])


# The worked example (P = C3, peer C7, baseline C0). G = the gold value, X = a wrong read.
PLAN: dict[str, dict[str, Any]] = {
    "C3": {
        "zsrc-0.pdf": answer("C3", G1, G2),
        "zsrc-1.pdf": answer("C3", G1, X),
        "zsrc-2.pdf": answer("C3", G1, X),
        "zsrc-3.pdf": row("pipeline_error", "page"),  # P failed: both fields escalate
        "zdeg-0.pdf": answer("C3", G1, G2),
        "zdeg-1.pdf": answer("C3", X, G2),
        "zdeg-2.pdf": answer("C3", G1, None),  # no value for f2
        "zdeg-3.pdf": answer("C3", G1, G2),
    },
    "C7": {
        "zsrc-0.pdf": answer("C7", G1, G2),
        "zsrc-1.pdf": answer("C7", G1, G2),
        "zsrc-2.pdf": answer("C7", G1, X),  # agrees with P's wrong read: a false accept
        "zsrc-3.pdf": answer("C7", G1, G2),
        "zdeg-0.pdf": refused,  # no output: no disagreement either
        "zdeg-1.pdf": answer("C7", G1, G2),
        "zdeg-2.pdf": answer("C7", G1, G2),
        "zdeg-3.pdf": answer("C7", X, G2),  # disagrees with a right P: a wasted escalation
    },
    "C0": {
        "zsrc-0.pdf": answer("C0", G1, G2),
        "zsrc-1.pdf": answer("C0", G1, G2),
        "zsrc-2.pdf": answer("C0", X, G2),
        "zsrc-3.pdf": answer("C0", G1, G2),
        "zdeg-0.pdf": row("pipeline_error", "page"),
        "zdeg-1.pdf": answer("C0", G1, G2),
        "zdeg-2.pdf": answer("C0", G1, G2),
        "zdeg-3.pdf": answer("C0", G1, G2),
    },
}


def collect_all(w: Path, mp: pytest.MonkeyPatch) -> None:
    for cid in ("C3", "C7", "C0"):
        assert collect(w, mp, cid, Model(PLAN[cid], answer(cid, G1, G2))) == 0, cid


def report_argv(w: Path, out: str = "s4", **over: str) -> list[str]:
    a = {
        "--recipe": str(w / "recipe.json"),
        "--recipe-sha256": digest(w),
        "--manifest": str(w / "hold.json"),
        "--dev-manifest": str(w / "dev.json"),
        "--corpus-root": str(w / "corpus"),
        "--gold": str(w / "gold.jsonl"),
        "--runs": str(w / "runs"),
        "--baseline": "C0",
        "--baseline-pins": str(w / "c0-pins.json"),
        "--normaliser-v2-sha256": normalise_v2.MODULE_SHA256,
        "--billed-usd": "0.75",
        "--billed-source": "list-pod-billing read 2026-11-19 (test)",
        "--access-log": str(w / "holdout-access.jsonl"),
        "--out": str(w / out),
    }
    a.update(over)
    return ["report", *(x for k, v in a.items() if v != "" for x in (k, v))]


def s4_json(w: Path, out: str = "s4") -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((w / out / "s4.json").read_bytes())
    return doc


SECRETS = [*PAGE_IDS, *SRC, *DEG, G1, G2, "7654321", "86420135", GOLD_TEXT, MARKER]


def assert_clean(*texts: str) -> None:
    for text in texts:
        for s in SECRETS:
            assert s not in text, s


# ---------------------------------------------------------------- the real path


def test_the_s4_figures_are_the_ones_worked_out_by_hand(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch)
    collect_all(w, monkeypatch)
    collected = capsys.readouterr()
    assert s4.main(report_argv(w)) == 0
    streams = capsys.readouterr()
    data = (w / "s4" / "s4.json").read_bytes()
    assert streams.out == "sha256:" + hashlib.sha256(data).hexdigest() + "\n"
    assert streams.err == ""
    assert_clean(collected.out, collected.err, streams.out, streams.err, data.decode())
    doc = s4_json(w)
    assert doc["publishable"] is False and doc["members"] == ["C3", "C7"]
    r, h, s = (doc["parts"][k] for k in ("R", "H", "sensitivity"))
    # R: s0 all right; s1 f2 escalated (C7 disagrees); s2 f2 a false accept (both read X);
    # s3 P failed, both escalated. 8 fields, 3 escalated, 5 accepted, 4 of them exact.
    assert (r["fields"], r["escalated_fields"], r["accepted_fields"]) == (8, 3, 5)
    assert r["accepted_field_exact"]["k"] == 4 and r["accepted_field_exact"]["rate"] == 4 / 5
    assert r["false_accept"]["k"] == 1 and r["false_accept"]["rate"] == 1 / 5
    assert r["escalation_rate"] == 3 / 8
    assert r["recipe_yield"]["k"] == 4 and r["recipe_yield"]["n"] == 8
    assert r["recipe_yield"]["wilson_95"] == select_5h.wilson_interval(4, 8)
    assert r["false_accept"]["wilson_95"] == select_5h.wilson_interval(1, 5)
    assert r["accepted_pages"] == 2  # s0, s2
    # recipe page-ok [s0]; C0 page-ok [s0, s1, s3]: 0 recipe-only, 2 baseline-only
    m = r["mcnemar_recipe_vs_baseline"]
    assert (m["only_left"], m["only_baseline"], m["both"], m["neither"]) == (0, 2, 1, 1)
    assert m["p_exact"] == 0.5
    # cost: C3 3 pages x 0.01 (s3 failed: no latency), C7 4 x 0.005 = 0.05 over 2 pages
    assert r["cost"]["derived_usd"] == pytest.approx(0.05)
    assert r["cost"]["usd_per_accepted_page"] == pytest.approx(0.025)
    assert r["cost"]["pages_without_cost"] == {"C3": 1, "C7": 0}
    # H: d0 accepted (C7 gave nothing); d1 f1 escalated; d2 f2 no value; d3 f1 escalated
    # though P was right (wasted). 3 escalated, 5 accepted, all exact.
    assert (h["fields"], h["escalated_fields"], h["accepted_fields"]) == (8, 3, 5)
    assert h["accepted_field_exact"]["k"] == 5 and h["false_accept"]["k"] == 0
    assert h["recipe_yield"]["rate"] == 5 / 8 and h["accepted_pages"] == 1
    m = h["mcnemar_recipe_vs_baseline"]  # recipe [d0]; C0 [d1, d2, d3]
    assert (m["only_left"], m["only_baseline"], m["p_exact"]) == (1, 3, 0.625)
    m = h["mcnemar_primary_vs_baseline"]  # C3 alone [d0, d3]; C0 [d1, d2, d3]
    assert (m["only_left"], m["only_baseline"], m["p_exact"]) == (1, 2, 1.0)
    assert h["cost"]["derived_usd"] == pytest.approx(0.055)
    assert h["cost"]["usd_per_accepted_page"] == pytest.approx(0.055)
    # sensitivity: zsrc-0 and its scan share a dev page's filer: 6 pages, 12 fields
    assert doc["sensitivity_subset"]["pages"] == 6 == s["pages"]
    assert doc["sensitivity_subset"]["page_ids_sha256"] == canonical_sha256(
        sorted(f"{d}#0" for d in (*SRC[1:], *DEG[1:]))
    )
    assert (s["fields"], s["escalated_fields"], s["accepted_fields"]) == (12, 6, 6)
    assert (s["accepted_field_exact"]["k"], s["false_accept"]["k"]) == (5, 1)
    assert s["accepted_pages"] == 1
    m = s["mcnemar_recipe_vs_baseline"]
    assert (m["only_left"], m["only_baseline"], m["p_exact"]) == (0, 5, 0.0625)
    # cells by select_s1's relabelling: field-exact over the gold's fields, failed pages wrong
    cells = {
        p: {c: (v["critical_exact"], v["critical_n"]) for c, v in doc["parts"][p]["cells"].items()}
        for p in ("R", "H", "sensitivity")
    }
    assert cells["R"] == {"C3": (4, 8), "C7": (7, 8), "C0": (7, 8)}
    assert cells["H"] == {"C3": (6, 8), "C7": (5, 8), "C0": (6, 8)}
    assert cells["sensitivity"] == {"C3": (6, 12), "C7": (10, 12), "C0": (11, 12)}
    assert doc["failures"]["C3"]["classes"]["pipeline_failure"] == 1
    assert doc["failures"]["C7"]["reasons"] == {"page_over_pixel_cap": 1}
    # the S3 scoring of the same holdout agrees with S4-2 where both define the figure
    for part in ("H", "R"):
        esc = doc["signals_s3"]["scores"][part]["escalate"]
        assert esc["flagged"] == doc["parts"][part]["escalated_fields"]
        assert esc["false_accepts"] == doc["parts"][part]["false_accept"]["k"]
    assert doc["billed"]["usd"] == 0.75 and "derived" not in doc["billed"]
    code = doc["inputs"]["code"]
    assert code["s4"] == s4.MODULE_SHA256 and code["normaliser_v2"] == normalise_v2.MODULE_SHA256
    # a second report on the same inputs is byte-identical
    assert s4.main(report_argv(w, out="again")) == 0
    assert (w / "again" / "s4.json").read_bytes() == data


def test_a_failed_primary_page_escalates_where_no_signal_fires(tmp_path, monkeypatch):
    """Recipe on ``disagreement`` only. zsrc-3: P and C7 both failed, so no peer disagrees and
    no signal is in the rule; S4-2 escalates the page's fields all the same. zdeg-3 has no gold
    field: it is an accepted page with nothing to accept, and in McNemar neither side's."""
    w = world(tmp_path, monkeypatch, escalate_on=("disagreement",), no_fields=("zdeg-3.pdf#0",))
    plans = {c: dict(PLAN[c]) for c in PLAN}
    plans["C7"]["zsrc-3.pdf"] = refused
    plans["C3"]["zdeg-2.pdf"] = answer("C3", G1, G2)  # no "no value" left in H
    for cid in ("C3", "C7", "C0"):
        assert collect(w, monkeypatch, cid, Model(plans[cid], answer(cid, G1, G2))) == 0
    assert s4.main(report_argv(w)) == 0
    doc = s4_json(w)
    r, h = doc["parts"]["R"], doc["parts"]["H"]
    # R as in the worked example: s1 f2 escalated, s3 both escalated (failed P), s2 a false accept
    assert (r["escalated_fields"], r["accepted_fields"], r["false_accept"]["k"]) == (3, 5, 1)
    assert doc["signals_s3"]["scores"]["R"]["escalate"]["flagged"] == 1  # the rule alone: s1 f2
    # H: d0 accepted, d1 f1 escalated, d2 accepted, d3 has no field: 6 fields, 1 escalated
    assert (h["fields"], h["escalated_fields"], h["accepted_pages"]) == (6, 1, 3)
    m = h["mcnemar_recipe_vs_baseline"]  # recipe [d0, d2]; C0 [d1, d2]; d3 neither
    assert (m["both"], m["only_left"], m["only_baseline"], m["neither"]) == (1, 1, 1, 1)


def test_the_collection_reads_no_gold_and_scores_nothing(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch)
    (w / "gold.jsonl").unlink()

    def no_gold(path: Path) -> Any:
        raise AssertionError("the collection read gold")

    monkeypatch.setattr(s0.Driver, "_gold", staticmethod(no_gold))
    assert collect(w, monkeypatch, "C3", Model(PLAN["C3"], answer("C3", G1, G2))) == 0
    out = capsys.readouterr().out
    assert "accepted" not in out and "residual" not in out
    lines = [x for x in out.splitlines() if " page " in x]
    assert len(lines) == 8 and all("latency=" in x and "cost=" in x for x in lines)
    recs = [
        json.loads(x) for x in (w / "runs" / "C3" / "final-records.jsonl").read_text().splitlines()
    ]
    assert {r["split"] for r in recs} == {"holdout"} and len(recs) == 8
    assert all(r["critical"] is None and r["accepted"] is None and r["metrics"] == {} for r in recs)
    assert sorted(t for r in recs for t in r["hard_failures"]) == ["contract_failed"]
    summary = json.loads((w / "runs" / "C3" / "s0-summary.json").read_text())
    assert "accepted" not in summary and summary["score_flags_not_failures"] == {}
    pins = json.loads((w / "runs" / "C3" / "s0-run.json").read_text())
    assert pins["frozen_recipe_sha256"] == digest(w) and pins["role"] == "member"


def test_one_access_log_holds_one_recipe_digest(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    collect_all(w, monkeypatch)
    assert s4.main(report_argv(w)) == 0
    logs = sorted(p.relative_to(w).as_posix() for p in w.rglob("holdout-access*"))
    assert logs == ["holdout-access.jsonl"]
    lines = (w / "holdout-access.jsonl").read_text(encoding="utf-8").splitlines()
    hold = json.loads((w / "hold.json").read_text())
    assert [json.loads(x) for x in lines] == [
        {"frozen_recipe_sha256": digest(w), "manifest_sha256": hold["manifest_sha256"]}
    ]


def test_resume_on_a_second_pod_sends_no_terminal_page_and_refuses_a_changed_pin(
    tmp_path, monkeypatch
):
    w = world(tmp_path, monkeypatch)
    clock = Clock()
    first = Model({}, answer("C7", G1, G2))

    def tick() -> None:
        clock.t += s0.timedelta(minutes=60)

    first.on_call = tick
    assert collect(w, monkeypatch, "C7", first, clock=clock) == 3  # the deadline stops it
    assert len(first.calls) == 2 and not (w / "runs" / "C7" / "final-records.jsonl").exists()
    later = (CREATED + s0.timedelta(hours=3)).isoformat()
    for pin, value in (
        ("--image-digest", "sha256:" + "9" * 64),
        ("--recipe-sha256", "sha256:" + "9" * 64),
    ):
        model = Model({}, answer("C7", G1, G2))
        rc = collect(
            w,
            monkeypatch,
            "C7",
            model,
            clock=Clock(CREATED + s0.timedelta(hours=3, minutes=5)),
            **{"--pod-id": "podtwo", "--created-utc": later, pin: value},
        )
        assert rc == 2 and model.calls == [], pin
    second = Model({}, answer("C7", G1, G2))
    rc = collect(
        w,
        monkeypatch,
        "C7",
        second,
        clock=Clock(CREATED + s0.timedelta(hours=3, minutes=5)),
        **{"--pod-id": "podtwo", "--created-utc": later},
    )
    assert rc == 0
    assert not set(first.calls) & set(second.calls) and len(second.calls) == 6
    recs = (w / "runs" / "C7" / "final-records.jsonl").read_text().splitlines()
    assert len(recs) == 8
    pods = [
        json.loads(x)["pod_id"]
        for x in (w / "runs" / "C7" / "attempts.jsonl").read_text().splitlines()
    ]
    assert pods == [POD, "podtwo"]


def test_a_run_of_zero_pages_is_refused_by_both_drivers(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    model = Model({}, answer("C3", G1, G2))
    pod = pod_for("C3")
    assert collect(w, monkeypatch, "C3", model, pod=pod, **{"--manifest": str(w / "dev.json")}) == 2
    assert model.calls == [] and pod.calls == []
    assert not (w / "holdout-access.jsonl").exists() and not (w / "runs").exists()
    # the dev driver on the holdout manifest: refused, where it used to run zero pages, exit 0
    monkeypatch.setenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", host("C3"))
    argv = [
        "--candidate-id", "C3", "--provider", "mineru_vlm", "--revision", REV_PAGE,
        "--image-digest", IMG["C3"], "--pod-id", POD, "--created-utc", CREATED.isoformat(),
        "--usd-per-hour", "1.0", "--config-sha256", PAGE_CONFIG,
        "--manifest", str(w / "hold.json"), "--corpus-root", str(w / "corpus"),
        "--gold", str(w / "gold.jsonl"), "--out", str(w / "s0out"),
    ]  # fmt: skip
    clock = Clock()
    assert s0.main(argv, request=pod, call=model, now=clock.now, sleep=clock.sleep) == 2
    assert model.calls == [] and pod.calls == [] and not (w / "s0out").exists()


# ---------------------------------------------------------------- collection refusals


def _tamper_recipe(w: Path) -> dict[str, str]:
    recipe = json.loads((w / "recipe.json").read_text())
    recipe["escalate_on"] = ["no_value"]
    (w / "recipe.json").write_text(json.dumps(recipe))
    return {"--recipe-sha256": recipe["recipe_sha256"]}


def _other_log(w: Path) -> dict[str, str]:
    line = {"frozen_recipe_sha256": "sha256:" + "5" * 64, "manifest_sha256": "x"}
    (w / "holdout-access.jsonl").write_text(json.dumps(line) + "\n")
    return {}


def _bad_pins(w: Path) -> dict[str, str]:
    pins = json.loads((w / "c0-pins.json").read_text())
    (w / "c0-pins.json").write_text(json.dumps({**pins, "revision": "d" * 40}))
    return {}


COLLECT_REFUSALS = {
    "recipe body edited": ("C3", _tamper_recipe),
    "another digest": ("C3", lambda w: {"--recipe-sha256": "sha256:" + "4" * 64}),
    "digest not a digest": ("C3", lambda w: {"--recipe-sha256": "abc"}),
    "member image differs": ("C3", lambda w: {"--image-digest": "sha256:" + "8" * 64}),
    "member config differs": ("C3", lambda w: {"--config-sha256": "sha256:" + "8" * 64}),
    "member revision differs": ("C3", lambda w: {"--revision": "1" * 40}),
    "member with baseline pins": ("C3", lambda w: {"--baseline-pins": str(w / "c0-pins.json")}),
    "baseline without pins": ("C0", lambda w: {"--baseline-pins": ""}),
    "baseline pins differ": ("C0", _bad_pins),
    "baseline image differs": ("C0", lambda w: {"--image-digest": "sha256:" + "8" * 64}),
    "baseline under another digest": ("C0", lambda w: {"--recipe-sha256": "sha256:" + "4" * 64}),
    "access log names another recipe": ("C3", _other_log),
}


@pytest.mark.parametrize("name", sorted(COLLECT_REFUSALS))
def test_each_collection_refusal_is_exit_2_before_any_request_or_access(
    tmp_path, monkeypatch, capsys, name
):
    w = world(tmp_path, monkeypatch)
    cid, spoil = COLLECT_REFUSALS[name]
    log_before = (
        (w / "holdout-access.jsonl").read_bytes() if (w / "holdout-access.jsonl").exists() else None
    )
    over = spoil(w)
    log_before = (
        (w / "holdout-access.jsonl").read_bytes()
        if (w / "holdout-access.jsonl").exists()
        else log_before
    )
    model, pod = Model({}, answer(cid, G1, G2)), pod_for(cid)
    assert collect(w, monkeypatch, cid, model, pod=pod, **over) == 2
    assert model.calls == [] and pod.calls == [] and not (w / "runs").exists()
    after = (
        (w / "holdout-access.jsonl").read_bytes() if (w / "holdout-access.jsonl").exists() else None
    )
    assert after == log_before
    streams = capsys.readouterr()
    assert_clean(streams.out, streams.err)


# ---------------------------------------------------------------- report refusals


def _records(w: Path, cid: str) -> list[dict[str, Any]]:
    return [
        json.loads(x) for x in (w / "runs" / cid / "final-records.jsonl").read_text().splitlines()
    ]


def _write_records(w: Path, cid: str, recs: list[dict[str, Any]]) -> None:
    body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in recs)
    (w / "runs" / cid / "final-records.jsonl").write_text(body, encoding="utf-8")


def _drop_page(w: Path) -> dict[str, str]:
    _write_records(w, "C7", _records(w, "C7")[1:])
    return {}


def _scored(w: Path) -> dict[str, str]:
    recs = _records(w, "C7")
    recs[0]["critical"] = {"n": 2, "exact": 2, "accepted_errors": 0}
    _write_records(w, "C7", recs)
    return {}


def _raw_changed(w: Path) -> dict[str, str]:
    r = next(r for r in _records(w, "C3") if r["raw_sha256"])
    path = w / "runs" / "C3" / "raw" / (r["record_key"][7:] + ".json")
    path.write_bytes(path.read_bytes().replace(b"Revenue", b"Revenuf"))
    return {}


def _gold_short(w: Path) -> dict[str, str]:
    lines = (w / "gold.jsonl").read_text().splitlines()
    (w / "gold.jsonl").write_text("\n".join(lines[1:]) + "\n")
    return {}


def _log_gone(w: Path) -> dict[str, str]:
    (w / "holdout-access.jsonl").unlink()
    return {}


def _log_second(w: Path) -> dict[str, str]:
    with (w / "holdout-access.jsonl").open("a") as fh:
        fh.write(
            json.dumps({"frozen_recipe_sha256": "sha256:" + "5" * 64, "manifest_sha256": "x"})
            + "\n"
        )
    return {}


def _pins_file(w: Path) -> dict[str, str]:
    pins = json.loads((w / "c0-pins.json").read_text())
    (w / "other-pins.json").write_text(json.dumps({**pins, "image_digest": IMG["C3"]}))
    return {"--baseline-pins": str(w / "other-pins.json")}


def _member_pins(w: Path) -> dict[str, str]:
    path = w / "runs" / "C7" / "s0-run.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "image_digest": IMG["C0"]}))
    return {}


def _dev_edited(w: Path) -> dict[str, str]:
    dev = json.loads((w / "dev.json").read_text())
    dev["salt"] = "other"
    (w / "dev.json").write_text(json.dumps(dev))
    return {}


def _no_provenance(w: Path) -> dict[str, str]:
    dev = json.loads((w / "dev.json").read_text())
    del dev["documents"][0]["provenance"]["adsh"]
    body = {k: v for k, v in dev.items() if k != "manifest_sha256"}
    dev["manifest_sha256"] = canonical_sha256(body)
    (w / "dev.json").write_text(json.dumps(dev))
    hold = json.loads((w / "hold.json").read_text())
    hold["disjoint_from_sha256"] = dev["manifest_sha256"]
    hold["manifest_sha256"] = canonical_sha256(
        {k: v for k, v in hold.items() if k != "manifest_sha256"}
    )
    (w / "hold.json").write_text(json.dumps(hold))
    log = {"frozen_recipe_sha256": digest(w), "manifest_sha256": hold["manifest_sha256"]}
    (w / "holdout-access.jsonl").write_text(json.dumps(log) + "\n")
    return {}


def _no_run(w: Path) -> dict[str, str]:
    (w / "runs" / "C7" / "s0-run.json").unlink()
    return {}


def _other_dev(w: Path) -> dict[str, str]:
    dev = json.loads((w / "dev.json").read_text())
    doc = {**dev["documents"][0], "provenance": {"adsh": "x-1", "cik": 77}}
    other = freeze([doc], "o", "lpc_sec", split="dev")
    (w / "other-dev.json").write_text(json.dumps(other))
    return {"--dev-manifest": str(w / "other-dev.json")}


def _field_moved(w: Path) -> dict[str, str]:
    recs = _records(w, "C3")
    i = next(i for i, r in enumerate(recs) if r["raw_sha256"] is not None)
    recs[i]["gpu_seconds"] = 1.0
    _write_records(w, "C3", recs)
    return {}


REPORT_REFUSALS: dict[str, tuple[Any, int, str]] = {
    "v2 digest": (lambda w: {"--normaliser-v2-sha256": "sha256:" + "1" * 64}, 2, "v2"),
    "billed nan": (lambda w: {"--billed-usd": "nan"}, 2, "billed-usd"),
    "billed negative": (lambda w: {"--billed-usd": "-1"}, 2, "billed-usd"),
    "billed inf": (lambda w: {"--billed-usd": "inf"}, 2, "billed-usd"),
    "billed source empty": (lambda w: {"--billed-source": " "}, 2, "billed-source"),
    "billed source too long": (lambda w: {"--billed-source": "x" * 501}, 2, "billed-source"),
    "recipe digest": (lambda w: {"--recipe-sha256": "sha256:" + "4" * 64}, 2, "recipe file"),
    "baseline is a member": (lambda w: {"--baseline": "C7"}, 2, "outside a recipe"),
    "dev manifest edited": (_dev_edited, 2, "intact"),
    "dev manifest is the holdout": (
        lambda w: {"--dev-manifest": str(w / "hold.json")},
        2,
        "not dev",
    ),
    "another dev manifest": (_other_dev, 2, "disjoint"),
    "a document without a filer": (_no_provenance, 2, "filer prefix"),
    "gold short of a page": (_gold_short, 2, "1 page(s) without gold"),
    "gold missing": (lambda w: {"--gold": str(w / "none.jsonl")}, 2, "not readable"),
    "access log gone": (_log_gone, 2, "access log"),
    "access log names a second recipe": (_log_second, 2, "2 line(s)"),
    "a run is missing": (_no_run, 2, "C7's s0-run.json"),
    "a page without a terminal record": (_drop_page, 2, "C7: 1 page(s) without"),
    "a record carries a score": (_scored, 2, "C7: a record is not a blind"),
    "a raw output changed": (_raw_changed, 4, "raw output differs"),
    "a stored record field differs": (_field_moved, 4, "differs in ['gpu_seconds']"),
    "baseline pins file differs": (_pins_file, 4, "C0: the run's pins are not the baseline"),
    "member run pins differ from the recipe": (_member_pins, 4, "C7: the run's pins differ"),
}


@pytest.fixture(scope="module")
def collected(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("s4-collected")
    with pytest.MonkeyPatch.context() as mp:
        collect_all(world(base, mp), mp)
    return base


def _copy(collected: Path, tmp: Path, mp: pytest.MonkeyPatch) -> Path:
    w = tmp / "w"
    import shutil

    shutil.copytree(collected, w)
    for name in ("C3", "C7", "C0"):  # the runs pinned their access log's absolute path
        path = w / "runs" / name / "s0-run.json"
        pins = json.loads(path.read_text())
        pins["access_log"] = str((w / "holdout-access.jsonl").resolve())
        path.write_text(json.dumps(pins, indent=2, sort_keys=True) + "\n")
    mp.setattr(s0, "_pypdfium2_version", lambda: s0.PYPDFIUM2_VERSION)
    return w


def test_a_copied_world_reports(collected, tmp_path, monkeypatch, capsys):
    w = _copy(collected, tmp_path, monkeypatch)
    assert s4.main(report_argv(w)) == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("name", sorted(REPORT_REFUSALS))
def test_each_report_refusal_is_fixed_text_with_its_detail_inside_out(
    collected, tmp_path, monkeypatch, capsys, name
):
    w = _copy(collected, tmp_path, monkeypatch)
    spoil, code, says = REPORT_REFUSALS[name]
    over = spoil(w)
    capsys.readouterr()
    assert s4.main(report_argv(w, **over)) == code
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err.startswith(f"s4 report exit {code}: ") and says in streams.err
    assert_clean(streams.out, streams.err)
    assert not (w / "s4" / "s4.json").exists()
    assert (w / "s4" / "refusal.txt").is_file()
    assert not list(w.glob("s4.stage-*"))


def test_a_page_without_a_terminal_record_names_the_member_and_the_count(
    collected, tmp_path, monkeypatch, capsys
):
    w = _copy(collected, tmp_path, monkeypatch)
    _drop_page(w)
    assert s4.main(report_argv(w)) == 2
    assert "C7: 1 page(s) without a terminal record" in capsys.readouterr().err


def test_a_refusal_that_names_a_page_reaches_refusal_txt_only(
    collected, tmp_path, monkeypatch, capsys
):
    w = _copy(collected, tmp_path, monkeypatch)
    recs = _records(w, "C7")
    i = next(i for i, r in enumerate(recs) if r["raw_sha256"] is None)  # passed through as stored
    recs[i]["provider_cost_usd"] = -1.0  # select_5h._check names the page in its message
    _write_records(w, "C7", recs)
    assert s4.main(report_argv(w)) == 2
    err = capsys.readouterr().err
    assert_clean(err)
    assert "refused (ContractError)" in err
    assert recs[i]["page_id"] in (w / "s4" / "refusal.txt").read_text(encoding="utf-8")


def test_out_is_written_once(collected, tmp_path, monkeypatch, capsys):
    w = _copy(collected, tmp_path, monkeypatch)
    (w / "s4").mkdir()
    (w / "s4" / "keep").write_text("x")
    assert s4.main(report_argv(w)) == 2
    assert sorted(p.name for p in (w / "s4").iterdir()) == ["keep"]
    assert "written once" in capsys.readouterr().err


def test_the_report_reads_v2_text_not_the_v1_text_the_collection_stored(
    collected, tmp_path, monkeypatch
):
    """A value v1 leaves glued to a footnote mark is read after v2 frees it (S4-4)."""
    w = _copy(collected, tmp_path, monkeypatch)
    assert s4.main(report_argv(w)) == 0
    base = s4_json(w)
    (tmp_path / "sup").mkdir()
    w2 = world(tmp_path / "sup", monkeypatch)
    plan = copy.copy(PLAN["C3"])
    plan["zsrc-1.pdf"] = ok("page", text=table(G1, G2 + "<sup>(a)</sup>"), latency=LATENCY["C3"])
    for cid in ("C3", "C7", "C0"):
        model = Model(plan if cid == "C3" else PLAN[cid], answer(cid, G1, G2))
        assert collect(w2, monkeypatch, cid, model) == 0
    assert s4.main(report_argv(w2)) == 0
    sup = s4_json(w2)
    # zsrc-1: P now reads G2 (v2 frees it), C7 reads G2: f2 no longer escalated, and exact
    assert sup["parts"]["R"]["escalated_fields"] == base["parts"]["R"]["escalated_fields"] - 1
    assert sup["parts"]["R"]["recipe_yield"]["k"] == base["parts"]["R"]["recipe_yield"]["k"] + 1
