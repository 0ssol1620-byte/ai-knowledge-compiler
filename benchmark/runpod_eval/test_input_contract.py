from __future__ import annotations

import json
from pathlib import Path

import pytest
from input_contract import adaptive_repeat_indices, select_inference_inputs
from public_core_sources import content_sha256, sha256_file

RUNTIME_SCRIPTS = (
    "paddleocr_vl_stage2.py",
    "mineru_stage2.py",
    "deepseek_ocr2_stage2.py",
    "ovisocr2_stage2.py",
)


def _images(root: Path, count: int) -> None:
    for index in range(count):
        (root / f"page-{index:03d}.png").write_bytes(f"source-only-image-{index}".encode())


def _input_manifest(root: Path, count: int) -> Path:
    inputs = []
    for index in range(count):
        image = root / f"page-{index:03d}.png"
        inputs.append(
            {
                "case_id": f"case-{index:03d}",
                "input_relative_path": image.name,
                "input_sha256": sha256_file(image),
            }
        )
    manifest = {
        "schema": "folynta.public-core-inference-inputs.v1",
        "benchmark_id": "fixture",
        "dataset_revision": "revision-1",
        "ground_truth_mounted": False,
        "source_count": count,
        "input_count": count,
        "complete_source_coverage": True,
        "complete_input_coverage": True,
        "inputs": inputs,
    }
    manifest["content_sha256"] = content_sha256(manifest)
    path = root / "inference-input-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_public_core_requires_full_frozen_inventory(tmp_path: Path) -> None:
    _images(tmp_path, 3)
    manifest = _input_manifest(tmp_path, 3)

    selection = select_inference_inputs(
        input_dir=tmp_path,
        supported_extensions={".png"},
        limit=0,
        evidence_class="public-core",
        expected_input_count=3,
        input_manifest=manifest,
    )

    assert len(selection.selected) == 3
    assert selection.complete_input_coverage is True
    assert selection.benchmark_id == "fixture"
    assert selection.dataset_revision == "revision-1"
    assert selection.input_manifest_sha256 is not None


def test_public_core_accepts_a_relative_input_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    _images(stage, 2)
    manifest = _input_manifest(stage, 2)
    monkeypatch.chdir(tmp_path)

    selection = select_inference_inputs(
        input_dir=Path("stage"),
        supported_extensions={".png"},
        limit=0,
        evidence_class="public-core",
        expected_input_count=2,
        input_manifest=manifest,
    )

    assert len(selection.selected) == 2


@pytest.mark.parametrize(
    ("limit", "expected_input_count", "message"),
    (
        (1, 3, "--limit 0"),
        (0, None, "expected-input-count"),
        (0, 2, "frozen manifest"),
    ),
)
def test_public_core_rejects_partial_or_unbound_inputs(
    tmp_path: Path,
    limit: int,
    expected_input_count: int | None,
    message: str,
) -> None:
    _images(tmp_path, 3)
    manifest = _input_manifest(tmp_path, 3)

    with pytest.raises(ValueError, match=message):
        select_inference_inputs(
            input_dir=tmp_path,
            supported_extensions={".png"},
            limit=limit,
            evidence_class="public-core",
            expected_input_count=expected_input_count,
            input_manifest=manifest,
        )


def test_public_core_rejects_a_tampered_input(tmp_path: Path) -> None:
    _images(tmp_path, 2)
    manifest = _input_manifest(tmp_path, 2)
    (tmp_path / "page-001.png").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="hash does not match"):
        select_inference_inputs(
            input_dir=tmp_path,
            supported_extensions={".png"},
            limit=0,
            evidence_class="public-core",
            expected_input_count=2,
            input_manifest=manifest,
        )


def test_public_core_rejects_manifest_content_tampering(tmp_path: Path) -> None:
    _images(tmp_path, 1)
    manifest = _input_manifest(tmp_path, 1)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["dataset_revision"] = "changed"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="content hash"):
        select_inference_inputs(
            input_dir=tmp_path,
            supported_extensions={".png"},
            limit=0,
            evidence_class="public-core",
            expected_input_count=1,
            input_manifest=manifest,
        )


