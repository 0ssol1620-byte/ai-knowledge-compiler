from __future__ import annotations

import hashlib
import json
import re
import socket
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from research.vendor_comparison_20261017 import run
from research.vendor_comparison_20261017.adapters import ADAPTERS
from research.vendor_comparison_20261017.adapters.base import (
    Document,
    MissingResponseShape,
    ParseResult,
    Pin,
    ReplayTransport,
    Status,
)
from research.vendor_comparison_20261017.adapters.landingai import LandingAIAdapter
from research.vendor_comparison_20261017.adapters.llamaparse import LlamaParseAdapter
from research.vendor_comparison_20261017.adapters.reducto import ReductoAdapter
from research.vendor_comparison_20261017.adapters.unstructured import UnstructuredAdapter
from research.vendor_comparison_20261017.cost import SNAPSHOTS, document_cost

PACKAGE = Path(run.__file__).parent
CASES = run.cases()
DOC = Document("SYNTHETIC-doc-unit", b"%PDF-1.7\n% SYNTHETIC unit bytes\n%%EOF\n", 2)
OK_LANDINGAI = {"status": 200, "json": {"markdown": "SYNTHETIC text."}}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _case(vendor: str, scenario: str) -> dict[str, object]:
    return next(c for c in CASES if c["vendor"] == vendor and c["name"] == scenario)


def test_socket_guard_blocks_network() -> None:
    with pytest.raises(AssertionError, match="network access attempted"):
        socket.create_connection(("127.0.0.1", 9))
    with socket.socket() as sock, pytest.raises(AssertionError, match="network access"):
        sock.connect(("127.0.0.1", 9))


def test_package_has_no_network_or_environment_access() -> None:
    network = re.compile(
        r"^\s*(?:from|import)\s+(socket|ssl|http|urllib|requests|httpx|aiohttp)\b", re.MULTILINE
    )
    sources = [p for p in PACKAGE.rglob("*.py") if "tests" not in p.parts]
    assert len(sources) >= 9
    for source in sources:
        text = source.read_text(encoding="utf-8")
        assert not network.search(text), source.name
        assert not re.search(r"\benviron\b|\bgetenv\b", text), source.name


def test_every_fixture_is_labelled_synthetic_in_name_and_data() -> None:
    paths = sorted((PACKAGE / "fixtures" / "synthetic").iterdir())
    assert len(paths) == 6
    for path in paths:
        assert path.name.startswith("SYNTHETIC-"), path.name
        assert json.loads(path.read_text(encoding="utf-8"))["label"] == "SYNTHETIC"


def test_unlabelled_fixture_is_refused(tmp_path: Path) -> None:
    named = tmp_path / "SYNTHETIC-x.json"
    named.write_text('{"label": "real"}', encoding="utf-8")
    unnamed = tmp_path / "vendor-x.json"
    unnamed.write_text('{"label": "SYNTHETIC"}', encoding="utf-8")
    for path in (named, unnamed):
        with pytest.raises(ValueError, match="SYNTHETIC"):
            run.load_fixture(path)


@pytest.mark.parametrize("case", CASES, ids=[f"{c['vendor']}:{c['name']}" for c in CASES])
def test_every_synthetic_scenario_meets_its_expectation(case: dict[str, object]) -> None:
    row = run._row(case)
    assert row["mismatches"] == [], {key: row.get(key) for key in row["mismatches"]}


def test_a_wrong_expectation_is_reported() -> None:
    case = _case("landingai", "ok")
    expected = {"status": "timeout", "attempts": 9, "SYNTHETIC_unknown_key": None}
    row = run._row({**case, "expected": expected})
    assert row["mismatches"] == ["status", "attempts", "SYNTHETIC_unknown_key"]


def test_every_adapter_meets_all_six_failure_paths() -> None:
    required = {"rate_limited", "server_error", "timeout", "size_rejected", "empty_output"}
    for vendor in ADAPTERS:
        rows = [run._row(c) for c in CASES if c["vendor"] == vendor]
        assert required <= {row["status"] for row in rows}, vendor
        assert any(
            r["scenario"] == "broken_json" and r["status"] == "malformed_response" for r in rows
        ), vendor


def test_only_429_and_5xx_are_retried_with_backoff() -> None:
    clock = FakeClock()
    transport = ReplayTransport(
        [{"status": 429, "text": ""}, {"status": 503, "text": ""}, OK_LANDINGAI]
    )
    pin = Pin("D-V-landingai", "SYNTHETIC_KEY_NAME", 60.0)
    result = LandingAIAdapter(transport, sleep=clock.sleep, clock=clock).parse(DOC, pin)
    assert (result.status, result.attempts, clock.sleeps) == (Status.OK, 3, [2.0, 4.0])
    assert result.elapsed_s == 6.0

    clock = FakeClock()
    transport = ReplayTransport([{"timeout": True}])
    result = LandingAIAdapter(transport, sleep=clock.sleep, clock=clock).parse(DOC, pin)
    assert (result.status, result.attempts, clock.sleeps) == (Status.TIMEOUT, 1, [])
    assert result.raw_sha256 is None


