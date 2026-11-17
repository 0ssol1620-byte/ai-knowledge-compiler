"""The page server against the real client, in process: no GPU, no vendor tool, no network.

The registered runners (``benchmark.runners.base.run_external``) talk to the server over a
loopback socket; only their TLS leg (``post_bytes``: DNS, address check, pinned HTTPS) is
replaced by a plain HTTP connection to 127.0.0.1. Everything the client builds and checks is
its own code. Each recipe in ``recipes/`` is run once with its vendor command replaced by a
fake script that records the arguments it was given.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import http.client
import importlib.util
import itertools
import json
import math
import os
import re
import socket
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

from benchmark.run_benchmark import parser_output_validator
from benchmark.runners import base
from benchmark.runners.base import RunnerUnavailable, build_provider_payload
from benchmark.runners.registry import EXTERNAL_RUNNERS

_HERE = Path(__file__).resolve().parent
_REPO = Path(base.__file__).resolve().parents[2]
REVISION = "ed6b654c018d742e65a17671e379c5e6ecc87ec9"
OTHER_REVISION = "1" * 40
ENDPOINT = "https://c0.example/parse"
_BEARER = "c0-test-bearer-7f3a"
SOURCE = b"%PDF-1.4 not a real pdf; the pipeline is a fake"
RECIPES = sorted((_HERE / "recipes").glob("c*-*.json"))
RECIPES = [p for p in RECIPES if not p.name.endswith("-weights-manifest.json")]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


srv = _load("mineru_akc_server")
weights = _load("mineru_akc_weights")


def _recipe(name: str = "c0-mineru-pipeline", **overrides: Any) -> dict[str, Any]:
    recipe = srv.load_recipe(_HERE / "recipes" / f"{name}.json")
    return {**recipe, **overrides}


class FakePipeline:
    def __init__(self, text: Any = "# Title\n\n| a | b |\n", error: BaseException | None = None):
        self.text = text
        self.error = error
        self.calls: list[tuple[bytes, str, int | None, str | None]] = []
        self.gate: threading.Event | None = None
        self.entered = threading.Event()

    def __call__(self, data: bytes, suffix: str, page: int | None, lang: str | None) -> Any:
        self.calls.append((data, suffix, page, lang))
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(10)
        if self.error is not None:
            raise self.error
        return self.text


class Loopback:
    """``post_bytes`` with the TLS leg swapped for plain HTTP to the in-process server."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.seen: list[tuple[int, bytes, dict[str, str]]] = []
        self.tamper: dict[str, str] = {}

    def __call__(
        self, config: Any, body: bytes, headers: dict[str, str], **_: Any
    ) -> tuple[int, str, bytes]:
        assert config.endpoint == ENDPOINT and config.allow_network
        sent = {**headers, **self.tamper}
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request("POST", "/parse", body=body, headers=sent)
            response = connection.getresponse()
            status, raw = response.status, response.read()
            content_type = response.headers.get_content_type()
        finally:
            connection.close()
        self.seen.append((status, raw, sent))
        return status, content_type, raw


def _serve(settings: Any, pipeline: Any, ready: Any = lambda: True) -> Iterator[Any]:
    server = srv.make_server(settings, pipeline, ("127.0.0.1", 0), ready)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def _manifests(recipe: dict[str, Any]) -> dict[str, str]:
    return {"model": "a" * 64, **{aux["role"]: "b" * 64 for aux in recipe["aux_models"]}}


def _settings(recipe: dict[str, Any] | None = None, **overrides: Any) -> Any:
    recipe = recipe or _recipe()
    receipt = srv.recipe_receipt(recipe, {"mineru": "3.4.4"}, _manifests(recipe))
    return srv.Settings(**{"recipe": recipe, "token": None, "receipt": receipt, **overrides})


