"""Capability tokens: short-lived, scope-limited delegations of authority.

A capability token answers one question -- *may this bearer perform exactly
these actions until exactly this moment* -- without dragging the full session
along. A long-lived session mints a narrow, short-lived token; downstream
callers (export workers, search runners, other services) present the token and
hold no more power than the task needs. Lose the token and the blast radius is
a few scopes for a few minutes; lose the session and it is not.

The wire format is deliberately JWT-shaped but not a JWT: ``cap_v1`` is three
base64url parts, ``header.payload.signature``, signed with HMAC-SHA256 over a
purpose-derived key. The constraint that shaped every decision here is
*stdlib only*. This module sits in ``akc_cir``, which must stay importable by
tooling that cannot carry PyJWT or cryptography, and the primitive we need --
HMAC-SHA256 with constant-time comparison -- has been in ``hmac`` since before
this repository existed. Anything PyJWT would add (asymmetric keys, JWKS,
algorithm negotiation) is attack surface a token minted minutes ago does not
want.

Fail-closed rules the verifier enforces, in order: structure, then header, then
signature, and only once the bytes are authentic are the claims believed. An
expired token, an audience mismatch, a broken signature, and a revoked jti are
four different failures and are reported as such, because an operator debugging
a 401 needs to know whether the clock, the configuration, the bytes, or the
revocation list is wrong.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
from dataclasses import dataclass
from typing import Protocol

__all__ = [
    "CAPABILITY_SCOPES",
    "DEFAULT_TTL_SECONDS",
    "MAX_TTL_SECONDS",
    "TOKEN_TYPE",
    "Claims",
    "InMemoryRevocationStore",
    "RevocationStore",
    "TokenError",
    "mint",
    "require_scope",
    "verify",
]

#: Wire-format version. Appears in the JOSE-style header ``typ`` so a token
#: can identify its own scheme, and in error codes so a future cap_v2 can be
#: deployed alongside this one without ambiguity.
TOKEN_TYPE = "cap_v1"  # noqa: S105 - format label, not a secret

#: The complete scope vocabulary of cap_v1. Minting refuses anything outside
#: this set: an unknown or typo'd scope must fail loudly at issuance rather
#: than silently grant nothing and leave the caller wondering why access was
#: denied downstream.
CAPABILITY_SCOPES = frozenset(
    {
        "worlds:read",
        "search:run",
        "evidence:read",
        "export:run",
    }
)

DEFAULT_TTL_SECONDS = 900
MAX_TTL_SECONDS = 3600

_MAX_SUB_LENGTH = 255
_MAX_AUD_LENGTH = 255
_MAX_JTI_LENGTH = 128
#: Clock skew tolerated when checking iat. exp gets no leeway on the far side:
#: a capability that says it expired at T is expired from T onward.
_FUTURE_IAT_LEEWAY_SECONDS = 60

_ALGORITHM = "HS256"


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64_decode(part: str) -> bytes:
    padded = part + "=" * (-len(part) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _mac(secret: bytes, signing_input: str) -> str:
    digest = hmac.new(secret, signing_input.encode("ascii"), hashlib.sha256).digest()
    return _b64_encode(digest)


# The header never varies, so its base64url encoding is computed once. Every
# token this module mints shares these exact wire bytes.
_HEADER_PAYLOAD = json.dumps(
    {"alg": _ALGORITHM, "typ": TOKEN_TYPE}, separators=(",", ":"), sort_keys=True
)
_ENCODED_HEADER = _b64_encode(_HEADER_PAYLOAD.encode("utf-8"))


class TokenError(Exception):
    """A capability token failed verification, with a machine-readable cause.

    The codes partition cleanly enough to act on: ``TOKEN_MALFORMED`` means the
    bytes were never valid, ``BAD_SIGNATURE`` means they were altered or signed
    by someone else, ``TOKEN_EXPIRED`` and ``AUDIENCE_MISMATCH`` mean the token
    is genuine but not usable here/now, and ``JTI_REVOKED`` means it was
    genuinely issued and then withdrawn.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Claims:
    """What a verified token vouches for."""

    sub: str
    scopes: tuple[str, ...]
    aud: str
    iat: int
    exp: int
    jti: str

    @property
    def scope_set(self) -> frozenset[str]:
        return frozenset(self.scopes)


class RevocationStore(Protocol):
    """Where issued jti values go to die.

    A protocol, not a class, because revocation is deployment-specific: the API
    keeps an in-process set for tests and single-node deployments, while a
    multi-node deployment wants Redis or the database. Verifiers depend on the
    shape, never the storage.
    """

    def is_revoked(self, jti: str) -> bool: ...


class InMemoryRevocationStore:
    """Thread-safe process-local :class:`RevocationStore`."""

    def __init__(self) -> None:
        self._revoked: set[str] = set()
        self._lock = threading.Lock()

    def revoke(self, jti: str) -> None:
        if not jti:
            raise ValueError("jti is required to revoke")
        with self._lock:
            self._revoked.add(jti)

    def is_revoked(self, jti: str) -> bool:
        with self._lock:
            return jti in self._revoked


