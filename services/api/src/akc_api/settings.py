"""Runtime settings with safe local defaults and fail-closed production checks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded exclusively from AKC_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="AKC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./.akc-data/akc.db"
    data_dir: Path = Path(".akc-data")
    web_origins: str = "http://localhost:3000"

    jwt_secret: str = "local-development-secret-change-before-production"  # noqa: S105
    jwt_issuer: str = "ai-knowledge-compiler"
    access_token_minutes: int = Field(default=30, ge=5, le=1440)
    refresh_token_days: int = Field(default=14, ge=1, le=90)
    session_cookie_name: str = "akc_session"
    cookie_secure: bool | None = None
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    oidc_enabled: bool = False
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None
    oidc_scopes: str = "openid email profile"
    oidc_allowed_algorithms: str = "RS256,ES256"
    oidc_allowed_endpoint_hosts: str = ""
    oidc_http_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    oidc_cache_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    oidc_transaction_ttl_seconds: int = Field(default=300, ge=60, le=900)
    oidc_transaction_encryption_key: str | None = None
    oidc_state_hmac_secret: str | None = None
    mfa_encryption_key: str | None = None
    mfa_recovery_hmac_secret: str | None = None
    mfa_challenge_ttl_seconds: int = Field(default=300, ge=60, le=900)
    mfa_required_plans: str = "team,enterprise"

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
    presigned_upload_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    presigned_download_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    multipart_session_ttl_seconds: int = Field(
        default=24 * 60 * 60,
        ge=600,
        le=24 * 60 * 60,
    )
    multipart_upload_threshold_bytes: int = Field(
        default=50 * 1024 * 1024,
        ge=5 * 1024 * 1024,
    )
    multipart_part_size_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=5 * 1024 * 1024,
        le=5 * 1024 * 1024 * 1024,
    )
    multipart_max_parts: int = Field(default=10_000, ge=1, le=10_000)
    multipart_presign_batch_size: int = Field(default=20, ge=1, le=100)
    multipart_client_concurrency: int = Field(default=4, ge=1, le=8)
    multipart_client_max_retries: int = Field(default=3, ge=0, le=8)

    # The global guard is the Team ceiling. The tenant plan limit is enforced
    # separately at upload initiation and finalization.
    max_upload_bytes: int = Field(default=1024 * 1024 * 1024, ge=50 * 1024 * 1024)
    max_pages: int = Field(default=500, ge=1, le=10_000)
    max_archive_files: int = Field(default=2_000, ge=1)
    max_archive_uncompressed_bytes: int = Field(default=250 * 1024 * 1024, ge=1024)
    max_archive_ratio: float = Field(default=100.0, ge=1.0)

    parser_provider: str = "mock"
    knowledge_provider: Literal["deterministic", "qwen_durable"] = "deterministic"
    qwen_endpoint_id: str = ""
    qwen_provider_key: str = "qwen3_5_4b"
    qwen_model_revision: str = ""
    qwen_runtime_image_digest: str = ""
    qwen_adapter_version: str = ""
    qwen_prompt_revision: str = ""
    qwen_knowledge_schema_sha256: str = ""
    qwen_max_attempts: int = Field(default=3, ge=1, le=10)
    external_ocr_enabled: bool = False
    private_mode: bool = True
    training_opt_in_default: bool = False
    default_retention_days: int = Field(default=7, ge=0, le=3650)
    event_retention_days: int = Field(default=7, ge=1, le=365)
    local_background_tasks: bool = True
    # The control plane never parses documents in production. This switch
    # exists solely to make the durable worker adapter runnable in isolated
    # development and test environments.
    local_analysis_worker_enabled: bool = False
    # Upload storage can accept larger source objects than the current native
    # parser sandbox can safely materialize. Keep this independent and
    # fail-closed at enqueue time.
    analysis_max_source_bytes: int = Field(
        default=256 * 1024 * 1024,
        ge=1024 * 1024,
    )
    analysis_max_attempts: int = Field(default=3, ge=1, le=10)
    analysis_lease_seconds: float = Field(default=330.0, gt=0, le=3600)
    analysis_attempt_timeout_seconds: float = Field(default=300.0, gt=0, le=1800)
    analysis_backoff_base_seconds: float = Field(default=2.0, gt=0, le=300)
    analysis_backoff_max_seconds: float = Field(default=120.0, gt=0, le=3600)
    metrics_enabled: bool = True
    otel_enabled: bool = False
    otel_service_name: str = Field(
        default="akc-api",
        pattern=r"^[a-z][a-z0-9-]{1,62}$",
    )
    otel_exporter_otlp_endpoint: str | None = None
    otel_export_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    allow_public_registration: bool = True

    # ADR-006 · anonymous trial ingest.
    #
    # Off by default, following url_ingestion_enabled: a capability whose blast
    # radius is the public internet does not arrive switched on. Enabling it is
    # a deployment decision that also requires the rate limiter and, in
    # production, a CAPTCHA provider.
    #
    # The caps are settings rather than constants so an operator can tighten
    # them without a release. They can only be tightened relative to the
    # authenticated limits — see the validator below.
    trial_ingest_enabled: bool = False
    trial_ingest_max_bytes: int = Field(default=8 * 1024 * 1024, ge=64 * 1024)
    trial_ingest_max_pages: int = Field(default=10, ge=1, le=50)
    trial_ingest_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)
    trial_ingest_window_seconds: int = Field(default=3600, ge=60, le=86_400)

    # Two budgets, not one. Creating a session and presigning an object are
    # different operations with different costs, and sharing a counter meant a
    # visitor who mis-picked a file twice was locked out of uploading at all.
    trial_ingest_sessions_per_client: int = Field(default=5, ge=1, le=20)
    trial_ingest_uploads_per_client: int = Field(default=10, ge=1, le=100)
    # CAPTCHA escalates before the hard limit, so a human near the boundary is
    # challenged rather than refused.
    #
    # Third session onward, not second: trying the hero with two documents is
    # ordinary behaviour, and where no CAPTCHA provider is configured — which
    # is the default outside production — escalation is a refusal rather than a
    # challenge. The threshold has to leave room for a person.
    trial_ingest_captcha_after: int = Field(default=3, ge=1, le=20)

    url_ingestion_enabled: bool = False
    url_encryption_key: str | None = None
    url_query_hmac_secret: str | None = None
    url_fetch_max_attempts: int = Field(default=5, ge=1, le=10)

    clamav_enabled: bool = False
    clamav_host: str = "clamav"
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    clamav_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    allow_development_antivirus_bypass: bool = True
    cdr_enabled: bool = False
    cdr_provider: Literal["unavailable", "http"] = "unavailable"
    cdr_endpoint_url: str | None = None
    cdr_api_key: str | None = None
    cdr_timeout_seconds: float = Field(default=60.0, ge=1.0, le=300.0)
    cdr_max_output_bytes: int = Field(
        default=512 * 1024 * 1024,
        ge=1024 * 1024,
    )
    cdr_supported_mime_types: str = (
        "application/pdf,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
        "application/vnd.openxmlformats-officedocument.presentationml.presentation,"
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    redis_url: str | None = None
    abuse_identity_hmac_secret: str | None = None
    trusted_proxy_cidrs: str = ""
    rate_limit_memory_max_buckets: int = Field(default=10_000, ge=100, le=1_000_000)
    register_client_limit: int = Field(default=5, ge=1, le=10_000)
    register_account_limit: int = Field(default=3, ge=1, le=10_000)
    register_window_seconds: int = Field(default=3600, ge=1, le=86_400)
    register_captcha_after: int = Field(default=3, ge=1, le=10_000)
    login_client_limit: int = Field(default=20, ge=1, le=100_000)
    login_account_limit: int = Field(default=10, ge=1, le=100_000)
    login_window_seconds: int = Field(default=900, ge=1, le=86_400)
    login_captcha_after: int = Field(default=5, ge=1, le=100_000)
    verify_client_limit: int = Field(default=20, ge=1, le=100_000)
    verify_window_seconds: int = Field(default=900, ge=1, le=86_400)
    resend_client_limit: int = Field(default=5, ge=1, le=10_000)
    resend_account_limit: int = Field(default=3, ge=1, le=10_000)
    resend_window_seconds: int = Field(default=3600, ge=1, le=86_400)
    resend_captcha_after: int = Field(default=2, ge=1, le=10_000)
    operation_account_limit: int = Field(default=30, ge=1, le=100_000)
    operation_tenant_limit: int = Field(default=100, ge=1, le=100_000)
    operation_window_seconds: int = Field(default=60, ge=1, le=86_400)

    captcha_provider: Literal["disabled", "turnstile"] = "disabled"
    captcha_secret_key: str | None = None
    captcha_verify_url: str = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    captcha_timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    email_verification_enabled: bool = True
    email_verification_provider: Literal["capture", "resend", "disabled"] = "capture"
    verification_hmac_secret: str | None = None
    verification_delivery_encryption_key: str | None = None
    idempotency_response_encryption_key: str | None = None
    pdf_password_encryption_key: str | None = None
    pdf_password_hmac_secret: str | None = None
    pdf_password_ttl_seconds: int = Field(default=300, ge=30, le=900)
    pdf_password_max_attempts: int = Field(default=3, ge=1, le=5)
    idempotency_retention_days: int = Field(default=30, ge=1, le=365)
    verification_token_ttl_seconds: int = Field(default=1800, ge=300, le=86_400)
    team_invitation_ttl_seconds: int = Field(
        default=7 * 24 * 60 * 60,
        ge=300,
        le=30 * 24 * 60 * 60,
    )
    verification_delivery_max_attempts: int = Field(default=5, ge=1, le=10)
    verification_delivery_retry_seconds: int = Field(default=60, ge=1, le=3600)
    verification_public_base_url: str = "http://localhost:3000"
    resend_api_key: str | None = None
    resend_sender: str | None = None
    resend_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    test_support_key: str | None = None

    free_daily_file_cap: int = Field(default=5, ge=1, le=10_000)
    free_daily_page_cap: int = Field(default=50, ge=1, le=100_000)
    free_daily_gpu_cost_usd_cap: Decimal = Field(
        default=Decimal("1.000000"),
        gt=0,
    )
    free_gpu_cost_per_visual_page_usd: Decimal = Field(
        default=Decimal("0.020000"),
        ge=0,
    )
    payments_enabled: bool = False
    payment_provider: Literal["disabled", "fake", "merchant"] = "disabled"
    payment_merchant_id: str | None = None
    payment_webhook_secret: str | None = None
    payment_supported_currencies: str = "KRW,USD"
    payment_checkout_ttl_seconds: int = Field(default=1800, ge=300, le=86_400)
    payment_webhook_tolerance_seconds: int = Field(default=300, ge=30, le=900)
    payment_webhook_max_bytes: int = Field(default=65_536, ge=1024, le=1_048_576)
    payment_event_max_attempts: int = Field(default=8, ge=1, le=100)
    payment_event_retry_seconds: int = Field(default=60, ge=1, le=3600)
    payment_reconciliation_interval_seconds: int = Field(
        default=3600,
        ge=60,
        le=86_400,
    )
    payment_reconciliation_batch_size: int = Field(default=100, ge=1, le=1000)
    webhook_delivery_enabled: bool = False
    webhook_encryption_key: str | None = None
    webhook_allowed_hosts: str = ""
    webhook_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    webhook_max_attempts: int = Field(default=5, ge=1, le=10)
    webhook_max_endpoints_per_tenant: int = Field(default=20, ge=1, le=100)
    scheduler_poll_seconds: float = Field(default=1.0, ge=0.1, le=60.0)

    @property
    def object_root(self) -> Path:
        return self.data_dir / "objects"

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.web_origins.split(",") if item.strip()]

    @property
    def cdr_supported_mimes(self) -> frozenset[str]:
        return frozenset(
            item.strip().casefold()
            for item in self.cdr_supported_mime_types.split(",")
            if item.strip()
        )

    @property
    def oidc_scope_values(self) -> tuple[str, ...]:
        return tuple(item for item in self.oidc_scopes.split() if item)

    @property
    def oidc_algorithm_values(self) -> tuple[str, ...]:
        return tuple(
            item.strip() for item in self.oidc_allowed_algorithms.split(",") if item.strip()
        )

    @property
    def allowed_oidc_endpoint_hosts(self) -> frozenset[str]:
        configured = {
            item.strip().casefold()
            for item in self.oidc_allowed_endpoint_hosts.split(",")
            if item.strip()
        }
        if self.oidc_issuer_url:
            issuer_host = urlsplit(self.oidc_issuer_url).hostname
            if issuer_host:
                configured.add(issuer_host.casefold())
        return frozenset(configured)

    @property
    def mfa_plan_codes(self) -> frozenset[str]:
        return frozenset(
            item.strip().casefold() for item in self.mfa_required_plans.split(",") if item.strip()
        )

    @property
    def effective_cookie_secure(self) -> bool:
        return self.env == "production" if self.cookie_secure is None else self.cookie_secure

    @property
    def allowed_webhook_hosts(self) -> tuple[str, ...]:
        return tuple(
            item.strip().casefold()
            for item in self.webhook_allowed_hosts.split(",")
            if item.strip()
        )

    @property
    def trusted_proxy_networks(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.trusted_proxy_cidrs.split(",") if item.strip())

    @property
    def supported_payment_currencies(self) -> frozenset[str]:
        return frozenset(
            item.strip().upper()
            for item in self.payment_supported_currencies.split(",")
            if item.strip()
        )

    def _development_secret(self, purpose: str) -> bytes:
        return hmac.new(
            self.jwt_secret.encode("utf-8"),
            f"akc-local-{purpose}-v1".encode("ascii"),
            hashlib.sha256,
        ).digest()

    @property
    def effective_abuse_identity_hmac_secret(self) -> str:
        if self.abuse_identity_hmac_secret:
            return self.abuse_identity_hmac_secret
        if self.env == "production":
            raise ValueError("production abuse identity secret is not configured")
        return self._development_secret("abuse-identity").hex()

    @property
    def effective_verification_hmac_secret(self) -> str:
        if self.verification_hmac_secret:
            return self.verification_hmac_secret
        if self.env == "production":
            raise ValueError("production verification secret is not configured")
        return self._development_secret("verification-token").hex()

    @property
    def effective_oidc_transaction_encryption_key(self) -> str:
        if self.oidc_transaction_encryption_key:
            return self.oidc_transaction_encryption_key
        if self.env == "production":
            raise ValueError("production OIDC transaction encryption key is not configured")
        return base64.urlsafe_b64encode(self._development_secret("oidc-transaction")).decode(
            "ascii"
        )

    @property
    def effective_oidc_state_hmac_secret(self) -> str:
        if self.oidc_state_hmac_secret:
            return self.oidc_state_hmac_secret
        if self.env == "production":
            raise ValueError("production OIDC state secret is not configured")
        return self._development_secret("oidc-state").hex()

    @property
    def effective_mfa_encryption_key(self) -> str:
        if self.mfa_encryption_key:
            return self.mfa_encryption_key
        if self.env == "production":
            raise ValueError("production MFA encryption key is not configured")
        return base64.urlsafe_b64encode(self._development_secret("mfa-seed")).decode("ascii")

    @property
    def effective_mfa_recovery_hmac_secret(self) -> str:
        if self.mfa_recovery_hmac_secret:
            return self.mfa_recovery_hmac_secret
        if self.env == "production":
            raise ValueError("production MFA recovery secret is not configured")
        return self._development_secret("mfa-recovery").hex()

    @property
    def effective_verification_delivery_encryption_key(self) -> str:
        if self.verification_delivery_encryption_key:
            return self.verification_delivery_encryption_key
        if self.env == "production":
            raise ValueError("production verification encryption key is not configured")
        return base64.urlsafe_b64encode(self._development_secret("verification-delivery")).decode(
            "ascii"
        )

    @property
    def effective_idempotency_response_encryption_key(self) -> str:
        if self.idempotency_response_encryption_key:
            return self.idempotency_response_encryption_key
        if self.env == "production":
            raise ValueError("production idempotency encryption key is not configured")
        return base64.urlsafe_b64encode(self._development_secret("idempotency-response")).decode(
            "ascii"
        )

    @property
    def effective_url_encryption_key(self) -> str:
        if self.url_encryption_key:
            return self.url_encryption_key
        if self.env == "production":
            raise ValueError("production URL encryption key is not configured")
        return base64.urlsafe_b64encode(self._development_secret("url-encryption")).decode("ascii")

    @property
    def effective_url_query_hmac_secret(self) -> bytes:
        if self.url_query_hmac_secret:
            value = self.url_query_hmac_secret.encode("utf-8")
            if len(value) < 32:
                raise ValueError("URL query HMAC secret must contain at least 32 bytes")
            return value
        if self.env == "production":
            raise ValueError("production URL query HMAC secret is not configured")
        return self._development_secret("url-query-hmac")

    @property
    def effective_pdf_password_encryption_key(self) -> str:
        if self.pdf_password_encryption_key:
            return self.pdf_password_encryption_key
        if self.env == "production":
            raise ValueError("production PDF password encryption key is not configured")
        return base64.urlsafe_b64encode(self._development_secret("pdf-password-encryption")).decode(
            "ascii"
        )

    @property
    def effective_pdf_password_hmac_secret(self) -> bytes:
        if self.pdf_password_hmac_secret:
            encoded = self.pdf_password_hmac_secret.encode("utf-8")
            if len(encoded) < 32:
                raise ValueError("PDF password HMAC secret must contain at least 32 bytes")
            return encoded
        if self.env == "production":
            raise ValueError("production PDF password HMAC secret is not configured")
        return self._development_secret("pdf-password-hmac")

    @property
    def effective_payment_webhook_secret(self) -> str:
        if self.payment_webhook_secret:
            return self.payment_webhook_secret
        if self.env == "production":
            raise ValueError("production payment webhook secret is not configured")
        return self._development_secret("payment-webhook").hex()

    @model_validator(mode="after")
    def enforce_production_safety(self) -> Settings:
        try:
            tuple(ipaddress.ip_network(item, strict=False) for item in self.trusted_proxy_networks)
        except ValueError as exc:
            raise ValueError("AKC_TRUSTED_PROXY_CIDRS contains an invalid network") from exc
        currencies = self.supported_payment_currencies
        if not currencies or any(
            len(currency) != 3
            or not currency.isascii()
            or not currency.isalpha()
            or currency != currency.upper()
            for currency in currencies
        ):
            raise ValueError("AKC_PAYMENT_SUPPORTED_CURRENCIES must contain uppercase ISO codes")
        if not currencies.issubset({"KRW", "USD"}):
            raise ValueError("unsupported payment currency configuration")
        if self.payments_enabled and self.payment_provider == "disabled":
            raise ValueError("enabled payments require a provider")
        if self.payment_provider == "fake" and self.env == "production":
            raise ValueError("production forbids the fake payment provider")
        if self.payment_provider != "disabled":
            if not self.payment_merchant_id and self.env == "production":
                raise ValueError("production payment merchant id is not configured")
            if self.env == "production" and (
                not self.payment_webhook_secret
                or len(self.payment_webhook_secret.encode("utf-8")) < 32
            ):
                raise ValueError("production payment webhook secret must contain at least 32 bytes")
        if self.payment_webhook_secret and len(self.payment_webhook_secret.encode("utf-8")) < 32:
            raise ValueError("payment webhook secret must contain at least 32 bytes")
        if self.url_encryption_key:
            try:
                Fernet(self.url_encryption_key.encode("ascii"))
            except (UnicodeError, ValueError) as exc:
                raise ValueError("URL encryption key must be Fernet-compatible") from exc
        if self.url_query_hmac_secret and len(self.url_query_hmac_secret.encode("utf-8")) < 32:
            raise ValueError("URL query HMAC secret must contain at least 32 bytes")
        if bool(self.pdf_password_encryption_key) != bool(self.pdf_password_hmac_secret):
            raise ValueError("PDF password encryption and HMAC secrets must be configured together")
        if self.pdf_password_encryption_key:
            try:
                Fernet(self.pdf_password_encryption_key.encode("ascii"))
            except (UnicodeError, ValueError) as exc:
                raise ValueError("PDF password encryption key must be Fernet-compatible") from exc
            _ = self.effective_pdf_password_hmac_secret
        if self.register_captcha_after > self.register_client_limit:
            raise ValueError("registration CAPTCHA threshold exceeds its client limit")
        if self.login_captcha_after > min(
            self.login_client_limit,
            self.login_account_limit,
        ):
            raise ValueError("login CAPTCHA threshold exceeds a login limit")
        if self.resend_captcha_after > min(
            self.resend_client_limit,
            self.resend_account_limit,
        ):
            raise ValueError("resend CAPTCHA threshold exceeds a resend limit")
        if self.captcha_provider == "turnstile" and not self.captcha_secret_key:
            raise ValueError("Turnstile requires AKC_CAPTCHA_SECRET_KEY")
        if self.email_verification_provider == "resend":
            if not self.resend_api_key or not self.resend_sender:
                raise ValueError("Resend verification delivery requires API key and sender")
            verification_origin = urlsplit(self.verification_public_base_url)
            if (
                verification_origin.scheme != "https"
                or not verification_origin.hostname
                or verification_origin.username
                or verification_origin.password
                or verification_origin.query
                or verification_origin.fragment
            ):
                raise ValueError(
                    "Resend verification delivery requires a credential-free HTTPS base URL"
                )
        if self.test_support_key and self.env != "test":
            raise ValueError("AKC_TEST_SUPPORT_KEY is permitted only in test")
        if not self.mfa_plan_codes or not self.mfa_plan_codes.issubset({"team", "enterprise"}):
            raise ValueError("AKC_MFA_REQUIRED_PLANS must contain Team/Enterprise plan codes")
        if bool(self.mfa_encryption_key) != bool(self.mfa_recovery_hmac_secret):
            raise ValueError("MFA encryption and recovery HMAC secrets must be configured together")
        if self.mfa_encryption_key or self.env != "production":
            try:
                Fernet(self.effective_mfa_encryption_key.encode("ascii"))
            except (UnicodeError, ValueError) as exc:
                raise ValueError("MFA encryption key must be Fernet-compatible") from exc
            if len(self.effective_mfa_recovery_hmac_secret.encode("utf-8")) < 32:
                raise ValueError("MFA recovery HMAC secret must contain at least 32 bytes")
        if self.oidc_enabled:
            if not self.oidc_issuer_url or not self.oidc_client_id or not self.oidc_redirect_uri:
                raise ValueError("OIDC requires issuer URL, client ID, and redirect URI")
            issuer = urlsplit(self.oidc_issuer_url)
            if (
                issuer.scheme != "https"
                or not issuer.hostname
                or issuer.username
                or issuer.password
                or issuer.query
                or issuer.fragment
            ):
                raise ValueError("OIDC issuer must be a credential-free HTTPS URL")
            redirect = urlsplit(self.oidc_redirect_uri)
            local_redirect = (
                self.env != "production"
                and redirect.scheme == "http"
                and redirect.hostname in {"127.0.0.1", "localhost", "testserver"}
            )
            if (
                (redirect.scheme != "https" and not local_redirect)
                or not redirect.hostname
                or redirect.username
                or redirect.password
                or redirect.query
                or redirect.fragment
            ):
                raise ValueError(
                    "OIDC redirect URI must be credential-free HTTPS "
                    "(or local HTTP in non-production)"
                )
            if "openid" not in self.oidc_scope_values:
                raise ValueError("OIDC scopes must include openid")
            algorithms = set(self.oidc_algorithm_values)
            if not algorithms or not algorithms.issubset(
                {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
            ):
                raise ValueError("OIDC algorithms must be asymmetric and allowlisted")
            if not self.allowed_oidc_endpoint_hosts:
                raise ValueError("OIDC endpoint host allowlist is empty")
            try:
                Fernet(self.effective_oidc_transaction_encryption_key.encode("ascii"))
            except (UnicodeError, ValueError) as exc:
                raise ValueError(
                    "OIDC transaction encryption key must be Fernet-compatible"
                ) from exc
            if len(self.effective_oidc_state_hmac_secret.encode("utf-8")) < 32:
                raise ValueError("OIDC state HMAC secret must contain at least 32 bytes")
            if self.env == "production" and (
                not self.oidc_client_secret or len(self.oidc_client_secret.encode("utf-8")) < 24
            ):
                raise ValueError("production OIDC requires a confidential client secret")
        if self.private_mode and self.external_ocr_enabled:
            raise ValueError("private_mode forbids external OCR transfer")
        if not self.cdr_supported_mimes:
            raise ValueError("AKC_CDR_SUPPORTED_MIME_TYPES cannot be empty")
        if self.cdr_enabled:
            if self.cdr_provider != "http" or not self.cdr_endpoint_url:
                raise ValueError("enabled CDR requires the HTTP provider and endpoint")
            endpoint = urlsplit(self.cdr_endpoint_url)
            local_http = (
                self.env != "production"
                and endpoint.scheme == "http"
                and endpoint.hostname in {"127.0.0.1", "localhost", "testserver"}
            )
            if (
                (endpoint.scheme != "https" and not local_http)
                or not endpoint.hostname
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
            ):
                raise ValueError(
                    "CDR endpoint must be credential-free HTTPS (or local HTTP in non-production)"
                )
        if self.env == "production" and self.local_analysis_worker_enabled:
            raise ValueError("production forbids the in-process analysis adapter")
        if self.knowledge_provider == "qwen_durable":
            exact_sha = re.compile(r"^sha256:[0-9a-f]{64}$")
            if self.object_store_driver != "s3":
                raise ValueError("durable Qwen requires S3-compatible object storage")
            if not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", self.qwen_endpoint_id):
                raise ValueError("AKC_QWEN_ENDPOINT_ID is invalid")
            if not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.:-]{1,79}",
                self.qwen_provider_key,
            ):
                raise ValueError("AKC_QWEN_PROVIDER_KEY is invalid")
            if not re.fullmatch(r"[0-9a-f]{40,64}", self.qwen_model_revision):
                raise ValueError("AKC_QWEN_MODEL_REVISION must be exact")
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
        if bool(self.s3_access_key_id) != bool(self.s3_secret_access_key):
            raise ValueError("both S3 static credential fields must be set together")
        if (
            self.object_store_driver == "s3"
            and not self.s3_use_ambient_credentials
            and not (self.s3_access_key_id and self.s3_secret_access_key)
        ):
            raise ValueError("S3 requires static or ambient workload credentials")
        if self.max_upload_bytes > (self.multipart_part_size_bytes * self.multipart_max_parts):
            raise ValueError("multipart part size/count must cover AKC_MAX_UPLOAD_BYTES")
        if self.webhook_delivery_enabled:
            from akc_scheduler.webhooks import HostAllowlist

            try:
                Fernet((self.webhook_encryption_key or "").encode("ascii"))
            except (UnicodeError, ValueError) as exc:
                raise ValueError(
                    "webhook delivery requires a Fernet-compatible encryption key"
                ) from exc
            HostAllowlist(self.allowed_webhook_hosts)
        if self.otel_enabled and not self.otel_exporter_otlp_endpoint:
            raise ValueError("AKC_OTEL_EXPORTER_OTLP_ENDPOINT is required when enabled")
        if self.otel_exporter_otlp_endpoint:
            endpoint = urlsplit(self.otel_exporter_otlp_endpoint)
            if (
                endpoint.scheme not in {"http", "https"}
                or not endpoint.hostname
                or endpoint.username
                or endpoint.password
                or endpoint.path not in {"", "/"}
                or endpoint.query
                or endpoint.fragment
            ):
                raise ValueError("AKC_OTEL_EXPORTER_OTLP_ENDPOINT must be a credential-free origin")
        if self.analysis_lease_seconds <= self.analysis_attempt_timeout_seconds:
            raise ValueError("analysis_lease_seconds must exceed analysis_attempt_timeout_seconds")
        if self.analysis_max_source_bytes > self.max_upload_bytes:
            raise ValueError("analysis_max_source_bytes cannot exceed max_upload_bytes")
        # ADR-006 — the anonymous cap may only be tighter than the authenticated
        # one. Misconfiguring it the other way would let a visitor with no
        # account submit a larger object than a paying tenant can.
        if self.trial_ingest_max_bytes > self.analysis_max_source_bytes:
            raise ValueError(
                "trial_ingest_max_bytes cannot exceed analysis_max_source_bytes"
            )
        # RateLimitPolicy rejects a captcha threshold above the hard limit, and
        # it would be a startup crash rather than a config error if it reached
        # that constructor. Catch it here where the message is actionable.
        if self.trial_ingest_captcha_after > self.trial_ingest_sessions_per_client:
            raise ValueError(
                "trial_ingest_captcha_after cannot exceed trial_ingest_sessions_per_client"
            )
        # Enabling anonymous ingest without a limiter would leave the endpoint
        # with no bound at all. _consume_rate_control fails closed when the
        # backend is unavailable, but an operator should not be able to ship the
        # endpoint with no backend configured either.
        if self.env == "production" and self.trial_ingest_enabled:
            if not self.redis_url:
                raise ValueError(
                    "trial_ingest_enabled requires AKC_REDIS_URL in production"
                )
            if self.captcha_provider == "disabled":
                raise ValueError(
                    "trial_ingest_enabled requires a captcha provider in production"
                )
        if self.analysis_backoff_max_seconds < self.analysis_backoff_base_seconds:
            raise ValueError(
                "analysis_backoff_max_seconds must be at least analysis_backoff_base_seconds"
            )
        if (
            self.env == "production"
            and self.webhook_delivery_enabled
            and not self.allowed_webhook_hosts
        ):
            raise ValueError("webhook delivery requires an explicit host allowlist")
        if self.env == "production":
            if len(self.jwt_secret) < 32 or "change-before-production" in self.jwt_secret:
                raise ValueError("AKC_JWT_SECRET must be a strong production secret")
            if self.database_url.startswith("sqlite"):
                raise ValueError("production requires PostgreSQL")
            if self.local_background_tasks:
                raise ValueError("production requires the durable scheduler adapter")
            if self.object_store_driver != "s3":
                raise ValueError("production requires S3-compatible object storage")
            if self.multipart_upload_threshold_bytes >= self.max_upload_bytes:
                raise ValueError(
                    "production multipart threshold must be below the product upload limit"
                )
            if self.s3_endpoint_url:
                endpoint = urlsplit(self.s3_endpoint_url)
                if endpoint.scheme != "https" or not endpoint.hostname:
                    raise ValueError("production S3-compatible endpoint must use HTTPS")
            if not self.clamav_enabled or self.allow_development_antivirus_bypass:
                raise ValueError("production requires fail-closed antivirus scanning")
            if not self.metrics_enabled:
                raise ValueError("production requires Prometheus metrics")
            if not self.otel_enabled:
                raise ValueError("production requires OpenTelemetry export")
            if self.email_verification_provider == "capture":
                raise ValueError("production forbids development email capture")
            if self.allow_public_registration:
                if (
                    not self.email_verification_enabled
                    or self.email_verification_provider != "resend"
                ):
                    raise ValueError(
                        "public production registration requires verified email delivery"
                    )
                if self.captcha_provider != "turnstile":
                    raise ValueError("public production registration requires risk CAPTCHA")
            if self.url_ingestion_enabled:
                try:
                    Fernet((self.url_encryption_key or "").encode("ascii"))
                except (UnicodeError, ValueError) as exc:
                    raise ValueError("production URL ingestion requires a Fernet key") from exc
                if (
                    not self.url_query_hmac_secret
                    or len(self.url_query_hmac_secret.encode("utf-8")) < 32
                ):
                    raise ValueError(
                        "production URL ingestion requires a 32-byte query HMAC secret"
                    )
            if self.knowledge_provider == "deterministic":
                raise ValueError("production forbids the deterministic knowledge provider")
            if not self.redis_url:
                raise ValueError("production requires Redis-backed abuse controls")
            if not self.redis_url.startswith("rediss://"):
                raise ValueError("production Redis abuse controls require TLS")
            try:
                Fernet((self.idempotency_response_encryption_key or "").encode("ascii"))
            except (UnicodeError, ValueError) as exc:
                raise ValueError("production idempotency responses require a Fernet key") from exc
            secret_values = (
                self.abuse_identity_hmac_secret,
                self.verification_hmac_secret,
                self.pdf_password_hmac_secret,
            )
            if any(secret is None or len(secret.encode("utf-8")) < 32 for secret in secret_values):
                raise ValueError(
                    "production requires explicit 32-byte abuse, verification, and PDF secrets"
                )
            if len(set(cast(str, value) for value in secret_values)) != len(secret_values):
                raise ValueError("production abuse, verification, and PDF secrets must be distinct")
            try:
                Fernet((self.pdf_password_encryption_key or "").encode("ascii"))
            except (UnicodeError, ValueError) as exc:
                raise ValueError("production PDF passwords require a Fernet key") from exc
            try:
                Fernet((self.verification_delivery_encryption_key or "").encode("ascii"))
            except (UnicodeError, ValueError) as exc:
                raise ValueError("production verification delivery requires a Fernet key") from exc
            if not self.mfa_encryption_key or not self.mfa_recovery_hmac_secret:
                raise ValueError("production requires explicit MFA encryption and recovery secrets")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