def _case(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    (tmp_path / "doc.pdf").write_bytes(SOURCE)
    case = {
        "benchmark_case_id": "page-0001",
        "page_index": 2,
        "language": "ko",
        "document_class": "ko_scan",
        "text": "gold must never leave",
        "source": {
            "path": "doc.pdf",
            "filename": "doc.pdf",
            "content_type": "application/pdf",
            "sha256": hashlib.sha256(SOURCE).hexdigest(),
        },
        **overrides,
    }
    return build_provider_payload(case, corpus_root=tmp_path)


@pytest.fixture
def harness(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[FakePipeline, Loopback, dict[str, Any]]]:
    """(pipeline, transport, payload) with the server running; ``param`` overrides settings."""
    options = dict(getattr(request, "param", {}))
    pipeline = options.pop("pipeline", None) or FakePipeline()
    monkeypatch.delenv(base.PROVIDER_CREDENTIAL, raising=False)
    payload = _case(tmp_path)
    for server in _serve(_settings(**options), pipeline):
        transport = Loopback(server.server_address[1])
        monkeypatch.setattr(base, "post_bytes", transport)
        yield pipeline, transport, payload


def _client(payload: dict[str, Any], revision: str = REVISION, provider: str = "mineru") -> Any:
    return EXTERNAL_RUNNERS[provider](
        payload, endpoint=ENDPOINT, revision=revision, allow_network=True
    )


def _raw(port: int, body: bytes, headers: dict[str, Any], path: str = "/parse") -> Any:
    """One POST with headers sent as given (latin-1 bytes allowed); (status, body)."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.putrequest("POST", path, skip_accept_encoding=True)
        for key, value in headers.items():
            connection.putheader(key, value)
        connection.endheaders()
        connection.send(body)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _headers(
    body: bytes, provider: str = "mineru", extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
        "X-AKC-Benchmark-Provider": provider,
        "X-AKC-Model-Revision": REVISION,
        "X-AKC-Input-SHA256": hashlib.sha256(body).hexdigest(),
        **(extra or {}),
    }


def _port(harness: Any) -> int:
    return int(harness[1].port)


# --- the protocol ----------------------------------------------------------------------------


def test_a_page_round_trips_with_echo_fields_and_a_valid_output(harness: Any) -> None:
    pipeline, transport, payload = harness
    result = _client(payload)
    assert result["provider"] == "mineru"
    assert result["model_revision"] == REVISION
    assert result["benchmark_case_id"] == "page-0001"
    assert result["text"] == pipeline.text
    assert pipeline.calls == [(SOURCE, ".pdf", 2, None)]  # C0 passes no -l (decision A0-8)
    errors = list(
        parser_output_validator(_REPO / "benchmark" / "manifest.yaml").iter_errors(result)
    )
    assert errors == []
    receipt = result["metrics"]["receipt"]
    _, _, headers = transport.seen[0]
    assert receipt["input_sha256"] == headers["X-AKC-Input-SHA256"]
    assert receipt["source_sha256"] == hashlib.sha256(SOURCE).hexdigest()
    recipe = _recipe()
    assert receipt["recipe"] == {
        "name": "c0-mineru-pipeline",
        "sha256": srv.canonical_sha256(recipe),
        "options": recipe["options"],
    }
    assert receipt["weights"]["revision"] == REVISION
    assert receipt["versions"] == {"mineru": "3.4.4"}
    assert receipt["revision_attested"] is True
    assert receipt["markdown_sha256"] == hashlib.sha256(pipeline.text.encode()).hexdigest()
    assert receipt["page_index"] == 2 and receipt["lang"] is None


@pytest.mark.parametrize(
    "harness", [dict(recipe=_recipe("c0-mineru-pipeline-lang-ko"))], indirect=True
)
def test_the_named_korean_recipe_maps_ko_and_only_ko(harness: Any) -> None:
    pipeline, _, payload = harness
    _client(payload)
    _client({**payload, "language": "en"})
    assert [call[3] for call in pipeline.calls] == ["korean", None]


def test_the_revision_is_attested_by_the_server_not_echoed(harness: Any) -> None:
    """Mutant: a server that echoes ``X-AKC-Model-Revision`` would let this call succeed."""
    pipeline, transport, payload = harness
    with pytest.raises(RunnerUnavailable, match="non-200"):
        _client(payload, revision=OTHER_REVISION)
    assert pipeline.calls == []
    assert transport.seen[0][0] == 409
    assert json.loads(transport.seen[0][1]) == {"error": "model_revision_mismatch"}


@pytest.mark.parametrize(
    "harness",
    [dict(recipe=_recipe(model={**_recipe()["model"], "revision": OTHER_REVISION}))],
    indirect=True,
)
def test_a_server_with_other_weights_refuses_the_pinned_revision(harness: Any) -> None:
    pipeline, transport, payload = harness
    with pytest.raises(RunnerUnavailable):
        _client(payload)
    assert pipeline.calls == [] and transport.seen[0][0] == 409


def test_another_provider_is_refused(harness: Any) -> None:
    pipeline, transport, payload = harness
    with pytest.raises(RunnerUnavailable):
        _client(payload, provider="olmocr_2")
    assert pipeline.calls == []
    assert json.loads(transport.seen[0][1]) == {"error": "provider_mismatch"}


@pytest.mark.parametrize("harness", [dict(token=_BEARER)], indirect=True)
def test_a_configured_token_is_required(harness: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline, transport, payload = harness
    with pytest.raises(RunnerUnavailable):
        _client(payload)  # no token in the client's environment
    monkeypatch.setenv(base.PROVIDER_CREDENTIAL, "c0-test-token-wrong")
    with pytest.raises(RunnerUnavailable):
        _client(payload)
    assert [s for s, _, _ in transport.seen] == [401, 401]
    assert pipeline.calls == []
    monkeypatch.setenv(base.PROVIDER_CREDENTIAL, _BEARER)
    assert _client(payload)["text"] == pipeline.text
    assert len(pipeline.calls) == 1


def test_without_a_configured_token_the_server_runs_unauthenticated(harness: Any) -> None:
    """A0 only (5G A0-4): no token configured, none required."""
    pipeline, _, payload = harness
    assert _client(payload)["text"] == pipeline.text


@pytest.mark.parametrize("harness", [dict(max_request_bytes=64)], indirect=True)
def test_an_oversize_request_is_refused_before_it_runs(harness: Any) -> None:
    pipeline, transport, payload = harness
    with pytest.raises(RunnerUnavailable):
        _client(payload)
    assert transport.seen[0][0] == 413 and pipeline.calls == []


def test_a_tampered_body_digest_is_refused(harness: Any) -> None:
    pipeline, transport, payload = harness
    transport.tamper = {"X-AKC-Input-SHA256": "0" * 64}
    with pytest.raises(RunnerUnavailable):
        _client(payload)
    assert transport.seen[0][0] == 400 and pipeline.calls == []
    assert json.loads(transport.seen[0][1]) == {"error": "input_digest_mismatch"}


def test_a_source_that_does_not_match_its_digest_is_refused(harness: Any) -> None:
    pipeline, transport, payload = harness
    bad = {**payload, "source": {**payload["source"], "sha256": "f" * 64}}
    with pytest.raises(RunnerUnavailable):
        _client(bad)
    assert json.loads(transport.seen[0][1]) == {"error": "source_digest_mismatch"}
    assert pipeline.calls == []


def test_a_synthetic_fixture_is_not_a_page(harness: Any) -> None:
    pipeline, transport, _ = harness
    synthetic = build_provider_payload(
        {"benchmark_case_id": "s-1", "is_synthetic": True, "text": "x"}, corpus_root=None
    )
    with pytest.raises(RunnerUnavailable):
        _client(synthetic)
    assert json.loads(transport.seen[0][1]) == {"error": "source_required"}
    assert pipeline.calls == []


def test_a_second_concurrent_page_is_refused_not_queued(harness: Any) -> None:
    pipeline, transport, payload = harness
    pipeline.gate = threading.Event()
    first: dict[str, Any] = {}
    worker = threading.Thread(target=lambda: first.update(result=_client(payload)))
    worker.start()
    assert pipeline.entered.wait(10)
    with pytest.raises(RunnerUnavailable):
        _client(payload)
    assert json.loads(transport.seen[-1][1]) == {"error": "busy"}
    assert transport.seen[-1][0] == 429
    pipeline.gate.set()
    worker.join(10)
    assert first["result"]["text"] == pipeline.text
    assert len(pipeline.calls) == 1  # the refused page never reached the pipeline


@pytest.mark.parametrize(
    "harness",
    [dict(pipeline=FakePipeline(error=RuntimeError("secret detail at /opt/akc/inner.py line 7")))],
    indirect=True,
)
def test_a_pipeline_exception_is_a_failure_row_without_the_trace(
    harness: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    _, transport, payload = harness
    result = _client(payload)
    assert result["failure"] == {"reason": "pipeline_error"}
    assert result["provider"] == "mineru" and result["model_revision"] == REVISION
    assert result["receipt"]["revision_attested"] is False
    assert "text" not in result
    raw = transport.seen[0][1].decode()
    for leak in ("Traceback", "secret detail", "inner.py", "RuntimeError"):
        assert leak not in raw
    assert "secret detail" in capsys.readouterr().err  # kept in the pod log only


@pytest.mark.parametrize(
    "harness",
    [dict(pipeline=FakePipeline(error=srv.PageFailure("pipeline_exit_nonzero")))],
    indirect=True,
)
def test_a_page_failure_keeps_its_reason(harness: Any) -> None:
    _, _, payload = harness
    assert _client(payload)["failure"] == {"reason": "pipeline_exit_nonzero"}


@pytest.mark.parametrize("harness", [dict(pipeline=FakePipeline(text="  \n"))], indirect=True)
def test_an_empty_transcription_is_a_failure_row(harness: Any) -> None:
    _, _, payload = harness
    assert _client(payload)["failure"] == {"reason": "empty_output"}


@pytest.mark.parametrize(
    "harness",
    [dict(pipeline=FakePipeline(text="\\" * 4000), max_response_bytes=6000)],
    indirect=True,
)
def test_the_size_bound_is_on_the_serialized_response(harness: Any) -> None:
    """4,000 text bytes fit 6,000, but JSON doubles every backslash: the wire size is refused.
    Mutant: bounding the text bytes lets this through."""
    pipeline, transport, payload = harness
    result = _client(payload)
    assert result["failure"] == {"reason": "output_too_large"}
    assert len(transport.seen[0][1]) <= 6000
    pipeline.text = "a" * 1000
    assert _client(payload)["text"] == "a" * 1000


@pytest.mark.parametrize(
    "harness", [dict(pipeline=FakePipeline(error=srv.ServiceDown()))], indirect=True
)
def test_a_dead_pipeline_service_is_unavailable_not_a_page_result(harness: Any) -> None:
    """Operational, not semantic: no row is recorded, the page is retried later."""
    _, transport, payload = harness
    with pytest.raises(RunnerUnavailable):
        _client(payload)
    assert transport.seen[0][0] == 503


# --- malformed requests get a fixed answer, never a dropped connection (review r20) -------


def test_a_non_ascii_body_digest_header_is_a_400(harness: Any) -> None:
    pipeline, _, payload = harness
    body = json.dumps(payload).encode()
    status, raw = _raw(
        _port(harness), body, _headers(body, extra={"X-AKC-Input-SHA256": b"\xe9" * 64})
    )
    assert (status, json.loads(raw)) == (400, {"error": "input_digest_mismatch"})
    assert pipeline.calls == []


@pytest.mark.parametrize("length", [b"\xb2", b"1" * 13, b"-1", b"1e3"])
def test_a_content_length_that_is_not_ascii_digits_is_a_411(harness: Any, length: bytes) -> None:
    pipeline, _, payload = harness
    body = json.dumps(payload).encode()
    status, raw = _raw(_port(harness), body, _headers(body, extra={"Content-Length": length}))
    assert (status, json.loads(raw)) == (411, {"error": "length_required"})
    assert pipeline.calls == []


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"language": ["ko"]}, "language_invalid"),
        ({"language": {"ko": 1}}, "language_invalid"),
        ({"page_index": True}, "page_index_invalid"),
        ({"page_index": 0.0}, "page_index_invalid"),
    ],
)
def test_a_malformed_payload_field_is_a_400(harness: Any, change: Any, code: str) -> None:
    pipeline, transport, payload = harness
    with pytest.raises(RunnerUnavailable):
        _client({**payload, **change})
    assert (transport.seen[0][0], json.loads(transport.seen[0][1])) == (400, {"error": code})
    assert pipeline.calls == []


def test_a_non_ascii_source_digest_is_a_400(harness: Any) -> None:
    pipeline, transport, payload = harness
    with pytest.raises(RunnerUnavailable):
        _client({**payload, "source": {**payload["source"], "sha256": "é" * 64}})
    assert json.loads(transport.seen[0][1]) == {"error": "source_digest_mismatch"}
    assert pipeline.calls == []


def _image_payload(payload: dict[str, Any], content_type: str, page: Any) -> dict[str, Any]:
    return {
        **payload,
        "page_index": page,
        "source": {**payload["source"], "content_type": content_type},
    }


def test_an_image_is_one_page(harness: Any) -> None:
    pipeline, transport, payload = harness
    for page in (5, True):
        with pytest.raises(RunnerUnavailable):
            _client(_image_payload(payload, "image/png", page))
    assert [json.loads(raw) for _, raw, _ in transport.seen] == [
        {"error": "page_index_invalid"}
    ] * 2
    assert _client(_image_payload(payload, "image/png", None))["text"] == pipeline.text
    assert pipeline.calls == [(SOURCE, ".png", None, None)]


def test_an_unsupported_content_type_is_a_failure_row_and_never_runs(harness: Any) -> None:
    pipeline, _, payload = harness
    result = _client(_image_payload(payload, "image/tiff", 0))
    assert result["failure"] == {"reason": "page_content_type_unsupported"}
    assert pipeline.calls == []


def test_a_refusal_after_the_length_is_admitted_reaches_the_client(harness: Any) -> None:
    """The body is read off the socket before the answer, so a large body is not reset."""
    pipeline, _, _ = harness
    body = b"x" * (8 * 1024 * 1024)
    status, raw = _raw(_port(harness), body, _headers(body, provider="olmocr_2"))
    assert (status, json.loads(raw)) == (409, {"error": "provider_mismatch"})
    assert pipeline.calls == []


def test_health_names_the_recipe_and_the_attested_revision(harness: Any) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", _port(harness), timeout=10)
    connection.request("GET", "/health")
    value = json.loads(connection.getresponse().read())
    connection.close()
    assert value == {
        "provider": "mineru",
        "model_revision": REVISION,
        "recipe": "c0-mineru-pipeline",
        "receipt_sha256": srv.canonical_sha256(_settings().receipt),
        "busy": False,
        "ready": True,
    }


@pytest.mark.parametrize("harness", [dict(socket_timeout_s=0.5)], indirect=True)
def test_a_stalled_upload_holds_no_slot_and_is_dropped(harness: Any) -> None:
    """The slot is taken only after the body is in; the socket timeout drops the staller.
    Mutants: slot taken before the read (the second page gets 429); no socket timeout (the
    stalled connection stays open)."""
    pipeline, _, payload = harness
    stalled = socket.create_connection(("127.0.0.1", _port(harness)), timeout=5)
    head = "".join(f"{k}: {v}\r\n" for k, v in _headers(b"x" * 1000).items())
    stalled.sendall(f"POST /parse HTTP/1.1\r\nHost: x\r\n{head}\r\n".encode() + b"x" * 10)
    time.sleep(0.2)
    assert _client(payload)["text"] == pipeline.text
    started = time.monotonic()
    assert stalled.recv(1) == b""  # closed by the server, not by our 5 s timeout
    assert time.monotonic() - started < 3
    stalled.close()


# --- the vendor command: each recipe, with a fake tool ----------------------------------------

FAKE_TOOL = r"""
import json, os, sys, time
args = sys.argv[1:]
def after(*flags):
    for flag in flags:
        if flag in args:
            return args[args.index(flag) + 1]
source = after("-p", "-i", "--source")  # C1's client names only the page file
out = after("-o", "--save_path") or os.path.join(os.path.dirname(source), "out")
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": args, "source": open(source, "rb").read().hex()}) + "\n")
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "sleep":
    time.sleep(3)
    open(os.environ["FAKE_LATE"], "w").close()
    sys.exit(0)
target = os.path.join(out, "page", "ocr")
os.makedirs(target, exist_ok=True)
text = "# page from the fake tool\n"
if mode == "env":
    text = json.dumps(sorted(os.environ))
if mode == "big":
    text = "x" * 4096
for n in range({"none": 0, "two": 2}.get(mode, 1)):
    with open(os.path.join(target, f"page{n}.md"), "w", encoding="utf-8") as f:
        f.write(text)
if mode == "grandchild":  # outlives the command, in the command's process group
    import subprocess
    late = "import time, sys; time.sleep(2); open(sys.argv[1], 'w').close()"
    subprocess.Popen([sys.executable, "-c", late, os.environ["FAKE_LATE"]])
if mode == "exit3":
    sys.exit(3)
"""


class FakeService:
    def __init__(self) -> None:
        self.up = True
        self.recovered = 0

    def ready(self) -> bool:
        return self.up

    def available(self) -> bool:
        return self.up

    def recover(self) -> None:
        self.recovered += 1
        self.up = False


def _faked(recipe: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    tool = tmp_path / "fake_tool.py"
    tool.write_text(FAKE_TOOL, encoding="utf-8")
    faked = copy.deepcopy(recipe)
    faked["argv"] = [sys.executable, str(tool), *recipe["argv"]]
    return faked


def _env(tmp_path: Path, mode: str = "ok") -> dict[str, str]:
    return {
        **os.environ,
        "FAKE_LOG": str(tmp_path / "argv.jsonl"),
        "FAKE_MODE": mode,
        "FAKE_LATE": str(tmp_path / "late"),
    }


def _calls(tmp_path: Path) -> list[dict[str, Any]]:
    log = tmp_path / "argv.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _expected_argv(recipe: dict[str, Any], page: int | None, lang: str | None) -> list[str]:
    argv = list(recipe["argv"])
    if page is not None and recipe["page_argv"] is not None:
        argv += [a.format(page=page) for a in recipe["page_argv"]]
    if lang is not None:
        argv += [a.format(lang=lang) for a in recipe["lang_argv"]]
    return argv


@pytest.mark.parametrize("path", RECIPES, ids=[p.stem for p in RECIPES])
def test_each_recipe_round_trips_through_the_real_client(
    path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recipe = srv.load_recipe(path)
    monkeypatch.delenv(base.PROVIDER_CREDENTIAL, raising=False)
    page = 0 if recipe["page_argv"] is None else 2
    payload = _case(tmp_path, page_index=page)
    service = FakeService()
    pipeline = srv.command_pipeline(_faked(recipe, tmp_path), service, _env(tmp_path))
    revision = recipe["model"]["revision"]
    for server in _serve(_settings(recipe), pipeline, service.ready):
        monkeypatch.setattr(base, "post_bytes", Loopback(server.server_address[1]))
        result = _client(payload, revision=revision, provider=recipe["provider"])
    assert result["provider"] == recipe["provider"] and result["model_revision"] == revision
    assert result["text"] == "# page from the fake tool\n"
    assert result["metrics"]["receipt"]["recipe"]["name"] == recipe["name"]
    assert result["metrics"]["receipt"]["recipe"]["sha256"] == srv.canonical_sha256(recipe)
    (call,) = _calls(tmp_path)
    assert bytes.fromhex(call["source"]) == SOURCE
    lang = recipe["lang_by_language"].get("ko")
    expected = _expected_argv(recipe, page, lang)
    work = Path(call["argv"][expected.index("{source}")]).parent
    assert call["argv"] == [a.format(source=work / "page.pdf", out=work / "out") for a in expected]
    assert service.recovered == 0


def test_the_recipes_say_what_each_slot_runs() -> None:
    by_name = {p.stem: srv.load_recipe(p) for p in RECIPES}
    assert set(by_name) == {
        "c0-mineru-pipeline",
        "c0-mineru-pipeline-lang-ko",
        "c1-paddleocr-vl",
        "c3-mineru-vlm",
    }
    c0, c3, c1 = by_name["c0-mineru-pipeline"], by_name["c3-mineru-vlm"], by_name["c1-paddleocr-vl"]
    pairs = {c0["argv"][i]: c0["argv"][i + 1] for i in range(len(c0["argv"]) - 1)}
    assert pairs["-b"] == "pipeline" and pairs["-m"] == "ocr" and c0["lang_by_language"] == {}
    pairs = {c3["argv"][i]: c3["argv"][i + 1] for i in range(len(c3["argv"]) - 1)}
    assert pairs["-b"] == "vlm-engine" and c3["packages"]["mineru"] == c0["packages"]["mineru"]
    assert c3["model"]["revision"] == "bff20d4ae2bf202df9f45284b4d43681555a97ed"
    assert c1["model"]["revision"] == "c5630abae1d940eafe0697512a0325494b02ab42"
    # C1's vendor arguments live in its service (paddleocr-vl-akc/test_paddleocr_vl_service.py
    # holds them equal to the production adapter's); the per-page command is its client
    service = c1["service"]["argv"]
    pairs = {service[i]: service[i + 1] for i in range(len(service) - 1)}
    assert service[1:3] == ["/opt/akc/paddleocr_vl_service.py", "serve"]
    assert (pairs["--engine"], pairs["--device"]) == ("paddle", "gpu:0")
    assert c1["argv"][1:3] == ["/opt/akc/paddleocr_vl_service.py", "page"]
    for recipe in by_name.values():
        for key in ("model", *(f"aux{i}" for i in range(len(recipe["aux_models"])))):
            model = recipe["model"] if key == "model" else recipe["aux_models"][int(key[3:])]
            if model["manifest"] and model["manifest"].startswith("/opt/akc/recipes/"):
                local = _HERE / "recipes" / Path(model["manifest"]).name
                manifest = json.loads(local.read_text(encoding="utf-8"))
                assert (manifest["repo_id"], manifest["revision"]) == (
                    model["repo_id"],
                    model["revision"],
                )
                assert manifest["file_count"] == len(manifest["files"])
                assert manifest["total_bytes"] == sum(f["size"] for f in manifest["files"])


def test_the_recipes_match_the_registry_rows() -> None:
    rows = yaml.safe_load((_REPO / "infra" / "model-registry" / "models.yaml").read_text("utf-8"))
    by_key = {row["provider_key"]: row for row in rows["releases"]}
    for path in RECIPES:
        recipe = srv.load_recipe(path)
        row = by_key[recipe["provider"]]
        assert (row["upstream_id"], row["upstream_revision"]) == (
            recipe["model"]["repo_id"],
            recipe["model"]["revision"],
        )
        serving = row["runtime"]["serving"]
        assert serving["enabled"] is False and serving["built"] is False
        assert recipe["name"] in serving["recipes"]
        assert serving["runner"] == recipe["provider"] in EXTERNAL_RUNNERS
        assert serving["attested_revision"] == recipe["model"]["revision"]
        assert serving["page_timeout_s"] == recipe["timeout_s"] == srv.PAGE_TIMEOUT_S
        assert serving.get("includes_model_load", False) is (recipe["service"] is None)


@pytest.mark.parametrize(
    ("mode", "reason"), [("none", "pipeline_output_missing"), ("two", "pipeline_output_missing")]
)
def test_a_run_without_exactly_one_output_is_a_page_failure(
    tmp_path: Path, mode: str, reason: str
) -> None:
    service = FakeService()
    run = srv.command_pipeline(_faked(_recipe(), tmp_path), service, _env(tmp_path, mode))
    with pytest.raises(srv.PageFailure) as caught:
        run(SOURCE, ".pdf", 0, None)
    assert caught.value.reason == reason
    assert service.recovered == 0  # the command finished: nothing is left running


def test_a_non_zero_exit_is_a_failure_even_with_an_output_file(tmp_path: Path) -> None:
    """Mutant: ignoring the return code would return the file the failed run left behind."""
    service = FakeService()
    run = srv.command_pipeline(_faked(_recipe(), tmp_path), service, _env(tmp_path, "exit3"))
    with pytest.raises(srv.PageFailure) as caught:
        run(SOURCE, ".pdf", 0, None)
    assert caught.value.reason == "pipeline_exit_nonzero"
    assert service.recovered == 1  # the service may still be working on what the client left


def test_a_timed_out_page_is_killed_and_the_server_answers_503_until_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutants: the command left running (the late file appears); no recovery (the next page
    would run while the service still works on the abandoned one)."""
    recipe = _faked(_recipe(timeout_s=0.5), tmp_path)
    service = FakeService()
    pipeline = srv.command_pipeline(recipe, service, _env(tmp_path, "sleep"))
    monkeypatch.delenv(base.PROVIDER_CREDENTIAL, raising=False)
    payload = _case(tmp_path)
    for server in _serve(_settings(), pipeline, service.ready):
        transport = Loopback(server.server_address[1])
        monkeypatch.setattr(base, "post_bytes", transport)
        assert _client(payload)["failure"] == {"reason": "page_timeout"}
        assert service.recovered == 1
        with pytest.raises(RunnerUnavailable):
            _client(payload)
        assert (transport.seen[-1][0], json.loads(transport.seen[-1][1])) == (
            503,
            {"error": "pipeline_unavailable"},
        )
        assert len(_calls(tmp_path)) <= 1  # nothing ran while recovering
    time.sleep(3.5)
    assert not (tmp_path / "late").exists()


def test_the_command_is_not_started_while_the_service_is_down(tmp_path: Path) -> None:
    service = FakeService()
    service.up = False
    run = srv.command_pipeline(_faked(_recipe(), tmp_path), service, _env(tmp_path))
    with pytest.raises(srv.ServiceDown):
        run(SOURCE, ".pdf", 0, None)
    assert _calls(tmp_path) == []


@pytest.mark.parametrize("harness", [dict(recipe=_recipe("c1-paddleocr-vl"))], indirect=True)
def test_a_recipe_without_page_selection_refuses_a_later_page(harness: Any) -> None:
    pipeline, transport, payload = harness
    with pytest.raises(RunnerUnavailable):
        _client(
            payload,
            revision=_recipe("c1-paddleocr-vl")["model"]["revision"],
            provider="paddleocr_vl_1_6",
        )
    assert json.loads(transport.seen[0][1]) == {"error": "page_index_unsupported"}
    assert pipeline.calls == []


# --- recipes, versions and weights at start ---------------------------------------------------


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"extra": 1}, "recipe keys"),
        (
            {"model": {"repo_id": "r", "revision": "main", "dir": "d", "manifest": "m"}},
            "40-character",
        ),
        ({"argv": ["tool", "{source}", "{secret}"]}, "names a field"),
        ({"lang_argv": None}, "needs lang_argv"),
        (
            {"service": {"argv": ["x"], "health_url": "http://10.0.0.1/h", "startup_timeout_s": 1}},
            "loopback",
        ),
        ({"timeout_s": 0}, "timeout_s"),
    ],
)
def test_a_malformed_recipe_is_refused(
    tmp_path: Path, change: dict[str, Any], message: str
) -> None:
    recipe = {**_recipe("c0-mineru-pipeline-lang-ko"), **change}
    path = tmp_path / "r.json"
    path.write_text(json.dumps(recipe), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        srv.load_recipe(path)


def test_a_pinned_package_must_be_installed_at_its_version() -> None:
    assert srv.installed_versions({"pytest": None}, [])["pytest"] == pytest.__version__
    with pytest.raises(SystemExit, match="recipe pins"):
        srv.installed_versions({"pytest": "0.0.1"}, [])
    with pytest.raises(SystemExit, match="not installed"):
        srv.installed_versions({"akc-no-such-package": None}, [])


def _tree(tmp_path: Path, name: str, revision: str) -> dict[str, Any]:
    root = tmp_path / name
    root.mkdir()
    data = b"weights of " + name.encode()
    (root / "w.bin").write_bytes(data)
    manifest = {
        "repo_id": f"org/{name}",
        "revision": revision,
        "file_count": 1,
        "files": [{"path": "w.bin", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}],
    }
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return {"repo_id": f"org/{name}", "revision": revision, "dir": str(root), "manifest": str(path)}


def test_the_weights_are_verified_before_serving(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    model = _tree(tmp_path, "main", REVISION)
    aux = {"role": "layout", **_tree(tmp_path, "layout", OTHER_REVISION)}
    manifest_sha = hashlib.sha256(Path(model["manifest"]).read_bytes()).hexdigest()
    aux_sha = hashlib.sha256(Path(aux["manifest"]).read_bytes()).hexdigest()
    assert srv.verified_weights(_recipe(model=model, aux_models=[aux])) == {
        "model": manifest_sha,
        "layout": aux_sha,
    }
    assert f"org/main@{REVISION} manifest {manifest_sha}" in capsys.readouterr().out
    (Path(aux["dir"]) / "w.bin").write_bytes(b"changed")
    with pytest.raises(SystemExit, match="layout: weights differ"):
        srv.verified_weights(_recipe(model=model, aux_models=[aux]))
    with pytest.raises(SystemExit, match="another repository or revision"):
        srv.verified_weights(_recipe(model={**model, "revision": OTHER_REVISION}))


def test_an_unpinned_model_refuses_to_serve(tmp_path: Path) -> None:
    """An aux model without a pinned repository: the server does not start."""
    c1 = _recipe("c1-paddleocr-vl")
    assert [a["role"] for a in c1["aux_models"]] == ["layout_detection"]
    unpinned = [{**c1["aux_models"][0], "repo_id": None, "revision": None}]
    model = _tree(tmp_path, "main", c1["model"]["revision"])
    with pytest.raises(SystemExit, match="layout_detection: not pinned"):
        srv.verified_weights({**c1, "model": model, "aux_models": unpinned})


def test_the_debian_packages_are_pinned_by_version() -> None:
    text = (_HERE / "Dockerfile").read_text(encoding="utf-8")
    install = text.split("apt-get install --yes --no-install-recommends", 1)[1].split("&&", 1)[0]
    packages = install.replace("\\", " ").split()
    assert packages == ["libgl1=1.6.0-1", "libglib2.0-0=2.74.6-2+deb12u9"]
    assert "snapshot.debian.org/archive/debian/20261116T000000Z" in text


# --- baked weights -------------------------------------------------------------------------


def test_the_baked_manifest_pins_the_registry_revision() -> None:
    manifest = json.loads((_HERE / "weights-manifest.json").read_text(encoding="utf-8"))
    assert manifest["repo_id"] == "opendatalab/PDF-Extract-Kit-1.0"
    assert manifest["revision"] == REVISION
    assert manifest["file_count"] == len(manifest["files"])
    assert manifest["total_bytes"] == sum(f["size"] for f in manifest["files"])


def test_the_weights_check_refuses_any_difference(tmp_path: Path) -> None:
    big, small = b"weights" * 100, b'{"a": 1}\n'
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "w.safetensors").write_bytes(big)
    (tmp_path / "models" / "config.json").write_bytes(small)
    blob = hashlib.sha1(b"blob %d\0" % len(small) + small, usedforsecurity=False).hexdigest()
    manifest = {
        "files": [
            {
                "path": "models/w.safetensors",
                "size": len(big),
                "sha256": hashlib.sha256(big).hexdigest(),
            },
            {"path": "models/config.json", "size": len(small), "git_blob_sha1": blob},
        ]
    }
    assert weights.verify_tree(tmp_path, manifest) == []
    (tmp_path / "models" / "w.safetensors").write_bytes(big[:-1] + b"X")
    assert weights.verify_tree(tmp_path, manifest) == ["digest differs models/w.safetensors"]
    (tmp_path / "models" / "w.safetensors").write_bytes(big)
    (tmp_path / "models" / "config.json").write_bytes(b'{"a": 2}\n')
    assert weights.verify_tree(tmp_path, manifest) == ["digest differs models/config.json"]
    (tmp_path / "models" / "config.json").write_bytes(small)
    (tmp_path / "extra.bin").write_bytes(b"x")
    assert weights.verify_tree(tmp_path, manifest) == ["unexpected file extra.bin"]
    (tmp_path / "extra.bin").unlink()
    (tmp_path / "models" / "config.json").unlink()
    assert weights.verify_tree(tmp_path, manifest) == ["missing file models/config.json"]


# --- round 2: every request field bounded, fuzzed (lead decision B) ---------------------------


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"benchmark_case_id": "c" * 257}, "case_id_invalid"),
        ({"benchmark_case_id": "page\n0001"}, "case_id_invalid"),
        ({"benchmark_case_id": "페이지-1"}, "case_id_invalid"),
        ({"benchmark_case_id": 7}, "case_id_invalid"),
        ({"page_index": 10_000}, "page_index_invalid"),
        ({"page_index": 10**30}, "page_index_invalid"),
        ({"page_index": -1}, "page_index_invalid"),
    ],
)
def test_an_unbounded_request_field_is_a_400_never_a_page(
    harness: Any, change: dict[str, Any], code: str
) -> None:
    """Mutants: no length bound on the case id (echoed unbounded); no upper bound on the page
    index (reaches the vendor command)."""
    pipeline, transport, payload = harness
    with pytest.raises(RunnerUnavailable):
        _client({**payload, **change})
    assert (transport.seen[0][0], json.loads(transport.seen[0][1])) == (400, {"error": code})
    assert pipeline.calls == []
    case_id = {**payload, "benchmark_case_id": "c" * 256, "page_index": 9999}
    assert _client(case_id)["benchmark_case_id"] == "c" * 256  # the bounds are inclusive
    assert pipeline.calls[-1][2] == 9999


