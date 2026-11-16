from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from benchmark.runners.base import RunnerUnavailable
from benchmark.runners.registry import EXTERNAL_RUNNERS
from benchmark.screen.critical_fields import canonical_values, score_critical_fields
from benchmark.screen.manifest import HoldoutGuard, HoldoutSealedError
from benchmark.screen.run_screen import Candidate, ImmutableOutputError, run_screen
from benchmark.v6.contracts import ContractError

IMG = "sha256:" + "1" * 64
CFG = "sha256:" + "2" * 64
REV = "a" * 40
GOLD_MARKER = "GOLD-ONLY-MARKER"


def _candidate(**kw: Any) -> Candidate:
    base = {
        "candidate_id": "mineru-a",
        "provider": "mineru",
        "revision": REV,
        "image_digest": IMG,
        "config_sha256": CFG,
        "endpoint": "https://x.invalid/p",
        "allow_network": True,
    }
    return Candidate(**{**base, **kw})


def _setup(tmp_path: Path, pages: int = 2) -> tuple[HoldoutGuard, Path, dict[str, dict[str, Any]]]:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    body = b"hello"
    (corpus / "d1.txt").write_bytes(body)
    docs = [
        {
            "doc_id": "d1.txt",
            "source_sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
            "page_count": pages,
            "stratum": "s0",
            "language": "ko",
            "document_class": "c",
            "split": "dev",
        },
        {
            "doc_id": "h.txt",
            "source_sha256": "sha256:" + "9" * 64,
            "page_count": 1,
            "stratum": "s0",
            "language": "ko",
            "document_class": "c",
            "split": "holdout",
        },
    ]
    guard = HoldoutGuard(
        {"documents": docs, "manifest_sha256": "sha256:" + "0" * 64}, tmp_path / "log"
    )
    gold = {
        f"d1.txt#{p}": {
            "text": f"{GOLD_MARKER} 1,234.5억",
            "blocks": [],
            "critical_fields": [
                {"field_id": "f", "kind": "number", "value": "123450000000", "anchor": "영업이익"}
            ],
        }
        for p in range(pages)
    }
    return guard, corpus, gold


def _output(payload: dict[str, Any], text: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "benchmark_case_id": payload["benchmark_case_id"],
        "provider": "mineru",
        "model_revision": REV,
        "text": text,
        "reading_order": [],
        "blocks": [],
        "generated_claims": [],
        "metrics": {"latency_ms": 5.0, "gpu_seconds": 1.5, "estimated_cost_usd": 0.01},
        "warnings": [],
    }


def _run(
    tmp_path: Path, guard: HoldoutGuard, corpus: Path, gold: Any, cand: Candidate | None = None
) -> Any:
    return run_screen(
        guard=guard,
        split="dev",
        purpose="tune",
        candidate=cand or _candidate(),
        corpus_root=corpus,
        gold=gold,
        raw_dir=tmp_path / "raw",
        records_path=tmp_path / "rec.jsonl",
    )


def test_provider_exception_is_a_record_and_run_continues(tmp_path, monkeypatch):
    guard, corpus, gold = _setup(tmp_path)
    calls: list[str] = []

    def runner(payload, **_):
        calls.append(payload["benchmark_case_id"])
        if len(calls) == 1:
            raise RunnerUnavailable("pod died")
        return _output(payload, "영업이익 1,234.5억")

    monkeypatch.setitem(EXTERNAL_RUNNERS, "mineru", runner)
    recs = _run(tmp_path, guard, corpus, gold)
    assert [r["accepted"] for r in recs] == [False, True]
    assert recs[0]["hard_failures"] == ["provider_unavailable"] and recs[0]["raw_sha256"] is None
    assert recs[1]["critical"] == {"n": 1, "exact": 1, "accepted_errors": 0}
    assert recs[1]["gpu_seconds"] == 1.5 and recs[1]["provider_cost_usd"] == 0.01


