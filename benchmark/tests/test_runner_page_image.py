"""Page-image runners (vLLM chat endpoints, Gemini, Mistral) against a fake transport only."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from benchmark.run_benchmark import parser_output_validator
from benchmark.runners import base, vlm
from benchmark.runners.base import RunnerUnavailable
from benchmark.runners.registry import EXTERNAL_RUNNERS, RUNNER_CONFIGS

ROOT = Path(__file__).resolve().parents[2]
REVISION = "a" * 40
IMAGE = b"\x89PNG fake page bytes"
VLLM = {
    "ovis_ocr2": "ATH-MaaS/OvisOCR2",
    "ovis_ocr3": "ATH-MaaS/OvisOCR3",
    "minicpm_ocr_1": "openbmb/MiniCPM-OCR-1.0",
    "nemotron_parse_3_5": "nvidia/Nemotron-3.5-Parse",
    "teleocr": "XingChen-AGI/TeleOCR",
    "xiaomi_ocr_0": "xiaomi-research/Xiaomi-OCR-0",
}
GEMINI = "gemini-4-hydrogen"
GEMINI_URL = f"https://gemini.example/v1beta/models/{GEMINI}:generateContent"
GEMINI_OPTIONS: dict[str, Any] = {
    "thinking_config": {"thinkingBudget": 1024},
    "media_resolution": "MEDIA_RESOLUTION_HIGH",
}
VALIDATOR = parser_output_validator(ROOT / "benchmark" / "manifest.yaml")


def _served(model: str) -> str:
    return f"{model}@{REVISION}"


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


def _chat(model: str, /, **over: Any) -> bytes:
    body = {
        "model": _served(model),
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
    if provider == "gemini_api":
        kwargs: dict[str, Any] = {"endpoint": GEMINI_URL, "allow_network": True, **GEMINI_OPTIONS}
    else:
        kwargs = {
            "endpoint": "https://vllm.example/v1/chat/completions",
            "revision": REVISION,
            "allow_network": True,
        }
    kwargs.update(kw)
    return EXTERNAL_RUNNERS[provider](_payload(), **kwargs)


def _text_part(request: dict[str, Any]) -> str:
    parts = request["messages"][0]["content"]
    return next(p["text"] for p in parts if p["type"] == "text")


def _storable(out: dict[str, Any]) -> bytes:
    # exactly what the screen runner does with a result, but stricter (no NaN)
    return json.dumps(
        out, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def test_registered() -> None:
    assert {*VLLM, "gemini_api", "mistral_ocr_4"} <= set(EXTERNAL_RUNNERS)
    assert {*VLLM, "gemini_api", "mistral_ocr_4"} <= set(RUNNER_CONFIGS)


@pytest.mark.parametrize(("provider", "model"), VLLM.items())
def test_vllm_request_shape_and_valid_result(provider: str, model: str, monkeypatch) -> None:
    transport = FakeTransport(200, _chat(model))
    out = _call(provider, transport, monkeypatch)
    config, request, _ = transport.calls[0]
    assert config.model_revision == REVISION and config.provider == provider
    # served-model-name is <repo>@<revision>, and the response echoed it
    assert request["model"] == _served(model) and request["temperature"] == 0.0
    parts = request["messages"][0]["content"]
    image = next(p for p in parts if p["type"] == "image_url")
    assert image["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(IMAGE).decode()
    receipt = out["metrics"]["receipt"]
    assert _text_part(request) == receipt["prompt"]
    assert not list(VALIDATOR.iter_errors(out))
    assert out["text"] == "# 안녕" and out["provider"] == provider
    assert receipt["model_revision"] == REVISION and receipt["generation"]["max_tokens"]
    assert receipt["image_sha256"] == hashlib.sha256(IMAGE).hexdigest()
    assert receipt["served_model_name"] == _served(model)
    assert receipt["revision_attested"] is True
    assert receipt["prompt_source"]
    # config_sha256 carries prompt, generation and served name; it is what the screen pins
    expected = vlm.config_sha256(RUNNER_CONFIGS[provider](revision=REVISION))
    assert receipt["config_sha256"] == expected


def test_each_candidate_carries_its_own_pinned_config() -> None:
    digests = {p: vlm.config_sha256(RUNNER_CONFIGS[p](revision=REVISION)) for p in VLLM}
    assert len(set(digests.values())) == len(VLLM)
    for provider in VLLM:
        other = vlm.config_sha256(RUNNER_CONFIGS[provider](revision="b" * 40))
        assert other != digests[provider]  # the served name names the revision


def test_ovis2_reuses_the_vendor_prompt_and_limits_of_the_stage2_runner() -> None:
    import ovisocr2_stage2  # benchmark/runpod_eval is on the configured pythonpath

    cfg = RUNNER_CONFIGS["ovis_ocr2"](revision=REVISION)
    assert cfg["prompt"] == ovisocr2_stage2.VENDOR_PROMPT
    gen = cfg["generation"]
    assert gen["max_tokens"] == 16_384 and gen["temperature"] == 0.0
    assert gen["mm_processor_kwargs"]["images_kwargs"] == {
        "min_pixels": 448 * 448,
        "max_pixels": 2_880 * 2_880,
    }
    assert gen["chat_template_kwargs"] == {"enable_thinking": False}


def test_card_prescribed_prompts_are_used_and_quoted() -> None:
    nemotron = RUNNER_CONFIGS["nemotron_parse_3_5"](revision=REVISION)
    assert nemotron["prompt"] == (
        "</s><s><predict_bbox><predict_classes><output_markdown><predict_text_in_pic>"
    )
    assert nemotron["content_order"] == "text_first"
    assert nemotron["generation"] == {
        "temperature": 0,
        "max_tokens": 8744,
        "top_k": 1,
        "repetition_penalty": 1.1,
        "skip_special_tokens": False,
    }
    ovis3 = RUNNER_CONFIGS["ovis_ocr3"](revision=REVISION)
    # prompts/document_markdown.txt at 5b252386, fetched as public metadata (receipt kept)
    assert (
        hashlib.sha256(ovis3["prompt"].encode()).hexdigest()
        == "dbf31d5899a86047ce0cd4d0d12cdc5616df1bea5d9a600b823098442c32997c"
    )
    xiaomi = RUNNER_CONFIGS["xiaomi_ocr_0"](revision=REVISION)
    assert xiaomi["prompt"].startswith("Extract all information from the main body")
    assert xiaomi["generation"]["max_tokens"] == 4096
    assert RUNNER_CONFIGS["minicpm_ocr_1"](revision=REVISION)["prompt"] == "Text Recognition:"
    for provider in ("nemotron_parse_3_5", "ovis_ocr3", "xiaomi_ocr_0", "minicpm_ocr_1"):
        assert RUNNER_CONFIGS[provider](revision=REVISION)["prompt_source"].startswith("card")
    tele = RUNNER_CONFIGS["teleocr"](revision=REVISION)
    assert tele["prompt"] == vlm.GENERIC_PROMPT
    assert tele["prompt_source"].startswith("generic")


def test_nemotron_sends_the_task_prompt_before_the_image(monkeypatch) -> None:
    transport = FakeTransport(200, _chat(VLLM["nemotron_parse_3_5"]))
    _call("nemotron_parse_3_5", transport, monkeypatch)
    _, request, _ = transport.calls[0]
    kinds = [p["type"] for p in request["messages"][0]["content"]]
    assert kinds == ["text", "image_url"]
    assert request["top_k"] == 1 and request["skip_special_tokens"] is False


@pytest.mark.parametrize("served", ["ATH-MaaS/OvisOCR2", _served("ATH-MaaS/OvisOCR3"), "x@y"])
def test_a_response_that_does_not_name_the_pinned_revision_is_refused(
    served: str, monkeypatch
) -> None:
    raw = _chat(VLLM["ovis_ocr2"], model=served)
    out = _call("ovis_ocr2", FakeTransport(200, raw), monkeypatch)
    assert out["failure"]["reason"] == "served_model_differs"
    assert out["receipt"]["revision_attested"] is False
    assert base64.b64decode(out["receipt"]["raw_response_b64"]) == raw


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
    render = {"renderer": "pypdfium2", "render_scale": vlm.RENDER_SCALE, "renderer_version": "x"}

    def fake_render(d: bytes, i: int, s: float) -> tuple[bytes, dict[str, Any]]:
        seen.append((d, i, s))
        return IMAGE, render

    monkeypatch.setattr(vlm, "render_pdf_page", fake_render)
    payload = _payload()
    payload["page_index"] = 3
    payload["source"]["content_type"] = "application/pdf"
    monkeypatch.setattr(vlm, "post_bytes", FakeTransport(200, _chat(VLLM["teleocr"])))
    out = EXTERNAL_RUNNERS["teleocr"](
        payload, endpoint="https://v.example/x", revision=REVISION, allow_network=True
    )
    assert seen == [(IMAGE, 3, vlm.RENDER_SCALE)]
    assert out["metrics"]["receipt"]["image_mime"] == "image/png"
    assert out["metrics"]["receipt"]["render"] == render


def _real_pdf(width: float, height: float) -> bytes:
    import pypdfium2  # type: ignore[import-untyped]

    pdf = pypdfium2.PdfDocument.new()
    try:
        pdf.new_page(width, height).close()
        buffer = io.BytesIO()
        pdf.save(buffer)
        return buffer.getvalue()
    finally:
        pdf.close()


def test_render_receipt_names_scale_and_renderer_version() -> None:
    import pypdfium2.version as v  # type: ignore[import-untyped]

    png, render = vlm.render_pdf_page(_real_pdf(612, 792), 0, vlm.RENDER_SCALE)
    assert png.startswith(b"\x89PNG")
    assert render["render_scale"] == vlm.RENDER_SCALE
    assert render["renderer"] == "pypdfium2"
    assert render["renderer_version"] == str(v.PYPDFIUM_INFO)
    assert render["pdfium_version"] == str(v.PDFIUM_INFO)
    assert render["rendered_pixels"] == [1224, 1584]


class _Tracked:
    def __init__(self, log: list[str], name: str) -> None:
        self.log, self.name = log, name

    def close(self) -> None:
        self.log.append(self.name)


def _fake_pypdfium2(monkeypatch, size: tuple[float, float], log: list[str]) -> None:
    rendered = (int(size[0] * 2), int(size[1] * 2)) if all(map(math.isfinite, size)) else (0, 0)

    class Image(_Tracked):
        size = rendered

        def save(self, buffer: io.BytesIO, **_: Any) -> None:
            buffer.write(IMAGE)

    class Bitmap(_Tracked):
        def to_pil(self) -> Image:
            return Image(log, "image")

    class Page(_Tracked):
        def get_size(self) -> tuple[float, float]:
            return size

        def render(self, **_: Any) -> Bitmap:
            log.append("render")
            return Bitmap(log, "bitmap")

    class Doc(_Tracked):
        def __len__(self) -> int:
            return 1

        def __getitem__(self, _i: int) -> Page:
            return Page(log, "page")

    class PdfiumError(Exception):
        pass

    def open_doc(data: bytes) -> Doc:
        if data == b"garbage":
            raise PdfiumError("Failed to load document")
        return Doc(log, "doc")

    version = types.SimpleNamespace(PYPDFIUM_INFO="9.9.9", PDFIUM_INFO="1@test")
    fake = types.SimpleNamespace(PdfDocument=open_doc, PdfiumError=PdfiumError, version=version)
    monkeypatch.setitem(sys.modules, "pypdfium2", fake)
    monkeypatch.setitem(sys.modules, "pypdfium2.version", version)


def test_oversized_pdf_page_is_a_page_refusal_before_rendering_and_closes_what_it_opened(
    monkeypatch,
) -> None:
    log: list[str] = []
    _fake_pypdfium2(monkeypatch, (14400.0, 14400.0), log)
    with pytest.raises(vlm.PageRefused) as caught:
        vlm.render_pdf_page(b"%PDF", 0, vlm.RENDER_SCALE)
    assert caught.value.reason == "page_over_pixel_cap"
    assert not isinstance(caught.value, RunnerUnavailable)  # not provider_unavailable
    assert "render" not in log and log == ["page", "doc"]


def test_rendered_page_closes_bitmap_page_and_document(monkeypatch) -> None:
    log: list[str] = []
    _fake_pypdfium2(monkeypatch, (612.0, 792.0), log)
    png, render = vlm.render_pdf_page(b"%PDF", 0, vlm.RENDER_SCALE)
    assert png == IMAGE and render["renderer_version"] == "9.9.9"
    assert log == ["render", "image", "bitmap", "page", "doc"]


@pytest.mark.parametrize(
    ("data", "index", "size", "reason"),
    [
        (b"garbage", 0, (612.0, 792.0), "page_pdf_unreadable"),
        (b"%PDF", 1, (612.0, 792.0), "page_index_out_of_range"),
        (b"%PDF", -1, (612.0, 792.0), "page_index_out_of_range"),
        (b"%PDF", 0, (float("nan"), 792.0), "page_size_invalid"),
        (b"%PDF", 0, (0.0, 792.0), "page_size_invalid"),
        (b"%PDF", 0, (float("inf"), 1.0), "page_size_invalid"),
    ],
)
def test_unrenderable_pages_are_page_refusals_with_their_own_reason(
    data: bytes, index: int, size: tuple[float, float], reason: str, monkeypatch
) -> None:
    log: list[str] = []
    _fake_pypdfium2(monkeypatch, size, log)
    with pytest.raises(vlm.PageRefused) as caught:
        vlm.render_pdf_page(data, index, vlm.RENDER_SCALE)
    assert caught.value.reason == reason
    assert "render" not in log
    if data != b"garbage":
        assert log[-1] == "doc"


def test_unsupported_source_type_is_a_page_refusal(monkeypatch) -> None:
    transport = FakeTransport(200, _chat(VLLM["teleocr"]))
    monkeypatch.setattr(vlm, "post_bytes", transport)
    payload = _payload()
    payload["source"]["content_type"] = "text/plain"
    with pytest.raises(vlm.PageRefused, match="page_content_type_unsupported"):
        EXTERNAL_RUNNERS["teleocr"](
            payload, endpoint="https://v.example/x", revision=REVISION, allow_network=True
        )
    assert transport.calls == []


def _raw_pdf(mediabox: str, extra: str = "") -> bytes:
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [{mediabox}] {extra}>>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.7\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{body}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


_COORD = st.one_of(
    st.integers(-200_000, 200_000).map(str),
    st.sampled_from(["1e30", "-1e30", "0", "1441", "1440", "nan", "x", ""]),
)
_EXTRA = st.sampled_from(
    [
        "",
        "/Rotate 90 ",
        "/Rotate 45 ",
        "/UserUnit 75 ",
        "/CropBox [0 0 612 792] ",
        "/CropBox [0 0 14400 14400] ",
        "/MediaBox 5 ",
    ]
)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(_COORD, min_size=4, max_size=4), _EXTRA, st.integers(-2, 2))
def test_any_hostile_page_box_renders_under_the_cap_or_is_a_page_refusal(
    box: list[str], extra: str, index: int
) -> None:
    from PIL import Image

    try:
        png, render = vlm.render_pdf_page(_raw_pdf(" ".join(box), extra), index, vlm.RENDER_SCALE)
    except vlm.PageRefused as refused:
        assert refused.reason.startswith("page_")
        return
    with Image.open(io.BytesIO(png)) as image:
        assert image.size[0] * image.size[1] <= vlm.MAX_RENDER_PIXELS
        assert list(image.size) == render["rendered_pixels"]


@settings(max_examples=60, deadline=None)
@given(st.binary(max_size=512))
def test_any_bytes_as_a_pdf_render_or_refuse(data: bytes) -> None:
    try:
        vlm.render_pdf_page(b"%PDF-1.7\n" + data, 0, vlm.RENDER_SCALE)
    except vlm.PageRefused as refused:
        assert refused.reason.startswith("page_")


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
    errors = list(VALIDATOR.iter_errors(out))
    assert errors  # the screen runner records contract_failed and keeps the raw output


def test_refusal_reasons_never_echo_provider_values(monkeypatch) -> None:
    secret = "PROVIDER-CONTROLLED-" + "x" * 5000
    raw = _chat(VLLM["ovis_ocr2"], choices=[{"finish_reason": secret, "message": {}}])
    out = _call("ovis_ocr2", FakeTransport(200, raw), monkeypatch)
    assert out["failure"]["reason"] == "finish_reason_not_stop"


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


def test_lone_surrogate_completion_is_a_failure_row_not_an_unstorable_result(monkeypatch) -> None:
    raw = _chat(VLLM["ovis_ocr2"]).replace("# 안녕".encode(), b"\\ud800")
    out = _call("ovis_ocr2", FakeTransport(200, raw), monkeypatch)
    assert "failure" in out
    _storable(out)


def test_usage_is_flattened_to_finite_numbers(monkeypatch) -> None:
    usage = b'{"prompt_tokens": 7, "d": {"x": [[[1]]]}, "n": NaN, "b": true, "s": "x"}'
    raw = _chat(VLLM["ovis_ocr2"]).replace(b'{"completion_tokens": 3}', usage)
    out = _call("ovis_ocr2", FakeTransport(200, raw), monkeypatch)
    assert out["metrics"]["receipt"]["usage"] == {"prompt_tokens": 7}
    _storable(out)


_JSON = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats()
    | st.text(alphabet=st.characters(blacklist_categories=()), max_size=8),
    lambda inner: (
        st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=6), inner, max_size=3)
    ),
    max_leaves=12,
)


def _maybe(valid: Any) -> st.SearchStrategy[Any]:
    return st.one_of(st.just(valid), _JSON)


@st.composite
def _chat_responses(draw: st.DrawFn) -> bytes:
    content = draw(_maybe("# page"))
    choice = draw(
        _maybe(
            {"finish_reason": draw(_maybe("stop")), "message": draw(_maybe({"content": content}))}
        )
    )
    body = draw(
        _maybe(
            {
                "model": draw(_maybe(_served(VLLM["ovis_ocr2"]))),
                "choices": draw(_maybe([choice])),
                "usage": draw(_JSON),
            }
        )
    )
    return json.dumps(body, ensure_ascii=draw(st.booleans())).encode("utf-8", "surrogatepass")


@st.composite
def _gemini_responses(draw: st.DrawFn) -> bytes:
    part = draw(_maybe({"text": draw(_maybe("hello")), "thought": draw(_maybe(False))}))
    candidate = draw(
        _maybe({"finishReason": draw(_maybe("STOP")), "content": draw(_maybe({"parts": [part]}))})
    )
    body = draw(
        _maybe(
            {
                "modelVersion": draw(_maybe(GEMINI)),
                "promptFeedback": draw(_JSON),
                "candidates": draw(_maybe([candidate])),
                "usageMetadata": draw(_JSON),
            }
        )
    )
    return json.dumps(body, ensure_ascii=draw(st.booleans())).encode("utf-8", "surrogatepass")


def _check_result(out: dict[str, Any], raw: bytes) -> None:
    _storable(out)  # never a result the screen cannot serialise
    if "failure" in out:
        assert base64.b64decode(out["receipt"]["raw_response_b64"]) == raw
        assert out["failure"]["reason"] in vlm.REFUSAL_REASONS
        assert out["receipt"]["revision_attested"] is False
    else:
        assert isinstance(out["text"], str) and out["text"].strip()
        assert not list(VALIDATOR.iter_errors(out))


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.one_of(_chat_responses(), st.binary(max_size=64)))
def test_any_vllm_response_yields_a_storable_result_with_raw_kept(raw: bytes) -> None:
    with pytest.MonkeyPatch.context() as mp:
        out = _call("ovis_ocr2", FakeTransport(200, raw), mp)
    _check_result(out, raw)


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.one_of(_gemini_responses(), st.binary(max_size=64)))
def test_any_gemini_response_yields_a_storable_result_with_raw_kept(raw: bytes) -> None:
    with pytest.MonkeyPatch.context() as mp:
        out = _call("gemini_api", FakeTransport(200, raw), mp)
    _check_result(out, raw)
    if "failure" not in out:
        assert out["metrics"]["receipt"]["revision_attested"] is False


def test_transport_failure_is_unavailable_not_a_fallback(monkeypatch) -> None:
    def down(*_a: Any, **_k: Any) -> Any:
        raise RunnerUnavailable("benchmark provider is unavailable")

    monkeypatch.setattr(vlm, "post_bytes", down)
    with pytest.raises(RunnerUnavailable):
        EXTERNAL_RUNNERS["teleocr"](
            _payload(), endpoint="https://v.example/x", revision=REVISION, allow_network=True
        )


@pytest.mark.parametrize(
    ("provider", "endpoint"),
    [
        ("gemini_api", GEMINI_URL + "?key=SECRET"),
        ("gemini_api", GEMINI_URL + "#SECRET"),
        ("gemini_api", f"https://u:SECRET@gemini.example/v1beta/models/{GEMINI}:generateContent"),
        ("ovis_ocr2", "https://vllm.example/v1/chat/completions?token=SECRET"),
        ("teleocr", "https://SECRET@vllm.example/v1/chat/completions"),
    ],
)
def test_an_endpoint_that_could_carry_a_credential_is_refused_before_any_call(
    provider: str, endpoint: str, monkeypatch
) -> None:
    raw = _gemini() if provider == "gemini_api" else _chat(VLLM.get(provider, ""))
    transport = FakeTransport(200, raw)
    with pytest.raises(RunnerUnavailable) as caught:
        _call(provider, transport, monkeypatch, endpoint=endpoint)
    assert transport.calls == []
    assert "SECRET" not in str(caught.value)


def test_gemini_request_shape_and_key_stays_out_of_the_record(monkeypatch) -> None:
    transport = FakeTransport(200, _gemini(usageMetadata={"totalTokenCount": 9}))
    out = _call("gemini_api", transport, monkeypatch)
    _, request, headers = transport.calls[0]
    assert headers["x-goog-api-key"] == "test-key-not-real"
    inline = request["contents"][0]["parts"][0]["inline_data"]
    assert inline["mime_type"] == "image/png" and base64.b64decode(inline["data"]) == IMAGE
    generation = request["generationConfig"]
    assert generation["temperature"] == 0.0
    assert generation["thinkingConfig"] == {"thinkingBudget": 1024}
    assert generation["mediaResolution"] == "MEDIA_RESOLUTION_HIGH"
    receipt = out["metrics"]["receipt"]
    assert receipt["model"] == GEMINI and out["model_revision"] == GEMINI
    assert receipt["generation"] == generation
    assert receipt["usage"] == {"totalTokenCount": 9}
    assert receipt["revision_attested"] is False  # a hosted id names no weights revision
    assert receipt["config_sha256"] == vlm.config_sha256(
        RUNNER_CONFIGS["gemini_api"](model=GEMINI, **GEMINI_OPTIONS)
    )
    assert "test-key-not-real" not in json.dumps(out)
    assert not list(VALIDATOR.iter_errors(out))


@pytest.mark.parametrize(
    "options",
    [
        {"media_resolution": "MEDIA_RESOLUTION_HIGH"},
        {"thinking_config": {"thinkingBudget": 1024}},
        {"thinking_config": {}, "media_resolution": "MEDIA_RESOLUTION_HIGH"},
        {"thinking_config": {"thinkingBudget": -1}, "media_resolution": "MEDIA_RESOLUTION_HIGH"},
        {"thinking_config": {"thinkingBudget": True}, "media_resolution": "MEDIA_RESOLUTION_HIGH"},
        {"thinking_config": {"thinkingBudget": 10**9}, "media_resolution": "MEDIA_RESOLUTION_HIGH"},
        {
            "thinking_config": {"thinkingBudget": 8, "thinkingLevel": "low"},
            "media_resolution": "MEDIA_RESOLUTION_HIGH",
        },
        {"thinking_config": {"unknown": 1}, "media_resolution": "MEDIA_RESOLUTION_HIGH"},
        {"thinking_config": {"thinkingBudget": 8}, "media_resolution": "high"},
        {
            "thinking_config": {"thinkingBudget": 8},
            "media_resolution": "MEDIA_RESOLUTION_UNSPECIFIED",
        },
    ],
)
def test_gemini_requires_bounded_thinking_and_an_explicit_media_resolution(
    options: dict[str, Any], monkeypatch
) -> None:
    transport = FakeTransport(200, _gemini())
    monkeypatch.setattr(vlm, "post_bytes", transport)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    with pytest.raises(RunnerUnavailable):
        EXTERNAL_RUNNERS["gemini_api"](
            _payload(), endpoint=GEMINI_URL, allow_network=True, **options
        )
    assert transport.calls == []


def test_gemini_thinking_level_is_an_accepted_bound(monkeypatch) -> None:
    transport = FakeTransport(200, _gemini())
    out = _call("gemini_api", transport, monkeypatch, thinking_config={"thinkingLevel": "low"})
    assert out["metrics"]["receipt"]["generation"]["thinkingConfig"] == {"thinkingLevel": "low"}


def test_gemini_thought_parts_are_not_transcription(monkeypatch) -> None:
    parts = [{"text": "let me think", "thought": True}, {"text": "page text"}]
    raw = _gemini(candidates=[{"finishReason": "STOP", "content": {"parts": parts}}])
    out = _call("gemini_api", FakeTransport(200, raw), monkeypatch)
    assert out["text"] == "page text"
    only_thought = _gemini(candidates=[{"finishReason": "STOP", "content": {"parts": [parts[0]]}}])
    out = _call("gemini_api", FakeTransport(200, only_thought), monkeypatch)
    assert out["failure"]["reason"] == "empty_completion"


def test_gemini_refuses_a_revision_it_cannot_mean(monkeypatch) -> None:
    transport = FakeTransport(200, _gemini())
    with pytest.raises(RunnerUnavailable, match="revision"):
        _call("gemini_api", transport, monkeypatch, revision=REVISION)
    assert transport.calls == []


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
            _payload(), endpoint=endpoint, allow_network=True, **GEMINI_OPTIONS
        )
    assert transport.calls == []


def test_gemini_explicit_alias_parameter_refused_and_endpoint_must_agree(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    run = EXTERNAL_RUNNERS["gemini_api"]
    with pytest.raises(RunnerUnavailable, match="alias"):
        run(
            _payload(),
            endpoint=GEMINI_URL,
            allow_network=True,
            model="gemini-flash-latest",
            **GEMINI_OPTIONS,
        )
    with pytest.raises(RunnerUnavailable, match="does not name"):
        run(
            _payload(),
            endpoint=GEMINI_URL,
            allow_network=True,
            model="gemini-3.9-pro",
            **GEMINI_OPTIONS,
        )


def test_gemini_needs_a_key(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RunnerUnavailable, match="GEMINI_API_KEY"):
        EXTERNAL_RUNNERS["gemini_api"](
            _payload(), endpoint=GEMINI_URL, allow_network=True, **GEMINI_OPTIONS
        )


@pytest.mark.parametrize(
    "raw",
    [
        _gemini(modelVersion="gemini-4-hydrogen-002"),  # silent redirect of an alias
        _gemini(candidates=[{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]),
        _gemini(promptFeedback={"blockReason": "SAFETY"}),
        b'{"candidates": []}',
    ],
)
def test_gemini_bad_response_is_a_failure_row(raw: bytes, monkeypatch) -> None:
    out = _call("gemini_api", FakeTransport(200, raw), monkeypatch)
    assert "failure" in out and base64.b64decode(out["receipt"]["raw_response_b64"]) == raw


# --- Mistral OCR: the model id is required; the retired id and aliases are refused ---


def _mistral_result(model: str) -> bytes:
    return json.dumps(
        {
            "schema_version": "1.0",
            "benchmark_case_id": "page-1",
            "provider": "mistral_ocr_4",
            "model_revision": model,
            "text": "x",
        }
    ).encode()


@pytest.mark.parametrize(
    "model",
    [
        None,
        "",
        "mistral-ocr-4-0",
        "mistral-ocr-latest",
        "mistral-ocr-4",
        "mistral-ocr-4-1-latest",
        "labs-mistral-ocr-4-1",
        "Mistral-OCR-4-1",
    ],
)
def test_mistral_refuses_a_missing_retired_or_alias_model_before_any_call(
    model: str | None, monkeypatch
) -> None:
    transport = FakeTransport(200, _mistral_result("mistral-ocr-4-1"))
    monkeypatch.setattr(base, "post_bytes", transport)
    kwargs: dict[str, Any] = {"endpoint": "https://m.example/x", "allow_network": True}
    if model is not None:
        kwargs["model"] = model
    with pytest.raises(RunnerUnavailable):
        EXTERNAL_RUNNERS["mistral_ocr_4"](_payload(), **kwargs)
    assert transport.calls == []


def test_mistral_sends_the_pinned_model_id(monkeypatch) -> None:
    transport = FakeTransport(200, _mistral_result("mistral-ocr-4-1"))
    monkeypatch.setattr(base, "post_bytes", transport)
    out = EXTERNAL_RUNNERS["mistral_ocr_4"](
        _payload(), endpoint="https://m.example/x", allow_network=True, model="mistral-ocr-4-1"
    )
    config, _, headers = transport.calls[0]
    assert config.model_revision == "mistral-ocr-4-1"
    assert headers["X-AKC-Model-Revision"] == "mistral-ocr-4-1"
    assert out["model_revision"] == "mistral-ocr-4-1"
    with pytest.raises(RunnerUnavailable, match="revision"):
        EXTERNAL_RUNNERS["mistral_ocr_4"](
            _payload(),
            endpoint="https://m.example/x",
            allow_network=True,
            model="mistral-ocr-4-1",
            revision=REVISION,
        )


# --- screen.Candidate: API candidates are pinned by model id; configs are bound ---


def test_screen_candidate_binds_config_sha256_and_takes_an_api_model() -> None:
    from benchmark.screen.run_screen import Candidate
    from benchmark.v6.contracts import ContractError

    img = "sha256:" + "1" * 64
    good = vlm.config_sha256(RUNNER_CONFIGS["ovis_ocr3"](revision=REVISION))
    Candidate("c7", "ovis_ocr3", REVISION, img, good).validate()
    with pytest.raises(ContractError, match="config_sha256"):
        Candidate("c7", "ovis_ocr3", REVISION, img, "sha256:" + "2" * 64).validate()
    gemini = vlm.config_sha256(RUNNER_CONFIGS["gemini_api"](model=GEMINI, **GEMINI_OPTIONS))
    api = Candidate(
        "h2", "gemini_api", "", img, gemini, model=GEMINI, runner_options=GEMINI_OPTIONS
    )
    api.validate()
    with pytest.raises(ContractError):  # thinking/media resolution are part of the pin
        Candidate("h2", "gemini_api", "", img, gemini, model=GEMINI).validate()
    with pytest.raises(ContractError):  # a vLLM candidate has no model field
        Candidate("c7", "ovis_ocr3", REVISION, img, good, model="ATH-MaaS/OvisOCR3").validate()
    with pytest.raises(ContractError):  # a non-API, non-config provider still needs hex
        Candidate("c0", "mineru", "", img, "sha256:" + "2" * 64).validate()


def test_screen_records_a_page_refusal_with_its_own_reason(tmp_path: Path) -> None:
    from benchmark.screen.manifest import HoldoutGuard
    from benchmark.screen.run_screen import Candidate, run_screen

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "d.pdf").write_bytes(b"%PDF")
    digest = "sha256:" + hashlib.sha256(b"%PDF").hexdigest()
    docs = [
        {
            "doc_id": "d.pdf",
            "source_sha256": digest,
            "page_count": 1,
            "stratum": "s",
            "language": "ko",
            "document_class": "c",
            "split": "dev",
        }
    ]
    guard = HoldoutGuard(
        {"documents": docs, "manifest_sha256": "sha256:" + "0" * 64}, tmp_path / "l"
    )
    cfg = vlm.config_sha256(RUNNER_CONFIGS["teleocr"](revision=REVISION))
    cand = Candidate(
        "c6", "teleocr", REVISION, "sha256:" + "1" * 64, cfg, "https://v.example/x", True
    )

    def refuse(*_a: Any) -> dict[str, Any]:
        raise vlm.PageRefused("page_over_pixel_cap")

    records = run_screen(
        guard=guard,
        split="dev",
        purpose="tune",
        candidate=cand,
        corpus_root=corpus,
        gold={"d.pdf#0": {"text": "x", "blocks": [], "critical_fields": []}},
        raw_dir=tmp_path / "raw",
        records_path=tmp_path / "r.jsonl",
        call=refuse,
    )
    assert records[0]["hard_failures"] == ["page_over_pixel_cap"]
    assert records[0]["provider_error_type"] == "benchmark.runners.vlm.PageRefused"
    assert records[0]["accepted"] is False and records[0]["raw_sha256"] is None


def test_screen_call_passes_model_and_runner_options(tmp_path: Path, monkeypatch) -> None:
    from benchmark.screen import run_screen as rs

    seen: dict[str, Any] = {}

    def fake(payload: dict[str, Any], **kw: Any) -> dict[str, Any]:
        seen.update(kw)
        return {}

    monkeypatch.setitem(rs.EXTERNAL_RUNNERS, "gemini_api", fake)  # type: ignore[index]
    monkeypatch.setattr(rs, "build_provider_payload", lambda case, corpus_root: {})
    gemini = vlm.config_sha256(RUNNER_CONFIGS["gemini_api"](model=GEMINI, **GEMINI_OPTIONS))
    cand = rs.Candidate(
        "h2", "gemini_api", "", "sha256:" + "1" * 64, gemini, GEMINI_URL, True,
        model=GEMINI, runner_options=GEMINI_OPTIONS,
    )  # fmt: skip
    rs._call(cand, {}, tmp_path)
    assert seen == {
        "endpoint": GEMINI_URL,
        "revision": "",
        "allow_network": True,
        "model": GEMINI,
        **GEMINI_OPTIONS,
    }
