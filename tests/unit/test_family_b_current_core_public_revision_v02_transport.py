from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V01_PROTOCOL = ROOT / "research" / "experiments" / "H3-B-CURRENT-CORE-PUBLIC-REVISION-01" / "protocol.json"
V02_DIR = ROOT / "research" / "experiments" / "H3-B-CURRENT-CORE-PUBLIC-REVISION-02"
V02_PROTOCOL = V02_DIR / "protocol.json"
V02_RUNNER = V02_DIR / "run_experiment.py"


def _load_v02():
    spec = importlib.util.spec_from_file_location("h3_b_current_core_v02_runner", V02_RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_v02_is_transport_only_and_preserves_v01_scientific_parameters() -> None:
    v01 = json.loads(V01_PROTOCOL.read_text(encoding="utf-8"))
    v02 = json.loads(V02_PROTOCOL.read_text(encoding="utf-8"))

    assert v02["amendment_scope"] == "TRANSPORT_ONLY"
    assert v02["scientific_parameters_changed_from_v01"] is False
    assert v02["transport"] == {
        "mode": "single_batched_mediawiki_query",
        "expected_request_count": 1,
        "retry_policy": "none_after_v02_seal",
    }
    for key in (
        "source",
        "cutoff",
        "titles",
        "projection",
        "frozen_safety_gates",
        "performance_metrics_are_measurements_not_pass_gates",
    ):
        assert v02[key] == v01[key], key


def test_v02_freeze_scope_covers_v01_evaluator_and_entire_live_package() -> None:
    runner = _load_v02()
    hashes = runner.frozen_hashes()

    assert str(runner.V01_RUNNER.relative_to(runner.ROOT)).replace("\\", "/") in hashes
    package_python = sorted(runner.AKC_CIR.glob("*.py"))
    assert package_python
    for path in package_python:
        relative = str(path.relative_to(runner.ROOT)).replace("\\", "/")
        assert relative in hashes


def test_single_batch_transport_parses_two_revisions_for_every_registered_title(monkeypatch) -> None:
    runner = _load_v02()
    protocol = runner.load_protocol()
    titles = tuple(protocol["titles"])
    pages = []
    for index, title in enumerate(titles, start=1):
        pages.append(
            {
                "pageid": index,
                "title": title,
                "revisions": [
                    {
                        "revid": 2000 + index,
                        "parentid": 1000 + index,
                        "timestamp": "2026-07-31T00:00:00Z",
                        "sha1": f"new-{index}",
                        "slots": {"main": {"content": f"== Section ==\nnew content {index} " + "x " * 100}},
                    },
                    {
                        "revid": 1000 + index,
                        "parentid": 900 + index,
                        "timestamp": "2026-07-30T00:00:00Z",
                        "sha1": f"old-{index}",
                        "slots": {"main": {"content": f"== Section ==\nold content {index} " + "x " * 100}},
                    },
                ],
            }
        )
    payload = {"query": {"pages": pages}}
    encoded = json.dumps(payload).encode("utf-8")
    calls = []

    def fake_urlopen(request, timeout=0):
        calls.append((request.full_url, timeout))
        return io.BytesIO(encoded)

    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)
    pairs = runner.fetch_all_pairs(titles, protocol["cutoff"])

    assert len(calls) == 1
    assert len(pairs) == len(titles) == 12
    assert [item[0] for item in pairs] == list(titles)
    for requested, older, newer in pairs:
        assert older.requested_title == requested
        assert newer.requested_title == requested
        assert older.revid < newer.revid
        assert older.text != newer.text
