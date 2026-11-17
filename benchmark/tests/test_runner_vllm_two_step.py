"""C1 PaddleOCR-VL-1.6 and C3 MinerU2.5-Pro (two-step) on vLLM chat endpoints, fakes only."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import secrets
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from benchmark.run_benchmark import parser_output_validator
from benchmark.runners import base, mineru_vlm, vlm
from benchmark.runners.base import RunnerUnavailable
from benchmark.runners.registry import EXTERNAL_RUNNERS, RUNNER_CONFIGS
from benchmark.runners.vlm import PageRefused

ROOT = Path(__file__).resolve().parents[2]
REVISION = "a" * 40
ENDPOINT = "https://vllm.example/v1/chat/completions"
C1, C3 = "paddleocr_vl_1_6_vllm", "mineru_vlm"
SERVED = {
    C1: f"PaddlePaddle/PaddleOCR-VL-1.6@{REVISION}",
    C3: f"opendatalab/MinerU2.5-Pro-2605-1.2B@{REVISION}",
}
VALIDATOR = parser_output_validator(ROOT / "benchmark" / "manifest.yaml")
TEXT = mineru_vlm.REGION_PROMPTS["default"]
TABLE = mineru_vlm.REGION_PROMPTS["table"]
FORMULA = mineru_vlm.REGION_PROMPTS["equation"]


def _png(size: tuple[int, int] = (200, 100)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    return buffer.getvalue()


PAGE = _png()


def _payload(data: bytes = PAGE, content_type: str = "image/png") -> dict[str, Any]:
    return {
        "benchmark_case_id": "page-1",
        "page_index": 0,
        "source": {"content_type": content_type, "bytes_base64": base64.b64encode(data).decode()},
    }


def _chat(text: str, *, served: str = SERVED[C3], finish: str = "stop") -> bytes:
    body = {
        "model": served,
        "choices": [{"finish_reason": finish, "message": {"content": text}}],
        "usage": {"completion_tokens": 3},
    }
    return json.dumps(body, ensure_ascii=False).encode()


def _box(x1: int, y1: int, x2: int, y2: int, kind: str, rotate: str = "") -> str:
    turn = f"<|rotate_{rotate}|>" if rotate else ""
    return f"<|box_start|>{x1} {y1} {x2} {y2}<|box_end|><|ref_start|>{kind}<|ref_end|>{turn}"


LAYOUT = "\n".join(
    [
        _box(0, 0, 500, 500, "text", "up"),
        _box(500, 0, 1000, 500, "table"),
        _box(0, 500, 500, 1000, "image"),
        _box(500, 500, 1000, 1000, "equation"),
    ]
)


class Server:
    """A fake vLLM server: the first call gets ``layout``, every later call the next of
    ``regions``. A reply is raw bytes (status 200), (status, raw), or an exception to raise."""

    def __init__(self, layout: Any, regions: list[Any] | None = None) -> None:
        self.layout, self.regions = layout, list(regions or [])
        self.calls: list[tuple[Any, dict[str, Any], dict[str, str]]] = []

    def __call__(self, config: Any, body: bytes, headers: dict[str, str], **_: Any) -> Any:
        request = json.loads(body)
        self.calls.append((config, request, headers))
        reply = self.layout if len(self.calls) == 1 else self.regions.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        status, raw = reply if isinstance(reply, tuple) else (200, reply)
        return status, "application/json", raw


def _run(provider: str, server: Any, monkeypatch: pytest.MonkeyPatch, **kw: Any) -> dict[str, Any]:
    monkeypatch.setattr(base, "post_bytes", server)
    monkeypatch.setattr(vlm, "post_bytes", server)
    payload = kw.pop("payload", None) or _payload()
    kwargs = {"endpoint": ENDPOINT, "revision": REVISION, "allow_network": True, **kw}
    return EXTERNAL_RUNNERS[provider](payload, **kwargs)


def _image(request: dict[str, Any]) -> Image.Image:
    part = next(p for p in request["messages"][0]["content"] if p["type"] == "image_url")
    head, data = part["image_url"]["url"].split(",", 1)
    assert head == "data:image/png;base64"
    return Image.open(io.BytesIO(base64.b64decode(data)))


def _prompt(request: dict[str, Any]) -> str:
    return next(p["text"] for p in request["messages"][0]["content"] if p["type"] == "text")


def _raw(step: dict[str, Any]) -> bytes:
    return base64.b64decode(step["raw_response_b64"])


def _happy() -> Server:
    return Server(_chat(LAYOUT), [_chat("para"), _chat("<fcel>a<nl>"), _chat("x^2")])


# --- registration ---


def test_both_keys_registered_and_the_external_c1_key_is_unchanged() -> None:
    assert {C1, C3} <= set(EXTERNAL_RUNNERS) and {C1, C3} <= set(RUNNER_CONFIGS)
    from benchmark.runners import paddleocr_vl

    assert EXTERNAL_RUNNERS["paddleocr_vl_1_6"] is paddleocr_vl.run
    for provider in (C1, C3):
        cfg = RUNNER_CONFIGS[provider](revision=REVISION)
        assert cfg["served_model_name"] == SERVED[provider]
        other = RUNNER_CONFIGS[provider](revision="b" * 40)
        assert vlm.config_sha256(other) != vlm.config_sha256(cfg)


# --- C1 ---


def test_c1_sends_the_card_prompt_after_the_page_and_returns_an_attested_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = Server(_chat("# 안녕", served=SERVED[C1]))
    out = _run(C1, server, monkeypatch)
    _, request, headers = server.calls[0]
    assert request["model"] == SERVED[C1] and request["temperature"] == 0.0
    assert [p["type"] for p in request["messages"][0]["content"]] == ["image_url", "text"]
    assert _prompt(request) == "OCR:" and "Authorization" not in headers
    assert not list(VALIDATOR.iter_errors(out)) and out["text"] == "# 안녕"
    receipt = out["metrics"]["receipt"]
    assert receipt["revision_attested"] is True
    assert receipt["config_sha256"] == vlm.config_sha256(RUNNER_CONFIGS[C1](revision=REVISION))
    assert receipt["prompt_source"].startswith("card at c5630aba")


@pytest.mark.parametrize(
    "served", ["PaddlePaddle/PaddleOCR-VL-1.6", f"PaddlePaddle/PaddleOCR-VL-1.6@{'b' * 40}", "x"]
)
def test_c1_an_answer_from_another_revision_is_a_failure_row(
    served: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _chat("text", served=served)
    out = _run(C1, Server(raw), monkeypatch)
    assert out["failure"] == {"reason": "served_model_differs"}
    assert out["receipt"]["revision_attested"] is False and _raw(out["receipt"]) == raw


def test_c1_a_non_stop_finish_is_a_failure_row(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _chat("cut off", served=SERVED[C1], finish="length")
    out = _run(C1, Server(raw), monkeypatch)
    assert out["failure"] == {"reason": "finish_reason_not_stop"} and _raw(out["receipt"]) == raw


# --- both: door, exit, page refusals ---


@pytest.mark.parametrize("provider", [C1, C3])
def test_a_token_echoed_by_the_server_becomes_the_fixed_failure_row(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = "tok-" + secrets.token_urlsafe(24)
    monkeypatch.setenv("AKC_BENCHMARK_PROVIDER_TOKEN", marker)
    if provider == C1:
        server = Server(_chat(f"page {marker}", served=SERVED[C1]))
    else:  # the layout is clean; the second step echoes it
        server = Server(_chat(_box(0, 0, 1000, 1000, "text")), [_chat(f"page {marker}")])
    out = _run(provider, server, monkeypatch)
    assert all(h["Authorization"] == f"Bearer {marker}" for _, _, h in server.calls)
    assert out == {
        "schema_version": "1.0",
        "benchmark_case_id": "page-1",
        "provider": provider,
        "model_revision": REVISION,
        "failure": {"reason": base.CREDENTIAL_IN_RESULT},
        "receipt": {"revision_attested": False},
    }


@pytest.mark.parametrize("provider", [C1, C3])
@pytest.mark.parametrize("revision", ["", "main", "G" * 40])
def test_an_unpinned_revision_refuses_before_any_call(
    provider: str, revision: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = _happy()
    with pytest.raises(RunnerUnavailable, match="revision"):
        _run(provider, server, monkeypatch, revision=revision)
    assert server.calls == []


@pytest.mark.parametrize("provider", [C1, C3])
def test_an_unsupported_page_type_is_a_page_refusal_before_any_call(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = _happy()
    with pytest.raises(PageRefused) as caught:
        _run(provider, server, monkeypatch, payload=_payload(b"x", "application/msword"))
    assert caught.value.reason == "page_content_type_unsupported" and server.calls == []


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"\x89PNG not an image", "page_image_unreadable"),
        (PAGE[: len(PAGE) // 2], "page_image_unreadable"),
        (_png((3000, 3000)), "page_over_pixel_cap"),
    ],
    ids=["not_an_image", "truncated", "over_pixel_cap"],
)
def test_c3_a_page_it_cannot_decode_or_that_is_too_large_is_refused_before_any_call(
    data: bytes, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = _happy()
    with pytest.raises(PageRefused) as caught:
        _run(C3, server, monkeypatch, payload=_payload(data))
    assert caught.value.reason == reason and server.calls == []


# --- C3: the two steps ---


def test_c3_layout_then_one_call_per_region_with_its_type_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _happy()
    out = _run(C3, server, monkeypatch)
    requests = [request for _, request, _ in server.calls]
    assert [_prompt(r) for r in requests] == [mineru_vlm.LAYOUT_PROMPT, TEXT, TABLE, FORMULA]
    assert _image(requests[0]).size == mineru_vlm.LAYOUT_SIZE
    assert [_image(r).size for r in requests[1:]] == [(100, 50)] * 3  # quarters of 200x100
    for request in requests:
        assert request["model"] == SERVED[C3]
        assert request["skip_special_tokens"] is False
        assert request["vllm_xargs"] == {"no_repeat_ngram_size": 100}
        assert request["temperature"] == 0.01 and request["top_k"] == 1
    assert not list(VALIDATOR.iter_errors(out))
    assert out["text"] == "para\n\n<fcel>a<nl>\n\nx^2"  # the image region is not sent
    receipt = out["metrics"]["receipt"]
    assert receipt["config_sha256"] == vlm.config_sha256(RUNNER_CONFIGS[C3](revision=REVISION))
    assert receipt["revision_attested"] is True
    assert receipt["image_sha256"] == hashlib.sha256(PAGE).hexdigest()
    steps = receipt["steps"]
    assert [s["step"] for s in steps] == ["layout", "region", "region", "region"]
    assert [s.get("region_index") for s in steps] == [None, 0, 1, 3]
    assert _raw(steps[0]) == _chat(LAYOUT) and _raw(steps[3]) == _chat("x^2")
    assert all(s["revision_attested"] is True for s in steps)


def test_c3_a_rotated_region_is_cropped_then_turned(monkeypatch: pytest.MonkeyPatch) -> None:
    server = Server(_chat(_box(0, 0, 250, 1000, "text", "right")), [_chat("sideways")])
    out = _run(C3, server, monkeypatch)
    _, request, _ = server.calls[1]
    assert _image(request).size == (100, 50)  # a 50x100 crop, turned by 90 degrees
    assert out["metrics"]["receipt"]["steps"][1]["angle"] == 90


@pytest.mark.parametrize(
    "layout",
    [
        "Title: Annual report",
        _box(0, 0, 500, 500, "text") + "\nstray words",
        _box(500, 0, 500, 500, "text"),  # empty width
        _box(0, 600, 500, 500, "text"),  # bottom above top
        _box(0, 0, 1001, 500, "text"),
        _box(0, 0, 500, 500, "Text"),
        _box(0, 0, 500, 500, "text") + " trailing",
        "<|box_start|>0 0 500<|box_end|><|ref_start|>text<|ref_end|>",
    ],
)
def test_c3_a_layout_outside_the_grammar_is_a_failure_row_with_its_bytes(
    layout: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = Server(_chat(layout), [_chat("never sent")])
    out = _run(C3, server, monkeypatch)
    assert out["failure"] == {"reason": "layout_unparseable"} and len(server.calls) == 1
    assert _raw(out["receipt"]["steps"][0]) == _chat(layout)
    assert list(VALIDATOR.iter_errors(out))


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (_chat(LAYOUT, finish="length"), "layout_finish_reason_not_stop"),
        ((500, b'{"error": "boom"}'), "layout_http_500"),
        (_chat(LAYOUT, served=SERVED[C1]), "layout_served_model_differs"),
        (b"not json", "layout_malformed_response"),
    ],
)
def test_c3_a_failed_layout_is_a_failure_row_with_its_bytes(
    reply: Any, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = Server(reply)
    out = _run(C3, server, monkeypatch)
    raw = reply[1] if isinstance(reply, tuple) else reply
    assert out["failure"] == {"reason": reason} and len(server.calls) == 1
    assert _raw(out["receipt"]["steps"][0]) == raw
    assert out["receipt"]["revision_attested"] is False


@pytest.mark.parametrize(
    ("second", "reason"),
    [
        ((500, b"{}"), "region_http_500"),
        (_chat("cut", finish="length"), "region_finish_reason_not_stop"),
        (_chat("other", served=SERVED[C1]), "region_served_model_differs"),
        (_chat("   "), "region_empty_completion"),
        (RunnerUnavailable("benchmark provider is unavailable"), "region_provider_unavailable"),
    ],
)
def test_c3_a_failed_region_is_a_failure_row_that_keeps_the_layout_bytes(
    second: Any, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = Server(_chat(LAYOUT), [_chat("para"), second, _chat("never sent")])
    out = _run(C3, server, monkeypatch)
    assert out["failure"] == {"reason": reason}
    assert len(server.calls) == 3  # layout, first region, the failing one; nothing after
    steps = out["receipt"]["steps"]
    assert _raw(steps[0]) == _chat(LAYOUT) and _raw(steps[1]) == _chat("para")
    if isinstance(second, BaseException):
        assert len(steps) == 2
    else:
        failed = second[1] if isinstance(second, tuple) else second
        assert _raw(steps[2]) == failed and steps[2]["failure"] == reason.removeprefix("region_")
    assert list(VALIDATOR.iter_errors(out))


def test_c3_nothing_back_for_the_layout_is_unavailable_not_a_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = Server(RunnerUnavailable("benchmark provider is unavailable"))
    with pytest.raises(RunnerUnavailable):
        _run(C3, server, monkeypatch)


def test_c3_more_regions_than_the_bound_is_a_failure_row_before_step_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = "\n".join([_box(0, 0, 10, 10, "text")] * (mineru_vlm.MAX_REGIONS + 1))
    server = Server(_chat(layout))
    out = _run(C3, server, monkeypatch)
    assert out["failure"] == {"reason": "layout_too_many_regions"} and len(server.calls) == 1


def test_c3_a_page_with_only_image_regions_sends_none_and_is_a_failure_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = Server(_chat(_box(0, 0, 1000, 1000, "image")))
    out = _run(C3, server, monkeypatch)
    assert out["failure"] == {"reason": "no_text_regions"} and len(server.calls) == 1


def test_c3_config_names_the_server_processor_and_what_is_unverified() -> None:
    cfg = RUNNER_CONFIGS[C3](revision=REVISION)
    assert cfg["mode"] == "two_step"
    assert cfg["server_logits_processor"].startswith("mineru_vl_utils:MinerULogitsProcessor")
    assert "UNVERIFIED" in cfg["prompt_source"]
    assert cfg["layout_input_pixels"] == [1036, 1036]
    assert cfg["skipped_region_types"] == ["image"]
