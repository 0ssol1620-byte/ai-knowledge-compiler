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
    _CLOSE,
    _CUR_FIRST,
    _CURRENCY,
    _EN_SCALE,
    _EN_WORDS,
    _FOLD,
    _FOREIGN,
    _GLUED_LETTERS,
    _KO_CHARS,
    _LABEL_TEXT,
    _OPEN,
    _PAIR,
    _SCALE_LETTERS,
    _SCALE_WORDS,
    _SIGN,
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
        "5 :(",
        "(\uc6d0 5 ",
        "x\uc6d0) 5 ",
        "[x-\uc6d0",
        "aR$",
        "5 M ",
        "$ (",
        "5 (in % ",
        "(5 %",
        "usd",
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
        "gap-run",
        "open-label",
        "stray-label",
        "dirty-label",
        "dollar-spelling",
        "scale-letter",
        "currency-paren",
        "marked-group",
        "own-mark-group",
        "code-letters",
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
    # WO-D08-1G H2 and H4 changed these two pins: a scale word or a percent across a tab or a
    # line break is next to the number and was not applied, so the number is refused (was 5).
    assert canonical_values("number", "5\nmillion") == set()
    assert canonical_values("number", "5\t%") == set()
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


def _variants(c: str) -> list[str]:
    """``c`` and every character the reader's fold table turns into it (U+FF0D for "-")."""
    return [c, *(chr(k) for k, v in _FOLD.items() if v == c)]


def _currency_code(s: str) -> str | None:
    """The code the reader's table gives the spelling ``s`` after folding (codes in any case)."""
    folded = s.translate(_FOLD)
    return _CURRENCY.get(folded) or _CURRENCY.get(folded.upper())


# Every standalone prefix the reader knows, derived from its tables: each sign, the accounting
# "(", each currency spelling (codes also in lower and title case), with their fold variants.
_SIGN_PREFIXES = [v for s in _SIGN for v in _variants(s)]
_NEGATIVE_PREFIXES = [v for s, neg in _SIGN.items() if neg for v in _variants(s)]
_NEGATIVE_PREFIXES += _variants("(")
_CURRENCY_PREFIXES = sorted(
    {v for k in _CURRENCY for v in _variants(k)}
    | {k.lower() for k in _CURRENCY if k.isascii() and k.isalpha()}
    | {k.title() for k in _CURRENCY if k.isascii() and k.isalpha()}
)
# A sign, an accounting "(" or a currency, each a field of its own before a number.
_STANDALONE = [*_SIGN_PREFIXES, *_variants("("), *_CURRENCY_PREFIXES]


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


# Every currency spelling the reader knows, as written (codes in upper case): its own table.
_CURRENCY_SPELLINGS = frozenset(_CURRENCY)
# Words and labels that begin with a currency (amendment A.5).
_CURRENCY_WORDS = ["원가", "원래", "Euro", "usdx", "달러화", "엔화", "원)", "$)", "USD]"]


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
        # Lead note, round 11: a currency closing a bracket is a unit label only when the
        # bracket closes its own "(" or the innermost bracket still open before it ("(원)",
        # "[단위: 원]"); without one the consumed currency is refused.
        "A $) 5",
        "A USD] 5",
        "A 원) 5",
        "A 원] 5",
        "A €} 5",
        "A KRW) 5",
        "A 달러) 5",
        "A usd) 5",
        "A \uff04) 5",
        "A \uffe5) 5",
        "A x 원) 5",
        "A 가 $) 5",
        "A : 원) 5",
        "A [원) 5",
        "A (원] 5",
        "A [원} 5",
        "A {USD] 5",
        "A (단위: 원] 5",
        "A [단위: 원) 5",
        "A 원)) 5",
        "A (원) 원) 5",
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
        ("A (단위:원) 5", ("5", "num", None)),
        ("A (단위 : 원) 5", ("5", "num", None)),
        ("A \uff08원) 5", ("5", "num", None)),
        # Lead note, round 11: a closing bracket that matches the innermost open one keeps the
        # label text, whichever bracket it is.
        ("A [원] 5", ("5", "num", None)),
        ("A {USD} 5", ("5", "num", None)),
        ("A [USD] 5", ("5", "num", None)),
        ("A [단위: 원] 5", ("5", "num", None)),
        ("A {단위: 원} 5", ("5", "num", None)),
        ("A [단위:원] 5", ("5", "num", None)),
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
        st.sampled_from(_CURRENCY_WORDS),
        # One of those words with text after it.
        st.builds(
            lambda w, t: w + t,
            st.sampled_from(_CURRENCY_WORDS),
            st.text(_PROPERTY_JUNK + " ", max_size=3),
        ),
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
# at the next position, and a fixed set of continuations. Prefixes and classes come from the
# reader's own tables (_SIGN_PREFIXES, _CURRENCY_PREFIXES above), so a sign, currency or fold
# added there is enumerated here unasked.
_NEXT_CLASSES = sorted(
    set(_OPEN)  # opening punctuation and label separators
    | set(_SIGN)  # signs
    | _CUR_FIRST  # currency first characters, both cases
    | _CURRENCY_SPELLINGS  # whole currencies
    | {chr(k) for k, v in _FOLD.items() if v not in string.digits}  # folded variants
    | set("x가")  # an ASCII letter, a Hangul syllable
    | _KO_CHARS  # scale syllables
    | _CLOSE
)
_WHITESPACE_RUNS = [" ", "\t", "\n", "\r", "\x0b", "\x0c", "  ", " \t"]


def test_a_standalone_prefix_then_whitespace_never_yields_the_bare_number():
    """``A `` + P + S + N + rest: the result is None, except that a sign, spaces, a whole
    currency and then the digits read as the signed currency value ("- 원5", "- $ 5"). Never
    the bare, unsigned or currency-less number."""
    prefixes = [*_SIGN_PREFIXES, *_variants("("), *_CURRENCY_PREFIXES]
    # Meta-assertion: the prefixes enumerated are exactly as many as the reader's tables give,
    # counted here straight from _SIGN, the inverse of _FOLD and _CURRENCY (ASCII codes also in
    # lower and title case), so a prefix the derivation above drops fails here.
    unfold = {v: {chr(k) for k, w in _FOLD.items() if w == v} for v in _FOLD.values()}
    signs = set(_SIGN).union(*(unfold.get(s, set()) for s in _SIGN))
    parens = {"("} | unfold.get("(", set())
    codes = [k for k in _CURRENCY if k.isascii() and k.isalpha()]
    currencies = set(_CURRENCY).union(*(unfold.get(k, set()) for k in _CURRENCY))
    currencies |= {k.lower() for k in codes} | {k.title() for k in codes}
    assert len(prefixes) == len(set(prefixes))
    # The count also as a literal, so a mistake both derivations share fails, and a table change
    # is a visible edit here: 7 signs (- + △ ▲ and the folded - - +), 2 parens, 60 currencies
    # (14 ASCII codes in three cases, 8 symbols and words, 4 folded symbols, 6 "$" spellings).
    assert len(set(prefixes)) == len(signs) + len(parens) + len(currencies) == 7 + 2 + 60
    assert set(prefixes) == signs | parens | currencies
    wrong = []
    for p in prefixes:
        for s in _WHITESPACE_RUNS:
            for nxt in _NEXT_CLASSES:
                for rest in ["5", " 5", "가 5", ") 5", " :5"]:
                    text = f"A {p}{s}{nxt}{rest}"
                    want = None
                    joined = p in _SIGN_PREFIXES and not s.strip(" ")
                    if joined and _currency_code(nxt) and rest in ("5", " 5"):
                        sign = "-" if p in _NEGATIVE_PREFIXES else ""
                        want = (sign + "5", "num", _currency_code(nxt))
                    got = value_after_anchor(_field("x", "A"), text)
                    if got != want:
                        wrong.append((text, got, want))
    assert not wrong, (len(wrong), wrong[:20])


