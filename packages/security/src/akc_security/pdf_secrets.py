"""Ephemeral, tenant-bound secret storage for encrypted PDF passwords.

Passwords are never represented by a database model, loggable dataclass, command
line argument, or environment variable.  Development may keep a bounded
``bytearray`` in process memory; distributed deployments use an application-
encrypted Redis value with a short server-enforced TTL.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, Self, cast
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from redis.asyncio import Redis
from redis.exceptions import RedisError

_MAX_PASSWORD_BYTES = 1024
_MIN_TTL_SECONDS = 30
_MAX_TTL_SECONDS = 15 * 60
_MIN_ATTEMPTS = 1
_MAX_ATTEMPTS = 5
_KEY_PREFIX = b"akc:pdf-password:v1:"

_PUT_SCRIPT = """
redis.call('HSET', KEYS[1],
  'ciphertext', ARGV[1],
  'generation', ARGV[2],
  'attempts', 0,
  'max_attempts', ARGV[3])
redis.call('PEXPIRE', KEYS[1], ARGV[4])
return 1
"""

_ACQUIRE_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then
  return {}
end
local attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
local maximum = tonumber(redis.call('HGET', KEYS[1], 'max_attempts'))
if attempts > maximum then
  redis.call('DEL', KEYS[1])
  return {'EXHAUSTED'}
end
local ciphertext = redis.call('HGET', KEYS[1], 'ciphertext')
local generation = redis.call('HGET', KEYS[1], 'generation')
return {ciphertext, generation, tostring(attempts), tostring(maximum)}
"""

_DELETE_GENERATION_SCRIPT = """
if redis.call('HGET', KEYS[1], 'generation') == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class PdfSecretError(RuntimeError):
    """Stable, content-free error returned across the secret boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PdfSecretBinding:
    """Opaque ownership tuple that prevents cross-tenant password reuse."""

    tenant_id: UUID
    document_id: UUID
    source_sha256: str

    def __post_init__(self) -> None:
        if len(self.source_sha256) != 64:
            raise ValueError("source_sha256 must contain 64 lowercase hexadecimal characters")
        try:
            decoded = bytes.fromhex(self.source_sha256)
        except ValueError as exc:
            raise ValueError(
                "source_sha256 must contain 64 lowercase hexadecimal characters"
            ) from exc
        if decoded.hex() != self.source_sha256:
            raise ValueError("source_sha256 must contain 64 lowercase hexadecimal characters")

    def canonical_bytes(self) -> bytes:
        return self.tenant_id.bytes + self.document_id.bytes + bytes.fromhex(self.source_sha256)


@dataclass(slots=True)
class PdfSecretLease:
    """A short-lived password copy that can be actively zeroed after parsing."""

    binding: PdfSecretBinding
    attempt: int
    max_attempts: int
    _generation: str = field(repr=False)
    _password: bytearray = field(repr=False)
    _destroyed: bool = field(default=False, init=False, repr=False)

    def reveal(self) -> bytes:
        if self._destroyed:
            raise PdfSecretError("PDF_PASSWORD_LEASE_DESTROYED")
        return bytes(self._password)

    def destroy(self) -> None:
        for index in range(len(self._password)):
            self._password[index] = 0
        self._password.clear()
        self._destroyed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.destroy()


class PdfSecretStore(Protocol):
    async def put(
        self,
        binding: PdfSecretBinding,
        password: str,
        *,
        ttl_seconds: int = 5 * 60,
        max_attempts: int = 3,
    ) -> None: ...

    async def acquire(self, binding: PdfSecretBinding) -> PdfSecretLease: ...

    async def finish(self, lease: PdfSecretLease, *, success: bool) -> None: ...

    async def delete(self, binding: PdfSecretBinding) -> None: ...

    async def close(self) -> None: ...


def _password_bytes(password: str) -> bytearray:
    encoded = password.encode("utf-8")
    if not encoded or len(encoded) > _MAX_PASSWORD_BYTES or b"\x00" in encoded:
        raise PdfSecretError("PDF_PASSWORD_INVALID")
    return bytearray(encoded)


def _validate_policy(ttl_seconds: int, max_attempts: int) -> None:
    if not _MIN_TTL_SECONDS <= ttl_seconds <= _MAX_TTL_SECONDS:
        raise ValueError("PDF password TTL is outside the safe bound")
    if not _MIN_ATTEMPTS <= max_attempts <= _MAX_ATTEMPTS:
        raise ValueError("PDF password attempt limit is outside the safe bound")


def _binding_digest(binding: PdfSecretBinding, key: bytes) -> bytes:
    return hmac.new(key, binding.canonical_bytes(), hashlib.sha256).digest()