def test_resume_does_not_call_provider_twice_and_retries_failures(tmp_path, monkeypatch):
    guard, corpus, gold = _setup(tmp_path)
    calls = []

    def runner(payload, **_):
        calls.append(1)
        if len(calls) == 1:
            raise RunnerUnavailable("down")
        return _output(payload, "x")

    monkeypatch.setitem(EXTERNAL_RUNNERS, "mineru", runner)
    _run(tmp_path, guard, corpus, gold)
    assert len(calls) == 2
    recs = _run(tmp_path, guard, corpus, gold)  # page 0 failed -> retried; page 1 cached
    assert len(calls) == 3
    assert all(r["accepted"] is not None for r in recs) and recs[0]["raw_sha256"]
    _run(tmp_path, guard, corpus, gold)
    assert len(calls) == 3


def test_changed_raw_output_raises(tmp_path, monkeypatch):
    guard, corpus, gold = _setup(tmp_path, pages=1)
    monkeypatch.setitem(EXTERNAL_RUNNERS, "mineru", lambda p, **_: _output(p, "a"))
    _run(tmp_path, guard, corpus, gold)
    raw = next((tmp_path / "raw").glob("*.json"))
    raw.write_bytes(raw.read_bytes() + b" ")
    with pytest.raises(ImmutableOutputError):
        _run(tmp_path, guard, corpus, gold)


def test_contract_failure_is_a_record(tmp_path, monkeypatch):
    guard, corpus, gold = _setup(tmp_path, pages=1)
    monkeypatch.setitem(EXTERNAL_RUNNERS, "mineru", lambda p, **_: {"text": "no schema"})
    (rec,) = _run(tmp_path, guard, corpus, gold)
    assert rec["hard_failures"] == ["contract_failed"] and rec["accepted"] is False


@pytest.mark.parametrize("field", ["image_digest", "revision"])
def test_candidate_without_pin_refuses(tmp_path, field):
    guard, corpus, gold = _setup(tmp_path)
    with pytest.raises(ContractError):
        _run(tmp_path, guard, corpus, gold, _candidate(**{field: "latest"}))


def test_payload_never_contains_gold(tmp_path, monkeypatch):
    guard, corpus, gold = _setup(tmp_path, pages=1)
    seen: list[str] = []

    def runner(payload, **_):
        seen.append(json.dumps(payload))
        return _output(payload, "x")

    monkeypatch.setitem(EXTERNAL_RUNNERS, "mineru", runner)
    _run(tmp_path, guard, corpus, gold)
    assert seen and GOLD_MARKER not in seen[0] and "critical_fields" not in seen[0]


def test_missing_gold_refuses_before_any_call(tmp_path, monkeypatch):
    guard, corpus, gold = _setup(tmp_path)
    monkeypatch.setitem(EXTERNAL_RUNNERS, "mineru", lambda p, **_: pytest.fail("called"))
    del gold["d1.txt#1"]
    with pytest.raises(ContractError):
        _run(tmp_path, guard, corpus, gold)


def test_holdout_needs_frozen_recipe(tmp_path):
    guard, corpus, gold = _setup(tmp_path)
    with pytest.raises(HoldoutSealedError):
        run_screen(
            guard=guard,
            split="holdout",
            purpose="evaluate_frozen",
            candidate=_candidate(),
            corpus_root=corpus,
            gold=gold,
            raw_dir=tmp_path / "r",
            records_path=tmp_path / "x.jsonl",
        )


def test_accepted_wrong_number_is_critical_error(tmp_path, monkeypatch):
    guard, corpus, gold = _setup(tmp_path, pages=1)
    monkeypatch.setitem(EXTERNAL_RUNNERS, "mineru", lambda p, **_: _output(p, "영업이익 1,234.6억"))
    (rec,) = _run(tmp_path, guard, corpus, gold)
    assert rec["accepted"] and rec["critical"] == {"n": 1, "exact": 0, "accepted_errors": 1}


def _same(a: str, b: str, kind: str = "number") -> bool:
    return canonical_values(kind, a) == canonical_values(kind, b) != set()