@pytest.mark.parametrize("p", [*_CURRENCY_PREFIXES, *_NEGATIVE_PREFIXES])
def test_every_standalone_prefix_is_read_with_the_number_across_spaces(p):
    """The enumeration above is not vacuous: each prefix, spaces, then digits, carries P."""
    paren = p in _variants("(")
    got = value_after_anchor(_field("x", "A"), f"A {p} 5" + (" )" if paren else ""))
    assert got is not None and got != ("5", "num", None), (p, got)
    code = _currency_code(p)
    assert got[2] == code and got[0] == ("-5" if p in _NEGATIVE_PREFIXES else "5"), (p, got)


def test_a_currency_closing_a_bracket_is_a_unit_label_only_when_it_closes_its_opener():
    """Lead note, round 11, closed by enumeration over the reader's tables: ``A`` + opener + a
    currency glued to a closing bracket + `` 5``. Only a bracket that closes the innermost one
    still open before it ("(원)", "(단위: 원)", "[원]", "{단위: USD}"), with nothing but
    label text between that opener and the currency (WO-D08-1G item 1), makes a unit label,
    after which the bare 5 is read; any other shape is refused, never the currency-less 5,
    wherever the currency stands: glued after a word too ("(단위:원]" is refused since
    WO-D08-1G, "(단위 [x] 원)" too: "[" and "]" are not label text). A "(" glued to a further
    bracket ("([원]") is an accounting paren consumed with no digit after it, refused like
    "([5])"."""
    openers = ["", "x ", ": ", "가 ", "(단위: ", "(단위 : ", "(단위:", "(a) ", "( x) "]
    openers += [o + "(" for o in ("", "x ")] + [v for o in _PAIR.values() for v in _variants(o)]
    openers += ["[단위: ", "{단위: ", "([", "[(", "{[", "(단위 [x] ", "[단위 (x) "]
    wrong = []
    for opener in openers:
        folded = opener.translate(_FOLD)
        # The brackets the opener leaves open, innermost last, each with what follows it.
        stack: list[tuple[str, int]] = []
        lead = folded.split(" ")[-1]
        paren_consumed = lead[:1] == "(" and len(lead) > 1 and not lead[1].isalpha()
        for at, c in enumerate(folded):
            if c in _PAIR.values():
                stack.append((c, at))
            elif c in _PAIR and stack[-1:] and stack[-1][0] == _PAIR[c]:
                stack.pop()
        inner, at = stack[-1] if stack else ("", len(folded))
        between = folded[at + 1 :]
        label_text = all(c in " :," or (c.isascii() and c.isalpha()) or _hangul(c) for c in between)
        for cur in _CURRENCY_PREFIXES:
            for close in sorted(set(_CLOSE) & set(_PAIR)):
                text = f"A {opener}{cur}{close} 5"
                label = not paren_consumed and inner == _PAIR[close] and label_text
                want = ("5", "num", None) if label else None
                got = value_after_anchor(_field("x", "A"), text)
                if got != want:
                    wrong.append((text, got, want))
    assert not wrong, (len(wrong), wrong[:20])


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


def _hangul(c: str) -> bool:
    return "\uac00" <= c <= "\ud7a3"


def _mark(text: str, k: int) -> bool:
    """Test side, from the definition: ``text[k]`` starts a percent or a currency spelling of
    the reader's table (codes in any case) that no ASCII digit follows across spaces."""
    if text[k] == "%":
        return True
    for key in sorted(_CURRENCY, key=len, reverse=True):
        head = text[k : k + len(key)]
        code = key.isascii() and key.isalpha()
        if (head.isascii() and head.upper() == key) if code else head == key:
            return text[k + len(key) :].lstrip(" ")[:1] not in tuple(string.digits)
    return False


_OWN = re.compile(
    r"[0-9] *[조억만천백십]* *(?:(?i:thousand|million|billion|trillion|bn|k|m|b) *)?\Z"
)


_SCALE_WORD = re.compile(
    r"(?i:thousand|million|billion|trillion|bn|mn|mm|tn|lakh|lac|crore|hundred)s?\Z"
)
_KO_RUN = re.compile(r"[천백십]?[만억조]?")


def _scale_word_at(text: str, k: int) -> bool:
    """Test side, from WO-D08-1G H1/H2: does a scale expression of more than one letter begin
    at ``k``: a word of the scale tables (any case, plural "s"), or a Korean unit run that
    ends its word or takes a currency ("억", "백만원"; not "조사")."""
    if text[k] in _KO_SCALE:
        u = k + len(_KO_RUN.match(text, k).group())
        rest = text[u:]
        return not rest[:1] or not _hangul(rest[0]) or rest.startswith(("원", "달러", "엔"))
    word = re.match(r"[A-Za-z]*", text[k:]).group()
    return bool(_SCALE_WORD.match(word))


def _spelling_at(text: str, k: int) -> int:
    """Test side: the length of the currency spelling of the reader's table at ``k`` (codes in
    any case, other spellings as written), or 0."""
    for key in sorted(_CURRENCY, key=len, reverse=True):
        head = text[k : k + len(key)]
        code = key.isascii() and key.isalpha()
        if (head.isascii() and head.upper() == key) if code else head == key:
            return len(key)
    return 0


def _next_number_takes_the_sign(rest: str) -> bool:
    """Test side: across ASCII spaces, an optional currency and an optional "(", a digit."""
    j = len(rest) - len(rest.lstrip(" "))
    if _spelling_at(rest, j):
        j += _spelling_at(rest, j)
        j += len(rest[j:]) - len(rest[j:].lstrip(" "))
    if rest[j : j + 1] == "(":
        j += 1 + len(rest[j + 1 :]) - len(rest[j + 1 :].lstrip(" "))
    return rest[j : j + 1] in tuple(string.digits)


def _word_start(text: str, k: int) -> bool:
    c, before = text[k], text[k - 1 : k]
    if c in string.ascii_letters:
        return not before or before not in string.ascii_letters
    return c in _KO_SCALE and not (before and _hangul(before))


def _group_is_free(text: str, p: int) -> bool | None:
    """The group opened at ``text[p]`` (to its matching closer, or the end): True when it holds
    a percent or currency that is no number's own, or a scale expression no digit stands
    before; False when it holds only marks and scales of numbers; None when it holds neither."""
    depth: list[str] = []
    holds = False
    for k in range(p, len(text)):
        c = text[k]
        if c in "([{":
            depth.append(c)
        elif c in _PAIR and depth and depth[-1] == _PAIR[c]:
            depth.pop()
            if not depth:
                break
        elif _mark(text, k):
            if not _OWN.search(text[:k]):
                return True
            holds = True
        elif _spelling_at(text, k):
            holds = True  # a currency with a digit after it: another number's prefix
        elif _word_start(text, k) and _scale_word_at(text, k):
            if text[:k].rstrip(" ")[-1:] not in tuple(string.digits):
                return True
            holds = True
    return False if holds else None


def _says_unit(after: str) -> bool:
    """Test-side oracle for the Korean-group property, from WO-D08-1G item 2 and H1-H7: does
    what follows a read number with its own scale (``after``, which begins with " (") hold a
    percent, currency or scale that the number did not apply. A bracket group there that holds
    one that is no number's own refuses; one that holds only numbers' own leaves the number
    (it has its own scale). Past a group that holds neither, the first mark refuses, a currency
    with a digit after it or a digit ends the search, the first sign refuses unless a number
    follows it, and the first word refuses when it is a scale word or its field holds a symbol
    currency. After the "(" a single letter is never a scale."""
    after = after.translate(_FOLD)
    assert after.startswith(" (")
    for k, c in enumerate(after):
        free = _group_is_free(after, k) if c in "([{" else None
        if free is not None:
            return free
        if _mark(after, k):
            return True
        if _spelling_at(after, k):
            return False
        if c in string.digits:
            return False
        if c in _SIGN and not _next_number_takes_the_sign(after[k + 1 :]):
            return True  # a sign that no number takes; the next number's is punctuation
        if c in string.ascii_letters or _hangul(c):
            if _scale_word_at(after, k):
                return True
            field = re.match(r"[^ \t\n\r]*", after[k:]).group()
            return any(s in field for s in "$₩€£¥")
    return False


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
    # A parenthesised field is never joined, whatever it holds. WO-D08-1G item 2: one that
    # holds a percent or currency (not the start or the suffix of a further number) refuses
    # the value.
    inside = data.draw(st.text(_PROPERTY_JUNK, max_size=4))
    want = None if _says_unit(f" ({inside}") else (str(value), "num", None)
    assert read(f"({inside}") == want, inside
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


