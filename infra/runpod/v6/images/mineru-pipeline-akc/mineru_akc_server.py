"""Arena C0: the MinerU 3.4.4 pipeline behind the AKC external-runner protocol (WO-D10-0F).

The mirror of ``benchmark/runners/base.py::external_exchange``. The client POSTs the provider
payload as JSON with ``X-AKC-Benchmark-Provider``, ``X-AKC-Input-SHA256`` (of the body),
``X-AKC-Model-Revision`` and, when configured, ``Authorization: Bearer``; it accepts only a 200
``application/json`` object whose ``provider`` and ``model_revision`` equal what it asked for,
and treats every other status as the provider being unavailable.

So this server answers 200 only for a page it ran: the parser output, or a failure row when the
pipeline failed on the page. A request it will not run (wrong token, size, provider, revision
or digest; a page already running) gets a 4xx with a fixed error code and runs nothing. The
revision it reports is the weights revision baked into the image, never the request header
echoed back. Standard library only; the pipeline is the image's own ``mineru`` command, run in
process against the ``mineru-api`` child this file starts on loopback with the models loaded.
TLS is terminated by the pod proxy in front of it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata
from pathlib import Path
from typing import Any

PROVIDER = "mineru"
ROUTE = "/parse"
BEARER_ENV = "AKC_BENCHMARK_PROVIDER_TOKEN"  # the client's bearer token, same name on the pod
# The client reads a source of up to 64 MiB; base64 and the JSON envelope add about a third.
MAX_REQUEST_BYTES = 96 * 1024 * 1024
# The client refuses a response above 10 MiB; the transcription stays well below it.
MAX_TEXT_BYTES = 8 * 1024 * 1024
API_HOST, API_PORT = "127.0.0.1", 8000  # mineru-api, loopback only
WEIGHTS_MANIFEST = Path("/opt/akc/weights-manifest.json")
# What the pipeline is asked to do, for every page. Backend and method are the recorded FOLYNTA
# recipe (benchmark/runpod_eval/mineru_stage2.py: --backend pipeline --method ocr); formula and
# table are MinerU's documented defaults, stated so the receipt does not depend on them.
RECIPE: dict[str, Any] = {
    "mineru": "3.4.4",
    "backend": "pipeline",
    "method": "ocr",
    "formula": True,
    "table": True,
    # ``-l`` by the payload's language; any other language takes MinerU's default model.
    "lang_by_language": {"ko": "korean"},
}
CONTENT_SUFFIX = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}


class PageFailure(Exception):
    """The pipeline ran and failed on this page: a failure row with this fixed reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ServiceDown(Exception):
    """The pipeline cannot run at all (operational): 503, nothing is recorded for the page."""


