"""Authorization receipts: the only thing that lets a paid phase run.

ARENA_CONTRACT.md section 11 D6. A receipt is a JSON file under
``receipts/authorizations/`` that validates against
``arena/core/schemas/authorization-receipt.schema.json``. Loading is fail
closed: one malformed file in the directory raises, because a gate that
skips what it cannot read is the silent fallback the campaign forbids.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, Final

from jsonschema import Draft202012Validator

SCHEMA_ID: Final = "tavonel.arena.authorization-receipt.v1"
SCHEMA_PATH: Final = (
    Path(__file__).resolve().parent / "schemas" / "authorization-receipt.schema.json"
)
PHASES: Final = ("phase1_canary", "phase2_full_run", "phase3_opus_full_run", "builder_pod")
_TIMESTAMP_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"


class AuthorizationError(ValueError):
    """A receipt file is missing, malformed or contradicts the campaign."""


@cache
def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _parse_timestamp(value: str, *, field: str, path: Path) -> datetime:
    try:
        return datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError as exc:
        raise AuthorizationError(
            f"{path}: {field} is not an ISO-8601 UTC timestamp: {value!r}"
        ) from exc


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise AuthorizationError("now must be timezone-aware")
    return moment.astimezone(UTC)


def format_timestamp(moment: datetime) -> str:
    """``YYYY-MM-DDTHH:MM:SSZ`` for a timezone-aware datetime."""

    return _as_utc(moment).strftime(_TIMESTAMP_FORMAT)


@dataclass(frozen=True, slots=True)
class AuthorizationReceipt:
    path: Path
    sha256: str
    campaign_id: str
    phase: str
    authorized_by: str
    authorized_at: datetime
    expires_at: datetime | None
    max_usd: float
    model_keys: tuple[str, ...] | None  # None means "*"
    statement: str

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and _as_utc(now) >= self.expires_at

    def is_not_yet_valid(self, now: datetime) -> bool:
        """True before ``authorized_at`` (ARENA_CONTRACT 11.5 D32).

        A receipt dated in the future has not been given yet. Reading it as
        valid would let a post-dated file authorize spend today, which is the
        same failure as an expired one from the other side.
        """

        return _as_utc(now) < self.authorized_at

    def covers(self, *, phase: str, model_key: str | None, now: datetime) -> bool:
        """True when this receipt authorizes ``phase`` for ``model_key`` at ``now``."""

        if phase not in PHASES:
            raise AuthorizationError(f"unknown phase {phase!r}")
        if self.phase != phase:
            return False
        # 11.5 D32: the window is closed on both sides.
        if self.is_not_yet_valid(now) or self.is_expired(now):
            return False
        if self.model_keys is None:
            return True
        if model_key is None:
            # A model-scoped receipt cannot authorize a campaign-wide action.
            return False
        return model_key in self.model_keys

    def to_record(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "campaign_id": self.campaign_id,
            "phase": self.phase,
            "authorized_by": self.authorized_by,
            "authorized_at": format_timestamp(self.authorized_at),
            "expires_at": None if self.expires_at is None else format_timestamp(self.expires_at),
            "max_usd": self.max_usd,
            "model_keys": "*" if self.model_keys is None else list(self.model_keys),
            "statement": self.statement,
        }


def parse_authorization(path: Path, *, campaign_id: str) -> AuthorizationReceipt:
    """Parse and validate one receipt file. Raises on any defect."""

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AuthorizationError(f"{path}: cannot read: {exc}") from exc
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorizationError(f"{path}: not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(record, dict):
        raise AuthorizationError(f"{path}: top level must be an object")
    errors = sorted(_validator().iter_errors(record), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        location = "/".join(str(p) for p in first.path) or "<root>"
        raise AuthorizationError(f"{path}: schema violation at {location}: {first.message}")
    if record["campaign_id"] != campaign_id:
        raise AuthorizationError(
            f"{path}: campaign_id {record['campaign_id']!r} is not {campaign_id!r}"
        )
    authorized_at = _parse_timestamp(record["authorized_at"], field="authorized_at", path=path)
    expires_raw = record["expires_at"]
    expires_at = (
        None
        if expires_raw is None
        else _parse_timestamp(expires_raw, field="expires_at", path=path)
    )
    if expires_at is not None and expires_at <= authorized_at:
        raise AuthorizationError(f"{path}: expires_at must be after authorized_at")
    keys_raw = record["model_keys"]
    model_keys = None if keys_raw == "*" else tuple(str(k) for k in keys_raw)
    return AuthorizationReceipt(
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        campaign_id=record["campaign_id"],
        phase=record["phase"],
        authorized_by=record["authorized_by"],
        authorized_at=authorized_at,
        expires_at=expires_at,
        max_usd=float(record["max_usd"]),
        model_keys=model_keys,
        statement=record["statement"],
    )


def load_authorizations(
    directory: Path, *, campaign_id: str
) -> tuple[AuthorizationReceipt, ...]:
    """Every ``*.json`` under ``directory``; a missing directory means none.

    Any file that fails to parse raises: the caller must not proceed on a
    directory it cannot fully read.
    """

    if not directory.exists():
        return ()
    if not directory.is_dir():
        raise AuthorizationError(f"{directory} is not a directory")
    return tuple(
        parse_authorization(path, campaign_id=campaign_id)
        for path in sorted(directory.glob("*.json"))
    )


def select_authorization(
    receipts: Sequence[AuthorizationReceipt],
    *,
    phase: str,
    model_key: str | None,
    now: datetime,
    required_usd: float,
) -> AuthorizationReceipt | None:
    """The receipt that covers the action and its cost, or None (blocked)."""

    if required_usd < 0:
        raise AuthorizationError("required_usd must not be negative")
    candidates = [
        r
        for r in receipts
        if r.covers(phase=phase, model_key=model_key, now=now) and r.max_usd >= required_usd
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r.max_usd, r.authorized_at))
