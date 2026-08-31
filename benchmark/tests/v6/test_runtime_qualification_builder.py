"""Tests for the D6 anti-fabrication mechanism:
infra/runpod/v6/runtime_smoke_baseline.py and
infra/runpod/v6/build_runtime_qualification.py.

Every evidence file here is synthetic/fabricated, constructed in a pytest
tmp_path directory. Nothing in this file touches a real GPU or a real pod.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.v6.contracts import ContractError
from infra.runpod.v6.build_runtime_qualification import (
    QualificationRefused,
    build_qualification_receipt,
    validate_and_write,
)
from infra.runpod.v6.build_runtime_qualification import main as build_runtime_qualification_main
from infra.runpod.v6.runtime_qualification import BakedRuntimeQualification
from infra.runpod.v6.runtime_smoke_baseline import (
    build_and_seal_baseline,
    build_smoke_baseline,
)

IMAGE_DIGEST = "ghcr.io/tavonel/test-image@sha256:" + "a" * 64
ALT_IMAGE_DIGEST = "ghcr.io/tavonel/test-image@sha256:" + "b" * 64
LINEAGE_TARGET_NAME = "synthetic-target"
WEIGHTS_REVISION = "synthetic-weights-revision-0001"
MODEL_ARTIFACT_SHA256 = "sha256:" + "5" * 64


def _write_markdown_run(root: Path, *, case_id: str, content: str, repeat: int = 1) -> Path:
    repeat_dir = root / f"markdown-repeat-{repeat}"
    repeat_dir.mkdir(parents=True, exist_ok=True)
    (repeat_dir / f"{case_id}.md").write_text(content, encoding="utf-8")
    return root


def _write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# runtime_smoke_baseline.py
# --------------------------------------------------------------------------


def test_passing_baseline_is_deterministic_and_has_a_real_expected_hash(tmp_path: Path) -> None:
    content = "# Case A\n\nSample smoke body text.\n"
    repeat_dirs = tuple(
        _write_markdown_run(tmp_path / f"repeat-{i}", case_id="case-a", content=content)
        for i in (1, 2, 3)
    )
    baseline = build_smoke_baseline(
        repeat_dirs=repeat_dirs,  # type: ignore[arg-type]
        pod_id="baseline-pod",
        started_at="2026-01-01T00:00:00+00:00",
        image_digest=IMAGE_DIGEST,
        sealed_at="2026-01-01T00:10:00+00:00",
    )
    assert baseline["intra_pod_determinism"] is True
    assert baseline["passed"] is True
    assert baseline["established_expected_sha256"] is not None
    assert baseline["established_expected_sha256"].startswith("sha256:")
    assert len(baseline["established_expected_sha256"]) == len("sha256:") + 64


def test_failing_baseline_records_non_determinism_without_majority_vote(tmp_path: Path) -> None:
    matching_content = "# Case A\n\nSample smoke body text.\n"
    differing_content = "# Case A\n\nA DIFFERENT smoke body text.\n"
    repeat_dirs = (
        _write_markdown_run(tmp_path / "repeat-1", case_id="case-a", content=matching_content),
        _write_markdown_run(tmp_path / "repeat-2", case_id="case-a", content=differing_content),
        _write_markdown_run(tmp_path / "repeat-3", case_id="case-a", content=matching_content),
    )
    # Two of three repeats agree (a would-be majority) -- the baseline must
    # still refuse to resolve this via majority vote.
    baseline = build_smoke_baseline(
        repeat_dirs=repeat_dirs,
        pod_id="baseline-pod",
        started_at="2026-01-01T00:00:00+00:00",
        image_digest=IMAGE_DIGEST,
    )
    assert baseline["intra_pod_determinism"] is False
    assert baseline["passed"] is False
    assert baseline["established_expected_sha256"] is None


def test_resealing_an_existing_baseline_path_raises_file_exists_error(tmp_path: Path) -> None:
    content = "# Case A\n\nSample smoke body text.\n"
    repeat_dirs = tuple(
        _write_markdown_run(tmp_path / f"repeat-{i}", case_id="case-a", content=content)
        for i in (1, 2, 3)
    )
    output_path = tmp_path / "baseline.json"
    build_and_seal_baseline(
        repeat_dirs=repeat_dirs,  # type: ignore[arg-type]
        pod_id="baseline-pod",
        started_at="2026-01-01T00:00:00+00:00",
        image_digest=IMAGE_DIGEST,
        output_path=output_path,
    )
    with pytest.raises(FileExistsError):
        build_and_seal_baseline(
            repeat_dirs=repeat_dirs,  # type: ignore[arg-type]
            pod_id="baseline-pod-2",
            started_at="2026-01-02T00:00:00+00:00",
            image_digest=IMAGE_DIGEST,
            output_path=output_path,
        )


# --------------------------------------------------------------------------
# build_runtime_qualification.py -- 6 individual refusal paths
# --------------------------------------------------------------------------


def _valid_baseline_dict(**overrides: object) -> dict:
    base = {
        "schema": "folynta.baked-runtime-smoke-baseline.v1",
        "baseline_run_id": "baseline-pod@2026-01-01T00:00:00+00:00",
        "image_digest": IMAGE_DIGEST,
        "repeat_sha256": ["sha256:" + "7" * 64] * 3,
        "intra_pod_determinism": True,
        "established_expected_sha256": "sha256:" + "7" * 64,
        "passed": True,
        "sealed_at": "2026-01-01T00:10:00+00:00",
    }
    base.update(overrides)
    return base


def _refusal_kwargs(tmp_path: Path, baseline_path: Path, **overrides: object) -> dict:
    kwargs: dict = {
        "baseline_receipt_path": baseline_path,
        "validation_run_id": "validation-pod@2026-01-15T00:00:00+00:00",
        "validation_started_at": "2026-01-15T00:00:00+00:00",
        "validation_image_digest": IMAGE_DIGEST,
        "validation_markdown_dir": tmp_path / "does-not-exist",
        "smoke_input_path": tmp_path / "does-not-exist.png",
        "build_receipt_path": tmp_path / "does-not-exist-build-receipt.json",
        "runtime_identity_path": tmp_path / "does-not-exist-runtime-identity.json",
        "lineage_path": tmp_path / "does-not-exist-lineage.json",
        "lineage_target": LINEAGE_TARGET_NAME,
        "baked_runtime_file_sha256": "sha256:" + "6" * 64,
    }
    kwargs.update(overrides)
    return kwargs


def test_refusal_missing_baseline_receipt(tmp_path: Path) -> None:
    kwargs = _refusal_kwargs(tmp_path, tmp_path / "no-such-baseline.json")
    with pytest.raises(QualificationRefused, match="missing or unreadable"):
        build_qualification_receipt(**kwargs)


def test_refusal_baseline_passed_not_true(tmp_path: Path) -> None:
    baseline_path = _write_json(tmp_path / "baseline.json", _valid_baseline_dict(passed=False))
    kwargs = _refusal_kwargs(tmp_path, baseline_path)
    with pytest.raises(QualificationRefused, match=r"baseline\.passed is not true"):
        build_qualification_receipt(**kwargs)


def test_refusal_intra_pod_determinism_not_true(tmp_path: Path) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json", _valid_baseline_dict(intra_pod_determinism=False)
    )
    kwargs = _refusal_kwargs(tmp_path, baseline_path)
    with pytest.raises(QualificationRefused, match="intra_pod_determinism is not true"):
        build_qualification_receipt(**kwargs)


def test_refusal_baseline_run_id_equals_validation_run_id(tmp_path: Path) -> None:
    same_id = "same-pod@2026-01-01T00:00:00+00:00"
    baseline_path = _write_json(
        tmp_path / "baseline.json", _valid_baseline_dict(baseline_run_id=same_id)
    )
    kwargs = _refusal_kwargs(tmp_path, baseline_path, validation_run_id=same_id)
    with pytest.raises(QualificationRefused, match="genuinely different"):
        build_qualification_receipt(**kwargs)


def test_refusal_baseline_sealed_after_validation_started(tmp_path: Path) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json",
        _valid_baseline_dict(sealed_at="2026-02-01T00:00:00+00:00"),
    )
    kwargs = _refusal_kwargs(
        tmp_path, baseline_path, validation_started_at="2026-01-15T00:00:00+00:00"
    )
    with pytest.raises(QualificationRefused, match="sealed at or after validation start"):
        build_qualification_receipt(**kwargs)


def test_refusal_image_digest_mismatch(tmp_path: Path) -> None:
    baseline_path = _write_json(
        tmp_path / "baseline.json", _valid_baseline_dict(image_digest=IMAGE_DIGEST)
    )
    kwargs = _refusal_kwargs(tmp_path, baseline_path, validation_image_digest=ALT_IMAGE_DIGEST)
    with pytest.raises(QualificationRefused, match="does not match validation_image_digest"):
        build_qualification_receipt(**kwargs)


# --------------------------------------------------------------------------
# build_runtime_qualification.py -- full success and mismatch paths
# --------------------------------------------------------------------------


def _write_full_evidence(
    tmp_path: Path,
    *,
    validation_content: str,
    label: str,
) -> dict:
    """Writes a complete, self-consistent, synthetic evidence set. Returns the
    kwargs for build_qualification_receipt, all pointed at real files.
    """

    baseline_content = "# Case A\n\nSample smoke body text.\n"
    baseline_repeat_dirs = tuple(
        _write_markdown_run(
            tmp_path / f"{label}-baseline-repeat-{i}", case_id="case-a", content=baseline_content
        )
        for i in (1, 2, 3)
    )
    baseline_output = tmp_path / f"{label}-baseline.json"
    build_and_seal_baseline(
        repeat_dirs=baseline_repeat_dirs,  # type: ignore[arg-type]
        pod_id=f"{label}-baseline-pod",
        started_at="2026-01-01T00:00:00+00:00",
        image_digest=IMAGE_DIGEST,
        output_path=baseline_output,
        sealed_at="2026-01-01T00:10:00+00:00",
    )

    validation_dir = _write_markdown_run(
        tmp_path / f"{label}-validation", case_id="case-a", content=validation_content
    )

    smoke_input_path = tmp_path / f"{label}-smoke-input.bin"
    smoke_input_path.write_bytes(b"synthetic smoke input bytes, not a real image")

    build_receipt_path = _write_json(
        tmp_path / f"{label}-build-receipt.json",
        {
            "source_commit": "d" * 40,
            "source_tree_sha256": "sha256:" + "1" * 64,
            "dockerfile_sha256": "sha256:" + "2" * 64,
            "image_digest": IMAGE_DIGEST,
            "sbom_sha256": "sha256:" + "3" * 64,
            "vulnerability_scan_sha256": "sha256:" + "4" * 64,
            "critical_vulnerability_count": 0,
            "model_revision": WEIGHTS_REVISION,
            "model_artifact_sha256": MODEL_ARTIFACT_SHA256,
        },
    )
    runtime_identity_path = _write_json(
        tmp_path / f"{label}-runtime-identity.json",
        {"gpu_type": "NVIDIA A40", "cuda_version": "12.4", "framework_version": "test-fw-1.0.0"},
    )
    lineage_path = _write_json(
        tmp_path / f"{label}-lineage.json",
        {
            "targets": {
                LINEAGE_TARGET_NAME: {
                    "weights_revision": WEIGHTS_REVISION,
                    "artifact_sha256": MODEL_ARTIFACT_SHA256,
                }
            }
        },
    )

    return {
        "baseline_receipt_path": baseline_output,
        "validation_run_id": f"{label}-validation-pod@2026-01-02T00:00:00+00:00",
        "validation_started_at": "2026-01-02T00:00:00+00:00",
        "validation_image_digest": IMAGE_DIGEST,
        "validation_markdown_dir": validation_dir,
        "smoke_input_path": smoke_input_path,
        "build_receipt_path": build_receipt_path,
        "runtime_identity_path": runtime_identity_path,
        "lineage_path": lineage_path,
        "lineage_target": LINEAGE_TARGET_NAME,
        "baked_runtime_file_sha256": "sha256:" + "6" * 64,
    }


def test_full_success_path_round_trips_through_the_real_frozen_validator(tmp_path: Path) -> None:
    matching_content = "# Case A\n\nSample smoke body text.\n"
    kwargs = _write_full_evidence(tmp_path, validation_content=matching_content, label="ok")

    receipt = build_qualification_receipt(**kwargs)
    assert receipt["passed"] is True
    assert receipt["identity_verified"] is True
    assert receipt["model_artifact_verified"] is True
    assert receipt["smoke_passed"] is True
    assert receipt["smoke_prediction_sha256"] == receipt["smoke_expected_sha256"]

    output_path = tmp_path / "ok-qualification.json"
    qualification = validate_and_write(receipt, output_path)
    assert isinstance(qualification, BakedRuntimeQualification)
    assert qualification.passed is True

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["passed"] is True


def test_mismatched_validation_markdown_is_rejected_by_the_frozen_validator_not_forced(
    tmp_path: Path,
) -> None:
    different_content = "# Case A\n\nThis validation run produced DIFFERENT output.\n"
    kwargs = _write_full_evidence(tmp_path, validation_content=different_content, label="mismatch")

    # Building the receipt does not itself raise -- it only computes booleans.
    receipt = build_qualification_receipt(**kwargs)
    assert receipt["smoke_passed"] is False
    assert receipt["passed"] is False
    assert receipt["smoke_prediction_sha256"] != receipt["smoke_expected_sha256"]
    # smoke_expected_sha256 must still be exactly the baseline's value -- never
    # silently substituted with the (mismatching) observed prediction.
    baseline = json.loads(kwargs["baseline_receipt_path"].read_text(encoding="utf-8"))
    assert receipt["smoke_expected_sha256"] == baseline["established_expected_sha256"]

    # The frozen contract's own exact-match gate is the one that refuses it.
    with pytest.raises(ContractError, match="does not match expected"):
        BakedRuntimeQualification.from_mapping(receipt)


# --------------------------------------------------------------------------
# Structural anti-fabrication checks
# --------------------------------------------------------------------------


def test_cli_has_no_expected_sha256_or_force_passed_style_argument() -> None:
    parser = build_runtime_qualification_main.__globals__["_parser"]()
    # argparse has no public API to enumerate an existing parser's actions.
    option_strings = {
        option_string
        for action in parser._actions
        for option_string in action.option_strings
    }
    forbidden_fragments = ("expected-sha256", "smoke-expected", "force-passed")
    for option_string in option_strings:
        lowered = option_string.lower()
        for fragment in forbidden_fragments:
            assert fragment not in lowered, f"found forbidden-shaped CLI argument: {option_string}"


def test_neither_d6_module_reads_an_environment_variable() -> None:
    import infra.runpod.v6.build_runtime_qualification as build_module
    import infra.runpod.v6.runtime_smoke_baseline as baseline_module

    for module in (build_module, baseline_module):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "os.environ" not in source
        assert "getenv" not in source
