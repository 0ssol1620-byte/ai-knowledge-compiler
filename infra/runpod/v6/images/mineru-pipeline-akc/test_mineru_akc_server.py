"""The C0 server against the real client, in process: no GPU, no MinerU, no network.

The registered ``mineru`` runner (``benchmark.runners.base.run_external``) talks to the server
over a loopback socket; only its TLS leg (``post_bytes``: DNS, address check, pinned HTTPS) is
replaced by a plain HTTP connection to 127.0.0.1. Everything the client builds and checks is
its own code.
"""

from __future__ import annotations

import hashlib
import http.client
import importlib.util
import json
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

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


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


srv = _load("mineru_akc_server")
weights = _load("mineru_akc_weights")


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


def _serve(settings: Any, pipeline: FakePipeline) -> Iterator[Any]:
    server = srv.make_server(settings, pipeline, ("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def _settings(**overrides: Any) -> Any:
    receipt = {"recipe": srv.RECIPE, "recipe_sha256": srv.canonical_sha256(srv.RECIPE)}
    return srv.Settings(
        **{"model_revision": REVISION, "token": None, "receipt": receipt, **overrides}
    )


@pytest.fixture
def harness(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[FakePipeline, Loopback, dict[str, Any]]]:
    """(pipeline, transport, payload) with the server running; ``param`` overrides settings."""
    options = dict(getattr(request, "param", {}))
    pipeline = options.pop("pipeline", None) or FakePipeline()
    monkeypatch.delenv(base.PROVIDER_CREDENTIAL, raising=False)
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
    }
    payload = build_provider_payload(case, corpus_root=tmp_path)
    for server in _serve(_settings(**options), pipeline):
        transport = Loopback(server.server_address[1])
        monkeypatch.setattr(base, "post_bytes", transport)
        yield pipeline, transport, payload


def _client(payload: dict[str, Any], revision: str = REVISION, provider: str = "mineru") -> Any:
    return EXTERNAL_RUNNERS[provider](
        payload, endpoint=ENDPOINT, revision=revision, allow_network=True
    )


def test_a_page_round_trips_with_echo_fields_and_a_valid_output(harness: Any) -> None:
    pipeline, transport, payload = harness
    result = _client(payload)
    assert result["provider"] == "mineru"
    assert result["model_revision"] == REVISION
    assert result["benchmark_case_id"] == "page-0001"
    assert result["text"] == pipeline.text
    assert pipeline.calls == [(SOURCE, ".pdf", 2, "korean")]
    errors = list(
        parser_output_validator(_REPO / "benchmark" / "manifest.yaml").iter_errors(result)
    )
    assert errors == []
    receipt = result["metrics"]["receipt"]
    _, _, headers = transport.seen[0]
    assert receipt["input_sha256"] == headers["X-AKC-Input-SHA256"]
    assert receipt["source_sha256"] == hashlib.sha256(SOURCE).hexdigest()
    assert receipt["recipe"] == srv.RECIPE
    assert receipt["recipe_sha256"] == srv.canonical_sha256(srv.RECIPE)
    assert receipt["revision_attested"] is True
    assert receipt["markdown_sha256"] == hashlib.sha256(pipeline.text.encode()).hexdigest()
    assert receipt["page_index"] == 2 and receipt["lang"] == "korean"


def test_a_page_in_another_language_takes_mineru_default_model(harness: Any) -> None:
    pipeline, _, payload = harness
    _client({**payload, "language": "en"})
    assert pipeline.calls[0][3] is None


def test_the_revision_is_attested_by_the_server_not_echoed(harness: Any) -> None:
    """Mutant: a server that echoes ``X-AKC-Model-Revision`` would let this call succeed."""
    pipeline, transport, payload = harness
    with pytest.raises(RunnerUnavailable, match="non-200"):
        _client(payload, revision=OTHER_REVISION)
    assert pipeline.calls == []
    assert transport.seen[0][0] == 409
    assert json.loads(transport.seen[0][1]) == {"error": "model_revision_mismatch"}


@pytest.mark.parametrize("harness", [dict(model_revision=OTHER_REVISION)], indirect=True)
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
    "harness", [dict(pipeline=FakePipeline(text="x" * 64), max_text_bytes=32)], indirect=True
)
def test_an_oversize_transcription_is_a_failure_row(harness: Any) -> None:
    _, _, payload = harness
    assert _client(payload)["failure"] == {"reason": "output_too_large"}


@pytest.mark.parametrize(
    "harness", [dict(pipeline=FakePipeline(error=srv.ServiceDown()))], indirect=True
)
def test_a_dead_pipeline_service_is_unavailable_not_a_page_result(harness: Any) -> None:
    """Operational, not semantic: no row is recorded, the page is retried later."""
    _, transport, payload = harness
    with pytest.raises(RunnerUnavailable):
        _client(payload)
    assert transport.seen[0][0] == 503


# --- the real pipeline adapter, with the click command faked ----------------------------


class FakeCommand:
    def __init__(self, exit_code: int | None = None, outputs: int = 1) -> None:
        self.exit_code = exit_code
        self.outputs = outputs
        self.args: list[str] = []

    def main(self, *, args: list[str], standalone_mode: bool) -> None:
        assert standalone_mode is False
        self.args = args
        source = Path(args[args.index("-p") + 1])
        assert source.read_bytes() == SOURCE
        out = Path(args[args.index("-o") + 1]) / source.stem / "ocr"
        out.mkdir(parents=True)
        for n in range(self.outputs):
            (out / f"{source.stem}{n}.md").write_text("# page\n", encoding="utf-8")
        if self.exit_code is not None:
            raise SystemExit(self.exit_code)


def test_the_adapter_runs_the_documented_cli_against_loopback() -> None:
    command = FakeCommand()
    text = srv.mineru_pipeline(command, lambda: True)(SOURCE, ".pdf", 3, "korean")
    assert text == "# page\n"
    args = command.args
    assert args[args.index("--api-url") + 1] == "http://127.0.0.1:8000"
    pairs = {args[i]: args[i + 1] for i in range(len(args) - 1) if args[i].startswith("-")}
    assert pairs["-b"] == "pipeline" and pairs["-m"] == "ocr"
    assert pairs["-f"] == "true" and pairs["-t"] == "true"
    assert pairs["-s"] == "3" and pairs["-e"] == "3" and pairs["-l"] == "korean"
    image = FakeCommand()
    srv.mineru_pipeline(image, lambda: True)(SOURCE, ".png", None, None)
    assert "-s" not in image.args and "-l" not in image.args


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        (FakeCommand(exit_code=2), "pipeline_exit_nonzero"),
        (FakeCommand(outputs=0), "pipeline_output_missing"),
        (FakeCommand(outputs=2), "pipeline_output_missing"),
    ],
)
def test_the_adapter_turns_a_failed_run_into_a_page_failure(command: Any, reason: str) -> None:
    with pytest.raises(srv.PageFailure) as caught:
        srv.mineru_pipeline(command, lambda: True)(SOURCE, ".pdf", 0, None)
    assert caught.value.reason == reason


def test_the_adapter_refuses_when_the_api_child_is_gone() -> None:
    command = FakeCommand()
    with pytest.raises(srv.ServiceDown):
        srv.mineru_pipeline(command, lambda: False)(SOURCE, ".pdf", 0, None)
    assert command.args == []


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
