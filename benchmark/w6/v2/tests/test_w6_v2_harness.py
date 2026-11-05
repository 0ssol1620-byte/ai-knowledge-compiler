"""Offline unit tests for the W6 v2 pilot harness (no network, no secrets)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.w6.v2.acquisition import ItemOutcome, acquire_corpus  # noqa: E402
from benchmark.w6.v2.credentials import load_openrouter_key, redact  # noqa: E402
from benchmark.w6.v2.grading import (  # noqa: E402
    critical_match,
    provenance_hit,
    wilson_interval,
)
from benchmark.w6.v2.retrieval import RagIndex, chunk_text  # noqa: E402


# ---------------------------------------------------------------- acquisition
class _FakeResponse:
    def __init__(self, *, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.url = "https://example.test/fake"

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    def get(self, url, timeout=None):
        behaviour = self.responses[self.calls] if self.calls < len(self.responses) else None
        self.calls += 1
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_acquire_records_failures_not_silent(tmp_path):
    responses = [
        _FakeResponse(status_code=500),  # attempt 1 -> http_500
        _FakeResponse(status_code=500),  # attempt 2
        _FakeResponse(status_code=500),  # attempt 3 -> item fails
        _FakeResponse(payload={"pages": [{"extract": "x" * 2500}]}),  # item 2 ok
    ]
    report = acquire_corpus(
        titles=["Alpha", "Beta"],
        endpoints=["https://e.test/{title}"],
        cache_dir=tmp_path,
        max_attempts_per_item=3,
        client_factory=lambda: _FakeSession(responses),
        clock=lambda: 0.0,
    )
    counts = report.summary_counts()
    assert counts.get("failed") == 1
    assert counts.get("ok") == 1
    failed = next(o for o in report.outcomes if o.status == "failed")
    assert failed.error_class == "http_500"
    assert failed.attempts == 3
    dumped = json.dumps(report.to_dict())
    assert '"status": "failed"' in dumped  # ledgered, never dropped


def test_acquire_respects_deadline_and_ledgers_remaining(tmp_path):
    import httpx

    class AdvancingClock:
        def __init__(self) -> None:
            self.t = 0.0

        def __call__(self) -> float:
            return self.t

    clock = AdvancingClock()

    class SlowSession(_FakeSession):
        def get(self, url, timeout=None):
            clock.t += 600.0  # every network touch burns 10 simulated minutes
            return super().get(url, timeout=timeout)

    responses = [
        _FakeResponse(payload={"pages": [{"extract": "y" * 2500}]}),  # item 1 ok
        httpx.TimeoutException("simulated timeout"),  # item 2 attempt 1
        httpx.TimeoutException("simulated timeout"),  # item 2 attempt 2
        httpx.TimeoutException("simulated timeout"),  # item 2 attempt 3
    ]

    report = acquire_corpus(
        titles=["One", "Two", "Three"],
        endpoints=["https://e.test/{title}"],
        cache_dir=tmp_path,
        phase_deadline_seconds=1200.0,
        client_factory=lambda: SlowSession(responses),
        clock=clock,
    )
    statuses = [o.status for o in report.outcomes]
    assert statuses[0] == "ok"
    assert statuses[1] == "failed" and report.outcomes[1].error_class == "timeout"
    assert statuses[2] == "deadline_exceeded"
    # invariant: every title is ledgered exactly once — no silent drops
    all_titles = {o.title for o in report.outcomes} | set(report.deadline_exhausted_remaining)
    assert all_titles == {"One", "Two", "Three"}


def test_cache_hit_skips_network(tmp_path):
    title = "Cached"
    from hashlib import sha1

    cache_file = tmp_path / f"{sha1(title.encode(), usedforsecurity=False).hexdigest()}.json"
    cache_file.write_text(json.dumps({"title": title, "text": "z" * 3000}), encoding="utf-8")
    seen: list[str] = []

    class NoNet(_FakeSession):
        def get(self, url, timeout=None):
            seen.append(url)
            raise AssertionError("network used despite warm cache")

    report = acquire_corpus(
        titles=[title],
        endpoints=["https://e.test/{title}"],
        cache_dir=tmp_path,
        client_factory=lambda: NoNet([]),
        clock=lambda: 0.0,
    )
    assert report.summary_counts().get("cache_hit") == 1
    assert not seen


def test_item_outcome_never_carries_secret_shapes():
    outcome = ItemOutcome(source_id="src-000", title="T", status="failed", error_class="timeout")
    blob = json.dumps(outcome.to_dict())
    assert "sk-or" not in blob.lower()


# ---------------------------------------------------------------- credentials
def test_load_key_prefers_env_and_redacts():
    env = {"OPENROUTER_API_KEY": "sk-or-v1-" + "a" * 64}
    key = load_openrouter_key(environment=env)
    assert key == env["OPENROUTER_API_KEY"]
    preview = redact(key)
    assert "a" * 10 not in preview and "chars" in preview


def test_load_key_parses_labelled_file(tmp_path):
    secret = "sk-or-v1-" + "b" * 64
    cred = tmp_path / "api.txt"
    cred.write_text(f"Github some other token\nOpenrouter {secret}\n", encoding="utf-8")
    assert load_openrouter_key(environment={}, credential_file=cred) == secret


def test_load_key_failure_does_not_leak(tmp_path):
    cred = tmp_path / "empty.txt"
    cred.write_text("nothing here\n", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_openrouter_key(environment={}, credential_file=cred)
    assert "b" * 20 not in str(excinfo.value)


# ------------------------------------------------------------------- grading
def test_critical_match_normalisation():
    assert critical_match("The tower is 330 metres tall.", "330 metres")
    assert critical_match("built in 1,889", "1889")
    assert not critical_match("no relevant fact here", "1889")


def test_provenance_hit_variants():
    assert provenance_hit("blah\nSources: src-001, src-002", "src-001") is True
    assert provenance_hit("blah\nSources: src-002", "src-001") is False
    assert provenance_hit("no sources line", "src-001") is None


def test_wilson_interval_bounds():
    low, high = wilson_interval(30, 60)
    assert 0 < low < 0.5 < high < 1


# ------------------------------------------------------------------ retrieval
def test_chunking_overlap_and_rag_context():
    docs = {
        "src-001": {"text": "alpha beta " * 200},
        "src-002": {"text": "quantum tunneling allows particles to pass barriers " * 50},
    }
    chunks = chunk_text(docs["src-002"]["text"], chunk_chars=900, overlap_chars=120)
    assert len(chunks) > 1
    index = RagIndex(docs)
    context, sources = index.context_for(docs, "how does quantum tunneling work?", top_k=5)
    assert context.startswith("RETRIEVED CHUNKS:")
    assert all(sid.startswith("src-") for sid in sources)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