# --- WO-D08-1F (lead decisions after the fifteenth review of WO-D08-1).
# Item 3: a sign inside a unit label refuses; the reader does not guess what the sign applies to.
@pytest.mark.parametrize(
    "candidate",
    [
        "A [-원] 5",
        "A {-USD} 5",
        "A [△원] 5",
        "A (단위: -원) 5",
        "A [단위: -원] 5",
        # The same class: every sign and fold, a sign anywhere inside the label.
        "A [+$] 5",
        "A {▲원} 5",
        "A [\uff0d원] 5",
        "A [\u2212원] 5",
        "A (단위: △원) 5",
        "A [x -원] 5",
        "A [-단위: 원] 5",
        "A {단위 - USD} 5",
    ],
)
def test_a_sign_inside_a_unit_label_refuses(candidate):
    assert value_after_anchor(_field("x", "A"), candidate) is None
    assert score_critical_fields([_field("5", "A")], candidate).exact == 0


def test_a_unit_label_with_a_sign_refuses_and_without_one_reads_plain():
    """Item 3, closed by enumeration over the reader's tables: every opening bracket (with its
    folds), every sign (with its folds), every currency spelling, the sign glued to the
    currency, standing before it in the label, or glued to the label's first word. With the
    sign: None. The same label without it: the plain 5 (its unit label is text)."""
    close_of = {o: c for c, o in _PAIR.items()}
    wrong = []
    for o in [v for b in _PAIR.values() for v in _variants(b)]:
        close = close_of[o.translate(_FOLD)]
        for cur in _CURRENCY_PREFIXES:
            for shape in ("{o}{s}{c}{z}", "{o}단위: {s}{c}{z}", "{o}{s}단위: {c}{z}"):
                plain = shape.format(o=o, s="", c=cur, z=close)
                if value_after_anchor(_field("x", "A"), f"A {plain} 5") != ("5", "num", None):
                    wrong.append((plain, "unsigned label not read"))
                for s in _SIGN_PREFIXES:
                    text = "A " + shape.format(o=o, s=s, c=cur, z=close) + " 5"
                    got = value_after_anchor(_field("x", "A"), text)
                    if got is not None:
                        wrong.append((text, got))
    assert not wrong, (len(wrong), wrong[:20])


# Item 4: a percent or currency set apart from the number by a label separator or opening
# punctuation refuses the number; it is never read plain.
@pytest.mark.parametrize(
    "candidate",
    [
        "A 5 :%",
        "A 5 |%",
        "A 5 :원",
        "A 5 |원",
        "A 5 (%)",
        # The same class: any whitespace, any separator or opening run, a token that already
        # took a mark, a scaled or accounting number, a code in any case.
        "A 5 =%",
        "A 5 [%]",
        "A 5 {원}",
        'A 5 "원"',
        "A 5 ( %)",
        "A 5 : 원",
        "A 5:원",
        "A 5|원",
        "A 5\t:%",
        "A 5\n(%)",
        "A 5 (USD)",
        "A 5 (usd)",
        "A 5 ($)",
        "A 5% (%)",
        "A 5원 (원)",
        "A 12억 (원)",
        "A (5) :%",
    ],
)
def test_a_percent_or_currency_set_apart_by_a_separator_refuses(candidate):
    assert value_after_anchor(_field("x", "A"), candidate) is None
    assert score_critical_fields([_field("5", "A")], candidate).exact == 0


@pytest.mark.parametrize(
    ("candidate", "want"),
    [
        # Kept as today (item 4): a percent or currency after ASCII spaces is the grammar's own
        # spaced suffix. After other whitespace alone it is not joined, and since WO-D08-1G H4
        # it refuses the number ("A 5\t%" was plain 5, now None: pinned with the H4 inputs).
        ("A 5 %", ("5", "pct", None)),
        ("A 5 원", ("5", "num", "KRW")),
        # A currency that begins a further number is that number's prefix, not a mark.
        ("A 5 ($3)", ("5", "num", None)),
        ("A 5\n($3)", ("5", "num", None)),
        ("A 5 :$3", ("5", "num", None)),
        ("A 5 (원 3)", ("5", "num", None)),
        ("A 12억 (3456만)", ("1200000000", "num", None)),
    ],
)
def test_a_percent_or_currency_the_grammar_joins_or_that_starts_a_number(candidate, want):
    assert value_after_anchor(_field("x", "A"), candidate) == want


def test_every_separated_percent_or_currency_refuses_the_number():
    """Item 4, closed by enumeration over the reader's tables: a number (plain, percent,
    currency, accounting, scaled), any ASCII whitespace or none, one label separator or opening
    character (or two), then a percent or any currency spelling, then nothing, a space and a
    word, or a closer: None. With a digit after the currency it begins the next number, and the
    first number stands (whitespace before the run, which a glued separator would refuse)."""
    tokens = {
        "5": ("5", "num", None),
        "5%": ("5", "pct", None),
        "$5": ("5", "num", "USD"),
        "(5)": ("-5", "num", None),
        "12억": ("1200000000", "num", None),
    }
    runs = [*sorted(_OPEN), ":(", "| ["]
    wrong = []
    for number, value in tokens.items():
        for ws in ["", " ", "\t", "\n", " \t"]:
            for run in runs:
                for mark in ["%", *_CURRENCY_PREFIXES]:
                    for tail in ["", " x", ")"]:
                        text = f"A {number}{ws}{run}{mark}{tail}"
                        got = value_after_anchor(_field("x", "A"), text)
                        if got is not None:
                            wrong.append((text, got))
                    if ws and mark != "%" and number != "12억":
                        text = f"A {number}{ws}{run}{mark}3"
                        got = value_after_anchor(_field("x", "A"), text)
                        if got != value:
                            wrong.append((text, got, value))
    assert not wrong, (len(wrong), wrong[:20])


# Item 5: more currencies, in the tables. Codes read in any case; the "$" spellings as written.
@pytest.mark.parametrize(
    ("candidate", "want"),
    [
        ("A CNY 5", ("5", "num", "CNY")),
        ("A RMB 5", ("5", "num", "CNY")),
        ("A rmb 5", ("5", "num", "CNY")),
        ("A 5 HKD", ("5", "num", "HKD")),
        ("A TWD 5", ("5", "num", "TWD")),
        ("A SGD 5", ("5", "num", "SGD")),
        ("A AUD 5", ("5", "num", "AUD")),
        ("A CAD 5", ("5", "num", "CAD")),
        ("A 5CHF", ("5", "num", "CHF")),
        ("A INR 5", ("5", "num", "INR")),
        ("A US$5", ("5", "num", "USD")),
        ("A HK$ 5", ("5", "num", "HKD")),
        ("A NT$5", ("5", "num", "TWD")),
        ("A S$5", ("5", "num", "SGD")),
        ("A A$5", ("5", "num", "AUD")),
        ("A C$5", ("5", "num", "CAD")),
        ("A - US$5", ("-5", "num", "USD")),
        ("A 5 US$", ("5", "num", "USD")),
        # Read plain before the table grew: the currency was dropped.
        ("A US$ 5", ("5", "num", "USD")),
        ("A 5 CHF", ("5", "num", "CHF")),
        # Kept as today: EURO is not a code; EUR glued to a letter is a word, which is text.
        ("A EURO 5", ("5", "num", None)),
        ("A Euro 5", ("5", "num", None)),
        ("A audited 5", ("5", "num", None)),
    ],
)
def test_more_currencies_are_read_from_the_table(candidate, want):
    assert value_after_anchor(_field("x", "A"), candidate) == want
    assert score_critical_fields([_field("5", "A")], candidate).exact == (
        want == ("5", "num", None)
    )


