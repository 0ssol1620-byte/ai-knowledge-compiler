"""Fail-closed OIDC/PKCE and TOTP MFA security primitives.

This module deliberately has no FastAPI or database dependency.  Protocol
validation can therefore be exercised against deterministic HTTP transports
and locally signed JWTs without claiming that an external IdP was verified.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken

from akc_api.settings import Settings

_MAX_OIDC_DOCUMENT_BYTES = 1024 * 1024
_MAX_JWKS_KEYS = 50
_TOTP_PERIOD_SECONDS = 30
_TOTP_DIGITS = 6


class OidcProtocolError(RuntimeError):
    """An OIDC response failed transport or cryptographic validation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OidcDiscovery:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    token_endpoint_auth_methods: frozenset[str]


@dataclass(frozen=True)
class OidcClaims:
    issuer: str
    subject: str
    email: str
    display_name: str


class OidcClient:
    """Minimal verified authorization-code client with discovery and JWKS."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not settings.oidc_enabled:
            raise ValueError("OIDC is disabled")
        self._settings = settings
        self.issuer = (settings.oidc_issuer_url or "").rstrip("/")
        self.client_id = settings.oidc_client_id or ""
        self.redirect_uri = settings.oidc_redirect_uri or ""
        self._client = httpx.AsyncClient(
            timeout=settings.oidc_http_timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )
        self._discovery: tuple[float, OidcDiscovery] | None = None
        self._jwks: tuple[float, tuple[dict[str, Any], ...]] | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    def _endpoint(self, raw: object) -> str:
        if not isinstance(raw, str):
            raise OidcProtocolError("OIDC_DISCOVERY_INVALID")
        parsed = urlsplit(raw)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.hostname.casefold() not in self._settings.allowed_oidc_endpoint_hosts
        ):
            raise OidcProtocolError("OIDC_ENDPOINT_NOT_ALLOWED")
        return raw

    async def _json_document(self, url: str, *, form: dict[str, str] | None = None) -> Any:
        try:
            if form is None:
                response = await self._client.get(
                    url,
                    headers={"Accept": "application/json"},
                )
            else:
                if self._settings.oidc_client_secret:
                    response = await self._client.post(
                        url,
                        data=form,
                        auth=httpx.BasicAuth(
                            self.client_id,
                            self._settings.oidc_client_secret,
                        ),
                        headers={"Accept": "application/json"},
                    )
                else:
                    response = await self._client.post(
                        url,
                        data=form,
                        headers={"Accept": "application/json"},
                    )
            response.raise_for_status()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcProtocolError("OIDC_PROVIDER_UNAVAILABLE") from exc
        if len(response.content) > _MAX_OIDC_DOCUMENT_BYTES:
            raise OidcProtocolError("OIDC_RESPONSE_TOO_LARGE")
        try:
            return response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OidcProtocolError("OIDC_RESPONSE_INVALID") from exc

    async def discovery(self, *, force: bool = False) -> OidcDiscovery:
        now = time.monotonic()
        if not force and self._discovery is not None and self._discovery[0] > now:
            return self._discovery[1]
        raw = await self._json_document(f"{self.issuer}/.well-known/openid-configuration")
        if not isinstance(raw, dict) or raw.get("issuer") != self.issuer:
            raise OidcProtocolError("OIDC_ISSUER_MISMATCH")
        methods_value = raw.get("token_endpoint_auth_methods_supported", [])
        methods = (
            frozenset(str(item) for item in methods_value)
            if isinstance(methods_value, list)
            else frozenset()
        )
        required_method = "client_secret_basic" if self._settings.oidc_client_secret else "none"
        if methods and required_method not in methods:
            raise OidcProtocolError("OIDC_CLIENT_AUTH_UNSUPPORTED")
        result = OidcDiscovery(
            issuer=self.issuer,
            authorization_endpoint=self._endpoint(raw.get("authorization_endpoint")),
            token_endpoint=self._endpoint(raw.get("token_endpoint")),
            jwks_uri=self._endpoint(raw.get("jwks_uri")),
            token_endpoint_auth_methods=methods,
        )
        self._discovery = (
            now + self._settings.oidc_cache_ttl_seconds,
            result,
        )
        return result

    async def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
    ) -> str:
        discovery = await self.discovery()
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": " ".join(self._settings.oidc_scope_values),
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{discovery.authorization_endpoint}?{query}"

    async def _load_jwks(self, *, force: bool = False) -> tuple[dict[str, Any], ...]:
        now = time.monotonic()
        if not force and self._jwks is not None and self._jwks[0] > now:
            return self._jwks[1]
        discovery = await self.discovery(force=force)
        raw = await self._json_document(discovery.jwks_uri)
        keys_value = raw.get("keys") if isinstance(raw, dict) else None
        if (
            not isinstance(keys_value, list)
            or not keys_value
            or len(keys_value) > _MAX_JWKS_KEYS
            or any(not isinstance(item, dict) for item in keys_value)
        ):
            raise OidcProtocolError("OIDC_JWKS_INVALID")
        keys = tuple(cast(dict[str, Any], item) for item in keys_value)
        self._jwks = (now + self._settings.oidc_cache_ttl_seconds, keys)
        return keys

    async def _verification_key(self, kid: str, alg: str) -> Any:
        for force in (False, True):
            keys = await self._load_jwks(force=force)
            matches = [
                item
                for item in keys
                if hmac.compare_digest(str(item.get("kid", "")), kid)
                and item.get("use", "sig") == "sig"
                and item.get("alg", alg) == alg
            ]
            if len(matches) == 1:
                try:
                    return jwt.PyJWK.from_dict(matches[0], algorithm=alg).key
                except (jwt.PyJWTError, ValueError) as exc:
                    raise OidcProtocolError("OIDC_JWK_INVALID") from exc
            if len(matches) > 1:
                raise OidcProtocolError("OIDC_JWK_AMBIGUOUS")
        raise OidcProtocolError("OIDC_JWK_NOT_FOUND")

    @staticmethod
    def _validate_at_hash(*, access_token: str, at_hash: str, algorithm: str) -> None:
        digest_name = {
            "RS256": "sha256",
            "ES256": "sha256",
            "RS384": "sha384",
            "ES384": "sha384",
            "RS512": "sha512",
            "ES512": "sha512",
        }.get(algorithm)
        if digest_name is None:
            raise OidcProtocolError("OIDC_ALGORITHM_DENIED")
        digest = hashlib.new(digest_name, access_token.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b"=").decode()
        if not hmac.compare_digest(expected, at_hash):
            raise OidcProtocolError("OIDC_AT_HASH_INVALID")

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        expected_nonce: str,
    ) -> OidcClaims:
        discovery = await self.discovery()
        raw = await self._json_document(
            discovery.token_endpoint,
            form={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "code_verifier": code_verifier,
            },
        )
        if not isinstance(raw, dict):
            raise OidcProtocolError("OIDC_TOKEN_RESPONSE_INVALID")
        id_token = raw.get("id_token")
        access_token = raw.get("access_token")
        if not isinstance(id_token, str) or not isinstance(access_token, str):
            raise OidcProtocolError("OIDC_TOKEN_RESPONSE_INVALID")
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise OidcProtocolError("OIDC_ID_TOKEN_INVALID") from exc
        kid = header.get("kid")
        algorithm = header.get("alg")
        if (
            not isinstance(kid, str)
            or not kid
            or not isinstance(algorithm, str)
            or algorithm not in self._settings.oidc_algorithm_values
        ):
            raise OidcProtocolError("OIDC_ALGORITHM_DENIED")
        key = await self._verification_key(kid, algorithm)
        try:
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=[algorithm],
                issuer=self.issuer,
                audience=self.client_id,
                options={
                    "require": [
                        "exp",
                        "iat",
                        "iss",
                        "aud",
                        "sub",
                        "nonce",
                        "email",
                        "email_verified",
                    ]
                },
                leeway=30,
            )
        except jwt.PyJWTError as exc:
            raise OidcProtocolError("OIDC_ID_TOKEN_INVALID") from exc
        nonce = claims.get("nonce")
        if not isinstance(nonce, str) or not hmac.compare_digest(nonce, expected_nonce):
            raise OidcProtocolError("OIDC_NONCE_INVALID")
        audiences = claims.get("aud")
        if (
            isinstance(audiences, list)
            and len(audiences) > 1
            and claims.get("azp") != self.client_id
        ):
            raise OidcProtocolError("OIDC_AZP_INVALID")
        if claims.get("email_verified") is not True:
            raise OidcProtocolError("OIDC_EMAIL_NOT_VERIFIED")
        subject = claims.get("sub")
        email = claims.get("email")
        if (
            not isinstance(subject, str)
            or not subject
            or len(subject) > 255
            or not isinstance(email, str)
            or not email
            or len(email) > 320
        ):
            raise OidcProtocolError("OIDC_CLAIMS_INVALID")
        at_hash = claims.get("at_hash")
        if isinstance(at_hash, str):
            self._validate_at_hash(
                access_token=access_token,
                at_hash=at_hash,
                algorithm=algorithm,
            )
        display = claims.get("name") or claims.get("preferred_username") or email
        return OidcClaims(
            issuer=self.issuer,
            subject=subject,
            email=email,
            display_name=str(display)[:200],
        )


class OidcTransactionCipher:
    """Encrypt PKCE verifier/nonce and authenticate opaque state."""

    def __init__(self, settings: Settings) -> None:
        self._fernet = Fernet(settings.effective_oidc_transaction_encryption_key.encode("ascii"))
        self._state_secret = settings.effective_oidc_state_hmac_secret.encode("utf-8")

    def new(self) -> tuple[str, str, str, bytes]:
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        encrypted = self._fernet.encrypt(
            json.dumps(
                {"nonce": nonce, "verifier": verifier},
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        return state, nonce, challenge, encrypted

    def state_digest(self, state: str) -> str:
        return hmac.new(
            self._state_secret,
            state.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def decrypt(self, payload: bytes) -> tuple[str, str]:
        try:
            raw = json.loads(self._fernet.decrypt(payload))
            nonce = raw["nonce"]
            verifier = raw["verifier"]
        except (InvalidToken, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise OidcProtocolError("OIDC_TRANSACTION_INVALID") from exc
        if not isinstance(nonce, str) or not isinstance(verifier, str):
            raise OidcProtocolError("OIDC_TRANSACTION_INVALID")
        return nonce, verifier


@dataclass(frozen=True)
class MfaTokenClaims:
    user_id: str
    tenant_id: str
    roles: tuple[str, ...]
    purpose: str
    token_id: str


class MfaSecurity:
    """TOTP, recovery-code, encrypted seed, and pending-token operations."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._fernet = Fernet(settings.effective_mfa_encryption_key.encode("ascii"))
        self._recovery_secret = settings.effective_mfa_recovery_hmac_secret.encode("utf-8")

    def encrypt_secret(self, secret: str) -> bytes:
        return self._fernet.encrypt(secret.encode("ascii"))

    def decrypt_secret(self, payload: bytes) -> str:
        try:
            return self._fernet.decrypt(payload).decode("ascii")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise ValueError("invalid MFA seed ciphertext") from exc

    @staticmethod
    def generate_totp_secret() -> str:
        return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")

    @staticmethod
    def _totp(secret: str, step: int) -> str:
        padded = secret + ("=" * (-len(secret) % 8))
        key = base64.b32decode(padded, casefold=True)
        digest = hmac.new(
            key,
            struct.pack(">Q", step),
            hashlib.sha1,
        ).digest()
        offset = digest[-1] & 0x0F
        binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
        return f"{binary % (10**_TOTP_DIGITS):0{_TOTP_DIGITS}d}"

    @classmethod
    def matching_totp_step(
        cls,
        secret: str,
        code: str,
        *,
        at: datetime | None = None,
    ) -> int | None:
        if len(code) != _TOTP_DIGITS or not code.isascii() or not code.isdigit():
            return None
        moment = at or datetime.now(UTC)
        current = int(moment.timestamp()) // _TOTP_PERIOD_SECONDS
        for step in (current - 1, current, current + 1):
            if hmac.compare_digest(cls._totp(secret, step), code):
                return step
        return None

    @classmethod
    def totp_code(
        cls,
        secret: str,
        *,
        at: datetime | None = None,
    ) -> str:
        """Generate a code for deterministic tests and trusted authenticator tooling."""

        moment = at or datetime.now(UTC)
        step = int(moment.timestamp()) // _TOTP_PERIOD_SECONDS
        return cls._totp(secret, step)

    def recovery_digest(self, code: str) -> str:
        normalized = code.replace("-", "").strip().upper()
        return hmac.new(
            self._recovery_secret,
            normalized.encode("ascii", errors="ignore"),
            hashlib.sha256,
        ).hexdigest()

    def generate_recovery_codes(self, *, count: int = 10) -> tuple[list[str], list[str]]:
        plaintext: list[str] = []
        digests: list[str] = []
        for _ in range(count):
            raw = secrets.token_hex(8).upper()
            code = "-".join(raw[index : index + 4] for index in range(0, 16, 4))
            plaintext.append(code)
            digests.append(self.recovery_digest(code))
        return plaintext, digests

    def issue_pending_token(
        self,
        *,
        user_id: str,
        tenant_id: str,
        roles: list[str],
        purpose: str,
    ) -> tuple[str, str, datetime]:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._settings.mfa_challenge_ttl_seconds)
        token_id = secrets.token_urlsafe(24)
        payload = {
            "sub": user_id,
            "tid": tenant_id,
            "roles": roles,
            "purpose": purpose,
            "jti": token_id,
            "typ": "mfa_pending",
            "iss": self._settings.jwt_issuer,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        token = jwt.encode(
            payload,
            self._settings.jwt_secret,
            algorithm="HS256",
        )
        return token, self.pending_token_digest(token_id), expires_at

    def decode_pending_token(self, token: str) -> MfaTokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret,
                algorithms=["HS256"],
                issuer=self._settings.jwt_issuer,
                options={
                    "require": [
                        "exp",
                        "iat",
                        "iss",
                        "sub",
                        "tid",
                        "jti",
                        "purpose",
                    ]
                },
            )
            if payload.get("typ") != "mfa_pending":
                raise jwt.InvalidTokenError("invalid token type")
            purpose = str(payload["purpose"])
            if purpose not in {"enroll", "challenge"}:
                raise jwt.InvalidTokenError("invalid MFA purpose")
            return MfaTokenClaims(
                user_id=str(payload["sub"]),
                tenant_id=str(payload["tid"]),
                roles=tuple(str(role) for role in payload.get("roles", [])),
                purpose=purpose,
                token_id=str(payload["jti"]),
            )
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid pending MFA token") from exc

    def pending_token_digest(self, token_id: str) -> str:
        return hmac.new(
            self._recovery_secret,
            f"pending:{token_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
