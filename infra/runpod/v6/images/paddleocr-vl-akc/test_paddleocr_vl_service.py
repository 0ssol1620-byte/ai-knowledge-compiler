"""C1's loopback service with a fake ``PaddleOCRVL`` injected: no paddle import, no GPU.

The fake records how often it is constructed and what ``predict`` is given. The page server's
own ``command_pipeline`` runs the C1 recipe's client command against a real service on a
loopback port, so the recipe, the client, the service and the server's exit-code handling are
the shipped code; only the vendor object is fake.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import http.client
import importlib.util
import json
import os
import re
import socket
import sys
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar
from urllib.parse import urlsplit

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[4]
_ADAPTER = _ROOT / "workers" / "gpu-parser" / "paddleocr_adapter.py"
_SERVER_DIR = _HERE.parent / "mineru-pipeline-akc"
_SOURCE = b"%PDF-1.4 a fake page"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


svc = _load("paddleocr_vl_service", _HERE / "paddleocr_vl_service.py")
srv = _load("c1_page_server", _SERVER_DIR / "mineru_akc_server.py")
C1 = srv.load_recipe(_SERVER_DIR / "recipes" / "c1-paddleocr-vl.json")


class FakeResult:
    def __init__(self, text: str) -> None:
        self.text = text

    def save_to_markdown(self, save_path: str) -> None:
        (Path(save_path) / "page.md").write_text(self.text, encoding="utf-8")


class FakeVL:
    """Stands in for ``paddleocr.PaddleOCRVL``. ``plan`` decides each predict call in turn:
    an int is that many results, an exception is raised."""

    constructed: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        FakeVL.constructed.append(kwargs)
        self.calls: list[dict[str, Any]] = []
        self.plan: list[Any] = []

    def predict(self, **kwargs: Any) -> Iterator[FakeResult]:
        self.calls.append(kwargs)
        step = self.plan.pop(0) if self.plan else 1
        if isinstance(step, BaseException):
            raise step
        return iter([FakeResult(f"# page {len(self.calls)}\n") for _ in range(step)])


@pytest.fixture(autouse=True)
def _fresh() -> None:
    FakeVL.constructed = []


def _kwargs() -> dict[str, Any]:
    return dict(svc.construct_kwargs("/m/layout", "/m/vl", "paddle", "gpu:0"))


@contextlib.contextmanager
def _running(service: Any) -> Iterator[int]:
    server = svc.make_server(service, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def _work(root: Path, name: str = "akc-page-abc", file: str = "page.pdf") -> Path:
    work = root / name
    (work / "out").mkdir(parents=True)
    source = work / file
    source.write_bytes(_SOURCE)
    return source


def _health(port: int) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", "/health")
        return connection.getresponse().status
    finally:
        connection.close()


def _url(port: int) -> str:
    return f"http://127.0.0.1:{port}/page"


# --- the object is loaded once; health follows it ----------------------------------------------


def test_the_object_is_constructed_once_across_pages(tmp_path: Path) -> None:
    service = svc.PageService(tmp_path)
    service.load(FakeVL, _kwargs())
    with _running(service) as port:
        for index in range(5):
            source = _work(tmp_path, f"akc-page-{index}")
            assert svc.page(_url(port), str(source)) == 0
            assert (source.parent / "out" / "page.md").read_text(encoding="utf-8").startswith("#")
    assert len(FakeVL.constructed) == 1 and len(service.pipeline.calls) == 5
    first = dict(service.pipeline.calls[0])
    assert Path(first.pop("input")).parent.name == "akc-page-0"
    assert first == svc.PREDICT_KWARGS


def test_health_is_200_only_once_the_object_is_loaded(tmp_path: Path) -> None:
    service = svc.PageService(tmp_path)
    with _running(service) as port:
        assert _health(port) == 503
        source = _work(tmp_path)
        assert svc.page(_url(port), str(source)) == 1  # not loaded: operational, not a page
        service.load(FakeVL, _kwargs())
        assert _health(port) == 200
        assert svc.page(_url(port), str(source)) == 0


def test_a_raising_page_is_a_failure_and_the_next_page_works(tmp_path: Path) -> None:
    service = svc.PageService(tmp_path)
    service.load(FakeVL, _kwargs())
    service.pipeline.plan = [RuntimeError("CUDA error on this page"), 1]
    with _running(service) as port:
        bad = _work(tmp_path, "akc-page-bad")
        assert svc.page(_url(port), str(bad)) == svc.FAILURE_EXITS["pipeline_raised"]
        assert list((bad.parent / "out").iterdir()) == []
        good = _work(tmp_path, "akc-page-good")
        assert svc.page(_url(port), str(good)) == 0
        assert _health(port) == 200
    assert len(FakeVL.constructed) == 1


def test_a_source_read_as_more_than_one_page_writes_nothing(tmp_path: Path) -> None:
    service = svc.PageService(tmp_path)
    service.load(FakeVL, _kwargs())
    service.pipeline.plan = [3]
    source = _work(tmp_path)
    assert service.run(source) == "page_count_unsupported"
    assert list((source.parent / "out").iterdir()) == []


def test_a_construction_failure_is_an_operational_exit_with_a_marker(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken(**kwargs: Any) -> Any:
        raise OSError("model directory unreadable")

    argv = ["serve", "--port", "0", "--layout-dir", "/m/l", "--vl-rec-dir", "/m/v"]
    assert svc.main([*argv, "--engine", "paddle", "--device", "gpu:0"], factory=broken) == 2
    assert f"{svc.LOAD_FAILED_MARKER} OSError" in capsys.readouterr().err
    assert svc.main([*argv, "--engine", "vllm", "--device", "gpu:0"], factory=FakeVL) == 2
    assert svc.main([*argv, "--engine", "paddle", "--device", "tpu"], factory=FakeVL) == 2
    assert FakeVL.constructed == []


def test_the_page_server_reports_a_service_that_cannot_load(tmp_path: Path) -> None:
    """The real ``Service.start`` of the page server against the real service file: the object
    cannot be constructed (here: an engine production does not allow), the child exits non-zero
    and the server's existing path says the service did not become healthy."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    spec = {
        "argv": [
            sys.executable,
            str(_HERE / "paddleocr_vl_service.py"),
            "serve",
            "--port",
            str(port),
            "--layout-dir",
            "/m/l",
            "--vl-rec-dir",
            "/m/v",
            "--engine",
            "not-an-engine",
            "--device",
            "gpu:0",
        ],
        "health_url": f"http://127.0.0.1:{port}/health",
        "startup_timeout_s": 60,
    }
    service = srv.Service(spec, dict(os.environ))
    assert service.start() is False
    assert service.child is not None and service.child.poll() == 2


