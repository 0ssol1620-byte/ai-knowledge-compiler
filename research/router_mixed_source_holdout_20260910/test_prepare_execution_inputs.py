from __future__ import annotations

import json
from pathlib import Path

from .preflight_mixed_holdout import digest
from .prepare_execution_inputs import MODEL_KEYS, build_requests, materialize_models


def test_materialization_and_request_matrix_use_exact_frozen_bytes(
    tmp_path: Path,
) -> None:
    arena = tmp_path / "arena"
    model_root = tmp_path / "models"
    snapshots: dict[str, object] = {}
    for index, model_key in enumerate(MODEL_KEYS, 1):
        revision = str(index) * 40
        runtime = {
            "model_key": model_key,
            "model_repo": f"owner/{model_key}",
            "model_revision": revision,
            "base_image": f"registry.example/{model_key}@sha256:{str(index) * 64}",
            "inference_config": {"temperature": 0, "model": model_key},
        }
        runtime_path = arena / "runtimes" / model_key / "runtime.json"
        runtime_path.parent.mkdir(parents=True)
        runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
        bundle_path = arena / "bundles" / model_key / "arena-bundle.tar.gz"
        bundle_path.parent.mkdir(parents=True)
        bundle_path.write_bytes(f"bundle:{model_key}".encode())
        weight = f"weight:{model_key}".encode()
        weight_relative = f"{model_key}/weights/model.safetensors"
        weight_path = model_root / weight_relative
        weight_path.parent.mkdir(parents=True)
        weight_path.write_bytes(weight)
        revision_relative = f"{model_key}/weights/arena-weights-revision.txt"
        snapshots[model_key] = {
            "repository": f"owner/{model_key}",
            "revision": revision,
            "official_api_url": f"https://huggingface.co/api/models/{model_key}",
            "official_snapshot_descriptor_sha256": "sha256:" + str(index) * 64,
            "official_file_count": 1,
            "files": [
                {
                    "relative_path": revision_relative,
                    "sha256": digest(revision.encode()),
                    "size_bytes": len(revision),
                },
                {
                    "relative_path": weight_relative,
                    "sha256": digest(weight),
                    "size_bytes": len(weight),
                },
            ],
        }

    rows = materialize_models(
        arena_root=arena,
        model_root=model_root,
        snapshot_binding={"models": snapshots},
        download_workers=2,
    )

    assert len(rows) == 3
    assert all((model_root / str(row["runtime_relative_path"])).is_file() for row in rows)
    assert all((model_root / str(row["bundle_relative_path"])).is_file() for row in rows)
    requests = build_requests(
        source_rows=[
            {
                "unit_id": "unit-1",
                "source_sha256": "sha256:" + "a" * 64,
                "target_locator": "page:1",
            }
        ],
        render_rows=[
            {
                "unit_id": "unit-1",
                "render_sha256": "sha256:" + "b" * 64,
            }
        ],
        model_rows=rows,
        router_policy_sha256="sha256:" + "c" * 64,
        model_root=model_root,
    )
    assert len(requests) == 3
    assert {str(row["model_key"]) for row in requests} == set(MODEL_KEYS)
    assert len({str(row["request_id"]) for row in requests}) == 3