class Refused(Exception):
    """A request this server will not run: an HTTP status and a fixed error code."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


# (source bytes, file suffix, 0-based page index or None for an image, ``-l`` value or None)
Pipeline = Callable[[bytes, str, int | None, str | None], str]


@dataclass(frozen=True)
class Settings:
    model_revision: str  # the baked weights revision; the only one this server will attest
    token: str | None
    receipt: dict[str, Any]  # identity carried in every result: recipe, versions, weights
    max_request_bytes: int = MAX_REQUEST_BYTES
    max_text_bytes: int = MAX_TEXT_BYTES


def canonical_sha256(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def page_request(payload: Any) -> tuple[str, bytes, str, int | None, str | None]:
    """(case id, source bytes, content type, page index, ``-l`` value), or Refused."""
    if not isinstance(payload, dict):
        raise Refused(400, "payload_not_object")
    case_id = payload.get("benchmark_case_id")
    if not isinstance(case_id, str) or not case_id:
        raise Refused(400, "case_id_missing")
    source = payload.get("source")
    if payload.get("claim_class") != "approved_internal_source" or not isinstance(source, dict):
        raise Refused(400, "source_required")  # a synthetic fixture has no page to run
    encoded = source.get("bytes_base64")
    try:
        data = base64.b64decode(encoded if isinstance(encoded, str) else "", validate=True)
    except (binascii.Error, ValueError):
        raise Refused(400, "source_not_base64") from None
    declared = source.get("sha256")
    digest = hashlib.sha256(data).hexdigest()
    if not data or not isinstance(declared, str) or not hmac.compare_digest(digest, declared):
        raise Refused(400, "source_digest_mismatch")
    content_type = source.get("content_type")
    if not isinstance(content_type, str):
        raise Refused(400, "content_type_missing")
    index = payload.get("page_index")
    page: int | None = None
    if content_type == "application/pdf":
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise Refused(400, "page_index_invalid")
        page = index
    elif isinstance(index, bool) or index not in (None, 0):
        raise Refused(400, "page_index_invalid")  # an image is one page
    lang = RECIPE["lang_by_language"].get(payload.get("language"))
    return case_id, data, content_type, page, lang


def make_server(
    settings: Settings, pipeline: Pipeline, address: tuple[str, int] = ("0.0.0.0", 8080)
) -> ThreadingHTTPServer:
    busy = threading.Lock()  # one page at a time; a second one is refused, never queued

    def run_page(payload: Any, input_sha256: str) -> dict[str, Any]:
        case_id, data, content_type, page, lang = page_request(payload)
        receipt: dict[str, Any] = {
            **settings.receipt,
            "input_sha256": input_sha256,
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "content_type": content_type,
            "page_index": page,
            "lang": lang,
        }
        started = time.perf_counter()
        suffix = CONTENT_SUFFIX.get(content_type)
        try:
            if suffix is None:
                raise PageFailure("page_content_type_unsupported")
            text = pipeline(data, suffix, page, lang)
            if not isinstance(text, str) or not text.strip():
                raise PageFailure("empty_output")
            encoded = text.encode("utf-8")  # a lone surrogate cannot be stored
            if len(encoded) > settings.max_text_bytes:
                raise PageFailure("output_too_large")
        except ServiceDown:
            raise
        except Exception as exc:
            if not isinstance(exc, PageFailure):
                traceback.print_exc(file=sys.stderr)  # the pod log, never the response body
            receipt["latency_ms"] = (time.perf_counter() - started) * 1000.0
            return {
                "schema_version": "1.0",
                "benchmark_case_id": case_id,
                "provider": PROVIDER,
                "model_revision": settings.model_revision,
                "failure": {
                    "reason": exc.reason if isinstance(exc, PageFailure) else "pipeline_error"
                },
                "receipt": {**receipt, "revision_attested": False},
            }
        latency_ms = (time.perf_counter() - started) * 1000.0
        receipt.update(
            latency_ms=latency_ms,
            markdown_sha256=hashlib.sha256(encoded).hexdigest(),
            revision_attested=True,
        )
        return {
            "schema_version": "1.0",
            "benchmark_case_id": case_id,
            "provider": PROVIDER,
            "model_revision": settings.model_revision,
            "text": text,
            "reading_order": [],
            "blocks": [],
            "generated_claims": [],
            "metrics": {"latency_ms": latency_ms, "receipt": receipt},
            "warnings": [],
        }

    class Handler(BaseHTTPRequestHandler):
        server_version = "akc-mineru-pipeline"
        sys_version = ""

        def _send(self, status: int, value: dict[str, Any]) -> None:
            body = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/health":
                self._send(404, {"error": "not_found"})
                return
            self._send(
                200,
                {
                    "provider": PROVIDER,
                    "model_revision": settings.model_revision,
                    "receipt_sha256": canonical_sha256(settings.receipt),
                    "busy": busy.locked(),
                },
            )

        def do_POST(self) -> None:
            unread = 0
            try:
                unread = self._admitted_length()
                if not busy.acquire(blocking=False):
                    raise Refused(429, "busy")
                try:
                    body, unread = self.rfile.read(unread), 0
                    value = self._run(body)
                finally:
                    busy.release()
            except Refused as refused:
                # an admitted body is read off the socket so the client sees the answer
                while unread > 0:
                    chunk = self.rfile.read(min(unread, 1 << 20))
                    unread = unread - len(chunk) if chunk else 0
                self._send(refused.status, {"error": refused.code})
                return
            self._send(200, value)

        def _admitted_length(self) -> int:
            """The checks that need no body; returns the body length, or Refused."""
            if self.path != ROUTE:
                raise Refused(404, "not_found")
            if settings.token is not None:
                expected = f"Bearer {settings.token}".encode()
                given = (self.headers.get("Authorization") or "").encode()
                if not hmac.compare_digest(given, expected):
                    raise Refused(401, "unauthorized")
            length = self.headers.get("Content-Length") or ""
            if self.headers.get("Transfer-Encoding") is not None or not length.isdigit():
                raise Refused(411, "length_required")
            if int(length) > settings.max_request_bytes:
                raise Refused(413, "request_too_large")
            if self.headers.get("X-AKC-Benchmark-Provider") != PROVIDER:
                raise Refused(409, "provider_mismatch")
            if self.headers.get("X-AKC-Model-Revision") != settings.model_revision:
                raise Refused(409, "model_revision_mismatch")
            return int(length)

        def _run(self, body: bytes) -> dict[str, Any]:
            declared = self.headers.get("X-AKC-Input-SHA256") or ""
            if not hmac.compare_digest(hashlib.sha256(body).hexdigest(), declared):
                raise Refused(400, "input_digest_mismatch")
            try:
                payload = json.loads(body)
            except (ValueError, RecursionError):
                raise Refused(400, "payload_not_json") from None
            try:
                return run_page(payload, declared)
            except ServiceDown:
                raise Refused(503, "pipeline_unavailable") from None

    return ThreadingHTTPServer(address, Handler)


def mineru_pipeline(command: Any, api_alive: Callable[[], bool]) -> Pipeline:
    """The image's ``mineru`` command (its console script's click command, run in process)
    against the loopback ``mineru-api``; one page in a fresh temporary directory."""

    def run(data: bytes, suffix: str, page: int | None, lang: str | None) -> str:
        if not api_alive():
            raise ServiceDown
        with tempfile.TemporaryDirectory(prefix="akc-page-") as work:
            source = Path(work) / f"page{suffix}"
            source.write_bytes(data)
            out = Path(work) / "out"
            args = ["-p", str(source), "-o", str(out), "--api-url", f"http://{API_HOST}:{API_PORT}"]
            args += ["-b", RECIPE["backend"], "-m", RECIPE["method"]]
            args += ["-f", str(RECIPE["formula"]).lower(), "-t", str(RECIPE["table"]).lower()]
            if page is not None:
                args += ["-s", str(page), "-e", str(page)]
            if lang is not None:
                args += ["-l", lang]
            try:
                command.main(args=args, standalone_mode=False)
            except SystemExit as exit_:
                if exit_.code not in (None, 0):
                    raise PageFailure("pipeline_exit_nonzero") from None
            found = sorted(out.rglob("*.md"))
            if len(found) != 1:
                raise PageFailure("pipeline_output_missing")
            return found[0].read_text(encoding="utf-8")

    return run


def _api_healthy() -> bool:
    connection = http.client.HTTPConnection(API_HOST, API_PORT, timeout=5)
    try:
        connection.request("GET", "/health")
        return connection.getresponse().status == 200
    except OSError:
        return False
    finally:
        connection.close()


def main() -> None:
    manifest = json.loads(WEIGHTS_MANIFEST.read_text(encoding="utf-8"))
    installed = metadata.version("mineru")
    if installed != RECIPE["mineru"]:
        raise SystemExit(f"mineru {installed} installed, the recipe pins {RECIPE['mineru']}")
    (entry,) = metadata.entry_points(group="console_scripts", name="mineru")
    command = entry.load()
    if not callable(getattr(command, "main", None)):
        raise SystemExit("the mineru console script is not a click command")
    settings = Settings(
        model_revision=manifest["revision"],
        token=os.environ.get(BEARER_ENV) or None,
        receipt={
            "recipe": RECIPE,
            "recipe_sha256": canonical_sha256(RECIPE),
            "weights": {
                "repo_id": manifest["repo_id"],
                "revision": manifest["revision"],
                "manifest_sha256": hashlib.sha256(WEIGHTS_MANIFEST.read_bytes()).hexdigest(),
            },
            "versions": {
                name: metadata.version(name)
                for name in ("mineru", "torch", "torchvision", "transformers", "pypdfium2")
            },
            "python": sys.version.split()[0],
        },
    )
    child = subprocess.Popen(["/usr/local/bin/mineru-api", "--host", "127.0.0.1", "--port", "8000"])
    deadline = time.monotonic() + 600
    while not _api_healthy():
        if child.poll() is not None or time.monotonic() > deadline:
            child.kill()
            raise SystemExit("mineru-api did not become healthy")
        time.sleep(2)
    server = make_server(settings, mineru_pipeline(command, lambda: child.poll() is None))
    try:
        server.serve_forever()
    finally:
        child.terminate()


if __name__ == "__main__":
    main()
