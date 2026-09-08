"""WP-R10 Phase B — the RUNTIME-VISIBLE half of the offline router replay.

Blueprint sections 38-39, program section 16. This module builds the features a
production router could actually have had, and the policies that consume them.

**It must never be able to open hidden evaluation truth.** That is enforced
structurally, not by convention:

  * every read goes through :func:`open_visible`, which resolves the path and
    refuses anything outside :data:`VISIBLE_ROOTS`;
  * ``scorer.py`` -- which opens the evaluator score files and OmniDocBench GT
    -- is never imported here, and a test asserts the import graph stays that
    way.

What is visible, and why each item is not truth about the answer:

  ``source_manifest.jsonl``      the corpus a runtime is handed, plus the
                                 render-time preflight statistics the campaign
                                 computed from the input raster itself
  ``frozen_outputs/<m>/…``       which model produced output for which unit
  ``runs/<m>/canonical/*``       the model outputs themselves
  ``runs/<m>/raw/*``             the same, pre-canonicalization
  ``runs/<m>/receipts/*``        the model's own execution telemetry
                                 (inference_ms, queue_ms, tokens, VRAM)
  ``cost/*``                     the GPU billing ledger
  the original source documents  what the customer uploaded

What is NOT visible here: ``reports/full_compare_20260905/*_raw/``, ``scores/``,
``OmniDocBench.json``, and the benchmark ``*.jsonl`` rule/GT files.

Diagnostic research code. Not a public benchmark result.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# Reconciler and the loss-weight freeze live in the Phase A lane; both are
# GT-blind by construction and are reused rather than reimplemented.
_ORACLE = Path(__file__).resolve().parents[1] / "router_oracle_20260908"
import sys  # noqa: E402

if str(_ORACLE) not in sys.path:
    sys.path.insert(0, str(_ORACLE))

from reconciler import (  # type: ignore[import-untyped]  # noqa: E402
    UNRESOLVED,
    normalize,
    select,
    similarity,
)

HERE = Path(__file__).resolve().parent

DEFAULT_ARENA_ROOT = Path(
    r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903"
)
DEFAULT_SOURCE_ROOT = Path(
    r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core"
)

# Where the original documents for each benchmark live, relative to SOURCE_ROOT.
# These are DIRECTORIES on purpose: the sibling `*.jsonl` rule files and
# `OmniDocBench.json` in the same dataset folders are hidden truth.
SOURCE_SUBROOTS = {
    "olmocr": "olmocr-bench/bench_data/pdfs",
    "omnidoc": "omnidocbench/images",
    "parsebench": "parsebench/docs",
}


class LeakageRefusal(RuntimeError):
    """A runtime-visible component tried to open a hidden-evaluation path."""


def arena_root() -> Path:
    return Path(os.environ.get("ARENA_ROOT", str(DEFAULT_ARENA_ROOT)))


def source_root() -> Path:
    return Path(os.environ.get("ARENA_SOURCE_ROOT", str(DEFAULT_SOURCE_ROOT)))


@lru_cache(maxsize=8)
def _roots(root: str, src: str) -> tuple[Path, ...]:
    root_path = Path(root).resolve()
    src_path = Path(src).resolve()
    return (
        root_path / "source_manifest.jsonl",
        root_path / "frozen_outputs",
        root_path / "runs",
        root_path / "cost",
        *(src_path / sub for sub in SOURCE_SUBROOTS.values()),
    )


def visible_roots() -> tuple[Path, ...]:
    """The complete allow-list. Anything not under one of these is refused.

    Cached on the two environment roots: `assert_visible` runs on every one of
    ~130,000 reads, and resolving six paths per read costs more than the reads.
    """
    return _roots(str(arena_root()), str(source_root()))


def assert_visible(path: Path) -> Path:
    """Resolve ``path`` and refuse it unless it is under an allow-listed root."""
    resolved = Path(path).resolve()
    for allowed in visible_roots():
        if resolved == allowed:
            return resolved
        if allowed in resolved.parents:
            return resolved
    raise LeakageRefusal(
        f"runtime-visible half refused a path outside the allow-list: {resolved}"
    )


def open_visible(path: Path, mode: str = "r") -> Any:
    """The only file handle this module hands out."""
    checked = assert_visible(path)
    if "b" in mode:
        return checked.open(mode)
    return checked.open(mode, encoding="utf-8", errors="replace")


def read_visible_text(path: Path) -> str:
    with open_visible(path) as handle:
        text: str = handle.read()
    return text


# ---------------------------------------------------------------------------
# frozen feature-construction constants (fixed BEFORE any scoring)
# ---------------------------------------------------------------------------

FEATURE_BUILDER_ID = "TAVONEL-ROUTER-REPLAY-FEATURES-2026-09-08-V1"

# Arena model keys bound to the production Route enum. Bound by identity, not by
# rank: `hpd_parsing` IS the HPD route's model, `paddleocr_vl_1_6` IS
# PaddleOCR-VL 1.6, `unlimited_ocr` IS Unlimited-OCR. Route.NATIVE has NO Arena
# arm -- the campaign never ran a native-parse arm -- and that absence is a
# result, not a gap to be filled with a substitute.
ROUTE_TO_ARENA_MODEL: dict[str, str | None] = {
    "native": None,
    "hpd_fast": "hpd_parsing",
    "paddle_fast": "paddleocr_vl_1_6",
    "paddle_vl": "paddleocr_vl_1_6",
    "unlimited_long": "unlimited_ocr",
    "mistral_fallback": None,
    "region_recovery": None,
    "authority_reconstruction": None,
    "unresolved": None,
    "quarantine": None,
}

# The production first-choice visual route's model. PRIMARY_ONLY is this arm.
PRIMARY_MODEL = "paddleocr_vl_1_6"

# The frozen peer used by every disagreement and critical-token signal. Chosen
# from the section 9 complementarity asymmetry recorded in Phase A
# (paddle wrong -> ovis rescues 30.8%), before any Phase B score was computed.
PEER_MODEL = "ovisocr2"

# The escalation target. Two are declared, and every escalating arm is run with
# each, because the external adjudicator's cost is UNMEASURED and the priced
# alternative is therefore reported beside it. Declared before scoring.
STRONG_MODELS = ("opus5_subscription", "unlimited_ocr")

# The blind quality predictor is only run for the models an arm can accept.
# Running it for all thirteen would cost an hour and answer nothing extra.
BLIND_RISK_MODELS = (PRIMARY_MODEL, PEER_MODEL, *STRONG_MODELS)

# Per-page latency receipts are read only for the models an arm can invoke.
# Every other model's latency comes from the campaign speed ledger's median and
# p90; its p95/p99 stay UNKNOWN rather than being interpolated.
LATENCY_MODELS = (PRIMARY_MODEL, PEER_MODEL, *STRONG_MODELS, "hpd_parsing")

# Cold-volume reads dominate this lane's runtime; see `_read_many`.
READ_THREADS = int(os.environ.get("REPLAY_READ_THREADS", "24"))

# Jaccard similarity at or above this is "agreement". 0.80 on markdown-stripped
# token sets. Fixed before scoring; never tuned against a score.
AGREEMENT_TAU = 0.80

# aggregate_evidence_risk above this is "predicted bad" for PREDICTION_ONLY.
PREDICTION_TAU = 0.50

# A critical-token report with at least this total risk is "L2 flagged".
CRITICAL_TOKEN_TAU = 0.90

_WORD = re.compile(r"\w+", re.UNICODE)
_REPLACEMENT_CHARS = re.compile(r"[\ufffd]")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# feature records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutputFeatures:
    """What a runtime can see about one model's output for one unit."""

    model: str
    status: str
    present: bool
    chars: int
    words: int
    lines: int
    table_rows: int
    replacement_ratio: float
    control_ratio: float
    inference_ms: float | None
    queue_ms: float | None
    load_ms: float | None
    peak_vram_mb: float | None


