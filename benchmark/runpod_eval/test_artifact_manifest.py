from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_manifest_excludes_runtime_cache(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    (root / "images").mkdir(parents=True)
    (root / ".cache" / "downloads").mkdir(parents=True)
    (root / "images" / "page.png").write_bytes(b"page")
    (root / ".cache" / "downloads" / "page.metadata").write_bytes(b"cache")
    output = tmp_path / "manifest.json"

    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("artifact_manifest.py")),
            "--root",
            str(root),
            "--output",
            str(output),
            "--identity",
            "dataset@example",
            "--exclude-prefix",
            ".cache",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    manifest = json.loads(output.read_text(encoding="utf-8"))
    receipt = json.loads(result.stdout)
    assert manifest["file_count"] == 1
    assert manifest["files"][0]["path"] == "images/page.png"
    assert receipt["sha256"].startswith("sha256:")
