"""Per-page ``claude -p`` command construction (masterplan section 21.4).

Every flag here was verified against ``claude --help`` on the installed
Claude Code 2.1.252 and against the official docs; the verified list, with the
version string and the reason for each flag, is in ``CLAUDE_CLI_FLAGS.md``.

Two things about this command are load-bearing and easy to get wrong:

- ``--tools``, ``--allowedTools`` and ``--add-dir`` are *variadic* options. A
  positional prompt placed after one of them is swallowed as another value. The
  prompt is therefore delivered on **stdin**, which the official headless docs
  document for ``-p`` ("Non-interactive mode reads stdin"), and the variadic
  flags are kept at the end of argv where nothing follows them.
- ``--bare`` is forbidden (masterplan section 21.3): the docs state that bare
  mode never reads OAuth credentials or the keychain and requires
  ``ANTHROPIC_API_KEY``, which would move the run onto API billing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from arena.opus.paths import canonical_json, sha256_tagged

# The alias passed to --model. The resolved id reported by the payload is checked
# against OPUS5_MODEL_RE and stored separately as ``reported_model``.
OPUS_MODEL_ALIAS: Final = "opus"
# API model id, from https://www.anthropic.com/news/claude-opus-5 ("Developers can
# get started with claude-opus-5 on the Claude API").
OPUS_DECLARED_MODEL: Final = "claude-opus-5"
OPUS_MODEL_REPO: Final = "anthropic:claude-opus-5"

# Accepts "claude-opus-5", "claude-opus-5-20260724", "opus-5". Deliberately does
# not accept the bare alias "opus" (which proves nothing) and does not accept
# "claude-opus-4-5" (the "-5" there follows a "4", not "opus").
OPUS5_MODEL_RE: Final = re.compile(r"(?:^|[^a-z0-9])opus[-_.]?5(?:$|[^0-9])", re.IGNORECASE)

# Claude Code spends a small amount of Haiku on its own housekeeping inside a
# ``-p`` run; the 2026-09-03 qualification probe returned modelUsage keys
# ``claude-haiku-4-5-20251001`` (898 in / 11 out) alongside ``claude-opus-5``
# (the answer). That is a property of the product surface, not a model fallback,
# so it is allowed, recorded on the receipt as an auxiliary model, and excluded
# from the benchmark's token and price columns.
AUXILIARY_MODEL_RE: Final = re.compile(r"haiku", re.IGNORECASE)

# Any of these appearing in argv means a non-Opus model could be selected.
FORBIDDEN_ARG_TOKENS: Final = (
    "--bare",
    "--fallback-model",
    "--dangerously-skip-permissions",
)
FORBIDDEN_MODEL_SUBSTRINGS: Final = (
    "sonnet",
    "haiku",
    "fable",
    "claude-3",
    "claude-4",
    "opus-4",
    "gpt",
    "gemini",
)


class CommandContractError(RuntimeError):
    """Raised when a command would violate the no-fallback contract."""


@dataclass(frozen=True, slots=True)
class OpusCommandConfig:
    """Everything that is frozen across the campaign and hashed into the job id."""

    claude_executable: str
    # Tokens placed BEFORE the executable. Host-specific launch mechanics only
    # (an explicit interpreter in tests, a wrapper on a locked-down host); like
    # the executable path itself, it is excluded from inference_config() so the
    # job id does not change between machines.
    launcher: tuple[str, ...] = ()
    effort: str = "high"
    model_alias: str = OPUS_MODEL_ALIAS
    output_format: str = "json"
    permission_mode: str = "dontAsk"
    tools: tuple[str, ...] = ("Read",)
    allowed_tools: tuple[str, ...] = ("Read",)
    no_session_persistence: bool = True
    disable_slash_commands: bool = True
    strict_mcp_config: bool = True
    # ``user`` is deliberately absent: user-level settings on a developer machine
    # carry SessionStart/UserPromptSubmit hooks that would inject machine-specific
    # context into every benchmark child and add startup latency. See
    # CLAUDE_CLI_FLAGS.md. The child also runs with a cwd outside any repository,
    # so no project/local settings file is discovered either.
    setting_sources: tuple[str, ...] = ("project", "local")
    extra_args: tuple[str, ...] = field(default=())

    def inference_config(self) -> dict[str, Any]:
        """The frozen per-model settings, as hashed into ``inference_job_id``.

        The executable path is intentionally excluded: it is host-specific and
        would make the job id differ between machines running the same config.
        """
        return {
            "disable_slash_commands": self.disable_slash_commands,
            "effort": self.effort,
            "extra_args": list(self.extra_args),
            "model_alias": self.model_alias,
            "no_session_persistence": self.no_session_persistence,
            "output_format": self.output_format,
            "permission_mode": self.permission_mode,
            "prompt_delivery": "stdin",
            "setting_sources": list(self.setting_sources),
            "strict_mcp_config": self.strict_mcp_config,
            "surface": "claude-code-read-tool",
            "tools": list(self.tools),
            "allowed_tools": list(self.allowed_tools),
        }

    def inference_config_sha256(self) -> str:
        return sha256_tagged(canonical_json(self.inference_config()).encode("utf-8"))


def build_prompt(prompt_text: str, image_path: Path) -> str:
    """Registry prompt + the single line naming the absolute image path.

    The image line is appended, never interpolated into the registry text, so the
    registry file's sha256 stays the thing that identifies the prompt contract.
    """
    body = prompt_text.rstrip("\n")
    absolute = str(Path(image_path).resolve())
    return f"{body}\n\nThe page image is at: {absolute}\n"


def build_command(cfg: OpusCommandConfig, image_path: Path) -> list[str]:
    """Return argv for one page. The prompt is NOT in argv; it goes on stdin."""
    image = Path(image_path).resolve()
    argv: list[str] = [
        *cfg.launcher,
        cfg.claude_executable,
        "-p",
        "--model",
        cfg.model_alias,
        "--output-format",
        cfg.output_format,
        "--permission-mode",
        cfg.permission_mode,
        "--effort",
        cfg.effort,
    ]
    if cfg.no_session_persistence:
        argv.append("--no-session-persistence")
    if cfg.disable_slash_commands:
        argv.append("--disable-slash-commands")
    if cfg.strict_mcp_config:
        argv.append("--strict-mcp-config")
    if cfg.setting_sources:
        argv += ["--setting-sources", ",".join(cfg.setting_sources)]
    argv += list(cfg.extra_args)
    # Variadic options last, each terminated by the next option or end of argv.
    argv += ["--add-dir", str(image.parent)]
    argv += ["--tools", *cfg.tools]
    argv += ["--allowedTools", *cfg.allowed_tools]
    assert_no_fallback(argv)
    return argv


def build_probe_command(cfg: OpusCommandConfig) -> list[str]:
    """Argv for the trivial qualification probe: same surface, no image, no tools."""
    argv: list[str] = [
        *cfg.launcher,
        cfg.claude_executable,
        "-p",
        "--model",
        cfg.model_alias,
        "--output-format",
        cfg.output_format,
        "--permission-mode",
        cfg.permission_mode,
        "--effort",
        cfg.effort,
    ]
    if cfg.no_session_persistence:
        argv.append("--no-session-persistence")
    if cfg.disable_slash_commands:
        argv.append("--disable-slash-commands")
    if cfg.strict_mcp_config:
        argv.append("--strict-mcp-config")
    if cfg.setting_sources:
        argv += ["--setting-sources", ",".join(cfg.setting_sources)]
    argv += list(cfg.extra_args)
    argv += ["--tools", *cfg.tools]
    argv += ["--allowedTools", *cfg.allowed_tools]
    assert_no_fallback(argv)
    return argv


def assert_no_fallback(argv: Sequence[str]) -> None:
    """Fail closed if argv could select anything but Opus (masterplan 21.8, 43).

    ``--bare`` is refused here as well as by policy, because the docs state it
    switches authentication to ``ANTHROPIC_API_KEY``.
    """
    lowered = [arg.lower() for arg in argv]
    for forbidden in FORBIDDEN_ARG_TOKENS:
        if forbidden in lowered:
            raise CommandContractError(
                f"{forbidden} is forbidden in the Opus subscription lane "
                "(masterplan sections 21.3 and 21.8: no fallback, no API switch)"
            )
    for index, arg in enumerate(lowered):
        if arg != "--model":
            continue
        if index + 1 >= len(lowered):
            raise CommandContractError("--model given without a value")
        value = lowered[index + 1]
        if value != OPUS_MODEL_ALIAS and not OPUS5_MODEL_RE.search(value):
            raise CommandContractError(f"--model {argv[index + 1]!r} is not an Opus 5 model")
    for arg in lowered:
        # Filesystem paths (the executable, --add-dir) are not model selectors and
        # must not be searched for model names; a directory called "gpt" is not a
        # contract violation.
        if "/" in arg or "\\" in arg:
            continue
        for bad in FORBIDDEN_MODEL_SUBSTRINGS:
            if bad in arg:
                raise CommandContractError(
                    f"argv token {arg!r} names a non-Opus model; the lane refuses to "
                    "downgrade or fall back"
                )


def is_opus5_model(model: str | None) -> bool:
    return bool(model) and bool(OPUS5_MODEL_RE.search(model or ""))


def is_auxiliary_model(model: str) -> bool:
    return bool(AUXILIARY_MODEL_RE.search(model))


@dataclass(frozen=True, slots=True)
class ModelAttribution:
    """Which models the payload says did the work."""

    opus5: tuple[str, ...]
    auxiliary: tuple[str, ...]
    unexpected: tuple[str, ...]
    all_reported: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return bool(self.opus5) and not self.unexpected

    @property
    def primary(self) -> str | None:
        return self.opus5[0] if self.opus5 else None

    def failure_reason(self) -> str | None:
        if self.unexpected:
            return (
                f"unexpected model: the payload attributes work to {list(self.unexpected)!r}, "
                "which is neither Opus 5 nor Claude Code's known auxiliary model"
            )
        if not self.opus5:
            if not self.all_reported:
                return (
                    "unexpected model: the payload names no model, so the run cannot be "
                    "attributed to Opus 5"
                )
            return (
                f"unexpected model: payload reports {list(self.all_reported)!r}, "
                "none of which is an Opus 5 model"
            )
        return None

    def to_json(self) -> dict[str, object]:
        return {
            "reported_models": list(self.all_reported),
            "opus5_models": list(self.opus5),
            "auxiliary_models": list(self.auxiliary),
            "unexpected_models": list(self.unexpected),
        }


def attribute_models(payload: Mapping[str, Any]) -> ModelAttribution:
    """Split every reported model into Opus 5 / auxiliary / unexpected."""
    reported = extract_reported_models(payload)
    opus5 = tuple(m for m in reported if is_opus5_model(m))
    auxiliary = tuple(m for m in reported if not is_opus5_model(m) and is_auxiliary_model(m))
    unexpected = tuple(
        m for m in reported if not is_opus5_model(m) and not is_auxiliary_model(m)
    )
    return ModelAttribution(
        opus5=opus5,
        auxiliary=auxiliary,
        unexpected=unexpected,
        all_reported=tuple(reported),
    )


def extract_reported_models(payload: Mapping[str, Any]) -> list[str]:
    """Every model id the payload names, in a stable order.

    Looks in the places Claude Code's JSON result is known to carry a model:
    ``model``, ``modelUsage`` keys, ``usage.model``, and the ``system/init``
    style ``model`` nested under ``init``. Unknown shapes are ignored rather than
    guessed at; a payload that names no model at all is a failure, not a pass.
    """
    found: list[str] = []

    def add(value: object) -> None:
        if isinstance(value, str) and value and value not in found:
            found.append(value)

    add(payload.get("model"))
    model_usage = payload.get("modelUsage")
    if isinstance(model_usage, Mapping):
        for key in model_usage:
            add(key)
    usage = payload.get("usage")
    if isinstance(usage, Mapping):
        add(usage.get("model"))
    init = payload.get("init")
    if isinstance(init, Mapping):
        add(init.get("model"))
    return found


__all__ = [
    "AUXILIARY_MODEL_RE",
    "FORBIDDEN_ARG_TOKENS",
    "FORBIDDEN_MODEL_SUBSTRINGS",
    "OPUS5_MODEL_RE",
    "OPUS_DECLARED_MODEL",
    "OPUS_MODEL_ALIAS",
    "OPUS_MODEL_REPO",
    "CommandContractError",
    "ModelAttribution",
    "OpusCommandConfig",
    "assert_no_fallback",
    "attribute_models",
    "build_command",
    "build_probe_command",
    "build_prompt",
    "extract_reported_models",
    "is_auxiliary_model",
    "is_opus5_model",
]
