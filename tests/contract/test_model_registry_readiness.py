from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

_VALIDATOR = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "infra/model-registry/validate_registry.py")
)
release_is_attested = _VALIDATOR["release_is_attested"]
validate = _VALIDATOR["validate"]


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


def test_attestation_requires_license_runtime_image_and_internal_status() -> None:
    release = _release()
    assert release_is_attested(release)
    release["licenses"]["license_snapshot_sha256"] = None
    assert not release_is_attested(release)


def test_strict_promotion_still_rejects_unpinned_candidates() -> None:
    errors = validate(strict=True)
    assert errors
    assert any("exact 40-64 hex revision required" in error for error in errors)