def test_a_content_type_that_is_not_a_short_ascii_token_is_a_400(harness: Any) -> None:
    """The content type is echoed in the receipt of a failure row, so it is bounded too."""
    pipeline, transport, payload = harness
    for value in ("x/" + "y" * 200, "image/p\x00ng"):
        with pytest.raises(RunnerUnavailable):
            _client(_image_payload(payload, value, None))
    assert [json.loads(raw) for _, raw, _ in transport.seen] == [
        {"error": "content_type_invalid"}
    ] * 2
    assert pipeline.calls == []


def test_two_content_lengths_are_a_411(harness: Any) -> None:
    pipeline, _, payload = harness
    body = json.dumps(payload).encode()
    connection = http.client.HTTPConnection("127.0.0.1", _port(harness), timeout=10)
    try:
        connection.putrequest("POST", "/parse", skip_accept_encoding=True)
        for key, value in _headers(body).items():
            connection.putheader(key, value)
        connection.putheader("Content-Length", "1")
        connection.endheaders()
        connection.send(body)
        response = connection.getresponse()
        status, raw = response.status, response.read()
    finally:
        connection.close()
    assert (status, json.loads(raw)) == (411, {"error": "length_required"})
    assert pipeline.calls == []


@pytest.mark.parametrize(
    "harness",
    [dict(receipt={"padding": "p" * 5000}, max_response_bytes=4000)],
    indirect=True,
)
def test_no_answer_leaves_the_server_above_the_response_bound(harness: Any) -> None:
    """The bound is enforced where every answer is written, not only on a successful page: a
    failure row that would exceed it is refused as a 500. Mutant: the bound only in run_page."""
    pipeline, transport, payload = harness
    pipeline.error = srv.PageFailure("pipeline_exit_nonzero")
    with pytest.raises(RunnerUnavailable):
        _client(payload)
    status, raw, _ = transport.seen[0]
    assert (status, json.loads(raw)) == (500, {"error": "response_too_large"})


