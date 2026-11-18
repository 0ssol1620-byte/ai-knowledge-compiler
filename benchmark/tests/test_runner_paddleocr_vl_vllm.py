"""C1 PaddleOCR-VL-1.6 on a vLLM chat endpoint (whole-page element prompt), fakes only."""

from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import secrets
from pathlib import Path
from typing import Any

import pytest
import yaml
from PIL import Image

from benchmark.run_benchmark import parser_output_validator
from benchmark.runners import base, paddleocr_vl_vllm, vlm
from benchmark.runners.base import RunnerUnavailable
from benchmark.runners.registry import EXTERNAL_RUNNERS, RUNNER_CONFIGS
from benchmark.runners.vlm import PageRefused

ROOT = Path(__file__).resolve().parents[2]
REVISION = "a" * 40
ENDPOINT = "https://vllm.example/v1/chat/completions"
C1 = "paddleocr_vl_1_6_vllm"
SERVED = f"PaddlePaddle/PaddleOCR-VL-1.6@{REVISION}"
VARIANT = "whole-page element prompt; not the card's page pipeline"
VALIDATOR = parser_output_validator(ROOT / "benchmark" / "manifest.yaml")


def _payload(data: bytes = b"\x89PNG page", content_type: str = "image/png") -> dict[str, Any]:
    return {
        "benchmark_case_id": "page-1",
        "page_index": 0,
        "source": {"content_type": content_type, "bytes_base64": base64.b64encode(data).decode()},
    }


def _chat(text: str, *, served: str = SERVED, finish: str = "stop") -> bytes:
    body = {
        "model": served,
        "choices": [{"finish_reason": finish, "message": {"content": text}}],
        "usage": {"completion_tokens": 3},
    }
    return json.dumps(body, ensure_ascii=False).encode()


class Server:
    """A fake vLLM server that answers every call with ``reply``."""

    def __init__(self, reply: bytes) -> None:
        self.reply = reply
        self.calls: list[tuple[dict[str, Any], dict[str, str]]] = []

    def __call__(self, config: Any, body: bytes, headers: dict[str, str], **_: Any) -> Any:
        self.calls.append((json.loads(body), headers))
        return 200, "application/json", self.reply


def _run(server: Any, monkeypatch: pytest.MonkeyPatch, **kw: Any) -> dict[str, Any]:
    monkeypatch.setattr(base, "post_bytes", server)
    monkeypatch.setattr(vlm, "post_bytes", server)
    payload = kw.pop("payload", None) or _payload()
    kwargs = {"endpoint": ENDPOINT, "revision": REVISION, "allow_network": True, **kw}
    return EXTERNAL_RUNNERS[C1](payload, **kwargs)


def _prompt(request: dict[str, Any]) -> str:
    return str(next(p["text"] for p in request["messages"][0]["content"] if p["type"] == "text"))


def _raw(step: dict[str, Any]) -> bytes:
    return base64.b64decode(step["raw_response_b64"])


# --- registration and label ---


def test_the_key_is_registered_and_the_external_c1_key_is_unchanged() -> None:
    assert C1 in EXTERNAL_RUNNERS and C1 in RUNNER_CONFIGS
    from benchmark.runners import paddleocr_vl

    assert EXTERNAL_RUNNERS["paddleocr_vl_1_6"] is paddleocr_vl.run
    cfg = RUNNER_CONFIGS[C1](revision=REVISION)
    assert cfg["served_model_name"] == SERVED
    other = RUNNER_CONFIGS[C1](revision="b" * 40)
    assert vlm.config_sha256(other) != vlm.config_sha256(cfg)


def test_the_withdrawn_two_step_runner_is_not_registered() -> None:
    """``mineru_vlm`` is now the external-protocol key (WO-D10-0I); the chat runner is gone."""
    assert "mineru_vlm" not in RUNNER_CONFIGS  # no chat profile for C3
    assert not (ROOT / "benchmark" / "runners" / "mineru_vlm.py").exists()


def test_runner_config_docstring_and_registry_row_name_the_variant() -> None:
    assert paddleocr_vl_vllm.VARIANT == VARIANT
    assert VARIANT in RUNNER_CONFIGS[C1](revision=REVISION)["prompt_source"]
    assert VARIANT.capitalize() in (paddleocr_vl_vllm.__doc__ or "")
    models = yaml.safe_load((ROOT / "infra/model-registry/models.yaml").read_text("utf-8"))
    (row,) = [r for r in models["releases"] if r["provider_key"] == "paddleocr_vl_1_6"]
    (variant,) = [v for v in row["runtime"]["serving_variants"] if v["runner"] == C1]
    assert variant["variant"] == VARIANT  # the variant row carries its label


