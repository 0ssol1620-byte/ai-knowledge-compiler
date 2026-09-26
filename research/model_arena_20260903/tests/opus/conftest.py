"""Shared fixtures for the Opus lane tests.

Nothing here touches the network or the real ``claude`` CLI. The fake CLI in
``claude.py`` is launched through an explicit interpreter path that the tests
inject into ``OpusCommandConfig.launcher``.
"""

from __future__ import annotations

import struct
import sys
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from arena.opus import paths as opus_paths
from arena.opus import runner as opus_runner
from arena.opus.command import OpusCommandConfig
from arena.opus.pricing import PriceSnapshot
from arena.opus.prompt import ResolvedPrompt
from arena.opus.selection import PageSpec

FAKE_CLAUDE = Path(__file__).resolve().parent / "claude.py"


def make_png(width: int = 8, height: int = 6) -> bytes:
    """A minimal, valid 8-bit greyscale PNG."""

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    rows = b"".join(b"\x00" + bytes([(x * 7 + y * 3) % 256 for x in range(width)])
                    for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def png_bytes() -> bytes:
    return make_png()


@pytest.fixture
def page_spec(tmp_path: Path, png_bytes: bytes) -> PageSpec:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    image = inputs / "omnidocbench-testcase0001.png"
    image.write_bytes(png_bytes)
    return PageSpec(
        case_key="omnidocbench-testcase0001",
        sample_id="omnidoc:images/test_page_001",
        benchmark="omnidoc",
        benchmark_revision="aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec",
        image_path=image,
        manifest_input_sha256=opus_paths.sha256_tagged(png_bytes),
        staged_source_sha256=opus_paths.sha256_tagged(b"original"),
        media_type="image",
        page_index=3,
        source_relative_path="images/test_page_001.png",
    )


@pytest.fixture
def second_page_spec(tmp_path: Path) -> PageSpec:
    data = make_png(10, 4)
    inputs = tmp_path / "inputs2"
    inputs.mkdir()
    image = inputs / "omnidocbench-testcase0002.png"
    image.write_bytes(data)
    return PageSpec(
        case_key="omnidocbench-testcase0002",
        sample_id="omnidoc:images/test_page_002",
        benchmark="omnidoc",
        benchmark_revision="aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec",
        image_path=image,
        manifest_input_sha256=opus_paths.sha256_tagged(data),
        staged_source_sha256=opus_paths.sha256_tagged(b"original2"),
        media_type="image",
        page_index=0,
        source_relative_path="images/test_page_002.png",
    )


@pytest.fixture
def fake_command_config() -> OpusCommandConfig:
    return OpusCommandConfig(
        claude_executable=str(FAKE_CLAUDE), launcher=(sys.executable,)
    )


@pytest.fixture
def price_snapshot() -> PriceSnapshot:
    return PriceSnapshot.load()


@pytest.fixture
def resolved_prompt(tmp_path: Path) -> ResolvedPrompt:
    text = "Transcribe the page.\n"
    path = tmp_path / "prompt.txt"
    path.write_text(text, encoding="utf-8")
    return ResolvedPrompt(
        prompt_id="opus5_transcription_v1",
        text=text,
        sha256=opus_paths.sha256_tagged(text.encode("utf-8")),
        path=path,
        source="test",
        notes=(),
    )


@pytest.fixture
def child_env(tmp_path: Path) -> dict[str, str]:
    """A clean env that still lets the fake CLI read its FAKE_CLAUDE_* knobs."""
    import os

    keep = {
        name: os.environ[name]
        for name in ("PATH", "Path", "SystemRoot", "SYSTEMROOT", "ComSpec", "COMSPEC", "PATHEXT")
        if name in os.environ
    }
    keep["TEMP"] = str(tmp_path)
    keep["TMP"] = str(tmp_path)
    return keep


@pytest.fixture
def isolated_run_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect every write path of the lane into tmp_path."""
    root = tmp_path / "runs" / "opus5_subscription"
    targets: dict[str, Any] = {
        "RUN_ROOT": root,
        "RAW_DIR": root / "raw",
        "CANONICAL_DIR": root / "canonical",
        "RECEIPT_DIR": root / "receipts",
        "CANARY_DIR": root / "canary",
        "CHECKPOINT_PATH": root / "checkpoint.json",
        "RUN_SUMMARY_PATH": root / "run-summary.json",
    }
    for name, value in targets.items():
        monkeypatch.setattr(opus_paths, name, value, raising=True)
        if hasattr(opus_runner, name):
            monkeypatch.setattr(opus_runner, name, value, raising=True)
    root.mkdir(parents=True, exist_ok=True)
    yield root


@pytest.fixture
def runner_config(
    fake_command_config: OpusCommandConfig,
    resolved_prompt: ResolvedPrompt,
    price_snapshot: PriceSnapshot,
    child_env: dict[str, str],
    tmp_path: Path,
) -> opus_runner.RunnerConfig:
    cwd = tmp_path / "childcwd"
    cwd.mkdir(exist_ok=True)
    return opus_runner.RunnerConfig(
        command=fake_command_config,
        prompt=resolved_prompt,
        price_snapshot=price_snapshot,
        claude_version="2.1.252 (Claude Code)",
        workers=2,
        timeout_seconds=60,
        job_kind="canary",
        env=child_env,
        child_cwd=cwd,
    )