_FUZZ_VALUES: list[Any] = [
    None,
    True,
    False,
    0,
    -1,
    1,
    9999,
    10_000,
    10**30,
    1.5,
    float("nan"),
    float("inf"),
    "",
    "ko",
    "en",
    "korean",
    "application/pdf",
    "image/png",
    "é",
    "\x00",
    "‮",
    "x" * 300,
    "z" * 20_000,
    "{page}",
    "{source}",
    [],
    ["ko"],
    {},
    {"a": 1},
]
_FUZZ_FIELDS = [
    ("benchmark_case_id",),
    ("page_index",),
    ("language",),
    ("claim_class",),
    ("source",),
    ("source", "content_type"),
    ("source", "sha256"),
    ("source", "bytes_base64"),
    ("source", "filename"),
    ("extra_field",),
]
# Every fixed refusal code the server can send: read from its own source.
_FIXED_CODES = set(
    re.findall(
        r'Refused\(\d+, "([a-z0-9_]+)"\)', (_HERE / "mineru_akc_server.py").read_text("utf-8")
    )
)


def _changed(payload: dict[str, Any], changes: Any) -> dict[str, Any]:
    value = copy.deepcopy(payload)
    for path, new in changes:
        target = value
        if len(path) == 2:
            if not isinstance(target.get(path[0]), dict):
                continue
            target = target[path[0]]
        target[path[-1]] = new
    return value


