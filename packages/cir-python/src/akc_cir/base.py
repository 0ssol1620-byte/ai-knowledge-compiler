"""Shared primitives for versioned, deterministic contracts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


def to_camel(value: str) -> str:
    """Convert internal snake_case names to the public camelCase wire format."""
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


class ContractModel(BaseModel):
    """Strict immutable base used by every public contract."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
StableId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=256),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class TimestampedModel(ContractModel):
    """Contract with a required timezone-aware timestamp."""

    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


def canonical_json(value: Any) -> str:
    """Serialize a JSON-compatible value reproducibly."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_digest(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def ensure_safe_identifier(value: str) -> str:
    """Validate IDs used in generated URNs, paths, and audit records."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{1,254}[A-Za-z0-9]", value):
        raise ValueError("identifier contains unsafe characters")
    return value
