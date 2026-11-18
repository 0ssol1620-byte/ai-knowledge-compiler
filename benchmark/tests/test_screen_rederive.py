"""Offline re-derivation of S0 records with normaliser v2 (WO-D10-0V).

Every S0 directory here is written by the real S0 driver (``s0.main``) with the fake pod and
fake model of ``test_screen_s0``; nothing is real: synthetic pages, synthetic gold, fake token.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from benchmark.screen import normalise_v1 as n1
from benchmark.screen import normalise_v2 as n2
from benchmark.screen import rederive, s0, select_5h
from benchmark.screen.manifest import HoldoutGuard
from benchmark.tests.test_screen_s0 import (
    Clock,
    Model,
    Pod,
    argv,
    down,
    final,
    host,
    ok,
    refused,
    row,
    run,
    world,
)
from benchmark.v6.contracts import ContractError

BS = "\\"
REV_N = "ea2e1fe486bea3e7d0d505df9bafa4ad562407a0"
SERVED_N = f"nvidia/Nemotron-3.5-Parse@{REV_N}"
# the value is hidden from v1 by markup v1 left (a footnote glued to it); v2 frees it
SUP_PAGE = "<table><tr><td>Revenue</td><td>1,234<sup>(a)</sup></td></tr></table>"
PLAIN_PAGE = "<table><tr><td>Revenue</td><td>1,234</td></tr></table>"
# an empty box glued to the value: v1 left it, so the reader refused the token; v2 spaces it
BOX_PAGE = f"{BS}begin{{tabular}}{{cc}}\n{BS}thead{{Revenue}} & 1,234{BS}mbox{{}} {BS}{BS}\n"
BOX_PAGE += f"{BS}end{{tabular}}"
ORIGINS = [select_5h.DEGRADED if i % 2 else "born_digital_html_print" for i in range(8)]


def _chat_plan() -> dict[str, Any]:
    """One page of each kind the chat driver stores: re-derived, and passed through."""
    return {
        "p0.pdf": ok(text=SUP_PAGE),  # re-derived: v2 changes the text and the reading
        "p1.pdf": ok(text=PLAIN_PAGE),  # re-derived: v2 text equals v1's
        "p2.pdf": down,  # no output (provider_unavailable after its retry): passed through
        "p3.pdf": row("http_524"),  # a failure row with stored output: passed through
        "p4.pdf": refused,  # page_over_pixel_cap, no output: passed through
        "p5.pdf": lambda case: {k: v for k, v in ok()(case).items() if k != "warnings"},
    }  # p5: normalised, then contract_failed by run_screen in both runs


def _s0(w: Path, mp: pytest.MonkeyPatch, out: str = "c2") -> Path:
    rc, _, _ = run(w, mp, Model(_chat_plan(), ok(text=PLAIN_PAGE)), out=out)
    assert rc == 0
    return w / out


def _nemotron_s0(w: Path, mp: pytest.MonkeyPatch, out: str = "c5") -> Path:
    pod = Pod("chat")
    pod.body["/v1/models"] = json.dumps({"data": [{"id": SERVED_N}]}).encode()
    mp.setenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", host("chat"))
    clock = Clock()
    over = {"--candidate-id": "C5", "--provider": "nemotron_parse_3_5", "--revision": REV_N}
    rc = s0.main(
        argv(w, "chat", out, **over),
        request=pod,
        call=Model({}, ok(text=BOX_PAGE)),
        now=clock.now,
        sleep=clock.sleep,
    )
    assert rc == 0
    return w / out


def _args(w: Path, s0_dir: Path, out: str, provider: str = "ovis_ocr2") -> list[str]:
    return [
        "--s0",
        str(s0_dir),
        "--provider",
        provider,
        "--manifest",
        str(w / "manifest.json"),
        "--corpus-root",
        str(w / "corpus"),
        "--gold",
        str(w / "gold.jsonl"),
        "--out",
        str(w / out),
    ]


def _raw(d: Path, r: dict[str, Any]) -> dict[str, Any]:
    raw: dict[str, Any] = json.loads((d / "raw" / (r["record_key"][7:] + ".json")).read_bytes())
    return raw


def _tree(d: Path) -> dict[str, bytes]:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------- the real path


def test_rederive_replays_normalised_pages_with_v2_and_passes_failures_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = world(tmp_path, monkeypatch, pages=8)
    stored_dir = _s0(w, monkeypatch)
    before = _tree(stored_dir)
    capsys.readouterr()
    assert rederive.main(_args(w, stored_dir, "re")) == 0
    printed = capsys.readouterr().out
    assert _tree(stored_dir) == before  # S0's own records are never touched
    stored, fresh = final(w, "c2"), final(w, "re")
    assert [r["record_key"] for r in fresh] == [r["record_key"] for r in stored]
    by_doc = {old["doc_id"]: (old, new) for old, new in zip(stored, fresh, strict=True)}
    for doc in ("p2.pdf", "p3.pdf", "p4.pdf"):  # passed through unchanged, raw copied
        old, new = by_doc[doc]
        assert new == old
        if old["raw_sha256"] is not None:
            assert _raw(w / "re", new) == _raw(stored_dir, old)
    assert by_doc["p2.pdf"][1]["hard_failures"] == ["provider_unavailable"]
    assert by_doc["p4.pdf"][1]["hard_failures"] == ["page_over_pixel_cap"]
    for doc in ("p0.pdf", "p1.pdf", "p5.pdf", "p6.pdf"):  # re-derived with v2
        old, new = by_doc[doc]
        raw_old, raw_new = _raw(stored_dir, old), _raw(w / "re", new)
        before_text = raw_old["metrics"]["normaliser"]["text_before"]
        assert raw_new["text"] == n2.normalise("ovis_ocr2", before_text)[0]
        assert raw_new["metrics"]["normaliser"] == {
            "profile": "html",
            "module_sha256": n2.MODULE_SHA256,
            "text_before": before_text,
            "residual": n2.normalise("ovis_ocr2", before_text)[1],
            "residual_v1": raw_old["metrics"]["normaliser"]["residual"],
        }
        assert new["raw_sha256"] != old["raw_sha256"]
        assert {k: v for k, v in new.items() if k not in rederive.SCORED} == {
            k: v for k, v in old.items() if k not in rederive.SCORED
        }
    assert by_doc["p5.pdf"][1]["hard_failures"] == ["contract_failed"]
    old, new = by_doc["p0.pdf"]  # the footnote glued to the value hid it from v1 only
    assert (old["critical"]["exact"], new["critical"]["exact"]) == (0, 1)
    summary = json.loads((w / "re" / "rederive-summary.json").read_text(encoding="utf-8"))
    assert summary["pages"] == 8
    assert (summary["pages_rederived"], summary["pages_passed_through"]) == (5, 3)
    assert summary["pages_text_changed"] == 1
    assert summary["residual"] == {"v1_sum": 2, "v2_sum": 0}
    assert summary["kinds_left"] == {}
    receipt = json.loads((w / "re" / "rederive-receipt.json").read_text(encoding="utf-8"))
    body = (w / "re" / "final-records.jsonl").read_bytes()
    assert receipt["final_records_sha256"] == "sha256:" + hashlib.sha256(body).hexdigest()
    assert receipt["normaliser_v2_sha256"] == n2.MODULE_SHA256
    assert receipt["inputs"]["s0_final_records_sha256"] == (
        "sha256:" + hashlib.sha256((stored_dir / "final-records.jsonl").read_bytes()).hexdigest()
    )
    for b, old, new in zip(receipt["records"], stored, fresh, strict=True):
        line = json.dumps(old, ensure_ascii=False, sort_keys=True).encode()
        assert b["input_record_sha256"] == "sha256:" + hashlib.sha256(line).hexdigest()
        line = json.dumps(new, ensure_ascii=False, sort_keys=True).encode()
        assert b["output_record_sha256"] == "sha256:" + hashlib.sha256(line).hexdigest()
    # nothing printed carries page text, a doc id or a gold value
    for secret in ("Revenue", "1,234", "p0.pdf", "GOLD-ONLY"):
        assert secret not in printed
    assert printed.startswith("rederive done pages=8 rederived=5 residual 2 -> 0")


def test_rederived_records_are_what_the_driver_writes_when_it_normalises_with_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same fake pages, once through S0 on v1 then re-derived, once through the driver with
    v2 in place of v1: the records agree in everything but the raw digest (the normaliser block
    differs) and the latency of a page with no answer (the driver's own clock)."""
    w = world(tmp_path, monkeypatch, pages=8)
    assert rederive.main(_args(w, _s0(w, monkeypatch), "re")) == 0
    monkeypatch.setattr(s0, "normalise", n2.normalise)
    _s0(w, monkeypatch, out="v2drv")
    keep = {"raw_sha256", "latency_ms"}
    for a, b in zip(final(w, "re"), final(w, "v2drv"), strict=True):
        assert {k: v for k, v in a.items() if k not in keep} == {
            k: v for k, v in b.items() if k not in keep
        }
        if a["raw_sha256"] is not None:
            ra, rb = _raw(w / "re", a), _raw(w / "v2drv", b)
            assert ra.get("text") == rb.get("text")  # a failure row has none
            if a["accepted"]:  # a measured answer; a contract failure takes the driver's clock
                assert a["latency_ms"] == b["latency_ms"]