def test_public_core_shard_is_bound_to_parent_and_exact_local_inventory(
    tmp_path: Path,
) -> None:
    parent_root = tmp_path / "parent"
    parent_root.mkdir()
    _images(parent_root, 3)
    parent_path = _input_manifest(parent_root, 3)
    parent = json.loads(parent_path.read_text(encoding="utf-8"))

    shard_root = tmp_path / "shard"
    shard_root.mkdir()
    for name in ("page-000.png", "page-002.png"):
        (shard_root / name).write_bytes((parent_root / name).read_bytes())
    shard = {
        "schema": "folynta.public-core-inference-shard.v1",
        "benchmark_id": "fixture",
        "dataset_revision": "revision-1",
        "ground_truth_mounted": False,
        "source_count": 3,
        "input_count": 2,
        "complete_source_coverage": False,
        "complete_input_coverage": True,
        "parent_input_manifest_sha256": parent["content_sha256"],
        "shard_index": 0,
        "shard_count": 2,
        "inputs": [parent["inputs"][0], parent["inputs"][2]],
    }
    shard["content_sha256"] = content_sha256(shard)
    shard_path = shard_root / "shard-manifest.json"
    shard_path.write_text(json.dumps(shard), encoding="utf-8")

    selection = select_inference_inputs(
        input_dir=shard_root,
        supported_extensions={".png"},
        limit=0,
        evidence_class="public-core-shard",
        expected_input_count=2,
        input_manifest=shard_path,
        parent_input_manifest=parent_path,
    )

    assert len(selection.selected) == 2
    assert selection.complete_input_coverage is True


def test_smoke_limit_is_explicitly_partial(tmp_path: Path) -> None:
    _images(tmp_path, 3)

    selection = select_inference_inputs(
        input_dir=tmp_path,
        supported_extensions={".png"},
        limit=1,
        evidence_class="smoke",
        expected_input_count=None,
    )

    assert len(selection.selected) == 1
    assert selection.complete_input_coverage is False


@pytest.mark.parametrize(
    ("evidence_class", "repeats", "start", "expected"),
    (
        ("public-core", 1, 1, (1,)),
        ("public-core", 2, 2, (2, 3)),
        ("public-core", 3, 1, (1, 2, 3)),
        ("public-core-shard", 1, 1, (1,)),
        ("stratified-audit", 3, 1, (1, 2, 3)),
    ),
)
def test_adaptive_repeat_shapes_are_explicit(
    evidence_class: str,
    repeats: int,
    start: int,
    expected: tuple[int, ...],
) -> None:
    assert adaptive_repeat_indices(
        evidence_class=evidence_class,
        repeats=repeats,
        repeat_start_index=start,
    ) == expected


@pytest.mark.parametrize(
    ("evidence_class", "repeats", "start"),
    (
        ("public-core", 2, 1),
        ("public-core", 1, 2),
        ("stratified-audit", 1, 1),
        ("stratified-audit", 2, 2),
    ),
)
def test_adaptive_repeat_shapes_reject_partial_or_redundant_work(
    evidence_class: str, repeats: int, start: int
) -> None:
    with pytest.raises(ValueError):
        adaptive_repeat_indices(
            evidence_class=evidence_class,
            repeats=repeats,
            repeat_start_index=start,
        )


@pytest.mark.parametrize("script_name", RUNTIME_SCRIPTS)
def test_every_runtime_exposes_the_full_public_input_contract(script_name: str) -> None:
    script = (Path(__file__).parent / script_name).read_text(encoding="utf-8")

    assert "select_inference_inputs(" in script
    assert '"--evidence-class"' in script
    assert '"--expected-input-count"' in script
    assert '"--input-manifest"' in script
    assert '"--parent-input-manifest"' in script
    assert "input_manifest=args.input_manifest" in script
    assert "parent_input_manifest=args.parent_input_manifest" in script
    assert '"input_manifest_sha256"' in script
    assert '"--repeat-start-index"' in script
    assert 'default=1, choices=(1, 2, 3)' in script
    assert "adaptive_repeat_indices(" in script
    assert '"complete_input_coverage"' in script
    assert '"ground_truth_mounted": False' in script
