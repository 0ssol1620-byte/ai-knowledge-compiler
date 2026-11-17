"""C1's long-lived page service: PaddleOCR's documented Python object, loaded once.

PaddleOCR 3.7.0 documents ``PaddleOCRVL(...)`` with ``predict()`` and ``save_to_markdown()``
(``docs/version3.x/pipeline_usage/PaddleOCR-VL.en.md``, snapshot sha256 ``4d383354…``), and the
production adapter (``workers/gpu-parser/paddleocr_adapter.py``) keeps exactly that object
loaded across pages. This file does the same for the arena page server
(``mineru-pipeline-akc/mineru_akc_server.py``), which treats it as the recipe's ``service``:

- ``serve`` constructs the object once, with the production adapter's arguments
  (``construct_kwargs``), and only then binds ``127.0.0.1``; ``GET /health`` is 200 only while
  the object is loaded. If the object cannot be constructed, it prints ``LOAD_FAILED_MARKER``
  and exits non-zero, which the server reports as "the recipe's service did not become healthy".
- ``page`` is the one-page client the recipe's ``argv`` runs. Its one request field is the page
  file the server already wrote into its own work directory; the service accepts nothing else
  (``PageService.source``) and writes the markdown into that directory's ``out``.

A page on which the object raises is a page failure with a fixed reason; the service stays up
and the client exits with the code the recipe maps to that reason (``FAILURE_EXITS``). Every
other client failure exits 1, which the server treats as operational and restarts the service.
Standard library only; no subprocess, no shell.
"""

from __future__ import annotations

import argparse
import http.client
import importlib
import json
import re
import sys
import tempfile
import traceback
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

HOST = "127.0.0.1"  # never anything else: the pod proxy reaches only the page server
ROUTE = "/page"
WORK_PREFIX = "akc-page-"  # the page server's temporary work directories
SOURCE_NAMES = frozenset({"page.pdf", "page.png", "page.jpg"})  # the page server's file names
MAX_REQUEST_BYTES = 4096
SOCKET_TIMEOUT_S = 30.0
LOAD_FAILED_MARKER = "AKC_SERVICE_LOAD_FAILED"
# The service's page-failure reasons and the client's exit code for each; the C1 recipe's
# ``service.page_failure_exits`` is the same map read the other way (a test holds them equal).
FAILURE_EXITS = {"pipeline_raised": 3, "page_count_unsupported": 4}
ENGINES = frozenset({"paddle", "paddle_static", "paddle_dynamic", "transformers"})
_DEVICE = re.compile(r"(?:gpu|cpu)(?::[0-9]+)?")
PIPELINE_VERSION = "v1.6"
# ``predict`` arguments: the production adapter's literal values, and its defaults where it
# reads an option (``orientation_classify``, ``unwarp``, ``chart_recognition``,
# ``seal_recognition``, ``ocr_image_blocks`` default False; ``max_output_tokens`` 4096).
PREDICT_KWARGS: dict[str, Any] = {
    "use_doc_orientation_classify": False,
    "use_doc_unwarping": False,
    "use_layout_detection": True,
    "use_chart_recognition": False,
    "use_seal_recognition": False,
    "use_ocr_for_image_block": False,
    "format_block_content": True,
    "temperature": 0.0,
    "max_new_tokens": 4096,
}


def construct_kwargs(layout_dir: str, vl_rec_dir: str, engine: str, device: str) -> dict[str, Any]:
    """The production adapter's ``PaddleOCRVL(...)`` arguments. The directories are the recipe's
    verified model directories (production: its manifest's); ``engine`` and ``device`` are the
    recipe's (production: ``PADDLEOCR_ENGINE``, ``PADDLEOCR_DEVICE``, defaults paddle, gpu:0),
    checked against the same sets."""
    if engine not in ENGINES:
        raise ValueError(f"engine {engine!r} is not one of {sorted(ENGINES)}")
    if not _DEVICE.fullmatch(device):
        raise ValueError(f"device {device!r} is not gpu[:N] or cpu[:N]")
    return {
        "pipeline_version": PIPELINE_VERSION,
        "layout_detection_model_dir": layout_dir,
        "vl_rec_model_dir": vl_rec_dir,
        "use_layout_detection": True,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_queues": True,
        "engine": engine,
        "device": device,
    }


