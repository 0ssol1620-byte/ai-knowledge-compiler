"""Immutable identifiers for the arena campaign (masterplan section 9).

Every identifier here is a pure function of values that are already frozen.
Nothing in this module reads the clock, the filesystem (except
:func:`sha256_file`) or the network, so two lanes that hold the same inputs
compute the same id byte for byte.

Two shapes of digest exist on purpose and are never mixed:

- ``"sha256:<64 lowercase hex>"`` identifies *file bytes* (ARENA_CONTRACT
  section 2). Use :func:`sha256_ref` / :func:`sha256_file`.
- bare 64-hex identifies a *record derived from canonical JSON* (job ids).
  Use :func:`sha256_hex`.

A runtime that has no image at all still needs a runtime identity: a bootstrap
pod uses ``"bootstrap:<bundle sha256>"`` and a subscription runtime uses
``"subscription:<label>"`` (ARENA_CONTRACT 11.5 D15/D27).

Inputs are validated rather than coerced. A malformed source path, an
unknown benchmark or a digest in the wrong shape raises :class:`IdError`
instead of producing an id that silently differs from another lane's.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Final

from arena.constants import BENCHMARK_KEYS, MODEL_KEYS, STAGED_BENCHMARK_ID

__all__ = [
    "RECOVERY_TYPES",
    "SHARD_INDEX_WIDTH",
    "IdError",
    "bootstrap_image_digest",
    "canonical_json",
    "canonical_json_bytes",
    "case_key_from_staged",
    "inference_job_id",
    "recovery_job_id",
    "sample_id_from_staged",
    "sha256_file",
    "sha256_hex",
    "sha256_ref",
    "shard_id",
    "subscription_image_digest",
    "worker_id",
]


class IdError(ValueError):
    """Raised when an identifier input is missing, malformed or ambiguous."""


SHA256_REF_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"
HEX64_PATTERN: Final = r"^[0-9a-f]{64}$"
# A pinned OCI digest ("repo@sha256:<hex>" or a bare "sha256:<hex>"), the
# bootstrap marker the canary uses before a baked image exists (contract 2),
# or the subscription marker of a model that has no container at all
# (ARENA_CONTRACT 11.5 D27): "subscription:<label>". The label is deliberately
# narrow - no slash, no whitespace, no colon - so a subscription digest can
# never be mistaken for an image reference or a registry path.
SUBSCRIPTION_LABEL_PATTERN: Final = r"[A-Za-z0-9._-]+"
RUNTIME_IMAGE_DIGEST_PATTERN: Final = (
    r"^(?:bootstrap:(?:sha256:)?[0-9a-f]{64}"
    rf"|subscription:{SUBSCRIPTION_LABEL_PATTERN}"
    r"|(?:[^\s@]+@)?sha256:[0-9a-f]{64})$"
)

_SHA256_REF_RE: Final = re.compile(SHA256_REF_PATTERN)
_SUBSCRIPTION_LABEL_RE: Final = re.compile(f"^{SUBSCRIPTION_LABEL_PATTERN}$")
_RUNTIME_IMAGE_DIGEST_RE: Final = re.compile(RUNTIME_IMAGE_DIGEST_PATTERN)
_CASE_KEY_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_POD_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# The staged public-core tree renders every page from one of these sources.
# An unknown extension is a manifest change, not something to guess through.
SOURCE_EXTENSIONS: Final = frozenset(
    {".png", ".jpg", ".jpeg", ".pdf", ".tif", ".tiff", ".webp", ".bmp"}
)

# Masterplan section 24.
RECOVERY_TYPES: Final = (
    "overlap_tiling",
    "crop",
    "region_extract",
    "higher_dpi",
    "alternative_prompt",
    "safer_config",
    "partial_page",
)

# 5,132 pages never shard past four digits; a fixed width keeps shard ids
# sortable as plain strings.
SHARD_INDEX_WIDTH: Final = 4
_MAX_SHARD_INDEX: Final = 10**SHARD_INDEX_WIDTH - 1
_MAX_WORKER_INDEX: Final = 9_999


# --------------------------------------------------------------------------
# canonical json + digests
# --------------------------------------------------------------------------


def canonical_json(obj: Any) -> str:
    """Deterministic JSON text: sorted keys, no spaces, ASCII-escaped.

    ``allow_nan=False`` because NaN/Infinity are not JSON and would make an
    identifier depend on the writer's json implementation.
    """

    try:
        return json.dumps(
            obj,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:  # pragma: no cover - message varies
        raise IdError(f"value is not canonical JSON: {exc}") from exc


def canonical_json_bytes(obj: Any) -> bytes:
    """:func:`canonical_json` encoded UTF-8 (identical to ASCII here)."""

    return canonical_json(obj).encode("utf-8")


def sha256_hex(data: bytes | str) -> str:
    """Bare lowercase hex sha256. Used for ids derived from canonical JSON."""

    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_ref(data: bytes | str) -> str:
    """``"sha256:<hex>"`` reference. Used for anything that identifies bytes."""

    return f"sha256:{sha256_hex(data)}"


def sha256_file(path: Path | str, *, chunk_size: int = 1 << 20) -> str:
    """``"sha256:<hex>"`` of a file's bytes, read in chunks."""

    file_path = Path(path)
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def bootstrap_image_digest(runtime_bundle_sha256: str) -> str:
    """The ``runtime_image_digest`` a bootstrap-mode canary uses (contract 2)."""

    ref = _require_text(runtime_bundle_sha256, "runtime_bundle_sha256")
    if not _SHA256_REF_RE.fullmatch(ref):
        raise IdError("runtime_bundle_sha256 must be 'sha256:<64 lowercase hex>'")
    return f"bootstrap:{ref}"


