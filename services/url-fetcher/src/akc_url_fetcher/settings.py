"""Fail-closed runtime settings for the isolated URL-fetch worker."""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class UrlFetcherSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AKC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./.akc-data/akc.db"
    url_database_role: str = "akc_url_fetcher"
    database_connect_timeout_seconds: float = Field(default=10, gt=0, le=60)
    database_command_timeout_seconds: float = Field(default=30, gt=0, le=300)
    database_statement_timeout_ms: int = Field(default=30_000, ge=1000, le=300_000)
    database_lock_timeout_ms: int = Field(default=5000, ge=100, le=60_000)
    database_idle_transaction_timeout_ms: int = Field(
        default=30_000,
        ge=1000,
        le=300_000,
    )
    database_pool_timeout_seconds: float = Field(default=10, gt=0, le=60)

    data_dir: Path = Path(".akc-data")
    object_store_driver: Literal["local", "s3"] = "local"
    s3_endpoint_url: str | None = None
    s3_region: str = "ap-northeast-2"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_use_ambient_credentials: bool = True
    s3_deletion_mode: Literal["versioned", "unversioned-explicit"] = "versioned"
    s3_bucket_quarantine: str = "akc-intake-quarantine"
    s3_bucket_source: str = "akc-source-private"
    s3_bucket_working: str = "akc-working-private"
    s3_bucket_derived: str = "akc-derived-private"
    s3_bucket_exports: str = "akc-exports-private"
    s3_bucket_audit: str = "akc-audit-evidence"

    url_encryption_key: str | None = None
    url_query_hmac_secret: str | None = None
    url_fetch_max_bytes: int = Field(
        default=50 * 1024 * 1024,
        ge=1024,
        le=1024 * 1024 * 1024,
    )
    url_fetch_connect_timeout_seconds: float = Field(default=5, gt=0, le=60)
    url_fetch_read_timeout_seconds: float = Field(default=20, gt=0, le=120)
    url_fetch_total_timeout_seconds: float = Field(default=30, gt=0, le=300)
    url_fetch_max_redirects: int = Field(default=5, ge=0, le=10)
    url_fetch_poll_interval_seconds: float = Field(default=0.5, gt=0, le=60)
    url_fetch_max_attempts: int = Field(default=5, ge=1, le=10)
    url_fetch_lease_seconds: float = Field(default=90, gt=0, le=3600)
    url_fetch_backoff_base_seconds: float = Field(default=2, gt=0, le=300)
    url_fetch_backoff_max_seconds: float = Field(default=300, gt=0, le=3600)
    url_fetch_backoff_jitter_ratio: float = Field(default=0.2, ge=0, le=1)

    clamav_enabled: bool = False
    clamav_host: str = "clamav"
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    clamav_timeout_seconds: float = Field(default=20, ge=1, le=120)
    allow_development_antivirus_bypass: bool = True

    metrics_enabled: bool = True
    metrics_bind_host: Literal["127.0.0.1", "0.0.0.0"] = "127.0.0.1"  # nosec B104
    metrics_port: int = Field(default=9103, ge=1024, le=65535)

    @property
    def object_root(self) -> Path:
        return self.data_dir / "objects"

    @property
    def database_backend(self) -> str:
        return make_url(self.database_url).get_backend_name()

    @property
    def effective_url_encryption_key(self) -> str:
        if self.url_encryption_key:
            return self.url_encryption_key
        if self.env == "production":
            raise ValueError("production URL encryption key is not configured")
        return base64.urlsafe_b64encode(
            hashlib.sha256(b"akc-explicit-local-url-encryption-v1").digest()
        ).decode("ascii")

    @property
    def effective_url_query_hmac_secret(self) -> bytes:
        if self.url_query_hmac_secret:
            value = self.url_query_hmac_secret.encode("utf-8")
            if len(value) < 32:
                raise ValueError("URL query HMAC secret must contain at least 32 bytes")
            return value
        if self.env == "production":
            raise ValueError("production URL query HMAC secret is not configured")
        return hashlib.sha256(b"akc-explicit-local-url-query-hmac-v1").digest()

    @model_validator(mode="after")
    def enforce_worker_safety(self) -> UrlFetcherSettings:
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", self.url_database_role):
            raise ValueError("AKC_URL_DATABASE_ROLE is invalid")
        try:
            database_url = make_url(self.database_url)
        except ArgumentError as exc:
            raise ValueError("AKC_DATABASE_URL is invalid") from exc
        backend = database_url.get_backend_name()
        if backend not in {"postgresql", "sqlite"}:
            raise ValueError("URL worker supports only PostgreSQL or SQLite")
        if backend == "postgresql" and database_url.drivername != "postgresql+asyncpg":
            raise ValueError("PostgreSQL URL worker requires asyncpg")
        if backend == "sqlite" and database_url.drivername != "sqlite+aiosqlite":
            raise ValueError("SQLite URL worker requires aiosqlite")
        if bool(self.s3_access_key_id) != bool(self.s3_secret_access_key):
            raise ValueError("both S3 static credential fields must be set together")
        if (
            self.object_store_driver == "s3"
            and not self.s3_use_ambient_credentials
            and not (self.s3_access_key_id and self.s3_secret_access_key)
        ):
            raise ValueError("S3 requires static or ambient workload credentials")
        if self.s3_endpoint_url:
            endpoint = urlsplit(self.s3_endpoint_url)
            if not endpoint.hostname or endpoint.username or endpoint.password:
                raise ValueError("S3 endpoint must be a credential-free origin")
            if self.env == "production" and endpoint.scheme != "https":
                raise ValueError("production S3 endpoint must use HTTPS")
        if self.url_fetch_total_timeout_seconds < max(
            self.url_fetch_connect_timeout_seconds,
            self.url_fetch_read_timeout_seconds,
        ):
            raise ValueError("URL total timeout cannot be shorter than component timeout")
        if self.url_fetch_lease_seconds <= (
            self.url_fetch_total_timeout_seconds + self.clamav_timeout_seconds
        ):
            raise ValueError("URL lease must cover fetch and antivirus timeouts")
        if self.url_fetch_backoff_max_seconds < self.url_fetch_backoff_base_seconds:
            raise ValueError("URL backoff maximum must be at least its base")
        try:
            Fernet(self.effective_url_encryption_key.encode("ascii"))
        except (UnicodeError, ValueError) as exc:
            raise ValueError("URL encryption key must be Fernet-compatible") from exc
        _ = self.effective_url_query_hmac_secret
        if self.env == "production":
            if backend != "postgresql":
                raise ValueError("production URL worker requires PostgreSQL")
            if self.object_store_driver != "s3":
                raise ValueError("production URL worker requires object storage")
            if not self.clamav_enabled:
                raise ValueError("production URL worker requires ClamAV")
            if self.allow_development_antivirus_bypass:
                raise ValueError("production URL worker forbids antivirus bypass")
            if (
                not self.metrics_enabled or self.metrics_bind_host != "0.0.0.0"  # nosec B104
            ):
                raise ValueError("production URL worker requires externally scrapeable metrics")
        return self