@dataclass(slots=True)
class _MemoryEntry:
    password: bytearray = field(repr=False)
    expires_at: float
    max_attempts: int
    attempts: int
    generation: str

    def destroy(self) -> None:
        for index in range(len(self.password)):
            self.password[index] = 0
        self.password.clear()


class InMemoryPdfSecretStore:
    """Single-process adapter for tests and explicit local development only."""

    def __init__(
        self,
        *,
        key_secret: bytes,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if len(key_secret) < 32:
            raise ValueError("PDF secret key must contain at least 32 bytes")
        self._key_secret = bytes(key_secret)
        self._clock = clock
        self._entries: dict[bytes, _MemoryEntry] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    def _key(self, binding: PdfSecretBinding) -> bytes:
        return _binding_digest(binding, self._key_secret)

    async def put(
        self,
        binding: PdfSecretBinding,
        password: str,
        *,
        ttl_seconds: int = 5 * 60,
        max_attempts: int = 3,
    ) -> None:
        _validate_policy(ttl_seconds, max_attempts)
        secret = _password_bytes(password)
        async with self._lock:
            if self._closed:
                secret.clear()
                raise PdfSecretError("PDF_SECRET_STORE_CLOSED")
            key = self._key(binding)
            previous = self._entries.pop(key, None)
            if previous is not None:
                previous.destroy()
            self._entries[key] = _MemoryEntry(
                password=secret,
                expires_at=self._clock() + ttl_seconds,
                max_attempts=max_attempts,
                attempts=0,
                generation=secrets.token_hex(16),
            )

    async def acquire(self, binding: PdfSecretBinding) -> PdfSecretLease:
        async with self._lock:
            if self._closed:
                raise PdfSecretError("PDF_SECRET_STORE_CLOSED")
            key = self._key(binding)
            entry = self._entries.get(key)
            if entry is None:
                raise PdfSecretError("PDF_PASSWORD_REQUIRED")
            if entry.expires_at <= self._clock():
                entry.destroy()
                del self._entries[key]
                raise PdfSecretError("PDF_PASSWORD_EXPIRED")
            entry.attempts += 1
            if entry.attempts > entry.max_attempts:
                entry.destroy()
                del self._entries[key]
                raise PdfSecretError("PDF_PASSWORD_ATTEMPTS_EXHAUSTED")
            return PdfSecretLease(
                binding=binding,
                attempt=entry.attempts,
                max_attempts=entry.max_attempts,
                _generation=entry.generation,
                _password=bytearray(entry.password),
            )

    async def finish(self, lease: PdfSecretLease, *, success: bool) -> None:
        try:
            async with self._lock:
                key = self._key(lease.binding)
                entry = self._entries.get(key)
                if entry is None or not hmac.compare_digest(
                    entry.generation,
                    lease._generation,
                ):
                    return
                if success or entry.attempts >= entry.max_attempts:
                    entry.destroy()
                    del self._entries[key]
        finally:
            lease.destroy()

    async def delete(self, binding: PdfSecretBinding) -> None:
        async with self._lock:
            entry = self._entries.pop(self._key(binding), None)
            if entry is not None:
                entry.destroy()

    async def close(self) -> None:
        async with self._lock:
            for entry in self._entries.values():
                entry.destroy()
            self._entries.clear()
            self._closed = True


class _AsyncRedis(Protocol):
    async def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: object,
    ) -> Any: ...

    async def delete(self, *names: object) -> int: ...

    async def aclose(self) -> None: ...


