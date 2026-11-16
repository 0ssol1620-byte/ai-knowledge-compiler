from __future__ import annotations

import hashlib
import logging
import re
import subprocess
import time

import pytest
from akc_native_parsers import hwp_boundary
from akc_native_parsers.hwp_boundary import run_isolated
from akc_native_parsers.hwp_contract import Accepted, Held, HwpAdapterRequest, Retryable
from akc_native_parsers.hwp_signature import HWP3_SIGNATURE

DATA = HWP3_SIGNATURE + b"synthetic body"


def _request(profile: str, data: bytes = DATA, **over: object) -> HwpAdapterRequest:
    base: dict[str, object] = {
        "job_id": "job-1",
        "source_handle": "src_0001",
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "declared_format": "hwp3",
        "authorized_scope_ref": "scope-1",
        "parser_profile": profile,
        "max_bytes": 1_000_000,
        "max_runtime_ms": 20_000,
    }
    base.update(over)
    return HwpAdapterRequest.model_validate(base)


def _run(profile: str, **over: object) -> Accepted | Held | Retryable:
    return run_isolated(_request(profile, **over), DATA, engine="fixture")


def test_fixture_engine_accepts_and_result_hash_is_stable() -> None:
    first, second = _run("fixture:complex_table"), _run("fixture:complex_table")
    assert isinstance(first, Accepted) and isinstance(second, Accepted)
    assert first.result.artifact_hashes == second.result.artifact_hashes
    assert len(first.result.blocks) == 2


def test_unavailable_engine_holds() -> None:
    out = run_isolated(_request("x"), DATA, engine="unavailable")
    assert out == Held(reason_code="HWP_ENGINE_UNAVAILABLE")


def test_crash_is_retryable_not_accepted() -> None:
    assert _run("fixture:crash") == Retryable(reason_code="PARSER_PROCESS_CRASH")


def test_hang_is_killed_and_retryable_within_budget() -> None:
    start = time.monotonic()
    out = _run("fixture:hang", max_runtime_ms=1500)
    assert out == Retryable(reason_code="PARSER_TIMEOUT")
    assert time.monotonic() - start < 15


def test_garbage_output_is_held() -> None:
    assert _run("fixture:garbage_output") == Held(reason_code="PARSER_RESULT_INVALID")


def test_hash_mismatch_is_held_before_any_child_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("child spawned")

    monkeypatch.setattr(subprocess, "Popen", boom)
    request = _request("fixture:complex_table", source_sha256="0" * 64)
    assert run_isolated(request, DATA, engine="fixture") == Held(
        reason_code="HWP_SOURCE_HASH_MISMATCH"
    )


def test_child_manifest_hash_mismatch_is_held() -> None:
    assert _run("fixture:hash_mismatch") == Held(reason_code="HWP_SOURCE_HASH_MISMATCH")


def test_oversized_output_is_held() -> None:
    assert _run("fixture:oversized_output") == Held(reason_code="PARSER_RESULT_TOO_LARGE")
    small = run_isolated(
        _request("fixture:complex_table"), DATA, engine="fixture", max_result_bytes=200
    )
    assert small == Held(reason_code="PARSER_RESULT_TOO_LARGE")


def test_network_attempt_never_yields_accepted_content() -> None:
    out = _run("fixture:attempt_network")
    assert not isinstance(out, Accepted)
    assert out == Retryable(reason_code="PARSER_PROCESS_CRASH")


def test_stderr_content_never_reaches_logs(caplog: pytest.LogCaptureFixture) -> None:
    secret = b"TOPSECRETBODY"
    data = HWP3_SIGNATURE + secret
    with caplog.at_level(logging.DEBUG):
        out = run_isolated(_request("fixture:stderr_leak", data), data, engine="fixture")
    assert isinstance(out, Accepted)
    assert "TOPSECRETBODY" not in caplog.text
    assert "TOPSECRETBODY" not in out.model_dump_json()
    assert any(w.startswith("child_stderr len=") for w in out.result.warnings)


def test_one_bad_file_does_not_block_the_next() -> None:
    kinds = [
        type(_run(p)) for p in ("fixture:complex_table", "fixture:crash", "fixture:complex_table")
    ]
    assert kinds == [Accepted, Retryable, Accepted]


def test_request_and_result_carry_no_host_paths() -> None:
    out = _run("fixture:complex_table")
    assert isinstance(out, Accepted)
    text = _request("fixture:complex_table").model_dump_json() + out.model_dump_json()
    assert not re.search(
        r"[A-Za-z]:[\/]|\\|(?<![A-Za-z0-9_\-\"])/[A-Za-z]", text.replace("section0/", "")
    )
    assert hwp_boundary.__file__ not in text
