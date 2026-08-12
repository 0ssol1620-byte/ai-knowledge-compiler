from __future__ import annotations

import json
import zipfile
from pathlib import Path

from benchmark.runpod_eval.package_public_benchmark_review import (
    GENERATED_PREFIXES,
    SOURCE_NAMES,
    SOURCE_PATHS,
    package_review,
)


def test_review_zip_includes_explicit_infra_algorithm_sources(tmp_path: Path) -> None:
    (tmp_path / "benchmark/reports/generated").mkdir(parents=True)
    (tmp_path / "benchmark/runpod_eval").mkdir(parents=True)
    (tmp_path / "benchmark/v6").mkdir(parents=True)
    (tmp_path / "tools/release").mkdir(parents=True)
    for relative in SOURCE_PATHS:
        source = tmp_path / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    output = tmp_path / "review.zip"

    receipt = package_review(repository=tmp_path, output_zip=output)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("REVIEW_PACKAGE_MANIFEST.json"))
    assert set(SOURCE_PATHS) <= names
    assert set(SOURCE_PATHS) <= {item["path"] for item in manifest["files"]}
    assert receipt["secret_free_policy"] == manifest["secret_free_policy"]
    assert "private" in str(receipt["secret_free_policy"])


def test_review_zip_contract_includes_patent_and_paper_artifact_sources() -> None:
    assert "folynta-patent-paper-artifacts-2026-08-05" in GENERATED_PREFIXES
    assert "folynta-operational-recovery-round2-2026-08-05" in GENERATED_PREFIXES
    assert "folynta-service-recovery-runtime-2026-08-06" in GENERATED_PREFIXES
    assert "build_patent_paper_artifacts.py" in SOURCE_NAMES
    assert "test_build_patent_paper_artifacts.py" in SOURCE_NAMES
    assert "tools/release/deliver_folynta_portable_report.mjs" in SOURCE_PATHS
