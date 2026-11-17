"""Page-image runners (vLLM chat endpoints, Gemini, Mistral) against a fake transport only."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import logging
import math
import secrets
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


def _marker() -> str:
    """A key-shaped value made in this process; never a real credential."""
    return "AIza" + secrets.token_urlsafe(30)


KEY = _marker()


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
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
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


def _fake_pypdfium2(
    monkeypatch, size: tuple[float, float], log: list[str], broken: str = ""
) -> None:
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
            if broken == "render":
                raise PdfiumError("Failed to render page")
            return Bitmap(log, "bitmap")

    class Doc(_Tracked):
        def __len__(self) -> int:
            return 1

        def __getitem__(self, _i: int) -> Page:
            if broken == "page":
                raise PdfiumError("Failed to load page")
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


@pytest.mark.parametrize("broken", ["page", "render"])
def test_a_page_pdfium_cannot_load_or_render_is_a_page_refusal(
    broken: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    log: list[str] = []
    _fake_pypdfium2(monkeypatch, (612.0, 792.0), log, broken)
    with pytest.raises(vlm.PageRefused) as caught:
        vlm.render_pdf_page(b"%PDF", 0, vlm.RENDER_SCALE)
    assert caught.value.reason == "page_unrenderable"
    assert log[-1] == "doc" and ("page" in log) == (broken == "render")


def test_a_page_inside_a_lying_count_is_a_page_refusal_on_the_real_renderer() -> None:
    # /Count says 5, /Kids names a page that exists and one that does not
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 9 0 R] /Count 5 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    assert vlm.render_pdf_page(out, 0, vlm.RENDER_SCALE)[1]["rendered_pixels"] == [200, 200]
    for index in (1, 3):  # inside the declared count, but pdfium cannot load the page
        with pytest.raises(vlm.PageRefused) as caught:
            vlm.render_pdf_page(out, index, vlm.RENDER_SCALE)
        assert caught.value.reason == "page_unrenderable"


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
        ("gemini_api", GEMINI_URL + "?key=" + KEY),
        ("gemini_api", GEMINI_URL + "#" + KEY),
        ("gemini_api", f"https://u:{KEY}@gemini.example/v1beta/models/{GEMINI}:generateContent"),
        ("ovis_ocr2", "https://vllm.example/v1/chat/completions?token=" + KEY),
        ("teleocr", f"https://{KEY}@vllm.example/v1/chat/completions"),
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
    assert KEY not in str(caught.value)


def test_gemini_request_shape_and_key_stays_out_of_the_record(monkeypatch) -> None:
    transport = FakeTransport(200, _gemini(usageMetadata={"totalTokenCount": 9}))
    out = _call("gemini_api", transport, monkeypatch)
    _, request, headers = transport.calls[0]
    assert headers["x-goog-api-key"] == KEY
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
    assert KEY not in json.dumps(out)
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
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    with pytest.raises(RunnerUnavailable):
        EXTERNAL_RUNNERS["gemini_api"](
            _payload(), endpoint=GEMINI_URL, allow_network=True, **options
        )
    assert transport.calls == []


def test_gemini_thinking_level_is_an_accepted_bound(monkeypatch) -> None:
    transport = FakeTransport(200, _gemini())
    out = _call("gemini_api", transport, monkeypatch, thinking_config={"thinkingLevel": "LOW"})
    assert out["metrics"]["receipt"]["generation"]["thinkingConfig"] == {"thinkingLevel": "LOW"}


def test_gemini_thought_parts_are_not_transcription(monkeypatch) -> None:
    parts = [{"text": "let me think", "thought": True}, {"text": "page text"}]
    raw = _gemini(candidates=[{"finishReason": "STOP", "content": {"parts": parts}}])
    out = _call("gemini_api", FakeTransport(200, raw), monkeypatch)
    assert out["text"] == "page text"
    only_thought = _gemini(candidates=[{"finishReason": "STOP", "content": {"parts": [parts[0]]}}])
    out = _call("gemini_api", FakeTransport(200, only_thought), monkeypatch)
    assert out["failure"]["reason"] == "empty_completion"


@pytest.mark.parametrize("thought", ["true", 1, 0, None, [], {}])
def test_gemini_a_thought_field_that_is_not_a_bool_is_malformed(
    thought: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    parts = [{"text": "a", "thought": thought}, {"text": "b"}]
    raw = _gemini(candidates=[{"finishReason": "STOP", "content": {"parts": parts}}])
    out = _call("gemini_api", FakeTransport(200, raw), monkeypatch)
    assert out["failure"]["reason"] == "malformed_response"


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
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    with pytest.raises(RunnerUnavailable):
        EXTERNAL_RUNNERS["gemini_api"](
            _payload(), endpoint=endpoint, allow_network=True, **GEMINI_OPTIONS
        )
    assert transport.calls == []


def test_gemini_explicit_alias_parameter_refused_and_endpoint_must_agree(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
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


MISTRAL = "mistral-ocr-4-1"
MISTRAL_URL = "https://api.mistral.example/v1/ocr"


def _mistral_result(model: str | None, **over: Any) -> bytes:
    body: dict[str, Any] = {
        "model": model,
        "pages": [{"index": 0, "markdown": "x"}],
        "usage_info": {"pages_processed": 1, "doc_size_bytes": 10},
    }
    if model is None:
        del body["model"]
    body.update(over)
    return json.dumps(body).encode()


def _mistral(transport: Any, monkeypatch: pytest.MonkeyPatch, **kw: Any) -> dict[str, Any]:
    monkeypatch.setattr(vlm, "post_bytes", transport)
    monkeypatch.setenv("MISTRAL_API_KEY", KEY)
    kwargs: dict[str, Any] = {"endpoint": MISTRAL_URL, "allow_network": True, "model": MISTRAL}
    kwargs.update(kw)
    return EXTERNAL_RUNNERS["mistral_ocr_4"](_payload(), **kwargs)


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
        "mistral-ocr-04-0",
        "mistral-ocr-4-00",
        "mistral-ocr-04-1",
        "mistral-ocr-4-01",
        "mistral-ocr-4-2",
        "mistral-ocr-9-9",
        "mistral-ocr-4-1 ",
    ],
)
def test_mistral_refuses_a_missing_retired_or_alias_model_before_any_call(
    model: str | None, monkeypatch
) -> None:
    transport = FakeTransport(200, _mistral_result(MISTRAL))
    with pytest.raises(RunnerUnavailable):
        _mistral(transport, monkeypatch, model=model)
    assert transport.calls == []


def test_mistral_sends_the_pinned_model_id(monkeypatch) -> None:
    transport = FakeTransport(200, _mistral_result(MISTRAL))
    out = _mistral(transport, monkeypatch)
    config, request, _ = transport.calls[0]
    assert config.model_revision == MISTRAL and request["model"] == MISTRAL
    assert out["model_revision"] == MISTRAL and out["text"] == "x"
    with pytest.raises(RunnerUnavailable, match="revision"):
        _mistral(transport, monkeypatch, revision=REVISION)


# --- WO-D10-0D item 3: Mistral on its own API (tests 10-14) ---


def test_d0d_10_mistral_sends_the_page_image_unchanged_with_the_key_in_the_header_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeTransport(200, _mistral_result(MISTRAL))
    out = _mistral(transport, monkeypatch)
    _, request, headers = transport.calls[0]
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert set(headers) == {"Authorization", "Content-Type"}
    assert request["document"]["type"] == "image_url"
    prefix, data = request["document"]["image_url"].split(",", 1)
    mime, image, _ = vlm.page_image(_payload())
    assert prefix == f"data:{mime};base64"
    assert hashlib.sha256(base64.b64decode(data)).digest() == hashlib.sha256(image).digest()
    assert request["include_image_base64"] is False
    assert KEY not in json.dumps(request) and KEY not in json.dumps(out)
    assert out["metrics"]["receipt"]["image_sha256"] == hashlib.sha256(image).hexdigest()


@pytest.mark.parametrize("served", ["mistral-ocr-4-0", "mistral-ocr-latest", "mistral-ocr-4", None])
def test_d0d_11_mistral_served_model_must_be_the_pinned_id(
    served: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _mistral(FakeTransport(200, _mistral_result(served)), monkeypatch)
    assert out["failure"] == {"reason": "served_model_differs"}


@pytest.mark.parametrize(
    "over",
    [
        {"pages": [{"index": 0, "markdown": "a"}, {"index": 1, "markdown": "b"}]},
        {"usage_info": {"pages_processed": 2}},
        {"pages": []},
        {"usage_info": {}},
    ],
)
def test_d0d_11_mistral_needs_exactly_one_processed_page(
    over: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _mistral(FakeTransport(200, _mistral_result(MISTRAL, **over)), monkeypatch)
    assert out["failure"] == {"reason": "malformed_response"}


def test_d0d_12_a_mistral_answer_echoing_its_key_is_withheld(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _mistral_result(MISTRAL, pages=[{"index": 0, "markdown": f"page {KEY}"}])
    out = _mistral(FakeTransport(200, raw), monkeypatch)
    assert out["failure"] == {"reason": base.CREDENTIAL_IN_RESULT}
    assert "MISTRAL_API_KEY" in base.CREDENTIAL_ENV


def test_d0d_13_a_mistral_429_is_unavailable_and_a_500_is_a_failure_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RunnerUnavailable, match="unavailable"):
        _mistral(FakeTransport(429, b'{"message": "Too Many Requests"}'), monkeypatch)
    out = _mistral(FakeTransport(500, b'{"message": "internal"}'), monkeypatch)
    assert out["failure"] == {"reason": "http_500"}
    kept = out["receipt"]["raw_response_b64"]
    assert base64.b64decode(kept) == b'{"message": "internal"}'


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


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://v.example/x?token=t",
        "https://v.example/x#t",
        "https://u:p@v.example/x",
        "https://v.example/x%3Ftoken%3Dt",
        "https://v.example/%41",
    ],
)
def test_screen_candidate_refuses_an_unclean_endpoint_before_the_first_page(
    endpoint: str, tmp_path: Path
) -> None:
    from benchmark.screen.run_screen import Candidate
    from benchmark.v6.contracts import ContractError

    cfg = vlm.config_sha256(RUNNER_CONFIGS["teleocr"](revision=REVISION))
    cand = Candidate("c6", "teleocr", REVISION, "sha256:" + "1" * 64, cfg, endpoint, True)
    with pytest.raises(ContractError, match="endpoint"):
        cand.validate()


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


# --- No credential can reach a runner result: the door (endpoint) and the exit (seal) ---
#
# Every value below is made in this process (secrets.token_urlsafe); none is a real key.

_PLAIN_EXTERNAL = sorted(set(EXTERNAL_RUNNERS) - set(VLLM) - {"gemini_api", "mistral_ocr_4"})


def _runner_kwargs(provider: str, endpoint: str | None, *, pinned: bool = True) -> dict[str, Any]:
    """``pinned=False`` leaves the model id / revision to the runner (None): the path where a
    Gemini model id is read from the endpoint."""
    kwargs: dict[str, Any] = {"endpoint": endpoint, "allow_network": True}
    if provider == "gemini_api":
        kwargs.update(model=GEMINI if pinned else None, **GEMINI_OPTIONS)
    elif provider == "mistral_ocr_4":
        kwargs["model"] = "mistral-ocr-4-1" if pinned else None
    else:
        kwargs["revision"] = REVISION if pinned else None
    return kwargs


def _credential_of(provider: str) -> str:
    named = {"gemini_api": "GEMINI_API_KEY", "mistral_ocr_4": "MISTRAL_API_KEY"}
    return named.get(provider, "AKC_BENCHMARK_PROVIDER_TOKEN")


def _chain_text(exc: BaseException | None) -> str:
    """Everything a caller could print: each exception of the chain, its notes, and the members
    of an exception group, with the traceback rendering on top."""
    import traceback

    texts = []
    pending = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        texts.append(f"{current!s} {current.args!r} {getattr(current, '__notes__', '')!r}")
        pending += [current.__cause__, current.__context__]
        if isinstance(current, BaseExceptionGroup):
            pending += list(current.exceptions)
    if exc is not None:
        texts.append("".join(traceback.format_exception(exc)))
    return "\n".join(texts)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _assert_absent(
    marker: str, out: dict[str, Any] | None, exc: BaseException | None, logs: str
) -> None:
    """The marker in no spelling a reader could recover: plain (any case, NFKC-folded), hex,
    inside any base64 string of the result (raw and re-serialised after ``json.loads``), in
    any exception text of the chain (notes and group members included), or in the log."""
    import unicodedata

    def recoverable(text: str) -> bool:
        folded = unicodedata.normalize("NFKC", text).casefold()
        return marker.casefold() in folded or marker.encode().hex() in folded

    assert not recoverable(logs)
    assert not recoverable(_chain_text(exc))
    if out is None:
        return
    assert not recoverable(json.dumps(out, ensure_ascii=False))
    for text in _strings(out):
        try:
            decoded = base64.b64decode(text, validate=True).decode("utf-8", "replace")
        except ValueError:
            continue
        assert not recoverable(decoded)
        with contextlib.suppress(ValueError, RecursionError):
            assert not recoverable(json.dumps(json.loads(decoded), ensure_ascii=False))


def test_runners_read_credentials_only_through_the_door() -> None:
    """Class guard: a runner that reads the environment directly would bypass the door."""
    import ast

    allowed = {("base.py", "read_credential"), ("base.py", "carries_credential")}
    allowed.add(("base.py", "request_bytes"))  # the host allowlist, not a credential
    hits = set()
    for path in sorted((ROOT / "benchmark" / "runners").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        owner: dict[int, str] = {}
        for func in ast.walk(tree):  # breadth first: an outer function claims its inner ones
            if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                for node in ast.walk(func):
                    owner.setdefault(id(node), func.name)
        for node in ast.walk(tree):
            name = node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", None)
            if name in {"getenv", "environ", "getenvb", "environb"}:
                hits.add((path.name, owner.get(id(node), "<module>")))
    assert hits <= allowed, sorted(hits - allowed)


_SPELLINGS = [
    "as_is",
    "upper",
    "lower",
    "pct1",
    "pct2",
    "pct3",
    "pct_first_char",
    "hex",
    "HEX",
    "b64",
    "b64url",
    "fullwidth",
    "tab_split",
    "newline_split",
    "space_split",
]
# Every position of the endpoint, each path segment of the tail included; "model" is the
# Gemini ``/models/<segment>:generateContent`` position the model id is read from.
_PLACES = [
    "host",
    "subdomain",
    "port",
    "path",
    "seg0",
    "seg1",
    "seg2",
    "in_seg0",
    "in_seg2",
    "model",
    "segment_param",
    "query",
    "fragment",
    "userinfo",
]


def _spell(value: str, spelling: str) -> str:
    from urllib.parse import quote

    if spelling == "hex":
        return value.encode().hex()
    if spelling == "HEX":
        return value.encode().hex().upper()
    if spelling == "b64":
        return base64.b64encode(value.encode()).decode()
    if spelling == "b64url":
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")
    if spelling == "fullwidth":
        return "".join(chr(ord(c) + 0xFEE0) if 0x21 <= ord(c) <= 0x7E else c for c in value)
    if spelling.endswith("_split"):
        sep = {"tab": "\t", "newline": "\n", "space": " "}[spelling.split("_")[0]]
        return value[: len(value) // 2] + sep + value[len(value) // 2 :]
    if spelling == "upper":
        return value.upper()
    if spelling == "lower":
        return value.lower()
    if spelling == "pct_first_char":
        return f"%{ord(value[0]):02X}" + value[1:]
    if spelling.startswith("pct"):
        out = "".join(f"%{ord(c):02X}" for c in value)
        for _ in range(int(spelling[-1]) - 1):
            out = quote(out, safe="")
        return out
    return value


def _endpoint_with(provider: str, spelled: str, place: str) -> str:
    segments = (
        ["v1beta", "models", f"{GEMINI}:generateContent"]
        if provider == "gemini_api"
        else ["v1", "chat", "completions"]
    )
    tail = "/" + "/".join(segments)
    if place[:-1] in {"seg", "in_seg"}:
        index = int(place[-1])
        segments[index] = segments[index] + spelled if place.startswith("in") else spelled
        return "https://p.example/" + "/".join(segments)
    if place == "model":
        return f"https://p.example/v1beta/models/{spelled}:generateContent"
    return {
        "host": f"https://{spelled}{tail}",
        "subdomain": f"https://{spelled}.p.example{tail}",
        "port": f"https://p.example:{spelled}{tail}",
        "path": f"https://p.example/{spelled}{tail}",
        "segment_param": f"https://p.example/v1;k={spelled}{tail}",
        "query": f"https://p.example{tail}?k={spelled}",
        "fragment": f"https://p.example{tail}#{spelled}",
        "userinfo": f"https://x:{spelled}@p.example{tail}",
    }[place]


@settings(
    max_examples=600,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(
    provider=st.sampled_from(sorted(EXTERNAL_RUNNERS)),
    spelling=st.sampled_from(_SPELLINGS),
    place=st.sampled_from(_PLACES),
    pinned=st.booleans(),
)
def test_door_any_endpoint_that_contains_the_credential_is_refused_before_any_call(
    provider: str, spelling: str, place: str, pinned: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """Property: whatever the model argument (pinned id or None) and wherever and however the
    credential sits in the endpoint, zero calls, and the marker is absent from the exception
    chain (notes included) and the log capture."""
    marker = _marker()
    endpoint = _endpoint_with(provider, _spell(marker, spelling), place)
    calls: list[Any] = []

    def transport(*a: Any, **_: Any) -> Any:
        calls.append(a)
        raise AssertionError("no call may happen")

    caplog.clear()
    with pytest.MonkeyPatch.context() as mp, caplog.at_level(logging.DEBUG):
        mp.setenv(_credential_of(provider), marker)
        mp.setattr(vlm, "post_bytes", transport)
        mp.setattr(base, "post_bytes", transport)
        with pytest.raises(RunnerUnavailable) as caught:
            EXTERNAL_RUNNERS[provider](
                _payload(), **_runner_kwargs(provider, endpoint, pinned=pinned)
            )
    assert calls == []
    _assert_absent(marker, None, caught.value, caplog.text)


@pytest.mark.parametrize("model_case", ["exact", "lower", "inside"])
def test_door_gemini_with_no_model_and_the_key_as_the_model_segment(
    model_case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's case: model=None, so the id would be read from ``/models/<segment>``."""
    marker = _marker()
    segment = {"exact": marker, "lower": marker.lower(), "inside": f"gemini-4-{marker}"}
    endpoint = f"https://g.example/v1beta/models/{segment[model_case]}:generateContent"
    transport = FakeTransport(200, _gemini())
    monkeypatch.setattr(vlm, "post_bytes", transport)
    monkeypatch.setenv("GEMINI_API_KEY", marker)
    with pytest.raises(RunnerUnavailable) as caught:
        EXTERNAL_RUNNERS["gemini_api"](
            _payload(), endpoint=endpoint, allow_network=True, model=None, **GEMINI_OPTIONS
        )
    assert transport.calls == []
    _assert_absent(marker, None, caught.value, "")


