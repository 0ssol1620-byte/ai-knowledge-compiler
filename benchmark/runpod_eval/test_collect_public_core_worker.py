from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from collect_public_core_worker import validate_archive


def _archive(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as bundle:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            bundle.addfile(info, io.BytesIO(content))


def test_validate_archive_accepts_only_bounded_worker_evidence(tmp_path: Path) -> None:
    archive = tmp_path / "worker.tar.gz"
    members = {
        "./worker-state.jsonl": b"{}\n",
        "./parsebench/run-summary.json": b"{}\n",
        "./omnidocbench/run-summary.json": b"{}\n",
        "./olmocr-bench/run-summary.json": b"{}\n",
        "./parsebench/markdown-repeat-1/parsebench-a.md": b"ok",
        "./parsebench/repeat-1/parsebench-a/vlm/parsebench-a_model.json": b"[]",
        "./parsebench/repeat-1.stderr.log": b"",
        "./parsebench/straggler-case-id.txt": b"parsebench-a\n",
    }
    _archive(archive, members)
    observed = validate_archive(archive)
    assert "worker-state.jsonl" in observed
    assert len(observed) == len(members)


def test_validate_archive_rejects_secret_or_path_escape(tmp_path: Path) -> None:
    for name in ("Github_API.txt", "../escape.txt"):
        archive = tmp_path / f"bad-{len(name)}.tar.gz"
        _archive(
            archive,
            {
                "worker-state.jsonl": b"{}\n",
                "parsebench/run-summary.json": b"{}\n",
                "omnidocbench/run-summary.json": b"{}\n",
                "olmocr-bench/run-summary.json": b"{}\n",
                name: b"secret",
            },
        )
        with pytest.raises(ValueError, match="unsafe or unexpected"):
            validate_archive(archive)


def test_validate_archive_requires_all_suite_summaries(tmp_path: Path) -> None:
    archive = tmp_path / "incomplete.tar.gz"
    _archive(
        archive,
        {
            "worker-state.jsonl": b"{}\n",
            "parsebench/run-summary.json": b"{}\n",
        },
    )
    with pytest.raises(ValueError, match="incomplete"):
        validate_archive(archive)
