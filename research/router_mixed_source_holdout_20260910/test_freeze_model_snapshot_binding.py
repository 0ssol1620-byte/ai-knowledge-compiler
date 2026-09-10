from __future__ import annotations

import json
from pathlib import Path

import pytest

from .freeze_model_snapshot_binding import SnapshotFreezeError, build_snapshot_binding
from .preflight_mixed_holdout import digest


def _runtime(tmp_path: Path) -> tuple[dict[str, object], Path, bytes]:
    model_key = "model_a"
    revision = "a" * 40
    runtime_root = tmp_path / "runtimes"
    runtime_path = runtime_root / model_key / "runtime.json"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        json.dumps(
            {
                "model_key": model_key,
                "model_repo": "owner/model-a",
                "model_revision": revision,
            }
        ),
        encoding="utf-8",
    )
    api = json.dumps(
        {
            "sha": revision,
            "siblings": [
                {
                    "rfilename": "model.safetensors",
                    "lfs": {"sha256": "b" * 64, "size": 99},
                },
                {"rfilename": "config.json", "size": 2},
            ],
        },
        separators=(",", ":"),
    ).encode()
    identity = {
        "models": {
            model_key: {
                "model_revision": revision,
                "runtime_sha256": digest(runtime_path.read_bytes()),
            }
        }
    }
    return identity, runtime_root, api


def test_freezes_official_and_generated_file_denominator(tmp_path: Path) -> None:
    identity, runtime_root, api = _runtime(tmp_path)

    def fetch(url: str, *, maximum_bytes: int) -> bytes:
        assert maximum_bytes > 0
        return api if "/api/models/" in url else b"{}"

    value = build_snapshot_binding(
        identity=identity, runtime_root=runtime_root, fetch=fetch
    )
    model = value["models"]["model_a"]  # type: ignore[index]
    assert model["official_file_count"] == 2  # type: ignore[index]
    files = model["files"]  # type: ignore[index]
    assert [row["relative_path"] for row in files] == [
        "model_a/weights/arena-weights-revision.txt",
        "model_a/weights/config.json",
        "model_a/weights/model.safetensors",
    ]
    assert files[1]["sha256"] == digest(b"{}")


def test_revision_or_runtime_drift_fails_closed(tmp_path: Path) -> None:
    identity, runtime_root, api = _runtime(tmp_path)
    identity["models"]["model_a"]["model_revision"] = "c" * 40  # type: ignore[index]
    with pytest.raises(SnapshotFreezeError, match="RUNTIME_IDENTITY_MISMATCH"):
        build_snapshot_binding(
            identity=identity,
            runtime_root=runtime_root,
            fetch=lambda *_args, **_kwargs: api,
        )


def test_path_traversal_and_duplicate_files_fail_closed(tmp_path: Path) -> None:
    identity, runtime_root, api = _runtime(tmp_path)
    payload = json.loads(api)
    payload["siblings"][0]["rfilename"] = "../escape.bin"
    with pytest.raises(SnapshotFreezeError, match="SNAPSHOT_FILE_PATH_INVALID"):
        build_snapshot_binding(
            identity=identity,
            runtime_root=runtime_root,
            fetch=lambda *_args, **_kwargs: json.dumps(payload).encode(),
        )

    payload["siblings"] = [
        {"rfilename": "same.json", "size": 2},
        {"rfilename": "same.json", "size": 2},
    ]
    with pytest.raises(SnapshotFreezeError, match="API_FILE_DUPLICATE"):
        build_snapshot_binding(
            identity=identity,
            runtime_root=runtime_root,
            fetch=lambda *_args, **_kwargs: json.dumps(payload).encode(),
        )
