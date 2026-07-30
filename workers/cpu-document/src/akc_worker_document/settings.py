"""Fail-closed settings for the isolated CPU document worker."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class AnalysisWorkerSettings(BaseSettings):
    """Worker-only configuration; it intentionally has no API signing secrets."""

    model_config = SettingsConfigDict(
        env_prefix="AKC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./.akc-data/akc.db"
    analysis_database_role: str = "akc_analysis_worker"
    database_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    database_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    database_command_timeout_seconds: float = Field(default=330.0, gt=0, le=1800)
    database_statement_timeout_ms: int = Field(default=325_000, ge=1000, le=1_800_000)
    database_lock_timeout_ms: int = Field(default=5000, ge=100, le=30_000)
    database_idle_transaction_timeout_ms: int = Field(
        default=340_000,
        ge=10_000,
        le=1_800_000,
    )

    data_dir: Path = Path(".akc-data")
    object_store_driver: Literal["local", "s3"] = "local"
    s3_endpoint_url: str | None = None
    s3_region: str = "ap-northeast-2"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_use_ambient_credentials: bool = True
    s3_bucket_quarantine: str = "akc-intake-quarantine"
    s3_bucket_source: str = "akc-source-private"
    s3_bucket_working: str = "akc-working-private"
    s3_bucket_derived: str = "akc-derived-private"
    s3_bucket_exports: str = "akc-exports-private"
    s3_bucket_audit: str = "akc-audit-evidence"
    redis_url: str | None = None
    pdf_password_encryption_key: str | None = None
    pdf_password_hmac_secret: str | None = None
    pdf_password_ttl_seconds: int = Field(default=300, ge=30, le=900)
    pdf_password_max_attempts: int = Field(default=3, ge=1, le=5)

    max_upload_bytes: int = Field(default=1024 * 1024 * 1024, ge=1024)
    analysis_max_source_bytes: int = Field(
        default=256 * 1024 * 1024,
        ge=1024 * 1024,
    )
    max_pages: int = Field(default=500, ge=1, le=10_000)
    max_archive_files: int = Field(default=2000, ge=1, le=100_000)
    max_archive_uncompressed_bytes: int = Field(
        default=250 * 1024 * 1024,
        ge=1024,
    )
    max_archive_ratio: float = Field(default=100.0, ge=1.0, le=10_000)
    max_extracted_chars_per_page: int = Field(
        default=2_000_000,
        ge=1000,
        le=20_000_000,
    )
    max_extracted_chars_total: int = Field(
        default=20_000_000,
        ge=1000,
        le=200_000_000,
    )
    private_mode: bool = True
    default_retention_days: int = Field(default=7, ge=0, le=3650)
    free_daily_file_cap: int = Field(default=5, ge=1, le=10_000)
    free_daily_page_cap: int = Field(default=50, ge=1, le=100_000)
    free_daily_gpu_cost_usd_cap: Decimal = Field(
        default=Decimal("1.000000"),
        gt=0,
    )

    analysis_poll_interval_seconds: float = Field(default=0.5, gt=0, le=60)
    analysis_max_attempts: int = Field(default=3, ge=1, le=10)
    analysis_lease_seconds: float = Field(default=330.0, gt=0, le=3600)
    analysis_attempt_timeout_seconds: float = Field(default=300.0, gt=0, le=1800)
    analysis_backoff_base_seconds: float = Field(default=2.0, gt=0, le=300)
    analysis_backoff_max_seconds: float = Field(default=120.0, gt=0, le=3600)
    analysis_backoff_jitter_ratio: float = Field(default=0.2, ge=0, le=1)
    analysis_sandbox_launcher: Literal["direct", "bubblewrap"] = "direct"
    analysis_child_memory_bytes: int = Field(
        default=1536 * 1024 * 1024,
        ge=128 * 1024 * 1024,
        le=8 * 1024 * 1024 * 1024,
    )
    analysis_child_file_bytes: int = Field(
        default=512 * 1024 * 1024,
        ge=16 * 1024 * 1024,
        le=4 * 1024 * 1024 * 1024,
    )
    analysis_child_open_files: int = Field(default=128, ge=32, le=1024)
    analysis_max_result_bytes: int = Field(
        default=128 * 1024 * 1024,
        ge=1024 * 1024,
        le=512 * 1024 * 1024,
    )

    preview_enabled: bool = True
    preview_dpi: int = Field(default=110, ge=72, le=180)
    preview_max_long_edge: int = Field(default=1800, ge=640, le=4096)
    preview_thumbnail_long_edge: int = Field(default=360, ge=128, le=1024)
    preview_max_pixels: int = Field(default=20_000_000, ge=1_000_000, le=50_000_000)
    preview_max_bytes_per_asset: int = Field(
        default=8 * 1024 * 1024,
        ge=64 * 1024,
        le=32 * 1024 * 1024,
    )
    preview_max_total_bytes: int = Field(
        default=256 * 1024 * 1024,
        ge=16 * 1024 * 1024,
        le=1024 * 1024 * 1024,
    )
    inference_raster_max_pixels: int = Field(
        default=40_000_000,
        ge=4_000_000,
        le=100_000_000,
    )
    inference_raster_max_bytes_per_asset: int = Field(
        default=32 * 1024 * 1024,
        ge=1024 * 1024,
        le=128 * 1024 * 1024,
    )
    inference_raster_max_total_bytes: int = Field(
        default=1024 * 1024 * 1024,
        ge=32 * 1024 * 1024,
        le=4 * 1024 * 1024 * 1024,
    )

    metrics_enabled: bool = True
    metrics_bind_host: Literal["127.0.0.1", "0.0.0.0"] = "127.0.0.1"  # nosec B104
    metrics_port: int = Field(default=9102, ge=1024, le=65535)

    @property
    def object_root(self) -> Path:
        return self.data_dir / "objects"

    @property
    def database_backend(self) -> str:
        return make_url(self.database_url).get_backend_name()

    @property
    def effective_pdf_password_key_secret(self) -> bytes:
        if self.pdf_password_hmac_secret:
            encoded = self.pdf_password_hmac_secret.encode("utf-8")
            if len(encoded) < 32:
                raise ValueError("PDF password HMAC secret must contain at least 32 bytes")
            return encoded
        if self.env == "production":
            raise ValueError("production PDF password HMAC secret is not configured")
        return hashlib.sha256(b"akc-explicit-local-pdf-password-key-v1").digest()

    @model_validator(mode="after")
    def enforce_worker_safety(self) -> AnalysisWorkerSettings:
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", self.analysis_database_role):
            raise ValueError("AKC_ANALYSIS_DATABASE_ROLE is invalid")
        try:
            database_url = make_url(self.database_url)
        except ArgumentError as exc:
            raise ValueError("AKC_DATABASE_URL is invalid") from exc
        backend = database_url.get_backend_name()
        if backend not in {"postgresql", "sqlite"}:
            raise ValueError("analysis worker supports only PostgreSQL or SQLite")
        if backend == "postgresql" and database_url.drivername != "postgresql+asyncpg":
            raise ValueError("PostgreSQL analysis worker requires asyncpg")
        if backend == "sqlite" and database_url.drivername != "sqlite+aiosqlite":
            raise ValueError("SQLite analysis worker requires aiosqlite")
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
        if self.redis_url:
            redis_endpoint = urlsplit(self.redis_url)
            if redis_endpoint.scheme not in {"redis", "rediss"} or not redis_endpoint.hostname:
                raise ValueError("PDF secret Redis URL is invalid")
            if self.env == "production" and redis_endpoint.scheme != "rediss":
                raise ValueError("production PDF secret Redis requires TLS")
            if not self.pdf_password_encryption_key:
                raise ValueError("PDF secret Redis requires an encryption key")
            try:
                Fernet(self.pdf_password_encryption_key.encode("ascii"))
            except (TypeError, ValueError) as exc:
                raise ValueError("PDF password encryption key must be Fernet-compatible") from exc
            _ = self.effective_pdf_password_key_secret
        if self.analysis_lease_seconds <= self.analysis_attempt_timeout_seconds:
            raise ValueError("analysis lease must exceed the attempt timeout")
        if self.analysis_max_source_bytes > self.max_upload_bytes:
            raise ValueError("analysis source limit cannot exceed the upload limit")
        minimum_child_memory = (
            (self.analysis_max_source_bytes * 3)
            + self.analysis_max_result_bytes
            + (self.preview_max_pixels * 4)
            + (64 * 1024 * 1024)
        )
        if self.analysis_child_memory_bytes < minimum_child_memory:
            raise ValueError(
                "analysis child memory must cover bounded parser, result, and preview working sets"
            )
        if self.analysis_child_file_bytes < max(
            self.analysis_max_source_bytes,
            self.analysis_max_result_bytes,
            self.preview_max_bytes_per_asset,
        ):
            raise ValueError("analysis child file limit is below a bounded input or output")
        if self.preview_max_total_bytes < (self.preview_max_bytes_per_asset * 2):
            raise ValueError("preview total limit must cover one preview pair")
        if self.analysis_backoff_max_seconds < self.analysis_backoff_base_seconds:
            raise ValueError("analysis backoff maximum must be at least its base")
        if self.max_extracted_chars_total < self.max_extracted_chars_per_page:
            raise ValueError("total extracted character limit must cover one page")
        if self.env == "production":
            if backend != "postgresql":
                raise ValueError("production analysis worker requires PostgreSQL")
            if self.object_store_driver != "s3":
                raise ValueError("production analysis worker requires object storage")
            if self.analysis_sandbox_launcher != "bubblewrap":
                raise ValueError("production analysis worker requires bubblewrap isolation")
            if (
                not self.metrics_enabled or self.metrics_bind_host != "0.0.0.0"  # nosec B104
            ):
                raise ValueError(
                    "production analysis worker requires externally scrapeable metrics"
                )
            if not self.redis_url:
                raise ValueError(
                    "production analysis worker requires Redis for ephemeral PDF passwords"
                )
        return self