def subscription_image_digest(label: str) -> str:
    """The ``runtime_image_digest`` of a subscription runtime (11.5 D27).

    The Opus lane passes ``claude-code-<cli version>-<model id>``. There is no
    container and no bundle, so the identity of the runtime is the CLI build
    plus the model id; a label that cannot be written unambiguously (a slash,
    a space, a colon) raises instead of being sanitised into a different id.
    """

    text = _require_text(label, "label")
    if not _SUBSCRIPTION_LABEL_RE.fullmatch(text):
        raise IdError(
            "subscription label must match [A-Za-z0-9._-]+ (no slash, colon or "
            f"whitespace), got {text!r}"
        )
    return f"subscription:{text}"


# --------------------------------------------------------------------------
# sample_id / case_key (ARENA_CONTRACT section 2)
# --------------------------------------------------------------------------


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise IdError(f"{field} must be a string, got {type(value).__name__}")
    if not value or value.strip() != value:
        raise IdError(f"{field} must be non-empty and free of surrounding whitespace")
    return value


def _require_benchmark(benchmark_key: str) -> str:
    key = _require_text(benchmark_key, "benchmark_key")
    if key not in BENCHMARK_KEYS:
        raise IdError(f"unknown benchmark key {key!r}; expected one of {BENCHMARK_KEYS}")
    return key


