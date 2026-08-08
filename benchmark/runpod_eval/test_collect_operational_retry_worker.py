import io
import tarfile
from pathlib import Path

import pytest
from collect_operational_retry_worker import _validate_archive


def _archive(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as bundle:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            bundle.addfile(info, io.BytesIO(content))


def test_retry_archive_requires_only_requested_suite_and_bounded_outputs(tmp_path: Path) -> None:
    path = tmp_path / "retry.tar.gz"
    _archive(
        path,
        {
            "worker-state.jsonl": b"{}\n",
            "parsebench.runner.log": b"ok",
            "parsebench/run-summary.json": b"{}\n",
            "parsebench/markdown-repeat-1/parsebench-a.md": b"recovered",
            "parsebench/repeat-1/parsebench-a/vlm/parsebench-a_model.json": b"[]",
        },
    )
    members = _validate_archive(path, ("parsebench",))
    assert "parsebench/run-summary.json" in members


def test_retry_archive_rejects_source_or_secret_material(tmp_path: Path) -> None:
    path = tmp_path / "bad.tar.gz"
    _archive(
        path,
        {
            "worker-state.jsonl": b"{}\n",
            "parsebench/run-summary.json": b"{}\n",
            "Github_API.txt": b"secret",
        },
    )
    with pytest.raises(ValueError, match="unexpected"):
        _validate_archive(path, ("parsebench",))
