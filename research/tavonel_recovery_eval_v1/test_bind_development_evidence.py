from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from bind_development_evidence import EvidenceBindingRefused, bind_claims


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def make_pack(tmp_path: Path, *, digest_override: str | None = None) -> tuple[Path, Path]:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    evidence = artifacts / "metric.json"
    evidence.write_text('{"value": 1}\n', encoding="utf-8")
    pack = tmp_path / "claims.json"
    pack.write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "metric",
                        "status": "approved",
                        "evidence": "metric.json",
                        "evidence_sha256": digest_override or sha(evidence),
                    },
                    {
                        "id": "not-approved",
                        "status": "withheld",
                        "evidence": "missing.json",
                        "evidence_sha256": "sha256:" + "0" * 64,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return pack, artifacts


def test_binds_only_approved_claims_to_exact_bytes(tmp_path: Path) -> None:
    pack, artifacts = make_pack(tmp_path)
    receipt = bind_claims(pack, artifacts)
    assert receipt["approved_claims_bound"] == 1
    assert receipt["claims"][0]["claim_id"] == "metric"
    assert receipt["confirmatory_eligible"] is False
    assert receipt["claims"][0]["status"] == "HISTORICAL_DEVELOPMENT_ONLY"


def test_digest_mismatch_refuses(tmp_path: Path) -> None:
    pack, artifacts = make_pack(tmp_path, digest_override="sha256:" + "f" * 64)
    with pytest.raises(EvidenceBindingRefused, match="digest mismatch"):
        bind_claims(pack, artifacts)


def test_missing_approved_artifact_refuses(tmp_path: Path) -> None:
    pack, artifacts = make_pack(tmp_path)
    evidence = artifacts / "metric.json"
    evidence.unlink()
    with pytest.raises(EvidenceBindingRefused, match="evidence absent"):
        bind_claims(pack, artifacts)


def test_path_escape_refuses(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    pack = tmp_path / "claims.json"
    pack.write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "escape",
                        "status": "approved",
                        "evidence": "../outside.json",
                        "evidence_sha256": sha(outside),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(EvidenceBindingRefused, match="unsafe evidence path"):
        bind_claims(pack, artifacts)
