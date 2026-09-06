from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import launch_gpu_successor_v2 as launch  # noqa: E402
from common import sha_file  # noqa: E402
from gpu_successor_v2_runtime import V2RuntimeError  # noqa: E402


def _write(path: Path, body: dict) -> Path:
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_provider_rate_receipt_reproduces_fresh_raw_response(tmp_path):
    raw = _write(
        tmp_path / "raw.json",
        {"gpu_type": "NVIDIA H200", "gpu_count": 1, "hourly_rate_usd": 3.5},
    )
    receipt = {
        "schema": "tavonel.runpod.provider_rate_receipt.v1",
        "source_url": "https://api.runpod.io/graphql",
        "observed_at": datetime.now(UTC).isoformat(),
        "provider_response_path": raw.name,
        "provider_response_sha256": sha_file(raw),
        "gpu_type": "NVIDIA H200",
        "hourly_rate_usd": 3.5,
    }
    assert launch._verify_live_rate_receipt(tmp_path / "receipt.json", receipt) == receipt


def test_stale_or_locally_claimed_rate_is_refused(tmp_path):
    raw = _write(
        tmp_path / "raw.json",
        {"gpu_type": "NVIDIA H200", "gpu_count": 1, "hourly_rate_usd": 3.5},
    )
    receipt = {
        "schema": "tavonel.runpod.provider_rate_receipt.v1",
        "source_url": "https://example.invalid/rate",
        "observed_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        "provider_response_path": raw.name,
        "provider_response_sha256": sha_file(raw),
        "gpu_type": "NVIDIA H200",
        "hourly_rate_usd": 3.5,
    }
    with pytest.raises(V2RuntimeError, match="provider API"):
        launch._verify_live_rate_receipt(tmp_path / "receipt.json", receipt)
