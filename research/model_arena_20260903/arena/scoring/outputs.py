"""Read a frozen output set - a model's, or a TAVONEL composite variant's.

Both shapes are reduced to the same :class:`OutputRow` so the QA gate, the
evaluator-input layouts and the provenance walk are written once. What differs
is recorded rather than smoothed over: a composite row names the model whose
output was chosen, and carries ``unresolved`` when the chosen model has no
frozen output for that page. An unresolved page is never given text.

Nothing here reads ground truth. The source manifest is the non-GT staged
index (masterplan section 2.1); its ``preflight`` block is a heuristic used to
separate a valid blank source from a failed empty extraction (section 41) and
is never used as a label.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from arena.constants import BENCHMARK_KEYS
from arena.scoring import jsonio
from arena.scoring.errors import InputError
from arena.scoring.paths import ScoringPaths

__all__ = [
    "OutputRow",
    "OutputSet",
    "SourceIndex",
    "SourceRow",
    "load_composite_output_set",
    "load_model_output_set",
    "load_output_set",
    "load_source_index",
]

OutputSetKind = Literal["model", "composite"]


@dataclass(frozen=True, slots=True)
class OutputRow:
    """One page of one output set, normalised across both shapes."""

    case_key: str
    sample_id: str
    benchmark: str
    status: str
    producing_model_key: str
    canonical_path: Path
    canonical_sha256: str | None
    raw_path: Path | None
    raw_sha256: str | None
    receipt_path: Path | None
    unresolved: bool
    unresolved_reason: str | None

    @property
    def has_output(self) -> bool:
        return not self.unresolved and self.status == "SUCCESS"


@dataclass(frozen=True, slots=True)
class OutputSet:
    """A frozen manifest plus the rows it points at."""

    key: str
    kind: OutputSetKind
    model_key: str | None
    variant: str | None
    manifest_path: Path
    manifest_sha256: str
    marker: Mapping[str, Any] | None
    rows: tuple[OutputRow, ...]

    def for_benchmark(self, benchmark: str) -> tuple[OutputRow, ...]:
        return tuple(row for row in self.rows if row.benchmark == benchmark)

    @property
    def benchmarks(self) -> tuple[str, ...]:
        seen = {row.benchmark for row in self.rows}
        return tuple(key for key in BENCHMARK_KEYS if key in seen)


@dataclass(frozen=True, slots=True)
class SourceRow:
    """One staged source page. Non-GT fields only (section 2.1)."""

    case_key: str
    sample_id: str
    benchmark: str
    source_relative_path: str
    source_sha256: str
    input_png_sha256: str
    media_type: str
    page_index: int
    is_probably_blank: bool | None


@dataclass(frozen=True, slots=True)
class SourceIndex:
    rows: Mapping[str, SourceRow]

    def by_benchmark(self, benchmark: str) -> tuple[SourceRow, ...]:
        return tuple(
            row for row in sorted(self.rows.values(), key=lambda r: r.case_key)
            if row.benchmark == benchmark
        )

    def get(self, case_key: str) -> SourceRow | None:
        return self.rows.get(case_key)

    def require(self, case_key: str) -> SourceRow:
        row = self.rows.get(case_key)
        if row is None:
            raise InputError(f"case_key {case_key!r} is absent from source_manifest.jsonl")
        return row


def _text(record: Mapping[str, Any], key: str, context: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise InputError(f"{context} is missing a non-empty {key!r}")
    return value


def _optional_text(record: Mapping[str, Any], key: str) -> str | None:
    value = record.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        return None
    return value


def load_source_index(paths: ScoringPaths) -> SourceIndex:
    """Read ``source_manifest.jsonl``. Its absence is an error, not a default."""

    path = paths.source_manifest
    if not jsonio.io_path(path).is_file():
        raise InputError(
            f"source_manifest.jsonl is absent at {path}; the QA gate cannot check "
            "sample coverage or source hashes without it"
        )
    rows: dict[str, SourceRow] = {}
    for record in jsonio.read_jsonl(path):
        case_key = _text(record, "case_key", "source_manifest row")
        if case_key in rows:
            raise InputError(f"source_manifest.jsonl repeats case_key {case_key!r}")
        preflight = record.get("preflight")
        blank: bool | None = None
        if isinstance(preflight, Mapping):
            flag = preflight.get("is_probably_blank")
            if isinstance(flag, bool):
                blank = flag
        page_index = record.get("page_index")
        rows[case_key] = SourceRow(
            case_key=case_key,
            sample_id=_text(record, "sample_id", f"source row {case_key}"),
            benchmark=_text(record, "benchmark", f"source row {case_key}"),
            source_relative_path=_text(
                record, "original_source_relative_path", f"source row {case_key}"
            ),
            source_sha256=_text(record, "original_source_sha256", f"source row {case_key}"),
            input_png_sha256=_text(record, "input_png_sha256", f"source row {case_key}"),
            media_type=_text(record, "media_type", f"source row {case_key}"),
            page_index=int(page_index) if isinstance(page_index, int) else 0,
            is_probably_blank=blank,
        )
    return SourceIndex(rows=rows)


def load_model_output_set(paths: ScoringPaths, model_key: str) -> OutputSet:
    """Read ``frozen_outputs/<model_key>/manifest.jsonl`` (contract 3.10)."""

    manifest_path = paths.frozen_manifest(model_key)
    if not jsonio.io_path(manifest_path).is_file():
        raise InputError(
            f"{model_key} has no frozen manifest at {manifest_path}; freeze the outputs "
            "before scoring (masterplan Phase 4)"
        )
    marker_path = paths.frozen_marker(model_key)
    marker: Mapping[str, Any] | None = None
    if jsonio.io_path(marker_path).is_file():
        loaded = jsonio.read_json(marker_path)
        if not isinstance(loaded, Mapping):
            raise InputError(f"{marker_path} is not a JSON object")
        marker = loaded

    rows: list[OutputRow] = []
    for record in jsonio.read_jsonl(manifest_path):
        case_key = _text(record, "case_key", "frozen manifest row")
        rows.append(
            OutputRow(
                case_key=case_key,
                sample_id=_text(record, "sample_id", f"frozen row {case_key}"),
                benchmark=_text(record, "benchmark", f"frozen row {case_key}"),
                status=_text(record, "status", f"frozen row {case_key}"),
                producing_model_key=model_key,
                canonical_path=paths.canonical_path(model_key, case_key),
                canonical_sha256=_optional_text(record, "canonical_sha256"),
                raw_path=paths.raw_path(model_key, case_key),
                raw_sha256=_optional_text(record, "raw_sha256"),
                receipt_path=paths.receipt_path(model_key, case_key),
                unresolved=False,
                unresolved_reason=None,
            )
        )
    return OutputSet(
        key=model_key,
        kind="model",
        model_key=model_key,
        variant=None,
        manifest_path=manifest_path,
        manifest_sha256=jsonio.sha256_file(manifest_path),
        marker=marker,
        rows=tuple(sorted(rows, key=lambda row: row.case_key)),
    )


def load_composite_output_set(paths: ScoringPaths, variant: str) -> OutputSet:
    """Read ``tavonel/adaptive_replay/<variant>/manifest.jsonl`` (contract 8)."""

    manifest_path = paths.composite_manifest(variant)
    if not jsonio.io_path(manifest_path).is_file():
        raise InputError(
            f"variant {variant!r} has no composite manifest at {manifest_path}; run the "
            "TAVONEL replay before scoring it"
        )
    rows: list[OutputRow] = []
    for record in jsonio.read_jsonl(manifest_path):
        case_key = _text(record, "case_key", "composite manifest row")
        unresolved = bool(record.get("unresolved"))
        chosen = record.get("chosen_model_key") or record.get("final_model")
        if not isinstance(chosen, str) or not chosen:
            raise InputError(f"composite row {case_key} names no chosen model")
        composite_path = paths.composite_canonical(variant, case_key)
        rows.append(
            OutputRow(
                case_key=case_key,
                sample_id=_text(record, "sample_id", f"composite row {case_key}"),
                benchmark=_text(record, "benchmark", f"composite row {case_key}"),
                status="FAILED" if unresolved else "SUCCESS",
                producing_model_key=chosen,
                canonical_path=composite_path,
                canonical_sha256=_optional_text(record, "composite_canonical_sha256"),
                raw_path=(
                    None
                    if record.get("chosen_raw_path") is None
                    else paths.root / str(record["chosen_raw_path"])
                ),
                raw_sha256=_optional_text(record, "chosen_raw_sha256"),
                receipt_path=paths.receipt_path(chosen, case_key),
                unresolved=unresolved,
                unresolved_reason=_optional_text(record, "unresolved_reason"),
            )
        )
    return OutputSet(
        key=variant,
        kind="composite",
        model_key=None,
        variant=variant,
        manifest_path=manifest_path,
        manifest_sha256=jsonio.sha256_file(manifest_path),
        marker=None,
        rows=tuple(sorted(rows, key=lambda row: row.case_key)),
    )


def load_output_set(
    paths: ScoringPaths, *, model: str | None = None, variant: str | None = None
) -> OutputSet:
    """Exactly one of ``model`` / ``variant`` selects the set to load."""

    if (model is None) == (variant is None):
        raise InputError("name exactly one of --model or --variant")
    if model is not None:
        return load_model_output_set(paths, model)
    if variant is None:  # pragma: no cover - the guard above already refused this
        raise InputError("name exactly one of --model or --variant")
    return load_composite_output_set(paths, variant)
