"""Arena page server: one vendor pipeline behind the AKC external-runner protocol.

WO-D10-0F wrote it for C0; WO-D10-0I made the pipeline a recipe so the same file serves C0
(MinerU 3.4.4 pipeline backend), C3 (the same MinerU's VLM backend) and C1 (PaddleOCR's page
pipeline). A recipe (``recipes/*.json``) is declarative: the vendor command and its arguments,
its environment, an optional long-lived service the command talks to, the model revision it
attests and where its output file appears. No vendor code is in this file.

The mirror of ``benchmark/runners/base.py::external_exchange``. The client POSTs the provider
payload as JSON with ``X-AKC-Benchmark-Provider``, ``X-AKC-Input-SHA256`` (of the body),
``X-AKC-Model-Revision`` and, when configured, ``Authorization: Bearer``; it accepts only a 200
``application/json`` object whose ``provider`` and ``model_revision`` equal what it asked for,
and treats every other status as the provider being unavailable.

So this server answers 200 only for a page it ran: the parser output, or a failure row when the
pipeline failed on the page. A request it will not run (wrong token, size, provider, revision
or digest; a page already running; the pipeline recovering) gets a 4xx or 503 with a fixed
error code and runs nothing. The revision it reports is the recipe's, which ``main`` checks
against the weights on disk before serving; never the request header echoed back. Standard
library only. TLS is terminated by the pod proxy in front of it.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import hashlib
import hmac
import http.client
import importlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROUTE = "/parse"
BEARER_ENV = "AKC_BENCHMARK_PROVIDER_TOKEN"  # the client's bearer token, same name on the pod
# The client reads a source of up to 64 MiB; base64 and the JSON envelope add about a third.
MAX_REQUEST_BYTES = 96 * 1024 * 1024
# The client refuses a response above 10 MiB; the serialized response stays below this.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
SOCKET_TIMEOUT_S = 30.0  # per read or write on the socket; a stalled client is dropped
CONTENT_SUFFIX = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_RECIPE_KEYS = {
    "name",
    "provider",
    "model",
    "aux_models",
    "packages",
    "service",
    "argv",
    "page_argv",
    "lang_argv",
    "lang_by_language",
    "env",
    "output_glob",
    "timeout_s",
    "options",
}


class PageFailure(Exception):
    """The pipeline ran and failed on this page: a failure row with this fixed reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ServiceDown(Exception):
    """The pipeline cannot run now (operational): 503, nothing is recorded for the page."""