# --- C1 ---


def test_c1_sends_the_card_prompt_after_the_page_and_returns_an_attested_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = Server(_chat("# 안녕"))
    out = _run(server, monkeypatch)
    request, headers = server.calls[0]
    assert request["model"] == SERVED and request["temperature"] == 0.0
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
    out = _run(Server(raw), monkeypatch)
    assert out["failure"] == {"reason": "served_model_differs"}
    assert out["receipt"]["revision_attested"] is False and _raw(out["receipt"]) == raw


def test_c1_a_non_stop_finish_is_a_failure_row(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _chat("cut off", finish="length")
    out = _run(Server(raw), monkeypatch)
    assert out["failure"] == {"reason": "finish_reason_not_stop"} and _raw(out["receipt"]) == raw


def test_a_token_echoed_by_the_server_becomes_the_fixed_failure_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "tok-" + secrets.token_urlsafe(24)
    monkeypatch.setenv("AKC_BENCHMARK_PROVIDER_TOKEN", marker)
    server = Server(_chat(f"page {marker}"))
    out = _run(server, monkeypatch)
    assert all(h["Authorization"] == f"Bearer {marker}" for _, h in server.calls)
    assert out == {
        "schema_version": "1.0",
        "benchmark_case_id": "page-1",
        "provider": C1,
        "model_revision": REVISION,
        "failure": {"reason": base.CREDENTIAL_IN_RESULT},
        "receipt": {"revision_attested": False},
    }


@pytest.mark.parametrize("revision", ["", "main", "G" * 40])
def test_an_unpinned_revision_refuses_before_any_call(
    revision: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = Server(_chat("x"))
    with pytest.raises(RunnerUnavailable, match="revision"):
        _run(server, monkeypatch, revision=revision)
    assert server.calls == []


def test_an_unsupported_page_type_is_a_page_refusal_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = Server(_chat("x"))
    with pytest.raises(PageRefused) as caught:
        _run(server, monkeypatch, payload=_payload(b"x", "application/msword"))
    assert caught.value.reason == "page_content_type_unsupported" and server.calls == []


# --- hostile page bytes are never decoded locally (the class the withdrawn runner had) ---


def _hostile_pages() -> list[bytes]:
    """Bytes in every format Pillow could pick by sniffing, plus random noise."""
    eps = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 100\nshowpage\n%%EOF\n"
    pages = [eps, b"\x89PNG not an image"]
    for fmt in ["GIF", "BMP", "TIFF", "PCX", "TGA", "PNG", "JPEG", "WEBP", "ICO", "PPM"]:
        buffer = io.BytesIO()
        Image.new("RGB", (40, 30), "white").save(buffer, format=fmt)
        pages.append(buffer.getvalue())
    # deterministic noise of varied length: a failure reproduces
    pages += [hashlib.shake_256(b"page-%d" % i).digest(1 + 97 * i) for i in range(40)]
    return pages


def test_any_declared_image_bytes_go_out_unchanged_and_no_local_decoder_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = _hostile_pages()

    def no_decode(*_: Any, **__: Any) -> Any:
        raise AssertionError("a runner decoded hostile page bytes locally")

    monkeypatch.setattr(Image, "open", no_decode)
    for data in pages:
        for mime in ("image/png", "image/jpeg", "image/webp"):
            server = Server(_chat("ok"))
            out = _run(server, monkeypatch, payload=_payload(data, mime))
            assert out["text"] == "ok"
            part = next(
                p for p in server.calls[0][0]["messages"][0]["content"] if p["type"] == "image_url"
            )
            head, sent = part["image_url"]["url"].split(",", 1)
            assert head == f"data:{mime};base64" and base64.b64decode(sent) == data


def test_no_runner_module_imports_an_image_decoder() -> None:
    """Page bytes are hostile data: a runner forwards them, it does not decode them. PDF
    pages are rendered by the shared ``vlm`` renderer (pdfium), which this guard leaves."""
    decoders = {"PIL", "cv2", "imageio", "skimage", "wand"}
    found = []
    for path in sorted((ROOT / "benchmark" / "runners").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            found += [f"{path.name}:{n}" for n in names if n.split(".")[0] in decoders]
    assert found == []