def test_number_normalisation():
    assert _same("1,234.5억", "123450000000")
    assert _same("1조 2,345억", "1234500000000")
    assert _same("(1,234)", "-1234") and _same("△1,000", "-1,000")
    assert _same("₩1,000", "1000원")
    assert not _same("-5%", "5%")
    assert not _same("5%", "0.05")
    assert not _same("₩1,000", "$1,000")
    assert not _same("1,234.5억", "123450000001")


def test_date_and_identifier_normalisation():
    assert _same("2024년 3월 5일", "2024.03.05", "date")
    assert canonical_values("date", "2024-02-30") == set()
    assert _same("123-45-67890", "1234567890", "identifier")


def test_unparseable_gold_fails_closed():
    with pytest.raises(ValueError):
        score_critical_fields(
            [{"field_id": "f", "kind": "number", "value": "n/a", "anchor": "a"}], "a 5"
        )
    s = score_critical_fields(
        [{"field_id": "f", "kind": "number", "value": "-5%", "anchor": "growth"}], "growth 5% up"
    )
    assert (s.n, s.exact, s.mismatched) == (1, 0, ("f",))


def _field(value: str, anchor: str = "a", kind: str = "number") -> dict[str, str]:
    return {"field_id": "f", "kind": kind, "value": value, "anchor": anchor}


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("영업이익은 1,234.5억원으로 증가", ("123450000000", "KRW")),
        ("가격 3,000원에 판매", ("3000", "KRW")),
        ("매출액1,234억 달성", ("123400000000", None)),
        ("금리는 -5%로", ("-5", "pct")),
        ("성장률 5%로", ("5", "pct")),
    ],
)
def test_korean_particles_do_not_break_numbers(text, want):
    (got,) = canonical_values("number", text)
    n, k, cur = got
    assert n == want[0] and (cur == want[1] or k == want[1])


def test_particle_after_number_is_not_a_false_match():
    assert score_critical_fields([_field("5", "성장률")], "성장률 5%로").exact == 0
    assert score_critical_fields([_field("3", "가격")], "가격 3,000원에").exact == 0
    assert score_critical_fields([_field("1,234.5억원", "a")], "a 1,234.5억원이").exact == 1


def test_trailing_comma_does_not_truncate():
    assert canonical_values("number", "1,234, and 5") == {("1234", "num", None), ("5", "num", None)}


def test_single_letter_scale_needs_no_space():
    assert canonical_values("number", "A: 200  B: 100") == {
        ("200", "num", None),
        ("100", "num", None),
    }
    assert canonical_values("number", "width 5 m") == {("5", "num", None)}
    assert canonical_values("number", "5m") == {("5000000", "num", None)}
    assert canonical_values("number", "3 million") == {("3000000", "num", None)}


def test_swapped_values_are_not_exact():
    gold = [
        {**_field("100", "A="), "field_id": "a"},
        {**_field("200", "B="), "field_id": "b"},
    ]
    assert score_critical_fields(gold, "A=200; B=100").mismatched == ("a", "b")
    assert score_critical_fields(gold, "A=100; B=200").exact == 2


def test_value_elsewhere_on_page_is_not_exact():
    s = score_critical_fields([_field("1,000", "Revenue")], "Revenue 2,000; note 1,000")
    assert (s.exact, s.mismatched) == (0, ("f",))
    assert score_critical_fields([_field("1,000", "Revenue")], "no label 1,000").exact == 0


@pytest.mark.parametrize("bad", [None, "", "  "])
def test_gold_without_anchor_is_refused(bad):
    f = {"field_id": "f", "kind": "number", "value": "5"}
    if bad is not None:
        f["anchor"] = bad
    with pytest.raises(ValueError):
        score_critical_fields([f], "5")


