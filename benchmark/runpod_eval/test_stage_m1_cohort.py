from __future__ import annotations

import json
from pathlib import Path

import yaml
from stage_m1_cohort import main


def test_stage_requires_six_source_only_cases(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    cases = []
    for index in range(6):
        filename = f"page-{index}.jpg"
        (source / filename).write_bytes(f"page-{index}".encode())
        cases.append({"family": f"family-{index}", "filename": filename})
    cohort = tmp_path / "cohort.yaml"
    cohort.write_text(
        yaml.safe_dump(
            {
                "cohort_id": "test",
                "source_license": "test",
                "ground_truth_in_inference_bundle": False,
                "cases": cases,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage_m1_cohort.py",
            "--cohort",
            str(cohort),
            "--source-images",
            str(source),
            "--output",
            str(output),
        ],
    )
    main()
    manifest = json.loads((output / "inference-manifest.json").read_text())
    assert manifest["case_count"] == 6
    assert manifest["ground_truth_mounted"] is False
    assert not any("ground" in path.name for path in output.rglob("*"))
