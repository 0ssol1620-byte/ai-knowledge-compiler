"""Configuration for the durable scheduler process."""

from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class SchedulerSettings(BaseSettings):
    """Scheduler settings loaded from ``AKC_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="AKC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    metrics_enabled: bool = True
    metrics_bind_host: Literal["127.0.0.1", "0.0.0.0"] = "127.0.0.1"  # nosec B104
    metrics_port: int = Field(default=9100, ge=1024, le=65535)
    database_url: str = "sqlite+aiosqlite:///./.akc-data/akc.db"
    scheduler_database_role: str = "akc_scheduler"
    dispatch_database_role: str = "akc_dispatch_worker"
    deletion_database_role: str = "akc_deletion_worker"
    gpu_database_role: str = "akc_gpu_worker"
    database_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    database_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    database_command_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    database_statement_timeout_ms: int = Field(default=25000, ge=1000, le=120000)
    database_lock_timeout_ms: int = Field(default=5000, ge=100, le=30000)
    database_idle_transaction_timeout_ms: int = Field(
        default=310000,
        ge=10000,
        le=3600000,
    )

    scheduler_poll_interval_seconds: float = Field(default=0.5, gt=0, le=60)
    scheduler_batch_size: int = Field(default=50, ge=1, le=500)
    scheduler_retention_interval_seconds: float = Field(
        default=3600.0,
        gt=0,
        le=86400,
    )
    scheduler_cleanup_batch_size: int = Field(default=1000, ge=1, le=10000)
    event_retention_days: int = Field(default=7, ge=1, le=365)
    outbox_retention_days: int = Field(default=7, ge=1, le=3650)
    dispatch_dead_letter_retention_days: int = Field(default=30, ge=1, le=3650)
    webhook_delivery_retention_days: int = Field(default=30, ge=1, le=3650)
    dispatch_max_attempts: int = Field(default=5, ge=1, le=100)
    dispatch_lease_seconds: float = Field(default=900.0, gt=0, le=86400)
    dispatch_attempt_timeout_seconds: float = Field(default=300.0, gt=0, le=3600)
    dispatch_backoff_base_seconds: float = Field(default=2.0, gt=0, le=3600)
    dispatch_backoff_max_seconds: float = Field(default=300.0, gt=0, le=86400)
    dispatch_backoff_jitter_ratio: float = Field(default=0.2, ge=0, le=1)
    dispatch_fairness_scan_tenants: int = Field(default=64, ge=1, le=1000)
    dispatch_tenant_busy_delay_seconds: float = Field(default=1.0, gt=0, le=60)
    dispatch_paused_delay_seconds: float = Field(default=15.0, gt=0, le=300)
    collection_finalizer_enabled: bool = False
    collection_finalizer_api_url: str = "http://127.0.0.1:8000/v1/internal/collections/finalize"
    collection_finalizer_hmac_secret: SecretStr = SecretStr("")
    collection_finalizer_timeout_seconds: float = Field(default=300.0, gt=0, le=1800)
    deletion_max_attempts: int = Field(default=20, ge=1, le=100)
    deletion_lease_seconds: float = Field(default=300.0, gt=0, le=3600)
    deletion_attempt_timeout_seconds: float = Field(default=240.0, gt=0, le=3500)
    deletion_backoff_base_seconds: float = Field(default=5.0, gt=0, le=3600)
    deletion_backoff_max_seconds: float = Field(default=3600.0, gt=0, le=86400)
    deletion_backoff_jitter_ratio: float = Field(default=0.2, ge=0, le=1)
    deletion_retention_sweep_interval_seconds: float = Field(
        default=3600.0,
        gt=0,
        le=86400,
    )
    gpu_worker_enabled: bool = False
    runpod_api_key: SecretStr = SecretStr("")
    gpu_worker_hmac_secret: SecretStr = SecretStr("")
    gpu_allowed_input_hosts: str = ""
    gpu_allowed_output_hosts: str = ""
    gpu_presign_ttl_seconds: int = Field(default=1200, ge=600, le=1800)
    gpu_lease_seconds: float = Field(default=60, gt=0, le=3600)
    gpu_provider_call_timeout_seconds: float = Field(default=30, gt=0, le=120)
    gpu_provider_job_timeout_seconds: float = Field(default=900, gt=0, le=1800)
    gpu_poll_interval_seconds: float = Field(default=2, gt=0, le=60)
    gpu_backoff_base_seconds: float = Field(default=2, gt=0, le=300)
    gpu_backoff_max_seconds: float = Field(default=120, gt=0, le=3600)
    gpu_backoff_jitter_ratio: float = Field(default=0.2, ge=0, le=1)
    gpu_max_cancel_attempts: int = Field(default=8, ge=1, le=100)
    gpu_max_output_bytes: int = Field(
        default=12 * 1024 * 1024,
        ge=1024,
        le=64 * 1024 * 1024,
    )

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

    # The in-process compile adapter consumes only this narrow provider policy.
    knowledge_provider: Literal["deterministic", "qwen_durable"] = "deterministic"
    qwen_endpoint_id: str = ""
    qwen_provider_key: str = "qwen3_5_4b"
    qwen_model_revision: str = ""
    qwen_runtime_image_digest: str = ""
    qwen_adapter_version: str = ""
    qwen_prompt_revision: str = ""
    qwen_knowledge_schema_sha256: str = ""
    qwen_max_attempts: int = Field(default=3, ge=1, le=10)
    private_mode: bool = True
    external_ocr_enabled: bool = False

    webhook_delivery_enabled: bool = False
    webhook_encryption_key: str = ""
    webhook_allowed_hosts: str = ""
    # One initial delivery plus the five frozen masterplan retry intervals.
    webhook_max_attempts: int = Field(default=6, ge=1, le=100)
    webhook_max_endpoints_per_tenant: int = Field(default=20, ge=1, le=100)
    webhook_retry_schedule_seconds: str = "60,300,1800,7200,43200"
    webhook_backoff_base_seconds: float = Field(default=2.0, gt=0, le=3600)
    webhook_backoff_max_seconds: float = Field(default=3600.0, gt=0, le=86400)
    webhook_backoff_jitter_ratio: float = Field(default=0.2, ge=0, le=1)
    webhook_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    webhook_read_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    webhook_attempt_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    webhook_configuration_retry_seconds: float = Field(default=60.0, gt=0, le=3600)
    webhook_max_retry_after_seconds: float = Field(default=86400.0, gt=0, le=604800)
    webhook_max_redirects: int = Field(default=3, ge=0, le=5)

    @property
    def allowed_webhook_hosts(self) -> tuple[str, ...]:
        """Return normalized, non-empty allowlist entries."""

        return tuple(
            entry.strip().casefold()
            for entry in self.webhook_allowed_hosts.split(",")
            if entry.strip()
        )

    @property
    def webhook_retry_schedule(self) -> tuple[int, ...]:
        """Return exact retry intervals; empty enables the legacy backoff."""

        if not self.webhook_retry_schedule_seconds.strip():
            return ()
        values: list[int] = []
        for raw in self.webhook_retry_schedule_seconds.split(","):
            value = raw.strip()
            if not value.isascii() or not value.isdigit():
                raise ValueError("AKC_WEBHOOK_RETRY_SCHEDULE_SECONDS is invalid")
            seconds = int(value)
            if seconds <= 0 or seconds > 7 * 24 * 60 * 60:
                raise ValueError("AKC_WEBHOOK_RETRY_SCHEDULE_SECONDS is invalid")
            values.append(seconds)
        if any(right <= left for left, right in pairwise(values)):
            raise ValueError("webhook retry schedule must be strictly increasing")
        return tuple(values)

    @staticmethod
    def _gpu_hosts(value: str) -> frozenset[str]:
        hosts = frozenset(entry.strip().casefold() for entry in value.split(",") if entry.strip())
        if any(
            not host
            or "*" in host
            or "/" in host
            or ":" in host
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host)
            for host in hosts
        ):
            raise ValueError("GPU object host allowlists contain an invalid hostname")
        return hosts

    @property
    def allowed_gpu_input_hosts(self) -> frozenset[str]:
        return self._gpu_hosts(self.gpu_allowed_input_hosts)

    @property
    def allowed_gpu_output_hosts(self) -> frozenset[str]:
        return self._gpu_hosts(self.gpu_allowed_output_hosts)

    @property
    def database_backend(self) -> str:
        return make_url(self.database_url).get_backend_name()

    @property
    def object_root(self) -> Path:
        return self.data_dir / "objects"

    def validate_deletion_storage(self) -> None:
        """Fail closed when the deletion trust boundary cannot reach storage."""

        if bool(self.s3_access_key_id) != bool(self.s3_secret_access_key):
            raise ValueError("both S3 static credential fields must be set together")
        if (
            self.object_store_driver == "s3"
            and not self.s3_use_ambient_credentials
            and not (self.s3_access_key_id and self.s3_secret_access_key)
        ):
            raise ValueError("deletion worker S3 requires static or ambient credentials")
        if self.env == "production" and self.object_store_driver != "s3":
            raise ValueError("production deletion worker requires S3-compatible storage")

    def validate_gpu_runtime(self) -> None:
        """Fail closed before creating any external provider client."""

        from akc_scheduler.gpu_jobs import GpuWorkerPolicy

        if not self.gpu_worker_enabled:
            raise ValueError("GPU worker mode requires AKC_GPU_WORKER_ENABLED=true")
        if self.object_store_driver != "s3":
            raise ValueError("GPU provider mode requires S3-compatible object storage")
        if bool(self.s3_access_key_id) != bool(self.s3_secret_access_key):
            raise ValueError("both S3 static credential fields must be set together")
        if not self.s3_use_ambient_credentials and not (
            self.s3_access_key_id and self.s3_secret_access_key
        ):
            raise ValueError("GPU object grants require static or ambient S3 credentials")
        if len(self.runpod_api_key.get_secret_value()) < 16:
            raise ValueError("AKC_RUNPOD_API_KEY is required for GPU provider mode")
        if len(self.gpu_worker_hmac_secret.get_secret_value().encode()) < 32:
            raise ValueError("AKC_GPU_WORKER_HMAC_SECRET must be at least 32 bytes")
        if not self.allowed_gpu_input_hosts or not self.allowed_gpu_output_hosts:
            raise ValueError("GPU provider mode requires exact input and output host allowlists")
        GpuWorkerPolicy(
            lease_seconds=self.gpu_lease_seconds,
            provider_call_timeout_seconds=self.gpu_provider_call_timeout_seconds,
            provider_job_timeout_seconds=self.gpu_provider_job_timeout_seconds,
            poll_interval_seconds=self.gpu_poll_interval_seconds,
            presign_ttl_seconds=self.gpu_presign_ttl_seconds,
            backoff_base_seconds=self.gpu_backoff_base_seconds,
            backoff_max_seconds=self.gpu_backoff_max_seconds,
            backoff_jitter_ratio=self.gpu_backoff_jitter_ratio,
            max_cancel_attempts=self.gpu_max_cancel_attempts,
            max_output_bytes=self.gpu_max_output_bytes,
        )

    def validate_knowledge_runtime(self) -> None:
        """Reject non-durable or unattested knowledge execution in production."""

        if self.knowledge_provider == "deterministic":
            if self.env == "production":
                raise ValueError("production forbids the deterministic knowledge provider")
            return
        if self.knowledge_provider != "qwen_durable":
            raise ValueError("AKC_KNOWLEDGE_PROVIDER is not configured")
        if self.object_store_driver != "s3":
            raise ValueError("durable Qwen requires S3-compatible object storage")
        if bool(self.s3_access_key_id) != bool(self.s3_secret_access_key):
            raise ValueError("both S3 static credential fields must be set together")
        if not self.s3_use_ambient_credentials and not (
            self.s3_access_key_id and self.s3_secret_access_key
        ):
            raise ValueError("durable Qwen requires static or ambient S3 credentials")
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", self.qwen_endpoint_id):
            raise ValueError("AKC_QWEN_ENDPOINT_ID is invalid")
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{1,79}",
            self.qwen_provider_key,
        ):
            raise ValueError("AKC_QWEN_PROVIDER_KEY is invalid")
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.qwen_model_revision):
            raise ValueError("AKC_QWEN_MODEL_REVISION must be exact")
        exact_sha = re.compile(r"^sha256:[0-9a-f]{64}$")
        if not exact_sha.fullmatch(
            self.qwen_runtime_image_digest
        ) or self.qwen_runtime_image_digest == "sha256:" + ("0" * 64):
            raise ValueError("AKC_QWEN_RUNTIME_IMAGE_DIGEST must be exact")
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{1,159}",
            self.qwen_adapter_version,
        ):
            raise ValueError("AKC_QWEN_ADAPTER_VERSION is invalid")
        if not exact_sha.fullmatch(
            self.qwen_prompt_revision
        ) or self.qwen_prompt_revision == "sha256:" + ("0" * 64):
            raise ValueError("AKC_QWEN_PROMPT_REVISION must be exact")
        if not exact_sha.fullmatch(
            self.qwen_knowledge_schema_sha256
        ) or self.qwen_knowledge_schema_sha256 == "sha256:" + ("0" * 64):
            raise ValueError("AKC_QWEN_KNOWLEDGE_SCHEMA_SHA256 must be exact")

    def validate_collection_finalizer(self) -> None:
        if not self.collection_finalizer_enabled:
            return
        secret = self.collection_finalizer_hmac_secret.get_secret_value().encode("utf-8")
        if len(secret) < 32:
            raise ValueError("collection finalizer HMAC secret must contain at least 32 bytes")
        endpoint = urlsplit(self.collection_finalizer_api_url)
        local_or_cluster_http = endpoint.scheme == "http" and (
            endpoint.hostname in {"127.0.0.1", "localhost", "akc-api"}
            or bool(endpoint.hostname and endpoint.hostname.endswith(".svc"))
        )
        if (
            (endpoint.scheme != "https" and not local_or_cluster_http)
            or not endpoint.hostname
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
            or endpoint.path != "/v1/internal/collections/finalize"
        ):
            raise ValueError("collection finalizer API URL is not an exact trusted endpoint")

    @model_validator(mode="after")
    def enforce_safe_scheduler_configuration(self) -> SchedulerSettings:
        self.validate_collection_finalizer()
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", self.scheduler_database_role):
            raise ValueError("AKC_SCHEDULER_DATABASE_ROLE is invalid")
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", self.dispatch_database_role):
            raise ValueError("AKC_DISPATCH_DATABASE_ROLE is invalid")
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", self.deletion_database_role):
            raise ValueError("AKC_DELETION_DATABASE_ROLE is invalid")
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", self.gpu_database_role):
            raise ValueError("AKC_GPU_DATABASE_ROLE is invalid")
        roles = {
            self.scheduler_database_role,
            self.dispatch_database_role,
            self.deletion_database_role,
            self.gpu_database_role,
        }
        if len(roles) != 4:
            raise ValueError(
                "scheduler, dispatch, deletion, and GPU database roles must be distinct"
            )
        if self.dispatch_backoff_max_seconds < self.dispatch_backoff_base_seconds:
            raise ValueError(
                "dispatch_backoff_max_seconds must be at least dispatch_backoff_base_seconds"
            )
        if self.dispatch_lease_seconds <= self.dispatch_attempt_timeout_seconds:
            raise ValueError("dispatch_lease_seconds must exceed dispatch_attempt_timeout_seconds")
        if self.deletion_backoff_max_seconds < self.deletion_backoff_base_seconds:
            raise ValueError(
                "deletion_backoff_max_seconds must be at least deletion_backoff_base_seconds"
            )
        if self.deletion_lease_seconds <= self.deletion_attempt_timeout_seconds:
            raise ValueError("deletion_lease_seconds must exceed deletion_attempt_timeout_seconds")
        if self.webhook_backoff_max_seconds < self.webhook_backoff_base_seconds:
            raise ValueError(
                "webhook_backoff_max_seconds must be at least webhook_backoff_base_seconds"
            )
        retry_schedule = self.webhook_retry_schedule
        if retry_schedule and len(retry_schedule) != self.webhook_max_attempts - 1:
            raise ValueError(
                "webhook retry schedule length must equal webhook_max_attempts minus one"
            )
        if self.webhook_delivery_enabled:
            from akc_scheduler.webhooks import HostAllowlist

            try:
                Fernet(self.webhook_encryption_key.encode("ascii"))
            except (UnicodeError, ValueError) as exc:
                raise ValueError(
                    "AKC_WEBHOOK_ENCRYPTION_KEY must be a Fernet-compatible key"
                ) from exc
            HostAllowlist(self.allowed_webhook_hosts)
            if self.env == "production" and not self.allowed_webhook_hosts:
                raise ValueError("AKC_WEBHOOK_ALLOWED_HOSTS is required in production")
        try:
            database_url = make_url(self.database_url)
        except ArgumentError as exc:
            raise ValueError("AKC_DATABASE_URL is invalid") from exc
        backend_name = database_url.get_backend_name()
        if backend_name not in {"postgresql", "sqlite"}:
            raise ValueError("scheduler supports only PostgreSQL or SQLite")
        if backend_name == "postgresql" and database_url.drivername != "postgresql+asyncpg":
            raise ValueError("PostgreSQL scheduler requires the asyncpg driver")
        if backend_name == "sqlite" and database_url.drivername != "sqlite+aiosqlite":
            raise ValueError("SQLite scheduler requires the aiosqlite driver")
        if self.env == "production" and backend_name != "postgresql":
            raise ValueError("production scheduler requires PostgreSQL")
        if self.env == "production" and (
            not self.metrics_enabled or self.metrics_bind_host != "0.0.0.0"  # nosec B104
        ):
            raise ValueError("production scheduler requires externally scrapeable metrics")
        return self
