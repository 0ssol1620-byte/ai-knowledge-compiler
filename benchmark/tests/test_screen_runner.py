from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

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
            "critical_fields": [{"field_id": "f", "kind": "number", "value": "123450000000"}],
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
            raise RuntimeError("pod died")
        return _output(payload, "1,234.5억")

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
            raise RuntimeError("down")
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
    monkeypatch.setitem(EXTERNAL_RUNNERS, "mineru", lambda p, **_: _output(p, "1,234.6억"))
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
        score_critical_fields([{"field_id": "f", "kind": "number", "value": "n/a"}], "5")
    s = score_critical_fields([{"field_id": "f", "kind": "number", "value": "-5%"}], "5% up")
    assert (s.n, s.exact, s.mismatched) == (1, 0, ("f",))
