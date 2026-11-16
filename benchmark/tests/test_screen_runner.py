from __future__ import annotations

import hashlib
import json
import re
import string
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from hypothesis import assume, example, given, seed, settings
from hypothesis import strategies as st

from benchmark.runners.base import RunnerUnavailable
from benchmark.runners.registry import EXTERNAL_RUNNERS
from benchmark.screen.critical_fields import (
    canonical_values,
    gold_value,
    score_critical_fields,
    value_after_anchor,
)
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
    assert recs[0]["provider_error_type"] == "benchmark.runners.base.RunnerUnavailable"
    assert recs[1]["provider_error_type"] is None
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
        ("금리는 -5%로", ("-5", "pct")),
        ("성장률 5%로", ("5", "pct")),
    ],
)
def test_korean_particles_do_not_break_numbers(text, want):
    (got,) = canonical_values("number", text)
    n, k, cur = got
    assert n == want[0] and (cur == want[1] or k == want[1])


def test_label_glued_to_a_number_is_read_through_its_anchor_only():
    # Field first: in the whole text the number is a suffix of the field "매출액1,234억" and is
    # refused; cut at its anchor, the number starts the field and is read.
    assert canonical_values("number", "매출액1,234억 달성") == set()
    assert score_critical_fields([_field("1,234억", "매출액")], "매출액1,234억 달성").exact == 1


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
    want = f"{type(exc).__module__}.{type(exc).__qualname__}"
    assert recs[0]["provider_error_type"] == want and recs[1]["provider_error_type"] is None
    assert str(exc) not in json.dumps(recs[0], ensure_ascii=False)  # type only, no message
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
    assert recs[0]["provider_error_type"] == "pypdf.errors.PdfReadError"
    assert all(re.fullmatch(r"[\w.]+\.\w+", r["provider_error_type"]) for r in recs)


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


# Whole token or no token: a number glued to a tail that is not part of its grammar is not
# read at all, never as a shorter prefix (decimal, unit run, percent or currency dropped).
@pytest.mark.parametrize(
    ("gold", "candidate"),
    [
        ("2", "2.5mm"),
        ("12", "12.5x"),
        ("1", "1.5GB"),
        ("1", "1.5e3"),
        ("1.2", "1.2.3"),
        ("3.5", "3.5%p"),
        ("1", "1.5 천 억"),
        ("1", "1.5천천"),
        ("1", "1.5억억"),
        ("2", "2.5천백만"),
        ("100000000", "1억 2천 억"),
        ("300000000", "3억 5천만x"),
        ("5", "5원x"),
        ("5", "5억.3"),
        ("5", "50%5"),
        ("5", "5원5"),
        ("5", "(5)5"),
    ],
)
def test_glued_tail_never_yields_a_prefix(gold, candidate):
    assert canonical_values("number", candidate) == set()
    with pytest.raises(ValueError):
        score_critical_fields([_field(candidate)], "a 5")
    assert score_critical_fields([_field(gold)], "a " + candidate).exact == 0


@pytest.mark.parametrize(
    "bad", ["1.5억5천만", "1.5천5백만", "0.5조5천억", "5천 0.5천", "5억 0.5억", "1조 0.5조"]
)
def test_overlapping_places_are_refused(bad):
    """A fraction spills into the places after it, and a place may not repeat."""
    assert canonical_values("number", bad) == set()
    with pytest.raises(ValueError):
        score_critical_fields([_field(bad)], "a 5")


def test_fraction_in_the_last_group_is_kept():
    assert _same("1.5천억", "150000000000")
    assert _same("1조 2.5천억", "1250000000000")


def test_newline_separates_unit_groups():
    assert canonical_values("number", "3억\n5천만") == {
        ("300000000", "num", None),
        ("50000000", "num", None),
    }
    assert score_critical_fields([_field("350000000")], "a 3억\n5천만").exact == 0


_MANTISSA = st.builds(
    lambda i, frac, commas: (f"{i:,}" if commas else str(i)) + (f".{frac}" if frac else ""),
    st.integers(1, 10**6),
    st.sampled_from(["", "5", "25", "05", "125"]),
    st.booleans(),
)
_UNIT = st.sampled_from(
    ["", "억", "천만", "천억", "백만", "십억", "만", "조", "k", "m", " million"]
)
_SUFFIX = st.sampled_from(["", "%", "원", " USD", "달러"])
_GLUED = st.sampled_from(
    ["mm", "x", "GB", "e3", "%p", ".3.4", ",3", "천천", "억억", " 천 억", "천백만", "q"]
)


@given(_MANTISSA, _UNIT, _SUFFIX, st.sampled_from(["", "x", ".3", "5", "억", " 천"]))
def test_property_no_proper_prefix_value_is_read(mantissa, unit, suffix, tail):
    """Whatever the token reads as, it never reads as any of its own proper prefixes."""
    # Hangul after "%" or a currency is a particle by design ("5%로"), so the token ends there.
    assume(not (suffix and tail in ("억", " 천")))
    text = mantissa + unit + suffix + tail
    whole = canonical_values("number", text)
    for k in range(1, len(text)):
        assert not whole & canonical_values("number", text[:k]), (text, text[:k])


@given(_MANTISSA, _UNIT, _GLUED)
def test_property_glued_junk_yields_no_number(mantissa, unit, junk):
    token = mantissa + unit
    assert len(canonical_values("number", token)) == 1
    assert canonical_values("number", token + junk) == set()
    assert canonical_values("number", "a " + token + junk + " b") == set()
    with pytest.raises(ValueError):
        score_critical_fields([_field(token + junk)], "a 5")
    assert score_critical_fields([_field(token)], "a " + token + junk).exact == 0


@given(
    st.integers(0, 99),
    st.sampled_from(["5", "25", "05"]),
    st.sampled_from([("조", ["5천억", " 1억", "3만"]), ("억", ["5천만", " 1만", "3천"])]),
    st.integers(0, 2),
)
def test_property_fraction_before_another_group_is_refused(whole, frac, big_and_rest, i):
    big, rest = big_and_rest
    text = f"{whole}.{frac}{big}{rest[i]}"
    assert canonical_values("number", text) == set()


# --- Bounded cost: every scan is linear in the page, whatever the page holds. ---------------
# One alphabet of every character the number and date grammars react to. Each case is a short
# head, a long run of one short fill pattern, then a short tail, which is the shape of every
# super-linear input found so far (a whitespace run before a non-number, a run of signs,
# a long digit-group chain).
_ALPHABET = " \n\t-+()△▲$₩원%,.'/~_xk1억만천조십USD년월일\u00b9\u00bd"
_SCAN_CHARS = 120_000
_SCAN_BUDGET_S = 3.0  # linear is ~0.2 s here; the quadratic whitespace scan took ~15 s


def _scan_seconds(text: str) -> float:
    started = time.perf_counter()
    for kind in ("number", "date", "identifier"):
        canonical_values(kind, text)
    score_critical_fields([_field("1")], "a" + text)
    return time.perf_counter() - started