def _fuzz_cases(payload: dict[str, Any]) -> Iterator[Any]:
    """Every value as the whole payload, every value in every field, and three deterministic
    value pairs for every pair of fields (454 requests)."""
    yield from _FUZZ_VALUES  # not an object at all
    for path in _FUZZ_FIELDS:
        for new in _FUZZ_VALUES:
            yield _changed(payload, [(path, new)])
    n = len(_FUZZ_VALUES)
    for i, (a, b) in enumerate(itertools.combinations(_FUZZ_FIELDS, 2)):
        for k in range(3):
            pair = [(a, _FUZZ_VALUES[(7 * i + k) % n]), (b, _FUZZ_VALUES[(11 * i + 5 * k) % n])]
            yield _changed(payload, pair)


@pytest.mark.parametrize(
    "harness",
    [dict(recipe=_recipe("c0-mineru-pipeline-lang-ko"), max_response_bytes=4000)],
    indirect=True,
)
def test_fuzzed_requests_get_a_fixed_answer_and_reach_the_command_only_bounded(
    harness: Any,
) -> None:
    """Property, over 454 generated payloads (wrong types, huge or non-ASCII strings,
    NaN, out-of-range numbers, format fields, missing parts): every answer is a 200 or a 4xx
    with one fixed code, never above the response bound and never a 500 or a dropped
    connection; a 4xx never reaches the pipeline; and what reaches the pipeline (and so the
    vendor's argv, ``vendor_argv``) is only a bounded page number and a language value of
    the recipe's own mapping. This is the reason the two ``Popen`` calls carry ``# noqa: S603``."""
    pipeline, _, payload = harness
    recipe = _recipe("c0-mineru-pipeline-lang-ko")
    statuses: set[int] = set()
    for case in _fuzz_cases(payload):
        body = json.dumps(case).encode()
        calls = len(pipeline.calls)
        status, raw = _raw(_port(harness), body, _headers(body))
        statuses.add(status)
        assert len(raw) <= 4000
        value = json.loads(raw)
        if status == 200:
            assert len(pipeline.calls) <= calls + 1  # a failure row may come before the run
            assert isinstance(value["benchmark_case_id"], str)
            assert len(value["benchmark_case_id"]) <= srv.MAX_CASE_ID_BYTES
        else:
            assert status == 400, (status, value)
            assert set(value) == {"error"} and value["error"] in _FIXED_CODES
            assert len(pipeline.calls) == calls
    assert statuses == {200, 400}
    for _, suffix, page, lang in pipeline.calls:
        assert suffix in srv.CONTENT_SUFFIX.values()
        assert page is None or (type(page) is int and 0 <= page <= srv.MAX_PAGE_INDEX)
        assert lang is None or lang in recipe["lang_by_language"].values()
        srv.vendor_argv(recipe, Path("s"), Path("o"), page, lang)  # accepted as built