@pytest.mark.parametrize(
    ("value", "want"),
    [("US$5", ("5", "num", "USD")), ("RMB 5", ("5", "num", "CNY")), ("5 CHF", ("5", "num", "CHF"))],
)
def test_gold_reads_the_new_currencies(value, want):
    assert gold_value(_field(value)) == want
    assert score_critical_fields([_field(value, "A")], "A 5").exact == 0


# Item 6: pinned as they read today, no change.
@pytest.mark.parametrize(
    ("candidate", "want"),
    [
        ("A [원]] 5", ("5", "num", None)),
        ("A [[원]] 5", ("5", "num", None)),
        ("A {[원]} 5", ("5", "num", None)),
        # "(" is a prefix the reader consumes (A.5), "[" and "{" are not: so a space inside
        # "[ 원]" leaves a label, inside "( 원)" a standalone paren then a non-digit.
        ("A [ 원] 5", ("5", "num", None)),
        ("A ( 원) 5", None),
        # Full-width brackets are not folded: unlisted characters next to the number refuse it.
        ("A \uff3b원\uff3d 5", None),
        ("A \uff5bUSD\uff5d 5", None),
    ],
)
def test_bracket_shapes_pinned_after_round_fifteen(candidate, want):
    assert value_after_anchor(_field("x", "A"), candidate) == want


# --- WO-D08-1G (lead decisions after the review of WO-D08-1F): the rules name what is allowed.
# Item 1: a bracket group that ends in a currency glued to its matching closer is a unit label
# (text) only if everything between its opener and the currency is label text: ASCII letters,
# Hangul syllables, an ASCII space, ":" and ",". Otherwise the number after it is refused,
# wherever the currency stands (at the start of a token or glued after a word).
@pytest.mark.parametrize(
    "candidate",
    [
        "A (단위:-원) 5",
        "A [금액-원] 5",
        "A [\u2013원] 5",
        "A [±원] 5",
        "A [~원] 5",
        "A [▼원] 5",
        # WO-D08-1F item 3's inputs stay refused under the allow-list that replaces its rule.
        "A [-원] 5",
        "A {-USD} 5",
        "A [△원] 5",
        "A (단위: -원) 5",
        "A [단위: -원] 5",
        # Decided by the rule: "[" and "]" inside the label are not label text, so the inner
        # "[x]" makes "(단위 [x] 원)" not a label (it was one under amendment A.6's stack).
        "A (단위 [x] 원) 5",
        "A [단위 (x) 원] 5",
        # The same class: other dashes and symbols, a digit, other punctuation, whitespace that
        # is not an ASCII space, a closer that does not match, a currency glued after a word.
        "A [\u2014원] 5",
        "A [\u2010원] 5",
        "A [\ufe63원] 5",
        "A [▽원] 5",
        "A [단위:△원] 5",
        "A (x-원) 5",
        "A [금액-USD] 5",
        "A [단위.원] 5",
        "A [단위\t원] 5",
        "A (x\u00a0원) 5",
        "A (단위1원) 5",
        "A (단위:원] 5",
        "A x원) 5",
        # Two rules meet on these: a "(" followed by a character that is not a letter is a
        # consumed accounting paren (amendments A.4, A.5) although " ", ":" and "," are label
        # text; the stricter reading wins.
        "A ( 원) 5",
        "A (:원) 5",
        "A (,원) 5",
    ],
)
def test_a_unit_label_holds_only_label_text(candidate):
    assert value_after_anchor(_field("x", "A"), candidate) is None
    assert score_critical_fields([_field("5", "A")], candidate).exact == 0


@pytest.mark.parametrize(
    "candidate",
    [
        "A (원) 5",
        "A (단위: 원) 5",
        "A [단위: 원] 5",
        "A {USD} 5",
        "A [단위, 원] 5",
        "A [금액 USD] 5",
        "A (단위:원) 5",
        "A 매출(억원) 5",
        "A [ 원] 5",
        "A [단위: HK$] 5",
    ],
)
def test_a_unit_label_of_label_text_is_text(candidate):
    assert value_after_anchor(_field("x", "A"), candidate) == ("5", "num", None)
    assert score_critical_fields([_field("5", "A")], candidate).exact == 1


_LABEL_ALLOWED = ["x", "X", "가", " ", ":", ","]
_LABEL_REFUSED = sorted(
    set("-+△▲\u2212\uff0d\uff0b\u2013\u2014\u2010\ufe63±~▼▽")  # signs, dashes
    | (set(string.punctuation) - set(":,"))  # every other ASCII punctuation
    | set("1\t\n\u00a0\u200b\u3131\u4e2d\u00b7")  # digit, whitespace, jamo, CJK, Latin-1
)


def _label_oracle(o: str, x: str, cur: str, close: str) -> bool:
    """Test side, from item 1: is ``o + x + cur + close`` (``x`` placed between the opener
    and the currency) a unit label, so the 5 after it is read plain."""
    label = (o + x).translate(_FOLD)
    stack: list[tuple[str, int]] = []
    for at, c in enumerate(label):
        if c in "([{":
            stack.append((c, at))
        elif c in _PAIR and stack and stack[-1][0] == _PAIR[c]:
            stack.pop()
    if not stack or stack[-1][0] != _PAIR[close]:
        return False
    between = label[stack[-1][1] + 1 :]
    if not all(c in " :," or (c.isascii() and c.isalpha()) or _hangul(c) for c in between):
        return False
    # A "(" right before a character that is not a letter is consumed as an accounting paren.
    if label[:1] == "(" and label[1:2] and not label[1].isalpha():
        return False
    if cur.translate(_FOLD) == "%":  # WO-D08-1G H8: a percent label, by the same allow-list
        return True
    # Item 4: letters glued before a "$" must spell a currency of the table. WO-D08-1G H7: a
    # symbol currency (with the letters of its spelling) must start its field, after an ASCII
    # space or an opener ("(가$)", "(단위,$)", "(가A$)" are refused).
    folded_cur = cur.translate(_FOLD)
    symbol = next((i for i, c in enumerate(folded_cur) if not c.isalpha()), None)
    if symbol is not None:
        head = label + folded_cur[:symbol]
        letters = len(head) - len(head.rstrip(string.ascii_letters))
        if letters and head[-letters:] + folded_cur[symbol] not in _CURRENCY:
            return False
        if head[: len(head) - letters][-1:] not in (" ", *_OPEN):
            return False
    return True


def test_every_label_character_class_in_every_bracket_pair():
    """Item 1, closed by enumeration over the module's tables: every bracket pair (openers with
    their folds), every currency spelling, one representative of every character class between
    the opener and the currency, glued to the currency or after a word. Label text: the plain 5
    is read. Anything else: None, never the plain 5."""
    # The allowed classes are exactly the module's, and no refused representative is one.
    assert frozenset(string.ascii_letters + " :,") == _LABEL_TEXT
    assert not set(_LABEL_REFUSED) & _LABEL_TEXT and not any(map(_hangul, _LABEL_REFUSED))
    close_of = {o: c for c, o in _PAIR.items()}
    wrong = []
    checked = 0
    for o in [v for b in _PAIR.values() for v in _variants(b)]:
        close = close_of[o.translate(_FOLD)]
        for cur in [*_CURRENCY_PREFIXES, *_variants("%")]:
            for x in [*_LABEL_ALLOWED, *_LABEL_REFUSED]:
                for between in (f"단위{x}", x):
                    if between in string.digits:
                        continue  # "[1원]" is the number 1원 itself, read as such
                    want = ("5", "num", None) if _label_oracle(o, between, cur, close) else None
                    text = f"A {o}{between}{cur}{close} 5"
                    got = value_after_anchor(_field("x", "A"), text)
                    checked += 1
                    if got != want:
                        wrong.append((text, got, want))
    assert checked > 10_000
    assert not wrong, (len(wrong), wrong[:20])


