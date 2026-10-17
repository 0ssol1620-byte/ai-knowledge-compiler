"""AT-6 inputs read back by the pinned evaluators' own loaders: offline, read-only, unmodified.

Each test writes SYNTHETIC converted files under ``tmp_path`` and hands them to the code the
pinned evaluator itself runs to find and read a candidate, taken by path from a local checkout:

- olmOCR-bench ``cfa88c1e``: ``evaluate_candidate`` (benchmark.py), which maps every PDF to its
  ``<stem>_pg<page>_repeat<r>.md`` files and reads them. Its module imports pypdf, numpy,
  fuzzysearch and playwright for scoring, which no interpreter here has, so the function alone is
  compiled from the pinned source as it stands, with the module's own stdlib imports and ``tqdm``
  (a progress bar) as the identity.
- OmniDocBench ``193627ae``: ``End2EndDataset._resolve_prediction_path`` and ``read_md_file``,
  imported in the checkout's own ``.venv``.
- ParseBench ``1d460294``: ``EvaluationRunner._find_result_files`` / ``_load_inference_result``
  and the layout-detection evaluator's adapter and label projection, imported in the checkout's
  own ``.venv``.

A missing checkout, interpreter or git skips with the missing path named. A checkout that is
present but not at the pin, or whose tracked files differ from it, fails. Nothing is written into
a checkout: subprocesses run with ``-B`` and git with ``--no-optional-locks``.
"""

from __future__ import annotations

import ast
import glob
import importlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from research.vendor_comparison_20261017.adapters import tavonel_live as tl

CACHE = Path(
    os.environ.get(
        "TAVONEL_EVALUATOR_CACHE", r"D:\CodexProjects\ai-knowledge-compiler\benchmark\cache"
    )
)
PINS = {
    "olmocr": "cfa88c1eb1c2ec4495c84d6820ffe85d33b7408c",
    "omnidoc": "193627ae9e97d89188468ed1ee3b7a856ff76044",
    "parsebench": "1d460294b3b9c57fb3fa944dc17a9c044c24d1e5",
}
FIXTURE = json.loads(
    (Path(tl.__file__).parents[1] / "fixtures/evaluator_inputs/SYNTHETIC-tavonel_live_regions.json")
    .read_bytes()
    .decode("utf-8")
)
ONE_PAGE = tl.read_regions(FIXTURE["responses"]["one_page_image"])
TWO_PAGE = tl.read_regions(FIXTURE["responses"]["two_page_pdf"])
ONE_PAGE_MD = "SYNTHETIC 표 제목처럼 보이는 문단\n\nSYNTHETIC body | not a table"

# Run inside the evaluator's interpreter before any evaluator import: the same refusal the
# package conftest applies in-process, so a loader that reached for the network would fail.
_NETWORK_OFF = """
import socket
def _refuse(*_a, **_k):
    raise OSError("network access attempted in an offline evaluator check")
socket.socket.connect = socket.socket.connect_ex = socket.socket.sendto = _refuse
socket.create_connection = socket.getaddrinfo = _refuse
"""

_OMNIDOC_DRIVER = """
import json, sys
checkout, pred_folder, out, *names = sys.argv[1:]
sys.path.insert(0, checkout)
from src.dataset.end2end_dataset import End2EndDataset, read_md_file
rows = {}
for name in names:
    path = End2EndDataset._resolve_prediction_path(None, pred_folder, name)
    rows[name] = None if path is None else {"path": path, "markdown": read_md_file(path)}
with open(out, "w", encoding="utf-8") as handle:
    json.dump(rows, handle)
"""

