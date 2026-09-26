"""Command construction, the no-fallback contract, and model attribution."""

from __future__ import annotations

from pathlib import Path

import pytest
from arena.opus.command import (
    CommandContractError,
    OpusCommandConfig,
    assert_no_fallback,
    attribute_models,
    build_command,
    build_probe_command,
    build_prompt,
    extract_reported_models,
    is_opus5_model,
)


def cfg() -> OpusCommandConfig:
    return OpusCommandConfig(claude_executable="/usr/bin/claude")


def test_command_carries_every_required_flag(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    image.write_bytes(b"x")
    argv = build_command(cfg(), image)

    assert argv[0] == "/usr/bin/claude"
    assert "-p" in argv
    assert argv[argv.index("--model") + 1] == "opus"
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--effort") + 1] == "high"
    assert "--no-session-persistence" in argv
    assert "--disable-slash-commands" in argv
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--setting-sources") + 1] == "project,local"
    assert argv[argv.index("--add-dir") + 1] == str(image.resolve().parent)


def test_variadic_flags_are_last_so_no_positional_is_swallowed(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    image.write_bytes(b"x")
    argv = build_command(cfg(), image)

    # Nothing may follow the final variadic option's values, and the prompt must
    # not be in argv at all -- it goes on stdin.
    assert argv[-2:] == ["--allowedTools", "Read"]
    assert not any("transcription" in token.lower() for token in argv)


def test_launcher_tokens_precede_the_executable(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    image.write_bytes(b"x")
    argv = build_command(
        OpusCommandConfig(claude_executable="fake.py", launcher=("python",)), image
    )
    assert argv[:2] == ["python", "fake.py"]


def test_prompt_appends_the_absolute_image_path(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    image.write_bytes(b"x")
    prompt = build_prompt("Line one.\nLine two.\n", image)

    assert prompt.startswith("Line one.\nLine two.")
    assert prompt.rstrip().endswith(f"The page image is at: {image.resolve()}")


def test_probe_command_has_no_add_dir() -> None:
    argv = build_probe_command(cfg())
    assert "--add-dir" not in argv


@pytest.mark.parametrize(
    "argv",
    [
        ["claude", "-p", "--bare"],
        ["claude", "-p", "--fallback-model", "sonnet"],
        ["claude", "-p", "--dangerously-skip-permissions"],
        ["claude", "-p", "--model", "sonnet"],
        ["claude", "-p", "--model", "claude-opus-4-5"],
        ["claude", "-p", "--model", "opus", "--append-system-prompt", "use haiku"],
    ],
)
def test_assert_no_fallback_refuses(argv: list[str]) -> None:
    with pytest.raises(CommandContractError):
        assert_no_fallback(argv)


def test_assert_no_fallback_ignores_paths_that_contain_model_names() -> None:
    # A directory happening to be called "gpt" is not a contract violation.
    assert_no_fallback(["/usr/bin/claude", "-p", "--model", "opus", "--add-dir", "/data/gpt"])


def test_model_flag_without_a_value_is_refused() -> None:
    with pytest.raises(CommandContractError, match="without a value"):
        assert_no_fallback(["claude", "-p", "--model"])


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("claude-opus-5", True),
        ("claude-opus-5-20260724", True),
        ("opus-5", True),
        ("opus", False),
        ("claude-opus-4-5", False),
        ("claude-sonnet-4-5-20250929", False),
        ("claude-haiku-4-5-20251001", False),
        (None, False),
    ],
)
def test_is_opus5_model(model: str | None, expected: bool) -> None:
    assert is_opus5_model(model) is expected


def test_extract_reported_models_reads_model_usage() -> None:
    payload = {
        "model": "claude-opus-5",
        "modelUsage": {"claude-haiku-4-5-20251001": {}, "claude-opus-5": {}},
    }
    assert extract_reported_models(payload) == ["claude-opus-5", "claude-haiku-4-5-20251001"]


def test_attribution_accepts_the_real_probe_shape() -> None:
    """The 2026-09-03 probe reported Haiku alongside Opus; that is not a fallback."""
    payload = {
        "modelUsage": {
            "claude-haiku-4-5-20251001": {"inputTokens": 898, "outputTokens": 11},
            "claude-opus-5": {"inputTokens": 2, "outputTokens": 4},
        }
    }
    attribution = attribute_models(payload)

    assert attribution.ok
    assert attribution.primary == "claude-opus-5"
    assert attribution.auxiliary == ("claude-haiku-4-5-20251001",)
    assert attribution.unexpected == ()
    assert attribution.failure_reason() is None


def test_attribution_rejects_a_sonnet_answer() -> None:
    payload = {"modelUsage": {"claude-sonnet-4-5-20250929": {}}}
    attribution = attribute_models(payload)

    assert not attribution.ok
    reason = attribution.failure_reason()
    assert reason is not None
    assert "unexpected model" in reason


def test_attribution_rejects_a_payload_naming_no_model() -> None:
    attribution = attribute_models({"result": "text"})

    assert not attribution.ok
    reason = attribution.failure_reason()
    assert reason is not None
    assert "names no model" in reason


def test_inference_config_hash_is_stable_across_hosts() -> None:
    a = OpusCommandConfig(claude_executable="/usr/bin/claude")
    b = OpusCommandConfig(claude_executable=r"C:\claude.exe", launcher=("python",))
    assert a.inference_config_sha256() == b.inference_config_sha256()


def test_inference_config_hash_changes_with_effort() -> None:
    a = OpusCommandConfig(claude_executable="claude", effort="high")
    b = OpusCommandConfig(claude_executable="claude", effort="max")
    assert a.inference_config_sha256() != b.inference_config_sha256()