class RedisPdfSecretStore:
    """Distributed adapter with authenticated encryption and Redis-enforced TTL."""

    def __init__(
        self,
        client: _AsyncRedis,
        *,
        encryption_key: str | bytes,
        key_secret: bytes,
        owns_client: bool = False,
    ) -> None:
        if len(key_secret) < 32:
            raise ValueError("PDF secret key must contain at least 32 bytes")
        raw_key = (
            encryption_key.encode("ascii") if isinstance(encryption_key, str) else encryption_key
        )
        try:
            self._fernet = Fernet(raw_key)
        except (TypeError, ValueError) as exc:
            raise ValueError("PDF secret encryption key must be Fernet-compatible") from exc
        self._client = client
        self._key_secret = bytes(key_secret)
        self._owns_client = owns_client

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        *,
        encryption_key: str | bytes,
        key_secret: bytes,
    ) -> RedisPdfSecretStore:
        if not redis_url.startswith(("redis://", "rediss://")):
            raise ValueError("PDF secret Redis URL is invalid")
        client = cast(
            _AsyncRedis,
            Redis.from_url(
                redis_url,
                decode_responses=False,
                socket_connect_timeout=3,
                socket_timeout=3,
                health_check_interval=30,
            ),
        )
        return cls(
            client,
            encryption_key=encryption_key,
            key_secret=key_secret,
            owns_client=True,
        )

    def _binding_digest(self, binding: PdfSecretBinding) -> bytes:
        return _binding_digest(binding, self._key_secret)

    def _key(self, binding: PdfSecretBinding) -> bytes:
        return _KEY_PREFIX + self._binding_digest(binding).hex().encode("ascii")

    def _encrypt(
        self,
        binding: PdfSecretBinding,
        password: bytearray,
        generation: str,
    ) -> bytes:
        payload = json.dumps(
            {
                "binding": base64.urlsafe_b64encode(self._binding_digest(binding)).decode("ascii"),
                "generation": generation,
                "password": base64.b64encode(password).decode("ascii"),
                "version": 1,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return self._fernet.encrypt(payload)

    def _decrypt(
        self,
        binding: PdfSecretBinding,
        ciphertext: bytes,
        generation: str,
    ) -> bytearray:
        try:
            payload = json.loads(self._fernet.decrypt(ciphertext))
            digest = base64.urlsafe_b64decode(str(payload["binding"]).encode("ascii"))
            password = bytearray(base64.b64decode(str(payload["password"]), validate=True))
            payload_generation = str(payload["generation"])
            version = int(payload["version"])
        except (InvalidToken, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PdfSecretError("PDF_SECRET_STORE_CORRUPT") from exc
        if (
            version != 1
            or not hmac.compare_digest(digest, self._binding_digest(binding))
            or not hmac.compare_digest(payload_generation, generation)
            or not password
            or len(password) > _MAX_PASSWORD_BYTES
        ):
            password.clear()
            raise PdfSecretError("PDF_SECRET_STORE_CORRUPT")
        return password

    async def put(
        self,
        binding: PdfSecretBinding,
        password: str,
        *,
        ttl_seconds: int = 5 * 60,
        max_attempts: int = 3,
    ) -> None:
        _validate_policy(ttl_seconds, max_attempts)
        secret = _password_bytes(password)
        generation = secrets.token_hex(16)
        try:
            ciphertext = self._encrypt(binding, secret, generation)
            await self._client.eval(
                _PUT_SCRIPT,
                1,
                self._key(binding),
                ciphertext,
                generation,
                max_attempts,
                ttl_seconds * 1000,
            )
        except RedisError as exc:
            raise PdfSecretError("PDF_SECRET_STORE_UNAVAILABLE") from exc
        finally:
            for index in range(len(secret)):
                secret[index] = 0
            secret.clear()

    async def acquire(self, binding: PdfSecretBinding) -> PdfSecretLease:
        try:
            raw = await self._client.eval(_ACQUIRE_SCRIPT, 1, self._key(binding))
        except RedisError as exc:
            raise PdfSecretError("PDF_SECRET_STORE_UNAVAILABLE") from exc
        if not isinstance(raw, list) or not raw:
            raise PdfSecretError("PDF_PASSWORD_REQUIRED")
        if raw[0] in {b"EXHAUSTED", "EXHAUSTED"}:
            raise PdfSecretError("PDF_PASSWORD_ATTEMPTS_EXHAUSTED")
        if len(raw) != 4:
            raise PdfSecretError("PDF_SECRET_STORE_CORRUPT")
        try:
            ciphertext = bytes(raw[0])
            generation = raw[1].decode("ascii") if isinstance(raw[1], bytes) else str(raw[1])
            attempt = int(raw[2])
            maximum = int(raw[3])
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise PdfSecretError("PDF_SECRET_STORE_CORRUPT") from exc
        password = self._decrypt(binding, ciphertext, generation)
        return PdfSecretLease(
            binding=binding,
            attempt=attempt,
            max_attempts=maximum,
            _generation=generation,
            _password=password,
        )

    async def finish(self, lease: PdfSecretLease, *, success: bool) -> None:
        try:
            if success or lease.attempt >= lease.max_attempts:
                try:
                    await self._client.eval(
                        _DELETE_GENERATION_SCRIPT,
                        1,
                        self._key(lease.binding),
                        lease._generation,
                    )
                except RedisError as exc:
                    raise PdfSecretError("PDF_SECRET_STORE_UNAVAILABLE") from exc
        finally:
            lease.destroy()

    async def delete(self, binding: PdfSecretBinding) -> None:
        try:
            await self._client.delete(self._key(binding))
        except RedisError as exc:
            raise PdfSecretError("PDF_SECRET_STORE_UNAVAILABLE") from exc

    async def close(self) -> None:
        if self._owns_client:
            try:
                await self._client.aclose()
            except RedisError as exc:
                raise PdfSecretError("PDF_SECRET_STORE_UNAVAILABLE") from exc