def _require_index(value: object, field: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IdError(f"{field} must be an int, got {type(value).__name__}")
    if value < 0 or value > maximum:
        raise IdError(f"{field} must be between 0 and {maximum}, got {value}")
    return value


def strip_source_extension(source_relative_path: str) -> str:
    """The staged ``source_relative_path`` minus its final known extension."""

    rel = _require_text(source_relative_path, "source_relative_path")
    if "\\" in rel:
        raise IdError("source_relative_path must use forward slashes")
    if rel.startswith("/") or ".." in PurePosixPath(rel).parts:
        raise IdError("source_relative_path must be a relative path without '..'")
    suffix = PurePosixPath(rel).suffix
    if suffix.lower() not in SOURCE_EXTENSIONS:
        raise IdError(
            f"source_relative_path {rel!r} has no known source extension "
            f"(expected one of {sorted(SOURCE_EXTENSIONS)})"
        )
    return rel[: -len(suffix)]


def sample_id_from_staged(staged_entry: Mapping[str, Any], benchmark_key: str) -> str:
    """``<benchmark>:<official-id>`` for one staged manifest row.

    official-id is ``source_relative_path`` with its extension removed, plus
    ``#p<page_index>`` when ``media_type == "pdf"`` (ARENA_CONTRACT section 2).
    An image page keeps its ``page_index`` in the manifest but not in the id,
    because the rendered PNG already *is* that page.
    """

    benchmark = _require_benchmark(benchmark_key)
    relative_path = _require_text(
        staged_entry.get("source_relative_path"), "source_relative_path"
    )
    official = strip_source_extension(relative_path)
    media_type = _require_text(staged_entry.get("media_type"), "media_type")
    if media_type != "pdf":
        return f"{benchmark}:{official}"
    page_index = _require_index(staged_entry.get("page_index"), "page_index", 100_000)
    return f"{benchmark}:{official}#p{page_index}"


def case_key_from_staged(staged_entry: Mapping[str, Any], benchmark_key: str) -> str:
    """The staged ``case_id``, checked for filesystem safety and benchmark fit."""

    benchmark = _require_benchmark(benchmark_key)
    case_id = _require_text(staged_entry.get("case_id"), "case_id")
    if not _CASE_KEY_RE.fullmatch(case_id):
        raise IdError(
            f"case_id {case_id!r} is not filesystem-safe "
            "(expected [A-Za-z0-9][A-Za-z0-9._-]{0,119})"
        )
    expected_prefix = f"{STAGED_BENCHMARK_ID[benchmark]}-"
    if not case_id.startswith(expected_prefix):
        raise IdError(f"case_id {case_id!r} does not belong to benchmark {benchmark!r}")
    return case_id


# --------------------------------------------------------------------------
# job / shard / worker ids
# --------------------------------------------------------------------------


def _require_sha256_ref(value: str, field: str) -> str:
    ref = _require_text(value, field)
    if not _SHA256_REF_RE.fullmatch(ref):
        raise IdError(f"{field} must be 'sha256:<64 lowercase hex>', got {ref!r}")
    return ref


def inference_job_id(
    *,
    campaign_id: str,
    benchmark_revision: str,
    sample_id: str,
    source_sha256: str,
    model_repo: str,
    model_revision: str,
    runtime_image_digest: str,
    prompt_sha256: str,
    inference_config_sha256: str,
) -> str:
    """sha256 hex over exactly the nine fields of ARENA_CONTRACT section 2.

    Keyword-only so a caller cannot reorder the fields silently. The same id
    with an existing ``SUCCESS`` receipt and a matching ``raw_output_sha256``
    is never re-run (masterplan section 9.3).
    """

    digest = _require_text(runtime_image_digest, "runtime_image_digest")
    if not _RUNTIME_IMAGE_DIGEST_RE.fullmatch(digest):
        raise IdError(
            "runtime_image_digest must be 'sha256:<hex>', '<image>@sha256:<hex>', "
            "'bootstrap:<runtime_bundle_sha256>' or 'subscription:<label>', "
            f"got {digest!r}"
        )
    payload = {
        "campaign_id": _require_text(campaign_id, "campaign_id"),
        "benchmark_revision": _require_text(benchmark_revision, "benchmark_revision"),
        "sample_id": _require_text(sample_id, "sample_id"),
        "source_sha256": _require_sha256_ref(source_sha256, "source_sha256"),
        "model_repo": _require_text(model_repo, "model_repo"),
        "model_revision": _require_text(model_revision, "model_revision"),
        "runtime_image_digest": digest,
        "prompt_sha256": _require_sha256_ref(prompt_sha256, "prompt_sha256"),
        "inference_config_sha256": _require_sha256_ref(
            inference_config_sha256, "inference_config_sha256"
        ),
    }
    return sha256_hex(canonical_json(payload))


def recovery_job_id(
    *,
    campaign_id: str,
    inference_job_id_of_base: str,
    recovery_type: str,
    recovery_config_sha256: str,
    # The canonical JSON key is literally "round" (masterplan section 24), so
    # the parameter carries that name even though it shadows the builtin.
    round: int,
) -> str:
    """sha256 hex for one TAVONEL recovery attempt (masterplan section 24)."""

    base = _require_text(inference_job_id_of_base, "inference_job_id_of_base")
    if not re.fullmatch(HEX64_PATTERN, base):
        raise IdError("inference_job_id_of_base must be bare 64 lowercase hex")
    kind = _require_text(recovery_type, "recovery_type")
    if kind not in RECOVERY_TYPES:
        raise IdError(f"unknown recovery_type {kind!r}; expected one of {RECOVERY_TYPES}")
    if isinstance(round, bool) or not isinstance(round, int) or round < 1:
        raise IdError("round must be an int >= 1")
    payload = {
        "campaign_id": _require_text(campaign_id, "campaign_id"),
        "inference_job_id_of_base": base,
        "recovery_type": kind,
        "recovery_config_sha256": _require_sha256_ref(
            recovery_config_sha256, "recovery_config_sha256"
        ),
        "round": round,
    }
    return sha256_hex(canonical_json(payload))


def _require_model_key(model_key: str) -> str:
    key = _require_text(model_key, "model_key")
    if key not in MODEL_KEYS:
        raise IdError(f"unknown model_key {key!r}; expected one of {MODEL_KEYS}")
    return key


def shard_id(model_key: str, benchmark: str, index: int) -> str:
    """``<model_key>-<benchmark>-<zero-padded index>`` (ARENA_CONTRACT section 2)."""

    key = _require_model_key(model_key)
    bench = _require_benchmark(benchmark)
    position = _require_index(index, "index", _MAX_SHARD_INDEX)
    return f"{key}-{bench}-{position:0{SHARD_INDEX_WIDTH}d}"


def worker_id(model_key: str, index: int, pod_id: str) -> str:
    """``<model_key>-w<index>-<pod_id>`` (ARENA_CONTRACT section 2)."""

    key = _require_model_key(model_key)
    position = _require_index(index, "index", _MAX_WORKER_INDEX)
    pod = _require_text(pod_id, "pod_id")
    if not _POD_ID_RE.fullmatch(pod):
        raise IdError(f"pod_id {pod!r} is not a safe provider id")
    return f"{key}-w{position}-{pod}"