def test_local_write_failure_propagates_not_a_provider_failure(tmp_path, monkeypatch):
    guard, corpus, gold = _setup(tmp_path, pages=1)
    monkeypatch.setitem(EXTERNAL_RUNNERS, "mineru", lambda p, **_: _output(p, "x"))
    (tmp_path / "raw").write_text("a file, so the raw directory cannot be made")
    with pytest.raises(OSError):
        _run(tmp_path, guard, corpus, gold)
    assert not (tmp_path / "rec.jsonl").exists() or not (tmp_path / "rec.jsonl").read_text()


def test_unserializable_output_is_contract_failed(tmp_path, monkeypatch):
    guard, corpus, gold = _setup(tmp_path, pages=1)
    monkeypatch.setitem(EXTERNAL_RUNNERS, "mineru", lambda p, **_: {"x": object()})
    (rec,) = _run(tmp_path, guard, corpus, gold)
    assert rec["hard_failures"] == ["contract_failed"] and rec["raw_sha256"] is None


def test_unparseable_gold_stops_before_any_call(tmp_path, monkeypatch):
    guard, corpus, gold = _setup(tmp_path)
    gold["d1.txt#1"]["critical_fields"] = [_field("n/a")]
    monkeypatch.setitem(EXTERNAL_RUNNERS, "mineru", lambda p, **_: pytest.fail("called"))
    with pytest.raises(ValueError):
        _run(tmp_path, guard, corpus, gold)


class _ParserCrash(Exception):
    """Stands in for a third-party parser error that is neither ValueError nor RuntimeError."""