# Item 2: after a number, a percent or currency it did not take refuses it: past ASCII
# whitespace and any run of punctuation or symbols, or past spaces alone; and a bracket group
# opened right after it that holds one anywhere.
@pytest.mark.parametrize(
    "candidate",
    [
        "A 5 ;%",
        "A 5 /%",
        "A 5 -%",
        "A 5 <%",
        "A 5 :- %",
        "A 5 :-원",
        "A 5,원",
        "A 5.원",
        "A 5 (단위: %)",
        "A 5 (in %)",
        "A 5 (USD thousands)",
        # The same class: a run of several separators, a group behind another separator, other
        # symbols, a character outside ASCII, a scale label that holds no digit.
        "A 5 :(in %)",
        "A 5 - (단위: %)",
        "A 5 *%",
        "A 5 ~ %",
        "A 5 \u00b7원",
        "A 5 \u200b%",
        "A 5 (단위: 백만원)",
        "A 5\n(단위: %)",
        # Past spaces alone or nothing, a mark the grammar did not take is not the number's
        # own: after an accounting paren, after a currency the number already took.
        "A (5) %",
        "A (5)원",
        "A 5원 %",
        "A 5 USD 원",
    ],
)
def test_a_percent_or_currency_the_number_did_not_take_refuses_it(candidate):
    assert value_after_anchor(_field("x", "A"), candidate) is None
    assert score_critical_fields([_field("5", "A")], candidate).exact == 0


@pytest.mark.parametrize(
    ("candidate", "want"),
    [
        # Kept: a currency followed by a digit is the next number's prefix; the grammar's own
        # spaced and glued percent and currency.
        ("A 5 ($3)", ("5", "num", None)),
        ("A 5 %", ("5", "pct", None)),
        ("A 5 원", ("5", "num", "KRW")),
        ("A 5%", ("5", "pct", None)),
        ("A 5원", ("5", "num", "KRW")),
        # "A 5\t%" was kept here (plain 5); WO-D08-1G H4 refuses it (pinned with H4).
        # Kept (an earlier named regression meets item 2): a mark inside the group that is the
        # suffix of a number there is that number's own, like a prefix with a digit after it.
        ("A 12억원 (전년 10억원)", ("1200000000", "num", "KRW")),
        ("A 12억원 (전년 10 억 원)", ("1200000000", "num", "KRW")),
        ("A 5 (12%)", ("5", "num", None)),
        ("A 5 (10 USD)", ("5", "num", None)),
        ("A 5 (3 million USD)", ("5", "num", None)),
    ],
)
def test_a_percent_or_currency_that_belongs_to_a_number_is_kept(candidate, want):
    assert value_after_anchor(_field("x", "A"), candidate) == want


def _punctuation_and_symbols() -> dict[str, list[str]]:
    """Every ASCII and Latin-1 character in a punctuation or symbol category, by category."""
    by_cat: dict[str, list[str]] = {}
    for cp in range(0x21, 0x100):
        c = chr(cp)
        if unicodedata.category(c)[0] in "PS":
            by_cat.setdefault(unicodedata.category(c), []).append(c)
    return by_cat


def test_every_punctuation_or_symbol_before_a_percent_or_currency_refuses_the_number():
    """Item 2, closed by enumeration: every ASCII and Latin-1 punctuation or symbol character
    (every general category P* and S* present there), with and without ASCII spaces around it,
    between a number and a percent or any currency spelling of the table: None. With a digit
    after the currency it begins the next number, and the number before it stands."""
    by_cat = _punctuation_and_symbols()
    assert set(by_cat) == {"Pc", "Pd", "Ps", "Pe", "Pi", "Pf", "Po", "Sm", "Sc", "Sk", "So"}
    tokens = {
        "5": ("5", "num", None),
        "(5)": ("-5", "num", None),
        "12억": ("1200000000", "num", None),
    }
    wrong = []
    for chars in by_cat.values():
        # A percent is not a separator: the grammar takes it, and a currency after it ("5%$").
        for c in (c for c in chars if c != "%"):
            for number, value in tokens.items():
                for a, b in [("", ""), (" ", ""), (" ", " "), ("", " ")]:
                    for mark in ["%", *_CURRENCY_PREFIXES]:
                        text = f"A {number}{a}{c}{b}{mark}"
                        got = value_after_anchor(_field("x", "A"), text)
                        if got is not None:
                            wrong.append((text, got))
                if c.isascii() and c not in "%$" and number != "12억":
                    for mark in _CURRENCY_PREFIXES:
                        text = f"A {number} {c}{mark}3"
                        got = value_after_anchor(_field("x", "A"), text)
                        if got != value:
                            wrong.append((text, got, value))
    assert not wrong, (len(wrong), wrong[:20])


# Item 3: a scale word the grammar does not read refuses the number before it.
@pytest.mark.parametrize(
    "candidate",
    [
        "A 5 mn",
        "A 5 M",
        "A 5 K",
        "A 12 lakh",
        "A INR 12 lakh",
        "A 3 hundred",
        # The same class: every word of the table, plural and other cases, after a currency,
        # an accounting paren or a percent, past a tab, before sentence punctuation.
        "A 5 MM",
        "A 5 tn",
        "A 5 lac",
        "A 5 crore",
        "A 5 B",
        "A 5 T",
        "A 5 lakhs",
        "A 5 Crores",
        "A $5 M",
        "A (5) bn",
        "A 5% Mn",
        "A 5\tM",
        "A 5\tbn",
        "A 5 M.",
    ],
)
def test_a_scale_word_the_grammar_does_not_read_refuses_the_number(candidate):
    assert value_after_anchor(_field("x", "A"), candidate) is None
    assert score_critical_fields([_field("5", "A")], candidate).exact == 0


@pytest.mark.parametrize(
    ("candidate", "want"),
    [
        # Lower-case "m" is not in the table: a unit, read plain.
        ("A width 5 m", ("5", "num", None)),
        ("A 5 k", ("5", "num", None)),
        # Words the grammar reads are unchanged ("bn" is in the table for where it does not).
        ("A 5 bn", ("5000000000", "num", None)),
        ("A 5 BN", ("5000000000", "num", None)),
        ("A 5M", ("5000000", "num", None)),
        ("A 5 million", ("5000000", "num", None)),
        ("A 5 thousand", ("5000", "num", None)),
        # A single letter that is a label, not a word standing alone, and a longer word.
        ("A 200  B: 100", ("200", "num", None)),
        ("A 5 Mio", ("5", "num", None)),
    ],
)
def test_a_scale_word_the_grammar_reads_or_that_is_no_scale_word_is_kept(candidate, want):
    assert value_after_anchor(_field("x", "A"), candidate) == want