class Refused(Exception):
    """A request this server will not run: an HTTP status and a fixed error code."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


# (source bytes, file suffix, 0-based page index or None for an image, language value or None)
Pipeline = Callable[[bytes, str, int | None, str | None], str]


def canonical_sha256(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def _template(argv: list[str], allowed: set[str]) -> None:
    for item in argv:
        try:
            item.format_map({name: "x" for name in allowed})
        except (KeyError, ValueError, IndexError):
            raise ValueError(
                f"argument {item!r} names a field other than {sorted(allowed)}"
            ) from None


def load_recipe(path: Path) -> dict[str, Any]:
    """A recipe file, checked for shape; ValueError names what is wrong."""
    recipe = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(recipe, dict) or set(recipe) != _RECIPE_KEYS:
        raise ValueError(f"recipe keys must be exactly {sorted(_RECIPE_KEYS)}")
    model = recipe["model"]
    if not isinstance(model, dict) or set(model) != {"repo_id", "revision", "dir", "manifest"}:
        raise ValueError("model must name repo_id, revision, dir and manifest")
    if not isinstance(model["revision"], str) or not _REVISION.fullmatch(model["revision"]):
        raise ValueError("model revision must be a full 40-character commit")
    for aux in recipe["aux_models"]:
        if not isinstance(aux, dict) or set(aux) != {
            "role",
            "repo_id",
            "revision",
            "dir",
            "manifest",
        }:
            raise ValueError("an aux model names role, repo_id, revision, dir and manifest")
    if not isinstance(recipe["provider"], str) or not recipe["provider"]:
        raise ValueError("provider must be a key name")
    if not _strings(recipe["argv"]):
        raise ValueError("argv must be a non-empty list of strings")
    _template(recipe["argv"], {"source", "out"})
    for key, field_name in (("page_argv", "page"), ("lang_argv", "lang")):
        if recipe[key] is not None:
            if not _strings(recipe[key]):
                raise ValueError(f"{key} must be null or a list of strings")
            _template(recipe[key], {field_name})
    service = recipe["service"]
    if service is not None:
        if not isinstance(service, dict) or set(service) != {
            "argv",
            "health_url",
            "startup_timeout_s",
        }:
            raise ValueError("service names argv, health_url and startup_timeout_s")
        if not _strings(service["argv"]) or urlsplit(service["health_url"]).hostname != "127.0.0.1":
            raise ValueError("service argv must be strings and its health URL on loopback")
    lang = recipe["lang_by_language"]
    if not isinstance(lang, dict) or not all(isinstance(v, str) for v in lang.values()):
        raise ValueError("lang_by_language maps a payload language to a string")
    if lang and recipe["lang_argv"] is None:
        raise ValueError("a language mapping needs lang_argv")
    env = recipe["env"]
    if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
        raise ValueError("env maps names to strings")
    timeout = recipe["timeout_s"]
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError("timeout_s must be a positive number")
    if not isinstance(recipe["output_glob"], str) or not recipe["output_glob"]:
        raise ValueError("output_glob must be a pattern")
    return recipe


@dataclass(frozen=True)
class Settings:
    recipe: dict[str, Any]
    token: str | None
    receipt: dict[str, Any]  # identity carried in every result: recipe, versions, weights
    max_request_bytes: int = MAX_REQUEST_BYTES
    max_response_bytes: int = MAX_RESPONSE_BYTES
    socket_timeout_s: float = SOCKET_TIMEOUT_S
    provider: str = field(init=False)
    model_revision: str = field(init=False)  # the only revision this server will attest

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", self.recipe["provider"])
        object.__setattr__(self, "model_revision", self.recipe["model"]["revision"])


def page_request(
    payload: Any, recipe: dict[str, Any]
) -> tuple[str, bytes, str, int | None, str | None]:
    """(case id, source bytes, content type, page index, language value), or Refused."""
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
    if not data or not isinstance(declared, str) or not _SHA256.fullmatch(declared):
        raise Refused(400, "source_digest_mismatch")
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), declared):
        raise Refused(400, "source_digest_mismatch")
    content_type = source.get("content_type")
    if not isinstance(content_type, str):
        raise Refused(400, "content_type_missing")
    index = payload.get("page_index")
    page: int | None = None
    if content_type == "application/pdf":
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise Refused(400, "page_index_invalid")
        if index > 0 and recipe["page_argv"] is None:
            raise Refused(400, "page_index_unsupported")  # the vendor command runs whole files
        page = index
    elif isinstance(index, bool) or index not in (None, 0):
        raise Refused(400, "page_index_invalid")  # an image is one page
    language = payload.get("language")
    if language is not None and not isinstance(language, str):
        raise Refused(400, "language_invalid")
    lang = recipe["lang_by_language"].get(language) if language is not None else None
    return case_id, data, content_type, page, lang


def _encode(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


def make_server(
    settings: Settings,
    pipeline: Pipeline,
    address: tuple[str, int] = ("0.0.0.0", 8080),
    ready: Callable[[], bool] = lambda: True,
) -> ThreadingHTTPServer:
    busy = threading.Lock()  # one page at a time; a second one is refused, never queued
    provider = settings.provider

    def failure(case_id: str, receipt: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "benchmark_case_id": case_id,
            "provider": provider,
            "model_revision": settings.model_revision,
            "failure": {"reason": reason},
            "receipt": {**receipt, "revision_attested": False},
        }

    def run_page(payload: Any, input_sha256: str) -> dict[str, Any]:
        case_id, data, content_type, page, lang = page_request(payload, settings.recipe)
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
        except ServiceDown:
            raise
        except Exception as exc:
            if not isinstance(exc, PageFailure):
                traceback.print_exc(file=sys.stderr)  # the pod log, never the response body
            receipt["latency_ms"] = (time.perf_counter() - started) * 1000.0
            return failure(
                case_id, receipt, exc.reason if isinstance(exc, PageFailure) else "pipeline_error"
            )
        latency_ms = (time.perf_counter() - started) * 1000.0
        receipt.update(
            latency_ms=latency_ms,
            markdown_sha256=hashlib.sha256(encoded).hexdigest(),
            revision_attested=True,
        )
        value = {
            "schema_version": "1.0",
            "benchmark_case_id": case_id,
            "provider": provider,
            "model_revision": settings.model_revision,
            "text": text,
            "reading_order": [],
            "blocks": [],
            "generated_claims": [],
            "metrics": {"latency_ms": latency_ms, "receipt": receipt},
            "warnings": [],
        }
        if len(_encode(value)) > settings.max_response_bytes:  # what goes on the wire
            del receipt["markdown_sha256"]
            return failure(case_id, receipt, "output_too_large")
        return value

    class Handler(BaseHTTPRequestHandler):
        server_version = "akc-page-server"
        sys_version = ""
        timeout = settings.socket_timeout_s  # applied to the socket by StreamRequestHandler

        def _send(self, status: int, value: dict[str, Any]) -> None:
            body = _encode(value)
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
                    "provider": provider,
                    "model_revision": settings.model_revision,
                    "recipe": settings.recipe["name"],
                    "receipt_sha256": canonical_sha256(settings.receipt),
                    "busy": busy.locked(),
                    "ready": ready(),
                },
            )

        def do_POST(self) -> None:
            try:
                length = self._admitted_length()
            except Refused as refused:  # nothing of the body was read: close after answering
                self.close_connection = True
                self._send(refused.status, {"error": refused.code})
                return
            try:
                self._check_headers()
            except Refused as refused:  # read off the socket, unstored, so the client sees it
                self._discard(length)
                self._send(refused.status, {"error": refused.code})
                return
            body = self.rfile.read(length)  # each read is bounded by the socket timeout
            if len(body) != length:
                self.close_connection = True  # the client went away mid-body
                return
            try:
                if not busy.acquire(blocking=False):  # taken only once the body is in
                    raise Refused(429, "busy")
                try:
                    value = self._run(body)
                finally:
                    busy.release()
            except Refused as refused:
                self._send(refused.status, {"error": refused.code})
                return
            except Exception:
                traceback.print_exc(file=sys.stderr)
                self._send(500, {"error": "internal_error"})
                return
            self._send(200, value)

        def _admitted_length(self) -> int:
            """Route and length: the checks made before any of the body is read."""
            if self.path != ROUTE:
                raise Refused(404, "not_found")
            length = self.headers.get("Content-Length") or ""
            valid = length.isascii() and length.isdigit() and len(length) <= 12
            if self.headers.get("Transfer-Encoding") is not None or not valid:
                raise Refused(411, "length_required")
            if int(length) > settings.max_request_bytes:
                raise Refused(413, "request_too_large")
            return int(length)

        def _check_headers(self) -> None:
            if settings.token is not None:
                expected = f"Bearer {settings.token}".encode()
                given = (self.headers.get("Authorization") or "").encode("latin-1", "replace")
                if not hmac.compare_digest(given, expected):
                    raise Refused(401, "unauthorized")
            if self.headers.get("X-AKC-Benchmark-Provider") != provider:
                raise Refused(409, "provider_mismatch")
            if self.headers.get("X-AKC-Model-Revision") != settings.model_revision:
                raise Refused(409, "model_revision_mismatch")

        def _discard(self, unread: int) -> None:
            while unread > 0:
                chunk = self.rfile.read(min(unread, 1 << 20))
                unread = unread - len(chunk) if chunk else 0

        def _run(self, body: bytes) -> dict[str, Any]:
            declared = self.headers.get("X-AKC-Input-SHA256") or ""
            if not _SHA256.fullmatch(declared) or not hmac.compare_digest(
                hashlib.sha256(body).hexdigest(), declared
            ):
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


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    """The process and every child it started (its own session on POSIX)."""
    if sys.platform == "win32":
        process.kill()
    else:
        with contextlib.suppress(ProcessLookupError):  # already gone
            os.killpg(process.pid, signal.SIGKILL)
    process.wait()


class Service:
    """The recipe's long-lived child (models loaded), restarted after an interrupted page."""

    def __init__(self, spec: dict[str, Any], env: dict[str, str]) -> None:
        self.spec = spec
        self.env = env
        self.child: subprocess.Popen[bytes] | None = None
        self.recovering = threading.Event()

    def _healthy(self) -> bool:
        url = urlsplit(self.spec["health_url"])
        connection = http.client.HTTPConnection(url.hostname or "", url.port or 80, timeout=5)
        try:
            connection.request("GET", url.path or "/")
            return connection.getresponse().status == 200
        except OSError:
            return False
        finally:
            connection.close()

    def start(self) -> bool:
        self.child = subprocess.Popen(self.spec["argv"], env=self.env, start_new_session=True)
        deadline = time.monotonic() + self.spec["startup_timeout_s"]
        while not self._healthy():
            if self.child.poll() is not None or time.monotonic() > deadline:
                _kill_group(self.child)
                return False
            time.sleep(2)
        return True

    def ready(self) -> bool:
        child = self.child
        return not self.recovering.is_set() and child is not None and child.poll() is None

    def recover(self) -> None:
        """Answer 503 until a fresh child is healthy: no orphan work reaches the next page."""
        self.recovering.set()

        def restart() -> None:
            if self.child is not None:
                _kill_group(self.child)
            if self.start():
                self.recovering.clear()
            else:
                print("service did not come back; answering 503", file=sys.stderr, flush=True)

        threading.Thread(target=restart, daemon=True).start()


