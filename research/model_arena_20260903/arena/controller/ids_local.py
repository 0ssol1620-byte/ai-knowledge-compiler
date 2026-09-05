"""Identifier derivation (ARENA_CONTRACT section 2 / masterplan section 9).

Lane A1 owns ``arena.core.ids``. It is built in parallel with this lane, so the
rule is implemented here too and the two are reconciled at import time:

- if ``arena.core.ids`` exists, it is authoritative and this module delegates;
- if it does not, the local implementation is used and :func:`ids_source`
  reports that, so every receipt says which derivation produced its ids.

That is a declared fallback, not a silent one. If lane A1 later disagrees with
this implementation for the same inputs, :func:`ids_source` plus the recorded
job ids make the disagreement visible instead of invisible.
"""

from __future__ import annotations

import hashlib
from typing import Final, Protocol, cast

from arena.provider.safety import canonical_json_bytes

__all__ = [
    "IDS_SOURCE_CORE",
    "IDS_SOURCE_LOCAL",
    "ids_source",
    "inference_job_id",
    "recovery_job_id",
    "shard_id",
    "worker_id",
]

IDS_SOURCE_CORE: Final = "arena.core.ids"
IDS_SOURCE_LOCAL: Final = "arena.controller.ids_local"


class _CoreIds(Protocol):  # pragma: no cover - structural check only
    def inference_job_id(
        self,
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
    ) -> str: ...


def _core() -> _CoreIds | None:
    try:
        from arena.core import ids as core_ids
    except ImportError:
        return None
    if not hasattr(core_ids, "inference_job_id"):
        return None
    return cast("_CoreIds", core_ids)


def ids_source() -> str:
    """Which module derived the ids in this process. Recorded in receipts."""

    return IDS_SOURCE_LOCAL if _core() is None else IDS_SOURCE_CORE


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
    """Lowercase hex sha256 of the canonical JSON of exactly nine fields."""

    core = _core()
    if core is not None:
        return core.inference_job_id(
            campaign_id=campaign_id,
            benchmark_revision=benchmark_revision,
            sample_id=sample_id,
            source_sha256=source_sha256,
            model_repo=model_repo,
            model_revision=model_revision,
            runtime_image_digest=runtime_image_digest,
            prompt_sha256=prompt_sha256,
            inference_config_sha256=inference_config_sha256,
        )
    payload = {
        "campaign_id": campaign_id,
        "benchmark_revision": benchmark_revision,
        "sample_id": sample_id,
        "source_sha256": source_sha256,
        "model_repo": model_repo,
        "model_revision": model_revision,
        "runtime_image_digest": runtime_image_digest,
        "prompt_sha256": prompt_sha256,
        "inference_config_sha256": inference_config_sha256,
    }
    for key, value in payload.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"inference_job_id field {key!r} must be a non-empty string")
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def recovery_job_id(
    *,
    campaign_id: str,
    inference_job_id_of_base: str,
    recovery_type: str,
    recovery_config_sha256: str,
    round_index: int,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "campaign_id": campaign_id,
                "inference_job_id_of_base": inference_job_id_of_base,
                "recovery_type": recovery_type,
                "recovery_config_sha256": recovery_config_sha256,
                "round": round_index,
            }
        )
    ).hexdigest()


def shard_id(model_key: str, benchmark: str, index: int) -> str:
    """``<model_key>-<benchmark>-<zero-padded index>``."""

    if index < 0:
        raise ValueError("shard index must be non-negative")
    return f"{model_key}-{benchmark}-{index:04d}"


def worker_id(model_key: str, index: int, pod_id: str) -> str:
    """``<model_key>-w<index>-<pod_id>``."""

    if index < 0:
        raise ValueError("worker index must be non-negative")
    if not pod_id:
        raise ValueError("worker_id requires a pod id")
    return f"{model_key}-w{index}-{pod_id}"


def runtime_image_digest_for_bootstrap(runtime_bundle_sha256: str) -> str:
    """``bootstrap:<runtime_bundle_sha256>`` (ARENA_CONTRACT section 2)."""

    if not runtime_bundle_sha256:
        raise ValueError("a bootstrap runtime digest needs the bundle hash")
    return f"bootstrap:{runtime_bundle_sha256}"