def test_every_scale_word_of_the_table_refuses_the_number_unless_the_grammar_reads_it():
    """Item 3, closed by enumeration over the module's tables: every scale word (in three
    cases and plural) and every single letter, after numbers with and without a currency,
    paren or percent, glued or past any ASCII whitespace, with what ends a word after it. The
    grammar's own scales (spaced "bn", glued "M" "K" "B") read the scaled value; else None."""
    # The table is pinned as a literal, so a change to it is a visible edit here.
    assert {"mn", "mm", "bn", "tn", "lakh", "lac", "crore", "hundred"} == _SCALE_WORDS
    assert set("MKBT") == _SCALE_LETTERS
    words = {v for w in _SCALE_WORDS for v in (w, w.upper(), w.title(), w + "s")}
    numbers = {
        "5": None,
        "$5": "USD",
        "INR 5": "INR",
        "(5)": None,
        "5%": None,
    }
    wrong = []
    for number, cur in numbers.items():
        for ws in ["", " ", "  ", "\t", "\n"]:
            for word in sorted(words | _SCALE_LETTERS):
                for end in ["", " x", ".", ","]:
                    text = f"A {number}{ws}{word}{end}"
                    plain = number not in ("(5)", "5%")
                    spaced = plain and ws.strip(" ") == "" and word.lower() == "bn"
                    glued = plain and ws == "" and word in ("M", "K", "B")
                    want = None
                    if spaced or glued:
                        scaled = 5 * _EN_SCALE[word.lower()]
                        want = (str(scaled), "num", cur)
                    got = value_after_anchor(_field("x", "A"), text)
                    if got != want:
                        wrong.append((text, got, want))
    assert not wrong, (len(wrong), wrong[:20])


# Item 4: letters glued before a "$" that do not spell a currency of the table refuse.
@pytest.mark.parametrize(
    "candidate",
    [
        "A R$ 5",
        "A NZ$ 5",
        "A CA$ 5",
        "A AU$ 5",
        "A MX$ 5",
        "A Z$ 5",
        "A R$5",
        "A us$ 5",
        "A xUS$ 5",
        "A [NZ$] 5",
        "A NZ$ (5)",
    ],
)
def test_an_unlisted_dollar_spelling_refuses_the_number(candidate):
    assert value_after_anchor(_field("x", "A"), candidate) is None
    assert score_critical_fields([_field("5", "A")], candidate).exact == 0


def test_every_one_to_three_letter_dollar_spelling_reads_only_from_the_table():
    """Item 4, closed by enumeration: every spelling of one or two ASCII letters (both cases)
    and of three upper-case letters, glued before "$", then the number spaced or glued: the
    currency of the table when the spelling is in it, else None, never a currency-less 5."""
    upper, letters = string.ascii_uppercase, string.ascii_letters
    spellings = [*letters, *(a + b for a in letters for b in letters)]
    spellings += [a + b + c for a in upper for b in upper for c in upper]
    wrong = []
    for sp in spellings:
        for gap in (" ", ""):
            text = f"A {sp}${gap}5"
            code = _CURRENCY.get(sp + "$")
            want = ("5", "num", code) if code else None
            got = value_after_anchor(_field("x", "A"), text)
            if got != want:
                wrong.append((text, got, want))
    assert not wrong, (len(wrong), wrong[:20])


# Item 5: a currency before accounting parentheses is the negative amount in that currency.
@pytest.mark.parametrize(
    ("candidate", "want"),
    [
        ("A $ (700)", ("-700", "num", "USD")),
        ("A $(700)", ("-700", "num", "USD")),
        ("A ₩ (700)", ("-700", "num", "KRW")),
        ("A USD (700)", ("-700", "num", "USD")),
        # Decided by the existing accounting-paren rule: spaces inside the parens are read
        # ("( 5 )" is -5), an open paren with no close is refused.
        ("A $ ( 700 )", ("-700", "num", "USD")),
        ("A $ (700", None),
        # Unchanged: the paren first, and whitespace other than spaces, a sign before the
        # currency or inside the paren, a second paren, a different currency after it.
        ("A ($ 700)", ("-700", "num", "USD")),
        ("A $\t(700)", None),
        ("A - $ (700)", None),
        ("A $ (-700)", None),
        ("A $ ((700))", None),
        ("A $ (700원)", None),
    ],
)
def test_a_currency_before_accounting_parentheses_reads_negative(candidate, want):
    assert value_after_anchor(_field("x", "A"), candidate) == want


@pytest.mark.parametrize(
    ("value", "want"),
    [
        ("$ (700)", ("-700", "num", "USD")),
        ("$(700)", ("-700", "num", "USD")),
        ("₩ (700)", ("-700", "num", "KRW")),
        ("USD (700)", ("-700", "num", "USD")),
        ("$ ( 700 )", ("-700", "num", "USD")),
    ],
)
def test_gold_reads_a_currency_before_accounting_parentheses(value, want):
    assert gold_value(_field(value)) == want
    assert score_critical_fields([_field(value, "A")], f"A {value}").exact == 1
    assert score_critical_fields([_field(value, "A")], "A 700").exact == 0


def test_gold_refuses_an_unclosed_accounting_paren_after_a_currency():
    assert _gold_refused("$ (700")


def test_every_currency_before_accounting_parentheses_reads_negative():
    """Item 5, closed by enumeration over the currency table: every spelling, glued or spaced
    before the paren, with and without spaces inside it: the negative amount in that currency.
    Without the closing paren: None."""
    wrong = []
    for p in _CURRENCY_PREFIXES:
        for gap in ("", " ", "  "):
            for paren in ("(700)", "( 700 )", "(1,234.5)"):
                text = f"A {p}{gap}{paren}"
                digits = paren.strip("() ").replace(",", "")
                want = ("-" + digits, "num", _currency_code(p))
                got = value_after_anchor(_field("x", "A"), text)
                if got != want:
                    wrong.append((text, got, want))
            text = f"A {p}{gap}(700"
            if value_after_anchor(_field("x", "A"), text) is not None:
                wrong.append((text, "unclosed read"))
    assert not wrong, (len(wrong), wrong[:20])


# Item 6: correct values that the rules above refuse, by design. Each would score a right
# answer as wrong; each is kept refused because what follows the number, or the label before
# it, says something the reader does not interpret ("원가" begins with the currency 원).
@pytest.mark.parametrize(
    "candidate",
    [
        "A 5 (원가)",
        "A 5 (audited)",
        "A $5 (USD)",
        "A 5 Audi",
        "A 5 cadets",
        "A 5 AUDUSD",
        # Found while implementing item 2, the same design: sentence punctuation, then a word
        # that begins with a currency ("원가" cost, "원화" the won).
        "A 5, 원가 3",
        "A 5%. 원화 강세",
        "A 5억, 원가 3억",
        # WO-D08-1G H4: a currency word on the next line ("원가" cost) is a mark next to the
        # number across a line break.
        "A 5\n원가",
        # WO-D08-1G H2: a single capital letter in a bracket group is not a scale, but a
        # Korean word that begins with a unit and takes a currency is ("(만원대)").
        "A 5 (만원대)",
    ],
)
def test_correct_values_refused_by_design(candidate):
    """Over-refusals by design (WO-D08-1G item 6), not defects: pinned so a change is seen."""
    assert value_after_anchor(_field("x", "A"), candidate) is None


# --- WO-D08-1G lead amendment (H1-H9). The reader never returns a number that stands next to
# a scale, sign, percent or currency expression it did not apply: glued, across ASCII
# whitespace of any kind, or across a punctuation run or a bracket group opened right after it.
_USD700 = ("-700", "num", "USD")
_PLAIN5 = ("5", "num", None)


