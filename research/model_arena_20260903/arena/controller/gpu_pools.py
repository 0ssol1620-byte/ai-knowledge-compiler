"""Validate ``gpu_pool_priority`` against the provider catalog (D9).

A GPU id that the catalog does not carry is not a slow path or a fallback: it
is a create request that will be rejected after the campaign has already paid
for everything upstream of it. So every name is checked at preflight and at
plan time, and an unknown one fails that model with the closest catalog ids
listed -- a typo like ``NVIDIA A100 80GB`` is one character from a real id and
is worth naming rather than merely rejecting.

The catalog comes from the snapshot ``RunPodPodsClient.catalog_gpus`` writes to
``receipts/provider_receipts/catalog-<ts>.json``. Reading the newest file on
disk keeps validation available to commands that open no socket.
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from arena.provider.runpod_pods import GpuPriceRow, PriceSnapshot
from arena.provider.safety import read_json

__all__ = [
    "MAX_PRICE_SNAPSHOT_AGE_HOURS",
    "GpuPoolError",
    "PoolValidation",
    "latest_price_snapshot_path",
    "load_price_snapshot",
    "snapshot_age_hours",
    "validate_pool",
]

SUGGESTION_COUNT: Final = 3
# ARENA_CONTRACT 11.5 D23: a dry run refuses to price from a snapshot older
# than this; --execute refreshes the catalog live rather than aging one out.
MAX_PRICE_SNAPSHOT_AGE_HOURS: Final = 6.0


class GpuPoolError(RuntimeError):
    """The catalog snapshot cannot be read or does not match the contract."""


@dataclass(frozen=True, slots=True)
class PoolValidation:
    model_key: str
    pool: tuple[str, ...]
    unknown: tuple[str, ...]
    suggestions: Mapping[str, tuple[str, ...]]
    snapshot_sha256: str
    snapshot_path: str | None
    # ARENA_CONTRACT 11.5 D25: catalog memory_gb x gpu_count_min must clear the
    # runtime's gpu_min_vram_gb. Each entry is (gpu_type_id, offered_gb).
    undersized: tuple[tuple[str, int], ...] = ()
    gpu_count_min: int = 1
    gpu_min_vram_gb: int | None = None

    @property
    def ok(self) -> bool:
        # A pool whose every entry is too small is a pod that OOMs at model
        # load. That is a paid failure, not a slow path, so it fails the same
        # gate an unknown GPU id does. A pool with some large-enough entries
        # stays valid -- the provider rents in list order -- and the undersized
        # names are reported rather than silently dropped.
        return not self.unknown and not (
            self.undersized and len(self.undersized) == len(self.pool)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "model_key": self.model_key,
            "gpu_pool_priority": list(self.pool),
            "unknown_gpu_type_ids": list(self.unknown),
            "closest_catalog_ids": {key: list(value) for key, value in self.suggestions.items()},
            "undersized_gpu_type_ids": [
                {"gpu_type_id": name, "offered_gb": offered} for name, offered in self.undersized
            ],
            "gpu_count_min": self.gpu_count_min,
            "gpu_min_vram_gb": self.gpu_min_vram_gb,
            "catalog_snapshot_sha256": self.snapshot_sha256,
            "catalog_snapshot_path": self.snapshot_path,
            "ok": self.ok,
        }

    def failure_lines(self) -> list[str]:
        lines = [
            f"{self.model_key}: gpu_pool_priority names {name!r}, which the catalog snapshot "
            f"{self.snapshot_sha256[:19]} does not carry; closest catalog ids: "
            + (", ".join(self.suggestions.get(name, ())) or "<none within edit distance>")
            for name in self.unknown
        ]
        lines.extend(
            f"{self.model_key}: {name!r} offers {offered} GB x {self.gpu_count_min} GPU(s) = "
            f"{offered * self.gpu_count_min} GB, below the runtime's gpu_min_vram_gb of "
            f"{self.gpu_min_vram_gb} GB (ARENA_CONTRACT 11.5 D25)"
            for name, offered in self.undersized
        )
        return lines


def latest_price_snapshot_path(directory: Path) -> Path | None:
    """The newest ``catalog-*.json`` in ``directory``, or ``None``.

    Names carry a UTC timestamp slug, so lexical order is chronological.
    """

    if not directory.is_dir():
        return None
    snapshots = sorted(directory.glob("catalog-*.json"))
    return snapshots[-1] if snapshots else None


def load_price_snapshot(path: Path) -> PriceSnapshot:
    """Rebuild a :class:`PriceSnapshot` from a persisted catalog receipt."""

    if not path.is_file():
        raise GpuPoolError(
            f"{path} is absent; run `python -m arena.controller preflight --execute`"
        )
    document = read_json(path)
    if not isinstance(document, Mapping):
        raise GpuPoolError(f"{path.name} is not a JSON object")
    rows_raw = document.get("rows")
    if not isinstance(rows_raw, Sequence) or isinstance(rows_raw, str):
        raise GpuPoolError(f"{path.name}.rows is not an array")
    captured = document.get("captured_at")
    if not isinstance(captured, str) or not captured:
        raise GpuPoolError(f"{path.name}.captured_at is missing")
    rows: list[GpuPriceRow] = []
    for index, item in enumerate(rows_raw):
        if not isinstance(item, Mapping):
            raise GpuPoolError(f"{path.name}.rows[{index}] is not an object")
        identifier = item.get("gpu_type_id")
        if not isinstance(identifier, str) or not identifier:
            raise GpuPoolError(f"{path.name}.rows[{index}].gpu_type_id is missing")
        rows.append(
            GpuPriceRow(
                gpu_type_id=identifier,
                display_name=str(item.get("display_name", identifier)),
                memory_gb=_as_int(item.get("memory_gb")),
                secure_available=bool(item.get("secure_available")),
                community_available=bool(item.get("community_available")),
                price_secure_usd_per_hour=_as_rate(item.get("price_secure_usd_per_hour")),
                price_community_usd_per_hour=_as_rate(item.get("price_community_usd_per_hour")),
            )
        )
    if not rows:
        raise GpuPoolError(f"{path.name} carries no catalog rows")
    return PriceSnapshot(captured_at=captured, rows=tuple(rows), path=path)


def validate_pool(
    model_key: str,
    pool: Sequence[str],
    snapshot: PriceSnapshot,
    *,
    gpu_count_min: int = 1,
    gpu_min_vram_gb: int | None = None,
) -> PoolValidation:
    """Every pool name against the snapshot; unknowns carry near matches.

    D25 adds the capacity half. A catalog row whose ``memory_gb`` times the
    runtime's ``gpu_count_min`` is below its ``gpu_min_vram_gb`` cannot hold
    the model, and renting it buys a CUDA_OOM at the model-load step. The
    floor is applied only when the runtime declares one: inventing a VRAM
    requirement would be exactly the fabricated data the constitution bans.
    """

    if gpu_count_min < 1:
        raise GpuPoolError("gpu_count_min must be at least 1")
    catalog = [row.gpu_type_id for row in snapshot.rows]
    known = set(catalog)
    unknown = tuple(name for name in pool if name not in known)
    suggestions = {
        name: tuple(difflib.get_close_matches(name, catalog, n=SUGGESTION_COUNT, cutoff=0.5))
        for name in unknown
    }
    undersized: list[tuple[str, int]] = []
    if gpu_min_vram_gb is not None:
        for name in pool:
            if name in unknown:
                continue
            offered = snapshot.row(name).memory_gb
            if offered * gpu_count_min < gpu_min_vram_gb:
                undersized.append((name, offered))
    return PoolValidation(
        model_key=model_key,
        pool=tuple(pool),
        unknown=unknown,
        suggestions=suggestions,
        snapshot_sha256=snapshot.snapshot_sha256(),
        snapshot_path=None if snapshot.path is None else snapshot.path.name,
        undersized=tuple(undersized),
        gpu_count_min=gpu_count_min,
        gpu_min_vram_gb=gpu_min_vram_gb,
    )


def snapshot_age_hours(snapshot: PriceSnapshot, *, now: datetime) -> float | None:
    """How old the catalog snapshot is (D23). ``None`` when it cannot be read."""

    try:
        captured = datetime.fromisoformat(snapshot.captured_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    return max(0.0, (now - captured).total_seconds() / 3600.0)


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _as_rate(value: object) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
