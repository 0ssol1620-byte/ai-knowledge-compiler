from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import sfir1_execution as sx  # noqa: E402
import sfir1_worker as worker  # noqa: E402


def candidate(lineage: str = "sfir1:git_docs:one") -> dict:
    return {
        "lineage_id": lineage,
        "family": "git_docs",
        "container_id": "github:example/repository",
        "payload_ref": {
            "before": "https://example.invalid/before.md",
            "after": "https://example.invalid/after.md",
        },
        "revision_id": {"before": "commit-before", "after": "commit-after"},
        "revision_timestamp": {
            "before": "2026-08-24T00:00:00Z",
            "after": "2026-08-25T00:00:00Z",
        },
        "capability_exercise": {"E5": True, "E6": True, "E9": True},
    }


def test_revision_adapter_is_exact_and_newest_first():
    adapted, revisions = worker._revision_adapter(candidate())
    assert adapted["suffix"] == ".md"
    assert [row["version"] for row in revisions] == ["commit-after", "commit-before"]
    assert [row["url"] for row in revisions] == [
        "https://example.invalid/after.md",
        "https://example.invalid/before.md",
    ]


def test_bad_revision_metadata_refuses_before_fetch():
    row = candidate()
    row["revision_timestamp"]["after"] = row["revision_timestamp"]["before"]
    with pytest.raises(sx.Refused, match="strictly increasing"):
        worker._revision_adapter(row)


@pytest.mark.parametrize(
    ("family", "locator", "expected"),
    [
        (
            "git_docs",
            "github://owner/repository/blob/0123456789abcdef/docs/guide.md",
            "https://raw.githubusercontent.com/owner/repository/0123456789abcdef/docs/guide.md",
        ),
        (
            "regulation_ecfr",
            "ecfr://title/12/part/12/section/12.34?version=2026-08-25",
            "https://www.ecfr.gov/api/versioner/v1/full/2026-08-25/title-12.xml?part=12",
        ),
    ],
)
def test_audited_immutable_locator_resolution(family, locator, expected):
    assert worker.resolve_payload_locator(family, locator) == expected


def test_mediawiki_locator_and_unwrap_use_exact_revision(monkeypatch):
    locator = "mediawiki://en.wikipedia.org/page/42/revision/9001"
    url = worker.resolve_payload_locator("encyclopedia_wikipedia", locator)
    query = __import__("urllib.parse").parse.parse_qs(__import__("urllib.parse").parse.urlparse(url).query)
    assert query["pageid"] == ["42"]
    assert query["oldid"] == ["9001"]
    monkeypatch.setattr(worker, "_bounded_http_get", lambda _url: b'{"parse":{"text":"<p>held revision</p>"}}')
    assert worker._default_payload_fetcher("encyclopedia_wikipedia", locator) == b"<p>held revision</p>"


