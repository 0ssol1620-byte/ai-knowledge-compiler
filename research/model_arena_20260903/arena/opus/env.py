"""Scrubbed child environment and preflight (masterplan section 21.2).

Two jobs:

1. Build the environment each ``claude -p`` child gets. Anything that could move
   the run off the subscription surface, or that tells the child it is nested
   inside another Claude Code session, is removed.
2. Refuse to start when the *parent* shell carries ``ANTHROPIC_API_KEY``.
   Masterplan section 21.2 is explicit: an API key present in the benchmark shell
   can silently switch billing from the subscription to the API, which makes the
   result a different experiment. That is a stop condition (section 43), not a
   warning.

No secret value is ever read, printed or stored here. The preflight looks only at
whether a name is present in ``os.environ``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from arena.core.ids import RUNTIME_IMAGE_DIGEST_PATTERN

# ARENA_CONTRACT D27: the label after ``subscription:`` is ``[A-Za-z0-9._-]+``.
_LABEL_UNSAFE_RE: Final = re.compile(r"[^A-Za-z0-9._-]+")

# Names copied through to the child when present. PATH is required to find the
# CLI, the profile directories are required for the OAuth credential store, and
# the temp/system names are required for a working Windows process.
KEEP_ENV_NAMES: Final = (
    "PATH",
    "Path",
    "HOME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
    "TEMP",
    "TMP",
    "TMPDIR",
    "SystemRoot",
    "SYSTEMROOT",
    "windir",
    "ComSpec",
    "COMSPEC",
    "PATHEXT",
    "SystemDrive",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "OS",
    "USERNAME",
    "LANG",
    "LC_ALL",
)

# Removed even if they appear in KEEP_ENV_NAMES-shaped form. Exact names first,
# then prefixes.
DROP_ENV_NAMES: Final = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR",
    "AWS_BEARER_TOKEN_BEDROCK",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)
DROP_ENV_PREFIXES: Final = ("CLAUDE_CODE_", "ANTHROPIC_", "CLAUDE_")

# ``ANTHROPIC_API_KEY`` in the parent is a hard stop (section 21.2). The other
# names are reported by preflight as findings but do not block on their own.
BLOCKING_PARENT_NAMES: Final = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
REPORTED_PARENT_NAMES: Final = (
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "AWS_BEARER_TOKEN_BEDROCK",
)


class PreflightError(RuntimeError):
    """Raised when the host is not fit to run a subscription benchmark."""


# Founder directive 2026-09-03: the run must be provably on the Claude Code
# subscription surface (claude.ai OAuth), never on ANTHROPIC_API_KEY. Scrubbing
# the child env (above) prevents the key from being *used*; this section proves,
# in the receipt, that the login itself is the subscription login. Only these
# four fields are ever read out of ``claude auth status --json`` -- anything
# whose name looks like a credential is refused by construction, not filtered
# after the fact.
_TOKEN_LIKE_RE: Final = re.compile(r"token|key|secret|credential|session", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class AuthStatus:
    """The subscription-relevant facts out of ``claude auth status --json``.

    Deliberately narrow: no token, key, secret, credential or session-shaped
    value is ever carried by this type, so nothing here can leak one into a
    receipt.
    """

    logged_in: bool
    auth_method: str | None
    api_provider: str | None
    subscription_type: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "logged_in": self.logged_in,
            "auth_method": self.auth_method,
            "api_provider": self.api_provider,
            "subscription_type": self.subscription_type,
        }


def check_auth_status(
    *,
    parent: Mapping[str, str] | None = None,
    executable: str | None = None,
    timeout_seconds: int = 60,
) -> AuthStatus:
    """Run ``claude auth status --json`` in the scrubbed child env and prove
    the login is a first-party subscription login.

    Fails closed (raises :class:`PreflightError`) when the command cannot be
    run, prints unreadable output, or reports anything other than a logged-in,
    ``authMethod == "claude.ai"``, ``apiProvider == "firstParty"`` session --
    each of those means the run would not be billed against the subscription.
    """
    source = os.environ if parent is None else parent
    exe = resolve_claude_executable(executable)
    child_env = scrub_env(source)
    try:
        completed = subprocess.run(
            [exe, "auth", "status", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env=child_env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreflightError(
            f"`claude auth status --json` could not be executed: {type(exc).__name__}: {exc}"
        ) from exc

    stdout = (completed.stdout or "").strip()
    try:
        payload: object = json.loads(stdout) if stdout else None
    except json.JSONDecodeError as exc:
        raise PreflightError(
            f"`claude auth status --json` did not print valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise PreflightError(
            "`claude auth status --json` did not print a JSON object "
            f"(got {type(payload).__name__}); cannot confirm subscription auth"
        )

    # Allow-list read: only these four names are ever pulled out of `payload`.
    # A key whose name matches _TOKEN_LIKE_RE could not reach AuthStatus even
    # if `claude auth status` grew one, because nothing here iterates payload.
    raw_logged_in = payload.get("loggedIn")
    raw_auth_method = payload.get("authMethod")
    raw_api_provider = payload.get("apiProvider")
    raw_subscription_type = payload.get("subscriptionType")

    logged_in = bool(raw_logged_in)
    auth_method = raw_auth_method if isinstance(raw_auth_method, str) else None
    api_provider = raw_api_provider if isinstance(raw_api_provider, str) else None
    subscription_type = (
        raw_subscription_type if isinstance(raw_subscription_type, str) else None
    )

    if not logged_in:
        raise PreflightError(
            "`claude auth status` reports loggedIn=false; the run would not be on "
            "the subscription surface. Log in with `claude login` (claude.ai) and "
            "re-run preflight."
        )
    if auth_method != "claude.ai":
        raise PreflightError(
            f"`claude auth status` reports authMethod={auth_method!r}, not "
            "'claude.ai'; the run would not be on the subscription surface. "
            "Re-authenticate through the claude.ai OAuth flow, not an API key or "
            "console login."
        )
    if api_provider != "firstParty":
        raise PreflightError(
            f"`claude auth status` reports apiProvider={api_provider!r}, not "
            "'firstParty'; the run would not be on the subscription surface."
        )

    return AuthStatus(
        logged_in=logged_in,
        auth_method=auth_method,
        api_provider=api_provider,
        subscription_type=subscription_type,
    )


def scrub_env(parent: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return the environment a ``claude -p`` child is allowed to inherit.

    Allow-list first (only ``KEEP_ENV_NAMES`` survive), deny-list second so a
    name that appears on both lists is still dropped.
    """
    source = os.environ if parent is None else parent
    child: dict[str, str] = {}
    for name in KEEP_ENV_NAMES:
        value = source.get(name)
        if value is not None:
            child[name] = value
    for name in list(child):
        if name in DROP_ENV_NAMES or name.upper().startswith(DROP_ENV_PREFIXES):
            del child[name]
    return child


