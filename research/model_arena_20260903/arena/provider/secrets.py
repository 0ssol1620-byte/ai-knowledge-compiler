"""The one place in the arena namespace that reads credential material.

Masterplan section 39: tokens come from an environment or secret store, never
from a log, never from a receipt, never from a pip freeze. ARENA_CONTRACT
section 9 repeats it: read only through this module, never serialize.

``Secret`` is deliberately *not* a ``str`` subclass. A ``str`` subclass would be
accepted by ``json.dumps``, by f-strings, by ``httpx`` header building and by
every logger in the process, and every one of those would leak silently. This
wrapper fails closed instead: printing it yields a redaction, serializing it
raises, and ``reveal()`` is the single audited exit.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from arena.provider.safety import register_live_secret

__all__ = [
    "CREDENTIAL_FILE",
    "R2Credentials",
    "Secret",
    "SecretUnavailable",
    "load_secret",
    "r2_credentials",
    "runpod_api_key",
    "runpod_api_key_source",
    "worker_bearer",
]

CREDENTIAL_FILE: Final = Path(r"D:\Github_API.txt")

RUNPOD_LABEL: Final = "Runpod_B"
RUNPOD_ENV_FALLBACK: Final = "RUNPOD_API_KEY"

R2_HEADING: Final = "Cloudflare R2"
R2_BLOCK_LABELS: Final = {"account": "Account API Token", "user": "User API Tokens"}
R2_ACCESS_KEY_LABEL: Final = "Access Key ID"
R2_SECRET_KEY_LABEL: Final = "Secret Access Key"  # noqa: S105 - a label, not a value
R2_ENDPOINT_LABEL: Final = "Use jurisdiction-specific endpoints for S3 clients"

_LINE_RE: Final = re.compile(r"^\s*(?P<label>[^:=]{1,80}?)\s*[:=]\s*(?P<value>.*?)\s*$")
_MIN_KEY_LENGTH: Final = 16


class SecretUnavailable(RuntimeError):
    """The credential is not present. Never carries the value it looked for."""


class Secret:
    """An opaque credential. Redacted everywhere except ``reveal()``."""

    __slots__ = ("_label", "_value")

    def __init__(self, value: str, *, label: str) -> None:
        if not isinstance(value, str) or not value:
            raise SecretUnavailable(f"secret {label!r} is empty")
        self._value = value
        self._label = label
        # So the receipt guard can catch this exact value even when its shape
        # is indistinguishable from a hash.
        register_live_secret(value)

    @property
    def label(self) -> str:
        return self._label

    def reveal(self) -> str:
        """Return the raw value. Call this only where a header is built."""

        return self._value

    def __len__(self) -> int:
        return len(self._value)

    def __bool__(self) -> bool:
        return bool(self._value)

    def __str__(self) -> str:
        return f"<redacted secret {self._label!r} len={len(self._value)}>"

    def __repr__(self) -> str:
        return f"Secret(label={self._label!r}, length={len(self._value)}, value=<redacted>)"

    def __format__(self, format_spec: str) -> str:
        return str(self)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Secret):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        # Hashing the value would let a dict key leak it by equality probing.
        return hash((Secret, self._label, len(self._value)))

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("a Secret may not be pickled, copied or serialized")

    def for_json(self) -> str:
        raise TypeError("a Secret may not be serialized to JSON")

    def __iter__(self) -> Iterator[str]:
        # json.dumps and csv writers probe iterability; refuse loudly.
        raise TypeError("a Secret may not be iterated")


def _iter_labelled_lines(path: Path) -> Iterator[tuple[int, str, str]]:
    if not path.is_file():
        raise SecretUnavailable(f"credential source {path.name} is absent")
    # errors="replace" so a stray non-UTF-8 byte in an unrelated line cannot
    # take down a lookup for a label that parses cleanly.
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        match = _LINE_RE.match(stripped)
        if match is None:
            yield number, "", stripped
            continue
        yield number, match.group("label").strip(), match.group("value").strip()


def load_secret(
    label: str,
    *,
    path: Path | None = None,
    min_length: int = _MIN_KEY_LENGTH,
) -> Secret:
    """Return the value of ``label`` from the credential file.

    The label must appear exactly once at the top level; an ambiguous label is
    an error rather than a guess (``Access Key ID`` appears twice, which is why
    R2 credentials go through :func:`r2_credentials`).
    """

    source = path or CREDENTIAL_FILE
    found: list[str] = []
    for _number, line_label, value in _iter_labelled_lines(source):
        if line_label.casefold() == label.casefold() and value:
            found.append(value)
    if not found:
        raise SecretUnavailable(f"label {label!r} is not present in {source.name}")
    if len(found) > 1:
        raise SecretUnavailable(
            f"label {label!r} appears {len(found)} times in {source.name}; "
            "resolve it through a block-aware reader instead of guessing"
        )
    if len(found[0]) < min_length:
        raise SecretUnavailable(f"label {label!r} is too short to be a credential")
    return Secret(found[0], label=label)


def runpod_api_key(*, path: Path | None = None, env: dict[str, str] | None = None) -> Secret:
    """RunPod key from the credential file, else ``RUNPOD_API_KEY``.

    The environment fallback is declared, not silent: it is reported in the
    preflight receipt as ``source``.
    """

    environment = os.environ if env is None else env
    try:
        return load_secret(RUNPOD_LABEL, path=path)
    except SecretUnavailable as file_error:
        value = environment.get(RUNPOD_ENV_FALLBACK, "")
        if len(value) >= _MIN_KEY_LENGTH:
            return Secret(value, label=RUNPOD_ENV_FALLBACK)
        raise SecretUnavailable(
            f"no RunPod credential: {file_error} and {RUNPOD_ENV_FALLBACK} is unset or too short"
        ) from None


def runpod_api_key_source(*, path: Path | None = None, env: dict[str, str] | None = None) -> str:
    """Which surface supplied the RunPod key, for the receipt. Never the value."""

    return runpod_api_key(path=path, env=env).label


@dataclass(frozen=True, slots=True, repr=False)
class R2Credentials:
    """One R2 token block. ``endpoint_url`` is not secret; the keys are."""

    block: str
    access_key_id: Secret
    secret_access_key: Secret
    endpoint_url: str

    def __repr__(self) -> str:
        return f"R2Credentials(block={self.block!r}, endpoint_url={self.endpoint_url!r})"


def r2_credentials(*, block: str = "account", path: Path | None = None) -> R2Credentials:
    """Read one R2 token block from the ``Cloudflare R2`` heading.

    The file holds two blocks (``Account API Token`` and ``User API Tokens``)
    that both define ``Access Key ID`` and ``Secret Access Key``, so the block
    has to be named. A block that is missing any of its three fields is an
    error; nothing is inferred from the other block.
    """

    if block not in R2_BLOCK_LABELS:
        raise SecretUnavailable(
            f"unknown R2 block {block!r}; expected one of {sorted(R2_BLOCK_LABELS)}"
        )
    wanted = R2_BLOCK_LABELS[block]
    source = path or CREDENTIAL_FILE

    heading_seen = False
    inside_wanted = False
    access: str | None = None
    secret: str | None = None
    endpoint: str | None = None

    for _number, label, value in _iter_labelled_lines(source):
        folded = label.casefold()
        if folded == R2_HEADING.casefold():
            heading_seen = True
            continue
        if value.startswith("{"):
            # Any "<label>: {" line opens a block and closes the previous one.
            inside_wanted = heading_seen and folded == wanted.casefold()
            continue
        if not label and value.startswith("}"):
            if inside_wanted:
                break
            continue
        if not inside_wanted:
            continue
        if folded == R2_ACCESS_KEY_LABEL.casefold():
            access = value
        elif folded == R2_SECRET_KEY_LABEL.casefold():
            secret = value
        elif folded == R2_ENDPOINT_LABEL.casefold():
            endpoint = value

    if not heading_seen:
        raise SecretUnavailable(f"heading {R2_HEADING!r} is not present in {source.name}")

    missing = [
        name
        for name, found in (
            (R2_ACCESS_KEY_LABEL, access),
            (R2_SECRET_KEY_LABEL, secret),
            (R2_ENDPOINT_LABEL, endpoint),
        )
        if not found
    ]
    if missing:
        raise SecretUnavailable(
            f"R2 block {wanted!r} in {source.name} is missing: {', '.join(missing)}"
        )
    assert access is not None and secret is not None and endpoint is not None
    if not endpoint.lower().startswith("https://") or len(endpoint) < len("https://a.b"):
        raise SecretUnavailable(f"R2 endpoint for block {wanted!r} is not an https URL")
    return R2Credentials(
        block=block,
        access_key_id=Secret(access, label=f"{wanted}/{R2_ACCESS_KEY_LABEL}"),
        secret_access_key=Secret(secret, label=f"{wanted}/{R2_SECRET_KEY_LABEL}"),
        endpoint_url=endpoint.rstrip("/"),
    )


def worker_bearer(value: str) -> Secret:
    """Wrap the per-campaign worker bearer so it cannot reach a receipt."""

    return Secret(value, label="ARENA_WORKER_TOKEN")