@pytest.mark.parametrize(
    ("candidate", "want"),
    [
        # H1: a scale after a token closed by an accounting paren, with or without a currency.
        ("A $ (700) million", None),
        ("A net loss of $(700) million", None),
        ("A $(700) billion", None),
        ("A USD (700) thousand", None),
        ("A $ (1.2) billion", None),
        ("A $ (700) Million", None),
        ("A $ (700) millions", None),
        ("A $ (700)\nmillion", None),
        ("A (700) million", None),
        ("A ($ 700) million", None),
        ("A $ (700) k", None),
        ("A (700)k", None),
        ("A (700)억", None),
        ("A (700) 억원", None),
        ("A $ (700)", _USD700),
        ("A $ (700) 3", _USD700),
        ("A $ (700) and", _USD700),
        # H2: the same rule for every token.
        ("A 5\tmillion", None),
        ("A 5\nmillion", None),
        ("A 5 (mn)", None),
        ("A 5 (in mn)", None),
        ("A 5 (in millions)", None),
        ("A 5, mn", None),
        ("A 5 - mn", None),
        ("A 5 (천원)", None),
        ("A 5 (단위: 백만)", None),
        ("A 5 million", ("5000000", "num", None)),
        ("A 5 bn", ("5000000000", "num", None)),
        ("A 5 and millions of others", _PLAIN5),
        # H3: a single capital letter refuses unless a letter, digit, "&" or ":" follows it.
        ("A 5 M/yr", None),
        ("A 5 M-", None),
        ("A 5 M\u2026", None),
        ("A 5 M+", None),
        ("A 5 M원", None),
        ("A 5 M x", None),
        ("A 5 M=", None),
        ("A 5 M", None),
        ("A 200  B: 100", ("200", "num", None)),
        ("A 5 M&A", _PLAIN5),
        ("A 5 M3", _PLAIN5),
        # H4: a percent or currency across a tab or a line break.
        ("A 5\t%", None),
        ("A 5\n%", None),
        ("A 5\t원", None),
        ("A 5\n원", None),
        ("A 5\n$3", _PLAIN5),
        ("A 5 %", ("5", "pct", None)),
        ("A 5 원", ("5", "num", "KRW")),
        # H5: a bracket group after the number that holds a mark or a scale.
        ("A 5 (단위: 1,000원)", None),
        ("A 5 ('000 USD)", None),
        ("A 5 (000 USD)", None),
        ("A 5 (2024 USD)", None),
        ("A 5 (x1원)", None),
        ("A 5 (12%)", _PLAIN5),
        ("A 5 ($3)", _PLAIN5),
        ("A 5\n(1%)", _PLAIN5),
        ("A 5 (10 USD)", _PLAIN5),
        ("A 12억원 (전년 10억원)", ("1200000000", "num", "KRW")),
        # H6: a sign glued to the word before it.
        ("A 다- 839 billion", None),
        ("A 매출- 5", None),
        ("A net- 5", None),
        ("A - 5", ("-5", "num", None)),
        ("A -5", ("-5", "num", None)),
        # H7: currency and percent signs the table does not know.
        ("A \u20b9 5", None),
        ("A \u20b95", None),
        ("A 5 \u20b9", None),
        ("A 5 (\u20b9)", None),
        ("A 5 (\ufe6a)", None),
        ("A 5\u2030", None),
        ("A \u0e3f5", None),
        ("A \uff32$ 5", None),
        ("A \uff2e\uff34\uff04 5", None),
        ("A \u00c9$ 5", None),
        ("A 가$ 5", None),
        ("A _$ 5", None),
        ("A R-$ 5", None),
        ("A x\u20ac 5", None),
        ("A 5 R$", None),
        ("A 5 NZ$", None),
        # H8: percent unit labels, by the allow-list of item 1.
        ("A [%] 5", _PLAIN5),
        ("A (단위: %) 5", _PLAIN5),
        ("A [-%] 5", None),
        ("A (단위:-%) 5", None),
        ("A [x1%] 5", None),
        # H9: one mark per token.
        ("A $700%", None),
        ("A ($ 700 %)", None),
        ("A $ (700 %)", None),
    ],
)
def test_nothing_next_to_a_number_is_left_unapplied(candidate, want):
    assert value_after_anchor(_field("x", "A"), candidate) == want
    if want is None:
        assert score_critical_fields([_field("5", "A")], candidate).exact == 0


def test_width_in_metres_is_read_plain():
    """H2 kept: a lower-case "m" spaced after a plain number is a unit, not a scale."""
    assert value_after_anchor(_field("x", "width"), "width 5 m") == _PLAIN5


@pytest.mark.parametrize(
    ("candidate", "want"),
    [
        # The acceptance rule's sign, after the number: one that no number after it takes is
        # next to this number and not applied (read plain 5 before the amendment).
        ("A 5 -", None),
        ("A 5\t+", None),
        ("A 5\n△", None),
        ("A 5 - note", None),
        ("A 5, -", None),
        ("A (5) -", None),
        ("A 5 (-)", None),
        # The next number's own sign: the number before it stands.
        ("A 5 - 3", _PLAIN5),
        ("A 5 -3", _PLAIN5),
        ("A 5 -$3", _PLAIN5),
        ("A 5 - (3)", _PLAIN5),
        ("A 5\n-5", _PLAIN5),
    ],
)
def test_a_sign_no_number_takes_refuses_the_number_before_it(candidate, want):
    assert value_after_anchor(_field("x", "A"), candidate) == want


@pytest.mark.parametrize(
    ("candidate", "want"),
    [
        # H6: pinned as read before the amendment, unchanged. "3-" is a token with a trailing
        # sign (refused); "A- 5": the sign is glued to the anchor, which is not in the text the
        # reader scans, so it is a standalone sign.
        ("A 3- 5", None),
        ("A- 5", ("-5", "num", None)),
        # H5 met an earlier named regression ("A 12억 (전년 10억)" reads 12억): a number with its
        # own scale is like one with its own currency, so a group of other numbers' own marks
        # and scales after it does not refuse it.
        ("A 12억 (전년 10억)", ("1200000000", "num", None)),
        # Stricter than H5 (b), as before the amendment: a group that holds a mark that is no
        # number's own refuses even a number with its own currency.
        ("A $5 (in %)", None),
        ("A 12억원 (단위: 원)", None),
        # Stricter than H8, as before the amendment: "(" right before a non-letter is an
        # accounting paren, so "(%)" is not a label (as "( 원)" is not).
        ("A (%) 5", None),
        # A single letter past punctuation is a label or a list marker, not a scale.
        ("A=100; B=200", ("100", "num", None)),
        ("A 5 (b)", _PLAIN5),
        ("A 5 (M)", _PLAIN5),
    ],
)
def test_decisions_of_the_amendment_where_rules_met(candidate, want):
    anchor = "A=" if candidate.startswith("A=") else "A"
    assert value_after_anchor(_field("x", anchor), candidate) == want


def _scale_expressions() -> dict[str, str]:
    """Every scale expression the module's tables define, by kind: the grammar's English words
    and ``_SCALE_WORDS`` in three cases and plural, every Korean unit run (one small unit, one
    big unit, or both), the single capitals and the grammar's glued letters."""
    out: dict[str, str] = {}
    for w in (*_EN_WORDS, *_SCALE_WORDS):
        for v in (w, w.upper(), w.title()):
            out[v] = "en" if w in _EN_WORDS else "word"
            out[v + "s"] = "plural"
    small = [c for c in _KO_CHARS if c in "천백십"]
    big = [c for c in _KO_CHARS if c in "만억조"]
    for unit in [*small, *big, *(a + b for a in small for b in big)]:
        out[unit] = "ko"
    for c in _SCALE_LETTERS:
        out[c] = "capital"
    for c in _GLUED_LETTERS - _SCALE_LETTERS:
        out[c] = "lower"
    return out


# How each "next to" form joins a scale expression to the number: glued, across ASCII spaces,
# across other whitespace, across a punctuation run, inside a bracket group opened after it.
_NEXT_TO = {
    "": "glued",
    " ": "spaces",
    "  ": "spaces",
    "\t": "whitespace",
    "\n": "whitespace",
    " \t": "whitespace",
    ", ": "punct",
    " - ": "punct",
    "; ": "punct",
    " (": "group",
    "\n(": "group",
    " (in ": "group",
    " [": "group",
}