@dataclass(frozen=True, slots=True)
class UnitFeatures:
    """Everything the replay's runtime half knows about one unit."""

    case_key: str
    benchmark: str
    unit_key: str
    media_type: str
    input_bytes: int
    width: int
    height: int
    page_index: int
    render_edge_density: float | None
    render_mean_intensity: float | None
    render_near_white_ratio: float | None
    render_entropy: float | None
    render_probably_blank: bool | None
    native_text_chars: int
    native_word_count: int
    native_invalid_unicode_ratio: float
    native_replacement_ratio: float
    native_text_available: bool
    outputs: Mapping[str, OutputFeatures]
    similarity: Mapping[str, float]  # "a|b" (a<b lexicographically) -> Jaccard
    reconciler_choice: str
    critical_token_risk: float  # primary vs peer, GT-blind L2 detector
    critical_token_kinds: tuple[str, ...]
    blind_risk: dict[str, float]  # model -> aggregate_evidence_risk of its output
    unknown_fields: tuple[str, ...]

    def sim(self, left: str, right: str) -> float | None:
        key = "|".join(sorted((left, right)))
        return self.similarity.get(key)


# ---------------------------------------------------------------------------
# loaders (allow-listed)
# ---------------------------------------------------------------------------


def _unit_key(benchmark: str, original_source_relative_path: str) -> str:
    """Map a manifest row to the key the benchmark's score files use.

    Identical to ``reconciler._unit_key``; restated here so the runtime half
    does not depend on a private name.
    """
    path = original_source_relative_path
    if benchmark == "omnidoc":
        return path.rsplit("/", 1)[-1]
    if benchmark == "olmocr":
        return path.removeprefix("bench_data/pdfs/")
    if benchmark == "parsebench":
        return path.removeprefix("docs/").removesuffix(".pdf")
    raise ValueError(f"unknown benchmark {benchmark}")