def dropped_names(parent: Mapping[str, str] | None = None) -> list[str]:
    """Names present in the parent that this lane deliberately does not pass on."""
    source = os.environ if parent is None else parent
    out = [
        name
        for name in source
        if name in DROP_ENV_NAMES or name.upper().startswith(DROP_ENV_PREFIXES)
    ]
    return sorted(out)


def resolve_claude_executable(explicit: str | None = None) -> str:
    """Absolute path to the Claude Code CLI, or raise."""
    if explicit:
        found = shutil.which(explicit) or (explicit if os.path.isfile(explicit) else None)
        if found is None:
            raise PreflightError(f"claude executable not found at {explicit!r}")
        return os.path.abspath(found)
    found = shutil.which("claude")
    if found is None:
        raise PreflightError("claude executable not found on PATH")
    return os.path.abspath(found)


@dataclass(frozen=True, slots=True)
class PreflightResult:
    ok: bool
    claude_executable: str
    claude_version: str | None
    version_exit_code: int | None
    parent_blocking_names: tuple[str, ...]
    parent_reported_names: tuple[str, ...]
    scrubbed_env_names: tuple[str, ...]
    dropped_env_names: tuple[str, ...]
    findings: tuple[str, ...]
    auth: AuthStatus | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "claude_executable": self.claude_executable,
            "claude_version": self.claude_version,
            "version_exit_code": self.version_exit_code,
            "parent_blocking_env_names_present": list(self.parent_blocking_names),
            "parent_reported_env_names_present": list(self.parent_reported_names),
            "scrubbed_env_names": list(self.scrubbed_env_names),
            "dropped_env_names": list(self.dropped_env_names),
            "findings": list(self.findings),
            "auth": self.auth.to_json() if self.auth is not None else None,
        }