def test_api_key_travels_by_name_only(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = "SYNTHETIC-sentinel-value-that-must-never-appear"
    monkeypatch.setenv("SYNTHETIC_LLAMAPARSE_KEY_NAME", sentinel)
    case = _case("llamaparse", "ok")
    result, transport = run.run_case(case)
    assert result.status == Status.OK
    assert {r.api_key_env for r in transport.requests} == {"SYNTHETIC_LLAMAPARSE_KEY_NAME"}
    dumped = repr(transport.requests) + repr(result) + json.dumps(run._row(case), default=str)
    assert sentinel not in dumped


def test_vendor_receives_the_exact_source_bytes() -> None:
    transport = ReplayTransport([OK_LANDINGAI])
    result = LandingAIAdapter(transport).parse(DOC, Pin("D-V-landingai", "SYNTHETIC_KEY", 60.0))
    assert transport.requests[0].file_bytes == DOC.pdf
    assert result.source_sha256 == hashlib.sha256(DOC.pdf).hexdigest()
    assert (
        result.raw_sha256 == hashlib.sha256(json.dumps(OK_LANDINGAI["json"]).encode()).hexdigest()
    )


@pytest.mark.parametrize("adapter", [ReductoAdapter, UnstructuredAdapter])
def test_uncaptured_response_shape_refuses_before_any_request(adapter: type) -> None:
    transport = ReplayTransport([{"status": 200, "json": {"markdown": "x"}}])
    with pytest.raises(MissingResponseShape, match=r"no response shape"):
        adapter(transport).parse(DOC, Pin("D-V-x", "SYNTHETIC_KEY", 60.0))
    assert transport.requests == []


@pytest.mark.parametrize(
    "config",
    [
        {"tier": "agentic", "version": "latest"},
        {"tier": "agentic"},
        {"tier": "premium", "version": "2026-01-08"},
        {},
    ],
)
def test_llamaparse_refuses_unreproducible_config_before_any_request(
    config: dict[str, str],
) -> None:
    transport = ReplayTransport([])
    with pytest.raises(ValueError, match="llamaparse"):
        LlamaParseAdapter(transport).parse(DOC, Pin("D-V-llamaparse", "K", 60.0, config))
    assert transport.requests == []


def test_llamaparse_job_past_its_deadline_is_a_timeout() -> None:
    clock = FakeClock()
    pending = {"status": 200, "json": {"job": {"status": "SYNTHETIC_IN_PROGRESS"}}}
    transport = ReplayTransport(
        [{"status": 200, "json": {"id": "f"}}, {"status": 200, "json": {"id": "j"}}] + [pending] * 4
    )
    pin = Pin("D-V-llamaparse", "K", 5.0, {"tier": "agentic", "version": "2026-01-08"})
    result = LlamaParseAdapter(transport, sleep=clock.sleep, clock=clock).parse(DOC, pin)
    assert (result.status, result.failure_class) == (Status.TIMEOUT, "operational")
    assert clock.sleeps == [2.0, 2.0, 2.0]
    assert transport.unused == 0 and result.markdown == ""


def _result(**changes: Any) -> ParseResult:
    base = ParseResult("D-V-landingai", DOC.doc_id, "0" * 64, Status.OK, "x", 1, {}, None, 0.0, 1)
    return replace(base, **changes)


def test_landingai_snapshot_rounds_credits_up_to_a_tenth() -> None:
    cost = document_cost("landingai", _result(markdown="x"), replace(DOC, pages=1), {})
    assert cost is not None and cost.snapshot_usd == Decimal("0.011")  # 1.0005 -> 1.1 credits


def test_document_that_never_reached_the_vendor_costs_nothing() -> None:
    cost = document_cost("reducto", _result(status=Status.SIZE_REJECTED, attempts=0), DOC, {})
    assert cost is not None and (cost.snapshot_usd, cost.metadata_usd) == (Decimal(0), None)


def test_tavonel_live_has_no_list_price_and_unknown_vendor_raises() -> None:
    assert document_cost("tavonel_live", _result(), DOC, {}) is None
    for attempts in (0, 1):
        with pytest.raises(ValueError, match="no price snapshot"):
            document_cost("acme", _result(attempts=attempts), DOC, {})


def test_price_snapshots_bind_receipt_files_by_sha256() -> None:
    assert set(SNAPSHOTS) == set(ADAPTERS) - {"tavonel_live"}
    for snapshot in SNAPSHOTS.values():
        assert snapshot.quoted
        for file, sha256, retrieved in snapshot.sources:
            assert file.startswith("competitor-protocol-receipts/web/")
            assert re.fullmatch(r"[0-9a-f]{64}", sha256)
            assert retrieved.startswith("2026-10-17T")
