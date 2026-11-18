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

An image that cannot import or load its own code is not a page result (WO-D10-0U): when a
failed page's command, or the recipe's service while that page ran, printed an import failure
(``IMAGE_DEFECT_SIGNATURES``), the server answers 503 ``image_defect`` to that page and every
later one and reports ``ready: false``, which the S0 driver stops on as operational; no failure
row is written for it.
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
import math
import os
import re
import signal
import string
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
from typing import IO, Any, TypeGuard
from urllib.parse import urlsplit

ROUTE = "/parse"
BEARER_ENV = "AKC_BENCHMARK_PROVIDER_TOKEN"  # the client's bearer token, same name on the pod
# The client reads a source of up to 64 MiB; base64 and the JSON envelope add about a third.
MAX_REQUEST_BYTES = 96 * 1024 * 1024
# The client refuses a response above 10 MiB; the serialized response stays below this.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
SOCKET_TIMEOUT_S = 30.0  # per read or write on the socket; a stalled client is dropped
# The pod proxy cuts a request at 100 s (§5G). A page gets at most this long, so a slow page is
# answered with the fixed failure row ``page_timeout`` before the proxy cuts the connection. A
# recipe may set a lower or higher value, but never one the proxy would cut first.
PAGE_TIMEOUT_S = 90
PROXY_CUT_S = 100
MAX_CASE_ID_BYTES = 256  # the case id is echoed in every result, so it is bounded
MAX_PAGE_INDEX = 9999  # a page index is passed to the vendor command, so it is bounded
MAX_CONTENT_TYPE_BYTES = 128  # echoed in the receipt
CONTENT_SUFFIX = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}
# What a Python process prints when the image cannot import or load its own code. Measured on
# the 2026-11-18 launches: C0's ``ModuleNotFoundError: No module named 'six'`` (the API's task
# error carries only "No module named …"), C1's ``ImportError: libgomp.so.1: cannot open shared
# object file`` and ``google.protobuf.runtime_version.VersionError: Detected incompatible
# Protobuf Gencode/Runtime versions …`` (generated code newer than the installed runtime). Each
# entry is the class name or the message text, so either form of the report is caught.
IMAGE_DEFECT_SIGNATURES = (
    "ModuleNotFoundError",
    "ImportError",
    "No module named ",
    "cannot open shared object file",
    "google.protobuf.runtime_version.VersionError",
    "Protobuf Gencode/Runtime",
)
_IMAGE_DEFECT = re.compile("|".join(map(re.escape, IMAGE_DEFECT_SIGNATURES)))
_SIGNATURE_CARRY = max(map(len, IMAGE_DEFECT_SIGNATURES)) - 1  # a signature split across reads
STDERR_READ_BYTES = 8192  # one read of a child's stderr; a longer line arrives in pieces
STDERR_JOIN_S = 5.0  # after the command's group is killed, its stderr reaches EOF at once
SERVICE_SETTLE_S = 1.0  # a service may log its trace just after answering the failed page
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_RECIPE_KEYS = {
    "name",
    "provider",
    "model",
    "aux_models",
    "packages",
    "absent_packages",
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


class ImageDefect(ServiceDown):
    """The image cannot import or load its own code: operational, and permanent for this image.
    ``signature`` is the fixed text that showed it (one of ``IMAGE_DEFECT_SIGNATURES``)."""

    def __init__(self, signature: str) -> None:
        super().__init__(signature)
        self.signature = signature


class StderrWatch:
    """A child's stderr, forwarded to ours as it arrives (the pod log, as when it was inherited),
    with each read numbered and the number of the last read that completed an image-defect
    signature kept, so a page can ask whether one was printed while it ran. The bytes are
    decoded here with replacement, read in bounded pieces, and nothing else is kept: no output
    of any length grows memory. One watch follows a service across its restarts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reads = 0
        self._hit: tuple[int, str] | None = None
        self._carry = ""

    def follow(self, stream: IO[bytes]) -> threading.Thread:
        thread = threading.Thread(target=self._pump, args=(stream,), daemon=True)
        thread.start()
        return thread

    def _pump(self, stream: IO[bytes]) -> None:
        with stream:
            while piece := stream.readline(STDERR_READ_BYTES):
                self.feed(piece)

    def feed(self, piece: bytes) -> None:
        text = piece.decode("utf-8", "replace")
        with contextlib.suppress(OSError, ValueError):  # a closed pod log must not stop the pump
            sys.stderr.write(text)
            sys.stderr.flush()
        with self._lock:
            self._reads += 1
            window = self._carry + text
            # only a signature that ends in this read: one inside the carry was counted before
            found = next(
                (m[0] for m in _IMAGE_DEFECT.finditer(window) if m.end() > len(self._carry)),
                None,
            )
            if found is not None:
                self._hit = (self._reads, found)
            self._carry = window[-_SIGNATURE_CARRY:]

    def mark(self) -> int:
        with self._lock:
            return self._reads

    def since(self, mark: int) -> str | None:
        """The signature of the last image-defect report read after ``mark``, if any."""
        with self._lock:
            hit = self._hit
        return hit[1] if hit is not None and hit[0] > mark else None


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
    return isinstance(value, list) and all(
        isinstance(item, str) and item and "\x00" not in item for item in value
    )


def _template(argv: list[str], allowed: set[str]) -> None:
    """Every ``{field}`` is a bare allowed name: no attribute, index, conversion or format spec,
    which would fail or reach into the object when the real value is substituted."""
    for item in argv:
        try:
            fields = [part for part in string.Formatter().parse(item) if part[1] is not None]
        except ValueError:
            fields = [("", "", "", None)]
        if any(name not in allowed or spec or conv for _, name, spec, conv in fields):
            raise ValueError(f"argument {item!r} names a field other than {sorted(allowed)}")


def _seconds(value: Any, name: str, below: float) -> float:
    """A finite number of seconds in (0, below): never NaN, an infinity, a bool or a string
    (a NaN limit would never time out)."""
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or not 0 < value < below
    ):
        raise ValueError(f"{name} must be a finite number of seconds above 0 and below {below}")
    return float(value)


def _pinned_model(entry: Any, keys: set[str], what: str) -> None:
    if not isinstance(entry, dict) or set(entry) != keys:
        raise ValueError(f"{what} names exactly {sorted(keys)}")
    if not isinstance(entry["revision"], str) or not _REVISION.fullmatch(entry["revision"]):
        raise ValueError(f"{what} revision must be a full 40-character commit")
    for key in ("repo_id", "dir", "manifest"):
        if not isinstance(entry[key], str) or not entry[key]:
            raise ValueError(f"{what} {key} must be a non-empty string")


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a JSON number")  # json.loads takes NaN and Infinity


def load_recipe(path: Path) -> dict[str, Any]:
    """A recipe file, checked for shape (``parse_recipe``)."""
    return parse_recipe(path.read_text(encoding="utf-8"))


def parse_recipe(text: str) -> dict[str, Any]:
    """A recipe's text, checked for shape; ValueError names what is wrong. Whatever the text
    holds, the only exception this raises is ValueError, and a recipe it returns can be used by
    every function below without a type error (a test fuzzes every field)."""
    try:
        recipe = json.loads(text, parse_constant=_no_constant)
    except RecursionError:
        raise ValueError("recipe nests too deeply") from None
    if not isinstance(recipe, dict) or set(recipe) != _RECIPE_KEYS:
        raise ValueError(f"recipe keys must be exactly {sorted(_RECIPE_KEYS)}")
    if not isinstance(recipe["name"], str) or not recipe["name"]:
        raise ValueError("name must be a non-empty string")
    _pinned_model(recipe["model"], {"repo_id", "revision", "dir", "manifest"}, "model")
    if not isinstance(recipe["aux_models"], list):
        raise ValueError("aux_models must be a list")
    roles: set[str] = set()
    for aux in recipe["aux_models"]:
        _pinned_model(aux, {"role", "repo_id", "revision", "dir", "manifest"}, "an aux model")
        role = aux["role"]
        if not isinstance(role, str) or not role or role == "model" or role in roles:
            raise ValueError("an aux model's role is a unique name other than 'model'")
        roles.add(role)
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
        required = {"argv", "health_url", "startup_timeout_s"}
        if not isinstance(service, dict) or not required <= set(service) <= {
            *required,
            "page_failure_exits",
        }:
            raise ValueError("service names argv, health_url, startup_timeout_s (and exits)")
        health = service["health_url"]
        if not _strings(service["argv"]) or not isinstance(health, str):
            raise ValueError("service argv must be strings and its health URL a string")
        try:
            parts = urlsplit(health)
            on_loopback = parts.hostname == "127.0.0.1" and parts.port is not None
        except ValueError:  # an out-of-range port, for one
            on_loopback = False
        if not on_loopback:
            raise ValueError("the service's health URL must be on loopback")
        _seconds(service["startup_timeout_s"], "startup_timeout_s", 3600)
        exits = service.get("page_failure_exits", {})
        if not isinstance(exits, dict) or not all(
            isinstance(reason, str)
            and re.fullmatch(r"[2-9]|[1-9][0-9]", code)
            and re.fullmatch(r"[a-z][a-z_]{0,63}", reason)
            for code, reason in exits.items()
        ):
            raise ValueError("page_failure_exits maps an exit code 2-99 to a fixed reason")
    lang = recipe["lang_by_language"]
    if not isinstance(lang, dict) or not all(isinstance(v, str) for v in lang.values()):
        raise ValueError("lang_by_language maps a payload language to a string")
    if lang and recipe["lang_argv"] is None:
        raise ValueError("a language mapping needs lang_argv")
    env = recipe["env"]
    if not isinstance(env, dict) or not all(
        _strings([value]) and _strings([name]) and "=" not in name for name, value in env.items()
    ):
        raise ValueError("env maps names to strings")
    packages = recipe["packages"]
    if not isinstance(packages, dict) or not all(
        isinstance(v, str) or v is None for v in packages.values()
    ):
        raise ValueError("packages maps names to a pinned version or null")
    if not _strings(recipe["absent_packages"]) and recipe["absent_packages"] != []:
        raise ValueError("absent_packages must be a list of package names")
    if isinstance(recipe["timeout_s"], (int, float)) and recipe["timeout_s"] >= PROXY_CUT_S:
        raise ValueError(f"timeout_s must be below the proxy's {PROXY_CUT_S} s cut")
    _seconds(recipe["timeout_s"], "timeout_s", PROXY_CUT_S)
    if not isinstance(recipe["output_glob"], str) or not recipe["output_glob"]:
        raise ValueError("output_glob must be a pattern")
    try:  # the pattern the output is found by, tried on a directory that does not exist
        list((Path(__file__).parent / "akc-no-such-dir").glob(recipe["output_glob"]))
    except (ValueError, NotImplementedError):
        raise ValueError("output_glob must be a relative pattern") from None
    if ".." in Path(recipe["output_glob"]).parts:
        raise ValueError("output_glob must be a relative pattern inside the output directory")
    if not isinstance(recipe["options"], dict):
        raise ValueError("options must be an object")
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


def _printable_ascii(value: Any, limit: int) -> bool:
    if not isinstance(value, str):
        return False
    return 0 < len(value) <= limit and value.isascii() and value.isprintable()


def _page_number(value: Any) -> TypeGuard[int]:
    return type(value) is int and 0 <= value <= MAX_PAGE_INDEX


def page_request(
    payload: Any, recipe: dict[str, Any]
) -> tuple[str, bytes, str, int | None, str | None]:
    """(case id, source bytes, content type, page index, language value), or Refused."""
    if not isinstance(payload, dict):
        raise Refused(400, "payload_not_object")
    case_id = payload.get("benchmark_case_id")
    if case_id is None or case_id == "":
        raise Refused(400, "case_id_missing")
    if not _printable_ascii(case_id, MAX_CASE_ID_BYTES):
        raise Refused(400, "case_id_invalid")
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
    if not _printable_ascii(content_type, MAX_CONTENT_TYPE_BYTES):
        raise Refused(400, "content_type_invalid")
    index = payload.get("page_index")
    page: int | None = None
    if content_type == "application/pdf":
        if not _page_number(index):
            raise Refused(400, "page_index_invalid")
        if index > 0 and recipe["page_argv"] is None:
            raise Refused(400, "page_index_unsupported")  # the vendor command runs whole files
        page = index
    elif index is not None and not (_page_number(index) and index == 0):
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
    defect = threading.Event()  # set once by an ImageDefect: no page runs on this image again
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
        except ImportError as exc:  # raised in this process: the image's defect, not the page's
            traceback.print_exc(file=sys.stderr)
            missing = isinstance(exc, ModuleNotFoundError)
            raise ImageDefect("ModuleNotFoundError" if missing else "ImportError") from None
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
            if len(body) > settings.max_response_bytes:  # every answer, whatever built it
                print(f"refused to send {len(body)} bytes", file=sys.stderr, flush=True)
                status, body = 500, _encode({"error": "response_too_large"})
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
                    "ready": ready() and not defect.is_set(),
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
            lengths = self.headers.get_all("Content-Length") or []
            length = lengths[0] if len(lengths) == 1 else ""  # two lengths: which one is true?
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
            if defect.is_set():
                raise Refused(503, "image_defect")
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
            except ImageDefect as exc:
                defect.set()
                print(
                    f"image defect ({exc.signature}): answering 503 image_defect from now on",
                    file=sys.stderr,
                    flush=True,
                )
                raise Refused(503, "image_defect") from None
            except ServiceDown:
                raise Refused(503, "pipeline_unavailable") from None

    return ThreadingHTTPServer(address, Handler)


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    """The process and every child it started (its own session on POSIX), also after the
    process itself has exited: a grandchild that outlived it must not run into the next page."""
    if sys.platform == "win32":
        process.kill()
    else:
        with contextlib.suppress(ProcessLookupError):  # the whole group is already gone
            os.killpg(process.pid, signal.SIGKILL)
    process.wait()


class Service:
    """The recipe's long-lived child (models loaded), restarted after an interrupted page, or
    once when it died on its own between pages. A restart that fails leaves it down: 503 and
    ``ready: false`` from then on, which a launcher treats as a dead pod."""

    def __init__(self, spec: dict[str, Any], env: dict[str, str]) -> None:
        self.spec = spec
        self.env = env
        self.child: subprocess.Popen[bytes] | None = None
        self.recovering = threading.Event()
        self.gave_up = False
        self.stderr = StderrWatch()  # every child's, across restarts

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
        self.child = subprocess.Popen(  # noqa: S603 - argv comes from the image's own recipe file checked by load_recipe, never from a request
            self.spec["argv"], env=self.env, stderr=subprocess.PIPE, start_new_session=True
        )
        if self.child.stderr is None:  # stderr=PIPE always gives one
            raise RuntimeError("the service's stderr was not captured")
        self.stderr.follow(self.child.stderr)
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

    def available(self) -> bool:
        """Whether a page may run now. A child that died on its own is restarted once, in the
        background; this page and every page until it is healthy get 503."""
        if self.ready():
            return True
        child = self.child
        if not self.recovering.is_set() and child is not None and not self.gave_up:
            print(f"service exited on its own ({child.poll()}); restarting", file=sys.stderr)
            self.recover()
        return False

    def recover(self) -> None:
        """Answer 503 until a fresh child is healthy: no orphan work reaches the next page."""
        self.recovering.set()

        def restart() -> None:
            if self.child is not None:
                _kill_group(self.child)
            if self.start():
                self.recovering.clear()
            else:
                self.gave_up = True
                print("service did not come back; answering 503", file=sys.stderr, flush=True)

        threading.Thread(target=restart, daemon=True).start()


class NoService:
    """A recipe whose command loads the models itself: idle as soon as the command is gone."""

    def __init__(self) -> None:
        self.stderr = StderrWatch()  # follows nothing: no process of its own prints

    def ready(self) -> bool:
        return True

    def available(self) -> bool:
        return True

    def recover(self) -> None:
        return None


def vendor_argv(
    recipe: dict[str, Any], source: Path, out: Path, page: int | None, lang: str | None
) -> list[str]:
    """The vendor command for one page. Every item is the recipe's; the only values a request
    decides are the bounded page number and a language value the recipe itself maps to."""
    if page is not None and not _page_number(page):
        raise ValueError("page is not a bounded page number")
    if lang is not None and lang not in recipe["lang_by_language"].values():
        raise ValueError("lang is not one of the recipe's language values")
    argv = [item.format(source=source, out=out) for item in recipe["argv"]]
    if page is not None and recipe["page_argv"] is not None:
        argv += [item.format(page=page) for item in recipe["page_argv"]]
    if lang is not None:
        argv += [item.format(lang=lang) for item in recipe["lang_argv"]]
    return argv


def command_pipeline(
    recipe: dict[str, Any],
    service: Any,
    env: dict[str, str],
    max_output_bytes: int = MAX_RESPONSE_BYTES,
) -> Pipeline:
    """The recipe's vendor command for one page, in a fresh temporary directory. An exit code the
    recipe's service maps to a reason (``page_failure_exits``) means the service answered that
    the page failed and is idle again: a failure row with that reason, no restart. Any other
    non-zero exit may leave the service working, so it is restarted. Before either, a non-zero
    exit is checked for an image defect: an import failure the command printed, or the service
    printed while the page ran, is ``ImageDefect`` (operational), never a page failure."""
    page_failures: dict[str, str] = (recipe["service"] or {}).get("page_failure_exits", {})
    service_stderr: StderrWatch = service.stderr

    def run(data: bytes, suffix: str, page: int | None, lang: str | None) -> str:
        if not service.available():
            raise ServiceDown
        with tempfile.TemporaryDirectory(prefix="akc-page-") as work:
            source = Path(work) / f"page{suffix}"
            source.write_bytes(data)
            out = Path(work) / "out"
            out.mkdir()
            argv = vendor_argv(recipe, source, out, page, lang)
            mark = service_stderr.mark()
            own = StderrWatch()
            process = subprocess.Popen(  # noqa: S603 - argv comes from the image's own recipe file checked by load_recipe, never from a request
                argv,
                env=env,
                cwd=work,
                stdin=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            if process.stderr is None:  # stderr=PIPE always gives one
                _kill_group(process)
                raise RuntimeError("the command's stderr was not captured")
            pump = own.follow(process.stderr)
            try:
                code = process.wait(timeout=recipe["timeout_s"])
            except subprocess.TimeoutExpired:
                _kill_group(process)
                service.recover()
                raise PageFailure("page_timeout") from None
            _kill_group(process)  # whatever the command left running dies with it
            pump.join(STDERR_JOIN_S)
            if code != 0:
                defect = own.since(0)
                if defect is None:
                    time.sleep(SERVICE_SETTLE_S)
                    defect = service_stderr.since(mark)
                if defect is not None:
                    raise ImageDefect(defect)
            if str(code) in page_failures:
                raise PageFailure(page_failures[str(code)])
            if code != 0:
                service.recover()  # a client that gave up may leave the service working
                raise PageFailure("pipeline_exit_nonzero")
            found = sorted(p for p in out.glob(recipe["output_glob"]) if p.is_file())
            if len(found) != 1:
                raise PageFailure("pipeline_output_missing")
            if found[0].stat().st_size > max_output_bytes:  # never read a file this large
                raise PageFailure("output_too_large")
            return found[0].read_text(encoding="utf-8")

    return run


def recipe_receipt(
    recipe: dict[str, Any], versions: dict[str, str], manifests: dict[str, str]
) -> dict[str, Any]:
    """What every result of this server says about how it was made. ``manifests``: the sha256
    of each verified weights manifest by role (``model`` and each aux model's role)."""
    return {
        "recipe": {
            "name": recipe["name"],
            "sha256": canonical_sha256(recipe),
            "options": recipe["options"],
        },
        "weights": {
            "repo_id": recipe["model"]["repo_id"],
            "revision": recipe["model"]["revision"],
            "manifest_sha256": manifests["model"],
            "aux": [
                {
                    "role": aux["role"],
                    "repo_id": aux["repo_id"],
                    "revision": aux["revision"],
                    "manifest_sha256": manifests[aux["role"]],
                }
                for aux in recipe["aux_models"]
            ],
        },
        # No long-lived service: the command loads every model for each page, so its latency
        # and cost per page are not comparable with a recipe that keeps them loaded.
        "includes_model_load": recipe["service"] is None,
        "versions": versions,
        "absent_packages": recipe["absent_packages"],
        "python": sys.version.split()[0],
    }


def installed_versions(packages: dict[str, str | None], absent: list[str]) -> dict[str, str]:
    """Installed versions; refuses to start when a pinned one differs or one is missing, or
    when a package the recipe rules out (another inference engine) is installed."""
    found: dict[str, str] = {}
    for name, pinned in packages.items():
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            raise SystemExit(f"{name} is not installed") from None
        if pinned is not None and found[name] != pinned:
            raise SystemExit(f"{name} {found[name]} installed, the recipe pins {pinned}")
    for name in absent:
        try:
            version = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
        raise SystemExit(f"{name} {version} installed, the recipe rules it out")
    return found


def verified_weights(recipe: dict[str, Any]) -> dict[str, str]:
    """Every model the recipe loads is on disk exactly as its manifest says; the sha256 of each
    manifest by role. Prints one line per model to the pod log."""
    weights = importlib.import_module("mineru_akc_weights")
    digests: dict[str, str] = {}
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
        digests[role] = hashlib.sha256(raw).hexdigest()
        print(
            f"weights {role} {model['repo_id']}@{model['revision']} manifest {digests[role]} "
            f"{manifest['file_count']} files verified",
            flush=True,
        )
    return digests


def child_env(recipe: dict[str, Any], environ: dict[str, str]) -> dict[str, str]:
    """The vendor tool's environment: the pod's plus the recipe's, never the bearer token."""
    env = {**environ, **recipe["env"]}
    env.pop(BEARER_ENV, None)
    return env


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    try:
        recipe = load_recipe(args.recipe)
    except ValueError as exc:
        raise SystemExit(f"recipe refused: {exc}") from None
    versions = installed_versions(recipe["packages"], recipe["absent_packages"])
    settings = Settings(
        recipe=recipe,
        token=os.environ.get(BEARER_ENV) or None,
        receipt=recipe_receipt(recipe, versions, verified_weights(recipe)),
    )
    print(f"recipe {recipe['name']} sha256 {settings.receipt['recipe']['sha256']}", flush=True)
    env = child_env(recipe, dict(os.environ))
    service: Service | NoService = NoService()
    if recipe["service"] is not None:
        service = Service(recipe["service"], env)
        if not service.start():
            raise SystemExit("the recipe's service did not become healthy")
    server = make_server(
        settings,
        command_pipeline(recipe, service, env, settings.max_response_bytes),
        ("0.0.0.0", args.port),
        service.ready,
    )
    try:
        server.serve_forever()
    finally:
        if isinstance(service, Service) and service.child is not None:
            _kill_group(service.child)


if __name__ == "__main__":
    main()
