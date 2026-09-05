"""Hashing, atomic writes and the secret-free guard shared by lane B1.

ARENA_CONTRACT section 9 requires that receipts are validated by a secret-free
check and that every file write is atomic (write ``.tmp`` -> fsync -> hash ->
``os.replace``). Both rules are enforced here so no caller has to remember them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

__all__ = [
    "IDENTIFIER_FIELDS",
    "SecretLeak",
    "assert_secret_free",
    "atomic_write_bytes",
    "canonical_json_bytes",
    "canonical_sha256",
    "iter_jsonl",
    "read_json",
    "register_live_secret",
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
    "timestamp_slug",
    "utc_now_iso",
    "write_json_atomic",
    "write_jsonl_append",
]

SHA256_PREFIX: Final = "sha256:"

# ARENA_CONTRACT section 9: reject strings that look like credential material.
_SECRET_PREFIXES: Final = ("rpa_", "hf_", "sk-", "ghp_", "gho_", "github_pat_", "AKIA")
# A long opaque run that mixes case and digits is a token shape. Lowercase-only
# runs (sha256 hex, pod ids, model keys) and uppercase-only runs (the campaign
# id, GPU pool names) deliberately do not match.
#
# ``/`` is NOT part of the run. An object key such as
# ``bundles/TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1/glm_ocr/arena-bundle.tar.gz``
# is 94 mixed-case characters end to end and would be reported as a credential,
# which fails closed in the wrong direction: it blocks a receipt that carries
# no secret at all. Every credential this campaign handles (``rpa_`` keys, hex
# R2 keys, SigV4 signatures) is slash-free, and the two things that do use
# slashes -- a presigned query string and a live credential value -- are caught
# exactly by ``_PRESIGNED_RE`` and ``_LIVE_SECRETS`` above.
_OPAQUE_TOKEN_RE: Final = re.compile(r"[A-Za-z0-9+=_-]{40,}")
_PRESIGNED_RE: Final = re.compile(r"(?i)[?&]X-Amz-(Signature|Credential)=")

# Record fields whose value the campaign derives from a source document's own
# name, and which therefore cannot be a credential no matter what shape they
# take. The 2026-09-03 GLM-OCR canary aborted on its fourteenth page because
# the sample id
# ``parsebench:docs/layout/Informe-Anual-Consolidado-2024-ENG-compressed_p14#p0``
# carries a 49-character mixed-case run -- a Spanish annual report's filename,
# reported as a credential.
#
# Only the *structural* token-shape rule is lifted, and only for these names.
# The credential prefixes, the presigned-URL signature and the exact values of
# the secrets this process actually loaded are still checked on every field:
# a ``sample_id`` holding ``rpa_...`` is still a leak. Every free-text field --
# ``error_message``, notes, log lines -- keeps the full rule set, and so does
# any string checked without a field name around it.
IDENTIFIER_FIELDS: Final = frozenset(
    {
        "sample_id",
        "case_key",
        "inference_job_id",
        "image_path",
        "source_relative_path",
        "input_relative_path",
    }
)
_SHA256_FIELD_SUFFIX: Final = "_sha256"


def _is_identifier_field(name: str) -> bool:
    """Is ``name`` a campaign-derived identifier rather than free text?

    ``*_sha256`` is included because a digest is 64 characters of hex that the
    campaign computed itself, and ``register_live_secret`` already catches the
    one credential that shares that shape (an R2 secret access key) by value.
    """

    return name in IDENTIFIER_FIELDS or name.endswith(_SHA256_FIELD_SUFFIX)


class SecretLeak(RuntimeError):
    """A value that looks like credential material reached a persisted record."""


# Exact values of every credential this process has loaded. The structural
# rules above cannot catch everything -- a Cloudflare R2 secret access key is 64
# lowercase hex characters, which is byte-for-byte the shape of a sha256 digest
# and of an inference_job_id. So every Secret registers its value here at
# construction, and the guard checks for it exactly. The set lives in memory
# only; nothing ever writes, hashes or logs its contents.
_LIVE_SECRETS: set[str] = set()

# Only values long and varied enough to be a real credential are registered.
# The check is a substring search, so a short or low-entropy value would match
# unrelated content and raise on a legitimate receipt -- which fails closed in
# the wrong direction: it blocks the campaign while protecting nothing. The
# credentials this campaign actually handles are 32 characters (R2 access key
# id), 50 (RunPod key) and 64 (R2 secret access key), so 24 is a floor no real
# credential falls below.
_MIN_REGISTERED_LENGTH: Final = 24
_MIN_REGISTERED_DISTINCT_CHARS: Final = 5


def register_live_secret(value: str) -> None:
    """Record a credential value so the guard can catch it verbatim.

    Values too short or too repetitive to be a credential are ignored rather
    than registered: ``"a" * 22`` is a substring of a great many legitimate
    hashes and revisions, and registering it would turn every receipt that
    mentions one into a false leak report.
    """

    if not isinstance(value, str) or len(value) < _MIN_REGISTERED_LENGTH:
        return
    if len(set(value)) < _MIN_REGISTERED_DISTINCT_CHARS:
        return
    _LIVE_SECRETS.add(value)


def _carries_prefix(text: str, prefix: str) -> bool:
    """Does ``prefix`` start a token in ``text``? (D88)

    A bare substring test read three ordinary words as credentials, because
    ``disk-``, ``task-`` and ``mask-`` all end in ``sk-``. A container log
    line quoting one of them killed the driver that was trying to record it.

    A credential begins where a token begins, so the character before it must
    not be a letter or a digit. Everything a real key sits behind -- the start
    of the value, a space, a quote, ``=``, ``:``, ``(`` -- still matches.
    """

    start = text.find(prefix)
    while start != -1:
        if start == 0 or not text[start - 1].isalnum():
            return True
        start = text.find(prefix, start + 1)
    return False


def _looks_opaque(candidate: str) -> bool:
    has_upper = any(character.isupper() for character in candidate)
    has_lower = any(character.islower() for character in candidate)
    has_digit = any(character.isdigit() for character in candidate)
    return has_upper and has_lower and has_digit


def assert_secret_free(value: object, *, context: str) -> None:
    """Raise ``SecretLeak`` if ``value`` contains anything token-shaped.

    The check is intentionally structural, not a denylist of known keys: a
    receipt must never carry a credential even for a provider we have not met.

    It runs per field, because the token-shape heuristic is only safe where the
    value could plausibly be a credential. Under one of the
    :data:`IDENTIFIER_FIELDS` names -- or any ``*_sha256`` -- the value is a
    campaign-derived identifier and that one rule is lifted; everything else
    still applies there, and every other field keeps the full rule set.
    """

    for field, text in _iter_fields(value):
        for live in _LIVE_SECRETS:
            if live in text:
                raise SecretLeak(
                    f"{context}: value contains a credential this process loaded "
                    f"({len(live)} characters, withheld)"
                )
        for prefix in _SECRET_PREFIXES:
            if _carries_prefix(text, prefix):
                raise SecretLeak(
                    f"{context}: value carries the {prefix!r} credential prefix"
                    + ("" if field is None else f" (field {field!r})")
                )
        if _PRESIGNED_RE.search(text):
            raise SecretLeak(f"{context}: value carries a presigned-URL signature")
        if field is not None and _is_identifier_field(field):
            continue
        for match in _OPAQUE_TOKEN_RE.finditer(text):
            candidate = match.group(0)
            if _looks_opaque(candidate):
                raise SecretLeak(
                    f"{context}: value carries a {len(candidate)}-character opaque token"
                    + ("" if field is None else f" (field {field!r})")
                )


def _iter_fields(value: object, field: str | None = None) -> Iterator[tuple[str | None, str]]:
    """Every string in ``value``, paired with the field name it sits under.

    A mapping key is itself checked, under no field name: a key is written by
    this codebase, never by a provider, so it is held to the full rule set.
    ``field`` is inherited by nested values so a list of digests under
    ``weights_sha256`` is treated the same as a single one.
    """

    if isinstance(value, str):
        yield field, value
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                yield None, key
                yield from _iter_fields(item, key)
            else:
                yield from _iter_fields(item, field)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _iter_fields(item, field)


def canonical_json_bytes(value: object) -> bytes:
    """Canonical JSON exactly as ARENA_CONTRACT section 2 defines it."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def canonical_sha256(value: object) -> str:
    """Bare lowercase hex digest of the canonical JSON of ``value``."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return SHA256_PREFIX + hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Digest of ``text`` encoded UTF-8.

    Every raw model output is persisted as UTF-8 bytes, so this is the one
    encoding a ``raw_output_sha256`` may be computed over.
    """

    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return SHA256_PREFIX + digest.hexdigest()


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_slug(moment: datetime | None = None) -> str:
    """Filename-safe UTC stamp, e.g. ``20260903T131502Z``."""

    return (moment or datetime.now(tz=UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def atomic_write_bytes(path: Path, data: bytes) -> str:
    """Write ``data`` to ``path`` atomically and return its ``sha256:`` digest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed explicitly below
        mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    temporary = Path(handle.name)
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        digest = sha256_bytes(data)
        os.replace(temporary, path)
    except BaseException:
        handle.close()
        temporary.unlink(missing_ok=True)
        raise
    return digest


def write_json_atomic(path: Path, value: object, *, context: str | None = None) -> str:
    """Secret-check, then atomically write ``value`` as sorted-key UTF-8 JSON."""

    assert_secret_free(value, context=context or str(path.name))
    body = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    return atomic_write_bytes(path, body.encode("utf-8"))


def write_jsonl_append(path: Path, value: object, *, context: str | None = None) -> None:
    """Append one secret-checked record to an append-only JSONL file."""

    assert_secret_free(value, context=context or str(path.name))
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path) -> Iterator[object]:
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{number} is not valid JSON") from exc
