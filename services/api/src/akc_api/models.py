"""Tenant-safe persistence model for the control plane."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from akc_api.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def uuid4() -> uuid.UUID:
    return uuid.uuid4()


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    plan_code: Mapped[str] = mapped_column(String(40), default="free")
    region: Mapped[str] = mapped_column(String(40), default="ap-northeast")
    data_retention_days: Mapped[int] = mapped_column(Integer, default=7)
    private_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    external_transfer_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    training_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    preview_pii_masking: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint("data_retention_days BETWEEN 0 AND 3650"),
        UniqueConstraint("id", "slug"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OidcIdentity(Base):
    """Stable external subject binding.

    Email is evidence shown by the provider at bind time, not the identity key.
    Only the issuer and immutable OIDC ``sub`` claim identify an account.
    """

    __tablename__ = "oidc_identities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email_at_binding: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_oidc_identity_subject"),
        UniqueConstraint("user_id", "issuer", name="uq_oidc_identity_user_issuer"),
        Index("oidc_identities_user_idx", "user_id"),
    )


class OidcLoginTransaction(Base):
    """Single-use, encrypted OIDC authorization transaction."""

    __tablename__ = "oidc_login_transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    browser_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    encrypted_secrets: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    binding_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    binding_tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE")
    )
    tenant_slug: Mapped[str | None] = mapped_column(String(100))
    tenant_name: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint("purpose IN ('login','bind')", name="oidc_transaction_purpose_check"),
        Index(
            "oidc_login_transactions_active_idx",
            "expires_at",
            postgresql_where=text("consumed_at IS NULL"),
            sqlite_where=text("consumed_at IS NULL"),
        ),
    )


class Membership(Base):
    __tablename__ = "memberships"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint("role IN ('owner','admin','editor','reviewer','viewer','billing')"),
    )


class MfaCredential(Base):
    """Tenant-scoped TOTP factor with encrypted seed and one-way recovery codes."""

    __tablename__ = "mfa_credentials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    encrypted_secret: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    recovery_code_hashes: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_totp_step: Mapped[int | None] = mapped_column(BigInteger)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('pending','active','disabled')",
            name="mfa_credential_status_check",
        ),
        UniqueConstraint("tenant_id", "user_id", name="uq_mfa_credential_tenant_user"),
        UniqueConstraint("tenant_id", "id"),
    )


class MfaChallenge(Base):
    """Durable single-use login/enrollment challenge."""

    __tablename__ = "mfa_challenges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("purpose IN ('enroll','challenge')", name="mfa_challenge_purpose_check"),
        CheckConstraint("failures BETWEEN 0 AND 5", name="mfa_challenge_failures_check"),
        UniqueConstraint("tenant_id", "id"),
        Index(
            "mfa_challenges_active_idx",
            "tenant_id",
            "user_id",
            "expires_at",
            postgresql_where=text("consumed_at IS NULL"),
            sqlite_where=text("consumed_at IS NULL"),
        ),
    )


class EmailVerificationToken(Base):
    """One-time email verification credential stored only as an HMAC digest."""

    __tablename__ = "email_verification_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        Index(
            "email_verification_tokens_active_idx",
            "tenant_id",
            "user_id",
            "expires_at",
            postgresql_where=text("consumed_at IS NULL AND invalidated_at IS NULL"),
            sqlite_where=text("consumed_at IS NULL AND invalidated_at IS NULL"),
        ),
    )


class EmailVerificationDelivery(Base):
    """Transactional encrypted outbox for verification delivery."""

    __tablename__ = "email_verification_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    token_hash: Mapped[str] = mapped_column(String(64))
    recipient_pseudonym: Mapped[str] = mapped_column(String(67))
    encrypted_payload: Mapped[bytes] = mapped_column(LargeBinary)
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["token_hash"],
            ["email_verification_tokens.token_hash"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "token_hash"),
        CheckConstraint("status IN ('pending','retry','delivered','dead_letter')"),
        CheckConstraint("attempts >= 0"),
        Index(
            "email_verification_deliveries_due_idx",
            "available_at",
            "created_at",
            "id",
            postgresql_where=text("status IN ('pending','retry')"),
            sqlite_where=text("status IN ('pending','retry')"),
        ),
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(24), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text)
    output_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    classification: Mapped[str] = mapped_column(String(40), default="general")
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        Index("projects_tenant_updated_idx", "tenant_id", "updated_at"),
        Index(
            "projects_active_idx",
            "tenant_id",
            "updated_at",
            "id",
            postgresql_where=text("deletion_requested_at IS NULL"),
            sqlite_where=text("deletion_requested_at IS NULL"),
        ),
    )


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    original_filename: Mapped[str] = mapped_column(String(500))
    safe_filename: Mapped[str] = mapped_column(String(240))
    expected_mime: Mapped[str] = mapped_column(String(160))
    expected_size: Mapped[int] = mapped_column(Integer)
    expected_sha256: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(500), unique=True)
    upload_mode: Mapped[str] = mapped_column(String(16), default="single")
    provider_upload_id: Mapped[str | None] = mapped_column(String(512))
    multipart_part_size: Mapped[int | None] = mapped_column(Integer)
    multipart_part_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="initiated")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("expected_size >= 0"),
        CheckConstraint("document_version >= 1"),
        CheckConstraint(
            "upload_mode IN ('single','multipart')",
            name="ck_upload_sessions_upload_mode",
        ),
        CheckConstraint(
            "(upload_mode = 'single' AND provider_upload_id IS NULL "
            "AND multipart_part_size IS NULL AND multipart_part_count IS NULL) "
            "OR (upload_mode = 'multipart' AND provider_upload_id IS NOT NULL "
            "AND multipart_part_size > 0 AND multipart_part_count > 0)",
            name="ck_upload_sessions_multipart_shape",
        ),
        CheckConstraint("status IN ('initiated','uploaded','completed','aborted','expired')"),
        UniqueConstraint("tenant_id", "id"),
        Index("upload_sessions_expiry_idx", "status", "expires_at"),
        Index(
            "upload_sessions_one_active_document_version_idx",
            "tenant_id",
            "document_id",
            "document_version",
            unique=True,
            postgresql_where=text("status IN ('initiated','uploaded')"),
            sqlite_where=text("status IN ('initiated','uploaded')"),
        ),
    )


class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    upload_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    original_filename: Mapped[str] = mapped_column(String(500))
    safe_filename: Mapped[str] = mapped_column(String(240))
    mime_type: Mapped[str] = mapped_column(String(160))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    antivirus_status: Mapped[str] = mapped_column(String(32), default="clean")
    cdr_status: Mapped[str] = mapped_column(String(32), default="not_requested")
    cdr_provider: Mapped[str | None] = mapped_column(String(80))
    cdr_revision: Mapped[str | None] = mapped_column(String(160))
    sanitized_storage_key: Mapped[str | None] = mapped_column(String(500), unique=True)
    sanitized_sha256: Mapped[str | None] = mapped_column(String(64))
    sanitized_size_bytes: Mapped[int | None] = mapped_column(Integer)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "upload_id"],
            ["upload_sessions.tenant_id", "upload_sessions.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "project_id", "sha256"),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("size_bytes >= 0"),
        CheckConstraint(
            "cdr_status IN ('not_requested','sanitized','unsupported','unavailable','rejected')",
            name="ck_source_files_cdr_status",
        ),
        CheckConstraint(
            "(cdr_status = 'sanitized' AND sanitized_storage_key IS NOT NULL "
            "AND sanitized_sha256 IS NOT NULL AND length(sanitized_sha256) = 64 "
            "AND sanitized_size_bytes > 0 AND cdr_provider IS NOT NULL "
            "AND cdr_revision IS NOT NULL) OR "
            "(cdr_status <> 'sanitized' AND sanitized_storage_key IS NULL "
            "AND sanitized_sha256 IS NULL AND sanitized_size_bytes IS NULL)",
            name="ck_source_files_cdr_derivative_shape",
        ),
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(500))
    document_type: Mapped[str] = mapped_column(String(80))
    language_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    page_count: Mapped[int | None] = mapped_column(Integer)
    active_version: Mapped[int] = mapped_column(Integer, default=1)
    cir_schema_version: Mapped[str] = mapped_column(String(20), default="1.0")
    status: Mapped[str] = mapped_column(String(40), default="UPLOADED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_file_id"],
            ["source_files.tenant_id", "source_files.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id"),
        Index(
            "documents_active_idx",
            "tenant_id",
            "project_id",
            "id",
            postgresql_where=text("deletion_requested_at IS NULL"),
            sqlite_where=text("deletion_requested_at IS NULL"),
        ),
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    source_filename: Mapped[str | None] = mapped_column(String(500))
    source_mime_type: Mapped[str | None] = mapped_column(String(160))
    source_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    cir_object_key: Mapped[str | None] = mapped_column(String(500))
    cir_snapshot_sha256: Mapped[str | None] = mapped_column(String(64))
    archived_objects: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    input_revision_hash: Mapped[str | None] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(120))
    model_revision: Mapped[str] = mapped_column(String(200))
    prompt_revision: Mapped[str | None] = mapped_column(String(120))
    normalization_revision: Mapped[str | None] = mapped_column(String(120))
    akmp_schema_version: Mapped[str] = mapped_column(String(20), default="1.0")
    status: Mapped[str] = mapped_column(String(32), default="source_verified")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_file_id"],
            ["source_files.tenant_id", "source_files.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("document_id", "version"),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("version >= 1"),
        CheckConstraint("source_size_bytes IS NULL OR source_size_bytes >= 0"),
        CheckConstraint(
            "status IN ('source_verified','processed','archived')",
            name="ck_document_versions_status",
        ),
        Index("document_versions_source_idx", "tenant_id", "source_file_id"),
    )


class DocumentSemanticClassification(Base):
    """Evidence-bound semantic profile, separate from the source file format."""

    __tablename__ = "document_semantic_classifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_version: Mapped[int] = mapped_column(Integer)
    compile_input_sha256: Mapped[str] = mapped_column(String(64))
    classification: Mapped[dict[str, Any]] = mapped_column(JSON)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON)
    provider_key: Mapped[str] = mapped_column(String(80))
    model_revision: Mapped[str] = mapped_column(String(64))
    runtime_image_digest: Mapped[str] = mapped_column(String(71))
    adapter_version: Mapped[str] = mapped_column(String(160))
    prompt_revision: Mapped[str] = mapped_column(String(71))
    schema_sha256: Mapped[str] = mapped_column(String(71))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "document_version",
            "compile_input_sha256",
            "schema_sha256",
            "model_revision",
            name="uq_document_semantic_classification_version",
        ),
        CheckConstraint("document_version >= 1"),
        CheckConstraint("length(compile_input_sha256) = 64"),
        CheckConstraint("length(model_revision) BETWEEN 40 AND 64"),
        CheckConstraint("length(runtime_image_digest) = 71"),
        CheckConstraint("length(prompt_revision) = 71"),
        CheckConstraint("length(schema_sha256) = 71"),
        Index(
            "document_semantic_classifications_document_idx",
            "tenant_id",
            "document_id",
            "document_version",
            "compile_input_sha256",
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active = 1"),
        ),
        Index(
            "document_semantic_classifications_one_active_idx",
            "tenant_id",
            "document_id",
            "document_version",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active = 1"),
        ),
    )


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    page_number: Mapped[int] = mapped_column(Integer)
    width_pt: Mapped[float | None]
    height_pt: Mapped[float | None]
    rotation: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="UPLOADED")
    route: Mapped[str | None] = mapped_column(String(80))
    route_policy_version: Mapped[str | None] = mapped_column(String(120))
    preflight_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    thumbnail_key: Mapped[str | None] = mapped_column(String(500))
    render_key: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("document_id", "page_number"),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("page_number >= 1"),
        Index("pages_document_status_idx", "document_id", "status", "page_number"),
    )


class PageAttempt(Base):
    """One bounded processing attempt for a logical, immutable page.

    A page keeps the terminal result produced by analysis. Reprocessing creates
    a new attempt row instead of reopening that page. Attempt identity and
    routing inputs are immutable; lifecycle state can only advance through the
    page-attempt transition service until it reaches a terminal state.
    """

    __tablename__ = "page_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    page_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    analysis_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    provider_invocation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    attempt_number: Mapped[int] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(40))
    route: Mapped[str] = mapped_column(String(80))
    route_profile: Mapped[str] = mapped_column(String(80))
    route_policy_version: Mapped[str] = mapped_column(String(120))
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    quality_vector: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    quality_evaluation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    escalation_decision: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "page_id"],
            ["pages.tenant_id", "pages.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("page_id", "attempt_number"),
        UniqueConstraint("analysis_task_id", "page_id"),
        CheckConstraint("attempt_number >= 1"),
        CheckConstraint("max_attempts BETWEEN 1 AND 5"),
        CheckConstraint("trigger IN ('analysis','compile','user_retry','provider_resume')"),
        CheckConstraint(
            "status IN ("
            "'UPLOADED','SECURITY_SCANNING','SECURITY_VERIFIED','PREFLIGHTING',"
            "'PREFLIGHTED','NATIVE_EXTRACTING','OCR_QUEUED','OCR_RUNNING',"
            "'NORMALIZING','VALIDATING','COMPLETED','NEEDS_REVIEW',"
            "'RETRY_SCHEDULED','FAILED')"
        ),
        CheckConstraint("event_sequence >= 0"),
        Index("page_attempts_page_number_idx", "page_id", "attempt_number"),
        Index("page_attempts_job_idx", "tenant_id", "job_id"),
        Index(
            "page_attempts_one_active_idx",
            "page_id",
            unique=True,
            postgresql_where=text("status NOT IN ('COMPLETED','NEEDS_REVIEW','FAILED')"),
            sqlite_where=text("status NOT IN ('COMPLETED','NEEDS_REVIEW','FAILED')"),
        ),
    )


class PageAttemptTransitionEvent(Base):
    """Append-only evidence for every page-attempt state transition."""

    __tablename__ = "page_attempt_transition_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    sequence: Mapped[int] = mapped_column(Integer)
    previous_state: Mapped[str | None] = mapped_column(String(40))
    current_state: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(160))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "attempt_id"],
            ["page_attempts.tenant_id", "page_attempts.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("attempt_id", "sequence"),
        CheckConstraint("sequence >= 1"),
        Index(
            "page_attempt_transition_events_stream_idx",
            "attempt_id",
            "sequence",
        ),
    )


class PageAsset(Base):
    __tablename__ = "page_assets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    page_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    asset_type: Mapped[str] = mapped_column(String(40))
    storage_key: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "page_id"],
            ["pages.tenant_id", "pages.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
    )


class Block(Base):
    __tablename__ = "blocks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("pages.id", ondelete="SET NULL"),
    )
    parent_block_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("blocks.id", ondelete="SET NULL"),
    )
    block_order: Mapped[int] = mapped_column(Integer)
    block_type: Mapped[str] = mapped_column(String(40))
    origin: Mapped[str] = mapped_column(String(40))
    bbox1000: Mapped[list[int] | None] = mapped_column(JSON)
    polygon_norm: Mapped[list[list[float]] | None] = mapped_column(JSON)
    source_text: Mapped[str | None] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    markdown: Mapped[str | None] = mapped_column(Text)
    structured_content: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    engine: Mapped[str | None] = mapped_column(String(120))
    engine_revision: Mapped[str | None] = mapped_column(String(200))
    confidence: Mapped[float | None]
    content_hash: Mapped[str | None] = mapped_column(String(64))
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    user_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)"),
        Index("blocks_document_order_idx", "document_id", "block_order"),
        Index("blocks_page_order_idx", "page_id", "block_order"),
    )


class BlockRevision(Base):
    __tablename__ = "block_revisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    block_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    base_revision: Mapped[int] = mapped_column(Integer)
    new_revision: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(60))
    base_value: Mapped[str | None] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "block_id"],
            ["blocks.tenant_id", "blocks.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("block_id", "new_revision"),
        UniqueConstraint("tenant_id", "id"),
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    job_type: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    priority: Mapped[int] = mapped_column(Integer, default=5)
    requested_options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost_estimate: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost_actual: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("priority BETWEEN 0 AND 9"),
        CheckConstraint(
            "status IN ('queued','running','waiting_review','completed','failed','cancelled')"
        ),
    )


class AnalysisTask(Base):
    """Durable, idempotent native-analysis work item.

    The API owns creation; only the isolated CPU document worker owns the
    execution lease and result fields.
    """

    __tablename__ = "analysis_tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_version: Mapped[int] = mapped_column(Integer, default=1)
    source_file_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    requested_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    block_count: Mapped[int] = mapped_column(Integer, default=0)
    preview_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_file_id"],
            ["source_files.tenant_id", "source_files.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "document_id", "document_version"),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("document_version >= 1"),
        CheckConstraint("status IN ('queued','running','completed','failed','dead_letter')"),
        CheckConstraint("attempt_count >= 0"),
        CheckConstraint("max_attempts BETWEEN 1 AND 10"),
        CheckConstraint("attempt_count <= max_attempts"),
        CheckConstraint("page_count >= 0"),
        CheckConstraint("block_count >= 0"),
        CheckConstraint("preview_count >= 0"),
        Index(
            "analysis_tasks_due_idx",
            "available_at",
            "created_at",
            "id",
            postgresql_where=text("status IN ('queued','running')"),
            sqlite_where=text("status IN ('queued','running')"),
        ),
    )


class GpuProviderInvocation(Base):
    """Durable, content-free control-plane state for one GPU invocation."""

    __tablename__ = "gpu_provider_invocations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_version_id: Mapped[str] = mapped_column(String(160))
    page_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(40), default="runpod")
    provider_key: Mapped[str] = mapped_column(String(80))
    endpoint_id: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_manifest_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    input_bucket: Mapped[str] = mapped_column(String(16))
    input_object_key: Mapped[str] = mapped_column(String(500))
    input_sha256: Mapped[str] = mapped_column(String(64))
    output_object_key: Mapped[str] = mapped_column(String(500))
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_revision: Mapped[str] = mapped_column(String(64))
    runtime_image_digest: Mapped[str] = mapped_column(String(71))
    adapter_version: Mapped[str] = mapped_column(String(160))
    transition_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    parent_invocation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lineage_root_invocation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    transition_category: Mapped[str | None] = mapped_column(String(32))
    transition_strategy: Mapped[str | None] = mapped_column(String(32))
    transition_action: Mapped[str | None] = mapped_column(String(24))
    transition_attempt: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    cancel_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    provider_job_id: Mapped[str | None] = mapped_column(String(160))
    provider_status: Mapped[str | None] = mapped_column(String(32))
    provider_callback_id: Mapped[str | None] = mapped_column(String(160))
    provider_callback_sha256: Mapped[str | None] = mapped_column(String(64))
    provider_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    object_grant_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(40))
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    result_manifest: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result_manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    completion_source: Mapped[str | None] = mapped_column(String(16))
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["processing_jobs.tenant_id", "processing_jobs.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "page_id"],
            ["pages.tenant_id", "pages.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_invocation_id"],
            ["gpu_provider_invocations.tenant_id", "gpu_provider_invocations.id"],
            name="fk_gpu_invocation_parent",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "lineage_root_invocation_id"],
            ["gpu_provider_invocations.tenant_id", "gpu_provider_invocations.id"],
            name="fk_gpu_invocation_lineage_root",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ("
            "'queued','submitting','submitted','running','retry',"
            "'cancel_requested','cancelling','completed','failed',"
            "'dead_letter','cancelled')"
        ),
        CheckConstraint("input_bucket IN ('source','derived')"),
        CheckConstraint("length(input_sha256) = 64"),
        CheckConstraint("length(request_manifest_sha256) = 64"),
        CheckConstraint("length(model_revision) BETWEEN 40 AND 64"),
        CheckConstraint("length(runtime_image_digest) = 71"),
        CheckConstraint("attempt_count >= 0"),
        CheckConstraint("cancel_attempt_count >= 0"),
        CheckConstraint("max_attempts BETWEEN 1 AND 10"),
        CheckConstraint("attempt_count <= max_attempts"),
        CheckConstraint("event_sequence >= 0"),
        CheckConstraint(
            "("
            "parent_invocation_id IS NULL "
            "AND lineage_root_invocation_id IS NULL "
            "AND transition_category IS NULL "
            "AND transition_strategy IS NULL "
            "AND transition_action IS NULL "
            "AND transition_attempt = 0"
            ") OR ("
            "parent_invocation_id IS NOT NULL "
            "AND lineage_root_invocation_id IS NOT NULL "
            "AND transition_category IN ('gpu_oom','invalid_output') "
            "AND transition_strategy IN ('reduce_or_escalate','fallback') "
            "AND transition_action IN ('reduce','escalate','fallback') "
            "AND transition_attempt BETWEEN 1 AND 10"
            ")",
            name="gpu_invocation_transition_metadata_check",
        ),
        CheckConstraint(
            "parent_invocation_id IS NULL OR parent_invocation_id <> id",
            name="gpu_invocation_parent_not_self_check",
        ),
        CheckConstraint("result_manifest_sha256 IS NULL OR length(result_manifest_sha256) = 64"),
        CheckConstraint(
            "provider_callback_sha256 IS NULL OR length(provider_callback_sha256) = 64"
        ),
        CheckConstraint("completion_source IS NULL OR completion_source IN ('poll','callback')"),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "idempotency_key"),
        UniqueConstraint("provider", "provider_callback_id"),
        Index(
            "gpu_provider_invocations_due_idx",
            "available_at",
            "created_at",
            "id",
            postgresql_where=text(
                "status IN ("
                "'queued','submitting','submitted','running','retry',"
                "'cancel_requested','cancelling')"
            ),
            sqlite_where=text(
                "status IN ("
                "'queued','submitting','submitted','running','retry',"
                "'cancel_requested','cancelling')"
            ),
        ),
        Index(
            "gpu_provider_invocations_job_idx",
            "tenant_id",
            "job_id",
            "created_at",
        ),
        Index(
            "gpu_provider_invocations_parent_idx",
            "tenant_id",
            "parent_invocation_id",
        ),
        Index(
            "gpu_provider_invocations_lineage_idx",
            "tenant_id",
            "lineage_root_invocation_id",
            "created_at",
        ),
    )


class GpuProviderAttempt(Base):
    """Append-only attempt identity with bounded mutable outcome fields."""

    __tablename__ = "gpu_provider_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    invocation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="submitting")
    request_manifest_sha256: Mapped[str] = mapped_column(String(64))
    provider_job_id: Mapped[str | None] = mapped_column(String(160))
    provider_response_sha256: Mapped[str | None] = mapped_column(String(71))
    result_manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(120))
    retryable: Mapped[bool | None] = mapped_column(Boolean)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "invocation_id"],
            ["gpu_provider_invocations.tenant_id", "gpu_provider_invocations.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("attempt_number BETWEEN 1 AND 10"),
        CheckConstraint(
            "status IN ("
            "'submitting','submitted','running','retry','completed',"
            "'failed','cancelled','timed_out')"
        ),
        CheckConstraint("length(request_manifest_sha256) = 64"),
        CheckConstraint(
            "provider_response_sha256 IS NULL OR length(provider_response_sha256) = 71"
        ),
        CheckConstraint("result_manifest_sha256 IS NULL OR length(result_manifest_sha256) = 64"),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("invocation_id", "attempt_number"),
        Index(
            "gpu_provider_attempts_invocation_idx",
            "invocation_id",
            "attempt_number",
        ),
    )


class GpuInvocationEvent(Base):
    """Append-only, content-free state transition evidence."""

    __tablename__ = "gpu_invocation_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    invocation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "invocation_id"],
            ["gpu_provider_invocations.tenant_id", "gpu_provider_invocations.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("sequence >= 1"),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("invocation_id", "sequence"),
        Index(
            "gpu_invocation_events_stream_idx",
            "invocation_id",
            "sequence",
        ),
    )


class FreeDailyUsage(Base):
    """UTC-day counters used to enforce free-tier cost ceilings."""

    __tablename__ = "free_daily_usage"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    gpu_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        default=Decimal("0"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint("file_count >= 0"),
        CheckConstraint("page_count >= 0"),
        CheckConstraint("gpu_cost_usd >= 0"),
    )


class FreeUsageReservation(Base):
    """Idempotency record for one committed free-tier usage reservation."""

    __tablename__ = "free_usage_reservations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    usage_date: Mapped[date] = mapped_column(Date)
    operation_key: Mapped[str] = mapped_column(String(200))
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    gpu_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        default=Decimal("0"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "usage_date"],
            ["free_daily_usage.tenant_id", "free_daily_usage.usage_date"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "operation_key"),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("file_count >= 0"),
        CheckConstraint("page_count >= 0"),
        CheckConstraint("gpu_cost_usd >= 0"),
        CheckConstraint("file_count > 0 OR page_count > 0 OR gpu_cost_usd > 0"),
    )


class FreeProcessedSource(Base):
    """Tenant-wide source digest claim preventing repeated free processing."""

    __tablename__ = "free_processed_sources"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_file_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_file_id"],
            ["source_files.tenant_id", "source_files.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("length(sha256) = 64"),
    )


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(120))
    schema_version: Mapped[str] = mapped_column(String(20), default="1.0")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["processing_jobs.tenant_id", "processing_jobs.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("job_id", "sequence"),
        UniqueConstraint("tenant_id", "id"),
        Index("job_events_stream_idx", "job_id", "sequence"),
        Index("job_events_retention_idx", "occurred_at", "id"),
    )


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    page_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    block_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    severity: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="open")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "page_id"], ["pages.tenant_id", "pages.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "block_id"],
            ["blocks.tenant_id", "blocks.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
    )


class KnowledgeNote(Base):
    __tablename__ = "knowledge_notes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    document_version: Mapped[int | None] = mapped_column(Integer)
    stable_key: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(200))
    note_type: Mapped[str] = mapped_column(String(60))
    content_markdown: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    evidence_block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    content_origin: Mapped[str] = mapped_column(String(40))
    review_status: Mapped[str] = mapped_column(String(30), default="unreviewed")
    compile_input_sha256: Mapped[str | None] = mapped_column(String(64))
    pipeline_schema_sha256: Mapped[str | None] = mapped_column(String(71))
    model_revision: Mapped[str | None] = mapped_column(String(64))
    compile_provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "stable_key",
            "document_version",
            "compile_input_sha256",
            "pipeline_schema_sha256",
            "model_revision",
            name="uq_knowledge_note_compile_revision",
        ),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("document_version IS NULL OR document_version >= 1"),
        Index(
            "knowledge_notes_active_document_idx",
            "tenant_id",
            "project_id",
            "document_id",
            "document_version",
            "stable_key",
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active = 1"),
        ),
        Index(
            "knowledge_notes_one_active_revision_idx",
            "tenant_id",
            "project_id",
            "document_id",
            "document_version",
            "stable_key",
            unique=True,
            postgresql_where=text("is_active AND document_id IS NOT NULL"),
            sqlite_where=text("is_active = 1 AND document_id IS NOT NULL"),
        ),
    )


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    stable_key: Mapped[str] = mapped_column(String(160))
    entity_type: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(500))
    evidence_block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "project_id", "stable_key"),
        UniqueConstraint("tenant_id", "id"),
    )


class Relation(Base):
    __tablename__ = "relations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    document_version: Mapped[int | None] = mapped_column(Integer)
    source_relation_key: Mapped[str | None] = mapped_column(String(256))
    subject_id: Mapped[str] = mapped_column(String(200))
    predicate: Mapped[str] = mapped_column(String(200))
    object_id: Mapped[str] = mapped_column(String(200))
    assertion_status: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float | None]
    evidence_block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String(30), default="pending")
    compile_input_sha256: Mapped[str | None] = mapped_column(String(64))
    pipeline_schema_sha256: Mapped[str | None] = mapped_column(String(71))
    model_revision: Mapped[str | None] = mapped_column(String(64))
    compile_provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "document_id",
            "source_relation_key",
            "document_version",
            "compile_input_sha256",
            "pipeline_schema_sha256",
            "model_revision",
            name="uq_relation_compile_revision",
        ),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("document_version IS NULL OR document_version >= 1"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)"),
        Index(
            "relations_active_document_idx",
            "tenant_id",
            "project_id",
            "document_id",
            "document_version",
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active = 1"),
        ),
        Index(
            "relations_one_active_revision_idx",
            "tenant_id",
            "project_id",
            "document_id",
            "document_version",
            "source_relation_key",
            unique=True,
            postgresql_where=text(
                "is_active AND document_id IS NOT NULL AND source_relation_key IS NOT NULL"
            ),
            sqlite_where=text(
                "is_active = 1 AND document_id IS NOT NULL AND source_relation_key IS NOT NULL"
            ),
        ),
    )


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    export_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    storage_key: Mapped[str | None] = mapped_column(String(500))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
    )


class CreditAccount(Base):
    __tablename__ = "credit_accounts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    reserved: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint("balance >= 0"),
        CheckConstraint("reserved >= 0"),
        CheckConstraint("reserved <= balance"),
    )


class CreditLedger(Base):
    __tablename__ = "credit_ledger"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("processing_jobs.id", ondelete="SET NULL"),
    )
    operation_key: Mapped[str] = mapped_column(String(200))
    entry_type: Mapped[str] = mapped_column(String(20))
    credits: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    reserved_after: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('grant','reserve','consume','release','refund','expire','adjust')"
        ),
        CheckConstraint("credits > 0"),
        UniqueConstraint("tenant_id", "operation_key"),
        UniqueConstraint("tenant_id", "id"),
    )


class Checkout(Base):
    """Provider-neutral, server-priced credit purchase intent."""

    __tablename__ = "payment_checkouts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    provider: Mapped[str] = mapped_column(String(40))
    provider_checkout_id: Mapped[str | None] = mapped_column(String(200))
    pack_code: Mapped[str] = mapped_column(String(80))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    credits: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    status: Mapped[str] = mapped_column(String(24), default="requested")
    checkout_url: Mapped[str | None] = mapped_column(String(2000))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint("amount_minor > 0"),
        CheckConstraint("credits > 0"),
        CheckConstraint("length(currency) = 3 AND currency = upper(currency)"),
        CheckConstraint(
            "status IN ('requested','provider_pending','open','completed','expired','cancelled')"
        ),
        UniqueConstraint("provider", "provider_checkout_id"),
        UniqueConstraint("tenant_id", "id"),
        Index("payment_checkouts_tenant_created_idx", "tenant_id", "created_at", "id"),
    )


class Payment(Base):
    """Canonical provider payment, independent from any provider SDK."""

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    checkout_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(40))
    provider_payment_id: Mapped[str] = mapped_column(String(200))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    credits: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "checkout_id"],
            ["payment_checkouts.tenant_id", "payment_checkouts.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount_minor > 0"),
        CheckConstraint("credits > 0"),
        CheckConstraint("length(currency) = 3 AND currency = upper(currency)"),
        CheckConstraint(
            "status IN "
            "('pending','succeeded','partially_refunded','refunded','disputed',"
            "'charged_back','failed','cancelled')"
        ),
        UniqueConstraint("provider", "provider_payment_id"),
        UniqueConstraint("tenant_id", "checkout_id"),
        UniqueConstraint("tenant_id", "id"),
        Index("payments_tenant_created_idx", "tenant_id", "created_at", "id"),
    )


class PaymentEvent(Base):
    """Durable signed-webhook inbox with provider-event replay protection."""

    __tablename__ = "payment_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT")
    )
    provider: Mapped[str] = mapped_column(String(40))
    provider_event_id: Mapped[str] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(80))
    provider_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column("payload", JSON)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint("length(payload_sha256) = 64"),
        CheckConstraint("attempts >= 0"),
        CheckConstraint("status IN ('pending','retry','processed','ignored','dead_letter')"),
        UniqueConstraint("provider", "provider_event_id"),
        UniqueConstraint("tenant_id", "id"),
        Index(
            "payment_events_due_idx",
            "next_attempt_at",
            "received_at",
            "id",
            postgresql_where=text("status IN ('pending','retry')"),
            sqlite_where=text("status IN ('pending','retry')"),
        ),
        Index("payment_events_tenant_received_idx", "tenant_id", "received_at", "id"),
    )


class CreditGrant(Base):
    """Immutable evidence connecting a settled payment to one ledger grant."""

    __tablename__ = "credit_grants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    credit_ledger_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    operation_key: Mapped[str] = mapped_column(String(200))
    credits: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["payments.tenant_id", "payments.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "credit_ledger_id"],
            ["credit_ledger.tenant_id", "credit_ledger.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("credits > 0"),
        UniqueConstraint("tenant_id", "payment_id"),
        UniqueConstraint("tenant_id", "credit_ledger_id"),
        UniqueConstraint("tenant_id", "operation_key"),
        UniqueConstraint("tenant_id", "id"),
    )


class Refund(Base):
    """Provider refund evidence; credit recovery is recorded separately."""

    __tablename__ = "payment_refunds"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    payment_event_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(40))
    provider_refund_id: Mapped[str] = mapped_column(String(200))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="succeeded")
    credits_requested: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    credit_adjusted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["payments.tenant_id", "payments.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "payment_event_id"],
            ["payment_events.tenant_id", "payment_events.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount_minor > 0"),
        CheckConstraint("credits_requested >= 0"),
        CheckConstraint("length(currency) = 3 AND currency = upper(currency)"),
        CheckConstraint("status IN ('pending','succeeded','failed')"),
        UniqueConstraint("provider", "provider_refund_id"),
        UniqueConstraint("tenant_id", "payment_event_id"),
        UniqueConstraint("tenant_id", "id"),
    )


class Dispute(Base):
    """Mutable provider dispute state backed by immutable reversal evidence."""

    __tablename__ = "payment_disputes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(40))
    provider_dispute_id: Mapped[str] = mapped_column(String(200))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="open")
    requested_credits: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    held_credits: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    reversed_credits: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    outstanding_credits: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["payments.tenant_id", "payments.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount_minor > 0"),
        CheckConstraint(
            "requested_credits >= 0 AND held_credits >= 0 "
            "AND reversed_credits >= 0 AND outstanding_credits >= 0"
        ),
        CheckConstraint("length(currency) = 3 AND currency = upper(currency)"),
        CheckConstraint("status IN ('open','won','lost','closed')"),
        UniqueConstraint("provider", "provider_dispute_id"),
        UniqueConstraint("tenant_id", "id"),
    )


class Reversal(Base):
    """Append-only credit hold, release, clawback, and debt-recovery evidence."""

    __tablename__ = "credit_reversals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    refund_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    dispute_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    payment_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    credit_ledger_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    operation_key: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(24))
    requested_credits: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    applied_credits: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    unrecovered_after: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["payments.tenant_id", "payments.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "refund_id"],
            ["payment_refunds.tenant_id", "payment_refunds.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "dispute_id"],
            ["payment_disputes.tenant_id", "payment_disputes.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "payment_event_id"],
            ["payment_events.tenant_id", "payment_events.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "credit_ledger_id"],
            ["credit_ledger.tenant_id", "credit_ledger.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "requested_credits >= 0 AND applied_credits >= 0 AND unrecovered_after >= 0"
        ),
        CheckConstraint("action IN ('refund','hold','unhold','chargeback','debt_recovery')"),
        CheckConstraint(
            "(refund_id IS NOT NULL AND dispute_id IS NULL) "
            "OR (refund_id IS NULL AND dispute_id IS NOT NULL)"
        ),
        UniqueConstraint("tenant_id", "operation_key"),
        UniqueConstraint("tenant_id", "id"),
        Index("credit_reversals_payment_idx", "tenant_id", "payment_id", "created_at"),
    )


class Reconciliation(Base):
    """Tenant-scoped evidence for a bounded payment reconciliation pass."""

    __tablename__ = "payment_reconciliations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT")
    )
    provider: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="running")
    events_scanned: Mapped[int] = mapped_column(Integer, default=0)
    events_processed: Mapped[int] = mapped_column(Integer, default=0)
    events_retried: Mapped[int] = mapped_column(Integer, default=0)
    events_dead_lettered: Mapped[int] = mapped_column(Integer, default=0)
    mismatches: Mapped[int] = mapped_column(Integer, default=0)
    repaired: Mapped[int] = mapped_column(Integer, default=0)
    outstanding_credits: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "events_scanned >= 0 AND events_processed >= 0 "
            "AND events_retried >= 0 AND events_dead_lettered >= 0 "
            "AND mismatches >= 0 AND repaired >= 0 AND outstanding_credits >= 0"
        ),
        CheckConstraint("status IN ('running','completed','failed')"),
        UniqueConstraint("tenant_id", "id"),
        Index(
            "payment_reconciliations_tenant_started_idx",
            "tenant_id",
            "started_at",
            "id",
        ),
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(String(240))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    response_body_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    state: Mapped[str] = mapped_column(String(20), default="started")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "endpoint", "idempotency_key"),
        CheckConstraint("state IN ('started','completed','failed')"),
        UniqueConstraint("tenant_id", "id"),
        Index("idempotency_records_expiry_idx", "expires_at", "id"),
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"))
    aggregate_type: Mapped[str] = mapped_column(String(60))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        Index(
            "outbox_pending_idx",
            "available_at",
            "created_at",
            "id",
            postgresql_where=text(
                "published_at IS NULL AND event_type IN "
                "('job.completed.v1','job.failed.v1','export.completed.v1')"
            ),
            sqlite_where=text(
                "published_at IS NULL AND event_type IN "
                "('job.completed.v1','job.failed.v1','export.completed.v1')"
            ),
        ),
        Index(
            "outbox_dispatch_pending_idx",
            "available_at",
            "created_at",
            "id",
            postgresql_where=text(
                "published_at IS NULL AND dead_lettered_at IS NULL "
                "AND event_type = 'job.dispatch.requested.v1'"
            ),
            sqlite_where=text(
                "published_at IS NULL AND dead_lettered_at IS NULL "
                "AND event_type = 'job.dispatch.requested.v1'"
            ),
        ),
        Index(
            "outbox_analysis_pending_idx",
            "available_at",
            "created_at",
            "id",
            postgresql_where=text(
                "published_at IS NULL AND dead_lettered_at IS NULL "
                "AND event_type = 'document.analysis.requested.v1'"
            ),
            sqlite_where=text(
                "published_at IS NULL AND dead_lettered_at IS NULL "
                "AND event_type = 'document.analysis.requested.v1'"
            ),
        ),
        Index(
            "outbox_deletion_pending_idx",
            "available_at",
            "created_at",
            "id",
            postgresql_where=text(
                "published_at IS NULL AND dead_lettered_at IS NULL "
                "AND event_type IN "
                "('deletion.purge.requested.v1','deletion.retry.requested.v1')"
            ),
            sqlite_where=text(
                "published_at IS NULL AND dead_lettered_at IS NULL "
                "AND event_type IN "
                "('deletion.purge.requested.v1','deletion.retry.requested.v1')"
            ),
        ),
        Index(
            "outbox_dead_retention_idx",
            "dead_lettered_at",
            "id",
            postgresql_where=text("dead_lettered_at IS NOT NULL"),
            sqlite_where=text("dead_lettered_at IS NOT NULL"),
        ),
        Index(
            "outbox_published_retention_idx",
            "published_at",
            "id",
            postgresql_where=text("published_at IS NOT NULL"),
            sqlite_where=text("published_at IS NOT NULL"),
        ),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(120))
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str] = mapped_column(String(200))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "id"),)


class DeletionReceipt(Base):
    __tablename__ = "deletion_receipts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT")
    )
    target_type: Mapped[str] = mapped_column(String(80))
    target_id_hash: Mapped[str] = mapped_column(String(64))
    manifest_hash: Mapped[str] = mapped_column(String(64))
    deleted_count: Mapped[int] = mapped_column(Integer)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint("deleted_count >= 0"),
        UniqueConstraint("tenant_id", "id"),
    )


class DeletionRequest(Base):
    """Durable tombstone and immutable purge manifest.

    ``manifest`` is written once by the API (or by the legacy-event bridge)
    and is never changed by the purge worker. Mutable progress lives in this
    row's explicit state fields and in ``deletion_objects``.
    """

    __tablename__ = "deletion_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT")
    )
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    target_id_hash: Mapped[str] = mapped_column(String(64))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(String(24), default="requested")
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    manifest_hash: Mapped[str] = mapped_column(String(64))
    object_count: Mapped[int] = mapped_column(Integer, default=0)
    deleted_count: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("target_type IN ('document','project')"),
        CheckConstraint("state IN ('requested','purging','retry','purged','dead_letter')"),
        CheckConstraint("object_count >= 0"),
        CheckConstraint("deleted_count >= 0"),
        CheckConstraint("attempts >= 0"),
        CheckConstraint("deleted_count <= object_count"),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(
            "tenant_id",
            "target_type",
            "target_id",
            name="uq_deletion_requests_target",
        ),
        Index(
            "deletion_requests_pending_idx",
            "state",
            "lease_expires_at",
            "requested_at",
            "id",
        ),
    )


class DeletionObject(Base):
    """Per-object purge progress; object keys are never exposed or logged."""

    __tablename__ = "deletion_objects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    deletion_request_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    operation: Mapped[str] = mapped_column(String(24), default="delete")
    bucket: Mapped[str] = mapped_column(String(24))
    object_key: Mapped[str] = mapped_column(String(500))
    object_key_hash: Mapped[str] = mapped_column(String(64))
    provider_upload_id: Mapped[str | None] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "deletion_request_id"],
            ["deletion_requests.tenant_id", "deletion_requests.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("operation IN ('delete','abort_multipart')"),
        CheckConstraint("bucket IN ('quarantine','source','working','derived','exports','audit')"),
        CheckConstraint("state IN ('pending','purged')"),
        CheckConstraint("attempts >= 0"),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(
            "deletion_request_id",
            "operation",
            "bucket",
            "object_key",
            name="uq_deletion_objects_manifest_entry",
        ),
        Index(
            "deletion_objects_pending_idx",
            "deletion_request_id",
            "state",
            "id",
        ),
    )


class DeletionAttempt(Base):
    """Append-only, PII-free evidence for every purge attempt."""

    __tablename__ = "deletion_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    deletion_request_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attempt_number: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(24), default="started")
    failure_hashes: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "deletion_request_id"],
            ["deletion_requests.tenant_id", "deletion_requests.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("attempt_number >= 1"),
        CheckConstraint("outcome IN ('started','retry','purged','dead_letter')"),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(
            "deletion_request_id",
            "attempt_number",
            name="uq_deletion_attempt_number",
        ),
    )


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(2000))
    secret_hash: Mapped[str] = mapped_column(String(64))
    encrypted_secret: Mapped[str] = mapped_column(Text)
    event_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "id"),)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(String(500))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "endpoint_id"],
            ["webhook_endpoints.tenant_id", "webhook_endpoints.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        Index(
            "webhook_deliveries_due_idx",
            "next_attempt_at",
            "id",
            postgresql_where=text("status IN ('pending','retry')"),
            sqlite_where=text("status IN ('pending','retry')"),
        ),
        Index(
            "webhook_deliveries_dead_retention_idx",
            "dead_lettered_at",
            "id",
            postgresql_where=text("status = 'dead_letter'"),
            sqlite_where=text("status = 'dead_letter'"),
        ),
        Index(
            "webhook_deliveries_delivered_retention_idx",
            "delivered_at",
            "id",
            postgresql_where=text("status = 'delivered'"),
            sqlite_where=text("status = 'delivered'"),
        ),
    )


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rollout_percent: Mapped[int] = mapped_column(Integer, default=0)
    conditions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "key"),
        CheckConstraint("rollout_percent BETWEEN 0 AND 100"),
    )


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    endpoint: Mapped[str] = mapped_column(String(120))
    model_id: Mapped[str] = mapped_column(String(240))
    revision: Mapped[str] = mapped_column(String(200))
    runtime_image_digest: Mapped[str] = mapped_column(String(200))
    adapter_version: Mapped[str] = mapped_column(String(120))
    policy_version: Mapped[str] = mapped_column(String(120))
    benchmark_report: Mapped[str] = mapped_column(String(240))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    canary_percent: Mapped[int] = mapped_column(Integer, default=0)
    lifecycle_state: Mapped[str] = mapped_column(String(24), default="candidate")
    generation: Mapped[int] = mapped_column(Integer, default=1)
    promoted_from_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("model_registry.id", ondelete="SET NULL"),
    )
    benchmark_sha256: Mapped[str | None] = mapped_column(String(71))
    recipe_sha256: Mapped[str | None] = mapped_column(String(71))
    approval_ref: Mapped[str | None] = mapped_column(String(160))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    __table_args__ = (
        UniqueConstraint("endpoint", "revision"),
        CheckConstraint("canary_percent BETWEEN 0 AND 100"),
        CheckConstraint("generation >= 1"),
        CheckConstraint("lifecycle_state IN ('candidate','champion','fallback','retired')"),
    )


class TrialSession(Base):
    """An anonymous visitor's one-shot preflight — ADR-006.

    Owned by the reserved system trial tenant seeded in migration 0023, so the
    tenant-scoping invariant in CONTRIBUTING.md holds without exception and the
    row-level policy on this table is the same shape as every other tenant
    table. There is no user: the session identifier is the only credential, it
    grants read access to exactly one project, and it stops existing at
    ``expires_at``.

    ``client_subject`` is the pseudonym the existing IdentityHasher produces,
    never a raw address, so this row and the rate limiter agree on who a caller
    is without either of them storing an IP.
    """

    __tablename__ = "trial_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    client_subject: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Set when a visitor signs up inside the window and the session is moved
    # into their tenant. Adoption re-runs authorization; it does not relocate
    # objects across tenant prefixes.
    adopted_tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("project_id"),
        CheckConstraint("expires_at > created_at", name="trial_sessions_ttl_forward"),
        Index(
            "trial_sessions_expiry_idx",
            "expires_at",
            postgresql_where=text("deletion_requested_at IS NULL"),
        ),
        Index("trial_sessions_client_idx", "client_subject", "created_at"),
    )
