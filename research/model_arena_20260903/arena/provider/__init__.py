"""Provider adapters for the model arena (lane B1).

Three external surfaces live here and nowhere else:

- ``secrets`` reads credential material and wraps it so it cannot be printed,
  logged or serialized by accident.
- ``runpod_pods`` speaks RunPod REST v2 for GPU pods, catalog and billing.
- ``r2`` speaks Cloudflare R2 (S3) for the worker/runtime bundle transport.
- ``worker_client`` speaks the ARENA_CONTRACT section 4 worker HTTP API.

Every one of them is dry-run by default: without ``execute=True`` they build
and hash the request they *would* have made and return a receipt instead.
"""

from __future__ import annotations

__all__ = ["r2", "runpod_pods", "safety", "secrets", "worker_client"]
