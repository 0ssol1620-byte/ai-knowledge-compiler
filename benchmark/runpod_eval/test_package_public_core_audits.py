import json
from pathlib import Path

import pytest
from package_public_core_audits import package_audits


def test_package_audits_rejects_incomplete_staging_receipt(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "audit-staging-receipt.json").write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-stratified-audit-staging.v1",
                "ground_truth_mounted": False,
                "input_count": 383,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="staging receipt"):
        package_audits(staging_root=staging, output_root=tmp_path / "packages")
