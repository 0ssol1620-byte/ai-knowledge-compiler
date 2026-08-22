from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.release.monitor_folynta_live_campaign import (
    read_deleted_workers,
    read_runpod_key,
    ssh_complete,
    ssh_cuda_health,
    validate_receipt,
)


def test_read_runpod_key_accepts_labeled_secret(tmp_path: Path) -> None:
    credentials = tmp_path / "credentials.txt"
    credentials.write_text("Github: ignored\nRunpod: " + "r" * 32 + "\n", encoding="utf-8")

    assert read_runpod_key(credentials) == "r" * 32


def test_validate_receipt_proves_exact_terminal_accounting(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "worker_index": 4,
                "archive_sha256": "sha256:" + "a" * 64,
                "summaries": [
                    {
                        "benchmark_id": "parsebench",
                        "input_count": 3,
                        "completed": 2,
                        "failed": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    worker = {"worker_index": 4, "suites": {"parsebench": 3}}

    assert validate_receipt(receipt, worker)["worker_index"] == 4


def test_validate_receipt_accepts_collector_summary_mapping(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "worker_index": 4,
                "archive_sha256": "sha256:" + "a" * 64,
                "summaries": {
                    "parsebench": {
                        "input_count": 3,
                        "completed": 2,
                        "failed": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    worker = {"worker_index": 4, "suites": {"parsebench": 3}}

    assert validate_receipt(receipt, worker)["worker_index"] == 4


def test_read_deleted_workers_matches_index_and_pod_id(tmp_path: Path) -> None:
    progress = tmp_path / "progress.jsonl"
    progress.write_text(
        "not-json\n"
        + json.dumps(
            {
                "event": "worker_pod_deleted",
                "worker_index": 3,
                "pod_id": "old-pod",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert read_deleted_workers(progress) == {(3, "old-pod")}


def test_validate_receipt_rejects_incomplete_terminal_accounting(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "worker_index": 4,
                "archive_sha256": "sha256:" + "a" * 64,
                "summaries": [
                    {
                        "benchmark_id": "parsebench",
                        "input_count": 3,
                        "completed": 1,
                        "failed": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    worker = {"worker_index": 4, "suites": {"parsebench": 3}}

    with pytest.raises(RuntimeError, match="terminal accounting differs"):
        validate_receipt(receipt, worker)


def test_cuda_health_requires_torch_cuda_not_only_nvidia_smi(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert isinstance(kwargs["input"], bytes)
        assert b"torch.cuda.is_available" in kwargs["input"]
        assert b"\r\n" not in kwargs["input"]
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout=b"NVIDIA GeForce RTX 5090\n",
            stderr=b"torch-cuda-unavailable\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    healthy, detail = ssh_cuda_health(
        {"host": "example.invalid", "port": 22},
        key=tmp_path / "key",
        known_hosts=tmp_path / "known_hosts",
    )

    assert healthy is False
    assert "torch-cuda-unavailable" in detail


def test_ssh_complete_sends_lf_only_bytes_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        payload = kwargs["input"]
        assert isinstance(payload, bytes)
        assert b"set -euo pipefail\n" in payload
        assert b"\r\n" not in payload
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=b"complete",
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert ssh_complete(
        {
            "host": "example.invalid",
            "port": 22,
            "mode": "operational-retry",
            "remote_result_root": "/workspace/results",
            "suites": {"parsebench": 3},
        },
        key=tmp_path / "key",
        known_hosts=tmp_path / "known_hosts",
    )