class NoService:
    """A recipe whose command loads the models itself: idle as soon as the command is gone."""

    def ready(self) -> bool:
        return True

    def recover(self) -> None:
        return None


def command_pipeline(recipe: dict[str, Any], service: Any, env: dict[str, str]) -> Pipeline:
    """The recipe's vendor command for one page, in a fresh temporary directory."""

    def run(data: bytes, suffix: str, page: int | None, lang: str | None) -> str:
        if not service.ready():
            raise ServiceDown
        with tempfile.TemporaryDirectory(prefix="akc-page-") as work:
            source = Path(work) / f"page{suffix}"
            source.write_bytes(data)
            out = Path(work) / "out"
            out.mkdir()
            argv = [item.format(source=source, out=out) for item in recipe["argv"]]
            if page is not None and recipe["page_argv"] is not None:
                argv += [item.format(page=page) for item in recipe["page_argv"]]
            if lang is not None:
                argv += [item.format(lang=lang) for item in recipe["lang_argv"]]
            process = subprocess.Popen(
                argv, env=env, cwd=work, stdin=subprocess.DEVNULL, start_new_session=True
            )
            try:
                code = process.wait(timeout=recipe["timeout_s"])
            except subprocess.TimeoutExpired:
                _kill_group(process)
                service.recover()
                raise PageFailure("pipeline_timeout") from None
            if code != 0:
                service.recover()  # a client that gave up may leave the service working
                raise PageFailure("pipeline_exit_nonzero")
            found = sorted(p for p in out.glob(recipe["output_glob"]) if p.is_file())
            if len(found) != 1:
                raise PageFailure("pipeline_output_missing")
            return found[0].read_text(encoding="utf-8")

    return run