# --- the arguments are production's ------------------------------------------------------------

# Copied from workers/gpu-parser/paddleocr_adapter.py (PaddleOcrVlAdapter.__init__ and
# .process): each keyword and the source text of the value production passes. The test below
# reads the adapter as text, so a change on either side fails it.
PRODUCTION_CONSTRUCT = {
    "pipeline_version": "_PIPELINE_VERSION",
    "layout_detection_model_dir": "str(layout_dir)",
    "vl_rec_model_dir": "str(recognition_dir)",
    "use_layout_detection": "True",
    "use_doc_orientation_classify": "False",
    "use_doc_unwarping": "False",
    "use_queues": "True",
    "engine": "engine",
    "device": "device",
}
PRODUCTION_PREDICT = {
    "input": "str(input_path)",
    "use_doc_orientation_classify": "_boolean_option(options, 'orientation_classify')",
    "use_doc_unwarping": "_boolean_option(options, 'unwarp')",
    "use_layout_detection": "True",
    "use_chart_recognition": "_boolean_option(options, 'chart_recognition')",
    "use_seal_recognition": "_boolean_option(options, 'seal_recognition')",
    "use_ocr_for_image_block": "_boolean_option(options, 'ocr_image_blocks')",
    "format_block_content": "True",
    "temperature": "0.0",
    "max_new_tokens": "max_new_tokens",
}


def _production_calls() -> tuple[dict[str, str], dict[str, str]]:
    tree = ast.parse(_ADAPTER.read_text(encoding="utf-8"))
    construct: dict[str, str] = {}
    predict: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = ast.unparse(node.func)
        if target in {"pipeline_type", "self._pipeline.predict"}:
            found = {kw.arg or "**": ast.unparse(kw.value) for kw in node.keywords}
            (construct if target == "pipeline_type" else predict).update(found)
    return construct, predict


