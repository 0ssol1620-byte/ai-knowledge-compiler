from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from benchmark.run_benchmark import main as run_benchmark_main
from benchmark.runners.base import RunnerUnavailable, build_provider_payload
from benchmark.runners.registry import EXTERNAL_RUNNERS

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _real_case(payload: bytes, *, path: str = "document.pdf") -> dict[str, object]:
    return {
        "benchmark_case_id": "approved-real-001",
        "document_id": "urn:akmp:doc:approved-real-001",
        "page_index": 0,
        "language": "ko",
        "document_class": "ko_scan",
        "high_risk": False,
        "text": "secret ground truth must not leave the evaluator",
        "reading_order": ["expected"],
        "blocks": [],
        "generated_claims": [],
        "is_synthetic": False,
        "source": {
            "path": path,
            "filename": "document.pdf",
            "content_type": "application/pdf",
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
    }


def test_real_provider_payload_excludes_ground_truth_and_binds_source() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        source = b"immutable approved corpus bytes"
        (root / "document.pdf").write_bytes(source)

        payload = build_provider_payload(_real_case(source), corpus_root=root)

    encoded = json.dumps(payload, sort_keys=True)
    assert "secret ground truth" not in encoded
    assert "reading_order" not in encoded
    assert "generated_claims" not in encoded
    assert base64.b64decode(payload["source"]["bytes_base64"]) == source
    assert payload["source"]["sha256"] == hashlib.sha256(source).hexdigest()


def test_real_provider_payload_rejects_traversal_and_hash_mismatch() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        source = b"approved"
        (root / "document.pdf").write_bytes(source)
        with pytest.raises(RunnerUnavailable, match="unsafe"):
            build_provider_payload(_real_case(source, path="../document.pdf"), corpus_root=root)
        case = _real_case(source)
        case["source"]["sha256"] = "0" * 64
        with pytest.raises(RunnerUnavailable, match="SHA-256"):
            build_provider_payload(case, corpus_root=root)


def test_external_cli_dispatches_registered_adapter_without_claiming_quality() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        truth = root / "truth.jsonl"
        truth.write_text(
            (REPOSITORY_ROOT / "benchmark" / "ground-truth" / "synthetic-v1.jsonl").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        output = root / "scores.jsonl"
        raw = root / "raw"
        revision = "a" * 40

        def fake_runner(
            case: dict[str, object],
            *,
            endpoint: str,
            revision: str,
            allow_network: bool,
        ) -> dict[str, object]:
            assert endpoint == "https://provider.example/v1/parse"
            assert allow_network is True
            return {
                "schema_version": "1.0",
                "benchmark_case_id": case["benchmark_case_id"],
                "provider": "paddleocr_vl_1_6",
                "model_revision": revision,
                "text": case["synthetic_fixture"]["text"],
                "reading_order": [],
                "blocks": [],
                "generated_claims": [],
                "metrics": {},
                "warnings": ["synthetic_contract_result_not_for_quality_claims"],
            }

        arguments = [
            "run_benchmark.py",
            "--ground-truth",
            str(truth),
            "--provider",
            "paddleocr_vl_1_6",
            "--raw-output-dir",
            str(raw),
            "--endpoint",
            "https://provider.example/v1/parse",
            "--model-revision",
            revision,
            "--allow-network",
            "--output",
            str(output),
        ]
        with (
            patch.dict(EXTERNAL_RUNNERS, {"paddleocr_vl_1_6": fake_runner}),
            patch.object(sys, "argv", arguments),
        ):
            assert run_benchmark_main() == 0

        records = [
            json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line
        ]
        assert records
        assert {record["claim_class"] for record in records} == {"contract_test"}
        assert all(record["is_synthetic"] is True for record in records)


def test_external_cli_requires_explicit_network_authority() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        truth = root / "truth.jsonl"
        truth.write_text(
            '{"benchmark_case_id":"x","is_synthetic":true}\n',
            encoding="utf-8",
        )
        arguments = [
            "run_benchmark.py",
            "--ground-truth",
            str(truth),
            "--provider",
            "paddleocr_vl_1_6",
            "--raw-output-dir",
            str(root / "raw"),
            "--endpoint",
            "https://provider.example/v1/parse",
            "--model-revision",
            "a" * 40,
            "--output",
            str(root / "scores.jsonl"),
        ]
        with patch.object(sys, "argv", arguments), pytest.raises(SystemExit) as exc_info:
            run_benchmark_main()
        assert exc_info.value.code == 2