def test_streaming_transport_refuses_before_exceeding_bound(monkeypatch):
    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            return b"x" * (worker.MAX_PAYLOAD_BYTES + 1)

    monkeypatch.setattr(worker.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    with pytest.raises(sx.Refused, match="streamed payload exceeds"):
        worker._bounded_http_get("https://example.invalid/immutable")


def test_ecfr_stream_isolates_exact_section_and_excludes_unrelated(monkeypatch, tmp_path):
    import io

    part = b"""<ECFR><DIV8 TYPE="SECTION" N="12.33"><HEAD>Section 12.33 unrelated</HEAD><P>UNRELATED MATERIAL</P></DIV8><DIV8 TYPE="SECTION" N="12.34"><HEAD>Section 12.34 target</HEAD><P>TARGET MATERIAL</P></DIV8></ECFR>"""

    class Response(io.BytesIO):
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()
            return False

    monkeypatch.setattr(worker.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(part))
    monkeypatch.setattr(worker, "ECFR_PART_CACHE_ROOT", tmp_path / "cache")
    locator = "ecfr://title/12/part/12/section/12.34?version=2026-08-25"
    payload = worker._default_payload_fetcher("regulation_ecfr", locator)
    assert b"TARGET MATERIAL" in payload
    assert b"UNRELATED MATERIAL" not in payload


def test_mock_network_observation_reuses_native_scientific_stack():
    opened: list[str] = []
    before = """# Handbook

## Overview

This paragraph is deliberately long enough to clear the minimum text threshold
the canonicaliser applies before it will admit a unit at all, and it contains a
[link](https://old.invalid/spec) whose native source span must be preserved.

## Details

A second substantial paragraph is also long enough to be admitted on its own,
so this fixture exercises a structural pair rather than an empty document.
"""
    after = before.replace("old.invalid", "new.invalid").replace(
        "A second substantial", "A second, revised substantial"
    )
    payloads = {
        "https://example.invalid/before.md": before.encode(),
        "https://example.invalid/after.md": after.encode(),
    }

    def fetch(_family: str, locator: str) -> bytes:
        opened.append(locator)
        return payloads[locator]

    result = worker._observe_one(candidate(), fetch)
    assert result["status"] == "OBSERVED"
    assert set(result["observations"]) == set(sx.ENDPOINTS)
    assert result["evidence"]["pair"]["after_version"] == "commit-after"
    assert opened == [
        "https://example.invalid/after.md",
        "https://example.invalid/before.md",
    ]


def test_producer_checks_authority_and_single_writer_before_payload(tmp_path, monkeypatch):
    rows = [candidate()]
    verified = {
        name: {"path": f"{name}.json", "sha256": f"sha256:{name}", "schema": schema}
        for name, schema in sx.SCHEMAS.items()
    }
    monkeypatch.setattr(sx, "verify_design_bindings", lambda _bindings: verified)
    monkeypatch.setattr(
        sx,
        "verify_receipt",
        lambda kind, *_args: {
            "body": {"acquisition_authorized": True} if kind == "protocol_freeze" else {"subject": {}},
        },
    )
    monkeypatch.setattr(sx, "roster_candidates", lambda *_args: rows)
    opened: list[str] = []

    def fetch(_family: str, locator: str) -> bytes:
        opened.append(locator)
        return (
            b"# Policy\n\nSee [new](https://new.invalid).\n"
            if "after" in locator
            else b"# Policy\n\nSee [old](https://old.invalid).\n"
        )

    def observe(row, payload_fetcher):
        payload_fetcher(row["family"], row["payload_ref"]["after"])
        payload_fetcher(row["family"], row["payload_ref"]["before"])
        blocks = {
            endpoint: {"exercised": True, "violations": 0, "stages_checked": []}
            for endpoint in sx.ENDPOINTS
        }
        return {
            "status": "OBSERVED",
            "observations": blocks,
            "evidence": {"pair": {"after_version": "commit-after"}, "rebuild": {}},
        }

    monkeypatch.setattr(worker, "_observe_one", observe)

    bindings = {name: (tmp_path / f"{name}.json", f"sha256:{name}") for name in sx.SCHEMAS}
    batch, path, digest = worker.produce_observation_batch(
        bindings,
        payload_fetcher=fetch,
        workers=1,
        spent_authority=tmp_path / "spent.json",
        observation_dir=tmp_path / "observations",
        acquisition_target=tmp_path / "acquisition.json",
    )
    assert batch["lineages_considered"] == 1
    assert path.name.startswith("sfir1-observation-batch--")
    assert sx.sha_file(path) == digest
    assert (tmp_path / "spent.json").is_file()
    assert opened
    ref = batch["evidence"]["sfir1:git_docs:one"]
    assert set(ref) == {"path", "sha256", "content_digest"}
    assert "pair" not in json.dumps(batch)
    evidence_path = Path(ref["path"])
    assert evidence_path.is_file()
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["schema"] == "tavonel.sfir1.scientific_evidence.v1"
    assert "pair" in evidence["result"]["evidence"]

    opened.clear()
    with pytest.raises(sx.Refused, match="already exists"):
        worker.produce_observation_batch(
            bindings,
            payload_fetcher=fetch,
            workers=1,
            spent_authority=tmp_path / "spent.json",
            observation_dir=tmp_path / "observations",
            acquisition_target=tmp_path / "acquisition.json",
        )
    assert opened == []


def test_bounded_scheduler_never_exceeds_worker_window_and_spools_immediately(tmp_path, monkeypatch):
    rows = [candidate(f"sfir1:git_docs:{index:03d}") for index in range(19)]
    lock = threading.Lock()
    active = 0
    maximum = 0
    submitted = 0
    maximum_submitted = 0
    released = threading.Event()
    started = threading.Event()
    blocks = {
        endpoint: {"exercised": True, "violations": 0, "stages_checked": []}
        for endpoint in sx.ENDPOINTS
    }

    def observe(row, _fetch):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            if maximum == 3:
                started.set()
        released.wait(timeout=2)
        with lock:
            active -= 1
        return {
            "status": "OBSERVED",
            "observations": blocks,
            "evidence": {"pair": {"large_body": "x" * 100_000}, "rebuild": {}},
        }

    real_executor = worker.ThreadPoolExecutor

    class TrackingExecutor:
        def __init__(self, *args, **kwargs):
            self.inner = real_executor(*args, **kwargs)

        def __enter__(self):
            self.inner.__enter__()
            return self

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

        def submit(self, *args, **kwargs):
            nonlocal submitted, maximum_submitted
            future = self.inner.submit(*args, **kwargs)
            with lock:
                submitted += 1
                maximum_submitted = max(maximum_submitted, submitted)

            def completed(_future):
                nonlocal submitted
                with lock:
                    submitted -= 1

            future.add_done_callback(completed)
            return future

    monkeypatch.setattr(worker, "_observe_one", observe)
    monkeypatch.setattr(worker, "ThreadPoolExecutor", TrackingExecutor)
    timer = threading.Timer(0.05, released.set)
    timer.start()
    try:
        compact, bound = worker._bounded_observe(
            rows,
            lambda *_args: b"",
            workers=3,
            observation_dir=tmp_path,
        )
    finally:
        timer.cancel()
        released.set()
    assert started.is_set()
    assert maximum <= 3
    assert bound == 3 * worker.IN_FLIGHT_PER_WORKER
    assert maximum_submitted == bound
    assert list(compact) == [row["lineage_id"] for row in rows]
    assert all("evidence" not in result for result in compact.values())
    assert len(list((tmp_path / "evidence").glob("*.json"))) == len(rows)


@pytest.mark.parametrize("workers", [0, 17, True])
def test_bounded_scheduler_refuses_unbounded_worker_counts(tmp_path, workers):
    with pytest.raises(sx.Refused, match="workers must be"):
        worker._bounded_observe(
            [],
            lambda *_args: b"",
            workers=workers,
            observation_dir=tmp_path,
        )


def test_instrument_exception_never_becomes_an_outcome_shaped_rejection(tmp_path, monkeypatch):
    rows = [candidate()]
    verified = {
        name: {"path": f"{name}.json", "sha256": f"sha256:{name}", "schema": schema}
        for name, schema in sx.SCHEMAS.items()
    }
    monkeypatch.setattr(sx, "verify_design_bindings", lambda _bindings: verified)
    monkeypatch.setattr(
        sx,
        "verify_receipt",
        lambda kind, *_args: {
            "body": {"acquisition_authorized": True} if kind == "protocol_freeze" else {"subject": {}},
        },
    )
    monkeypatch.setattr(sx, "roster_candidates", lambda *_args: rows)
    monkeypatch.setattr(worker, "_observe_one", lambda *_args: (_ for _ in ()).throw(RuntimeError("broken instrument")))
    bindings = {name: (tmp_path / f"{name}.json", f"sha256:{name}") for name in sx.SCHEMAS}
    with pytest.raises(sx.Refused, match="scientific observation instrument failed"):
        worker.produce_observation_batch(
            bindings,
            payload_fetcher=lambda *_args: b"not reached",
            workers=1,
            spent_authority=tmp_path / "spent.json",
            observation_dir=tmp_path / "observations",
            acquisition_target=tmp_path / "acquisition.json",
        )
    assert (tmp_path / "spent.json").is_file()
    assert not (tmp_path / "observations").exists()


def test_build_reduces_only_successful_observations_in_roster_order(tmp_path, monkeypatch):
    rows = [candidate("one"), candidate("two"), candidate("three")]
    monkeypatch.setattr(sx, "verify_design_bindings", lambda _bindings: {})
    monkeypatch.setattr(sx, "verify_receipt", lambda *_args: {"body": {"subject": {}}})
    monkeypatch.setattr(sx, "roster_candidates", lambda *_args: rows)
    blocks = {
        endpoint: {"exercised": True, "violations": 0, "stages_checked": []}
        for endpoint in sx.ENDPOINTS
    }
    bindings = {"roster": (tmp_path / "roster.json", "sha256:roster")}
    body = worker.build(
        bindings,
        observations={"one": blocks, "three": blocks},
        rejected_observations=[{"lineage_id": "two", "family": "git_docs", "code": "NO_RAW_DIFFERENCE"}],
        target=tmp_path / "acquisition.json",
    )
    assert [row["lineage_id"] for row in body["admitted"]] == ["one", "three"]
    assert body["lineages_considered"] == 3
    assert body["outcome_blind_reduction"] is True
