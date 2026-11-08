from __future__ import annotations

import importlib.util
import json
from pathlib import Path, PurePosixPath

REPOSITORY = Path(__file__).resolve().parents[3]
SCRIPT = REPOSITORY / "infra/product-core/vercel/stage_release.py"


def _load_stage_release():
    spec = importlib.util.spec_from_file_location("stage_product_core_vercel_release", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.stage_release


def test_staged_vercel_release_is_minimal_and_deterministic(tmp_path: Path) -> None:
    stage_release = _load_stage_release()
    first = stage_release(REPOSITORY, tmp_path / "first")
    second = stage_release(REPOSITORY, tmp_path / "second")

    assert first == second
    assert first["sourceDigest"].startswith("sha256:")
    paths = {row["path"] for row in first["files"]}
    assert "api/index.py" in paths
    assert "vendor/akc_product_core/semantics.py" in paths
    assert not any(
        PurePosixPath(path).name.startswith("test_") or "__pycache__" in PurePosixPath(path).parts
        for path in paths
    )

    written = json.loads((tmp_path / "first/release-manifest.json").read_text("utf-8"))
    assert written == first


def test_stage_release_refuses_repository_output_and_nonempty_output(tmp_path: Path) -> None:
    stage_release = _load_stage_release()
    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "keep.txt").write_text("keep", encoding="utf-8")

    for output in (REPOSITORY / "forbidden-stage", nonempty):
        try:
            stage_release(REPOSITORY, output)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe release output was accepted")
