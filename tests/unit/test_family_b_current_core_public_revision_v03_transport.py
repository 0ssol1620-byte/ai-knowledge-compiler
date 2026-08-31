from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V01_PROTOCOL = ROOT / "research" / "experiments" / "H3-B-CURRENT-CORE-PUBLIC-REVISION-01" / "protocol.json"
V03_DIR = ROOT / "research" / "experiments" / "H3-B-CURRENT-CORE-PUBLIC-REVISION-03"
V03_PROTOCOL = V03_DIR / "protocol.json"
V03_RUNNER = V03_DIR / "run_experiment.py"


def _load_v03():
    spec = importlib.util.spec_from_file_location("h3_b_current_core_v03_runner", V03_RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_v03_preserves_v01_scientific_parameters_and_declares_only_transport_changes() -> None:
    v01 = json.loads(V01_PROTOCOL.read_text(encoding="utf-8"))
    v03 = json.loads(V03_PROTOCOL.read_text(encoding="utf-8"))

    assert v03["amendment_scope"] == "TRANSPORT_ONLY"
    assert v03["scientific_parameters_changed_from_v01"] is False
    assert v03["transport"]["mode"] == "single_page_mediawiki_queries"
    assert v03["transport"]["minimum_inter_request_seconds"] == 2.0
    assert v03["transport"]["retry_only_for_http_status"] == 429
    assert v03["transport"]["maximum_attempts_per_title"] == 5
    for key in (
        "source",
        "cutoff",
        "titles",
        "projection",
        "frozen_safety_gates",
        "performance_metrics_are_measurements_not_pass_gates",
    ):
        assert v03[key] == v01[key], key


def test_v03_freeze_scope_covers_transport_lineage_and_entire_live_package() -> None:
    runner = _load_v03()
    hashes = runner.frozen_hashes()

    expected_lineage = [
        runner.V01_DIR / "protocol.json",
        runner.V01_DIR / "run_experiment.py",
        runner.V01_DIR / "receipts" / "pre-fetch-seal.json",
        runner.V01_DIR / "receipts" / "blocked-execution.json",
        runner.V02_DIR / "protocol.json",
        runner.V02_DIR / "run_experiment.py",
        runner.V02_DIR / "receipts" / "pre-fetch-seal.json",
        runner.V02_DIR / "receipts" / "blocked-execution.json",
    ]
    for path in expected_lineage:
        assert path.is_file(), path
        relative = str(path.relative_to(runner.ROOT)).replace("\\", "/")
        assert relative in hashes
    for path in sorted(runner.AKC_CIR.glob("*.py")):
        relative = str(path.relative_to(runner.ROOT)).replace("\\", "/")
        assert relative in hashes


def test_single_page_transport_retries_only_429_then_parses_pair(monkeypatch) -> None:
    runner = _load_v03()
    protocol = runner.load_protocol()
    title = protocol["titles"][0]
    payload = {
        "query": {
            "pages": [
                {
                    "pageid": 1,
                    "title": title,
                    "revisions": [
                        {
                            "revid": 200,
                            "parentid": 100,
                            "timestamp": "2026-07-31T00:00:00Z",
                            "sha1": "new",
                            "slots": {"main": {"content": "== Section ==\nnew " + "x " * 100}},
                        },
                        {
                            "revid": 100,
                            "parentid": 90,
                            "timestamp": "2026-07-30T00:00:00Z",
                            "sha1": "old",
                            "slots": {"main": {"content": "== Section ==\nold " + "x " * 100}},
                        },
                    ],
                }
            ]
        }
    }
    calls = []
    sleeps = []

    def fake_urlopen(request, timeout=0):
        calls.append((request.full_url, timeout))
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {"Retry-After": "1"},
                None,
            )
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: sleeps.append(seconds))

    older, newer = runner.fetch_pair(title, protocol["cutoff"], protocol["transport"])

    assert len(calls) == 2
    assert sleeps == [1.0]
    assert older.revid == 100
    assert newer.revid == 200
    assert older.text != newer.text


def test_non_429_http_error_fails_without_retry(monkeypatch) -> None:
    runner = _load_v03()
    protocol = runner.load_protocol()
    title = protocol["titles"][0]
    calls = []

    def fake_urlopen(request, timeout=0):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, None)

    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)

    try:
        runner.fetch_pair(title, protocol["cutoff"], protocol["transport"])
    except urllib.error.HTTPError as exc:
        assert exc.code == 503
    else:  # pragma: no cover
        raise AssertionError("503 must fail closed")
    assert len(calls) == 1