def test_the_vendor_argv_takes_nothing_unbounded_from_a_request() -> None:
    recipe = _recipe("c0-mineru-pipeline-lang-ko")
    argv = srv.vendor_argv(recipe, Path("s.pdf"), Path("o"), 3, "korean")
    assert argv == [
        *(a.format(source=Path("s.pdf"), out=Path("o")) for a in recipe["argv"]),
        "-s",
        "3",
        "-e",
        "3",
        "-l",
        "korean",
    ]
    for page, lang in ((10_000, None), (True, None), (-1, None), (None, "ko"), (None, "x")):
        with pytest.raises(ValueError):
            srv.vendor_argv(recipe, Path("s.pdf"), Path("o"), page, lang)


# --- round 2: the command, its group and its output -------------------------------------------


@pytest.mark.parametrize(
    ("mode", "recovered"), [("ok", 0), ("exit3", 1), ("none", 0), ("sleep", 1)]
)
def test_the_command_group_is_killed_after_every_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, recovered: int
) -> None:
    """Success, failure, no output and timeout alike. Mutant: killing only on timeout."""
    killed: list[int] = []
    real = srv._kill_group

    def counted(process: Any) -> None:
        killed.append(process.pid)
        real(process)

    monkeypatch.setattr(srv, "_kill_group", counted)
    service = FakeService()
    recipe = _faked(_recipe(timeout_s=1), tmp_path)
    run = srv.command_pipeline(recipe, service, _env(tmp_path, mode))
    with contextlib.suppress(srv.PageFailure):
        run(SOURCE, ".pdf", 0, None)
    assert len(killed) == 1 and service.recovered == recovered


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX")
def test_a_grandchild_that_outlives_a_successful_command_is_killed(tmp_path: Path) -> None:
    service = FakeService()
    run = srv.command_pipeline(_faked(_recipe(), tmp_path), service, _env(tmp_path, "grandchild"))
    assert run(SOURCE, ".pdf", 0, None) == "# page from the fake tool\n"
    time.sleep(3)
    assert not (tmp_path / "late").exists()


def test_an_oversize_output_file_is_refused_without_reading_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: reading the file before checking its size (the read below would fail)."""
    service = FakeService()
    run = srv.command_pipeline(_faked(_recipe(), tmp_path), service, _env(tmp_path, "big"), 1000)

    def no_read(*_: Any, **__: Any) -> str:
        raise AssertionError("the oversize file was read")

    monkeypatch.setattr(Path, "read_text", no_read)
    with pytest.raises(srv.PageFailure) as caught:
        run(SOURCE, ".pdf", 0, None)
    assert caught.value.reason == "output_too_large"


def test_main_gives_the_vendor_command_no_bearer_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``main()`` itself: the server gets the token, the vendor command's environment does not.
    Mutant: dropping the ``pop`` of the bearer variable."""
    recipe = {
        **_faked(_recipe("c1-paddleocr-vl"), tmp_path),
        "env": {"AKC_RECIPE_ENV": "1"},
        "service": None,  # the subject is the command's environment, not a service start
    }
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(recipe), encoding="utf-8")
    captured: dict[str, Any] = {}

    class Stub:
        def serve_forever(self) -> None:
            return None

    def fake_make_server(settings: Any, pipeline: Any, address: Any, ready: Any) -> Stub:
        captured.update(settings=settings, pipeline=pipeline)
        return Stub()

    monkeypatch.setattr(srv, "installed_versions", lambda packages, absent: {})
    monkeypatch.setattr(srv, "verified_weights", lambda r: _manifests(r))
    monkeypatch.setattr(srv, "make_server", fake_make_server)
    fake = _env(tmp_path, "env")
    for key in ("FAKE_LOG", "FAKE_MODE", "FAKE_LATE"):
        monkeypatch.setenv(key, fake[key])
    monkeypatch.setenv(srv.BEARER_ENV, _BEARER)
    srv.main(["--recipe", str(path), "--port", "0"])
    assert captured["settings"].token == _BEARER
    names = json.loads(captured["pipeline"](SOURCE, ".pdf", 0, None))
    assert "AKC_RECIPE_ENV" in names and "FAKE_LOG" in names
    assert srv.BEARER_ENV not in names