def recipe_receipt(
    recipe: dict[str, Any], versions: dict[str, str], weights_manifest_sha256: str
) -> dict[str, Any]:
    """What every result of this server says about how it was made."""
    return {
        "recipe": {
            "name": recipe["name"],
            "sha256": canonical_sha256(recipe),
            "options": recipe["options"],
        },
        "weights": {
            "repo_id": recipe["model"]["repo_id"],
            "revision": recipe["model"]["revision"],
            "manifest_sha256": weights_manifest_sha256,
        },
        "versions": versions,
        "python": sys.version.split()[0],
    }


def installed_versions(packages: dict[str, str | None]) -> dict[str, str]:
    """Installed versions; refuses to start when a pinned one differs or one is missing."""
    found: dict[str, str] = {}
    for name, pinned in packages.items():
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            raise SystemExit(f"{name} is not installed") from None
        if pinned is not None and found[name] != pinned:
            raise SystemExit(f"{name} {found[name]} installed, the recipe pins {pinned}")
    return found


def verified_weights(recipe: dict[str, Any]) -> str:
    """Every model the recipe loads is on disk exactly as its manifest says; the attested
    manifest's sha256. Prints one line per model to the pod log."""
    weights = importlib.import_module("mineru_akc_weights")
    digest = ""
    for role, model in [
        ("model", recipe["model"]),
        *((a["role"], a) for a in recipe["aux_models"]),
    ]:
        if not (model["repo_id"] and model["revision"] and model["manifest"] and model["dir"]):
            raise SystemExit(f"{role}: not pinned in the recipe; refusing to serve")
        raw = Path(model["manifest"]).read_bytes()
        manifest = json.loads(raw)
        if (manifest["repo_id"], manifest["revision"]) != (model["repo_id"], model["revision"]):
            raise SystemExit(f"{role}: manifest is for another repository or revision")
        errors = weights.verify_tree(Path(model["dir"]), manifest)
        if errors:
            raise SystemExit(f"{role}: weights differ from the manifest:\n" + "\n".join(errors))
        sha = hashlib.sha256(raw).hexdigest()
        print(
            f"weights {role} {model['repo_id']}@{model['revision']} manifest {sha} "
            f"{manifest['file_count']} files verified",
            flush=True,
        )
        digest = digest or sha
    return digest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    try:
        recipe = load_recipe(args.recipe)
    except ValueError as exc:
        raise SystemExit(f"recipe refused: {exc}") from None
    versions = installed_versions(recipe["packages"])
    settings = Settings(
        recipe=recipe,
        token=os.environ.get(BEARER_ENV) or None,
        receipt=recipe_receipt(recipe, versions, verified_weights(recipe)),
    )
    print(f"recipe {recipe['name']} sha256 {settings.receipt['recipe']['sha256']}", flush=True)
    env = {**os.environ, **recipe["env"]}
    env.pop(BEARER_ENV, None)  # the vendor tool never sees the token
    service: Service | NoService = NoService()
    if recipe["service"] is not None:
        service = Service(recipe["service"], env)
        if not service.start():
            raise SystemExit("the recipe's service did not become healthy")
    server = make_server(
        settings, command_pipeline(recipe, service, env), ("0.0.0.0", args.port), service.ready
    )
    try:
        server.serve_forever()
    finally:
        if isinstance(service, Service) and service.child is not None:
            _kill_group(service.child)


if __name__ == "__main__":
    main()