@pytest.mark.parametrize(
    "fill", [*sorted(set(_ALPHABET)), "1 ", "( ", "- ", "1,", "1억 ", "[(", '"(', "('"]
)
def test_every_single_pattern_run_scans_in_linear_time(fill):
    text = "a" + fill * (_SCAN_CHARS // len(fill)) + "x 1"
    assert _scan_seconds(text) < _SCAN_BUDGET_S, repr(fill)


@settings(max_examples=40, deadline=None)
@given(
    st.text(_ALPHABET, max_size=3),
    st.text(_ALPHABET, min_size=1, max_size=3),
    st.text(_ALPHABET, max_size=3),
)
@example(head="-", fill=" ", tail="x")
@example(head="$", fill="\n", tail="x")
def test_property_scan_time_is_bounded(head, fill, tail):
    text = head + fill * (_SCAN_CHARS // len(fill)) + tail
    assert _scan_seconds(text) < _SCAN_BUDGET_S, (head, fill, tail)


# --- Korean 만-grouped spacing (orthography art. 44): a bare digit group after a spaced unit
# group belongs to the same number, so the number is refused, never read as its prefix.
@pytest.mark.parametrize(
    ("gold", "candidate"),
    [
        ("12억 3456만", "A 12억 3456만 7898원"),
        ("1억 2,345만", "A 1억 2,345만 6,789원"),
        ("1만", "A 1만 9999"),
        ("10000", "A 1만 10000"),
        ("3억", "A 3억 5000"),
    ],
)
def test_bare_group_after_korean_group_is_not_a_prefix_match(gold, candidate):
    assert score_critical_fields([_field(gold, "A")], candidate).exact == 0
    with pytest.raises(ValueError):
        score_critical_fields([_field(candidate[2:])], "a 5")


@given(_groups, _flags, _flags, st.integers(0, 99999), st.booleans())
def test_property_bare_trailing_group_is_never_dropped(groups, styles, spaces, tail, commas):
    text = _ko_render(groups, styles, spaces) + " " + (f"{tail:,}" if commas else str(tail))
    assert canonical_values("number", text) == set()
    assert canonical_values("number", text + "원") == set()
    prefix = _ko_render(groups, styles, spaces)
    assert score_critical_fields([_field(prefix)], "a " + text).exact == 0


def test_tab_separates_korean_groups():
    assert canonical_values("number", "5천\t3억") == {
        ("5000", "num", None),
        ("300000000", "num", None),
    }


# --- Compatibility folding never builds a different number. ---------------------------------
@pytest.mark.parametrize(
    ("gold", "candidate"),
    [
        ("12.51", "A 12.5¹"),
        ("52", "A 5²"),
        ("11", "A 1½"),
        ("1234.52", "A 1,234.5²"),
        ("12.5", "A 12.5¹"),
        ("1", "A 1\u20442"),
        ("5", "A 5℃"),
        ("1.5", "A 1.5μm"),
        ("5", "A 5億"),
    ],
)
def test_footnote_fraction_and_symbol_glued_to_a_number_refuse_it(gold, candidate):
    assert score_critical_fields([_field(gold, "A")], candidate).exact == 0
    with pytest.raises(ValueError):
        score_critical_fields([_field(candidate[2:])], "a 5")


def _compat_chars() -> list[str]:
    keep = ("<wide>", "<narrow>", "<font>", "<noBreak>")
    out = []
    for cp in range(sys.maxunicode + 1):
        tag = unicodedata.decomposition(chr(cp))
        if (
            tag.startswith("<")
            and not tag.startswith(keep)
            and not unicodedata.normalize("NFKC", chr(cp)).isspace()
        ):
            out.append(chr(cp))
    return out


def test_no_compatibility_character_merges_into_a_number():
    """Exhaustive: every character NFKC would rewrite into other characters refuses the token."""
    chars = _compat_chars()
    assert len(chars) > 2000  # 2,362 on Python 3.13 (Unicode 15.1)
    for ch in chars:
        assert canonical_values("number", "12" + ch) == set(), repr(ch)
        assert canonical_values("number", ch + "12") == set(), repr(ch)
        assert canonical_values("number", "1.5" + ch + " x 7") == {("7", "num", None)}, repr(ch)
        assert canonical_values("number", ch + " 7") == set(), repr(ch)


def test_only_the_listed_folds_apply():
    assert _same("\uff11\uff0c\uff12\uff13\uff14억", "1,234억")  # fullwidth digits and comma
    assert _same("\uff081\uff0e5\uff05\uff09", "(1.5%)")  # fullwidth . % ( )
    assert _same("\u22125", "-5") and _same("\uff0d5", "-5")
    # Not on the list, so not folded: the character touches the token and refuses it.
    assert canonical_values("number", "1\u00a0억") == set()  # no-break space
    assert canonical_values("number", "\ufe635") == set()  # small hyphen-minus
    assert canonical_values("number", "\U0001d7cf\U0001d7d0") == set()  # mathematical digits
    assert canonical_values("number", "영업이익\u2009-5%") == set()  # thin space before a sign


# --- Signs, joiners and refused tokens: never a different number. ---------------------------
@pytest.mark.parametrize(
    "candidate",
    [
        "x-5",
        "Q3-5%",
        "--5",
        "-(5)",
        "1-5",
        "3~5억",
        "1/2",
        "10/20",
        "1'000",
        "1_000",
        "1..5",
        "\u20135",
        "1\u20135",
        "1+1",
    ],
)
def test_sign_or_joiner_glued_to_digits_reads_nothing(candidate):
    assert canonical_values("number", candidate) == set()
    assert score_critical_fields([_field("5", "A")], "A " + candidate).exact == 0
    with pytest.raises(ValueError):
        score_critical_fields([_field(candidate)], "a 5")


def test_spaced_parentheses_are_negative():
    assert _same("( 5 )", "-5") and _same("( 1,234억 )", "-123400000000")
    assert canonical_values("number", "5)") == set()  # a close paren with no open


def test_refused_token_after_anchor_is_not_skipped():
    assert score_critical_fields([_field("2억", "A")], "A 1.5억억 2억").exact == 0
    date_field = _field("2024-03-05", "A", "date")
    assert score_critical_fields([date_field], "A 2024-02-30 2024-03-05").exact == 0
    assert score_critical_fields([_field("AB1", "A", "identifier")], "A AB1¹ AB1").exact == 0


@pytest.mark.parametrize("bad", ["5 5", "1만 10000", "1.5억억 2억", "2.5mm 3"])
def test_gold_with_more_than_one_token_is_refused(bad):
    with pytest.raises(ValueError):
        score_critical_fields([_field(bad)], "a 5")


def test_deeply_nested_output_is_contract_failed(tmp_path, monkeypatch):
    guard, corpus, gold = _setup(tmp_path, pages=1)
    nested: list[Any] = []
    for _ in range(200_000):
        nested = [nested]
    monkeypatch.setitem(EXTERNAL_RUNNERS, "mineru", lambda p, **_: {"x": nested})
    (rec,) = _run(tmp_path, guard, corpus, gold)
    assert rec["hard_failures"] == ["contract_failed"] and rec["raw_sha256"] is None
    assert rec["provider_error_type"] == "builtins.RecursionError"


# --- Closed character set: a character outside the grammar never lets a token be read short. --
def _gold_refused(value: str, kind: str = "number") -> bool:
    try:
        gold_value(_field(value, "A", kind))
    except ValueError:
        return True
    return False


# Zero-width, format and combining characters, as PDF text extraction leaves them.
_INVISIBLE = [
    "\u200b",
    "\u200c",
    "\u200d",
    "\u2060",
    "\u00ad",
    "\ufeff",
    "\u200e",
    "\u200f",
    "\u0336",
    "\u0301",
    "\u20e3",
]


@pytest.mark.parametrize("ch", _INVISIBLE, ids=lambda c: f"U+{ord(c):04X}")
def test_invisible_character_inside_a_number_refuses_it(ch):
    assert score_critical_fields([_field("1", "A")], "A 1" + ch + "234").exact == 0
    assert score_critical_fields([_field("12.5", "A")], "A 12.5" + ch).exact == 0
    assert canonical_values("number", "1" + ch + "234") == set()
    assert _gold_refused("1" + ch + "234") and _gold_refused("12.5" + ch)
    assert (
        score_critical_fields([_field("2024-03-01", "A", "date")], "A 2024-03-1" + ch + "5").exact
        == 0
    )
    assert _gold_refused("2024-03-1" + ch + "5", "date")


@pytest.mark.parametrize("sep", ["\u202f", "\u2009", "\u00a0", "\u2002", "\u3000"])
def test_space_like_thousands_separator_refuses_the_number(sep):
    for text in (f"1{sep}000", f"1{sep}000{sep}000"):
        assert score_critical_fields([_field("1", "A")], "A " + text).exact == 0
        assert canonical_values("number", text) == set() and _gold_refused(text)


@pytest.mark.parametrize("text", ["\u02d75", "\u20525", "\u27965", "\u27685\u2769", "\u20105"])
def test_unlisted_minus_or_bracket_is_not_dropped(text):
    assert score_critical_fields([_field("5", "A")], "A " + text).exact == 0
    assert canonical_values("number", text) == set() and _gold_refused(text)


@pytest.mark.parametrize(
    "text",
    [
        "\u0661\u0662",
        "1\u0662",
        "\u0967\u0968",
        "\U0001d7cf\U0001d7d0",
        "\u0e51\u0e52",
        "\u1811\u1812",
    ],
)
def test_digit_outside_ascii_is_not_a_digit(text):
    assert score_critical_fields([_field("12", "A")], "A " + text).exact == 0
    assert canonical_values("number", text) == set() and _gold_refused(text)


@pytest.mark.parametrize("text", ["2024-03-05x", "2024-03-05\u00b9", "x2024-03-05", "2024-03-05-1"])
def test_date_touching_a_character_outside_its_grammar_is_refused(text):
    assert _gold_refused(text, "date")
    assert score_critical_fields([_field("2024-03-05", "A", "date")], "A " + text).exact == 0


def _outside_grammar() -> list[str]:
    """Every non-ASCII character of the classes that hide inside numbers in extracted text."""
    classes = {"Mn", "Mc", "Me", "Cf", "Cc", "Nd", "Nl", "No", "Zs", "Zl", "Zp", "Pd", "Sm"}
    listed = set("\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19\u2212\uff0d\uff0b")
    return [
        chr(cp)
        for cp in range(0x80, sys.maxunicode + 1)
        if unicodedata.category(chr(cp)) in classes and chr(cp) not in listed
    ]


def test_every_character_outside_the_grammar_refuses_a_token_it_touches():
    chars = _outside_grammar()
    assert len(chars) > 4000
    for ch in chars:
        assert canonical_values("number", "12" + ch) == set(), repr(ch)
        assert canonical_values("number", ch + "12") == set(), repr(ch)
        assert canonical_values("number", "1.5" + ch + " x 7") == {("7", "num", None)}, repr(ch)
        assert canonical_values("number", ch + " 7") == set(), repr(ch)


# Junk that is never part of a number: invisible, foreign digits, minus and bracket variants,
# space-like separators, symbols. ASCII space is in it, so junk can also stand apart.
_JUNK = (
    " "
    + "".join(_INVISIBLE)
    + "\u0661\u0967\u0e51\u1811\U0001d7cf\u00b9\u00bd\u2460"
    + "\u02d7\u2052\u2796\u2010\u2011\u2012\u2013\u2014\u2768\u2769"
    + "\u00a0\u202f\u2009\u2002\u3000\u00a4\u2103\u03bc\u5104"
)


@settings(max_examples=300)
@given(
    st.sampled_from(["", "-", "\u25b3", "$", "\u20a9"]),
    _MANTISSA,
    _UNIT,
    _SUFFIX,
    st.text(_JUNK, max_size=3),
    st.text(_JUNK, max_size=3),
)
def test_property_wide_junk_around_a_token_reads_it_whole_or_not_at_all(
    sign, mantissa, unit, suffix, head, tail
):
    token = sign + mantissa + unit + suffix
    whole = canonical_values("number", token)
    assume(len(whole) == 1)  # "$5원" names two currencies and is refused by design
    (want,) = whole
    text = head + token + tail
    got = canonical_values("number", text)
    assert got <= {want}, (text, got)
    # Every junk character but the space is unlisted, and a number joins across spaces, so
    # junk past a space may hide a part ("\u02d7 5"): any junk at all refuses the number.
    touched = bool(head.strip(" ") or tail.strip(" "))
    assert got == (set() if touched else {want}), text
    assert score_critical_fields([_field(token, "A")], "A " + text).exact == (not touched)
    if head.strip(" ") or tail.strip(" "):
        assert _gold_refused(text)
    else:
        assert gold_value(_field(text)) == want


# --- Exact arithmetic: a value is kept digit for digit or refused, never rounded. -------------
@pytest.mark.parametrize(
    ("gold", "candidate", "kept"),
    [
        ("12345678901234567890123456789", "12345678901234567890123456790", None),
        ("1.00000000000000000000000000001", "1", None),
        (
            "1234567890123456789012345678.9억",
            "1234567890123456789012345679억",
            "123456789012345678901234567890000000",
        ),
        ("1." + "0" * 29 + "1", "1", None),
        ("0." + "0" * 29 + "1", "0", None),
        ("1." + "0" * 29 + "1조", "1조", "1000000000000." + "0" * 17 + "1"),
        ("1." + "0" * 29 + "1 trillion", "1 trillion", "1000000000000." + "0" * 17 + "1"),
        ("9" * 30 + "조", "1" + "0" * 42, "9" * 30 + "0" * 12),
    ],
)
def test_long_numbers_are_not_rounded(gold, candidate, kept):
    assert gold_value(_field(gold)) == (kept or gold, "num", None)
    assert score_critical_fields([_field(gold, "A")], "A " + candidate).exact == 0
    assert score_critical_fields([_field(gold, "A")], "A " + gold).exact == 1


def test_number_beyond_exact_precision_is_refused():
    long = "1" * 101
    assert canonical_values("number", long) == set() and _gold_refused(long)
    assert canonical_values("number", "1" * 100) == {("1" * 100, "num", None)}


@pytest.mark.parametrize("bad", ["1.5 B", "1.5 mil", "5 apples", "3 \ubc31\ud654\uc810", "5 %p"])
def test_gold_is_exactly_one_token_and_nothing_else(bad):
    assert _gold_refused(bad)


# --- Linear at page scale: 1 MB against 256 KB for each kind of fill. ------------------------
def _kind_seconds(kind: str, text: str) -> float:
    started = time.perf_counter()
    canonical_values(kind, text)
    value_after_anchor(_field("x", "a", kind), text)
    return time.perf_counter() - started


def _best_seconds(kind: str, text: str) -> float:
    return min(_kind_seconds(kind, text) for _ in range(2))


@pytest.mark.parametrize("kind", ["number", "date", "identifier"])
@pytest.mark.parametrize(
    "fill",
    [
        " ",
        "\n",
        "1",
        "1 ",
        "1,",
        "1\uc5b5 ",
        "-x1.$ \uc5b5,\u00b9(",
        "2024-",
        "\u200b1\u00a0\u0661",
        "(",
        "[(",
        ":=|",
        "|5",
        "2024. 3. 5 ",
        "1 0",
    ],
    ids=[
        "space",
        "newline",
        "digits",
        "digit-space",
        "digit-comma",
        "ko-group",
        "junk",
        "date",
        "unicode-junk",
        "open-paren",
        "open-mixed",
        "label-separators",
        "label-digit",
        "spaced-date",
        "digit-space-digit",
    ],
)
def test_scan_time_grows_linearly_to_one_megabyte(fill, kind):
    small, large = (
        _best_seconds(kind, "a" + fill * (size // len(fill)) + "x 1")
        for size in (256_000, 1_024_000)
    )
    assert large <= 2 * 4 * small + 0.5, (kind, fill, small, large)


# --- No regular expression and no normalisation reads a token. -------------------------------
def test_scanner_uses_no_regex_and_no_normalisation():
    import ast

    import benchmark.screen.critical_fields as cf

    tree = ast.parse(Path(cf.__file__).read_text(encoding="utf-8"))
    imported = {
        a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    imported |= {
        (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    }
    assert not imported & {"re", "regex", "unicodedata", "fnmatch"}, imported
    called = {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert not called & {"match", "fullmatch", "search", "finditer", "findall", "sub"}


# --- A token touching junk or a joiner is refused and listed, never dropped or read short. ----
@pytest.mark.parametrize(
    ("gold", "candidate", "kind"),
    [
        ("12억", "A 12억 \u200b3456만", "number"),
        ("12억", "A 12억 \u00ad3456만", "number"),
        ("12억", "A 12억 \u20603456만", "number"),
        ("12억 3456만", "A 12억 3456만 \u200b7898원", "number"),
        ("5천만", "A 5천만 \u200b2천", "number"),
        ("5", "A 5,억", "number"),
        ("5", "A 5.억원", "number"),
        ("5", "A 5 .만", "number"),
        ("5", "A \u02d7 5", "number"),
        ("5", "A 5 \u200b%", "number"),
        ("3", "A 3 \u200bmillion", "number"),
        ("2024-03-06", "A 2024\u2010-03-05 2024-03-06", "date"),
        ("2024-03-06", "A 2024\u201003\u201005 (정정 2024-03-06)", "date"),
        ("2024-03-06", "A 2024\u200b-03-05 2024-03-06", "date"),
        ("2024-03-06", "A 2024\u00ad.03.05 2024-03-06", "date"),
        ("2024-03-06", "A 2024\u0301-03-05 2024-03-06", "date"),
        ("2024-03-06", "A 12024-03-05 2024-03-06", "date"),
        ("2024-03-06", "A 2024 03 05 2024-03-06", "date"),
        ("2024-03-06", "A 2024 \u2010 03 \u2010 05 2024-03-06", "date"),
        ("2024-03-06", "A 202\u200b4-03-05 2024-03-06", "date"),
        ("INV", "A INV_2024", "identifier"),
        ("v1", "A v1.2.3", "identifier"),
        ("KR", "A KR/2024/001", "identifier"),
        ("INV", "A INV:2024", "identifier"),
        ("INV", "A INV'2024", "identifier"),
        ("INV", "A INV@x", "identifier"),
        ("INV", "A INV#7", "identifier"),
        ("2024", "A INV_2024", "identifier"),
    ],
)
def test_token_touching_junk_or_a_joiner_is_refused_not_read_short(gold, candidate, kind):
    assert score_critical_fields([_field(gold, "A", kind)], candidate).exact == 0
    assert _gold_refused(candidate[2:], kind)


def test_refused_number_does_not_restart_inside_its_korean_groups():
    assert canonical_values("number", "\u200b12억 3456만") == set()
    assert canonical_values("number", "x12억 3456만") == set()


def test_only_ascii_spaces_join_the_parts_of_a_number():
    # A newline or a tab is a cell or line boundary: a lone "-" cell does not sign the next row.
    assert canonical_values("number", "-\n5") == {("5", "num", None)}
    assert canonical_values("number", "5\nmillion") == {("5", "num", None)}
    assert canonical_values("number", "5\t%") == {("5", "num", None)}
    assert canonical_values("number", "$\n5") == {("5", "num", None)}
    assert _same("- 5", "-5") and _same("5 %", "5%") and _same("3 million", "3000000")


@pytest.mark.parametrize("text", ["5\u1161", "\u11a85", "5억\u11a8", "5\u3131"])
def test_lone_jamo_is_not_a_particle(text):
    assert canonical_values("number", text) == set() and _gold_refused(text)


_DATE_TOKENS = ["2024-03-05", "2024.3.5", "2024/03/05", "2024년 3월 5일", "2024. 3. 5."]
_ID_TOKENS = ["AB12", "INV-2024", "X9", "kr2024001"]


@settings(max_examples=300)
@given(
    st.sampled_from([("date", t) for t in _DATE_TOKENS] + [("identifier", t) for t in _ID_TOKENS]),
    st.text(_JUNK, max_size=3),
    st.text(_JUNK, max_size=3),
)
def test_property_wide_junk_around_a_date_or_identifier_reads_it_whole_or_not_at_all(
    kind_token, head, tail
):
    kind, token = kind_token
    (want,) = canonical_values(kind, token)
    text = head + token + tail
    got = canonical_values(kind, text)
    assert got <= {want}, (text, got)
    # A date joins its parts across spaces, so junk past a space may hide one; an identifier
    # never spans a space, so only junk glued to it touches it.
    if kind == "date":
        touched = bool(head.strip(" ") or tail.strip(" "))
    else:
        touched = bool(head[-1:].strip(" ") or tail[:1].strip(" "))
    assert got == (set() if touched else {want}), text
    assert score_critical_fields([_field(token, "A", kind)], "A " + text).exact == (not touched)
    if head.strip(" ") or tail.strip(" "):
        assert _gold_refused(text, kind)
    else:
        assert gold_value(_field(text, "A", kind)) == want


# --- First token or nothing: what follows the anchor is read whole or refused, and a later ----
# token is never read in its place.
@pytest.mark.parametrize(
    ("gold", "candidate", "kind"),
    [
        *[
            ("2024-03-06", f"A 2024{sep}03{sep}05 2024-03-06", "date")
            for sep in string.punctuation.replace("-", "").replace("/", "").replace(".", "")
            + "가월"
        ],
        ("2024-03-06", "A 2024 _ 03 _ 05 2024-03-06", "date"),
        ("2024-03-06", "A 05.03.2024, 2024-03-06", "date"),
        ("2024-03-06", "A 03/05/2024, 2024-03-06", "date"),
        ("2024-03-06", "A 24.03.05, 2024-03-06", "date"),
        ("2024-03-06", "A 20240305, 2024-03-06", "date"),
        ("2024-03-06", "A 2024-03-05가3 2024-03-06", "date"),
        ("12", "A 12가3456", "identifier"),
        ("AB", "A AB가CD", "identifier"),
        ("INV", "A INV번호123", "identifier"),
        ("2024", "A 2024년3월", "identifier"),
        ("AB", "A AB가_CD", "identifier"),
        ("AB", "A AB:가CD", "identifier"),
        *[
            ("12억", f"A 12억 {tail}", "number")
            for tail in [
                "l456만",
                "O456만",
                "x3456만",
                ",3456만",
                ".3456만",
                "_3456만",
                "/3456만",
                "+3456만",
                "~3456만",
                "'3456만",
                "원3456만",
                "가3456만",
            ]
        ],
        ("5천만", "A 5천만 ,2천", "number"),
        ("5", "A 5. 만", "number"),
        ("5", "A 5, 억원", "number"),
        ("5", "A 5 , 억", "number"),
        ("5", "A 5:3", "number"),
        ("5", "A 5가3", "number"),
        ("5억", "A 5억가3", "number"),
        ("5", "A 5(3)", "number"),
        ("5", "A (5\n)", "number"),
        ("5", "A (5 ", "number"),
        ("5", "A 5-", "number"),
        ("5", "A 5- 3", "number"),
        ("3000000", "A 3 million 500 thousand", "number"),
        ("1000000000", "A 1 billion 200 million", "number"),
        ("5000", "A 5k 3", "number"),
    ],
)
def test_first_token_after_the_anchor_is_read_whole_or_refused(gold, candidate, kind):
    assert score_critical_fields([_field(gold, "A", kind)], candidate).exact == 0
    assert _gold_refused(candidate[2:], kind)


@pytest.mark.parametrize(
    ("gold", "candidate", "kind"),
    [
        ("12억", "A 12억 (전년 10억)", "number"),
        ("12억원", "A 12억 원", "number"),
        ("12억원", "A 12억 KRW", "number"),
        ("12억", "A 12억, 전년 10억", "number"),
        ("12억", "A 12억\n3456만", "number"),
        ("3000000", "A 3 million and more", "number"),
        ("5", "A 5:", "number"),
        ("5억원", "A 5억원이다.", "number"),
        ("INV2024", "A INV-2024를 확인", "identifier"),
        ("INV2024", "A 번호: INV-2024.", "identifier"),
        ("INV1", 'A "INV-1"', "identifier"),
        ("2024-03-05", "A (2024-03-05) 이후", "date"),
        ("2024-03-05", "A (2024-03-05)이후", "date"),
        ("2024-03-05", "A 2024년 3월 5일에", "date"),
        ("5", "A [5]", "number"),
        ("5", "A 5,", "number"),
        ("1000", "A 1,000", "number"),
        ("1", "A 1 0000", "number"),
        ("12억원", "A 12억원 (전년 10억원)", "number"),
    ],
)
def test_a_separated_token_is_still_read(gold, candidate, kind):
    assert score_critical_fields([_field(gold, "A", kind)], candidate).exact == 1


# The separator alphabet: every ASCII punctuation character, Hangul units and particles, ASCII
# letters and junk: zero-width, format and combining characters, digits outside ASCII and
# space-like characters that are not ASCII. A separator joins two token runs into one field.
_SEPARATOR = (
    string.punctuation
    + "조억만천백십가년월일원을이"
    + string.ascii_letters
    + "\u200b\u00ad\u00b9\u2010\u00e9\uff29"
    + "\u0301\u0336"  # combining
    + "\u0661\U0001d7cf"  # digits outside ASCII
    + "\u00a0\u202f\u2009"  # space-like, not ASCII
)
# A run before the first token run, inside the same field. Named opening punctuation is left
# out: stripping it is the one prefix the rule allows, and the gold side does not.
_LEADING = st.text("".join(sorted(set(_SEPARATOR) - set("([{\"'"))), max_size=3)
_DIGITS = st.text("0123456789", min_size=1, max_size=4)
_KO_GROUP = st.tuples(_DIGITS, st.sampled_from(["억", "만", "조", "천", "천만", "백억"]))
_FIRST_RUNS = {
    "number": st.one_of(_DIGITS, _KO_GROUP.map("".join)),
    "date": st.one_of(
        st.sampled_from(["2024", "1999"]), st.text("0123456789", min_size=1, max_size=2)
    ),
    "identifier": st.text(string.digits + string.ascii_letters, min_size=1, max_size=4),
}
_LATER = {"number": "987654321", "date": "2031-12-31", "identifier": "ZZ9QQ"}


@seed(20261117)
@settings(max_examples=600, deadline=None)
@given(st.sampled_from(sorted(_FIRST_RUNS)), st.data())
def test_property_value_after_anchor_is_the_first_token_or_nothing(kind, data):
    """The first field after the anchor is read whole or refused: never a prefix of it, never
    a suffix of it ("x=5", "\\u200b-;777"), and never the later token in its place."""
    runs = data.draw(st.lists(_FIRST_RUNS[kind], min_size=1, max_size=4))
    sep = st.text(_SEPARATOR, min_size=1, max_size=2)
    seps = data.draw(st.lists(sep, min_size=len(runs) - 1, max_size=len(runs) - 1))
    lead = data.draw(_LEADING)
    body = runs[0] + "".join(s + r for s, r in zip(seps, runs[1:], strict=True))
    first = lead + body
    # A run of label separators alone before the token is the anchor's own punctuation
    # ("A :5"): the field is read as the token after it. Gold never strips it.
    try:
        whole = gold_value(_field(body if set(lead) <= set(":=|") else first, "A", kind))
    except ValueError:
        whole = None
    later = gold_value(_field(_LATER[kind], "A", kind))
    got = value_after_anchor(_field("x", "A", kind), f"A {first} {_LATER[kind]}")
    assert got in (None, whole), (first, got, whole)
    assert got != later or whole == later, first


# --- ASCII-space thousands grouping: "1 000" cannot be told from 1 and 000, so it is refused. ---
@pytest.mark.parametrize(
    ("gold", "candidate"),
    [
        ("1", "A 1 000"),
        ("12", "A 12 345 678"),
        ("$1", "A $1 000"),
        ("-1", "A -1 000"),
        ("1", "A 1 000원"),
        ("1", "A 1 000."),
        ("1000", "A 1,000 000"),
        ("5", "A 5 ,000"),
        ("5", "A 5 .5"),
    ],
)
def test_ascii_space_thousands_grouping_is_refused(gold, candidate):
    assert score_critical_fields([_field(gold, "A")], candidate).exact == 0
    assert value_after_anchor(_field("x", "A"), candidate) is None
    assert _gold_refused(candidate[2:])


# --- Field first: a token is its whole field or nothing. Before it only named opening
# punctuation, after it only closing punctuation and one particle run; a prefix or a suffix of
# a field is never read, whatever stands next to it.
@pytest.mark.parametrize(
    ("gold", "candidate", "kind"),
    [
        ("5", "A 마이너스5", "number"),
        ("5", "A <5", "number"),
        ("5", "A >5", "number"),
        ("5", "A x=5", "number"),
        ("5", "A ref:5", "number"),
        ("5", "A @5", "number"),
        ("5", "A #5", "number"),
        ("5", "A 초과5", "number"),
        ("5", "A 미만5", "number"),
        ("5", "A 가5", "number"),
        ("5", "A 제5기", "number"),
        ("5", "A é:5", "number"),
        ("5", "A x:5", "number"),
        ("5", "A \u00a0;5", "number"),
        ("5", "A \u200b-;5", "number"),
        ("777", "A \u200b-;777", "number"),
        ("5", "A 5=", "number"),
        ("5", "A 5|=", "number"),
        ("5", "A x|5", "number"),
        ("5억", "A 약5억", "number"),
        ("5억원", "A 총5억원", "number"),
        ("12억 3456만원", "A 12억 3456만원 7", "number"),
        ("12억 3456만원", "A 12억 3456만원 7898", "number"),
        ("2024-03-05", "A <2024-03-05", "date"),
        ("2024-03-05", "A ~2024-03-05", "date"),
        ("2024-03-05", "A 기준일2024-03-05", "date"),
        ("2024-03-05", "A 약2024-03-05", "date"),
        ("2024-03-05", "A é:2024-03-05", "date"),
        ("2024-03-05", "A \u200b;2024-03-05", "date"),
        ("2024-03-05", "A 2024-03-05=", "date"),
        ("INV1", "A 번호INV-1", "identifier"),
        ("INV1", "A 번호:INV-1", "identifier"),
        ("AB12", "A 가가AB12", "identifier"),
        ("INV1", "A é:INV1", "identifier"),
        ("INV1", "A \u200b;INV1", "identifier"),
        ("INV", "A INV_ 2024", "identifier"),
        ("INV", "A INV- 2024", "identifier"),
        ("INV", "A -INV 2024", "identifier"),
        ("INV", "A INV= 2024", "identifier"),
    ],
)
def test_field_first_prefix_or_suffix_of_a_field_is_never_read(gold, candidate, kind):
    assert score_critical_fields([_field(gold, "A", kind)], candidate).exact == 0
    assert value_after_anchor(_field("x", "A", kind), candidate) is None
    assert _gold_refused(candidate[2:], kind)


# --- Label separators: "label:value" with no space is ordinary output. A run of ":" "=" "|"
# directly before the token is the anchor's own punctuation and is read through, for every
# kind; a trailing "|" is closing punctuation. Anything else glued before the token refuses it.
@pytest.mark.parametrize(
    ("candidate", "kind", "want"),
    [
        ("A :5", "number", ("5", "num", None)),
        ("A =5", "number", ("5", "num", None)),
        ("A |5|", "number", ("5", "num", None)),
        ("A |5", "number", ("5", "num", None)),
        ("A 5|", "number", ("5", "num", None)),
        ("A :=|5", "number", ("5", "num", None)),
        ("A :-5", "number", ("-5", "num", None)),
        ("A =(5)", "number", ("-5", "num", None)),
        ("A :$5", "number", ("5", "num", "USD")),
        ("A :12억 3456만", "number", ("1234560000", "num", None)),
        ("A :2024-03-05", "date", "2024-03-05"),
        ("A =2024-03-05", "date", "2024-03-05"),
        ("A |2024-03-05|", "date", "2024-03-05"),
        ("A :2024. 3. 5.", "date", "2024-03-05"),
        ("A =INV-1", "identifier", "INV1"),
        ("A :INV-1", "identifier", "INV1"),
        ("A |AB12|", "identifier", "AB12"),
        # Kept as they were (amendment A.1.3): a sign or currency standing alone before the
        # number joins it across an ASCII space; a parenthesised group after a Korean group is
        # not a continuation; closing punctuation, a particle, closing punctuation is tolerated.
        ("A - 5", "number", ("-5", "num", None)),
        ("A $ 5", "number", ("5", "num", "USD")),
        ("A 12억 (3456만)", "number", ("1200000000", "num", None)),
        ("A 5.이다", "number", ("5", "num", None)),
        ("A 12억;입", "number", ("1200000000", "num", None)),
        ('A "2024-03-05"부터', "date", "2024-03-05"),
        ('A "INV-1"을', "identifier", "INV1"),
    ],
)
def test_label_separator_directly_before_a_value_is_read(candidate, kind, want):
    assert value_after_anchor(_field("x", "A", kind), candidate) == want


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        (":5", "number"),
        ("=5", "number"),
        ("|5|", "number"),
        ("5|", "number"),
        (":2024-03-05", "date"),
        ("=INV-1", "identifier"),
    ],
)
def test_gold_with_a_label_separator_is_not_one_token(value, kind):
    assert _gold_refused(value, kind)


# --- Dates use one separator, and spaces only after a separator of the dotted or 년/월/일 form.
@pytest.mark.parametrize(
    "text",
    [
        "2024-03/05",
        "2024/03-05",
        "2024.03-05",
        "2024-03.05",
        "2024 - 03 - 05",
        "2024-03 -05",
        "2024 /03/05",
        "2024- 03-05",
        "2024/ 03/ 05",
        "2024 .03.05",
        "2024. 3 .5",
        "2024 년 3월 5일",
        "2024년 3 월 5일",
        "2024년 3월 5 일",
        "2024. 3월 5일",
        "2024년 3. 5.",
    ],
)
def test_date_uses_one_separator_and_spaces_only_after_it(text):
    assert value_after_anchor(_field("x", "A", "date"), "A " + text) is None
    assert score_critical_fields([_field("2024-03-05", "A", "date")], "A " + text).exact == 0
    assert _gold_refused(text, "date")


@pytest.mark.parametrize(
    "text",
    [
        "2024-03-05",
        "2024/3/5",
        "2024.3.5",
        "2024.03.05.",
        "2024. 3. 5.",
        "2024. 03. 05",
        "2024년 3월 5일",
        "2024년3월5일",
    ],
)
def test_one_separator_date_is_read(text):
    assert gold_value(_field(text, "A", "date")) == "2024-03-05"
    assert value_after_anchor(_field("x", "A", "date"), "A " + text + " 2031-12-31") in (
        "2024-03-05",
        None,  # a spaced date followed by a digit field: see the continuation property
    )
    assert value_after_anchor(_field("x", "A", "date"), "A " + text + "\n2031-12-31") == (
        "2024-03-05"
    )


# --- Independent-value property (amendment A.2.1). The test generates a value and renders it
# to a token itself; it never asks the reader what a token is worth.
_PROPERTY_JUNK = (
    string.punctuation
    + string.ascii_letters
    + string.digits
    + "조억만천백십"  # scale syllables
    + "가을이다부터입니년월일"  # non-scale Hangul
    + "\u200b\u200c\u200d\u2060\ufeff\u00ad\u200e\u200f"  # zero-width and format
    + "\u0301\u0336\u20e3"  # combining
    + "\u00a0\u202f\u2009"  # space-like, not ASCII
    + "\u0661\u0967\u0e51\U0001d7cf"  # Arabic-Indic, Devanagari, Thai, mathematical digits
    + "\u02d7\u2052\u2796"  # minus variants
    + "\u00b9\u00b2\u00b3\u2070\u00bd\u00bc\u2153"  # superscripts, vulgar fractions
)
_LABEL_SEPARATORS = ":=|"
_CLOSING = ")]}\"'.,;:!?|"
_ALNUM = string.ascii_letters + string.digits


@st.composite
def _number_token(draw: Any) -> tuple[str, Any]:
    style = draw(st.sampled_from(["plain", "comma", "decimal", "korean"]))
    if style == "korean":
        groups = draw(_groups)
        text, digits = _ko_render(groups, draw(_flags), draw(_flags)), str(_value(groups))
    elif style == "decimal":
        whole = draw(st.integers(0, 10**9))
        frac = draw(st.text("0123456789", min_size=1, max_size=6).filter(lambda f: f[-1] != "0"))
        text = digits = f"{whole}.{frac}"
    else:
        n = draw(st.integers(0, 10**12))
        text, digits = (f"{n:,}" if style == "comma" else str(n)), str(n)
    pct = style != "korean" and draw(st.booleans())
    currency = None if pct else draw(st.sampled_from([None, "USD", "KRW"]))
    if currency == "USD":
        text = "$" + text
    elif currency == "KRW":
        text += "원"
    if pct:
        text += "%"
    negative = digits.strip("0.") != "" and draw(st.booleans())
    if negative:
        text = draw(st.sampled_from([f"-{text}", f"({text})"]))
    return text, (("-" if negative else "") + digits, "pct" if pct else "num", currency)


@st.composite
def _date_token(draw: Any) -> tuple[str, Any]:
    d = draw(st.dates(min_value=date(1000, 1, 1), max_value=date(9999, 12, 31)))
    y = f"{d.year:04d}"
    pad = draw(st.booleans())
    m, dd = (f"{d.month:02d}", f"{d.day:02d}") if pad else (str(d.month), str(d.day))
    form = draw(st.sampled_from(["-", "/", ".", "spaced-dot", "ko", "spaced-ko"]))
    if form in ("-", "/", "."):
        text = f"{y}{form}{m}{form}{dd}"
    elif form == "spaced-dot":
        text = f"{y}. {m}. {dd}."
    else:
        sp = " " if form == "spaced-ko" else ""
        text = f"{y}년{sp}{m}월{sp}{dd}일"
    return text, d.isoformat()


@st.composite
def _identifier_token(draw: Any) -> tuple[str, Any]:
    chunks = draw(st.lists(st.text(_ALNUM, min_size=1, max_size=4), min_size=1, max_size=3))
    return "-".join(chunks), "".join(chunks).upper()


_TOKENS = {"number": _number_token(), "date": _date_token(), "identifier": _identifier_token()}


def _edge_joins(kind: str, pre: str, post: str) -> bool:
    """Would the character of ``pre`` or ``post`` at the token's edge be read as part of the
    token by its grammar ("1." + "5", "x-" + "AB", "5" + "억"): then the field is a different,
    longer token and its value is that token's own, which this property does not judge."""
    a, b = pre[-1:], post[:1]
    if (a and a in _ALNUM) or (b and b in _ALNUM):
        return True
    if kind == "identifier":
        return "-" in (a, b)
    if kind != "number":
        return False
    return bool(
        (a and a in "-+\u25b3\u25b2($€£¥₩원엔조억만천백십")
        or pre.endswith("달러")
        or (a and a in ".," and pre[-2:-1] and pre[-2:-1] in string.digits)
        or (b and b in "%조억만천백십원엔$€£¥₩")
        or post.startswith("달러")
        or (b and b in ".," and post[1:2] and post[1:2] in string.digits)
    )


@seed(20261117)
@settings(max_examples=500, deadline=None)
@given(
    st.sampled_from(sorted(_TOKENS)),
    st.data(),
    st.text(_PROPERTY_JUNK, max_size=3),
    st.text(_PROPERTY_JUNK, max_size=3),
)
def test_property_value_read_is_the_generated_value_or_nothing(kind, data, pre, post):
    token, value = data.draw(_TOKENS[kind])
    later, later_value = data.draw(_TOKENS[kind])
    assume(later_value != value and not _edge_joins(kind, pre, post))
    field = _field("x", "A", kind)
    # The later token on the next line: across a space a later number may be a grammatical
    # continuation ("12억 3456만") and a digit field after a spaced date refuses it, both of
    # which the continuation property decides. Date and identifier are also read across a space.
    seps = ["\n", " "] if kind != "number" else ["\n"]
    for sep in seps:
        got = value_after_anchor(field, f"A {pre}{token}{post}{sep}{later}")
        # (i) the generated value or nothing: never the later value, never any other.
        assert got in (None, value), (kind, pre, token, post, sep, got, value)
    # (ii) with nothing glued to it, the token is read: a reader that refuses all fails here.
    assert value_after_anchor(field, f"A {token}\n{later}") == value, token
    # (iii) a run of label separators before it, nothing after: still read.
    lead = data.draw(st.text(_LABEL_SEPARATORS, min_size=1, max_size=3))
    assert value_after_anchor(field, f"A {lead}{token}\n{later}") == value, (lead, token)
    # (iv) opening punctuation before it and closing punctuation after it: still read. For a
    # number "(" and ")" belong to the grammar (accounting negative), so they are left out.
    opening = "[{\"'" + ("" if kind == "number" else "(")
    closing = _CLOSING.replace(")", "") if kind == "number" else _CLOSING
    lead = data.draw(st.text(_LABEL_SEPARATORS + opening, max_size=3))
    trail = data.draw(st.text(closing, max_size=3))
    assert value_after_anchor(field, f"A {lead}{token}{trail}\n{later}") == value, (
        lead,
        token,
        trail,
    )
    # (v) amendment A.4: a standalone sign or currency field, an ASCII space, then label
    # separators or opening punctuation: refused, never the unsigned or currency-less value.
    if kind == "number":
        alone = data.draw(st.sampled_from(_STANDALONE))
        lead = data.draw(st.text(_LABEL_SEPARATORS + "([{\"'", min_size=1, max_size=3))
        assert value_after_anchor(field, f"A {alone} {lead}{token}\n{later}") is None, (
            alone,
            lead,
            token,
        )


# A sign, an accounting "(" or a currency, each a field of its own before a number.
_STANDALONE = ["-", "+", "△", "▲", "(", "$", "₩", "€", "£", "¥"]
_STANDALONE += ["\uff04", "\u2212", "USD", "krw", "Eur", "원", "달러", "엔"]
# Every currency spelling the reader knows, as written (codes in upper case), and its code.
_CURRENCY_CODES = {
    "$": "USD",
    "USD": "USD",
    "달러": "USD",
    "₩": "KRW",
    "원": "KRW",
    "KRW": "KRW",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "¥": "¥",
    "엔": "JPY",
    "JPY": "JPY",
}
_CURRENCY_SPELLINGS = frozenset(_CURRENCY_CODES)


# --- Amendment A.4: once a sign, "(" or currency is consumed for a number, the number is read
# with it or refused; the scan never restarts past it and reads the number without it.
@pytest.mark.parametrize(
    "candidate",
    [
        "A - :5",
        "A - =5",
        "A - |5|",
        "A + :5",
        "A △ :5",
        "A ( :5 )",
        "A - :5억",
        "A $ :5",
        "A $ =5",
        "A ₩ :5",
        "A USD :5",
        "A - [5]",
        'A - "5"',
        "A $ [5]",
        "A $ - 5",
        # The same class, not listed in A.4: whitespace other than a space, a table cell, a
        # field of two prefixes that the grammar does not join, an opening run glued to "(".
        "A -\t5",
        "A $\n5",
        "A | - | 5 |",
        "A -- 5",
        "A $- 5",
        "A -( 5)",
        'A ("5")',
        "A ([5])",
        "A - x 5",
        "A $USD 5",
        "A - (5)",
        # Amendment A.5: a sign or "(" standing alone, whitespace, then a word or label that
        # begins with a currency: refused like any other non-digit, never the bare number.
        "A - 원가 5",
        "A - 원래 5",
        "A △ 원가 5",
        "A + 원가 5",
        "A ▲ 달러화 5",
        "A - 엔화 5",
        "A - Euro 5",
        "A - EURO 5",
        "A - usdx 5",
        "A - 원) 5",
        "A - $) 5",
        "A - USD) 5",
        "A - 원] 5",
        "A - 원} 5",
        "A - 원가 :5",
        "A △ 엔) 5",
        "A ( 원) 5",
        "A ( $) 5",
        "A ( 원가 5 )",
        "A - 원화 5억",
        "A -\t원가 5",
        "A (\t원) 5",
    ],
)
def test_a_consumed_sign_paren_or_currency_is_never_dropped(candidate):
    assert value_after_anchor(_field("x", "A"), candidate) is None
    assert score_critical_fields([_field("5", "A")], candidate).exact == 0


@pytest.mark.parametrize(
    ("candidate", "want"),
    [
        # A prefix glued into a word is not a prefix: the word is text, the number after it reads.
        ("A 원가 5", ("5", "num", None)),  # 원가: cost
        ("A (주) 5", ("5", "num", None)),  # (주)
        ("A (단위: 원) 1,234", ("1234", "num", None)),  # (단위: 원), a unit header
        ("A (USD) 5", ("5", "num", None)),
        ("A -$ 5", ("-5", "num", "USD")),
        ("A ( 5 )", ("-5", "num", None)),
        # Amendment A.5: only glued shapes are text.
        ("A (원) 5", ("5", "num", None)),
        ("A (단위: 원) 5", ("5", "num", None)),
        ("A -원가 5", ("5", "num", None)),
        # A sign, a space, then a currency glued to the digits: the signed currency value.
        ("A - 원5", ("-5", "num", "KRW")),
        ("A - $ 5", ("-5", "num", "USD")),
    ],
)
def test_a_prefix_glued_into_a_word_or_a_unit_label_is_text(candidate, want):
    assert value_after_anchor(_field("x", "A"), candidate) == want


@seed(20261117)
@settings(max_examples=500, deadline=None)
@given(
    _number_token(),
    st.sampled_from(_STANDALONE),
    st.text(" \t\n\r", min_size=1, max_size=3),
    st.one_of(
        st.text(_PROPERTY_JUNK + " " + "△▲₩원", max_size=4),
        # Words and labels that begin with a currency (amendment A.5).
        st.sampled_from(["원가", "원래", "Euro", "usdx", "달러화", "엔화", "원)", "$)", "USD]"]),
    ),
)
@example(("5", ("5", "num", None)), "-", " ", "원가 ")
@example(("5", ("5", "num", None)), "(", " ", "$) ")
def test_property_a_standalone_prefix_field_is_read_with_the_number_or_refuses(
    rendered, alone, ws, junk
):
    """A standalone sign, "(" or currency field, whitespace, then anything that does not start
    with a digit, then a token: the prefix was consumed and nothing joins it to the number, so
    the result is None. Past spaces alone the prefix joins the token; with a digit right after
    the whitespace the field is a different, longer number, which this property does not judge,
    and neither is a currency glued to the token's digits ("- 원5" is a signed currency value).
    """
    token, _ = rendered
    assume(junk[:1] not in string.digits + " ")
    assume(junk or ws.strip(" "))
    assume(not (junk.upper() in _CURRENCY_SPELLINGS and token[:1] in string.digits))
    got = value_after_anchor(_field("x", "A"), f"A {alone}{ws}{junk}{token}\n7")
    assert got is None, (alone, ws, junk, token, got)


# Amendment A.5, closed by enumeration: every standalone prefix the reader knows, every ASCII
# whitespace run after it, one representative of every character class the reader tells apart
# at the next position, and a fixed set of continuations.
_NEGATIVE_PREFIXES = ["-", "\u2212", "△", "▲", "(", "\uff08"]
_SIGN_PREFIXES = ["-", "\u2212", "+", "△", "▲"]
_CURRENCY_PREFIXES = [*sorted(_CURRENCY_SPELLINGS), "usd", "Krw", "\uff04", "\uffe6", "\uffe1"]
_FOLDED_CURRENCY = {"\uff04": "USD", "\uffe6": "KRW", "\uffe1": "GBP"}
_NEXT_CLASSES = sorted(
    set("([{\"':=|")  # opening punctuation and label separators
    | set("-+△▲")  # signs
    | {s[0] for s in _CURRENCY_SPELLINGS}  # currency first characters
    | {s[0].lower() for s in _CURRENCY_SPELLINGS}
    | _CURRENCY_SPELLINGS  # whole currencies
    | set("x가")  # an ASCII letter, a Hangul syllable
    | set("조억만천백십")  # scale syllables
    | set(_CLOSING)
)


def test_a_standalone_prefix_then_whitespace_never_yields_the_bare_number():
    """``A `` + P + S + N + rest: the result is None, except that a sign, spaces, a whole
    currency and then the digits read as the signed currency value ("- 원5", "- $ 5"). Never
    the bare, unsigned or currency-less number."""
    wrong = []
    for p in [*_SIGN_PREFIXES, "(", "\uff08", *_CURRENCY_PREFIXES]:
        for s in [" ", "\t", "\n", "\r", "  ", " \t"]:
            for nxt in _NEXT_CLASSES:
                for rest in ["5", " 5", "가 5", ") 5", " :5"]:
                    text = f"A {p}{s}{nxt}{rest}"
                    want = None
                    joined = p in _SIGN_PREFIXES and not s.strip(" ")
                    if joined and nxt in _CURRENCY_SPELLINGS and rest in ("5", " 5"):
                        sign = "-" if p in _NEGATIVE_PREFIXES else ""
                        want = (sign + "5", "num", _CURRENCY_CODES[nxt])
                    got = value_after_anchor(_field("x", "A"), text)
                    if got != want:
                        wrong.append((text, got, want))
    assert not wrong, (len(wrong), wrong[:20])


@pytest.mark.parametrize("p", [*_CURRENCY_PREFIXES, "(", "-"])
def test_every_standalone_prefix_is_read_with_the_number_across_spaces(p):
    """The enumeration above is not vacuous: each prefix, spaces, then digits, carries P."""
    got = value_after_anchor(_field("x", "A"), f"A {p} 5" + (" )" if p == "(" else ""))
    assert got is not None and got != ("5", "num", None), (p, got)
    code = _FOLDED_CURRENCY.get(p) or _CURRENCY_CODES.get(p.upper())
    assert got[2] == code and got[0] == ("-5" if p in "(-" else "5"), (p, got)


# --- Continuation property (amendment A.2.2): the field after a Korean scale group, or after a
# part of a spaced date, continues it wholly or the whole value is refused.
# A field with no digit and no scale syllable, shaped as text after a value ends: closing
# punctuation, a run of words or particles, closing punctuation ("이다.", "전년", ").").
_NOT_A_PART = st.builds(
    lambda a, w, b: a + w + b,
    st.text(_CLOSING, max_size=2),
    st.text("가을이다부터입니전년대비", max_size=3),
    st.text(_CLOSING, max_size=2),
).filter(bool)
_GLUE = st.text("xX_~/\\@#=<>+-*\u200b\u00b9\u0661", min_size=1, max_size=2)
_LOWER = {"조": [("억", 10**8), ("만", 10**4)], "억": [("만", 10**4), ("천만", 10**7)]}
_KO_SCALE = "조억만천백십"


@seed(20261117)
@settings(max_examples=300, deadline=None)
@given(st.integers(1, 9999), st.sampled_from(["조", "억"]), st.data())
def test_property_a_field_after_a_korean_group_continues_it_wholly_or_refuses(n, big, data):
    value = n * (10**12 if big == "조" else 10**8)

    def read(g: str) -> Any:
        return value_after_anchor(_field("x", "A"), f"A {n}{big} {g}")

    unit, scale = data.draw(st.sampled_from(_LOWER[big]))
    m = data.draw(st.integers(1, 9 if unit == "천만" else 9999))
    part = f"{m}{unit}"
    # A whole lower group joins.
    assert read(part) == (str(value + m * scale), "num", None), part
    # A field with an ASCII digit that is not a whole continuation refuses the whole value.
    glue = data.draw(_GLUE)
    for bad in (glue + part, part + glue, f"{glue}{m}", f"{m}{glue}", f"{m}{glue}{unit}"):
        assert read(bad) is None, bad
    # So does a field that begins with a scale syllable.
    scaled = data.draw(st.sampled_from(_KO_SCALE)) + data.draw(st.text(_PROPERTY_JUNK, max_size=3))
    assert read(scaled) is None, scaled
    # A bare final group is a continuation by orthography (art. 44); it joins or refuses.
    assert read(str(m)) in (None, (str(value + m), "num", None))
    # A field with neither, of words and closing punctuation, leaves the value standing.
    word = data.draw(_NOT_A_PART)
    assert read(word) == (str(value), "num", None), word
    # A parenthesised field is never joined, whatever it holds.
    inside = data.draw(st.text(_PROPERTY_JUNK, max_size=4))
    assert read(f"({inside}") == (str(value), "num", None), inside
    # Any other field with no ASCII digit may still refuse, and never gives another value (kept,
    # A.1.3: an OCR "l" or "O", a hidden character or a spaced "~ 15억" can stand for a part).
    other = data.draw(
        st.text(_PROPERTY_JUNK.translate({ord(c): None for c in string.digits}), min_size=1)
    )
    got = read(other)  # a currency or percent word is the spaced suffix the grammar defines
    assert got is None or got[0] == str(value), (other, got)


@seed(20261117)
@settings(max_examples=300, deadline=None)
@given(
    st.dates(min_value=date(1000, 1, 1), max_value=date(9999, 12, 31)),
    st.sampled_from(["dot", "ko"]),
    st.data(),
)
def test_property_a_field_in_or_after_a_spaced_date_completes_it_wholly_or_refuses(d, form, data):
    iso = d.isoformat()
    m, dd = d.month, d.day
    if form == "dot":
        parts = [f"{d.year:04d}.", f"{m}.", f"{dd}."]
    else:
        parts = [f"{d.year:04d}년", f"{m}월", f"{dd}일"]

    def read(fields: list[str]) -> Any:
        return value_after_anchor(_field("x", "A", "date"), "A " + " ".join(fields))

    assert read(parts) == iso
    # A part replaced by a field with an ASCII digit that is not that part refuses the date.
    i = data.draw(st.integers(1, 2))
    glue = data.draw(_GLUE)
    digits = parts[i][:-1]
    for bad in (glue + parts[i], digits + glue + parts[i][-1], parts[i] + glue):
        assert read([*parts[:i], bad, *parts[i + 1 :]]) is None, bad
    # A part replaced by a field with no digit: no partial date stands.
    assert read([*parts[:i], data.draw(_NOT_A_PART)]) is None
    # After the whole date, a field with an ASCII digit refuses it (could be its split part:
    # "2024. 3. 1 5." is not 1 March), unless parenthesised; a field with neither leaves it.
    tail = data.draw(st.text(_PROPERTY_JUNK.replace("(", ""), max_size=2)) + data.draw(
        st.sampled_from(string.digits)
    )
    assert read([*parts, tail]) is None, tail
    assert read([*parts, f"({tail})"]) == iso, tail
    assert read([*parts, data.draw(_NOT_A_PART)]) == iso
