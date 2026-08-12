from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.v6.public_failure_adapter import PUBLIC_FAILURE_RULES
from tools.release.verify_folynta_public_failure_adapters import (
    verify_public_failure_adapters,
)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    parse_root = tmp_path / "parse"
    parse_root.mkdir()
    parse_types = sorted(PUBLIC_FAILURE_RULES["parsebench"])
    files = (
        "chart.jsonl",
        "layout.jsonl",
        "table.jsonl",
        "text_content.jsonl",
        "text_formatting.jsonl",
    )
    partitions = [parse_types[index:: len(files)] for index in range(len(files))]
    for filename, evaluator_types in zip(files, partitions, strict=True):
        (parse_root / filename).write_text(
            "".join(json.dumps({"type": value}) + "\n" for value in evaluator_types),
            encoding="utf-8",
        )

    olm_root = tmp_path / "olm"
    olm_data = olm_root / "bench_data"
    olm_data.mkdir(parents=True)
    (olm_data / "tests.jsonl").write_text(
        "".join(
            json.dumps({"type": value}) + "\n"
            for value in sorted(PUBLIC_FAILURE_RULES["olmocr-bench"])
        ),
        encoding="utf-8",
    )

    omni_config = tmp_path / "end2end.yaml"
    omni_types = sorted(set(PUBLIC_FAILURE_RULES["omnidocbench"]) - {"missing_page"})
    omni_config.write_text(
        "end2end_eval:\n  metrics:\n"
        + "".join(f"    {value}: {{}}\n" for value in omni_types),
        encoding="utf-8",
    )

    acquisition = {
        "gate": "PASS",
        "receipt_sha256": "sha256:" + "a" * 64,
        "datasets": [
            {
                "benchmark_id": benchmark_id,
                "dataset_revision": benchmark_id + "-revision",
                "passed": True,
            }
            for benchmark_id in PUBLIC_FAILURE_RULES
        ],
    }
    acquisition_path = tmp_path / "acquisition.json"
    acquisition_path.write_text(json.dumps(acquisition), encoding="utf-8")
    return acquisition_path, omni_config, parse_root, olm_root


def test_verifier_binds_every_official_type(tmp_path: Path) -> None:
    acquisition, omni, parse, olm = _fixture(tmp_path)

    receipt = verify_public_failure_adapters(
        acquisition_receipt=acquisition,
        omnidoc_config=omni,
        parsebench_root=parse,
        olmocr_root=olm,
    )

    assert receipt["gate"] == "PASS"
    assert [item["evaluator_type_count"] for item in receipt["datasets"]] == [5, 26, 6]
    assert str(receipt["receipt_sha256"]).startswith("sha256:")


def test_verifier_rejects_a_new_unmapped_official_type(tmp_path: Path) -> None:
    acquisition, omni, parse, olm = _fixture(tmp_path)
    path = parse / "chart.jsonl"
    path.write_text(
        path.read_text(encoding="utf-8") + json.dumps({"type": "future_rule"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"missing=\['future_rule'\]"):
        verify_public_failure_adapters(
            acquisition_receipt=acquisition,
            omnidoc_config=omni,
            parsebench_root=parse,
            olmocr_root=olm,
        )
