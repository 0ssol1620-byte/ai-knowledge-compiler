"""Page-image runners (vLLM chat endpoints, Gemini) against a fake transport only."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from benchmark.run_benchmark import parser_output_validator
from benchmark.runners import vlm
from benchmark.runners.base import RunnerUnavailable
from benchmark.runners.registry import EXTERNAL_RUNNERS

ROOT = Path(__file__).resolve().parents[2]
REVISION = "a" * 40
IMAGE = b"\x89PNG fake page bytes"
VLLM = {
    "ovis_ocr2": "ATH-MaaS/OvisOCR2",
    "minicpm_ocr_1": "openbmb/MiniCPM-OCR-1.0",
    "nemotron_parse_3_5": "nvidia/Nemotron-3.5-Parse",
    "teleocr": "XingChen-AGI/TeleOCR",
}
GEMINI = "gemini-3.8-flash"
GEMINI_URL = f"https://gemini.example/v1beta/models/{GEMINI}:generateContent"


def _payload() -> dict[str, Any]:
    return {
        "benchmark_case_id": "page-1",
        "page_index": 0,
        "source": {
            "content_type": "image/png",
            "bytes_base64": base64.b64encode(IMAGE).decode(),
        },
    }


class FakeTransport:
    def __init__(self, status: int, raw: bytes) -> None:
        self.status, self.raw, self.calls = status, raw, []

    def __call__(self, config, body, headers, **_):
        self.calls.append((config, json.loads(body), headers))
        return self.status, "application/json", self.raw


def _chat(model: str, **over: Any) -> bytes:
    body = {
        "model": model,
        "choices": [{"finish_reason": "stop", "message": {"content": "# 안녕"}}],
        "usage": {"completion_tokens": 3},
    }
    body.update(over)
    return json.dumps(body, ensure_ascii=False).encode()


def _gemini(**over: Any) -> bytes:
    body = {
        "modelVersion": GEMINI,
        "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "hello"}]}}],
    }
    body.update(over)
    return json.dumps(body).encode()


def _call(provider: str, transport: FakeTransport, monkeypatch, **kw: Any) -> dict[str, Any]:
    monkeypatch.setattr(vlm, "post_bytes", transport)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    endpoint = (
        GEMINI_URL if provider == "gemini_api" else "https://vllm.example/v1/chat/completions"
    )
    kwargs: dict[str, Any] = {"endpoint": endpoint, "revision": REVISION, "allow_network": True}
    kwargs.update(kw)
    return EXTERNAL_RUNNERS[provider](_payload(), **kwargs)


def test_registered() -> None:
    assert {*VLLM, "gemini_api"} <= set(EXTERNAL_RUNNERS)


@pytest.mark.parametrize(("provider", "model"), VLLM.items())
def test_vllm_request_shape_and_valid_result(provider: str, model: str, monkeypatch) -> None:
    transport = FakeTransport(200, _chat(model))
    out = _call(provider, transport, monkeypatch)
    config, request, _ = transport.calls[0]
    assert config.model_revision == REVISION and config.provider == provider
    assert request["model"] == model and request["temperature"] == 0.0
    parts = request["messages"][0]["content"]
    assert (
        parts[0]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(IMAGE).decode()
    )
    assert parts[1]["text"] == out["metrics"]["receipt"]["prompt"]
    assert not list(parser_output_validator(ROOT / "benchmark" / "manifest.yaml").iter_errors(out))
    assert out["text"] == "# 안녕" and out["provider"] == provider
    receipt = out["metrics"]["receipt"]
    assert receipt["model_revision"] == REVISION and receipt["generation"]["max_tokens"]
    assert receipt["image_sha256"] == hashlib.sha256(IMAGE).hexdigest()


@pytest.mark.parametrize("revision", ["", "main", "abc", "G" * 40])
def test_missing_or_unpinned_revision_refuses_before_any_call(revision: str, monkeypatch) -> None:
    transport = FakeTransport(200, b"{}")
    with pytest.raises(RunnerUnavailable, match="revision"):
        _call("teleocr", transport, monkeypatch, revision=revision)
    assert transport.calls == []


def test_network_needs_explicit_authority() -> None:
    with pytest.raises(RunnerUnavailable, match="allow-network"):
        EXTERNAL_RUNNERS["ovis_ocr2"](
            _payload(), endpoint="https://vllm.example/v1/chat/completions", revision=REVISION
        )


def test_synthetic_case_refused() -> None:
    with pytest.raises(RunnerUnavailable, match="source"):
        EXTERNAL_RUNNERS["ovis_ocr2"](
            {"benchmark_case_id": "x", "synthetic_fixture": {}},
            endpoint="https://vllm.example/x",
            revision=REVISION,
            allow_network=True,
        )


def test_pdf_page_is_rendered_by_index(monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(vlm, "render_pdf_page", lambda d, i, s: seen.append((d, i, s)) or IMAGE)
    payload = _payload()
    payload["page_index"] = 3
    payload["source"]["content_type"] = "application/pdf"
    monkeypatch.setattr(vlm, "post_bytes", FakeTransport(200, _chat(VLLM["teleocr"])))
    out = EXTERNAL_RUNNERS["teleocr"](
        payload, endpoint="https://v.example/x", revision=REVISION, allow_network=True
    )
    assert seen == [(IMAGE, 3, vlm.RENDER_SCALE)]
    assert out["metrics"]["receipt"]["image_mime"] == "image/png"


@pytest.mark.parametrize(
    ("status", "raw"),
    [
        (500, b"upstream exploded"),
        (200, b"\xff\xfe not json at all"),
        (200, b"[1, 2]"),
        (200, b"{}"),
        (200, _chat("some/other-model")),
        (200, _chat(VLLM["ovis_ocr2"], choices=[{"finish_reason": "length", "message": {}}])),
        (200, _chat(VLLM["ovis_ocr2"], choices=[])),
        (
            200,
            _chat(
                VLLM["ovis_ocr2"], choices=[{"finish_reason": "stop", "message": {"content": " "}}]
            ),
        ),
    ],
)
def test_refused_or_malformed_response_is_a_failure_row_with_raw_bytes(
    status: int, raw: bytes, monkeypatch
) -> None:
    out = _call("ovis_ocr2", FakeTransport(status, raw), monkeypatch)
    receipt = out["receipt"]
    # the exact bytes survive, hashed and stored before parsing; the page is not dropped
    assert base64.b64decode(receipt["raw_response_b64"]) == raw
    assert receipt["raw_response_sha256"] == hashlib.sha256(raw).hexdigest()
    assert out["failure"]["reason"] and "text" not in out
    errors = list(parser_output_validator(ROOT / "benchmark" / "manifest.yaml").iter_errors(out))
    assert errors  # the screen runner records contract_failed and keeps the raw output


def test_raw_is_kept_even_if_parse_blows_up(monkeypatch) -> None:
    raw = _chat(VLLM["ovis_ocr2"])

    real = json.loads

    def boom(data: Any) -> Any:
        if data == raw:
            raise RecursionError("parser died")
        return real(data)

    monkeypatch.setattr(vlm.json, "loads", boom)
    out = _call("ovis_ocr2", FakeTransport(200, raw), monkeypatch)
    assert out["failure"]["reason"] and "text" not in out
    assert base64.b64decode(out["receipt"]["raw_response_b64"]) == raw


def test_deeply_nested_json_is_a_failure_row_with_raw_bytes(monkeypatch) -> None:
    raw = b"[" * 200000 + b"]" * 200000
    out = _call("ovis_ocr2", FakeTransport(200, raw), monkeypatch)
    assert out["failure"]["reason"] == "malformed_response"
    assert base64.b64decode(out["receipt"]["raw_response_b64"]) == raw


def test_oversized_pdf_page_is_refused_before_rendering(monkeypatch) -> None:
    import sys
    import types

    class Page:
        def get_size(self) -> tuple[float, float]:
            return 14400.0, 14400.0

        def render(self, **_: Any) -> Any:
            raise AssertionError("must not render above the cap")

    fake = types.SimpleNamespace(PdfDocument=lambda _data: [Page()])
    monkeypatch.setitem(sys.modules, "pypdfium2", fake)
    with pytest.raises(RunnerUnavailable):
        vlm.render_pdf_page(b"%PDF", 0, vlm.RENDER_SCALE)


def test_transport_failure_is_unavailable_not_a_fallback(monkeypatch) -> None:
    def down(*_a: Any, **_k: Any) -> Any:
        raise RunnerUnavailable("benchmark provider is unavailable")

    monkeypatch.setattr(vlm, "post_bytes", down)
    with pytest.raises(RunnerUnavailable):
        EXTERNAL_RUNNERS["teleocr"](
            _payload(), endpoint="https://v.example/x", revision=REVISION, allow_network=True
        )


def test_gemini_request_shape_and_key_stays_out_of_the_record(monkeypatch) -> None:
    transport = FakeTransport(200, _gemini(usageMetadata={"totalTokenCount": 9}))
    out = _call("gemini_api", transport, monkeypatch)
    _, request, headers = transport.calls[0]
    assert headers["x-goog-api-key"] == "test-key-not-real"
    inline = request["contents"][0]["parts"][0]["inline_data"]
    assert inline["mime_type"] == "image/png" and base64.b64decode(inline["data"]) == IMAGE
    assert request["generationConfig"]["temperature"] == 0.0
    assert out["metrics"]["receipt"]["model"] == GEMINI
    assert out["metrics"]["receipt"]["usage"] == {"totalTokenCount": 9}
    assert "test-key-not-real" not in json.dumps(out)
    assert not list(parser_output_validator(ROOT / "benchmark" / "manifest.yaml").iter_errors(out))


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://g.example/v1beta/models/gemini-flash-latest:generateContent",
        "https://g.example/v1beta/models/gemini-pro-latest:generateContent",
        "https://g.example/v1beta/models/flash:generateContent",
        "https://g.example/v1beta/generateContent",
        None,
    ],
)
def test_gemini_refuses_an_alias_or_a_missing_model(endpoint: str | None, monkeypatch) -> None:
    transport = FakeTransport(200, _gemini())
    monkeypatch.setattr(vlm, "post_bytes", transport)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    with pytest.raises(RunnerUnavailable):
        EXTERNAL_RUNNERS["gemini_api"](
            _payload(), endpoint=endpoint, revision="snap-2026-11-17", allow_network=True
        )
    assert transport.calls == []


def test_gemini_explicit_alias_parameter_refused_and_endpoint_must_agree(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    run = EXTERNAL_RUNNERS["gemini_api"]
    with pytest.raises(RunnerUnavailable, match="alias"):
        run(
            _payload(),
            endpoint=GEMINI_URL,
            revision="r",
            allow_network=True,
            model="gemini-flash-latest",
        )
    with pytest.raises(RunnerUnavailable, match="does not name"):
        run(
            _payload(),
            endpoint=GEMINI_URL,
            revision="r",
            allow_network=True,
            model="gemini-3.9-pro",
        )


def test_gemini_needs_a_key(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RunnerUnavailable, match="GEMINI_API_KEY"):
        EXTERNAL_RUNNERS["gemini_api"](
            _payload(), endpoint=GEMINI_URL, revision="r", allow_network=True
        )


@pytest.mark.parametrize(
    "raw",
    [
        _gemini(modelVersion="gemini-3.8-flash-002"),  # silent redirect of an alias
        _gemini(candidates=[{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]),
        _gemini(promptFeedback={"blockReason": "SAFETY"}),
        b'{"candidates": []}',
    ],
)
def test_gemini_bad_response_is_a_failure_row(raw: bytes, monkeypatch) -> None:
    out = _call("gemini_api", FakeTransport(200, raw), monkeypatch)
    assert "failure" in out and base64.b64decode(out["receipt"]["raw_response_b64"]) == raw