_PARSEBENCH_DRIVER = """
import json, sys
from pathlib import Path
checkout, output_dir, out = sys.argv[1:]
sys.path.insert(0, checkout + "/src")
from parse_bench.evaluation.evaluators.layoutdet import LayoutDetectionEvaluator
from parse_bench.evaluation.layout_adapters import create_layout_adapter_for_result
from parse_bench.evaluation.runner import EvaluationRunner
evaluator = LayoutDetectionEvaluator()
rows = {}
for path in EvaluationRunner._find_result_files(None, Path(output_dir)):
    result = EvaluationRunner._load_inference_result(None, path)
    row = None
    if result is not None:
        row = {
            "group": path.parent.name,
            "product_type": result.product_type.value,
            "example_id": result.request.example_id,
            "markdown": result.output.markdown,
        }
        if row["product_type"] == "layout_detection":
            layout = create_layout_adapter_for_result(result).to_layout_output(result)
            row["predictions"] = evaluator._extract_predictions(
                result, layout, target_ontology=evaluator._default_ontology
            )
    rows[path.relative_to(output_dir).as_posix()] = row
with open(out, "w", encoding="utf-8") as handle:
    json.dump(rows, handle, ensure_ascii=False)
"""


def _git(root: Path, *args: str) -> str:
    git = shutil.which("git")
    if git is None:
        pytest.skip(f"git not on PATH: cannot check {root} against its pin")
    done = subprocess.run(  # noqa: S603 - fixed argv, read-only git query
        [git, "--no-optional-locks", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _checkout(name: str, loader: str) -> Path:
    root = CACHE / name
    if not (root / loader).is_file():
        pytest.skip(f"evaluator checkout absent: {root / loader} not found")
    head = _git(root, "rev-parse", "HEAD").strip()
    assert head == PINS[name], f"{root} is at {head}, not the pin {PINS[name]}"
    dirty = _git(root, "status", "--porcelain", "--untracked-files=no")
    assert dirty == "", f"{root} tracked files differ from the pin:\n{dirty}"
    return root


def _interpreter(root: Path) -> Path:
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        pytest.skip(f"evaluator interpreter absent: {python} not found")
    return python


def _drive(python: Path, driver: str, *args: str | Path, scratch: Path) -> None:
    # -I: no user site, no PYTHON* variables, no cwd on sys.path. -B: no bytecode written into
    # the checkout. NUMBA_CACHE_DIR: ParseBench's fast_tree_edit uses ``@njit(cache=True)``,
    # whose cache probe otherwise creates and deletes a file in the checkout's __pycache__.
    # -X utf8: the evaluators run on UTF-8 Linux hosts, and ParseBench opens result files with
    # the locale codec (runner.py ``open(result_path)``), so on a cp949 Windows locale it would
    # fail to decode the UTF-8 Korean fixture and silently skip the file.
    done = subprocess.run(  # noqa: S603 - the pinned checkout's own interpreter, fixed driver
        [str(python), "-I", "-B", "-X", "utf8", "-c", _NETWORK_OFF + driver, *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=600,
        env={
            **os.environ,
            "HF_HUB_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "NUMBA_CACHE_DIR": str(scratch / "SYNTHETIC-numba-cache"),
        },
    )
    assert done.returncode == 0, done.stderr[-4000:]


def _write(base: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))


def _olmocr_evaluate_candidate(root: Path) -> Callable[..., Any]:
    """``evaluate_candidate`` compiled from the pinned benchmark.py, its body untouched."""
    path = root / "benchmark.py"
    tree = ast.parse(path.read_bytes().decode("utf-8"), filename=str(path))
    namespace: dict[str, Any] = {"__name__": "olmocr_bench_benchmark"}
    for node in tree.body:
        if isinstance(node, ast.Import | ast.ImportFrom):
            module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            if module and module.split(".")[0] in sys.stdlib_module_names:
                code = compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec")
                exec(code, namespace)  # noqa: S102 - the evaluator's own stdlib import line
    # Non-stdlib names the function touches: tqdm only wraps the futures for a progress bar, and
    # BasePDFTest appears only in the signature's annotations.
    namespace["tqdm"] = lambda iterable, **_kwargs: iterable
    namespace["BasePDFTest"] = object
    (function,) = [
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "evaluate_candidate"
    ]
    code = compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec")
    exec(code, namespace)  # noqa: S102 - the pinned evaluator function, unmodified
    evaluate: Callable[..., Any] = namespace["evaluate_candidate"]
    return evaluate


@dataclass(frozen=True)
class _ReadProbe:
    """Stands in for an olmOCR test: passes only on the exact text this page was given."""

    id: str
    pdf: str
    page: int
    expected: str
    type: str = "SYNTHETIC_read_probe"

    def run(self, md_content: str) -> tuple[bool, str]:
        return md_content == self.expected, f"read {md_content!r}"


def _olmocr_bench(tmp_path: Path) -> tuple[Any, ...]:
    root = _checkout("olmocr", "benchmark.py")
    evaluate_candidate = _olmocr_evaluate_candidate(root)
    pages = {"SYNTHETIC-doc": (TWO_PAGE, 3), "SYNTHETIC-refused": ([], 2)}
    pdf_folder = tmp_path / "pdfs"
    candidate = tmp_path / "SYNTHETIC-tavonel-live"
    expected: dict[tuple[str, int], str] = {}
    for stem, (regions, count) in pages.items():
        source = f"bench_data/pdfs/table_tests/{stem}.pdf"
        (pdf_folder / "table_tests").mkdir(parents=True, exist_ok=True)
        (pdf_folder / "table_tests" / f"{stem}.pdf").write_bytes(b"%PDF SYNTHETIC")
        for repeat in (1, 2):
            files = tl.olmocr_candidate(source, regions, pages=count, repeat=repeat)
            _write(candidate, files)
            for page in range(1, count + 1):
                expected[(stem, page)] = files[f"table_tests/{stem}_pg{page}_repeat{repeat}.md"]
    # benchmark.py main(): pdf_basenames are the PDFs' paths relative to the pdfs folder.
    pdf_basenames = [
        os.path.relpath(p, pdf_folder)
        for p in glob.glob(os.path.join(pdf_folder, "**/*.pdf"), recursive=True)
    ]
    probes = [
        _ReadProbe(f"SYNTHETIC-{stem}-{page}", name, page, expected[(stem, page)])
        for name in pdf_basenames
        for (stem, page) in expected
        if Path(name).stem == stem
    ]
    assert len(probes) == 5
    return evaluate_candidate(str(candidate), probes, pdf_basenames), expected


def test_olmocr_reads_every_page_file_including_the_empty_ones(tmp_path: Path) -> None:
    (score, total, errors, failures, _types, scores, results), expected = _olmocr_bench(tmp_path)
    assert (errors, failures) == ([], [])
    assert (total, scores, score) == (5, [1.0] * 5, 1.0)
    assert expected[("SYNTHETIC-doc", 3)] == expected[("SYNTHETIC-refused", 1)] == ""
    assert (
        expected[("SYNTHETIC-doc", 1)]
        == "SYNTHETIC heading-like line\n\nSYNTHETIC second paragraph."
    )
    assert sum(len(by_page) for by_page in results.values()) == 5


def test_olmocr_a_missing_page_is_an_error_not_an_empty_prediction(tmp_path: Path) -> None:
    # Why the adapter writes an empty file for a page with no region: without one the
    # evaluator reports the page missing and scores it 0 with an error.
    root = _checkout("olmocr", "benchmark.py")
    evaluate_candidate = _olmocr_evaluate_candidate(root)
    source = "bench_data/pdfs/table_tests/SYNTHETIC-doc.pdf"
    files = tl.olmocr_candidate(source, TWO_PAGE, pages=3)
    del files["table_tests/SYNTHETIC-doc_pg3_repeat1.md"]
    _write(tmp_path / "SYNTHETIC-tavonel-live", files)
    pdf = os.path.join("table_tests", "SYNTHETIC-doc.pdf")
    probes = [_ReadProbe("SYNTHETIC-p3", pdf, 3, "")]
    _s, _t, errors, _f, _ty, scores, results = evaluate_candidate(
        str(tmp_path / "SYNTHETIC-tavonel-live"), probes, [pdf]
    )
    assert scores == [0.0]
    assert len(errors) == 1 and "missing MD repeats" in errors[0] and "page 3" in errors[0]
    assert results[pdf][3][0][1:] == (False, "Missing MD files")


def test_omnidocbench_resolves_and_reads_each_prediction(tmp_path: Path) -> None:
    root = _checkout("omnidoc", "src/dataset/end2end_dataset.py")
    python = _interpreter(root)
    files = {
        **tl.omnidocbench_prediction("images/SYNTHETIC-page.jpg", ONE_PAGE),
        **tl.omnidocbench_prediction("images/SYNTHETIC-refused.png", []),
    }
    _write(tmp_path, files)
    pred_folder = tmp_path / "markdown-repeat-1"
    out = tmp_path / "SYNTHETIC-omnidoc-read.json"
    names = ["SYNTHETIC-page.jpg", "SYNTHETIC-refused.png", "SYNTHETIC-absent.jpg"]
    _drive(python, _OMNIDOC_DRIVER, root, pred_folder, out, *names, scratch=tmp_path)
    rows = json.loads(out.read_bytes().decode("utf-8"))
    page, refused, absent = (rows[name] for name in names)
    assert Path(page["path"]) == pred_folder / "SYNTHETIC-page.md"
    assert page["markdown"] == ONE_PAGE_MD
    assert Path(refused["path"]) == pred_folder / "SYNTHETIC-refused.md"
    assert refused["markdown"] == ""
    # A page with no file at all is read as an empty page too (the evaluator warns and goes on).
    assert absent is None


def test_parsebench_loads_parse_and_layout_results_and_projects_text_boxes(
    tmp_path: Path,
) -> None:
    root = _checkout("parsebench", "src/parse_bench/evaluation/runner.py")
    python = _interpreter(root)
    for category in ("table", "layout"):
        _write(
            tmp_path,
            tl.parsebench_result(
                f"docs/{category}/SYNTHETIC-x.pdf",
                ONE_PAGE,
                image_size_px=(200, 100),
                recorded_at="2026-10-17T00:00:00+00:00",
                latency_ms=12,
            ),
        )
    out = tmp_path / "SYNTHETIC-parsebench-read.json"
    _drive(python, _PARSEBENCH_DRIVER, root, tmp_path, out, scratch=tmp_path.parent)
    rows = json.loads(out.read_bytes().decode("utf-8"))
    assert sorted(rows) == ["layout/SYNTHETIC-x.result.json", "table/SYNTHETIC-x.result.json"]
    parse, layout = rows["table/SYNTHETIC-x.result.json"], rows["layout/SYNTHETIC-x.result.json"]
    assert (parse["group"], parse["product_type"], parse["example_id"]) == (
        "table",
        "parse",
        "table/SYNTHETIC-x",
    )
    assert parse["markdown"] == layout["markdown"] == ONE_PAGE_MD
    assert (layout["group"], layout["product_type"]) == ("layout", "layout_detection")
    # The evaluator's label projection keeps every box as class Text, unranked, and its
    # normalised box is bbox1000 / 1000: pixels -> [0, 1] undoes the adapter's scaling exactly.
    predictions = layout["predictions"]
    assert [(p["class_name"], p["score"]) for p in predictions] == [("Text", 1.0), ("Text", 1.0)]
    assert [p["bbox"] for p in predictions] == [
        pytest.approx([v / 1000 for v in r.bbox1000]) for r in ONE_PAGE
    ]


def test_parsebench_refuses_the_empty_envelope_exactly_like_the_frozen_campaign_one(
    tmp_path: Path,
) -> None:
    # The pinned loader requires raw_output to be a dict (pipeline_io.py InferenceResult), so the
    # empty prediction - raw_output null, as the frozen campaign's empty_parsebench_result
    # writes it - is not loaded. The pinned runner then scores that test case as blank output
    # (runner.py "Score test cases with no inference result as blank output (0.0)"), so it stays
    # in N. Only raw_output decides it: the same envelope with raw_output {} loads.
    root = _checkout("parsebench", "src/parse_bench/evaluation/runner.py")
    python = _interpreter(root)
    frozen = importlib.import_module("build_recovery_counterfactual_candidate")
    kwargs: dict[str, Any] = {
        "image_size_px": (200, 100),
        "recorded_at": "2026-10-17T00:00:00+00:00",
        "latency_ms": 0,
    }
    _write(tmp_path, tl.parsebench_result("docs/chart/SYNTHETIC-empty.pdf", [], **kwargs))
    _write(tmp_path, tl.parsebench_result("docs/layout/SYNTHETIC-empty.pdf", [], **kwargs))
    _write(tmp_path, tl.parsebench_result("docs/chart/SYNTHETIC-frozen.pdf", ONE_PAGE, **kwargs))
    frozen.empty_parsebench_result(str(tmp_path / "chart/SYNTHETIC-frozen.result.json"))
    for name in ("chart/SYNTHETIC-empty", "layout/SYNTHETIC-empty"):
        envelope = json.loads((tmp_path / f"{name}.result.json").read_bytes().decode("utf-8"))
        assert envelope["raw_output"] is None
        envelope["raw_output"] = {}
        _write(tmp_path, {f"{name}-raw-output-object.result.json": json.dumps(envelope)})
    out = tmp_path / "SYNTHETIC-parsebench-read.json"
    _drive(python, _PARSEBENCH_DRIVER, root, tmp_path, out, scratch=tmp_path.parent)
    rows = json.loads(out.read_bytes().decode("utf-8"))
    assert len(rows) == 5
    for name in ("chart/SYNTHETIC-empty", "layout/SYNTHETIC-empty", "chart/SYNTHETIC-frozen"):
        assert rows[f"{name}.result.json"] is None, name
    chart = rows["chart/SYNTHETIC-empty-raw-output-object.result.json"]
    layout = rows["layout/SYNTHETIC-empty-raw-output-object.result.json"]
    assert (chart["product_type"], chart["markdown"]) == ("parse", "")
    assert (layout["product_type"], layout["markdown"], layout["predictions"]) == (
        "layout_detection",
        "",
        [],
    )


def test_an_absent_checkout_skips_naming_the_missing_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.modules[__name__], "CACHE", tmp_path / "SYNTHETIC-no-cache")
    with pytest.raises(pytest.skip.Exception, match="SYNTHETIC-no-cache") as skipped:
        _checkout("olmocr", "benchmark.py")
    assert str(tmp_path / "SYNTHETIC-no-cache" / "olmocr" / "benchmark.py") in str(skipped.value)
    with pytest.raises(pytest.skip.Exception, match="interpreter absent"):
        _interpreter(tmp_path)


def test_a_checkout_off_its_pin_or_edited_fails_instead_of_skipping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "olmocr"
    root.mkdir()
    (root / "benchmark.py").write_bytes(b"# SYNTHETIC stand-in, not the evaluator\n")
    identity = ["-c", "user.name=SYNTHETIC", "-c", "user.email=synthetic@invalid"]
    for args in (
        ["init", "-q"],
        ["add", "benchmark.py"],
        [*identity, "commit", "-qm", "SYNTHETIC"],
    ):
        _git(root, *args)
    monkeypatch.setattr(sys.modules[__name__], "CACHE", tmp_path)
    with pytest.raises(AssertionError, match="not the pin cfa88c1e"):
        _checkout("olmocr", "benchmark.py")
    head = _git(root, "rev-parse", "HEAD").strip()
    monkeypatch.setitem(PINS, "olmocr", head)
    assert _checkout("olmocr", "benchmark.py") == root
    (root / "benchmark.py").write_bytes(b"# SYNTHETIC edit\n")
    with pytest.raises(AssertionError, match="tracked files differ from the pin"):
        _checkout("olmocr", "benchmark.py")