_ENDPOINT_ALPHABET = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-/")
_OUTSIDE = [
    *sorted(set(map(chr, range(0x20, 0x7F))) - _ENDPOINT_ALPHABET),
    chr(0x09),  # tab
    chr(0x0A),  # newline
    chr(0x0D),  # carriage return
    chr(0x00),
    chr(0x7F),
    chr(0x00E9),  # non-ASCII letter
    chr(0xFF4B),  # fullwidth k
    chr(0x200B),  # zero-width space
    chr(0x0130),  # dotted capital I (casefolds to two characters)
]


@pytest.mark.parametrize("char", _OUTSIDE)
def test_door_endpoint_shape_is_an_allow_list(char: str) -> None:
    """Host and path come from letters, digits, '.', '-', '_', ':', '/' (ASCII) and nothing else."""
    for endpoint in (f"https://h.example/a{char}b", f"https://h{char}x.example/a"):
        with pytest.raises(RunnerUnavailable):
            base.require_clean_endpoint(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://h.example/v1",  # no plain HTTP, loopback or not (no test needs it)
        "http://127.0.0.1/v1",
        "HTTPS://h.example/v1",
        "ftp://h.example/v1",
        "https:/h.example/v1",
        "https://",
        "//h.example/v1",
        b"https://h.example/v1",
        123,
    ],
)
def test_door_endpoint_must_be_an_https_string(endpoint: Any) -> None:
    with pytest.raises(RunnerUnavailable):
        base.require_clean_endpoint(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        None,
        "https://h.example",
        "https://h.example/",
        "https://h.example:8443/v1/chat/completions",
        f"https://g.example/v1beta/models/{GEMINI}:generateContent",
        "https://my_host-1.example/a_b/c-d/e.f",
    ],
)
def test_door_a_clean_endpoint_is_accepted(endpoint: str | None) -> None:
    base.require_clean_endpoint(endpoint)


