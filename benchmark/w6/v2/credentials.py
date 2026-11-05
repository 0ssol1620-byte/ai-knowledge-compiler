"""Credential loading for the W6 v2 pilot.

Pattern follows benchmark/sources/dart.py::load_dart_api_key: the secret is
parsed from a local labelled file or the environment and must never appear in
an error message, log line, report, or commit.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

DEFAULT_CREDENTIAL_FILE = Path("D:/Github_API.txt")

# OpenRouter keys look like sk-or-v1-<64 hex>; accept the general shape but do
# not hard-fail on future formats (any non-space token >= 20 chars).
_OPENROUTER_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])sk-or-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])"
)
_GENERIC_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_\-]{20,}(?![A-Za-z0-9_-])")


class CredentialError(ValueError):
    pass


def load_openrouter_key(
    *,
    environment: Mapping[str, str] | None = None,
    credential_file: Path | None = None,
) -> str:
    """Return the OpenRouter API key; raise CredentialError without leaking it."""

    values = os.environ if environment is None else environment
    direct = values.get("OPENROUTER_API_KEY", "").strip()
    if direct:
        return direct

    configured_file = credential_file
    if configured_file is None and values.get("W6_CREDENTIAL_FILE"):
        configured_file = Path(values["W6_CREDENTIAL_FILE"])
    if configured_file is None:
        configured_file = DEFAULT_CREDENTIAL_FILE

    try:
        text = Path(configured_file).read_text(encoding="utf-8-sig")
    except OSError:
        raise CredentialError(
            "credential file cannot be read (path withheld); set OPENROUTER_API_KEY instead"
        ) from None

    candidates: list[str] = []
    generic_candidates: list[str] = []
    for line in text.splitlines():
        if "openrouter" not in line.casefold().replace("_", "").replace("-", "").replace(" ", ""):
            continue
        candidates.extend(_OPENROUTER_TOKEN_PATTERN.findall(line))
        if not candidates:
            after_label = re.split(r"[:=,\t ]", line, maxsplit=1)
            if len(after_label) == 2 and after_label[1].strip():
                generic_candidates.extend(_GENERIC_TOKEN_PATTERN.findall(after_label[1]))
    key = candidates[0] if candidates else (generic_candidates[0] if generic_candidates else "")
    if not key:
        raise CredentialError(
            "no OpenRouter-labelled key found in credential file (value withheld)"
        )
    return key


def redact(value: str, visible: int = 3) -> str:
    """Safe-to-print representation for receipts (never the full secret)."""
    if len(value) <= visible + 4:
        return "***"
    return f"{value[:visible]}...({len(value)} chars)"
