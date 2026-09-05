"""Official evaluators: pinned checkout, input layout, run command, watchdog.

One :class:`EvaluatorLane` describes everything needed to reproduce one
benchmark's score on one lane (``main`` or ``historical``): which repository,
which revision and where that revision came from, how the environment is set
up, what the canonical markdown has to be reshaped into, and the exact command
that produces the official numbers.

Three rules bind this module.

*``benchmark/cache`` is never mutated.* It is a clone source. Every run works
inside ``scores/_evaluators/<benchmark>/<revision>/``, which the campaign owns
and can delete.

*The layouts are copied, not invented.* Each one is derived from the previous
FOLYNTA campaign's scripts (``benchmark/runpod_eval/public_core_merge.py`` and
the ``evaluate_*_official.py`` trio) and from the evaluator sources
themselves, and is documented in ``arena/scoring/LAYOUTS.md``. Where the
canonical output cannot supply something an evaluator wants - layout boxes,
for instance - the field is left empty and the case is listed. No bbox is
fabricated to satisfy a schema.

*An evaluator that did not finish produces no number.* :func:`run_steps`
raises :class:`EvaluatorBlockedError` on a non-zero exit, a watchdog timeout
or a missing result file, and the caller records ``EVALUATOR_BLOCKED``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final, Literal

from arena.constants import BENCHMARK_KEYS, HISTORICAL_EVALUATOR_PINS
from arena.scoring import jsonio
from arena.scoring.errors import EvaluatorBlockedError, InputError, LayoutError
from arena.scoring.outputs import OutputRow, SourceIndex
from arena.scoring.paths import ScoringPaths

__all__ = [
    "DEFAULT_STEP_TIMEOUT_SECONDS",
    "EVALUATOR_REPOSITORIES",
    "LAYOUT_REVISION",
    "PARSEBENCH_GROUPS",
    "EvaluatorLane",
    "EvaluatorStep",
    "PrepareResult",
    "checkout_commands",
    "olmocr_markdown_name",
    "parsebench_result_document",
    "prepare_inputs",
    "resolve_gt_path",
    "resolve_lane",
    "run_steps",
]

Lane = Literal["main", "historical"]

#: Bumped whenever the evaluator-input layouts change. Recorded in every
#: summary so a score is tied to the adapter that built its input.
LAYOUT_REVISION: Final = "arena-layouts-v1"

EVALUATOR_REPOSITORIES: Final = {
    "parsebench": "https://github.com/run-llama/ParseBench.git",
    "omnidoc": "https://github.com/opendatalab/OmniDocBench.git",
    "olmocr": "https://github.com/jina-ai/olmocr-bench.git",
}

#: ``benchmark-registry.lock.yaml`` entrypoints, kept here so a lane can be
#: described when ``evaluator_registry.json`` has not been generated yet.
LOCK_ENTRYPOINTS: Final = {
    "parsebench": "uv run parse-bench evaluation run --output_dir OUTPUT_DIR",
    "omnidoc": "python pdf_validation.py --config config.yaml",
    "olmocr": "python benchmark.py --dir BENCH_DATA_DIR",
}

#: The documented environment setup for each evaluator, from its own README
#: and dependency file. These are recorded and printed; this lane never
#: installs anything as a side effect of scoring.
SETUP_COMMANDS: Final = {
    "parsebench": ("uv", "sync", "--extra", "runners"),
    "omnidoc": ("python", "-m", "pip", "install", "-e", "."),
    "olmocr": ("python", "-m", "pip", "install", "-r", "requirements.txt"),
}
SETUP_NOTES: Final = {
    "parsebench": (
        "ParseBench README 'Quick Start': `uv sync --extra runners`. The optional "
        "`--extra fast` adds a numba TEDS kernel with identical scores."
    ),
    "omnidoc": (
        "OmniDocBench README: conda env on Python 3.10 then `pip install -e .`; its "
        "pyproject pins every dependency with `==` and requires >=3.10,<3.12."
    ),
    "olmocr": (
        "olmOCR-bench requirements.txt, then `python -m playwright install chromium` "
        "for the math rendering tests."
    ),
}
EXTRA_SETUP_COMMANDS: Final = {
    "olmocr": (("python", "-m", "playwright", "install", "chromium"),),
}

#: (group, product_type) exactly as the 2026-08 campaign ran them.
PARSEBENCH_GROUPS: Final = (
    ("chart", "parse"),
    ("layout", "layout_detection"),
    ("table", "parse"),
    ("text_content", "parse"),
    ("text_formatting", "parse"),
)

#: ParseBench filters prediction files by their parent directory name; the two
#: text groups share one inference directory (``evaluation/runner.py``).
PARSEBENCH_INFERENCE_DIR: Final = {"text_content": "text", "text_formatting": "text"}

#: Watchdog defaults. A full benchmark is hours of CPU; the point of the cap is
#: to turn a hang into a recorded EVALUATOR_BLOCKED rather than a dead campaign.
DEFAULT_STEP_TIMEOUT_SECONDS: Final = {
    "parsebench": 6 * 3600,
    "omnidoc": 8 * 3600,
    "olmocr": 4 * 3600,
}

#: How many characters of stderr survive into a receipt.
STDERR_TAIL_CHARS: Final = 4000

_OMNIDOC_PREDICTION_DIR: Final = "markdown"


# ---------------------------------------------------------------------------
# lane resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvaluatorLane:
    benchmark: str
    lane: Lane
    repository: str
    revision: str
    revision_source: str
    entrypoint: str
    clone_source: str
    clone_source_kind: Literal["local_cache", "upstream"]
    checkout_dir: Path
    setup_commands: tuple[tuple[str, ...], ...]
    setup_note: str
    notes: tuple[str, ...] = ()

    def to_record(self) -> dict[str, Any]:
        return {
            "benchmark": self.benchmark,
            "lane": self.lane,
            "repository": self.repository,
            "revision": self.revision,
            "revision_source": self.revision_source,
            "entrypoint": self.entrypoint,
            "clone_source": self.clone_source,
            "clone_source_kind": self.clone_source_kind,
            "checkout_dir": str(self.checkout_dir),
            "setup_commands": [list(command) for command in self.setup_commands],
            "setup_note": self.setup_note,
            "notes": list(self.notes),
        }


def _registry_record(paths: ScoringPaths, benchmark: str) -> Mapping[str, Any] | None:
    path = paths.evaluator_registry
    if not jsonio.io_path(path).is_file():
        return None
    document = jsonio.read_json(path)
    records: Any = document
    if isinstance(document, Mapping):
        records = document.get("benchmarks", document)
    if isinstance(records, Mapping):
        entry = records.get(benchmark)
        if isinstance(entry, Mapping):
            return entry
        return None
    if isinstance(records, list):
        for entry in records:
            if isinstance(entry, Mapping) and entry.get("benchmark") == benchmark:
                return entry
    return None


def resolve_lane(
    paths: ScoringPaths,
    benchmark: str,
    lane: Lane,
    *,
    clone_source: str | None = None,
) -> EvaluatorLane:
    """Describe one evaluator lane, saying where each value came from.

    ``evaluator_registry.json`` is authoritative when it exists. When it does
    not, the revision falls back to ``arena.constants.HISTORICAL_EVALUATOR_PINS``
    and the fallback is written into ``notes`` and into every summary's
    provenance - a main-lane score pinned to the historical revision is not a
    main-lane score, and the record has to say so.
    """

    if benchmark not in BENCHMARK_KEYS:
        raise InputError(f"unknown benchmark {benchmark!r}; expected one of {BENCHMARK_KEYS}")
    if lane not in ("main", "historical"):
        raise InputError(f"unknown lane {lane!r}; expected 'main' or 'historical'")

    notes: list[str] = []
    record = _registry_record(paths, benchmark)
    historical_pin = HISTORICAL_EVALUATOR_PINS[benchmark]
    repository = EVALUATOR_REPOSITORIES[benchmark]
    entrypoint = LOCK_ENTRYPOINTS[benchmark]

    if record is None:
        revision = historical_pin
        revision_source = "arena.constants.HISTORICAL_EVALUATOR_PINS"
        notes.append(
            f"evaluator_registry.json is absent at {paths.evaluator_registry}; the "
            f"revision is the FOLYNTA historical pin {historical_pin}"
        )
        if lane == "main":
            notes.append(
                "the main lane is pinned to the historical revision because the campaign "
                "has not resolved a main pin yet; this score is not comparable to a "
                "main-lane score taken at the campaign's own pin"
            )
    else:
        field_name = "historical_pin" if lane == "historical" else "main_pin"
        value = record.get(field_name)
        if not isinstance(value, str) or not value:
            raise InputError(
                f"evaluator_registry.json has no usable {field_name} for {benchmark}"
            )
        revision = value
        revision_source = f"evaluator_registry.json:{field_name}"
        repository = str(record.get("repository") or repository)
        entrypoint = str(record.get("entrypoint") or entrypoint)
        if record.get("frozen") is not True:
            notes.append(
                "evaluator_registry.json is not frozen yet; the pin may still change "
                "(ARENA_CONTRACT section 3.8)"
            )

    if clone_source is not None:
        source = clone_source
        kind: Literal["local_cache", "upstream"] = (
            "local_cache" if not clone_source.startswith("http") else "upstream"
        )
        notes.append(f"clone source overridden on the command line: {clone_source}")
    elif revision == historical_pin:
        source = str(paths.evaluator_cache(benchmark))
        kind = "local_cache"
        notes.append(
            "cloned from the local pinned mirror under benchmark/cache, which is at "
            "this exact revision; benchmark/cache is a read-only clone source"
        )
    else:
        source = repository
        kind = "upstream"
        notes.append(
            "cloned from upstream because the requested revision is newer than the "
            "local benchmark/cache mirror"
        )

    return EvaluatorLane(
        benchmark=benchmark,
        lane=lane,
        repository=repository,
        revision=revision,
        revision_source=revision_source,
        entrypoint=entrypoint,
        clone_source=source,
        clone_source_kind=kind,
        checkout_dir=paths.evaluator_checkout(benchmark, revision),
        setup_commands=(SETUP_COMMANDS[benchmark], *EXTRA_SETUP_COMMANDS.get(benchmark, ())),
        setup_note=SETUP_NOTES[benchmark],
        notes=tuple(notes),
    )


def checkout_commands(lane: EvaluatorLane) -> tuple[tuple[str, ...], ...]:
    """The two commands that materialise a campaign-owned pinned checkout."""

    return (
        ("git", "clone", "--no-checkout", lane.clone_source, str(lane.checkout_dir)),
        ("git", "-C", str(lane.checkout_dir), "checkout", lane.revision),
    )


# ---------------------------------------------------------------------------
# ground truth resolution
# ---------------------------------------------------------------------------

#: Which ``gt_paths`` entry each evaluator's run command actually needs. The
#: registry lists every ground-truth file for the isolation audit; only one of
#: them is the evaluator's entry point, and guessing would be a silent choice.
_GT_SELECTOR: Final = {
    "omnidoc": ("OmniDocBench.json", "the end2end ground-truth annotation file"),
    "parsebench": ("docs", "the test-case document tree"),
    "olmocr": ("bench_data/pdfs", "the bench_data directory holding pdfs/ and the rule jsonl"),
}


def resolve_gt_path(
    paths: ScoringPaths, benchmark: str, gt_paths: Sequence[str], *, override: str | None = None
) -> Path:
    """The single ground-truth path this benchmark's evaluator is pointed at."""

    if override is not None:
        return Path(override)
    suffix, description = _GT_SELECTOR[benchmark]
    matches = [entry for entry in gt_paths if entry.endswith(suffix)]
    if len(matches) != 1:
        raise InputError(
            f"evaluator_registry gt_paths for {benchmark} must contain exactly one entry "
            f"ending in {suffix!r} ({description}); found {len(matches)}. Pass --gt-path "
            "to name it explicitly."
        )
    resolved = paths.repo_relative(matches[0])
    if benchmark == "olmocr":
        # The evaluator's --dir is the directory that *contains* pdfs/.
        resolved = resolved.parent
    return resolved