def load_manifest(root: Path, benchmark: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open_visible(root / "source_manifest.jsonl") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if benchmark is None or row.get("benchmark") == benchmark:
                rows.append(row)
    return rows


def load_frozen_status(root: Path, model: str, benchmark: str) -> dict[str, dict[str, str]]:
    """case_key -> {status, canonical_path} for one model and benchmark."""
    manifest = root / "frozen_outputs" / model / "manifest.jsonl"
    out: dict[str, dict[str, str]] = {}
    if not manifest.is_file():
        return out
    with open_visible(manifest) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("benchmark") != benchmark:
                continue
            out[str(row["case_key"])] = {
                "status": str(row.get("status") or "UNKNOWN"),
                "canonical_path": str(row.get("canonical_path") or ""),
            }
    return out


def _read_many(paths: Sequence[tuple[Any, Path]]) -> list[tuple[Any, str | None]]:
    """Read many small files at once.

    ponytail: a thread pool, because this corpus lives on a cold volume where a
    single small read costs ~110 ms of scanning overhead and almost no CPU.
    Serial, the 67,000 canonical outputs take two hours; the work is I/O wait,
    so threads are the whole fix. Upgrade path if it ever becomes CPU-bound:
    a process pool, or a packed cache built once.
    """

    def one(item: tuple[Any, Path]) -> tuple[Any, str | None]:
        key, path = item
        try:
            return key, read_visible_text(path)
        except OSError:
            return key, None

    with ThreadPoolExecutor(max_workers=READ_THREADS) as pool:
        return list(pool.map(one, paths))


def load_receipts(
    root: Path, model: str, case_keys: Sequence[str], cache_dir: Path
) -> dict[str, dict[str, float]]:
    """Per-page execution telemetry, cached because it is 5,132 small files.

    Paths come from the frozen manifest's case keys, never from a directory
    scan: enumerating a 5,132-entry directory on this volume costs as much as
    reading it.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"receipts_{model}.json"
    if cache.is_file():
        cached: dict[str, dict[str, float]] = json.loads(cache.read_text(encoding="utf-8"))
        return cached
    directory = root / "runs" / model / "receipts"
    out: dict[str, dict[str, float]] = {}
    for case_key, text in _read_many(
        [(key, directory / f"{key}.json") for key in case_keys]
    ):
        if text is None:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        out[str(case_key)] = {
            key: float(payload[key])
            for key in ("inference_ms", "queue_ms", "load_ms", "peak_vram_mb")
            if isinstance(payload.get(key), (int, float))
        }
    cache.write_text(
        json.dumps(out, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    return out


def load_cost(root: Path) -> dict[str, Any]:
    """Campaign totals plus per-model provider cost, straight from the ledger."""
    campaign = json.loads(read_visible_text(root / "cost" / "campaign-cost.json"))
    per_model: dict[str, dict[str, float]] = {}
    unterminated: dict[str, int] = {}
    for path in sorted((root / "cost").glob("pod-*.json")):
        pod = json.loads(read_visible_text(path))
        key = pod.get("model_key")
        if not key:
            continue
        row = per_model.setdefault(str(key), {"billed_seconds": 0.0, "provider_cost_usd": 0.0})
        row["billed_seconds"] += float(pod.get("billed_seconds") or 0.0)
        row["provider_cost_usd"] += float(pod.get("estimated_provider_cost_usd") or 0.0)
        row["pod_count"] = row.get("pod_count", 0.0) + 1.0
        if pod.get("deleted_at") is None and pod.get("last_job_finished_at") is None:
            unterminated[str(key)] = unterminated.get(str(key), 0) + 1
    for key, row in per_model.items():
        marker = root / "frozen_outputs" / key / "FROZEN.json"
        pages = float(campaign.get("successful_pages") or 0)
        if marker.is_file():
            pages = float(json.loads(read_visible_text(marker)).get("success_count") or pages)
        row["pages_basis"] = pages
        row["cost_per_1000_pages_usd"] = (
            row["provider_cost_usd"] / pages * 1000.0 if pages else 0.0
        )
        row["unterminated_pods_still_billing"] = float(unterminated.get(key, 0))
    return {"campaign_totals": campaign, "per_model": per_model}


# ---------------------------------------------------------------------------
# native inspection of the original source document
# ---------------------------------------------------------------------------


def native_text(root: Path, benchmark: str, relative: str, page_index: int) -> str | None:
    """Extract the PDF text layer. Returns None when there is no text layer.

    pypdf, deliberately not PyMuPDF (blueprint section 78). An image input has
    no text layer at all and returns None -- which is a measurement, not a zero.
    """
    sub = SOURCE_SUBROOTS.get(benchmark)
    if sub is None:
        return None
    prefix = {"olmocr": "bench_data/pdfs/", "omnidoc": "images/", "parsebench": "docs/"}[
        benchmark
    ]
    path = source_root() / sub / relative.removeprefix(prefix)
    if path.suffix.casefold() != ".pdf" or not path.is_file():
        return None
    assert_visible(path)
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        page = reader.pages[page_index] if page_index < len(reader.pages) else reader.pages[0]
        return str(page.extract_text() or "")
    except Exception:  # a broken PDF is data, not a crash
        return None


# ---------------------------------------------------------------------------
# per-unit feature construction
# ---------------------------------------------------------------------------


def _text_features(
    model: str, status: str, text: str | None, telemetry: dict[str, float]
) -> OutputFeatures:
    body = text or ""
    chars = len(body)
    return OutputFeatures(
        model=model,
        status=status,
        present=text is not None and status == "SUCCESS",
        chars=chars,
        words=len(_WORD.findall(body)),
        lines=body.count("\n") + (1 if body else 0),
        table_rows=len(_TABLE_ROW.findall(body)),
        replacement_ratio=(len(_REPLACEMENT_CHARS.findall(body)) / chars) if chars else 0.0,
        control_ratio=(len(_CONTROL_CHARS.findall(body)) / chars) if chars else 0.0,
        inference_ms=telemetry.get("inference_ms"),
        queue_ms=telemetry.get("queue_ms"),
        load_ms=telemetry.get("load_ms"),
        peak_vram_mb=telemetry.get("peak_vram_mb"),
    )


def _blind_risk(text: str, blank_probability: float | None) -> float:
    """GT-blind quality risk from the repo's own detectors. No ground truth."""
    from akc_cir.inspection import (
        aggregate_evidence_risk,
        detect_duplication,
        detect_garble,
    )
    from akc_cir.inspection import detect_completeness as _completeness

    signals = []
    signal, _unknown = _completeness(
        output_chars=len(text), blank_probability=blank_probability
    )
    if signal is not None:
        signals.append(signal)
    for detector in (detect_duplication(text), detect_garble(text)):
        if detector is not None:
            signals.append(detector)
    return float(aggregate_evidence_risk(signals)) if signals else 0.0


def build_units(
    root: Path,
    benchmark: str,
    models: Sequence[str],
    cache_dir: Path,
    *,
    with_native: bool = True,
) -> tuple[list[UnitFeatures], dict[tuple[str, str], str]]:
    """Build one benchmark's runtime-visible features and its output index.

    Returns the units and ``{(model, unit_key): canonical text}``. The texts come
    back because the scorer needs the accepted output for SCLR, and reading the
    same 67,000 files twice would double the only expensive part of this lane.
    """
    from akc_cir.critical_tokens import verify_critical_tokens

    cache_dir.mkdir(parents=True, exist_ok=True)
    rows = load_manifest(root, benchmark)
    case_keys = [str(row["case_key"]) for row in rows]
    frozen = {model: load_frozen_status(root, model, benchmark) for model in models}
    telemetry = {
        model: (
            load_receipts(root, model, case_keys, cache_dir)
            if model in LATENCY_MODELS
            else {}
        )
        for model in models
    }

    wanted: list[tuple[tuple[str, str], Path]] = []
    for model in models:
        for key, row_entry in frozen[model].items():
            if row_entry["status"] == "SUCCESS" and row_entry["canonical_path"]:
                wanted.append(((model, key), root / row_entry["canonical_path"]))
    canonical: dict[tuple[str, str], str] = {
        key: text for key, text in _read_many(wanted) if text is not None
    }

    natives: dict[str, str | None] = {}
    if with_native:
        natives = dict(
            _read_many_native(
                root,
                benchmark,
                [
                    (
                        str(row["case_key"]),
                        str(row.get("original_source_relative_path") or ""),
                        int(row.get("page_index") or 0),
                    )
                    for row in rows
                ],
            )
        )

    units: list[UnitFeatures] = []
    text_index: dict[tuple[str, str], str] = {}
    for row in rows:
        case_key = str(row["case_key"])
        source_rel = str(row.get("original_source_relative_path") or "")
        preflight = row.get("preflight") or {}
        unit_key = _unit_key(benchmark, source_rel)
        texts: dict[str, str] = {}
        outputs: dict[str, OutputFeatures] = {}
        for model in models:
            entry = frozen[model].get(case_key)
            status = entry["status"] if entry else "MISSING"
            text = canonical.get((model, case_key))
            if text is not None:
                texts[model] = text
                text_index[(model, unit_key)] = text
            outputs[model] = _text_features(
                model, status, text, telemetry[model].get(case_key, {})
            )

        sets = {model: normalize(text) for model, text in texts.items()}
        sims: dict[str, float] = {}
        keys = sorted(sets)
        for i, left in enumerate(keys):
            for right in keys[i + 1 :]:
                sims[f"{left}|{right}"] = similarity(sets[left], sets[right])
        choice = select(sets) if sets else UNRESOLVED

        primary_text = texts.get(PRIMARY_MODEL)
        peer_text = texts.get(PEER_MODEL)
        risk = 0.0
        kinds: tuple[str, ...] = ()
        if primary_text is not None and peer_text is not None:
            report = verify_critical_tokens(peer_text, primary_text)
            risk = float(max((m.risk for m in report.mismatches), default=0.0))
            kinds = tuple(sorted({str(m.kind) for m in report.mismatches}))

        blank_probability = preflight.get("near_white_ratio")
        blind = {
            model: _blind_risk(
                texts[model],
                float(blank_probability) if blank_probability is not None else None,
            )
            for model in BLIND_RISK_MODELS
            if model in texts
        }

        native = natives.get(case_key)
        native_body = native or ""
        native_chars = len(native_body)
        units.append(
            UnitFeatures(
                case_key=case_key,
                benchmark=benchmark,
                unit_key=unit_key,
                media_type=str(row.get("media_type") or "unknown"),
                input_bytes=int(row.get("bytes") or 0),
                width=int(row.get("width") or 1),
                height=int(row.get("height") or 1),
                page_index=int(row.get("page_index") or 0),
                render_edge_density=_maybe_float(preflight.get("edge_density")),
                render_mean_intensity=_maybe_float(preflight.get("mean_intensity")),
                render_near_white_ratio=_maybe_float(preflight.get("near_white_ratio")),
                render_entropy=_maybe_float(preflight.get("render_entropy")),
                render_probably_blank=(
                    bool(preflight["is_probably_blank"])
                    if "is_probably_blank" in preflight
                    else None
                ),
                native_text_chars=native_chars,
                native_word_count=len(_WORD.findall(native_body)),
                native_invalid_unicode_ratio=(
                    len(_CONTROL_CHARS.findall(native_body)) / native_chars
                    if native_chars
                    else 0.0
                ),
                native_replacement_ratio=(
                    len(_REPLACEMENT_CHARS.findall(native_body)) / native_chars
                    if native_chars
                    else 0.0
                ),
                native_text_available=native is not None,
                outputs=outputs,
                similarity=sims,
                reconciler_choice=choice,
                critical_token_risk=risk,
                critical_token_kinds=kinds,
                blind_risk=blind,
                unknown_fields=UNKNOWN_PAGE_METRIC_FIELDS,
            )
        )
    return units, text_index


def _read_many_native(
    root: Path, benchmark: str, rows: Sequence[tuple[str, str, int]]
) -> list[tuple[str, str | None]]:
    """Extract the PDF text layer for a whole benchmark, in parallel."""

    def one(row: tuple[str, str, int]) -> tuple[str, str | None]:
        case_key, relative, page_index = row
        return case_key, native_text(root, benchmark, relative, page_index)

    with ThreadPoolExecutor(max_workers=READ_THREADS) as pool:
        return list(pool.map(one, rows))


def _maybe_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


CACHE_SCHEMA = "tavonel.router_replay.unit_features.v1"


def _to_dict(unit: UnitFeatures) -> dict[str, Any]:
    payload = {
        key: getattr(unit, key)
        for key in UnitFeatures.__slots__
        if key not in {"outputs", "similarity", "critical_token_kinds", "unknown_fields"}
    }
    payload["outputs"] = {
        model: {k: getattr(out, k) for k in OutputFeatures.__slots__}
        for model, out in unit.outputs.items()
    }
    payload["similarity"] = dict(unit.similarity)
    payload["critical_token_kinds"] = list(unit.critical_token_kinds)
    return payload


def _from_dict(payload: dict[str, Any]) -> UnitFeatures:
    outputs = {
        model: OutputFeatures(**row) for model, row in (payload.pop("outputs") or {}).items()
    }
    payload["critical_token_kinds"] = tuple(payload.get("critical_token_kinds") or ())
    return UnitFeatures(
        outputs=outputs, unknown_fields=UNKNOWN_PAGE_METRIC_FIELDS, **payload
    )


def load_or_build_units(
    root: Path, benchmark: str, models: Sequence[str], cache_dir: Path
) -> tuple[list[UnitFeatures], dict[tuple[str, str], str]]:
    """Build once, then read the cache.

    The build is ~67k cold small-file reads and is the whole cost of this lane,
    so both halves of its result are cached: the features as JSON, and the
    canonical outputs as one zstd blob rather than 67,000 files again.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"units_{benchmark}.json"
    texts_cache = cache_dir / f"texts_{benchmark}.jsonl.zst"
    if cache.is_file() and texts_cache.is_file():
        payload = json.loads(cache.read_text(encoding="utf-8"))
        if payload.get("schema") == CACHE_SCHEMA and payload.get("models") == sorted(models):
            return [_from_dict(row) for row in payload["units"]], _read_text_cache(
                texts_cache
            )
    units, texts = build_units(root, benchmark, models, cache_dir)
    cache.write_text(
        json.dumps(
            {
                "schema": CACHE_SCHEMA,
                "feature_builder_id": FEATURE_BUILDER_ID,
                "benchmark": benchmark,
                "models": sorted(models),
                "units": [_to_dict(unit) for unit in units],
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    _write_text_cache(texts_cache, texts)
    return units, texts


def _write_text_cache(path: Path, texts: Mapping[tuple[str, str], str]) -> None:
    import zstandard

    payload = "\n".join(
        json.dumps([model, unit, text], ensure_ascii=False)
        for (model, unit), text in texts.items()
    )
    path.write_bytes(zstandard.ZstdCompressor(level=6).compress(payload.encode("utf-8")))


def _read_text_cache(path: Path) -> dict[tuple[str, str], str]:
    import zstandard

    raw = zstandard.ZstdDecompressor().decompress(
        path.read_bytes(), max_output_size=2_000_000_000
    )
    out: dict[tuple[str, str], str] = {}
    for line in raw.decode("utf-8").splitlines():
        if line:
            model, unit, text = json.loads(line)
            out[(model, unit)] = text
    return out


# ---------------------------------------------------------------------------
# PageMetrics for the current Core deterministic router
# ---------------------------------------------------------------------------

# Fields `PageMetrics` types as a non-optional Ratio that this corpus cannot
# measure. They are set to 0.0 and DECLARED, never to the CPU worker's 0.5
# sentinel -- which would classify every unit HANDWRITTEN and make HPD_FAST
# unreachable (matrix C-09 / R11-04). The `worker_sentinels` variant reproduces
# that defect on purpose, to size it.
UNKNOWN_PAGE_METRIC_FIELDS = (
    "image_coverage",
    "native_block_count",
    "whitespace_anomaly_score",
    "estimated_columns",
    "table_density",
    "formula_density",
    "chart_probability",
    "handwriting_probability",
    "rotation_degrees",
    "skew_degrees",
    "blur_score",
    "contrast_score",
    "small_text_score",
)


def page_metrics(
    unit: UnitFeatures,
    *,
    reading_order_assumption: float,
    worker_sentinels: bool = False,
) -> Any:
    """Build the production `PageMetrics` from runtime-visible evidence only.

    ``reading_order_assumption`` is the unmeasurable
    ``native_reading_order_score``. It is swept from 0.0 to 1.0 rather than
    guessed, and both ends are reported: the band is the honest answer.
    """
    from akc_router.preflight import PageMetrics

    sentinel = 0.5 if worker_sentinels else 0.0
    near_white = unit.render_near_white_ratio
    ink = min(1.0, max(0.0, 1.0 - near_white)) if near_white is not None else 0.0
    return PageMetrics(
        page_index0=unit.page_index,
        width=max(1, unit.width),
        height=max(1, unit.height),
        native_text_chars=unit.native_text_chars,
        native_word_count=unit.native_word_count,
        native_block_count=0,
        native_text_coverage=ink,
        image_coverage=1.0 if unit.media_type == "image" else 0.0,
        invalid_unicode_ratio=min(1.0, unit.native_invalid_unicode_ratio),
        replacement_char_ratio=min(1.0, unit.native_replacement_ratio),
        whitespace_anomaly_score=0.0,
        native_reading_order_score=reading_order_assumption,
        estimated_columns=0,
        table_density=0.0,
        formula_density=0.0,
        chart_probability=0.0,
        handwriting_probability=sentinel,
        rotation_degrees=0,
        skew_degrees=0.0,
        blur_score=sentinel,
        contrast_score=sentinel,
        small_text_score=sentinel,
        script_distribution={},
        suspected_prompt_injection=False,
    )


# ---------------------------------------------------------------------------
# the Policy protocol and the arms that need no planner
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnitPlan:
    """One arm's decision for one unit.

    ``routes`` are the models actually invoked (they are what gets paid for and
    what sets latency). ``accepted`` is the single model whose output the arm
    hands downstream, or ``None`` for UNRESOLVED. ``escalate`` records that the
    arm chose to spend more than its primary because it suspected a loss.
    """

    routes: tuple[str, ...]
    accepted: str | None
    speculative: tuple[str, ...] = ()
    escalate: bool = False
    unresolved_reason: str | None = None
    reason_codes: tuple[str, ...] = ()


@runtime_checkable
class Policy(Protocol):
    """Anything that turns runtime-visible features into a plan.

    Lane A1's `akc_router.planner` plugs in here through
    :func:`planner_adapter` without this module importing it.
    """

    name: str

    def plan(self, unit_features: UnitFeatures) -> UnitPlan: ...


@dataclass(frozen=True)
class FixedModel:
    """SINGLE:<model>, PRIMARY_ONLY and ALWAYS_STRONG are all this arm."""

    model: str
    name: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            object.__setattr__(self, "name", f"SINGLE:{self.model}")

    def plan(self, unit_features: UnitFeatures) -> UnitPlan:
        out = unit_features.outputs.get(self.model)
        if out is None or not out.present:
            return UnitPlan(
                routes=(self.model,),
                accepted=None,
                unresolved_reason="model produced no output for this unit",
            )
        return UnitPlan(routes=(self.model,), accepted=self.model)


@dataclass(frozen=True)
class AlwaysAllReconciled:
    """Run every permitted model, keep FROZEN_RECONCILER_V1's medoid."""

    models: tuple[str, ...]
    name: str = "ALWAYS_ALL_RECONCILED"

    def plan(self, unit_features: UnitFeatures) -> UnitPlan:
        choice = unit_features.reconciler_choice
        if choice == UNRESOLVED or choice not in unit_features.outputs:
            return UnitPlan(
                routes=self.models,
                accepted=None,
                unresolved_reason="no candidate output for the frozen reconciler",
            )
        return UnitPlan(routes=self.models, accepted=choice, escalate=True)


@dataclass(frozen=True)
class Escalating:
    """Primary, plus a strong model when a GT-blind trigger fires.

    ``trigger`` selects which signal is consulted. Every threshold is frozen in
    this module's constants before any score is read.
    """

    trigger: str  # "prediction" | "disagreement" | "critical_token" | "never"
    strong: str
    primary: str = PRIMARY_MODEL
    peer: str = PEER_MODEL
    name: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            object.__setattr__(self, "name", f"{self.trigger.upper()}_ONLY@{self.strong}")

    def _fires(self, unit: UnitFeatures) -> bool:
        if self.trigger == "never":
            return False
        if self.trigger == "prediction":
            return unit.blind_risk.get(self.primary, 1.0) >= PREDICTION_TAU
        if self.trigger == "disagreement":
            sim = unit.sim(self.primary, self.peer)
            return sim is None or sim < AGREEMENT_TAU
        if self.trigger == "critical_token":
            return unit.critical_token_risk >= CRITICAL_TOKEN_TAU
        raise ValueError(f"unknown trigger {self.trigger}")

    def plan(self, unit_features: UnitFeatures) -> UnitPlan:
        routes: list[str] = [self.primary]
        if self.trigger == "disagreement" or self.trigger == "critical_token":
            routes.append(self.peer)
        escalate = self._fires(unit_features)
        chosen = self.primary
        if escalate:
            routes.append(self.strong)
            strong_out = unit_features.outputs.get(self.strong)
            if strong_out is not None and strong_out.present:
                chosen = self.strong
        out = unit_features.outputs.get(chosen)
        if out is None or not out.present:
            return UnitPlan(
                routes=tuple(routes),
                accepted=None,
                escalate=escalate,
                unresolved_reason="accepted model produced no output",
            )
        return UnitPlan(routes=tuple(routes), accepted=chosen, escalate=escalate)


@dataclass(frozen=True)
class CoreRouter:
    """The current production `akc_router.engine.select_first_route`, replayed.

    The Arena has no native-parse arm, so a unit this router sends to
    `Route.NATIVE` is UNRESOLVED here -- recorded and counted, never
    substituted with another model's output.
    """

    mode: str = "balanced"
    reading_order_assumption: float = 1.0
    worker_sentinels: bool = False
    name: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            tag = "sentinels" if self.worker_sentinels else f"ro={self.reading_order_assumption:g}"
            object.__setattr__(self, "name", f"CORE_ROUTER@{self.mode},{tag}")

    def plan(self, unit_features: UnitFeatures) -> UnitPlan:
        from akc_router.engine import select_first_route
        from akc_router.models import FeatureFlags, ProcessingMode, Route, RouterContext

        context = RouterContext(
            mode=ProcessingMode(self.mode),
            dominant_language="en",
            feature_flags=FeatureFlags(
                hpd_enabled=True, paddle_fast_enabled=True, unlimited_long_enabled=True
            ),
            ready_routes=frozenset(
                {Route.NATIVE, Route.HPD_FAST, Route.PADDLE_FAST, Route.PADDLE_VL}
            ),
        )
        decision = select_first_route(context, page_metrics(
            unit_features,
            reading_order_assumption=self.reading_order_assumption,
            worker_sentinels=self.worker_sentinels,
        ))
        model = ROUTE_TO_ARENA_MODEL.get(str(decision.route.value))
        if model is None:
            return UnitPlan(
                routes=(),
                accepted=None,
                unresolved_reason=f"route {decision.route.value} has no Arena arm",
                reason_codes=decision.reason_codes,
            )
        out = unit_features.outputs.get(model)
        if out is None or not out.present:
            return UnitPlan(
                routes=(model,),
                accepted=None,
                unresolved_reason="routed model produced no output",
                reason_codes=decision.reason_codes,
            )
        return UnitPlan(
            routes=(model,), accepted=model, reason_codes=decision.reason_codes
        )


@dataclass(frozen=True)
class ReplayComposite:
    """REPLAY_COMPOSITE_V1 — the arm the section 18 ablations switch off.

    Frozen before scoring. Primary and the cheap peer run on every unit. The
    strong arm is invoked when any enabled trigger fires. The cost leg is the
    section 42 expected-verified-cost idea in its smallest honest form: do not
    pay for the strong arm when the ONLY thing that fired was the blind
    predictor and the cheap peer already corroborates the primary. The
    reconciler leg decides what to accept out of the escalated candidate set.
    """

    strong: str
    use_disagreement: bool = True
    use_critical_token: bool = True
    use_prediction: bool = True
    use_reconciler: bool = True
    use_cost_objective: bool = True
    name: str = "REPLAY_COMPOSITE_V1"

    def plan(self, unit_features: UnitFeatures) -> UnitPlan:
        primary, peer = PRIMARY_MODEL, PEER_MODEL
        routes: list[str] = [primary, peer]
        blind = unit_features.blind_risk.get(primary, 1.0)
        sim = unit_features.sim(primary, peer)
        corroborated = sim is not None and sim >= AGREEMENT_TAU
        disagreed = self.use_disagreement and not corroborated
        critical = (
            self.use_critical_token
            and unit_features.critical_token_risk >= CRITICAL_TOKEN_TAU
        )
        predicted = self.use_prediction and blind >= PREDICTION_TAU
        escalate = disagreed or critical or predicted
        if (
            self.use_cost_objective
            and escalate
            and predicted
            and not (disagreed or critical)
            and corroborated
        ):
            escalate = False
        chosen = primary
        if escalate:
            routes.append(self.strong)
            if self.use_reconciler:
                chosen = _medoid_of(unit_features, (primary, peer, self.strong)) or primary
            elif _present(unit_features, self.strong):
                chosen = self.strong
        if not _present(unit_features, chosen):
            return UnitPlan(
                routes=tuple(routes),
                accepted=None,
                escalate=escalate,
                unresolved_reason="accepted model produced no output",
            )
        return UnitPlan(routes=tuple(routes), accepted=chosen, escalate=escalate)


def _present(unit: UnitFeatures, model: str) -> bool:
    out = unit.outputs.get(model)
    return out is not None and out.present


def _medoid_of(unit: UnitFeatures, candidates: Sequence[str]) -> str | None:
    """FROZEN_RECONCILER_V1's rule restricted to an escalated candidate set.

    Uses the pairwise Jaccard the feature builder already computed, so it is the
    same similarity the frozen reconciler uses -- not a second definition.
    """
    present = sorted(m for m in candidates if _present(unit, m))
    if not present:
        return None
    if len(present) == 1:
        return present[0]
    best, best_score = None, float("-inf")
    for model in present:
        others = [unit.sim(model, other) or 0.0 for other in present if other != model]
        score = sum(others) / len(others)
        if score > best_score:
            best, best_score = model, score
    return best


def planner_adapter(strong: str = STRONG_MODELS[0]) -> Policy | None:
    """Lane A1's `akc_router.planner`, if it exists yet. Never a hard dependency."""
    try:
        from akc_router import planner as _planner  # type: ignore[attr-defined]
    except ImportError:
        return None
    factory = getattr(_planner, "build_replay_policy", None)
    if factory is None:
        return None
    policy: Policy = factory(strong=strong)
    return policy


def frozen_policy_parameters() -> dict[str, Any]:
    """Everything a reader needs to reproduce the arms, and nothing tuned."""
    return {
        "feature_builder_id": FEATURE_BUILDER_ID,
        "primary_model": PRIMARY_MODEL,
        "peer_model": PEER_MODEL,
        "strong_models": list(STRONG_MODELS),
        "agreement_tau": AGREEMENT_TAU,
        "prediction_tau": PREDICTION_TAU,
        "critical_token_tau": CRITICAL_TOKEN_TAU,
        "route_to_arena_model": dict(ROUTE_TO_ARENA_MODEL),
        "unknown_page_metric_fields": list(UNKNOWN_PAGE_METRIC_FIELDS),
        "visible_roots_relative": [
            "source_manifest.jsonl",
            "frozen_outputs/",
            "runs/",
            "cost/",
            *[f"<source_root>/{sub}" for sub in SOURCE_SUBROOTS.values()],
        ],
        "notes": [
            "Every threshold above was written down before any score file was "
            "opened. None was moved after a result was seen.",
            "Route.NATIVE has no Arena arm; units routed there are UNRESOLVED, "
            "never substituted.",
            "native_reading_order_score is unmeasurable on this corpus and is "
            "swept over its whole range instead of guessed.",
        ],
    }


__all__ = [
    "AGREEMENT_TAU",
    "CRITICAL_TOKEN_TAU",
    "FEATURE_BUILDER_ID",
    "PEER_MODEL",
    "PREDICTION_TAU",
    "PRIMARY_MODEL",
    "ROUTE_TO_ARENA_MODEL",
    "STRONG_MODELS",
    "AlwaysAllReconciled",
    "CoreRouter",
    "Escalating",
    "FixedModel",
    "LeakageRefusal",
    "OutputFeatures",
    "Policy",
    "ReplayComposite",
    "UnitFeatures",
    "UnitPlan",
    "arena_root",
    "assert_visible",
    "build_units",
    "frozen_policy_parameters",
    "load_cost",
    "open_visible",
    "page_metrics",
    "planner_adapter",
    "source_root",
    "visible_roots",
]
