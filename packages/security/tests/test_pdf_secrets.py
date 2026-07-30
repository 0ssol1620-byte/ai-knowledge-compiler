from __future__ import annotations

import uuid

import pytest
from akc_security import (
    InMemoryPdfSecretStore,
    PdfSecretBinding,
    PdfSecretError,
    RedisPdfSecretStore,
)
from cryptography.fernet import Fernet


def binding(*, tenant: uuid.UUID | None = None) -> PdfSecretBinding:
    return PdfSecretBinding(
        tenant_id=tenant or uuid.uuid4(),
        document_id=uuid.uuid4(),
        source_sha256="a" * 64,
    )


@pytest.mark.asyncio
async def test_memory_secret_is_bound_attempt_limited_and_destroyed_on_success() -> None:
    store = InMemoryPdfSecretStore(key_secret=b"k" * 32)
    owner = binding()
    other_tenant = binding(tenant=uuid.uuid4())
    await store.put(owner, "correct horse", ttl_seconds=30, max_attempts=3)

    with pytest.raises(PdfSecretError, match="PDF_PASSWORD_REQUIRED"):
        await store.acquire(other_tenant)

    lease = await store.acquire(owner)
    assert "correct horse" not in repr(lease)
    assert lease.reveal() == b"correct horse"
    await store.finish(lease, success=True)
    with pytest.raises(PdfSecretError, match="PDF_PASSWORD_LEASE_DESTROYED"):
        lease.reveal()
    with pytest.raises(PdfSecretError, match="PDF_PASSWORD_REQUIRED"):
        await store.acquire(owner)


@pytest.mark.asyncio
async def test_memory_secret_expires_and_limits_wrong_attempts() -> None:
    now = [100.0]
    store = InMemoryPdfSecretStore(key_secret=b"k" * 32, clock=lambda: now[0])
    owner = binding()
    await store.put(owner, "wrong", ttl_seconds=30, max_attempts=2)

    first = await store.acquire(owner)
    await store.finish(first, success=False)
    second = await store.acquire(owner)
    await store.finish(second, success=False)
    with pytest.raises(PdfSecretError, match="PDF_PASSWORD_REQUIRED"):
        await store.acquire(owner)

    await store.put(owner, "temporary", ttl_seconds=30)
    now[0] += 31
    with pytest.raises(PdfSecretError, match="PDF_PASSWORD_EXPIRED"):
        await store.acquire(owner)


@pytest.mark.asyncio
async def test_memory_overwrite_and_close_zeroize_old_values() -> None:
    store = InMemoryPdfSecretStore(key_secret=b"k" * 32)
    owner = binding()
    await store.put(owner, "first", ttl_seconds=30)
    await store.put(owner, "second", ttl_seconds=30)
    lease = await store.acquire(owner)
    assert lease.reveal() == b"second"
    lease.destroy()
    await store.close()
    with pytest.raises(PdfSecretError, match="PDF_SECRET_STORE_CLOSED"):
        await store.acquire(owner)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[bytes, dict[str, object]] = {}

    @staticmethod
    def _bytes(value: object) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode()
        raise TypeError("fake Redis expected a bytes-compatible value")

    @staticmethod
    def _int(value: object) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, (bytes, str)):
            return int(value)
        raise TypeError("fake Redis expected an integer-compatible value")

    async def eval(
        self,
        script: str,
        _numkeys: int,
        *keys_and_args: object,
    ) -> object:
        key = self._bytes(keys_and_args[0])
        if "PEXPIRE" in script:
            self.values[key] = {
                "ciphertext": keys_and_args[1],
                "generation": keys_and_args[2],
                "attempts": 0,
                "maximum": self._int(keys_and_args[3]),
            }
            return 1
        if "HINCRBY" in script:
            item = self.values.get(key)
            if item is None:
                return []
            item["attempts"] = self._int(item["attempts"]) + 1
            if self._int(item["attempts"]) > self._int(item["maximum"]):
                del self.values[key]
                return [b"EXHAUSTED"]
            return [
                item["ciphertext"],
                str(item["generation"]).encode(),
                str(item["attempts"]).encode(),
                str(item["maximum"]).encode(),
            ]
        item = self.values.get(key)
        if item is not None and item["generation"] == keys_and_args[1]:
            del self.values[key]
            return 1
        return 0

    async def delete(self, *names: object) -> int:
        deleted = 0
        for name in names:
            deleted += self.values.pop(self._bytes(name), None) is not None
        return deleted

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_redis_adapter_encrypts_at_rest_and_deletes_after_success() -> None:
    redis = FakeRedis()
    store = RedisPdfSecretStore(
        redis,
        encryption_key=Fernet.generate_key(),
        key_secret=b"k" * 32,
    )
    owner = binding()
    await store.put(owner, "not-in-redis", ttl_seconds=30)
    serialized = repr(redis.values)
    assert "not-in-redis" not in serialized
    assert str(owner.tenant_id) not in serialized
    assert str(owner.document_id) not in serialized

    lease = await store.acquire(owner)
    assert lease.reveal() == b"not-in-redis"
    await store.finish(lease, success=True)
    with pytest.raises(PdfSecretError, match="PDF_PASSWORD_REQUIRED"):
        await store.acquire(owner)


@pytest.mark.asyncio
async def test_redis_ciphertext_is_bound_to_exact_document() -> None:
    redis = FakeRedis()
    key = Fernet.generate_key()
    store = RedisPdfSecretStore(redis, encryption_key=key, key_secret=b"k" * 32)
    first = binding()
    second = binding(tenant=first.tenant_id)
    await store.put(first, "secret", ttl_seconds=30)

    first_key = store._key(first)
    second_key = store._key(second)
    redis.values[second_key] = dict(redis.values[first_key])
    with pytest.raises(PdfSecretError, match="PDF_SECRET_STORE_CORRUPT"):
        await store.acquire(second)


def test_binding_and_policy_reject_unbounded_or_malformed_secrets() -> None:
    with pytest.raises(ValueError):
        PdfSecretBinding(
            tenant_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            source_sha256="A" * 64,
        )

    store = InMemoryPdfSecretStore(key_secret=b"k" * 32)
    owner = binding()

    async def invalid() -> None:
        with pytest.raises(PdfSecretError, match="PDF_PASSWORD_INVALID"):
            await store.put(owner, "", ttl_seconds=30)
        with pytest.raises(PdfSecretError, match="PDF_PASSWORD_INVALID"):
            await store.put(owner, "x" * 1025, ttl_seconds=30)
        with pytest.raises(ValueError):
            await store.put(owner, "ok", ttl_seconds=29)
        with pytest.raises(ValueError):
            await store.put(owner, "ok", ttl_seconds=30, max_attempts=6)

    import asyncio

    asyncio.run(invalid())
