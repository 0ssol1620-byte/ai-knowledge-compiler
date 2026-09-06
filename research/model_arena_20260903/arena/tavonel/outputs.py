"""Where each model's frozen output for a case actually lives.

Preference order, recorded per reference in ``source`` rather than applied
silently:

1. ``frozen_outputs/<model_key>/manifest.jsonl`` — the sealed manifest lane B1
   writes at Phase 4, carrying the hash each file had when it was frozen.
2. ``runs/<model_key>/canonical/`` — the run tree, used only when a model has
   no frozen manifest yet (during a partial campaign).

A manifest row that claims a SUCCESS output which is not on disk is an
integrity violation and stops the command; it is never quietly skipped.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.tavonel import guards
from arena.tavonel.errors import MissingInputError
from arena.tavonel.paths import ArenaPaths

SOURCE_FROZEN_MANIFEST = "frozen_manifest"
SOURCE_RUNS_TREE = "runs_tree"


@dataclass(frozen=True, slots=True)
class OutputRef:
    """One model's frozen output for one case."""

    model_key: str
    case_key: str
    canonical_path: Path
    canonical_sha256: str | None
    raw_path: Path | None
    raw_sha256: str | None
    status: str | None
    sample_id: str | None
    benchmark: str | None
    source: str


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _resolve(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value)
    return candidate if candidate.is_absolute() else root / candidate


def _from_manifest(paths: ArenaPaths, model_key: str) -> dict[str, OutputRef]:
    refs: dict[str, OutputRef] = {}
    manifest = paths.frozen_manifest(model_key)
    for row in guards.iter_jsonl_guarded(manifest, what=f"frozen manifest for {model_key}"):
        case_key = row.get("case_key")
        if not isinstance(case_key, str):
            continue
        status = row.get("status") if isinstance(row.get("status"), str) else None
        canonical = _resolve(paths.root, row.get("canonical_path")) or paths.canonical_path(
            model_key, case_key
        )
        if not canonical.is_file():
            if status == "SUCCESS":
                raise MissingInputError(
                    f"{manifest}: {case_key} is SUCCESS but its canonical output is missing "
                    f"at {canonical}"
                )
            continue
        raw = _resolve(paths.root, row.get("raw_path"))
        refs[case_key] = OutputRef(
            model_key=model_key,
            case_key=case_key,
            canonical_path=canonical,
            canonical_sha256=_text_or_none(row.get("canonical_sha256")),
            raw_path=raw if raw is not None and raw.is_file() else None,
            raw_sha256=_text_or_none(row.get("raw_sha256")),
            status=status,
            sample_id=_text_or_none(row.get("sample_id")),
            benchmark=_text_or_none(row.get("benchmark")),
            source=SOURCE_FROZEN_MANIFEST,
        )
    return refs


def _from_runs(paths: ArenaPaths, model_key: str) -> dict[str, OutputRef]:
    refs: dict[str, OutputRef] = {}
    canonical_dir = paths.runs / model_key / "canonical"
    guards.assert_readable(canonical_dir)
    if not canonical_dir.is_dir():
        return refs
    for path in sorted(canonical_dir.glob("*.md")):
        case_key = path.stem
        raw = paths.raw_text_path(model_key, case_key)
        refs[case_key] = OutputRef(
            model_key=model_key,
            case_key=case_key,
            canonical_path=path,
            canonical_sha256=None,
            raw_path=raw if raw.is_file() else None,
            raw_sha256=None,
            status=None,
            sample_id=None,
            benchmark=None,
            source=SOURCE_RUNS_TREE,
        )
    return refs


def discover_output_models(paths: ArenaPaths) -> list[str]:
    models: set[str] = set()
    if paths.frozen_outputs.is_dir():
        for entry in paths.frozen_outputs.iterdir():
            if (entry / "manifest.jsonl").is_file():
                models.add(entry.name)
    if paths.runs.is_dir():
        for entry in paths.runs.iterdir():
            if (entry / "canonical").is_dir():
                models.add(entry.name)
    return sorted(models)


def load_outputs(
    paths: ArenaPaths, model_keys: Sequence[str] | None = None
) -> dict[str, dict[str, OutputRef]]:
    """``model_key -> case_key -> OutputRef`` for every model that produced output."""
    models = list(model_keys) if model_keys else discover_output_models(paths)
    loaded: dict[str, dict[str, OutputRef]] = {}
    for model_key in models:
        if paths.frozen_manifest(model_key).is_file():
            refs = _from_manifest(paths, model_key)
        else:
            refs = _from_runs(paths, model_key)
        if refs:
            loaded[model_key] = refs
    return loaded


def availability_index(
    outputs: Mapping[str, Mapping[str, OutputRef]],
) -> dict[str, tuple[str, ...]]:
    """``case_key -> the models that have a usable output for it``."""
    index: dict[str, list[str]] = {}
    for model_key, refs in outputs.items():
        for case_key in refs:
            index.setdefault(case_key, []).append(model_key)
    return {case_key: tuple(sorted(models)) for case_key, models in index.items()}


__all__ = [
    "SOURCE_FROZEN_MANIFEST",
    "SOURCE_RUNS_TREE",
    "OutputRef",
    "availability_index",
    "discover_output_models",
    "load_outputs",
]