def test_the_arguments_are_the_production_adapters() -> None:
    construct, predict = _production_calls()
    assert construct == PRODUCTION_CONSTRUCT
    assert predict == PRODUCTION_PREDICT
    text = _ADAPTER.read_text(encoding="utf-8")
    # where production computes a value, the default it computes it from
    assert '_PIPELINE_VERSION = "v1.6"' in text
    assert 'os.getenv("PADDLEOCR_ENGINE", "paddle")' in text
    assert 'os.getenv("PADDLEOCR_DEVICE", "gpu:0")' in text
    assert 'options.get("max_output_tokens", 4096)' in text
    assert "    default: bool = False," in text  # _boolean_option's default

    def value(source: str, *, layout: str, vl: str) -> Any:
        node = ast.parse(source, mode="eval").body
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "_boolean_option":
            return False
        return {
            "_PIPELINE_VERSION": "v1.6",
            "str(layout_dir)": layout,
            "str(recognition_dir)": vl,
            "engine": "paddle",
            "device": "gpu:0",
            "max_new_tokens": 4096,
            "str(input_path)": "<the page>",
        }[source]

    expected = {k: value(v, layout="/L", vl="/V") for k, v in PRODUCTION_CONSTRUCT.items()}
    assert svc.construct_kwargs("/L", "/V", "paddle", "gpu:0") == expected
    expected = {k: value(v, layout="", vl="") for k, v in PRODUCTION_PREDICT.items()}
    assert expected == {"input": "<the page>", **svc.PREDICT_KWARGS}


def test_the_recipe_runs_the_service_with_the_verified_directories() -> None:
    argv = C1["service"]["argv"]
    pairs = {argv[i]: argv[i + 1] for i in range(len(argv) - 1)}
    assert argv[1:3] == ["/opt/akc/paddleocr_vl_service.py", "serve"]
    assert pairs["--layout-dir"] == C1["aux_models"][0]["dir"]
    assert pairs["--vl-rec-dir"] == C1["model"]["dir"]
    assert (pairs["--engine"], pairs["--device"]) == ("paddle", "gpu:0")  # production's defaults
    assert C1["service"]["health_url"] == f"http://127.0.0.1:{pairs['--port']}/health"
    assert C1["service"]["page_failure_exits"] == {
        str(code): reason for reason, code in svc.FAILURE_EXITS.items()
    }
    assert (
        srv.recipe_receipt(C1, {}, {"model": "a" * 64, "layout_detection": "b" * 64})[
            "includes_model_load"
        ]
        is False
    )
    docker = (_HERE / "Dockerfile").read_text(encoding="utf-8")
    assert "infra/runpod/v6/images/paddleocr-vl-akc/paddleocr_vl_service.py /opt/akc/" in docker


# --- what a request can name -------------------------------------------------------------------


