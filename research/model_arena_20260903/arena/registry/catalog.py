"""RunPod GPU catalog observed on 2026-09-03 by the campaign orchestrator.

This is a *price and availability snapshot used for pool ordering only*. It is
not a billing source: the controller (lane B1) writes its own
`receipts/provider_receipts/catalog-<ts>.json` before every provisioning
decision and the cost ledger is computed from that, never from this table.

`gpu_type_id` values are RunPod `gpuTypeId` strings and are the only names the
registry is allowed to emit in `recommended_gpu_pool` / `gpu_pool_priority`.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

Availability = Literal["normal", "low"]

CATALOG_OBSERVED_AT: Final = "2026-09-03"
CATALOG_SOURCE_URL: Final = "https://www.runpod.io/gpu-models"


@dataclass(frozen=True, slots=True)
class RunPodGpu:
    gpu_type_id: str
    vram_gb: int
    usd_per_hour: float
    availability: Availability
    # Compute capability matters for FP8 kernels and for FlashInfer backends.
    architecture: str


_CATALOG: Final = (
    RunPodGpu("NVIDIA GeForce RTX 4090", 24, 0.34, "normal", "ada"),
    RunPodGpu("NVIDIA RTX A6000", 48, 0.33, "normal", "ampere"),
    RunPodGpu("NVIDIA A40", 48, 0.35, "low", "ampere"),
    RunPodGpu("NVIDIA L40S", 48, 0.79, "normal", "ada"),
    RunPodGpu("NVIDIA A100 80GB PCIe", 80, 1.19, "low", "ampere"),
    RunPodGpu("NVIDIA A100-SXM4-80GB", 80, 1.39, "normal", "ampere"),
    RunPodGpu("NVIDIA H100 PCIe", 80, 1.99, "normal", "hopper"),
    RunPodGpu("NVIDIA H100 80GB HBM3", 80, 2.69, "normal", "hopper"),
    RunPodGpu("NVIDIA RTX PRO 6000 Blackwell Server Edition", 96, 1.69, "normal", "blackwell"),
)

RUNPOD_GPU_CATALOG: Final = MappingProxyType({gpu.gpu_type_id: gpu for gpu in _CATALOG})

#: VRAM tiers actually purchasable in the catalog above, ascending.
VRAM_TIERS_GB: Final = (24, 48, 80, 96)


def is_known_gpu(gpu_type_id: str) -> bool:
    return gpu_type_id in RUNPOD_GPU_CATALOG


def catalog_snapshot() -> dict[str, object]:
    """Serializable snapshot embedded in `model_registry.json` for traceability."""
    return {
        "observed_at": CATALOG_OBSERVED_AT,
        "source_url": CATALOG_SOURCE_URL,
        "note": (
            "Pool-ordering reference only. Billing and canary cost projection use the "
            "controller's own provider_receipts catalog snapshot, never this table."
        ),
        "gpus": [
            {
                "gpu_type_id": gpu.gpu_type_id,
                "vram_gb": gpu.vram_gb,
                "usd_per_hour": gpu.usd_per_hour,
                "availability": gpu.availability,
                "architecture": gpu.architecture,
            }
            for gpu in _CATALOG
        ],
    }


__all__ = [
    "CATALOG_OBSERVED_AT",
    "CATALOG_SOURCE_URL",
    "RUNPOD_GPU_CATALOG",
    "VRAM_TIERS_GB",
    "RunPodGpu",
    "catalog_snapshot",
    "is_known_gpu",
]