def registry_gt_paths(paths: ScoringPaths, benchmark: str) -> tuple[str, ...]:
    record = _registry_record(paths, benchmark)
    if record is None:
        return ()
    values = record.get("gt_paths")
    if not isinstance(values, list):
        return ()
    return tuple(str(value) for value in values)


# ---------------------------------------------------------------------------
# evaluator input layouts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PrepareResult:
    benchmark: str
    input_root: Path
    written: int
    skipped: tuple[dict[str, Any], ...]
    notes: tuple[str, ...]
    files_sha256: Mapping[str, str] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "benchmark": self.benchmark,
            "layout_revision": LAYOUT_REVISION,
            "input_root": str(self.input_root),
            "written": self.written,
            "skipped_count": len(self.skipped),
            "skipped": list(self.skipped),
            "notes": list(self.notes),
        }


def _source_stem(relative_posix: str) -> str:
    return PurePosixPath(relative_posix).stem


def _source_category(relative_posix: str) -> str:
    return PurePosixPath(relative_posix).parent.name


def _read_canonical(row: OutputRow) -> str:
    data = jsonio.io_path(row.canonical_path).read_bytes()
    return data.decode("utf-8")


def _load_elements(paths: ScoringPaths, row: OutputRow) -> list[Mapping[str, Any]] | None:
    """The optional ``<case_key>.elements.json`` beside the canonical markdown."""

    path = paths.elements_path(row.producing_model_key, row.case_key)
    if not jsonio.io_path(path).is_file():
        return None
    document = jsonio.read_json(path)
    if isinstance(document, list):
        return [item for item in document if isinstance(item, Mapping)]
    if isinstance(document, Mapping):
        elements = document.get("elements")
        if isinstance(elements, list):
            return [item for item in elements if isinstance(item, Mapping)]
    return None