_ENTRY_STEP = {  # the first validation step after the door, per public entry point
    "gemini_api": ("benchmark.runners.gemini_api", "config"),
    "mistral_ocr_4": ("benchmark.runners.mistral_ocr", "config"),
    "ovis_ocr3": ("benchmark.runners.openai_chat", "config"),
    "mineru": ("benchmark.runners.base", "external_exchange"),
}


@pytest.mark.parametrize("provider", sorted(_ENTRY_STEP))
def test_door_comes_first_and_every_later_refusal_runs_inside_seal(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """By construction, not by input: the credential is read and the endpoint checked before
    any argument is validated, and whatever the validation raises passes the exit guard."""
    import importlib

    marker = _marker()
    monkeypatch.setenv(_credential_of(provider), marker)
    order: list[str] = []
    door = base.read_credential

    def spy_door(name: str, endpoint: Any) -> Any:
        order.append("door")
        return door(name, endpoint)

    def poisoned(*_a: Any, **_k: Any) -> Any:
        order.append("validate")
        error = RunnerUnavailable("refused: " + marker)
        error.add_note("note " + marker)
        raise error

    monkeypatch.setattr(base, "read_credential", spy_door)
    module, name = _ENTRY_STEP[provider]
    monkeypatch.setattr(importlib.import_module(module), name, poisoned)
    with pytest.raises(RunnerUnavailable) as caught:
        EXTERNAL_RUNNERS[provider](_payload(), **_runner_kwargs(provider, "https://p.example/v"))
    assert order == ["door", "validate"]
    _assert_absent(marker, None, caught.value, "")


def test_runner_refusal_messages_are_fixed_strings() -> None:
    """No exception raised under benchmark/runners, and no runner refusal type constructed
    there, takes a message built from a value (f-string, %, .format, +, a variable). The one
    allowed interpolation is a compile-time constant of its own module, listed here."""
    import ast

    allowed = {("gemini_api.py", "MAX_THINKING_BUDGET")}  # int literal at module level
    refusal_types = {"RunnerUnavailable", "ResponseRefused", "PageRefused"}

    def constants(tree: ast.Module) -> set[str]:
        return {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            for target in node.targets
            if isinstance(target, ast.Name)
        }

    def fixed(node: ast.expr, module: str, consts: set[str]) -> bool:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return True
        if isinstance(node, ast.JoinedStr):
            return all(
                isinstance(part, ast.Constant)
                or (
                    isinstance(part, ast.FormattedValue)
                    and isinstance(part.value, ast.Name)
                    and (module, part.value.id) in allowed
                    and part.value.id in consts
                    and part.format_spec is None
                )
                for part in node.values
            )
        return False

    bad = []
    checked = 0
    for path in sorted((ROOT / "benchmark" / "runners").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consts = constants(tree)
        for node in ast.walk(tree):
            call = None
            if isinstance(node, ast.Raise) and node.exc is not None:
                if not isinstance(node.exc, ast.Call):
                    bad.append((path.name, node.lineno, "raise of a non-constructed value"))
                    continue
                call = node.exc
            elif isinstance(node, ast.Call):
                func = node.func
                called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if called in refusal_types:
                    call = node
            if call is None:
                continue
            checked += 1
            for arg in [*call.args, *(keyword.value for keyword in call.keywords)]:
                if not fixed(arg, path.name, consts):
                    bad.append((path.name, call.lineno, ast.unparse(arg)))
    assert checked > 50  # the walk saw the runners' refusals
    assert bad == []


@pytest.mark.parametrize("provider", sorted(EXTERNAL_RUNNERS))
def test_door_an_endpoint_with_a_percent_sign_is_refused(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_credential_of(provider), _marker())
    endpoint = _endpoint_with(provider, "a%20b", "path")
    with pytest.raises(RunnerUnavailable, match="percent"):
        EXTERNAL_RUNNERS[provider](_payload(), **_runner_kwargs(provider, endpoint))


def test_door_refuses_a_name_that_is_not_a_declared_credential() -> None:
    with pytest.raises(ValueError):
        base.read_credential("HOME", None)


_LEAKS = [
    "echo_text",
    "upper_text",
    "escaped_text",
    "model_field",
    "usage_key",
    "status",
    "garbage",
    "raise",
    "hex_text",
    "fullwidth_text",
    "unrelated_escaped",
    "note",
]
_LEAKS_THAT_REACH_A_RESULT = {"echo_text", "hex_text", "fullwidth_text"}


class _Echo:
    """A hostile provider: puts the credential it was sent back into its answer."""

    def __init__(self, leak: str, marker: str) -> None:
        self.leak, self.marker = leak, marker

    def __call__(self, config: Any, body: bytes, headers: dict[str, str], **_: Any) -> Any:
        m = self.marker
        if self.leak == "raise":
            try:
                raise OSError(f"connection reset by {m}")
            except OSError as exc:
                raise RunnerUnavailable(f"provider down: {m}") from exc
        if self.leak == "note":
            error = RunnerUnavailable("provider down")
            error.add_note(f"while sending {m}")
            raise error
        if self.leak == "status":
            return 403, "application/json", json.dumps({"error": f"bad key {m}"}).encode()
        if self.leak == "garbage":
            return 200, "application/json", b"\xff\x00" + m.encode() + b"\x00"
        text = {
            "echo_text": f"page {m}",
            "escaped_text": f"page {m}",
            "upper_text": f"page {m.upper()}",
            "hex_text": f"page {m.encode().hex()}",
            "fullwidth_text": "page " + _spell(m, "fullwidth"),
        }.get(self.leak, "page text")
        if config.provider == "gemini_api":
            doc: dict[str, Any] = {
                "modelVersion": m if self.leak == "model_field" else GEMINI,
                "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}],
                "usageMetadata": {m: 1} if self.leak == "usage_key" else {},
            }
        elif config.provider in VLLM:
            served = _served(VLLM[config.provider])
            doc = {
                "model": m if self.leak == "model_field" else served,
                "choices": [{"finish_reason": "stop", "message": {"content": text}}],
                "usage": {m: 1} if self.leak == "usage_key" else {},
            }
        elif config.provider == "mistral_ocr_4":
            usage: dict[str, Any] = {"pages_processed": 1}
            if self.leak == "usage_key":
                usage[m] = 1
            doc = {
                "model": m if self.leak == "model_field" else config.model_revision,
                "pages": [{"index": 0, "markdown": text}],
                "usage_info": usage,
            }
        else:
            doc = {
                "schema_version": "1.0",
                "benchmark_case_id": "page-1",
                "provider": config.provider,
                "model_revision": m if self.leak == "model_field" else config.model_revision,
                "text": text,
                "metrics": {m: 1} if self.leak == "usage_key" else {},
            }
        raw = json.dumps(doc).encode()
        if self.leak == "escaped_text":  # the JSON spells the first character as \uXXXX
            raw = raw.replace(m.encode(), f"\\u{ord(m[0]):04x}".encode() + m[1:].encode())
        if self.leak == "unrelated_escaped":  # every character escaped, in a field nobody reads
            escaped = "".join(f"\\u{ord(c):04x}" for c in m).encode()
            raw = b'{"unrelated": "' + escaped + b'", ' + raw[1:]
        return 200, "application/json", raw


@settings(
    max_examples=400,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(
    provider=st.sampled_from(sorted(EXTERNAL_RUNNERS)),
    leak=st.sampled_from(_LEAKS),
    leaked=st.sampled_from(base.CREDENTIAL_ENV),
)
def test_exit_no_runner_result_or_error_carries_a_credential_a_provider_echoed(
    provider: str, leak: str, leaked: str, caplog: pytest.LogCaptureFixture
) -> None:
    markers = {name: _marker() for name in base.CREDENTIAL_ENV}
    marker = markers[leaked]
    out: dict[str, Any] | None = None
    exc: BaseException | None = None
    caplog.clear()
    with pytest.MonkeyPatch.context() as mp, caplog.at_level(logging.DEBUG):
        for name, value in markers.items():
            mp.setenv(name, value)
        mp.setattr(vlm, "post_bytes", _Echo(leak, marker))
        mp.setattr(base, "post_bytes", _Echo(leak, marker))
        try:
            out = EXTERNAL_RUNNERS[provider](_payload(), **_runner_kwargs(provider, None))
        except Exception as raised:  # what a caller would see and might print
            exc = raised
    for value in markers.values():
        _assert_absent(value, out, exc, caplog.text)
    if leak in _LEAKS_THAT_REACH_A_RESULT:  # so the result is the fixed failure row
        assert out is not None and out["failure"] == {"reason": base.CREDENTIAL_IN_RESULT}


@pytest.mark.parametrize("provider", sorted(EXTERNAL_RUNNERS))
def test_exit_a_result_echoing_the_key_becomes_a_fixed_failure_row(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _marker()
    monkeypatch.setenv(_credential_of(provider), marker)
    monkeypatch.setattr(vlm, "post_bytes", _Echo("echo_text", marker))
    monkeypatch.setattr(base, "post_bytes", _Echo("echo_text", marker))
    out = EXTERNAL_RUNNERS[provider](_payload(), **_runner_kwargs(provider, None))
    assert out == {
        "schema_version": "1.0",
        "benchmark_case_id": "page-1",
        "provider": provider,
        "model_revision": GEMINI
        if provider == "gemini_api"
        else ("mistral-ocr-4-1" if provider == "mistral_ocr_4" else REVISION),
        "failure": {"reason": base.CREDENTIAL_IN_RESULT},
        "receipt": {"revision_attested": False},
    }
    assert list(VALIDATOR.iter_errors(out))  # a failure row is never a valid parser output


@pytest.mark.parametrize("shift", [0, 1, 2])
def test_exit_finds_the_key_inside_base64_at_every_alignment(
    shift: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _marker()
    monkeypatch.setenv("AKC_BENCHMARK_PROVIDER_TOKEN", marker)
    blob = base64.b64encode(b"x" * shift + marker.encode() + b"tail").decode()
    assert base.carries_credential(json.dumps({"raw": blob}))
    assert not base.carries_credential(json.dumps({"raw": base64.b64encode(b"x" * 99).decode()}))


@pytest.mark.parametrize("spelling", ["as_is", "upper", "hex", "HEX", "b64url", "fullwidth"])
def test_exit_sees_every_listed_spelling_of_a_credential(
    spelling: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # '~', '>' and '?' are what make base64 differ from URL-safe base64 for an ASCII value: a
    # key of letters, digits, '-' and '_' alone encodes identically under both alphabets.
    marker = _marker() + "~>?"
    monkeypatch.setenv("AKC_BENCHMARK_PROVIDER_TOKEN", marker)
    spelled = _spell(marker, spelling)
    if spelling == "b64url":
        assert spelled != base64.b64encode(marker.encode()).decode().rstrip("=")
    assert base.carries_credential("x " + spelled + " y")
    assert not base.carries_credential("x " + _spell(_marker() + "~>?", spelling) + " y")


def test_exit_reads_a_stored_raw_response_after_json_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider that writes the key as \\uXXXX escapes in a field nobody extracts: only the
    raw bytes carry it, base64-encoded; decoded and re-serialised, it is the plain value."""
    marker = KEY  # the value _call puts in GEMINI_API_KEY
    escaped = "".join(f"\\u{ord(c):04x}" for c in marker)
    raw = _gemini().replace(
        b'{"modelVersion"', b'{"x": "' + escaped.encode() + b'", "modelVersion"'
    )
    assert marker.encode() not in raw
    out = _call("gemini_api", FakeTransport(200, raw), monkeypatch)
    assert out["failure"] == {"reason": base.CREDENTIAL_IN_RESULT}
    _assert_absent(marker, out, None, "")


@pytest.mark.parametrize("shape", ["note", "group_member_note", "group_member", "deep_note"])
def test_exit_an_exception_note_or_group_member_carrying_a_credential_is_withheld(
    shape: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _marker()
    monkeypatch.setenv("AKC_BENCHMARK_PROVIDER_TOKEN", marker)

    def produce() -> dict[str, Any]:
        inner = RuntimeError("plain")
        if shape in {"note", "group_member_note", "deep_note"}:
            inner.add_note("key " + marker)
        if shape == "group_member":
            inner = ValueError(marker)
        if shape == "deep_note":
            try:
                raise inner
            except RuntimeError as exc:
                raise RunnerUnavailable("plain outer") from exc
        if shape.startswith("group"):
            raise ExceptionGroup("g", [inner])
        raise inner

    with pytest.raises(RunnerUnavailable) as caught:
        base.seal(base.RunnerConfig("p", REVISION), _payload(), produce)
    assert str(caught.value) == "runner error withheld: its text carried a credential"
    _assert_absent(marker, None, caught.value, "")


def test_exit_an_unserialisable_result_or_a_credential_in_the_inputs_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _marker()
    monkeypatch.setenv("AKC_BENCHMARK_PROVIDER_TOKEN", marker)
    config = base.RunnerConfig("p", REVISION)
    out = base.seal(config, _payload(), lambda: {"x": object()})
    assert out["failure"] == {"reason": "result_not_serialisable"}
    tainted = base.RunnerConfig("p", marker)  # the inputs themselves carry the key
    with pytest.raises(RunnerUnavailable) as caught:
        base.seal(tainted, _payload(), lambda: {"model_revision": marker})
    _assert_absent(marker, None, caught.value, "")


# --- WO-D10-0D: the WO-D10-0C review notes closed (tests 1-8 of the work order) ---


def _escaped(value: str) -> str:
    return "".join(f"\\u{ord(c):04x}" for c in value)


@pytest.mark.parametrize("provider", ["gemini_api", "mineru"])
@pytest.mark.parametrize("hide", ["b64_hex", "b64_escaped"])
def test_d0d_01_a_caller_id_that_hides_the_key_withholds_the_failure_row(
    provider: str, hide: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _marker()
    monkeypatch.setenv(_credential_of(provider), marker)
    hidden = {
        "b64_hex": base64.b64encode(marker.encode().hex().encode()).decode(),
        "b64_escaped": base64.b64encode(f'"{_escaped(marker)}"'.encode()).decode(),
    }[hide]
    monkeypatch.setattr(vlm, "post_bytes", _Echo("echo_text", marker))
    monkeypatch.setattr(base, "post_bytes", _Echo("echo_text", marker))
    with pytest.raises(RunnerUnavailable, match="inputs carried a credential") as caught:
        EXTERNAL_RUNNERS[provider](
            {**_payload(), "benchmark_case_id": hidden}, **_runner_kwargs(provider, None)
        )
    _assert_absent(marker, None, caught.value, "")


def test_d0d_02_a_parse_error_whose_attributes_echo_the_key_is_withheld(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _marker()
    monkeypatch.setenv("AKC_BENCHMARK_PROVIDER_TOKEN", marker)
    raw = ('{"provider": "mineru", "echo": "' + marker + '"').encode()  # broken JSON
    monkeypatch.setattr(base, "post_bytes", FakeTransport(200, raw))
    with pytest.raises(RunnerUnavailable, match="withheld") as caught:
        EXTERNAL_RUNNERS["mineru"](_payload(), **_runner_kwargs("mineru", None))
    chain: list[BaseException | None] = [caught.value]
    while chain:
        exc = chain.pop()
        if exc is None:
            continue
        seen = f"{exc!s} {exc.args!r} {vars(exc)!r} {getattr(exc, 'doc', '')}"
        assert marker not in seen
        chain += [exc.__cause__, exc.__context__]


@pytest.mark.parametrize("status", [200, 401])
def test_d0d_03_a_broken_json_body_holding_the_key_escaped_is_caught(
    status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = ('{"modelVersion": "' + GEMINI + '", "x": "' + _escaped(KEY) + '"').encode()
    assert KEY.encode() not in raw
    out = _call("gemini_api", FakeTransport(status, raw), monkeypatch)
    assert out["failure"] == {"reason": base.CREDENTIAL_IN_RESULT}
    assert "raw_response_b64" not in json.dumps(out)


@pytest.mark.parametrize("shift", range(5))
@pytest.mark.parametrize("case", ["upper", "lower"])
def test_d0d_04_the_key_in_base32_is_seen_at_every_alignment(
    shift: int, case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    spelled = base64.b32encode(b"x" * shift + KEY.encode() + b"tail").decode()
    spelled = spelled.lower() if case == "lower" else spelled
    parts = [{"text": "page " + spelled}]
    raw = _gemini(candidates=[{"finishReason": "STOP", "content": {"parts": parts}}])
    out = _call("gemini_api", FakeTransport(200, raw), monkeypatch)
    assert out["failure"] == {"reason": base.CREDENTIAL_IN_RESULT}


def test_d0d_04_an_endpoint_path_in_base32_of_the_key_is_refused_at_the_door(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b32 = base64.b32encode(KEY.encode()).decode().rstrip("=")
    endpoint = f"https://g.example/{b32}/v1beta/models/{GEMINI}:generateContent"
    transport = FakeTransport(200, _gemini())
    with pytest.raises(RunnerUnavailable, match="credential"):
        _call("gemini_api", transport, monkeypatch, endpoint=endpoint)
    assert transport.calls == []


def test_d0d_05_an_exception_whose_text_cannot_be_read_is_withheld(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AKC_BENCHMARK_PROVIDER_TOKEN", _marker())

    class Unreadable(RuntimeError):
        def __str__(self) -> str:
            raise ValueError("no text")

    def produce() -> dict[str, Any]:
        raise Unreadable()

    with pytest.raises(RunnerUnavailable, match="withheld"):
        base.seal(base.RunnerConfig("p", REVISION), _payload(), produce)


def test_d0d_05_an_exception_carrying_the_key_only_in_its_args_is_withheld(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _marker()
    monkeypatch.setenv("AKC_BENCHMARK_PROVIDER_TOKEN", marker)

    class Quiet(RuntimeError):  # str() hides the args; nothing in vars()
        def __str__(self) -> str:
            return "provider said no"

    def produce() -> dict[str, Any]:
        raise Quiet("provider said no", marker)

    with pytest.raises(RunnerUnavailable, match="withheld") as caught:
        base.seal(base.RunnerConfig("p", REVISION), _payload(), produce)
    assert marker not in repr(caught.value.args)


def test_d0d_06_a_dict_key_holding_the_key_is_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = _marker()
    monkeypatch.setenv("AKC_BENCHMARK_PROVIDER_TOKEN", marker)
    hidden = base64.b64encode(marker.encode().hex().encode()).decode()
    out = base.seal(base.RunnerConfig("p", REVISION), _payload(), lambda: {"m": {hidden: 1}})
    assert out["failure"] == {"reason": base.CREDENTIAL_IN_RESULT}


def test_d0d_07_a_percent_encoded_key_is_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib.parse import quote

    marker = _marker() + "/+="
    monkeypatch.setenv("AKC_BENCHMARK_PROVIDER_TOKEN", marker)

    def produce() -> dict[str, Any]:
        return {"t": quote(marker, safe="")}

    out = base.seal(base.RunnerConfig("p", REVISION), _payload(), produce)
    assert out["failure"] == {"reason": base.CREDENTIAL_IN_RESULT}


@pytest.mark.parametrize(
    ("label", "named"),
    [
        (GEMINI, GEMINI),
        (REVISION, REVISION),
        ("ATH-MaaS/OvisOCR3@" + REVISION, "ATH-MaaS/OvisOCR3@" + REVISION),
        ("gemini 4", ""),
        ("KEY", ""),
        (None, ""),
        (5, ""),
        ("x" * 129, ""),
        ("-leading", ""),
    ],
)
def test_d0d_08_the_outer_seal_names_the_requested_model_or_nothing(
    label: Any, named: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _marker()
    monkeypatch.setenv("GEMINI_API_KEY", marker)
    label = marker if label == "KEY" else label
    out = base.guarded(
        "GEMINI_API_KEY",
        None,
        "gemini_api",
        _payload(),
        lambda _: {"t": marker},
        model_revision=label,
    )
    assert out["failure"] == {"reason": base.CREDENTIAL_IN_RESULT}
    assert out["model_revision"] == named


def test_d0d_08_every_runner_passes_its_own_model_or_revision_to_the_door(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    seen: dict[str, Any] = {}
    real = base.guarded

    def spy(name: str, endpoint: Any, provider: str, payload: Any, body: Any, **kw: Any) -> Any:
        seen[provider] = kw.get("model_revision")
        return real(name, endpoint, provider, payload, body, **kw)

    for module in ("base", "gemini_api", "mistral_ocr", "openai_chat"):
        monkeypatch.setattr(importlib.import_module(f"benchmark.runners.{module}"), "guarded", spy)
    for name in base.CREDENTIAL_ENV:
        monkeypatch.setenv(name, _marker())
    monkeypatch.setattr(vlm, "post_bytes", FakeTransport(500, b"{}"))
    monkeypatch.setattr(base, "post_bytes", FakeTransport(500, b"{}"))
    for provider in ("gemini_api", "mistral_ocr_4", "ovis_ocr3", "mineru"):
        with contextlib.suppress(RunnerUnavailable):
            EXTERNAL_RUNNERS[provider](_payload(), **_runner_kwargs(provider, None))
    assert seen == {
        "gemini_api": GEMINI,
        "mistral_ocr_4": "mistral-ocr-4-1",
        "ovis_ocr3": REVISION,
        "mineru": REVISION,
    }


# --- WO-D10-0D item 2: request_bytes, a transport with a closed query (test 9) ---


@pytest.mark.parametrize(
    ("method", "query"),
    [
        ("GET", {"key": "x"}),
        ("GET", {"pageToken": "a%2F"}),
        # lead decision C (round 2): "=", "+" and "/" are now accepted in a pageToken (an
        # opaque base64 token); they stay refused in pageSize, as does anything else
        ("GET", {"pageSize": "a=b"}),
        ("GET", {"pageSize": "0"}),
        ("GET", {"pageToken": "a b"}),
        ("GET", {"pageToken": "a\nb"}),
        ("GET", {"pageToken": "a&key=b"}),
        ("GET", {"pageToken": "a" * 2049}),
        ("GET", {"pageToken": ""}),
        ("GET", {"pageSize": 5}),
        ("GET", ["pageToken"]),
        ("PUT", None),
        ("get", None),
    ],
)
def test_d0d_09_request_bytes_refuses_an_open_query_or_method_before_dns(
    method: str, query: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    looked_up: list[Any] = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: looked_up.append(a))
    monkeypatch.setenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", "g.example")
    config = base.RunnerConfig("p", "", "https://g.example/v1beta/batches", True)
    with pytest.raises(RunnerUnavailable):
        base.request_bytes(config, method, None, {}, query=query)
    assert looked_up == []


def test_d0d_09_the_query_reaches_the_target_only(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []

    class Connection:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def request(self, method: str, target: str, **_: Any) -> None:
            sent.append((method, target))

        def getresponse(self) -> Any:
            message = types.SimpleNamespace(get_content_type=lambda: "application/json")
            return types.SimpleNamespace(status=200, headers=message, read=lambda n: b"{}")

        def close(self) -> None:
            pass

    resolved = types.SimpleNamespace(hostname_ascii="g.example", resolved_ips=["8.8.8.8"])
    monkeypatch.setattr(base, "_PinnedHTTPSConnection", Connection)
    monkeypatch.setattr(base, "validate_resolved_url", lambda *a: resolved)
    monkeypatch.setattr(
        base.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("8.8.8.8", 443))]
    )
    monkeypatch.setenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", "g.example")
    config = base.RunnerConfig("p", "", "https://g.example/v1beta/batches", True)
    query = {"pageToken": "t-1", "pageSize": "50"}
    assert base.request_bytes(config, "GET", None, {}, query=query) == (
        200,
        "application/json",
        b"{}",
    )
    base.request_bytes(config, "DELETE", None, {})
    base.request_bytes(config, "GET", None, {}, query={"pageToken": "Ab+/9~_.-=="})
    base.request_bytes(config, "GET", None, {}, query={"pageToken": "x" * 2048})
    assert sent == [
        ("GET", "/v1beta/batches?pageSize=50&pageToken=t-1"),
        ("DELETE", "/v1beta/batches"),
        ("GET", "/v1beta/batches?pageToken=Ab%2B%2F9~_.-%3D%3D"),  # percent-encoded by code
        ("GET", "/v1beta/batches?pageToken=" + "x" * 2048),
    ]
    assert config.endpoint == "https://g.example/v1beta/batches"  # the receipt's view is unchanged


# --- WO-D10-0D item 4: one request body for sync and batch; the batch REST helpers ---


@pytest.mark.parametrize("level", ["low", "THINKING_LEVEL_UNSPECIFIED", "ULTRA", 1])
def test_d0d_gemini_thinking_level_is_a_rest_enum_name(level: Any, monkeypatch) -> None:
    transport = FakeTransport(200, _gemini())
    with pytest.raises(RunnerUnavailable, match="thinkingLevel"):
        _call("gemini_api", transport, monkeypatch, thinking_config={"thinkingLevel": level})
    assert transport.calls == []


def test_d0d_the_sync_body_is_the_batch_request_byte_for_byte(monkeypatch) -> None:
    from benchmark.runners import gemini_api

    transport = FakeTransport(200, _gemini())
    _call("gemini_api", transport, monkeypatch)
    _, sent, _ = transport.calls[0]
    pinned = gemini_api.config(model=GEMINI, **GEMINI_OPTIONS)
    mime, image, _ = vlm.page_image(_payload())
    entry = {"request": gemini_api.request_body(pinned, mime, image), "metadata": {"key": "k"}}
    batch = json.loads(gemini_api.batch_create_body("akc-d10h-x", [entry]))
    assert batch["batch"]["inputConfig"]["requests"]["requests"][0]["request"] == sent


@pytest.mark.parametrize(
    "name",
    ["batches/", "batches/a/../b", "batches/a?x=1", "operations/a", "batches/a b", None, 5],
)
def test_d0d_a_job_name_outside_the_documented_shape_is_refused_before_any_call(
    name: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benchmark.runners import gemini_api

    calls: list[Any] = []
    monkeypatch.setattr(gemini_api, "request_bytes", lambda *a, **k: calls.append(a))
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    for helper in (gemini_api.batch_get, gemini_api.batch_delete):
        with pytest.raises(RunnerUnavailable, match="batch job name"):
            helper(name, allow_network=True)
    assert calls == []


def test_d0d_batch_helpers_go_through_the_door_and_the_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from benchmark.runners import gemini_api

    seen: list[tuple[str, str, Any, dict[str, str]]] = []

    def transport(config: Any, method: str, body: Any, headers: dict[str, str], **kw: Any) -> Any:
        seen.append((method, config.endpoint, kw.get("query"), headers))
        echo = (
            b'{"name": "batches/b1", "x": "' + KEY.encode() + b'"}' if method == "DELETE" else b"{}"
        )
        return 200, "application/json", echo

    monkeypatch.setattr(gemini_api, "request_bytes", transport)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RunnerUnavailable, match="GEMINI_API_KEY"):
        gemini_api.batch_get("batches/b1", allow_network=True)
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    out = gemini_api.batch_create(GEMINI, b"{}", allow_network=True)
    assert out["http_status"] == 200 and base64.b64decode(out["raw_b64"]) == b"{}"
    gemini_api.batch_list("tok-1", allow_network=True)
    gemini_api.batch_get("batches/b1", allow_network=True)
    leaked = gemini_api.batch_delete("batches/b1", allow_network=True)
    assert leaked["failure"] == {"reason": base.CREDENTIAL_IN_RESULT}
    base_url = "https://generativelanguage.googleapis.com/v1beta"
    assert [(m, e, q) for m, e, q, _ in seen] == [
        ("POST", f"{base_url}/models/{GEMINI}:batchGenerateContent", None),
        ("GET", f"{base_url}/batches", {"pageToken": "tok-1"}),
        ("GET", f"{base_url}/batches/b1", None),
        ("DELETE", f"{base_url}/batches/b1", None),
    ]
    assert all(h["x-goog-api-key"] == KEY for *_, h in seen)
    with pytest.raises(RunnerUnavailable):
        gemini_api.batch_create("gemini-latest", b"{}", allow_network=True)


# --- WO-D10-0D round 2: the API's own cutoff, the served-id map, batch cancel ---


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (
            _gemini(candidates=[{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]),
            "output_token_cutoff",
        ),
        (
            _gemini(usageMetadata={"candidatesTokenCount": 200, "thoughtsTokenCount": 8000}),
            "output_tokens_over_bound",
        ),
    ],
)
def test_d0d_r2_a_page_at_the_output_cutoff_is_a_failure_row_with_that_reason(
    raw: bytes, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _call("gemini_api", FakeTransport(200, raw), monkeypatch)
    assert out["failure"] == {"reason": reason}
    assert base64.b64decode(out["receipt"]["raw_response_b64"]) == raw


def test_d0d_r2_the_mistral_served_ids_are_exact_strings_from_the_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dated = "mistral-ocr-4-1-2611"
    refused = _mistral(FakeTransport(200, _mistral_result(dated)), monkeypatch)
    assert refused["failure"] == {"reason": "served_model_differs"}
    served = [MISTRAL, dated]
    ok = _mistral(FakeTransport(200, _mistral_result(dated)), monkeypatch, served_ids=served)
    assert ok["text"] == "x"
    for near in ("mistral-ocr-4-1-2612", "mistral-ocr-4-1-261", dated.upper()):
        out = _mistral(FakeTransport(200, _mistral_result(near)), monkeypatch, served_ids=served)
        assert out["failure"] == {"reason": "served_model_differs"}


def test_d0d_r2_batch_cancel_posts_cancel_through_the_door(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from benchmark.runners import gemini_api

    seen: list[tuple[str, str, Any]] = []

    def transport(config: Any, method: str, body: Any, headers: dict[str, str], **kw: Any) -> Any:
        seen.append((method, config.endpoint, body))
        return 200, "application/json", b"{}"

    monkeypatch.setattr(gemini_api, "request_bytes", transport)
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    out = gemini_api.batch_cancel("batches/b1", allow_network=True)
    assert out["http_status"] == 200
    base_url = "https://generativelanguage.googleapis.com/v1beta"
    assert seen == [("POST", f"{base_url}/batches/b1:cancel", b"{}")]
    with pytest.raises(RunnerUnavailable, match="batch job name"):
        gemini_api.batch_cancel("batches/b1:cancel", allow_network=True)
    assert len(seen) == 1


# --- WO-D10-0J: the planned image and the served ids ---


def test_0j_6_mistral_refuses_an_image_other_than_the_planned_one_before_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from benchmark.runners import mistral_ocr

    transport = FakeTransport(200, _mistral_result(MISTRAL))
    with pytest.raises(mistral_ocr.ImageDiffers):
        _mistral(transport, monkeypatch, image_sha256="0" * 64)
    assert transport.calls == []
    ok = _mistral(transport, monkeypatch, image_sha256=hashlib.sha256(IMAGE).hexdigest())
    assert ok["text"] == "x" and len(transport.calls) == 1


@pytest.mark.parametrize(
    "alias", ["mistral-ocr-4-0", "mistral-ocr-4", "mistral-ocr-latest", "Mistral-OCR-Latest"]
)
def test_0j_8_mistral_served_ids_refuse_the_retired_id_and_aliases_before_any_call(
    alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = FakeTransport(200, _mistral_result(alias))
    with pytest.raises(RunnerUnavailable, match="alias"):
        _mistral(transport, monkeypatch, served_ids=[MISTRAL, alias])
    assert transport.calls == []
