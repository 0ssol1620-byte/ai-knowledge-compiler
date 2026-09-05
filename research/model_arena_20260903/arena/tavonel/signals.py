"""Per ``(model_key, case_key)`` GT-free signal records (masterplan 12.2, 26).

Inputs, and nothing else (ARENA_CONTRACT section 8):

* ``runs/<model_key>/raw/<case_key>.raw.txt`` — the model's verbatim output
* ``runs/<model_key>/canonical/<case_key>.md`` — the canonicalised markdown
* ``runs/<model_key>/receipts/<case_key>.json`` — status, error class, tokens
* ``source_manifest.jsonl`` — the page's geometry and preflight row
* ``model_registry.json`` — the official max-token cap, when it records one

Output: ``tavonel/signals/<model_key>/<case_key>.json``, carrying a
``feature_set_version`` and a ``signals_sha256`` over its own body. No wall
clock enters the record, so recomputing it byte-identically is the test.

A feature that cannot be computed is ``null`` and its reason is recorded under
``unavailable``. Nothing here defaults a missing measurement to zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from arena.constants import CAMPAIGN_ID
from arena.tavonel import features, guards, jsonio
from arena.tavonel.errors import IntegrityError, MissingInputError
from arena.tavonel.paths import ArenaPaths

SIGNALS_SCHEMA = "tavonel.arena.signals.v1"

_MAX_TOKEN_CONFIG_KEYS = ("max_new_tokens", "max_tokens", "max_output_tokens")


@dataclass(frozen=True, slots=True)
class SignalsReport:
    """What one ``signals`` invocation did, for the CLI and for tests."""

    written: tuple[Path, ...]
    models: tuple[str, ...]
    case_count: int
    hash_mismatches: tuple[str, ...] = ()
    missing_outputs: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.hash_mismatches and not self.missing_outputs


@dataclass(frozen=True, slots=True)
class SourceIndex:
    """case_key -> geometry/preflight row from ``source_manifest.jsonl``."""

    rows: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    present: bool = False
    absence_reason: str | None = None


def load_source_index(paths: ArenaPaths) -> SourceIndex:
    manifest = paths.source_manifest
    if not manifest.is_file():
        return SourceIndex(
            rows={},
            present=False,
            absence_reason=f"source_manifest.jsonl absent at {manifest.name}",
        )
    rows: dict[str, Mapping[str, Any]] = {}
    for row in guards.iter_jsonl_guarded(manifest, what="source manifest"):
        case_key = row.get("case_key")
        if isinstance(case_key, str):
            rows[case_key] = row
    return SourceIndex(rows=rows, present=True, absence_reason=None)


def _registry_records(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    models = payload.get("models")
    if isinstance(models, dict):
        return models
    return payload


def load_max_output_tokens(paths: ArenaPaths) -> dict[str, int | None]:
    """Per-model output-token cap taken from the registry's official config."""
    registry = paths.model_registry
    if not registry.is_file():
        return {}
    payload = guards.read_json_guarded(registry, what="model registry")
    caps: dict[str, int | None] = {}
    for model_key, record in _registry_records(payload).items():
        if not isinstance(model_key, str) or not isinstance(record, dict):
            continue
        config = record.get("official_inference_config")
        cap: int | None = None
        if isinstance(config, dict):
            for key in _MAX_TOKEN_CONFIG_KEYS:
                value = config.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    cap = value
                    break
        caps[model_key] = cap
    return caps


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _geometry(
    row: Mapping[str, Any] | None,
    receipt: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(geometry, reason_when_absent)`` — never a fabricated size."""
    if row is not None:
        width = row.get("width")
        height = row.get("height")
        preflight = row.get("preflight")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            geometry: dict[str, Any] = {
                "width": width,
                "height": height,
                "megapixels": round(width * height / 1_000_000, 6),
                "geometry_source": "source_manifest",
            }
            if isinstance(preflight, dict):
                for key in (
                    "near_white_ratio",
                    "render_entropy",
                    "mean_intensity",
                    "edge_density",
                    "is_probably_blank",
                ):
                    if key in preflight:
                        geometry[key] = preflight[key]
            return geometry, None
    width = receipt.get("image_width")
    height = receipt.get("image_height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        return (
            {
                "width": width,
                "height": height,
                "megapixels": round(width * height / 1_000_000, 6),
                "geometry_source": "page_receipt",
            },
            None,
        )
    return None, "no page geometry in the source manifest row or the page receipt"


def _read_optional(path: Path) -> tuple[str | None, str | None]:
    """``(text, sha256)`` for an output file, or ``(None, None)`` when absent."""
    guards.assert_readable(path)
    if not path.is_file():
        return None, None
    data = path.read_bytes()
    return data.decode("utf-8", errors="replace"), jsonio.prefixed(jsonio.sha256_hex(data))


def compute_signals_record(
    *,
    paths: ArenaPaths,
    model_key: str,
    case_key: str,
    source_row: Mapping[str, Any] | None,
    max_output_tokens: int | None,
) -> dict[str, Any]:
    """Build one signals record. Raises when a required frozen input is absent."""
    receipt_path = guards.require_file(
        paths.receipt_path(model_key, case_key), what=f"page receipt for {model_key}/{case_key}"
    )
    receipt = jsonio.load_json_object(receipt_path)
    receipt_sha = jsonio.prefixed(jsonio.sha256_hex(receipt_path.read_bytes()))

    raw_text, raw_sha = _read_optional(paths.raw_text_path(model_key, case_key))
    canonical_text, canonical_sha = _read_optional(paths.canonical_path(model_key, case_key))

    status = receipt.get("status")
    unavailable: dict[str, str] = {}

    if canonical_text is not None:
        text = canonical_text
        text_source = "canonical"
    elif raw_text is not None:
        text = raw_text
        text_source = "raw"
        unavailable["canonical_markdown"] = "no canonical output file; features read the raw output"
    else:
        text = ""
        text_source = "none"
        if status == "SUCCESS":
            raise IntegrityError(
                f"{model_key}/{case_key}: receipt says SUCCESS but neither a raw nor a "
                "canonical output file exists"
            )
        unavailable["output_text"] = f"no output file on disk; receipt status is {status!r}"

    output_tokens = receipt.get("output_tokens")
    tokens_at_max: bool | None
    if isinstance(output_tokens, int) and isinstance(max_output_tokens, int):
        tokens_at_max = output_tokens >= max_output_tokens
    else:
        tokens_at_max = None
        unavailable["output_tokens_at_max"] = (
            "the receipt carries no output_tokens or the registry records no output cap"
        )

    computed = features.compute_text_features(text, output_tokens_at_max=tokens_at_max)
    geometry, geometry_reason = _geometry(source_row, receipt)
    if geometry_reason is not None:
        unavailable["source_geometry"] = geometry_reason

    if geometry is not None and geometry["megapixels"] > 0:
        ratio: float | None = round(computed.output_chars / float(geometry["megapixels"]), 6)
    else:
        ratio = None
        unavailable["output_to_source_ratio"] = (
            "output chars per megapixel needs page geometry, which is not available"
        )

    record: dict[str, Any] = {
        "schema": SIGNALS_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "feature_set_version": features.FEATURE_SET_VERSION,
        "model_key": model_key,
        "case_key": case_key,
        "sample_id": receipt.get("sample_id"),
        "benchmark": receipt.get("benchmark"),
        "text_source": text_source,
        "inputs": {
            "receipt_path": _relative(receipt_path, paths.root),
            "receipt_sha256": receipt_sha,
            "raw_path": (
                None
                if raw_sha is None
                else _relative(paths.raw_text_path(model_key, case_key), paths.root)
            ),
            "raw_sha256": raw_sha,
            "raw_sha256_matches_receipt": _matches(raw_sha, receipt.get("raw_output_sha256")),
            "canonical_path": (
                None
                if canonical_sha is None
                else _relative(paths.canonical_path(model_key, case_key), paths.root)
            ),
            "canonical_sha256": canonical_sha,
            "canonical_sha256_matches_receipt": _matches(
                canonical_sha, receipt.get("canonical_output_sha256")
            ),
        },
        "run": {
            "status": status,
            "error_class": receipt.get("error_class"),
            "inference_job_id": receipt.get("inference_job_id"),
            "runtime_mode": receipt.get("runtime_mode"),
            "attempt": receipt.get("attempt"),
            "retry_count": receipt.get("retry_count"),
            "output_tokens": output_tokens,
            "max_output_tokens": max_output_tokens,
            "output_tokens_at_max": tokens_at_max,
        },
        "features": computed.as_dict(),
        "derived": {"output_to_source_ratio": ratio},
        "source_geometry": geometry,
        "unavailable": unavailable,
    }
    record["signals_sha256"] = jsonio.prefixed(
        jsonio.record_digest(record, exclude=("signals_sha256",))
    )
    return record


def _matches(computed: str | None, recorded: object) -> bool | None:
    """``None`` when either side is missing — an unknown is not a match."""
    if computed is None or not isinstance(recorded, str) or not recorded:
        return None
    return computed == recorded


def discover_case_keys(paths: ArenaPaths, model_key: str) -> list[str]:
    """Case keys that actually ran, taken from the model's receipts directory."""
    receipts = paths.receipts_dir(model_key)
    guards.assert_readable(receipts)
    if not receipts.is_dir():
        raise MissingInputError(f"no receipts directory for model {model_key}: {receipts}")
    return sorted(path.stem for path in receipts.glob("*.json") if path.is_file())


def discover_models(paths: ArenaPaths) -> list[str]:
    if not paths.runs.is_dir():
        raise MissingInputError(f"no runs directory at {paths.runs}")
    return sorted(
        entry.name for entry in paths.runs.iterdir() if (entry / "receipts").is_dir()
    )


def build_signals(paths: ArenaPaths, model_keys: Sequence[str] | None = None) -> SignalsReport:
    """Compute and write signals for every case of every requested model."""
    models = list(model_keys) if model_keys else discover_models(paths)
    source_index = load_source_index(paths)
    caps = load_max_output_tokens(paths)
    written: list[Path] = []
    mismatches: list[str] = []
    missing: list[str] = []
    case_count = 0

    for model_key in models:
        for case_key in discover_case_keys(paths, model_key):
            record = compute_signals_record(
                paths=paths,
                model_key=model_key,
                case_key=case_key,
                source_row=source_index.rows.get(case_key),
                max_output_tokens=caps.get(model_key),
            )
            destination = paths.signals_path(model_key, case_key)
            jsonio.write_json_atomic(destination, record)
            written.append(destination)
            case_count += 1
            inputs = record["inputs"]
            for side in ("raw", "canonical"):
                if inputs[f"{side}_sha256_matches_receipt"] is False:
                    mismatches.append(f"{model_key}/{case_key}:{side}")
            if record["text_source"] == "none":
                missing.append(f"{model_key}/{case_key}")

    return SignalsReport(
        written=tuple(written),
        models=tuple(models),
        case_count=case_count,
        hash_mismatches=tuple(mismatches),
        missing_outputs=tuple(missing),
    )


def load_signals(paths: ArenaPaths, model_key: str, case_keys: Iterable[str]) -> dict[str, Any]:
    """Read back written signal records, keyed by case_key."""
    loaded: dict[str, Any] = {}
    for case_key in case_keys:
        path = paths.signals_path(model_key, case_key)
        if path.is_file():
            loaded[case_key] = guards.read_json_guarded(path, what="signals record")
    return loaded


def load_all_signals(paths: ArenaPaths, model_key: str) -> dict[str, Any]:
    directory = paths.signals_dir(model_key)
    guards.assert_readable(directory)
    if not directory.is_dir():
        return {}
    return {
        path.stem: guards.read_json_guarded(path, what="signals record")
        for path in sorted(directory.glob("*.json"))
    }


__all__ = [
    "SIGNALS_SCHEMA",
    "SignalsReport",
    "SourceIndex",
    "build_signals",
    "compute_signals_record",
    "discover_case_keys",
    "discover_models",
    "load_all_signals",
    "load_max_output_tokens",
    "load_signals",
    "load_source_index",
]