def parsebench_result_document(
    *,
    example_id: str,
    source_relative_path: str,
    product_type: str,
    markdown: str,
    pipeline_name: str,
    elements: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """One ``<stem>.result.json`` in ParseBench's inference-result shape.

    The shape is the one ``public_core_merge.build_parsebench_result`` wrote in
    the 2026-08 campaign. What differs is deliberate: this campaign has no
    per-model layout block stream it can trust across twelve runtimes, so
    ``layout_pages[].items`` and ``predictions`` are populated only from an
    adapter-emitted ``elements.json``. When there is none they stay empty and
    the case is listed in the prepare receipt. An invented bbox would be a
    fabricated measurement (CLAUDE.md: never invent data to satisfy a schema).
    """

    request = {
        "example_id": example_id,
        "source_file_path": source_relative_path,
        "product_type": product_type,
        "schema_override": None,
        "config_override": None,
    }
    raw_output = {
        "markdown": markdown,
        "layout_revision": LAYOUT_REVISION,
        "elements_available": elements is not None,
    }
    if product_type == "layout_detection":
        predictions = [] if elements is None else _layout_predictions(elements)
        return {
            "request": request,
            "pipeline_name": pipeline_name,
            "product_type": product_type,
            "raw_output": raw_output,
            "output": {
                "task_type": "layout_detection",
                "example_id": example_id,
                "pipeline_name": pipeline_name,
                "predictions": predictions,
                "markdown": markdown,
            },
            "latency_in_ms": 0,
        }
    return {
        "request": request,
        "pipeline_name": pipeline_name,
        "product_type": product_type,
        "raw_output": raw_output,
        "output": {
            "task_type": "parse",
            "example_id": example_id,
            "pipeline_name": pipeline_name,
            "pages": [{"page_index": 0, "markdown": markdown}],
            "markdown": markdown,
            "job_id": None,
        },
        "latency_in_ms": 0,
    }


def _layout_predictions(elements: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Layout predictions from an adapter's ``elements.json``, or nothing.

    An element without a four-number ``bbox`` and a ``label`` contributes no
    prediction; it is dropped rather than given a placeholder box.
    """

    predictions: list[dict[str, Any]] = []
    for order_index, element in enumerate(elements):
        bbox = element.get("bbox")
        label = element.get("label")
        if not isinstance(bbox, list) or len(bbox) != 4 or not isinstance(label, str):
            continue
        try:
            box = [float(value) for value in bbox]
        except (TypeError, ValueError):
            continue
        predictions.append(
            {
                "bbox": box,
                "score": 1.0,
                "label": label,
                "page": 1,
                "content": element.get("content"),
                "provider_metadata": {"order_index": order_index},
            }
        )
    return predictions


def olmocr_markdown_name(source_relative_path: str, page_index: int) -> PurePosixPath:
    """``<rel>_pg<page>_repeat1.md`` relative to the candidate directory.

    ``benchmark.py`` matches ``^<pdf without .pdf>_pg\\d+_repeat\\d+\\.md$``
    against the path relative to the candidate folder, so the directory
    structure under ``bench_data/pdfs`` is reproduced exactly. The page number
    is one-based; the staged manifest's ``page_index`` is zero-based.
    """

    relative = PurePosixPath(source_relative_path)
    parts = relative.parts
    if len(parts) < 3 or parts[0] != "bench_data" or parts[1] != "pdfs":
        raise LayoutError(
            f"olmOCR source path {source_relative_path!r} is not under bench_data/pdfs"
        )
    inner = PurePosixPath(*parts[2:])
    return inner.with_name(f"{inner.stem}_pg{page_index + 1}_repeat1.md")


def prepare_inputs(
    paths: ScoringPaths,
    *,
    key: str,
    benchmark: str,
    rows: Sequence[OutputRow],
    source_index: SourceIndex,
    pipeline_name: str,
) -> PrepareResult:
    """Write one benchmark's evaluator input from frozen canonical markdown."""

    input_root = paths.evaluator_input(key, benchmark)
    if benchmark == "parsebench":
        return _prepare_parsebench(
            paths, input_root, rows, source_index, pipeline_name=pipeline_name
        )
    if benchmark == "omnidoc":
        return _prepare_omnidoc(input_root, rows, source_index)
    if benchmark == "olmocr":
        return _prepare_olmocr(input_root, rows, source_index, candidate=key)
    raise InputError(f"unknown benchmark {benchmark!r}")


def _skip(row: OutputRow, reason: str) -> dict[str, Any]:
    return {"case_key": row.case_key, "sample_id": row.sample_id, "reason": reason}


def _usable(row: OutputRow, skipped: list[dict[str, Any]]) -> bool:
    if row.unresolved:
        skipped.append(_skip(row, row.unresolved_reason or "unresolved composite page"))
        return False
    if row.status != "SUCCESS":
        skipped.append(_skip(row, f"page status is {row.status}, not SUCCESS"))
        return False
    if not jsonio.io_path(row.canonical_path).is_file():
        skipped.append(_skip(row, f"canonical output is missing at {row.canonical_path}"))
        return False
    return True


def _prepare_parsebench(
    paths: ScoringPaths,
    input_root: Path,
    rows: Sequence[OutputRow],
    source_index: SourceIndex,
    *,
    pipeline_name: str,
) -> PrepareResult:
    skipped: list[dict[str, Any]] = []
    digests: dict[str, str] = {}
    no_elements = 0
    written = 0
    for row in sorted(rows, key=lambda item: item.case_key):
        if not _usable(row, skipped):
            continue
        source = source_index.require(row.case_key)
        category = _source_category(source.source_relative_path)
        stem = _source_stem(source.source_relative_path)
        product_type = "layout_detection" if category == "layout" else "parse"
        elements = _load_elements(paths, row)
        if elements is None:
            no_elements += 1
        document = parsebench_result_document(
            example_id=f"{category}/{stem}",
            source_relative_path=source.source_relative_path,
            product_type=product_type,
            markdown=_read_canonical(row),
            pipeline_name=pipeline_name,
            elements=elements,
        )
        destination = input_root / category / f"{stem}.result.json"
        digests[f"{category}/{stem}.result.json"] = jsonio.write_json_atomic(
            destination, document
        )
        written += 1
    notes = [
        "layout: <evaluator_input>/<category>/<stem>.result.json; ParseBench filters "
        "prediction files by their parent directory name and the text_content and "
        "text_formatting groups share the 'text' directory (evaluation/runner.py).",
        f"{no_elements} of {written} cases had no elements.json, so their layout "
        "predictions are empty rather than fabricated.",
    ]
    return PrepareResult(
        benchmark="parsebench",
        input_root=input_root,
        written=written,
        skipped=tuple(skipped),
        notes=tuple(notes),
        files_sha256=digests,
    )


def _prepare_omnidoc(
    input_root: Path, rows: Sequence[OutputRow], source_index: SourceIndex
) -> PrepareResult:
    skipped: list[dict[str, Any]] = []
    digests: dict[str, str] = {}
    prediction_dir = input_root / _OMNIDOC_PREDICTION_DIR
    seen: dict[str, str] = {}
    written = 0
    for row in sorted(rows, key=lambda item: item.case_key):
        if not _usable(row, skipped):
            continue
        source = source_index.require(row.case_key)
        stem = _source_stem(source.source_relative_path)
        if stem in seen:
            raise LayoutError(
                f"two cases map to the OmniDocBench page name {stem!r}: "
                f"{seen[stem]} and {row.case_key}"
            )
        seen[stem] = row.case_key
        digests[f"{_OMNIDOC_PREDICTION_DIR}/{stem}.md"] = jsonio.write_text_atomic(
            prediction_dir / f"{stem}.md", _read_canonical(row)
        )
        written += 1
    notes = (
        "layout: <evaluator_input>/markdown/<source stem>.md, flat, named after the "
        "ground-truth image file so quick_match pairs them (the 2026-08 campaign used "
        "markdown-repeat-1/<stem>.md).",
        "the prediction directory name becomes the evaluator's result file prefix "
        "(<name>_quick_match_*), so it is fixed at 'markdown'.",
    )
    return PrepareResult(
        benchmark="omnidoc",
        input_root=input_root,
        written=written,
        skipped=tuple(skipped),
        notes=notes,
        files_sha256=digests,
    )


def _prepare_olmocr(
    input_root: Path,
    rows: Sequence[OutputRow],
    source_index: SourceIndex,
    *,
    candidate: str,
) -> PrepareResult:
    skipped: list[dict[str, Any]] = []
    digests: dict[str, str] = {}
    candidate_dir = input_root / candidate
    written = 0
    for row in sorted(rows, key=lambda item: item.case_key):
        if not _usable(row, skipped):
            continue
        source = source_index.require(row.case_key)
        relative = olmocr_markdown_name(source.source_relative_path, source.page_index)
        digests[f"{candidate}/{relative}"] = jsonio.write_text_atomic(
            candidate_dir / Path(*relative.parts), _read_canonical(row)
        )
        written += 1
    notes = (
        "layout: <evaluator_input>/<candidate>/<path under bench_data/pdfs>/"
        "<stem>_pg<page>_repeat1.md, matching benchmark.py's "
        "'^<pdf>_pg\\\\d+_repeat\\\\d+\\\\.md$' regex against the candidate-relative path.",
        "the evaluator's --dir must contain pdfs/, the rule .jsonl files and the "
        "candidate directory; stage_olmocr_bench_root() links the first two in from "
        "the ground-truth tree without writing to it.",
    )
    return PrepareResult(
        benchmark="olmocr",
        input_root=input_root,
        written=written,
        skipped=tuple(skipped),
        notes=notes,
        files_sha256=digests,
    )


def stage_olmocr_bench_root(input_root: Path, gt_bench_data: Path) -> dict[str, Any]:
    """Put ``pdfs/`` and the rule ``*.jsonl`` beside the candidate directory.

    ``benchmark.py`` reads the pdfs, the rules and the candidate folders from
    one directory. The ground-truth tree is read-only, so the campaign-owned
    input root is populated with hard links where the filesystem allows them
    and with copies where it does not. Nothing is written under
    ``benchmark/datasets``.
    """

    source_pdfs = gt_bench_data / "pdfs"
    if not jsonio.io_path(source_pdfs).is_dir():
        raise InputError(f"olmOCR ground truth has no pdfs/ directory at {source_pdfs}")
    linked = 0
    copied = 0
    for pdf in sorted(source_pdfs.rglob("*.pdf")):
        destination = input_root / "pdfs" / pdf.relative_to(source_pdfs)
        if jsonio.io_path(destination).exists():
            continue
        jsonio.io_path(destination).parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(jsonio.io_path(pdf), jsonio.io_path(destination))
            linked += 1
        except OSError:
            shutil.copy2(jsonio.io_path(pdf), jsonio.io_path(destination))
            copied += 1
    rules = 0
    for rule in sorted(gt_bench_data.glob("*.jsonl")):
        destination = input_root / rule.name
        jsonio.io_path(destination).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(jsonio.io_path(rule), jsonio.io_path(destination))
        rules += 1
    if rules == 0:
        raise InputError(f"olmOCR ground truth has no rule .jsonl files in {gt_bench_data}")
    return {"pdfs_linked": linked, "pdfs_copied": copied, "rule_files": rules}


# ---------------------------------------------------------------------------
# run commands and the watchdog
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvaluatorStep:
    name: str
    argv: tuple[str, ...]
    cwd: Path
    timeout_seconds: int
    #: Paths (absolute, or relative to ``cwd``) that must exist afterwards.
    expected_outputs: tuple[str, ...] = ()
    #: Globs relative to ``cwd`` copied into ``evaluator_raw/<name>/``.
    collect_globs: tuple[str, ...] = ()

    def to_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "argv": list(self.argv),
            "cwd": str(self.cwd),
            "timeout_seconds": self.timeout_seconds,
            "expected_outputs": list(self.expected_outputs),
            "collect_globs": list(self.collect_globs),
        }


def build_steps(
    lane: EvaluatorLane,
    *,
    input_root: Path,
    raw_root: Path,
    gt_path: Path,
    candidate: str,
    python_executable: str = "python",
    timeout_seconds: int | None = None,
    max_workers: int = 8,
) -> tuple[EvaluatorStep, ...]:
    """The exact commands that produce this benchmark's official numbers."""

    timeout = timeout_seconds or DEFAULT_STEP_TIMEOUT_SECONDS[lane.benchmark]
    if lane.benchmark == "parsebench":
        steps = []
        for group, product_type in PARSEBENCH_GROUPS:
            report_dir = raw_root / group
            steps.append(
                EvaluatorStep(
                    name=group,
                    argv=(
                        "uv",
                        "run",
                        "parse-bench",
                        "evaluation",
                        "run",
                        f"--output_dir={input_root}",
                        f"--test_cases_dir={gt_path}",
                        f"--product_type={product_type}",
                        f"--group={group}",
                        f"--report_dir={report_dir}",
                        "--export_csv=True",
                        "--export_rule_csv=False",
                        "--export_markdown=True",
                        "--export_html=True",
                        "--verbose=False",
                        "--force=True",
                        "--multi_task=True",
                        f"--max_workers={max_workers}",
                        "--enable_teds=True",
                        "--skip_rules=False",
                        "--ontology=canonical",
                        "--verified_only=False",
                    ),
                    cwd=lane.checkout_dir,
                    timeout_seconds=timeout,
                    expected_outputs=(str(report_dir / "_evaluation_report.json"),),
                )
            )
        return tuple(steps)

    if lane.benchmark == "omnidoc":
        config_path = raw_root / "omnidoc-config.yaml"
        prediction_dir = input_root / _OMNIDOC_PREDICTION_DIR
        return (
            EvaluatorStep(
                name="end2end",
                argv=(python_executable, "pdf_validation.py", "--config", str(config_path)),
                cwd=lane.checkout_dir,
                timeout_seconds=timeout,
                expected_outputs=(
                    str(
                        lane.checkout_dir
                        / "result"
                        / f"{prediction_dir.name}_quick_match_metric_result.json"
                    ),
                ),
                collect_globs=(f"result/{prediction_dir.name}_quick_match_*",),
            ),
        )

    driver = Path(__file__).resolve().parent / "drivers" / "olmocr_driver.py"
    return (
        EvaluatorStep(
            name="benchmark",
            argv=(
                python_executable,
                str(driver),
                "--evaluator-dir",
                str(lane.checkout_dir),
                "--bench-dir",
                str(input_root),
                "--candidate",
                candidate,
                "--out",
                str(raw_root / "benchmark" / "official-result.json"),
            ),
            cwd=lane.checkout_dir,
            timeout_seconds=timeout,
            expected_outputs=(str(raw_root / "benchmark" / "official-result.json"),),
        ),
    )


def omnidoc_config(
    *, gt_path: Path, prediction_dir: Path, workers: int = 4, deterministic_matching: bool = False
) -> str:
    """The OmniDocBench end2end config, field for field as the 2026-08 lane ran it."""

    def quoted(path: Path) -> str:
        return path.resolve().as_posix().replace("'", "''")

    return f"""end2end_eval:
  metrics:
    text_block:
      metric: [Edit_dist]
    display_formula:
      metric: [Edit_dist]
    table:
      metric: [TEDS, Edit_dist]
      teds_workers: {workers}
    reading_order:
      metric: [Edit_dist]
  dataset:
    dataset_name: end2end_dataset
    ground_truth:
      data_path: '{quoted(gt_path)}'
    prediction:
      data_path: '{quoted(prediction_dir)}'
    match_method: quick_match
    match_workers: {workers}
    deterministic_matching: {"true" if deterministic_matching else "false"}
    quick_match_truncated_timeout_sec: 60
    match_timeout_sec: 90
    timeout_fallback_max_chunk_span: 10
    timeout_fallback_order_penalty: 0.10
"""


def _tail(text: str) -> str:
    return text[-STDERR_TAIL_CHARS:]


def run_steps(
    steps: Sequence[EvaluatorStep],
    raw_root: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Run each step under a watchdog, capturing stdout, stderr and results.

    A non-zero exit, a timeout or an absent expected output raises
    :class:`EvaluatorBlockedError` with the tail of stderr. It never returns a
    partial score, and it never fabricates one.
    """

    records: list[dict[str, Any]] = []
    for step in steps:
        step_dir = raw_root / step.name
        jsonio.io_path(step_dir).mkdir(parents=True, exist_ok=True)
        try:
            completed = subprocess.run(
                list(step.argv),
                cwd=str(step.cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=step.timeout_seconds,
                check=False,
                env=dict(env) if env is not None else None,
            )
        except subprocess.TimeoutExpired as exc:
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            jsonio.write_text_atomic(step_dir / "stderr.log", stderr)
            raise EvaluatorBlockedError(
                f"step {step.name!r} exceeded its {step.timeout_seconds}s watchdog",
                stderr_tail=_tail(stderr),
                timed_out=True,
            ) from exc
        except OSError as exc:
            raise EvaluatorBlockedError(
                f"step {step.name!r} could not be launched: {exc}",
                stderr_tail=str(exc)[-STDERR_TAIL_CHARS:],
            ) from exc

        jsonio.write_text_atomic(step_dir / "stdout.log", completed.stdout or "")
        jsonio.write_text_atomic(step_dir / "stderr.log", completed.stderr or "")
        if completed.returncode != 0:
            raise EvaluatorBlockedError(
                f"step {step.name!r} exited {completed.returncode}",
                stderr_tail=_tail(completed.stderr or ""),
                returncode=completed.returncode,
            )

        collected = _collect(step, step_dir)
        missing = [
            target
            for target in step.expected_outputs
            if not jsonio.io_path(_resolve(step.cwd, target)).exists()
        ]
        if missing:
            raise EvaluatorBlockedError(
                f"step {step.name!r} exited 0 but produced none of {missing}",
                stderr_tail=_tail(completed.stderr or ""),
                returncode=completed.returncode,
            )
        records.append(
            {
                **step.to_record(),
                "returncode": completed.returncode,
                "collected": collected,
            }
        )
    return records


def _resolve(cwd: Path, target: str) -> Path:
    path = Path(target)
    return path if path.is_absolute() else cwd / path


def _collect(step: EvaluatorStep, step_dir: Path) -> list[str]:
    collected: list[str] = []
    for pattern in step.collect_globs:
        for source in sorted(step.cwd.glob(pattern)):
            if not jsonio.io_path(source).is_file():
                continue
            destination = step_dir / source.name
            shutil.copy2(jsonio.io_path(source), jsonio.io_path(destination))
            collected.append(source.name)
    return collected