@pytest.mark.parametrize(
    "exc",
    [
        _ParserCrash("startxref not found"),
        KeyError("/Root"),
        IndexError("list index out of range"),
        AttributeError("NoneType has no attribute get_object"),
        ZeroDivisionError("division by zero"),
        RecursionError("maximum recursion depth exceeded"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        TypeError("unsupported operand"),
        OSError("bad stream"),
        ValueError("bad xref"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_any_provider_exception_is_a_record_and_run_continues(tmp_path, monkeypatch, exc):
    guard, corpus, gold = _setup(tmp_path)
    calls: list[int] = []

    def runner(payload, **_):
        calls.append(1)
        if len(calls) == 1:
            raise exc
        return _output(payload, "영업이익 1,234.5억")

    monkeypatch.setitem(EXTERNAL_RUNNERS, "mineru", runner)
    recs = _run(tmp_path, guard, corpus, gold)
    assert len(calls) == 2 and [r["accepted"] for r in recs] == [False, True]
    assert recs[0]["hard_failures"] == ["provider_error"] and recs[0]["raw_sha256"] is None
    lines = (tmp_path / "rec.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


_BROKEN = {
    "broken.pdf": b"%PDF-1.7\n1 0 obj << /Type /Catalog >> garbage no xref\n%%EOF\n",
    "broken.docx": b"PK\x03\x04" + b"\x00" * 40,
    "broken.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 20,
}


def test_native_lane_records_every_malformed_source_and_continues(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    docs = []
    for name, body in _BROKEN.items():
        (corpus / name).write_bytes(body)
        docs.append(
            {
                "doc_id": name,
                "source_sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
                "page_count": 1,
                "stratum": "malformed",
                "language": "ko",
                "document_class": "c",
                "split": "dev",
            }
        )
    guard = HoldoutGuard(
        {"documents": docs, "manifest_sha256": "sha256:" + "0" * 64}, tmp_path / "log"
    )
    gold = {f"{n}#0": {"text": "x", "blocks": [], "critical_fields": []} for n in _BROKEN}
    cand = Candidate("native", "native_document", REV, IMG, CFG)
    recs = _run(tmp_path, guard, corpus, gold, cand)
    assert [r["doc_id"] for r in recs] == list(_BROKEN)
    assert all(r["accepted"] is False and r["hard_failures"] for r in recs)
    assert all(r["raw_sha256"] is None for r in recs)


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_source_integrity_violation_stops_before_any_call(tmp_path, monkeypatch, damage):
    guard, corpus, gold = _setup(tmp_path)
    if damage == "missing":
        (corpus / "d1.txt").unlink()
    else:
        (corpus / "d1.txt").write_bytes(b"tampered")
    monkeypatch.setitem(EXTERNAL_RUNNERS, "mineru", lambda p, **_: pytest.fail("called"))
    with pytest.raises(ContractError):
        _run(tmp_path, guard, corpus, gold)
    assert not (tmp_path / "rec.jsonl").exists()


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("1천억원", "1,000억원"),
        ("1천억원", "100000000000원"),
        ("5천만", "50000000"),
        ("5백만원", "5,000,000원"),
        ("3십억", "3000000000"),
        ("1억2천만", "120000000"),
        ("5천5백만", "55000000"),
        ("1조 2천억", "1,200,000,000,000"),
        ("1,234천원", "1234000원"),
        ("12,345만", "123450000"),
    ],
)
def test_korean_compound_units_multiply(a, b):
    assert _same(a, b)


@pytest.mark.parametrize(
    ("gold", "candidate"),
    [
        ("1천", "영업이익 1천억"),
        ("5천", "영업이익 5천만"),
        ("5", "영업이익 5백만"),
        ("3", "영업이익 3십억"),
    ],
)
def test_prefix_of_a_unit_run_is_not_a_match(gold, candidate):
    assert score_critical_fields([_field(gold, "영업이익")], candidate).exact == 0


@pytest.mark.parametrize(
    "bad", ["5억만", "5천천", "5백천만", "1만2억", "1조 12,345억", "5천4,000만", "1억5000"]
)
def test_malformed_korean_unit_run_is_refused(bad):
    assert canonical_values("number", bad) == set()
    with pytest.raises(ValueError):
        score_critical_fields([_field(bad)], "a 5")


_BIG = (("조", 10**12), ("억", 10**8), ("만", 10**4))


def _ko_render(groups: list[int], styles: list[bool], spaces: list[bool]) -> str:
    """Independent renderer: one 0..9999 group per big unit, as digits or 천/백/십 words."""
    parts = []
    for (unit, _), g, words, sp in zip(_BIG, groups, styles, spaces, strict=True):
        if not g:
            continue
        if words:
            places = [(g // 1000, "천"), (g // 100 % 10, "백"), (g // 10 % 10, "십"), (g % 10, "")]
            body = "".join(f"{d}{u}" for d, u in places if d)
        else:
            body = f"{g:,}"
        parts.append(body + unit + (" " if sp else ""))
    return "".join(parts).strip()


_groups = st.lists(st.integers(0, 9999), min_size=3, max_size=3).filter(any)
_flags = st.lists(st.booleans(), min_size=3, max_size=3)


def _value(groups: list[int]) -> int:
    return sum(g * s for g, (_, s) in zip(groups, _BIG, strict=True))


@given(_groups, _flags, _flags)
def test_property_korean_rendering_is_exact(groups, styles, spaces):
    text, want = _ko_render(groups, styles, spaces), _value(groups)
    assert canonical_values("number", text) == {(str(want), "num", None)}
    assert canonical_values("number", text + "원") == {(str(want), "num", "KRW")}
    assert score_critical_fields([_field(text)], f"a {want:,}").exact == 1


@given(_groups, _flags, _flags, st.text("조억만천백십", min_size=1, max_size=3))
def test_property_trailing_unit_is_never_dropped(groups, styles, spaces, extra):
    text, want = _ko_render(groups, styles, spaces), _value(groups)
    assert (str(want), "num", None) not in canonical_values("number", text + extra)
    assert score_critical_fields([_field(text)], "a " + text + extra).exact == 0


def test_holdout_with_tune_purpose_raises(tmp_path):
    guard, corpus, gold = _setup(tmp_path)
    with pytest.raises(HoldoutSealedError):
        run_screen(
            guard=guard,
            split="holdout",
            purpose="tune",
            candidate=_candidate(),
            corpus_root=corpus,
            gold=gold,
            raw_dir=tmp_path / "r",
            records_path=tmp_path / "x.jsonl",
        )
