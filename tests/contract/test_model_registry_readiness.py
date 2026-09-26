from __future__ import annotations

import hashlib
import re
import runpy
from pathlib import Path
from typing import Any

_VALIDATOR = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "infra/model-registry/validate_registry.py")
)
release_is_attested = _VALIDATOR["release_is_attested"]
validate = _VALIDATOR["validate"]
verify_revision_source = _VALIDATOR["verify_revision_source"]


def _release() -> dict[str, Any]:
    return {
        "upstream_revision": "a" * 40,
        "licenses": {"license_snapshot_sha256": "sha256:" + ("b" * 64)},
        "runtime": {
            "version": "1.0.0",
            "image_digest": "sha256:" + ("c" * 64),
        },
        "internal_validation": {"status": "canary"},
    }


def test_registry_is_locally_valid_with_gemma_challenger_fail_closed() -> None:
    assert validate() == []


def test_revision_source_digest_is_checked_against_committed_bytes(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text('{"model":"pinned"}', encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(registry.read_bytes()).hexdigest()
    source = {"registry": "registry.json", "registry_sha256": digest}
    assert verify_revision_source(source, tmp_path) is None
    registry.write_text('{"model":"drifted"}', encoding="utf-8")
    assert "digest mismatch" in verify_revision_source(source, tmp_path)
    source["registry"] = "../outside.json"
    assert "outside the repository" in verify_revision_source(source, tmp_path)


def test_second_reader_adr_evidence_paths_and_digests_are_real() -> None:
    root = Path(__file__).resolve().parents[2]
    adr = (root / "docs/adr/ADR-007-element-aware-second-reader.md").read_text(encoding="utf-8")
    evidence = re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", adr, flags=re.MULTILINE)
    assert len(evidence) == 4
    for relative, digest in evidence:
        path = (root / relative).resolve()
        assert path.is_relative_to(root)
        assert path.is_file(), relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, relative


def test_attestation_requires_license_runtime_image_and_internal_status() -> None:
    release = _release()
    assert release_is_attested(release)
    release["licenses"]["license_snapshot_sha256"] = None
    assert not release_is_attested(release)


def test_strict_promotion_still_rejects_unpinned_candidates() -> None:
    errors = validate(strict=True)
    assert errors
    assert any("exact 40-64 hex revision required" in error for error in errors)