def test_the_client_command_takes_only_the_validated_page_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server's argv rule holds for C1: whatever page and language a request carries, the
    command is the recipe's items with the server's own page file and output directory."""
    work = Path(tempfile.gettempdir()) / "akc-page-x"
    for page in (0, None):
        for lang in (None, *C1["lang_by_language"].values()):
            argv = srv.vendor_argv(C1, work / "page.pdf", work / "out", page, lang)
            assert argv == [a.format(source=work / "page.pdf") for a in C1["argv"]]
    pairs = {argv[i]: argv[i + 1] for i in range(len(argv) - 1)}
    assert urlsplit(pairs["--url"]).hostname == "127.0.0.1"
    connected: list[tuple[Any, ...]] = []

    def no_connection(*args: Any, **kwargs: Any) -> Any:
        connected.append(args)
        raise OSError("the client must not connect here")

    monkeypatch.setattr(svc.http.client, "HTTPConnection", no_connection)
    for bad in (
        "http://10.0.0.1:8081/page",
        "http://localhost:8081/page",
        "https://127.0.0.1:8081/page",
        "http://127.0.0.1:1/x",
    ):
        assert svc.page(bad, str(work / "page.pdf")) == 1
    assert connected == []  # refused before any connection, not by a failed one


def test_the_service_binds_loopback_only(tmp_path: Path) -> None:
    server = svc.make_server(svc.PageService(tmp_path), 0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()
    text = (_HERE / "paddleocr_vl_service.py").read_text(encoding="utf-8")
    assert re.search(r"\bimport (subprocess|shlex)\b|os\.system|shell=", text) is None


def test_only_a_page_file_in_a_server_work_directory_is_accepted(tmp_path: Path) -> None:
    """Every value but ``<root>/akc-page-*/page.{pdf,png,jpg}`` with an empty ``out`` is refused,
    whatever its type or shape."""
    root = tmp_path / "root"
    root.mkdir()
    service = svc.PageService(root)
    good = _work(root)
    assert service.source(str(good)) == good.resolve()
    for file in ("page.png", "page.jpg"):
        assert service.source(str(_work(root, f"akc-page-{file}", file))) is not None
    outside = _work(tmp_path, "akc-page-outside")
    deeper = _work(root / "akc-page-a", "akc-page-b")
    other_name = _work(root, "akc-page-name", "doc.pdf")
    other_dir = _work(root, "work-1")
    full = _work(root, "akc-page-full")
    (full.parent / "out" / "stale.md").write_text("x", encoding="utf-8")
    no_out = root / "akc-page-noout"
    no_out.mkdir()
    (no_out / "page.pdf").write_bytes(_SOURCE)
    as_dir = root / "akc-page-dir" / "page.pdf"
    as_dir.mkdir(parents=True)
    (as_dir.parent / "out").mkdir()
    hostile: list[Any] = [
        None,
        0,
        1.5,
        True,
        [],
        {},
        [str(good)],
        {"path": str(good)},
        "",
        " ",
        "page.pdf",
        "akc-page-abc/page.pdf",
        str(good) + "\x00",
        str(good) + "\n",
        str(good.parent / ".." / "akc-page-abc" / "page.pdf"),
        str(good.parent / "out"),
        str(good.parent),
        str(root),
        str(outside),
        str(deeper),
        str(other_name),
        str(other_dir),
        str(full),
        str(no_out / "page.pdf"),
        str(as_dir),
        str(root / "akc-page-missing" / "page.pdf"),
        "x" * 5000,
        "/etc/passwd",
        "C:\\Windows\\win.ini",
    ]
    with contextlib.suppress(OSError):  # symbolic links need a privilege on Windows
        link = root / "akc-page-link"
        link.symlink_to(good.parent, target_is_directory=True)
        hostile.append(str(link / "page.pdf"))
        file_link = _work(root, "akc-page-filelink").parent / "page.png"
        file_link.symlink_to(good)
        hostile.append(str(file_link))
    accepted = [value for value in hostile if service.source(value) is not None]
    assert accepted == []


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"null",
        b"[]",
        b'{"source": 1}',
        b'{"source": "x", "out": "/tmp"}',
        b"\xff",
        b"[" * 4000,
        b'{"src": "x"}',
    ],
    ids=["empty", "null", "list", "int", "extra-key", "not-utf8", "deep", "other-key"],
)
def test_a_malformed_request_is_a_400_and_runs_nothing(tmp_path: Path, body: bytes) -> None:
    service = svc.PageService(tmp_path)
    service.load(FakeVL, _kwargs())
    with _running(service) as port:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("POST", "/page", body=body)
            response = connection.getresponse()
            assert (response.status, json.loads(response.read())) == (
                400,
                {"error": "source_invalid"},
            )
        finally:
            connection.close()
        oversize = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            oversize.request("POST", "/page", body=b"x" * (svc.MAX_REQUEST_BYTES + 1))
            assert oversize.getresponse().status == 411
        finally:
            oversize.close()
    assert service.pipeline.calls == []


# --- through the page server's own command pipeline --------------------------------------------


class FakeServerService:
    def __init__(self) -> None:
        self.recovered = 0

    def available(self) -> bool:
        return True

    def ready(self) -> bool:
        return True

    def recover(self) -> None:
        self.recovered += 1


def test_the_page_server_runs_c1_pages_through_the_service() -> None:
    """The C1 recipe's argv (interpreter and file swapped for this checkout's), the server's
    ``command_pipeline``, the real client and a real service: a page is the markdown; a page
    on which the object raises is the failure row ``pipeline_raised`` with no restart; a source
    of three pages is ``page_count_unsupported``; the object was built once."""
    service = svc.PageService(Path(tempfile.gettempdir()))  # where the server makes its work dirs
    service.load(FakeVL, _kwargs())
    with _running(service) as port:
        recipe = copy.deepcopy(C1)
        recipe["argv"] = [
            {
                "/app/.venv/bin/python": sys.executable,
                "/opt/akc/paddleocr_vl_service.py": str(_HERE / "paddleocr_vl_service.py"),
                C1["argv"][C1["argv"].index("--url") + 1]: _url(port),
            }.get(item, item)
            for item in C1["argv"]
        ]
        server_side = FakeServerService()
        run = srv.command_pipeline(recipe, server_side, dict(os.environ))
        assert run(_SOURCE, ".pdf", 0, None) == "# page 1\n"
        service.pipeline.plan = [ValueError("bad page"), 3, 1]
        for reason in ("pipeline_raised", "page_count_unsupported"):
            with pytest.raises(srv.PageFailure) as caught:
                run(_SOURCE, ".pdf", 0, None)
            assert caught.value.reason == reason
        assert run(_SOURCE, ".png", None, None) == "# page 4\n"
        assert server_side.recovered == 0
    assert len(FakeVL.constructed) == 1
    received = service.pipeline.calls[0]["input"]
    assert Path(received).name == "page.pdf" and Path(received).parent.name.startswith("akc-page-")
