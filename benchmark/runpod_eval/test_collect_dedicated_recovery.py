from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from collect_dedicated_recovery import collect_dedicated_recovery, validate_archive


def _archive(path: Path, members: tuple[str, ...]) -> None:
    with tarfile.open(path, "w:gz") as bundle:
        for name in members:
            data = b"{}\n"
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))


def test_validate_archive_accepts_bounded_recovery_evidence(tmp_path: Path) -> None:
    archive = tmp_path / "ok.tar.gz"
    _archive(
        archive,
        (
            "campaign-state.jsonl",
            "worker-00/parsebench/run-summary.json",
            "worker-00/parsebench/markdown-repeat-1/case.md",
            "worker-00/parsebench/repeat-1/case.json",
            "worker-00/parsebench/repeat-1/case/isolated-case-spec.json",
        ),
    )
    assert len(validate_archive(archive)) == 5


def test_validate_archive_rejects_unexpected_files(tmp_path: Path) -> None:
    archive = tmp_path / "bad.tar.gz"
    _archive(archive, ("campaign-state.jsonl", "ground-truth.json"))
    with pytest.raises(ValueError):
        validate_archive(archive)


def test_collector_does_not_single_quote_remote_root_variable() -> None:
    source = Path(collect_dedicated_recovery.__code__.co_filename).read_text(
        encoding="utf-8"
    )

    assert "test -f '$root/worker-" not in source
    assert 'test -f "$root/worker-' in source