def test_nemotron_pages_rederive_and_select_reads_only_one_normaliser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world(tmp_path, monkeypatch, origins=ORIGINS)
    c2, c5 = _s0(w, monkeypatch), _nemotron_s0(w, monkeypatch)
    assert rederive.main(_args(w, c2, "re2")) == 0
    assert rederive.main(_args(w, c5, "re5", "nemotron_parse_3_5")) == 0
    summary = json.loads((w / "re5" / "rederive-summary.json").read_text(encoding="utf-8"))
    left_by_v1 = n1.normalise("nemotron_parse_3_5", BOX_PAGE)[1]
    assert left_by_v1 > 0 and n2.normalise("nemotron_parse_3_5", BOX_PAGE)[1] == 0
    assert summary["residual"] == {"v1_sum": 8 * left_by_v1, "v2_sum": 0}
    assert summary["pages_text_changed"] == 8
    old, new = final(w, "c5")[0], final(w, "re5")[0]
    assert (old["critical"]["exact"], new["critical"]["exact"]) == (0, 1)
    guard = HoldoutGuard(json.loads((w / "manifest.json").read_text()), w / "access.jsonl")
    v2_raw, mixed_raw = w / "raw-v2", w / "raw-mixed"  # C5's v1 and v2 raws share keys
    for d, into in (("re2", v2_raw), ("re5", v2_raw), ("re2", mixed_raw), ("c5", mixed_raw)):
        shutil.copytree(w / d / "raw", into, dirs_exist_ok=True)
    v2_only = final(w, "re2") + final(w, "re5")
    s1 = select_5h.select_s1(v2_only, guard=guard, baseline="C5", raw_dir=v2_raw)
    assert set(s1["kept"]) == {"C2", "C5"}
    assert select_5h.load_texts(v2_only, v2_raw)
    mixed = final(w, "re2") + final(w, "c5")  # C2 on v2, C5 still on v1
    with pytest.raises(ContractError, match="mix 2 normalisers"):
        select_5h.select_s1(mixed, guard=guard, baseline="C5", raw_dir=mixed_raw)
    with pytest.raises(ContractError, match="mix 2 normalisers"):
        select_5h.load_texts(mixed, mixed_raw)


