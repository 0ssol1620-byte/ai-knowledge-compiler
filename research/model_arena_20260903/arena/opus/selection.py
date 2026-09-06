"""Page selection and PNG facts for the Opus lane.

Lane A2 owns ``canary_selection.json`` and ``source_manifest.jsonl``. This lane
reads them and, per ARENA_CONTRACT D27, **refuses** its deterministic fallback
once ``canary_selection.json`` exists: a frozen selection that is silently
replaced by a locally computed one is the same failure as a silent model
fallback. The fallback survives only for the case where lane A2 has not
published anything at all, and the path taken is recorded in every receipt.

Every identifier is derived through ``arena.core.ids``; this module holds no
private id implementation. It never reads anything under
``benchmark/datasets/acquired`` (ground truth).

``select_canary_pages`` is the 50-page frozen canary. ``select_source_manifest_pages``
is the whole-campaign selection ``run`` uses by default (ARENA_CONTRACT section
7): every row of ``source_manifest.jsonl``, resolved and cross-checked against
the staged manifests the same way the frozen canary block is.

PNG dimensions are read from the IHDR chunk with the standard library so the
runner has no image dependency and cannot silently decode a non-PNG.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from arena.constants import (
    CANARY_SALT,
    NAMESPACE_ROOT,
    STAGED_BENCHMARK_ID,
    STAGED_PUBLIC_CORE_ROOT,
)
from arena.core.ids import IdError, case_key_from_staged, sample_id_from_staged
from arena.opus.paths import read_json, sha256_tagged

CANARY_SELECTION_PATH: Final = NAMESPACE_ROOT / "canary_selection.json"
# Lane A2's whole-campaign row list (5,132 rows: parsebench 2078, omnidoc 1651,
# olmocr 1403). ``run`` selects from this by default; ``canary`` never does.
SOURCE_MANIFEST_PATH: Final = NAMESPACE_ROOT / "source_manifest.jsonl"
PNG_MAGIC: Final = b"\x89PNG\r\n\x1a\n"
_STAGED_TO_BENCHMARK: Final = {v: k for k, v in STAGED_BENCHMARK_ID.items()}


class SelectionError(RuntimeError):
    """Raised when a page cannot be resolved without guessing."""


@dataclass(frozen=True, slots=True)
class PageSpec:
    """One page to transcribe, resolved from the staged manifest."""

    case_key: str
    sample_id: str
    benchmark: str
    benchmark_revision: str
    image_path: Path
    manifest_input_sha256: str
    staged_source_sha256: str
    media_type: str
    page_index: int | None
    source_relative_path: str


def read_png_size(data: bytes) -> tuple[int, int]:
    """(width, height) from a PNG IHDR. Raises on anything that is not a PNG."""
    if len(data) < 24 or not data.startswith(PNG_MAGIC):
        raise SelectionError("input is not a PNG (magic bytes do not match)")
    if data[12:16] != b"IHDR":
        raise SelectionError("input is not a PNG (first chunk is not IHDR)")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        raise SelectionError(f"PNG reports a non-positive size: {width}x{height}")
    return int(width), int(height)


def staged_manifest_path(benchmark: str) -> Path:
    staged_id = STAGED_BENCHMARK_ID.get(benchmark, benchmark)
    return STAGED_PUBLIC_CORE_ROOT / staged_id / "inference-input-manifest.json"




def load_staged_index(benchmark: str) -> dict[str, PageSpec]:
    """case_key -> PageSpec for one benchmark, from the staged input manifest."""
    manifest = staged_manifest_path(benchmark)
    if not manifest.is_file():
        raise SelectionError(f"staged input manifest missing: {manifest}")
    data = read_json(manifest)
    if not isinstance(data, dict):
        raise SelectionError(f"staged input manifest is not an object: {manifest}")
    revision = str(data.get("dataset_revision") or "")
    if not revision:
        raise SelectionError(f"staged input manifest has no dataset_revision: {manifest}")
    inputs = data.get("inputs")
    if not isinstance(inputs, list):
        raise SelectionError(f"staged input manifest has no inputs list: {manifest}")

    root = manifest.parent
    index: dict[str, PageSpec] = {}
    for entry in inputs:
        if not isinstance(entry, dict):
            continue
        media_type = str(entry.get("media_type") or "")
        raw_page_index = entry.get("page_index")
        page_index = int(raw_page_index) if isinstance(raw_page_index, int) else None
        source_relative_path = str(entry["source_relative_path"])
        try:
            case_key = case_key_from_staged(entry, benchmark)
            sample_id = sample_id_from_staged(entry, benchmark)
        except IdError as exc:
            raise SelectionError(
                f"staged manifest row {entry.get('case_id')!r} in {manifest}: {exc}"
            ) from exc
        index[case_key] = PageSpec(
            case_key=case_key,
            sample_id=sample_id,
            benchmark=benchmark,
            benchmark_revision=revision,
            image_path=root / str(entry["input_relative_path"]),
            manifest_input_sha256=str(entry["input_sha256"]),
            staged_source_sha256=str(entry["source_sha256"]),
            media_type=media_type,
            page_index=page_index,
            source_relative_path=source_relative_path,
        )
    return index


def benchmark_of_case_key(case_key: str) -> str:
    """``omnidocbench-<hex>`` -> ``omnidoc``. Refuses an unknown prefix."""
    for staged_id, benchmark in _STAGED_TO_BENCHMARK.items():
        if case_key.startswith(f"{staged_id}-"):
            return benchmark
    raise SelectionError(f"case_key {case_key!r} does not name a known staged benchmark")


def resolve_case_keys(case_keys: list[str]) -> list[PageSpec]:
    """Resolve case keys against the staged manifests, preserving input order."""
    caches: dict[str, dict[str, PageSpec]] = {}
    specs: list[PageSpec] = []
    for case_key in case_keys:
        benchmark = benchmark_of_case_key(case_key)
        if benchmark not in caches:
            caches[benchmark] = load_staged_index(benchmark)
        spec = caches[benchmark].get(case_key)
        if spec is None:
            raise SelectionError(f"case_key {case_key!r} is not in the staged manifest")
        specs.append(spec)
    return specs


@dataclass(frozen=True, slots=True)
class FrozenPage:
    """One row of the frozen ``opus_canary`` block."""

    case_key: str
    sample_id: str | None
    input_png_sha256: str | None


def read_frozen_opus_canary(path: Path) -> tuple[FrozenPage, ...]:
    """The ``opus_canary`` rows of ``canary_selection.json``.

    Raises rather than returning an empty selection: the caller has already
    established that this file exists, and a file that exists but cannot be read
    is a stop, not a reason to compute a different selection (D27).
    """
    data = read_json(path)
    if not isinstance(data, dict):
        raise SelectionError(f"{path} is not a JSON object")
    block: Any = data.get("opus_canary")
    if block is None:
        raise SelectionError(
            f"{path} exists but carries no 'opus_canary' block; lane A2 owns that "
            "block and this lane may not substitute a selection of its own (D27)"
        )
    rows: Any = block
    if isinstance(block, dict):
        for key in ("samples", "case_keys", "cases"):
            if isinstance(block.get(key), list):
                rows = block[key]
                break
        else:
            raise SelectionError(
                f"{path}: 'opus_canary' has none of samples/case_keys/cases; "
                f"keys present: {sorted(block)}"
            )
    if not isinstance(rows, list) or not rows:
        raise SelectionError(f"{path}: 'opus_canary' resolves to no rows")

    pages: list[FrozenPage] = []
    for position, item in enumerate(rows):
        if isinstance(item, str):
            pages.append(FrozenPage(case_key=item, sample_id=None, input_png_sha256=None))
            continue
        if not isinstance(item, dict) or not isinstance(item.get("case_key"), str):
            raise SelectionError(
                f"{path}: 'opus_canary' row {position} has no string case_key"
            )
        sample_id = item.get("sample_id")
        png_sha = item.get("input_png_sha256")
        pages.append(
            FrozenPage(
                case_key=str(item["case_key"]),
                sample_id=str(sample_id) if isinstance(sample_id, str) else None,
                input_png_sha256=str(png_sha) if isinstance(png_sha, str) else None,
            )
        )
    if len({page.case_key for page in pages}) != len(pages):
        raise SelectionError(f"{path}: 'opus_canary' repeats a case_key")
    return tuple(pages)


def _check_against_frozen(spec: PageSpec, frozen: FrozenPage, path: Path) -> None:
    """Fail closed when the staged manifest and the frozen block disagree.

    ``sample_id`` is re-derived from the staged manifest through
    ``arena.core.ids``; if lane A2's frozen row names a different one the two
    lanes are looking at different pages and no receipt may be written.
    """
    if frozen.sample_id is not None and frozen.sample_id != spec.sample_id:
        raise SelectionError(
            f"{path}: frozen sample_id for {spec.case_key} is {frozen.sample_id!r} but "
            f"the staged manifest derives {spec.sample_id!r}"
        )
    if (
        frozen.input_png_sha256 is not None
        and spec.manifest_input_sha256
        and frozen.input_png_sha256 != spec.manifest_input_sha256
    ):
        raise SelectionError(
            f"{path}: frozen input_png_sha256 for {spec.case_key} is "
            f"{frozen.input_png_sha256} but the staged manifest says "
            f"{spec.manifest_input_sha256}"
        )


def fallback_canary_keys(limit: int, *, benchmark: str = "omnidoc") -> list[str]:
    """Deterministic GT-blind selection used until lane A2 publishes its file.

    Staged PNG file names sorted by ``sha256(name + CANARY_SALT)``; the first
    ``limit`` names become case keys. The salt is the frozen campaign salt so the
    choice is reproducible and cannot be tuned after seeing a result.
    """
    staged_id = STAGED_BENCHMARK_ID.get(benchmark, benchmark)
    inputs_dir = STAGED_PUBLIC_CORE_ROOT / staged_id / "inputs"
    if not inputs_dir.is_dir():
        raise SelectionError(f"staged inputs directory missing: {inputs_dir}")
    names = sorted(p.name for p in inputs_dir.iterdir() if p.suffix.lower() == ".png")
    if not names:
        raise SelectionError(f"no staged PNGs under {inputs_dir}")
    ranked = sorted(
        names,
        key=lambda name: hashlib.sha256((name + CANARY_SALT).encode("utf-8")).hexdigest(),
    )
    return [Path(name).stem for name in ranked[:limit]]


@dataclass(frozen=True, slots=True)
class CanarySelection:
    specs: tuple[PageSpec, ...]
    source: str
    detail: str


def select_canary_pages(limit: int, *, selection_path: Path | None = None) -> CanarySelection:
    """The frozen ``opus_canary`` block, or the fallback only when no file exists.

    ARENA_CONTRACT D27: once ``canary_selection.json`` exists the deterministic
    fallback is refused. ``limit`` may only trim the frozen block; asking for
    more pages than it holds is an error, never a top-up from somewhere else.
    """
    path = selection_path or CANARY_SELECTION_PATH
    if path.is_file():
        frozen = read_frozen_opus_canary(path)
        if limit > len(frozen):
            raise SelectionError(
                f"{path}: the frozen opus_canary block holds {len(frozen)} pages; "
                f"{limit} were requested and this lane may not invent the difference"
            )
        chosen = frozen[:limit]
        specs = resolve_case_keys([page.case_key for page in chosen])
        for spec, page in zip(specs, chosen, strict=True):
            _check_against_frozen(spec, page, path)
        return CanarySelection(
            specs=tuple(specs),
            source="canary_selection.json:opus_canary",
            detail=(
                f"{path}: frozen opus_canary block, {len(frozen)} pages, "
                f"{len(chosen)} used; sample_id and input_png_sha256 cross-checked "
                "against the staged manifest"
            ),
        )
    chosen_keys = fallback_canary_keys(limit)
    return CanarySelection(
        specs=tuple(resolve_case_keys(chosen_keys)),
        source="deterministic_fallback",
        detail=(
            f"{path} does not exist; used the first {limit} staged omnidocbench PNG "
            "names sorted by sha256(name + CANARY_SALT). Refused automatically as "
            "soon as lane A2 publishes that file (ARENA_CONTRACT D27)."
        ),
    )


def _read_source_manifest_rows(data: bytes, path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = data.decode("utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SelectionError(f"{path}:{line_no}: not valid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise SelectionError(f"{path}:{line_no}: row is not a JSON object")
        rows.append(row)
    return rows


def select_source_manifest_pages(
    limit: int | None, *, manifest_path: Path | None = None
) -> CanarySelection:
    """The whole campaign benchmark, from ``source_manifest.jsonl`` (lane A2).

    Reads every row of the manifest in file order, resolves each row's
    ``case_key`` against the staged manifest for its ``benchmark`` (through
    :func:`load_staged_index`, cached per benchmark rather than re-read per
    row -- there are 5,132 rows), and fails closed -- the same discipline
    :func:`_check_against_frozen` applies to the frozen canary block -- when a
    row's ``case_key`` is not in the staged index for its benchmark, or its
    ``input_png_sha256`` disagrees with what the staged manifest derives for
    that case_key. Manifest order is preserved; ``limit`` (``None`` means
    every row) only trims the selection, and validation stops at the same
    point the selection does.
    """
    path = manifest_path or SOURCE_MANIFEST_PATH
    if not path.is_file():
        raise SelectionError(f"source manifest missing: {path}")
    manifest_bytes = path.read_bytes()
    manifest_sha256 = sha256_tagged(manifest_bytes)
    rows = _read_source_manifest_rows(manifest_bytes, path)
    if not rows:
        raise SelectionError(f"{path} has no rows")

    total_counts: dict[str, int] = {}
    for row_index, row in enumerate(rows):
        benchmark = row.get("benchmark")
        if not isinstance(benchmark, str) or not benchmark:
            raise SelectionError(f"{path}: row {row_index} has no string benchmark")
        total_counts[benchmark] = total_counts.get(benchmark, 0) + 1

    caches: dict[str, dict[str, PageSpec]] = {}
    specs: list[PageSpec] = []
    for row_index, row in enumerate(rows):
        if limit is not None and len(specs) >= limit:
            break
        case_key = row.get("case_key")
        if not isinstance(case_key, str) or not case_key:
            raise SelectionError(f"{path}: row {row_index} has no string case_key")
        benchmark = str(row["benchmark"])
        if benchmark not in caches:
            caches[benchmark] = load_staged_index(benchmark)
        spec = caches[benchmark].get(case_key)
        if spec is None:
            raise SelectionError(
                f"{path}: row {row_index} case_key {case_key!r} is not in the staged "
                f"{benchmark} manifest"
            )
        row_sha = row.get("input_png_sha256")
        if isinstance(row_sha, str) and row_sha and row_sha != spec.manifest_input_sha256:
            raise SelectionError(
                f"{path}: row {row_index} input_png_sha256 for {case_key} is {row_sha} but "
                f"the staged manifest derives {spec.manifest_input_sha256}"
            )
        specs.append(spec)

    counts_str = ", ".join(f"{k}={v}" for k, v in sorted(total_counts.items()))
    detail = (
        f"{path}: {len(rows)} rows ({counts_str}); {len(specs)} selected"
        + (f" (--limit {limit})" if limit is not None else " (all rows)")
        + f"; manifest sha256 {manifest_sha256}; every selected case_key resolved against "
        "the staged manifest and cross-checked on input_png_sha256"
    )
    return CanarySelection(
        specs=tuple(specs),
        source="source_manifest.jsonl",
        detail=detail,
    )


def read_image_facts(spec: PageSpec) -> tuple[bytes, str, int, int]:
    """Bytes, ``sha256:<hex>``, width, height. Fails closed on a hash mismatch."""
    if not spec.image_path.is_file():
        raise SelectionError(f"page image missing: {spec.image_path}")
    data = spec.image_path.read_bytes()
    digest = sha256_tagged(data)
    if spec.manifest_input_sha256 and digest != spec.manifest_input_sha256:
        raise SelectionError(
            f"page image hash mismatch for {spec.case_key}: manifest says "
            f"{spec.manifest_input_sha256}, file is {digest}"
        )
    width, height = read_png_size(data)
    return data, digest, width, height


__all__ = [
    "CANARY_SELECTION_PATH",
    "SOURCE_MANIFEST_PATH",
    "CanarySelection",
    "FrozenPage",
    "PageSpec",
    "SelectionError",
    "benchmark_of_case_key",
    "fallback_canary_keys",
    "load_staged_index",
    "read_frozen_opus_canary",
    "read_image_facts",
    "read_png_size",
    "resolve_case_keys",
    "select_canary_pages",
    "select_source_manifest_pages",
    "staged_manifest_path",
]
