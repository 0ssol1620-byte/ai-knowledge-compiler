import sys
import time
from pathlib import Path

import pytest
from mineru_stage2 import (
    _archive_interrupted_path,
    _case_has_reusable_markdown,
    _chunks,
    _merge_batch_cases,
    _posix_descendant_pids,
    _run_command_with_timeout,
    _stage_batch_input,
    _validate_frozen_input,
)


def test_timeout_terminates_process_and_returns_promptly() -> None:
    started = time.perf_counter()
    return_code, stdout, stderr, timed_out = _run_command_with_timeout(
        [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(60)"],
        1,
    )

    assert timed_out is True
    assert return_code == 124
    assert "started" in stdout
    assert stderr == ""
    assert time.perf_counter() - started < 10


def test_posix_descendant_snapshot_is_safe_off_linux() -> None:
    descendants = _posix_descendant_pids(2**30)

    assert descendants == ()


def test_chunks_preserve_order_and_exact_coverage(tmp_path: Path) -> None:
    images = tuple(tmp_path / f"case-{index}.png" for index in range(5))
    assert [len(batch) for batch in _chunks(images, 2)] == [2, 2, 1]
    assert tuple(image for batch in _chunks(images, 2) for image in batch) == images
    assert _chunks(images, 0) == (images,)
    with pytest.raises(ValueError, match="cannot be negative"):
        _chunks(images, -1)


def test_bounded_batch_inputs_and_outputs_remain_case_addressable(tmp_path: Path) -> None:
    sources = []
    for index in range(2):
        source = tmp_path / "source" / f"case-{index}.png"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(f"image-{index}".encode())
        sources.append(source)
    staged = _stage_batch_input(tmp_path / "batch-input", tuple(sources))
    assert sorted(path.read_bytes() for path in staged.iterdir()) == [b"image-0", b"image-1"]

    batch_output = tmp_path / "batch-output"
    for source in sources:
        model = batch_output / source.stem / "vlm" / f"{source.stem}_model.json"
        model.parent.mkdir(parents=True)
        model.write_text("[]", encoding="utf-8")
    repeat_root = tmp_path / "repeat-1"
    _merge_batch_cases(
        batch_output=batch_output,
        repeat_root=repeat_root,
        images=tuple(sources),
    )
    for source in sources:
        assert (
            repeat_root / source.stem / "vlm" / f"{source.stem}_model.json"
        ).is_file()


def test_interrupted_resume_reuses_only_nonempty_markdown(tmp_path: Path) -> None:
    source = tmp_path / "source" / "case-a.png"
    source.parent.mkdir()
    source.write_bytes(b"image-a")
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    (frozen / source.name).write_bytes(source.read_bytes())
    _validate_frozen_input(frozen, (source,))

    repeat = tmp_path / "repeat-1"
    markdown = repeat / source.stem / "vlm" / f"{source.stem}.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("usable", encoding="utf-8")
    assert _case_has_reusable_markdown(repeat, source)
    markdown.write_text("", encoding="utf-8")
    assert not _case_has_reusable_markdown(repeat, source)

    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="does not match"):
        _validate_frozen_input(frozen, (source,))


def test_interrupted_paths_are_archived_without_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "batch-0001"
    source.mkdir()
    (source / "partial.txt").write_text("first", encoding="utf-8")
    archive = tmp_path / "archive"
    _archive_interrupted_path(source, archive)
    assert (archive / "batch-0001" / "partial.txt").read_text() == "first"

    source.mkdir()
    (source / "partial.txt").write_text("second", encoding="utf-8")
    _archive_interrupted_path(source, archive)
    assert (archive / "batch-0001.1" / "partial.txt").read_text() == "second"