# ---------------------------------------------------------------- refusals: nothing written


def _copy(w: Path, src: Path, name: str) -> Path:
    shutil.copytree(src, w / name)
    return w / name


def _first_with_raw(d: Path) -> dict[str, Any]:
    return next(r for r in final(d.parent, d.name) if r["raw_sha256"] is not None)


def test_a_raw_file_that_differs_from_its_record_is_exit_4_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = world(tmp_path, monkeypatch, pages=8)
    bad = _copy(w, _s0(w, monkeypatch), "bad")
    path = bad / "raw" / (_first_with_raw(bad)["record_key"][7:] + ".json")
    path.write_bytes(path.read_bytes().replace(b"1,234", b"1,235"))
    assert rederive.main(_args(w, bad, "re")) == s0.EXIT_INTEGRITY
    assert not (w / "re").exists() and not list(w.glob("re.partial-*"))
    assert "differs from its record" in capsys.readouterr().out
    path.unlink()
    assert rederive.main(_args(w, bad, "re")) == s0.EXIT_INTEGRITY
    assert not (w / "re").exists()


def test_a_text_before_that_v1_does_not_turn_into_the_stored_text_is_exit_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-signed so the raw digest matches: the stored v1 text is not v1(text_before)."""
    w = world(tmp_path, monkeypatch, pages=8)
    bad = _copy(w, _s0(w, monkeypatch), "bad")
    records = final(w, "bad")
    r = next(x for x in records if x["doc_id"] == "p1.pdf")
    path = bad / "raw" / (r["record_key"][7:] + ".json")
    raw = json.loads(path.read_bytes())
    raw["metrics"]["normaliser"]["text_before"] = SUP_PAGE  # v1 of it is not the stored text
    data = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    path.write_bytes(data.encode())
    r["raw_sha256"] = "sha256:" + hashlib.sha256(data.encode()).hexdigest()
    lines = "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in records)
    (bad / "final-records.jsonl").write_text(lines, encoding="utf-8")
    assert rederive.main(_args(w, bad, "re")) == s0.EXIT_INTEGRITY
    assert not (w / "re").exists()
    raw["metrics"]["normaliser"]["module_sha256"] = n2.MODULE_SHA256  # a block not from v1
    raw["metrics"]["normaliser"]["text_before"] = PLAIN_PAGE
    data = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    path.write_bytes(data.encode())
    r["raw_sha256"] = "sha256:" + hashlib.sha256(data.encode()).hexdigest()
    lines = "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in records)
    (bad / "final-records.jsonl").write_text(lines, encoding="utf-8")
    assert rederive.main(_args(w, bad, "re")) == s0.EXIT_INTEGRITY


def test_a_record_with_other_pins_or_a_missing_page_is_exit_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world(tmp_path, monkeypatch, pages=8)
    good = _s0(w, monkeypatch)
    records = final(w, "c2")
    for name, rows in (
        ("pins", [{**records[0], "image_digest": "sha256:" + "0" * 64}, *records[1:]]),
        ("short", records[1:]),
        ("twice", [*records, records[0]]),
    ):
        bad = _copy(w, good, name)
        lines = "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in rows)
        (bad / "final-records.jsonl").write_text(lines, encoding="utf-8")
        assert rederive.main(_args(w, bad, "re-" + name)) == s0.EXIT_INTEGRITY, name
        assert not (w / ("re-" + name)).exists()


def test_a_run_pinned_to_another_normaliser_is_exit_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world(tmp_path, monkeypatch, pages=8)
    bad = _copy(w, _s0(w, monkeypatch), "bad")
    pins = json.loads((bad / "s0-run.json").read_text(encoding="utf-8"))
    (bad / "s0-run.json").write_text(json.dumps({**pins, "normaliser_sha256": n2.MODULE_SHA256}))
    assert rederive.main(_args(w, bad, "re")) == s0.EXIT_INTEGRITY
    assert pins["normaliser_sha256"] == n1.MODULE_SHA256


def test_a_second_run_into_the_same_out_and_a_wrong_provider_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world(tmp_path, monkeypatch, pages=8)
    c2 = _s0(w, monkeypatch)
    assert rederive.main(_args(w, c2, "re")) == 0
    first = _tree(w / "re")
    assert rederive.main(_args(w, c2, "re")) == s0.EXIT_REFUSED  # write-once
    assert _tree(w / "re") == first
    assert rederive.main(_args(w, c2, "re-x", "ovis_ocr3")) == s0.EXIT_REFUSED
    assert rederive.main(_args(w, c2, "re-y", "gemini_api")) == s0.EXIT_REFUSED
    (w / "re-z").mkdir()  # an empty --out is taken
    assert rederive.main(_args(w, c2, "re-z")) == 0
    assert _tree(w / "re-z")["final-records.jsonl"] == first["final-records.jsonl"]
    assert not (w / "re-x").exists() and not (w / "re-y").exists()


def test_a_gold_or_corpus_that_is_not_the_runs_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world(tmp_path, monkeypatch, pages=8)
    c2 = _s0(w, monkeypatch)
    (w / "corpus" / "p0.pdf").write_bytes(b"changed")
    assert rederive.main(_args(w, c2, "re")) == s0.EXIT_REFUSED
    assert not (w / "re").exists()


def test_kinds_name_markup_only() -> None:
    text = f"<span a=1>x</span> {BS}frac{{1}} <x> </> 5"
    assert rederive.kinds(text) == {"<span>": 2, "\\frac": 1, "<x>": 1, "other": 1}


def test_a_text_before_over_the_drivers_bound_is_exit_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The driver never normalised a text over MAX_TEXT_CHARS: such a block is not its own."""
    w = world(tmp_path, monkeypatch, pages=8)
    c2 = _s0(w, monkeypatch)
    monkeypatch.setattr(rederive, "MAX_TEXT_CHARS", len(SUP_PAGE) - 1)
    assert rederive.main(_args(w, c2, "re")) == s0.EXIT_INTEGRITY
    assert not (w / "re").exists()