class PageService:
    """The loaded object and the one thing a request may name: a page file in a work directory
    of the page server, directly under ``work_root``."""

    def __init__(self, work_root: Path) -> None:
        self.work_root = work_root.resolve(strict=True)
        self.pipeline: Any = None

    def load(self, factory: Callable[..., Any], kwargs: dict[str, Any]) -> None:
        self.pipeline = factory(**kwargs)

    def loaded(self) -> bool:
        return self.pipeline is not None

    def source(self, value: Any) -> Path | None:
        """The page file, or None when ``value`` is anything but an existing regular file
        ``<work_root>/akc-page-*/page.{pdf,png,jpg}`` with an empty ``out`` beside it, reached
        without a link or a ``..``."""
        if not isinstance(value, str) or not 0 < len(value) <= 1024 or not value.isprintable():
            return None
        path = Path(value)
        if not path.is_absolute() or ".." in path.parts:
            return None
        try:
            if path.is_symlink() or path.parent.is_symlink():
                return None
            resolved = path.resolve(strict=True)
        except (OSError, ValueError):
            return None
        work = resolved.parent
        if (
            resolved.name not in SOURCE_NAMES
            or not work.name.startswith(WORK_PREFIX)
            or work.parent != self.work_root
            or not resolved.is_file()
        ):
            return None
        out = work / "out"
        if out.is_symlink() or not out.is_dir() or any(out.iterdir()):
            return None
        return resolved

    def run(self, source: Path) -> str | None:
        """One page: None when the markdown was written, else a fixed failure reason. Like the
        production adapter, the object's results are read in full and exactly one is required."""
        try:
            results = list(self.pipeline.predict(input=str(source), **PREDICT_KWARGS))
            if len(results) > 1:
                return "page_count_unsupported"
            for result in results:  # none: no file, and the page server says so
                result.save_to_markdown(save_path=str(source.parent / "out"))
        except Exception:
            traceback.print_exc(file=sys.stderr)  # the pod log; the answer carries the reason
            return "pipeline_raised"
        return None


def make_server(service: PageService, port: int) -> HTTPServer:
    """One request at a time (the page server never sends two); loopback only."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "akc-c1-service"
        sys_version = ""
        timeout = SOCKET_TIMEOUT_S

        def _send(self, status: int, value: dict[str, Any]) -> None:
            body = json.dumps(value, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/health":
                self._send(404, {"error": "not_found"})
            elif service.loaded():
                self._send(200, {"loaded": True})
            else:
                self._send(503, {"loaded": False})

        def do_POST(self) -> None:
            self.close_connection = True
            length = self.headers.get("Content-Length") or ""
            if self.path != ROUTE:
                self._send(404, {"error": "not_found"})
                return
            if not (length.isascii() and length.isdigit() and int(length) <= MAX_REQUEST_BYTES):
                self._send(411, {"error": "length_required"})
                return
            if not service.loaded():
                self._send(503, {"error": "not_loaded"})
                return
            try:
                payload = json.loads(self.rfile.read(int(length)))
            except (ValueError, RecursionError):
                payload = None
            source = (
                service.source(payload.get("source"))
                if isinstance(payload, dict) and set(payload) == {"source"}
                else None
            )
            if source is None:
                self._send(400, {"error": "source_invalid"})
                return
            self._send(200, {"failure": service.run(source)})

        def log_message(self, format: str, *args: Any) -> None:
            return None  # the page server logs each page; the vendor logs its own work

    return HTTPServer((HOST, port), Handler)


def page(url: str, source: str) -> int:
    """The recipe's per-page command: 0 when the markdown is written, the mapped exit code for
    a page failure, 1 for anything else (the page server then restarts the service)."""
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname != HOST or parts.path != ROUTE:
        print(f"refusing a service URL off loopback: {url!r}", file=sys.stderr)
        return 1
    body = json.dumps({"source": source}).encode("utf-8")
    connection = http.client.HTTPConnection(HOST, parts.port or 80, timeout=3600)
    try:
        connection.request("POST", ROUTE, body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        status, raw = response.status, response.read(MAX_REQUEST_BYTES)
    except OSError as exc:
        print(f"service unreachable: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        connection.close()
    try:
        answer = json.loads(raw)
    except ValueError:
        answer = None
    if status != 200 or not isinstance(answer, dict) or set(answer) != {"failure"}:
        print(f"service answered {status}: {raw[:200]!r}", file=sys.stderr)
        return 1
    failure = answer["failure"]
    if failure is None:
        return 0
    code = FAILURE_EXITS.get(failure) if isinstance(failure, str) else None
    print(f"page failure: {failure!r}", file=sys.stderr)
    return 1 if code is None else code


def _import_factory() -> Callable[..., Any]:
    factory: Callable[..., Any] = importlib.import_module("paddleocr").PaddleOCRVL
    return factory


def main(argv: list[str] | None = None, factory: Callable[..., Any] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, required=True)
    serve.add_argument("--layout-dir", required=True)
    serve.add_argument("--vl-rec-dir", required=True)
    serve.add_argument("--engine", required=True)
    serve.add_argument("--device", required=True)
    client = sub.add_parser("page")
    client.add_argument("--url", required=True)
    client.add_argument("--source", required=True)
    args = parser.parse_args(argv)
    if args.command == "page":
        return page(args.url, args.source)
    service = PageService(Path(tempfile.gettempdir()))  # the page server's temporary root
    try:
        kwargs = construct_kwargs(args.layout_dir, args.vl_rec_dir, args.engine, args.device)
        service.load(factory or _import_factory(), kwargs)
    except Exception as exc:  # operational: the page server sees the exit and gives up
        traceback.print_exc(file=sys.stderr)
        print(f"{LOAD_FAILED_MARKER} {type(exc).__name__}", file=sys.stderr, flush=True)
        return 2
    print("PaddleOCRVL loaded; serving on 127.0.0.1", flush=True)
    make_server(service, args.port).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
