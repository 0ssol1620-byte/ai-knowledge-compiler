from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import pytest
from hypothesis import assume, example, given, settings
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


@pytest.mark.parametrize("fill", [*sorted(set(_ALPHABET)), "1 ", "( ", "- ", "1,", "1억 "])
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
        assert canonical_values("number", "1.5" + ch + " 7") == {("7", "num", None)}, repr(ch)


def test_identity_folds_still_apply():
    assert _same("\uff11\uff0c\uff12\uff13\uff14억", "1,234억")  # fullwidth
    assert _same("1\u00a0억", "1억")  # no-break space
    assert _same("\U0001d7cf\U0001d7d0", "12")  # mathematical digits
    assert _same("영업이익\u2009-5%", "-5%")  # thin space before a sign


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