def preflight(
    *,
    parent: Mapping[str, str] | None = None,
    executable: str | None = None,
    timeout_seconds: int = 60,
) -> PreflightResult:
    """Check the host without spending any subscription allowance.

    ``claude --version`` does not start a session and does not call the model, so
    it is safe to run on every preflight.
    """
    source = os.environ if parent is None else parent
    blocking = tuple(n for n in BLOCKING_PARENT_NAMES if source.get(n))
    reported = tuple(n for n in REPORTED_PARENT_NAMES if source.get(n))
    findings: list[str] = []

    for name in blocking:
        findings.append(
            f"{name} is set in the parent environment. Masterplan section 21.2 forbids "
            "running the subscription benchmark from a shell that carries an API "
            "credential: Claude Code may bill the API instead of the subscription. "
            "Unset it in the benchmark shell and re-run preflight."
        )
    for name in reported:
        findings.append(
            f"{name} is set in the parent environment; it is scrubbed from the child, "
            "but check that this host is not configured for a third-party provider."
        )

    try:
        exe = resolve_claude_executable(executable)
    except PreflightError as exc:
        findings.append(str(exc))
        return PreflightResult(
            ok=False,
            claude_executable=executable or "claude",
            claude_version=None,
            version_exit_code=None,
            parent_blocking_names=blocking,
            parent_reported_names=reported,
            scrubbed_env_names=(),
            dropped_env_names=tuple(dropped_names(source)),
            findings=tuple(findings),
        )

    child_env = scrub_env(source)
    version: str | None = None
    version_code: int | None = None
    try:
        completed = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env=child_env,
            check=False,
        )
        version_code = completed.returncode
        version = completed.stdout.strip() or None
        if completed.returncode != 0:
            findings.append(
                f"`claude --version` exited {completed.returncode}; "
                "the CLI is not usable with the scrubbed environment."
            )
    except (OSError, subprocess.SubprocessError) as exc:
        findings.append(f"`claude --version` could not be executed: {type(exc).__name__}")

    auth: AuthStatus | None = None
    try:
        auth = check_auth_status(
            parent=source, executable=exe, timeout_seconds=timeout_seconds
        )
    except PreflightError as exc:
        findings.append(str(exc))

    ok = (
        not blocking
        and version is not None
        and version_code == 0
        and auth is not None
    )
    return PreflightResult(
        ok=ok,
        claude_executable=exe,
        claude_version=version,
        version_exit_code=version_code,
        parent_blocking_names=blocking,
        parent_reported_names=reported,
        scrubbed_env_names=tuple(sorted(child_env)),
        dropped_env_names=tuple(dropped_names(source)),
        findings=tuple(findings),
        auth=auth,
    )


def cli_version_token(version: str | None) -> str:
    """The bare version number out of ``claude --version`` output.

    ``"2.1.252 (Claude Code)"`` -> ``"2.1.252"``. An unreadable version is
    reported as ``"unknown"`` rather than guessed, and any character outside the
    label grammar is replaced so the digest stays parseable.
    """
    token = (version or "").split()[0].strip() if version else ""
    if not token:
        return "unknown"
    cleaned = _LABEL_UNSAFE_RE.sub("-", token)
    return cleaned or "unknown"


def subscription_image_digest(version: str | None, model_id: str) -> str:
    """``subscription:claude-code-<cli version>-<model id>`` (ARENA_CONTRACT D27).

    This lane runs no container, so the pair that actually decides what the model
    sees is the Claude Code build and the model id it resolves to. The result is
    checked against ``arena.core.ids.RUNTIME_IMAGE_DIGEST_PATTERN`` and this
    function fails closed when the grammar is not yet accepted there: an
    identifier the shared module would reject must never reach a receipt.
    """
    model = _LABEL_UNSAFE_RE.sub("-", (model_id or "").strip())
    if not model:
        raise PreflightError("model_id is required to build a subscription image digest")
    digest = f"subscription:claude-code-{cli_version_token(version)}-{model}"
    if not re.fullmatch(RUNTIME_IMAGE_DIGEST_PATTERN, digest):
        raise PreflightError(
            f"arena.core.ids does not accept {digest!r}: the 'subscription:<label>' "
            "grammar of ARENA_CONTRACT D27 has not landed in "
            "arena/core/ids.py (lane A1 owns it). Refusing to write a receipt "
            "carrying an identifier the shared module would reject."
        )
    return digest


__all__ = [
    "BLOCKING_PARENT_NAMES",
    "DROP_ENV_NAMES",
    "DROP_ENV_PREFIXES",
    "KEEP_ENV_NAMES",
    "AuthStatus",
    "PreflightError",
    "PreflightResult",
    "check_auth_status",
    "cli_version_token",
    "dropped_names",
    "preflight",
    "resolve_claude_executable",
    "scrub_env",
    "subscription_image_digest",
]