def _expected_next_to(number: str, form: str, expr: str, kind: str) -> Any:
    """Test side, from the amendment: the plain number reads only when the grammar applies the
    expression (glued English words and letters, spaced English words and Korean units, after
    a plain number), or a single letter stands past punctuation that holds no sign (a label,
    not a scale; a sign no number takes refuses), or a lower-case letter stands across spaces
    after a plain number ("width 5 m")."""
    plain = number in ("5", "$5")
    cur = "USD" if number == "$5" else None
    how = _NEXT_TO[form]
    if "-" in form:
        return None
    if plain and kind == "en" and how in ("glued", "spaces"):
        return (str(5 * _EN_SCALE[expr.lower()]), "num", cur)
    if plain and kind == "ko" and how in ("glued", "spaces"):
        value = 5
        for c in expr:
            value *= {"천": 1000, "백": 100, "십": 10, "만": 10**4, "억": 10**8, "조": 10**12}[c]
        return (str(value), "num", cur)
    if kind in ("capital", "lower") and how in ("punct", "group"):
        return {"5": _PLAIN5, "$5": ("5", "num", "USD"), "(5)": ("-5", "num", None)}.get(
            number, ("-5", "num", "USD")
        )
    if plain and how == "glued" and expr in _GLUED_LETTERS:
        return (str(5 * _EN_SCALE[expr.lower()]), "num", cur)
    if number == "5" and kind == "lower" and how == "spaces":
        return _PLAIN5
    return None


def test_every_scale_expression_next_to_a_number_refuses_it():
    """H1 and H2, closed by enumeration over the module's tables: every scale expression, every
    "next to" form, after a number with and without a currency and with and without accounting
    parentheses. Only what the grammar applies reads, and then scaled."""
    exprs = _scale_expressions()
    assert {"million", "MN", "lakhs", "억", "천만", "M", "k"} <= set(exprs)
    wrong = []
    checked = 0
    for number in ("5", "$5", "(5)", "$ (5)"):
        for form in _NEXT_TO:
            for expr, kind in exprs.items():
                close = ")" if _NEXT_TO[form] == "group" and form.strip().endswith("(") else ""
                close = "]" if form.strip().startswith("[") else close
                close = ")" if form.strip().startswith("(in") else close
                text = f"A {number}{form}{expr}{close}"
                want = _expected_next_to(number, form, expr, kind)
                got = value_after_anchor(_field("x", "A"), text)
                checked += 1
                if got != want:
                    wrong.append((text, got, want))
    assert checked > 1_000
    assert not wrong, (len(wrong), wrong[:20])


def _unlisted_signs() -> list[str]:
    """Every character of the Basic Multilingual Plane in Unicode category Sc, and the percent,
    per-mille and per-ten-thousand signs, that the fold table does not turn into a listed
    currency or "%"."""
    signs = [chr(cp) for cp in range(0x10000) if unicodedata.category(chr(cp)) == "Sc"]
    signs += ["\uff05", "\ufe6a", "\u2030", "\u2031", "\u066a", "\u0609", "\u060a"]
    listed = {k for k in _CURRENCY if len(k) == 1} | {"%"}
    return [c for c in signs if c.translate(_FOLD) not in listed]


def test_every_unlisted_currency_or_percent_sign_refuses_the_number_next_to_it():
    """H7, closed by enumeration: every unlisted sign, before or after the number, glued or
    across ASCII whitespace, alone or in a bracket group or a label: None, never the 5."""
    signs = _unlisted_signs()
    assert len(signs) > 50 and "\u20b9" in signs and "\u2030" in signs
    assert set(signs) <= _FOREIGN
    wrong = []
    for c in signs:
        for ws in ("", " ", "\t", "\n"):
            for text in (f"A {c}{ws}5", f"A 5{ws}{c}", f"A $5{ws}{c}", f"A (5){ws}{c}"):
                got = value_after_anchor(_field("x", "A"), text)
                if got is not None:
                    wrong.append((text, got))
        for text in (f"A 5 ({c})", f"A [{c}] 5", f"A (단위: {c}) 5", f"A 5 (in {c})"):
            got = value_after_anchor(_field("x", "A"), text)
            if got is not None:
                wrong.append((text, got))
    assert not wrong, (len(wrong), wrong[:20])


def test_every_symbol_currency_glued_after_text_refuses_the_number():
    """H7, closed by enumeration over the currency table: every symbol currency (with its fold
    variants) glued after a character that is not ASCII whitespace or an opener and does not
    complete a listed spelling, before the number or after it: None."""
    symbols = sorted(
        {v for k in _CURRENCY if not k.isalpha() and len(k) == 1 for v in _variants(k)}
    )
    assert "$" in symbols and "\u20a9" in symbols and "\uff04" in symbols
    glued_after = ["\uff32", "\u00c9", "가", "_", "R-", "x", "1-", "\u00b7", ")", "Rx", "NZ", "xUS"]
    wrong = []
    for sym in symbols:
        for g in glued_after:
            texts = [f"A {g}{sym} 5", f"A {g}{sym}5"]
            if not any(c in string.digits for c in g):  # "5 1-$": "1-" is the next token
                texts += [f"A 5 {g}{sym}", f"A (5) {g}{sym}"]
            for text in texts:
                got = value_after_anchor(_field("x", "A"), text)
                if got is not None:
                    wrong.append((text, got))
    assert not wrong, (len(wrong), wrong[:20])


def test_a_sign_glued_to_a_word_refuses_the_number_after_it():
    """H6, closed by enumeration over the sign table: every sign (with its fold variants) glued
    to an ASCII letter, a Hangul syllable or closing punctuation, then any ASCII whitespace (and
    a label separator or opening punctuation), then a number with or without a prefix: None.
    Standing alone, the sign is the number's."""
    wrong = []
    for sign in _SIGN_PREFIXES:
        for before in ("x", "net", "매출", "다", "x)"):
            for ws in (" ", "  ", "\t", "\n", " :", " [", "\n= "):
                for number in ("5", "$5", "(5)", "5억", "839 billion"):
                    text = f"A {before}{sign}{ws}{number}"
                    got = value_after_anchor(_field("x", "A"), text)
                    if got is not None:
                        wrong.append((text, got))
        text = f"A {sign} 5"
        want = ("-5" if _SIGN[sign.translate(_FOLD)] else "5", "num", None)
        if value_after_anchor(_field("x", "A"), text) != want:
            wrong.append((text, want))
    assert not wrong, (len(wrong), wrong[:20])


def test_a_token_with_a_currency_and_a_percent_is_refused():
    """H9, closed by enumeration over the currency table: every currency spelling as a prefix or
    a suffix, with a percent glued or spaced, plain or in accounting parentheses: None."""
    wrong = []
    for cur in _CURRENCY_PREFIXES:
        for text in (
            f"A {cur}700%",
            f"A {cur} 700 %",
            f"A ({cur} 700 %)",
            f"A {cur} (700 %)",
            f"A 700 %{cur}",
            f"A 700% {cur}",
        ):
            got = value_after_anchor(_field("x", "A"), text)
            if got is not None:
                wrong.append((text, got))
    assert not wrong, (len(wrong), wrong[:20])


def test_a_group_after_a_number_is_one_other_number_or_refuses():
    """H5, closed by enumeration: a bracket group right after a plain number, across any ASCII
    whitespace, that holds a percent, a currency or a scale, reads the number only when its
    whole content is one other non-zero number that is not a year with a spaced suffix."""
    one = ["12%", "$3", "1%", "10 USD", "3 million USD", "10억원", "1조 2억", "-3%", "($3)"]
    not_one = [
        "단위: 1,000원",
        "'000 USD",
        "000 USD",
        "0%",
        "2024 USD",
        "x1원",
        "전년 10억",
        "전년 $3",
        "in %",
        "12% 3",
        "3 x%",
    ]
    wrong = []
    for ws in (" ", "\t", "\n", ""):
        for o, c in (("(", ")"), ("[", "]"), ("{", "}")):
            for content in one:
                text = f"A 5{ws}{o}{content}{c}"
                if value_after_anchor(_field("x", "A"), text) != _PLAIN5 and ws:
                    wrong.append((text, "not read"))
            for content in not_one:
                text = f"A 5{ws}{o}{content}{c}"
                if value_after_anchor(_field("x", "A"), text) is not None:
                    wrong.append((text, "read"))
    assert not wrong, (len(wrong), wrong[:20])