# --- round 2: the real Service class -----------------------------------------------------------

HEALTH = r"""
import http.server, os, sys
open(os.environ["PIDLOG"], "a").write(f"{os.getpid()}\n")
if os.environ.get("HEALTH_FAIL_AFTER") and os.path.exists(os.environ["HEALTH_FAIL_AFTER"]):
    sys.exit(4)
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, *a):
        pass
http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
"""


def _wait(predicate: Any, seconds: float = 30) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_the_real_service_restarts_after_recover_and_once_after_dying_on_its_own(
    tmp_path: Path,
) -> None:
    """Mutants: no restart when the child dies between pages (503 for ever while the pod
    looks alive); restarting again after a failed restart."""
    script = tmp_path / "health.py"
    script.write_text(HEALTH, encoding="utf-8")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    broken = tmp_path / "broken"
    env = {**os.environ, "PIDLOG": str(tmp_path / "pids"), "HEALTH_FAIL_AFTER": str(broken)}
    spec = {
        "argv": [sys.executable, str(script), str(port)],
        "health_url": f"http://127.0.0.1:{port}/",
        "startup_timeout_s": 20,
    }
    service = srv.Service(spec, env)
    try:
        assert service.start() and service.ready() and service.available()
        first = service.child
        assert first is not None
        service.recover()  # after a timed-out page
        assert not service.ready() and not service.available()
        assert _wait(service.ready)
        assert first.poll() is not None and service.child is not first
        second = service.child
        assert second is not None
        second.kill()  # dies on its own between pages
        second.wait()
        assert not service.available()  # this page: 503, one restart begins
        assert _wait(service.ready) and service.child is not second
        broken.touch()  # from now on the child cannot start
        assert service.child is not None
        service.child.kill()
        service.child.wait()
        assert not service.available()
        assert _wait(lambda: service.gave_up)
        starts = len((tmp_path / "pids").read_text().split())
        assert not service.available() and not service.ready()
        time.sleep(0.5)
        assert len((tmp_path / "pids").read_text().split()) == starts  # no second attempt
    finally:
        if service.child is not None:
            srv._kill_group(service.child)


def test_no_service_is_always_available() -> None:
    no = srv.NoService()
    assert no.ready() and no.available() and no.recover() is None


# --- round 2: C1, C3, the registry key and the receipt ----------------------------------------


def test_c3_is_served_through_its_registry_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``EXTERNAL_RUNNERS["mineru_vlm"]`` is the external-protocol runner: it sends provider
    ``mineru_vlm`` and the pinned revision, and the C3 recipe's server answers it."""
    recipe = _recipe("c3-mineru-vlm")
    monkeypatch.delenv(base.PROVIDER_CREDENTIAL, raising=False)
    service = FakeService()
    pipeline = srv.command_pipeline(_faked(recipe, tmp_path), service, _env(tmp_path))
    for server in _serve(_settings(recipe), pipeline, service.ready):
        transport = Loopback(server.server_address[1])
        monkeypatch.setattr(base, "post_bytes", transport)
        result = EXTERNAL_RUNNERS["mineru_vlm"](
            _case(tmp_path),
            endpoint=ENDPOINT,
            revision=recipe["model"]["revision"],
            allow_network=True,
        )
    _, _, headers = transport.seen[0]
    assert headers["X-AKC-Benchmark-Provider"] == "mineru_vlm"
    assert headers["X-AKC-Model-Revision"] == recipe["model"]["revision"]
    assert result["provider"] == "mineru_vlm" and "failure" not in result


def test_the_receipt_says_which_recipes_load_models_per_page_and_every_manifest() -> None:
    c1 = _recipe("c1-paddleocr-vl")
    receipt = srv.recipe_receipt(c1, {}, {"model": "a" * 64, "layout_detection": "b" * 64})
    assert receipt["includes_model_load"] is False  # round 3: C1's service keeps them loaded
    assert srv.recipe_receipt({**c1, "service": None}, {}, _manifests(c1))["includes_model_load"]
    assert receipt["weights"]["aux"] == [
        {
            "role": "layout_detection",
            "repo_id": "PaddlePaddle/PP-DocLayoutV3",
            "revision": "241f8bdfc77a7c7bee915a5057aaee58c235a8d3",
            "manifest_sha256": "b" * 64,
        }
    ]
    for name in ("c0-mineru-pipeline", "c3-mineru-vlm"):
        assert (
            srv.recipe_receipt(_recipe(name), {}, {"model": "a" * 64})["includes_model_load"]
            is False
        )


def test_c3_names_its_engine_and_refuses_another() -> None:
    c3 = _recipe("c3-mineru-vlm")
    assert c3["absent_packages"] == ["vllm", "lmdeploy"]
    assert c3["options"]["inference_engine"].startswith("transformers")
    assert srv.installed_versions({}, ["akc-no-such-package"]) == {}
    with pytest.raises(SystemExit, match="rules it out"):
        srv.installed_versions({}, ["pytest"])