def mint(
    *,
    sub: str,
    scopes: list[str] | tuple[str, ...],
    aud: str,
    secret: bytes | str,
    now: int | float,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    jti: str | None = None,
) -> str:
    """Mint a cap_v1 token; deterministic given fixed inputs.

    Raises ValueError on any input that would silently weaken the token --
    unknown scopes, an empty subject or audience, or a ttl outside
    ``(0, MAX_TTL_SECONDS]``. Issuance is where mistakes must surface;
    verification should only ever see well-formed tokens.
    """
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    subject = sub.strip()
    audience = aud.strip()
    unique_scopes = tuple(dict.fromkeys(scopes))
    unknown = [scope for scope in unique_scopes if scope not in CAPABILITY_SCOPES]
    if not subject or len(subject) > _MAX_SUB_LENGTH:
        raise ValueError(f"sub must be 1..{_MAX_SUB_LENGTH} characters")
    if not audience or len(audience) > _MAX_AUD_LENGTH:
        raise ValueError(f"aud must be 1..{_MAX_AUD_LENGTH} characters")
    if not unique_scopes:
        raise ValueError("at least one scope is required")
    if unknown:
        raise ValueError(f"unknown capability scopes: {sorted(unknown)}")
    if not 0 < ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be within 1..{MAX_TTL_SECONDS}")
    token_id = jti if jti is not None else secrets.token_urlsafe(24)
    if not token_id or len(token_id) > _MAX_JTI_LENGTH:
        raise ValueError(f"jti must be 1..{_MAX_JTI_LENGTH} characters")

    issued_at = int(now)
    expires_at = issued_at + int(ttl_seconds)
    payload_json = json.dumps(
        {
            "sub": subject,
            "scopes": list(unique_scopes),
            "aud": audience,
            "iat": issued_at,
            "exp": expires_at,
            "jti": token_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    encoded_payload = _b64_encode(payload_json)
    signing_input = f"{_ENCODED_HEADER}.{encoded_payload}"
    signature = _mac(key, signing_input)
    return f"{signing_input}.{signature}"


def verify(
    token: str,
    *,
    aud: str,
    secret: bytes | str,
    now: int | float,
    revocation_store: RevocationStore | None = None,
) -> Claims:
    """Verify a cap_v1 token against audience, time, and revocation state.

    Checks run fail-closed and in order: structure, header, constant-time
    signature comparison, claim well-formedness, expiry (``now >= exp``
    rejects), audience equality, future-issued guard, then jti revocation.
    Every failure raises :class:`TokenError` with a specific code -- the
    caller gets the same answer whether the token came from an attacker or a
    buggy client, and more diagnostic detail than a bare 401.
    """
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    parts = token.split(".")
    if len(parts) != 3 or any(not part for part in parts):
        raise TokenError("TOKEN_MALFORMED")
    encoded_header, encoded_payload, encoded_signature = parts

    try:
        header = json.loads(_b64_decode(encoded_header))
    except (ValueError, UnicodeDecodeError) as exc:  # binascii.Error subclasses ValueError
        raise TokenError("TOKEN_MALFORMED") from exc
    if (
        not isinstance(header, dict)
        or header.get("alg") != _ALGORITHM
        or header.get("typ") != TOKEN_TYPE
    ):
        # No algorithm negotiation exists in cap_v1: anything but HS256 is not
        # a downgrade attempt to consider, it is simply not this format.
        raise TokenError("TOKEN_MALFORMED")

    expected_signature = _mac(key, f"{encoded_header}.{encoded_payload}")
    supplied_signature = encoded_signature.encode("ascii")
    if not hmac.compare_digest(expected_signature.encode("ascii"), supplied_signature):
        raise TokenError("BAD_SIGNATURE")

    try:
        raw_claims = json.loads(_b64_decode(encoded_payload))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TokenError("BAD_SIGNATURE") from exc
    # The bytes authenticate; now the claims themselves must be sane.
    if not isinstance(raw_claims, dict):
        raise TokenError("TOKEN_MALFORMED")
    subject = raw_claims.get("sub")
    scopes = raw_claims.get("scopes")
    audience = raw_claims.get("aud")
    issued_at = raw_claims.get("iat")
    expires_at = raw_claims.get("exp")
    token_id = raw_claims.get("jti")
    if (
        not isinstance(subject, str)
        or not subject
        or len(subject) > _MAX_SUB_LENGTH
        or not isinstance(audience, str)
        or not audience
        or len(audience) > _MAX_AUD_LENGTH
        or not isinstance(token_id, str)
        or not token_id
        or len(token_id) > _MAX_JTI_LENGTH
        or not isinstance(scopes, list)
        or not scopes
        or any(not isinstance(scope, str) or scope not in CAPABILITY_SCOPES for scope in scopes)
        or not isinstance(issued_at, int)
        or isinstance(issued_at, bool)
        or not isinstance(expires_at, int)
        or isinstance(expires_at, bool)
    ):
        raise TokenError("TOKEN_MALFORMED")
    if expires_at <= issued_at:
        raise TokenError("TOKEN_MALFORMED")

    moment = int(now)
    if expires_at <= moment:
        raise TokenError("TOKEN_EXPIRED")
    if audience != aud.strip():
        raise TokenError("AUDIENCE_MISMATCH")
    if issued_at > moment + _FUTURE_IAT_LEEWAY_SECONDS:
        # A token claiming to be minted in the future is either clock drift or
        # a replay under construction; neither is worth honouring beyond a
        # small skew allowance.
        raise TokenError("TOKEN_MALFORMED")
    if revocation_store is not None and revocation_store.is_revoked(token_id):
        raise TokenError("JTI_REVOKED")

    return Claims(
        sub=subject,
        scopes=tuple(dict.fromkeys(scopes)),
        aud=audience,
        iat=issued_at,
        exp=expires_at,
        jti=token_id,
    )


def require_scope(claims: Claims, scope: str) -> Claims:
    """Return ``claims`` if it carries ``scope``, else refuse loudly.

    The gate every consumer of a verified token should sit behind. Returning
    the claims (rather than None) lets handlers write
    ``claims = require_scope(claims, "export:run")`` and keep flowing.
    """
    if scope not in claims.scope_set:
        raise TokenError("SCOPE_INSUFFICIENT")
    return claims