def test_c1_pins_its_layout_model_and_switches_the_preprocessors_off() -> None:
    c1 = _recipe("c1-paddleocr-vl")
    (layout,) = c1["aux_models"]
    assert (layout["repo_id"], layout["revision"]) == (
        "PaddlePaddle/PP-DocLayoutV3",
        "241f8bdfc77a7c7bee915a5057aaee58c235a8d3",
    )
    service = c1["service"]["argv"]
    pairs = {service[i]: service[i + 1] for i in range(len(service) - 1)}
    assert pairs["--layout-dir"] == layout["dir"] and pairs["--vl-rec-dir"] == c1["model"]["dir"]
    assert "PP-DocLayoutV3" in c1["options"]["layout_model"]
    assert "use_doc_orientation_classify=False" in c1["options"]["doc_preprocessor"]
    assert "use_doc_unwarping=False" in c1["options"]["doc_preprocessor"]
    assert c1["packages"]["paddlex"] == "3.7.2"
    docker = (_HERE.parent / "paddleocr-vl-akc" / "Dockerfile").read_text(encoding="utf-8")
    assert '"paddlex==3.7.2"' in docker and "c1-layout-weights-manifest.json" in docker
    assert "uv pip freeze" in docker and "uv pip list" in docker
    assert "pip inspect" not in docker


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"timeout_s": 100}, "proxy"),
        ({"absent_packages": "vllm"}, "absent_packages"),
        ({"packages": {"mineru": 3}}, "packages"),
    ],
)
def test_a_recipe_the_proxy_would_cut_or_with_bad_package_lists_is_refused(
    tmp_path: Path, change: dict[str, Any], message: str
) -> None:
    path = tmp_path / "r.json"
    path.write_text(json.dumps({**_recipe(), **change}), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        srv.load_recipe(path)


# --- round 3: the recipe loader, by property; C1's page failures --------------------------------

_HOSTILE: list[Any] = [
    None,
    True,
    0,
    -1,
    1.5,
    1e308,
    "",
    "x",
    "main",
    "model",
    "\x00",
    "{source.x}",
    "{out[0]}",
    "{page!r}",
    "{}",
    "/abs/*.md",
    "../*.md",
    "http://127.0.0.1:99999/h",
    [],
    [1],
    ["x", None],
    {},
    {"a": 1},
    {"3": 4},
    {"1": "pipeline_raised"},
]
_RAW_CONSTANTS = ["NaN", "Infinity", "-Infinity", "1e999", '"90"', "true"]


def _paths(value: Any, prefix: tuple[Any, ...] = ()) -> Iterator[tuple[Any, ...]]:
    """Every key and list index in a recipe, depth first (the root itself excluded)."""
    items = value.items() if isinstance(value, dict) else enumerate(value)
    for key, child in items:
        yield (*prefix, key)
        if isinstance(child, (dict, list)) and child:
            yield from _paths(child, (*prefix, key))


def _set(recipe: dict[str, Any], path: tuple[Any, ...], new: Any) -> dict[str, Any]:
    value = copy.deepcopy(recipe)
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = new
    return value


def _usable(recipe: dict[str, Any]) -> None:
    """What the server does with a recipe it accepted, short of running anything."""
    srv.recipe_receipt(recipe, {}, _manifests(recipe))
    srv.canonical_sha256(recipe)
    srv.child_env(recipe, {"PATH": "x"})
    for page in (None, 0, 3):
        for lang in (None, *recipe["lang_by_language"].values()):
            srv.vendor_argv(recipe, Path("s.pdf"), Path("o"), page, lang)
    if recipe["service"] is not None:
        url = urlsplit(recipe["service"]["health_url"])
        assert url.hostname == "127.0.0.1" and url.port is not None
        float(recipe["service"]["startup_timeout_s"])
    assert math.isfinite(recipe["timeout_s"]) and 0 < recipe["timeout_s"] < srv.PROXY_CUT_S
    roles = [aux["role"] for aux in recipe["aux_models"]]
    assert len(set(roles)) == len(roles) and "model" not in roles


@pytest.mark.parametrize("path", RECIPES, ids=[p.stem for p in RECIPES])
def test_a_fuzzed_recipe_is_a_value_error_or_usable(path: Path) -> None:
    """Property, over every field of every shipped recipe replaced by each hostile value (and
    every field removed): ``load_recipe`` raises only ValueError, and whatever it accepts the
    server can use without a type error. The reviewer's probes (a NaN limit, an aux model
    revision ``main``, a role ``model``, a string start-up limit, ``aux_models`` null) are
    single points of this class."""
    recipe = srv.load_recipe(path)
    accepted = refused = 0
    cases: list[str] = []
    for where in _paths(recipe):
        for new in _HOSTILE:
            cases.append(json.dumps(_set(recipe, where, new)))
        if isinstance(where[-1], str):
            trimmed = _set(recipe, where, None)
            parent = trimmed
            for key in where[:-1]:
                parent = parent[key]
            del parent[where[-1]]
            cases.append(json.dumps(trimmed))
    for field in ("timeout_s",) + (("startup_timeout_s",) if recipe["service"] else ()):
        for constant in _RAW_CONSTANTS:
            text = json.dumps(recipe)
            key = f'"{field}": '
            start = text.index(key) + len(key)
            number = re.match(r"[0-9.]+", text[start:])
            assert number is not None
            cases.append(text[:start] + constant + text[start + len(number.group(0)) :])
    for text in cases:
        try:
            loaded = srv.parse_recipe(text)  # load_recipe's check, without a file per case
        except ValueError:
            refused += 1
            continue
        _usable(loaded)
        accepted += 1
    assert refused > 0 and accepted > 0  # both sides of the property were exercised


@pytest.mark.parametrize(
    ("where", "value", "message"),
    [
        (("timeout_s",), "NaN", "not a JSON number"),
        (("timeout_s",), "Infinity", "not a JSON number"),
        (("timeout_s",), "1e999", "proxy"),
        (("timeout_s",), '"90"', "timeout_s"),
        (("service", "startup_timeout_s"), "NaN", "not a JSON number"),
        (("service", "startup_timeout_s"), "1e999", "finite"),
        (("service", "startup_timeout_s"), '"600"', "startup_timeout_s"),
        (("service", "startup_timeout_s"), "true", "startup_timeout_s"),
        (("service", "startup_timeout_s"), "0", "startup_timeout_s"),
        (("service", "startup_timeout_s"), "3600", "startup_timeout_s"),
        (("aux_models",), "null", "aux_models must be a list"),
        (("aux_models",), "{}", "aux_models must be a list"),
        (("aux_models", 0, "revision"), '"main"', "40-character"),
        (("aux_models", 0, "role"), '"model"', "unique name other than 'model'"),
        (("aux_models", 0, "manifest"), "3", "manifest must be a non-empty string"),
        (("service", "page_failure_exits"), '{"1": "pipeline_raised"}', "exit code 2-99"),
        (("service", "page_failure_exits"), '{"3": "Pipeline Raised"}', "exit code 2-99"),
        (("service", "health_url"), '"http://127.0.0.1:99999/health"', "loopback"),
        (("argv", 0), '"{source.__class__}"', "names a field"),
        (("argv", 0), '"{source!r}"', "names a field"),
        (("argv", 0), '"{source:>99}"', "names a field"),
        (("output_glob",), '"/abs/*.md"', "relative pattern"),
        (("output_glob",), '"../*.md"', "inside the output directory"),
        (("name",), "7", "name"),
    ],
)
def test_the_reviewers_recipe_inputs_are_refused(
    tmp_path: Path, where: tuple[Any, ...], value: str, message: str
) -> None:
    recipe = _set(_recipe("c1-paddleocr-vl"), where, "@@VALUE@@")
    path = tmp_path / "r.json"
    path.write_text(json.dumps(recipe).replace('"@@VALUE@@"', value), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        srv.load_recipe(path)


def test_two_aux_models_with_one_role_are_refused(tmp_path: Path) -> None:
    c1 = _recipe("c1-paddleocr-vl")
    path = tmp_path / "r.json"
    path.write_text(json.dumps({**c1, "aux_models": c1["aux_models"] * 2}), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        srv.load_recipe(path)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, "90", True, 0, -1, 100])
def test_a_time_limit_is_a_finite_number_in_range(value: Any) -> None:
    """Whatever reaches the check, not only what JSON text can spell (``parse_recipe`` already
    refuses the NaN and Infinity constants)."""
    with pytest.raises(ValueError, match="finite number of seconds"):
        srv._seconds(value, "timeout_s", srv.PROXY_CUT_S)
    assert srv._seconds(90, "timeout_s", srv.PROXY_CUT_S) == 90.0


@pytest.mark.parametrize(
    ("code", "accepted"),
    [
        ("0", False),
        ("1", False),
        ("01", False),
        ("2", True),
        ("12", True),
        ("99", True),
        ("100", False),
        ("-9", False),
    ],
)
def test_page_failure_exit_codes_are_2_to_99(code: str, accepted: bool) -> None:
    """0 is success and 1 the client's operational failure; neither is a page failure."""
    c1 = _recipe("c1-paddleocr-vl")
    text = json.dumps(_set(c1, ("service", "page_failure_exits"), {code: "pipeline_raised"}))
    if accepted:
        assert srv.parse_recipe(text)["service"]["page_failure_exits"] == {code: "pipeline_raised"}
    else:
        with pytest.raises(ValueError, match="exit code 2-99"):
            srv.parse_recipe(text)


def test_a_mapped_exit_is_a_page_failure_with_its_reason_and_no_restart(tmp_path: Path) -> None:
    """The C1 service answered that the page failed and is idle: the recipe's reason, no
    restart. An unmapped non-zero exit still restarts (``pipeline_exit_nonzero``)."""
    recipe = _faked(_recipe(), tmp_path)
    recipe["service"] = {**recipe["service"], "page_failure_exits": {"3": "pipeline_raised"}}
    service = FakeService()
    run = srv.command_pipeline(recipe, service, _env(tmp_path, "exit3"))
    with pytest.raises(srv.PageFailure) as caught:
        run(SOURCE, ".pdf", 0, None)
    assert (caught.value.reason, service.recovered) == ("pipeline_raised", 0)
    recipe["service"]["page_failure_exits"] = {"4": "page_count_unsupported"}
    run = srv.command_pipeline(recipe, service, _env(tmp_path, "exit3"))
    with pytest.raises(srv.PageFailure) as caught:
        run(SOURCE, ".pdf", 0, None)
    assert (caught.value.reason, service.recovered) == ("pipeline_exit_nonzero", 1)
